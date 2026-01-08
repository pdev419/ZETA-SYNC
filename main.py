from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from node.agent.discovery import Discovery, parse_hostport
from node.constants import ENV_FILE, EVENTS_LOG, LOG_DIR, METRICS_LOG, PROJECT_ROOT
from node.peer.client import send_message
from node.peer.server import PeerServer
from node.storage.jsonl import append_jsonl, has_min_disk_free, tail_jsonl
from node.storage.node_id import load_or_create_node_id
from node.storage.paths import ensure_dirs
from node.sync.metrics_reader import parse_metrics_line
from node.sync.process_manager import ZetaSyncProcess


TEMPLATES_DIR = PROJECT_ROOT / "apps" / "web" / "templates"
STATIC_DIR = PROJECT_ROOT / "apps" / "web" / "static"


# -------------------------
# ENV helpers
# -------------------------
def env_str(key: str, default: str) -> str:
    v = os.getenv(key)
    return default if v is None or v.strip() == "" else v.strip()


def env_int(key: str, default: int) -> int:
    v = os.getenv(key)
    return default if v is None or v.strip() == "" else int(v.strip())


def env_float(key: str, default: float) -> float:
    v = os.getenv(key)
    return default if v is None or v.strip() == "" else float(v.strip())


def parse_csv_seeds(raw: str) -> List[str]:
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(",")]
    return [p for p in parts if p and ":" in p]


# -------------------------
# Settings
# -------------------------
@dataclass(frozen=True)
class Settings:
    http_host: str
    http_port: int
    peer_host: str
    peer_port: int
    seeds: List[str]
    gossip_interval_sec: float
    zeta_sync_cmd: str
    zeta_sync_args: List[str]
    zeta_sync_workdir: str


def load_settings() -> Settings:
    return Settings(
        http_host=env_str("HTTP_HOST", "0.0.0.0"),
        http_port=env_int("HTTP_PORT", 8080),
        peer_host=env_str("PEER_HOST", "0.0.0.0"),
        peer_port=env_int("PEER_PORT", 9443),
        seeds=parse_csv_seeds(env_str("SEEDS", "")),
        gossip_interval_sec=env_float("GOSSIP_INTERVAL_SEC", 2.0),
        zeta_sync_cmd=env_str("ZETA_SYNC_CMD", "./bin/zeta-sync"),
        zeta_sync_args=[a for a in env_str("ZETA_SYNC_ARGS", "").split() if a.strip()],
        zeta_sync_workdir=env_str("ZETA_SYNC_WORKDIR", "./data/state"),
    )


# -------------------------
# Runtime State
# -------------------------
@dataclass
class NodeRuntime:
    node_id: str
    settings: Settings
    discovery: Discovery

    # metrics stored by canonical node_id
    metrics_by_node: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # maps peer address -> node_id (learned via HELLO / METRICS_PUSH)
    peer_addr_to_node_id: Dict[str, str] = field(default_factory=dict)

    # reverse lookup node_id -> last known addr
    node_id_to_peer_addr: Dict[str, str] = field(default_factory=dict)

    excluded_nodes: Set[str] = field(default_factory=set)

    local_seq: int = 0
    zeta_proc: Optional[ZetaSyncProcess] = None

    def next_seq(self) -> int:
        self.local_seq += 1
        return self.local_seq

    def log_event(self, event_type: str, severity: str = "INFO", **extra: Any) -> None:
        if not has_min_disk_free(LOG_DIR):
            return
        append_jsonl(
            EVENTS_LOG,
            {
                "node_id": self.node_id,
                "sequence_id": self.next_seq(),
                "event_type": event_type,
                "severity": severity,
                **extra,
            },
        )

    def _resolve_cmd_workdir(self) -> tuple[str, str]:
        cmd0 = self.settings.zeta_sync_cmd
        workdir0 = self.settings.zeta_sync_workdir
        if not os.path.isabs(cmd0):
            cmd0 = str((PROJECT_ROOT / cmd0).resolve())
        if not os.path.isabs(workdir0):
            workdir0 = str((PROJECT_ROOT / workdir0).resolve())
        return cmd0, workdir0

    async def start_sync(self) -> None:
        if self.zeta_proc is None:
            cmd0, workdir0 = self._resolve_cmd_workdir()
            cmd = [cmd0] + self.settings.zeta_sync_args
            self.zeta_proc = ZetaSyncProcess(cmd=cmd, workdir=workdir0)

        try:
            await self.zeta_proc.start()
        except FileNotFoundError as e:
            self.log_event("SYNC_START_FAILED", severity="ERROR", reason="FILE_NOT_FOUND", detail=str(e))
            raise RuntimeError(
                f"ZETA_SYNC_CMD not found. Check .env ZETA_SYNC_CMD='{self.settings.zeta_sync_cmd}'."
            ) from e
        except PermissionError as e:
            self.log_event("SYNC_START_FAILED", severity="ERROR", reason="PERMISSION_DENIED", detail=str(e))
            raise RuntimeError(
                f"ZETA_SYNC_CMD not executable. Run chmod +x '{self.settings.zeta_sync_cmd}'."
            ) from e

        self.log_event("SYNC_STARTED", cmd=[self.settings.zeta_sync_cmd] + self.settings.zeta_sync_args)

    async def stop_sync(self) -> None:
        if self.zeta_proc:
            await self.zeta_proc.stop()
        self.log_event("SYNC_STOPPED")

    def learn_peer_identity(self, peer_addr: str, node_id: str) -> None:
        if not peer_addr or not node_id:
            return
        self.peer_addr_to_node_id[peer_addr] = node_id
        self.node_id_to_peer_addr[node_id] = peer_addr

    def upsert_peer_metrics(self, node_id: str, metrics: Dict[str, Any]) -> None:
        if not node_id or not isinstance(metrics, dict):
            return
        self.metrics_by_node[node_id] = metrics

    def cluster_status(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "known_peers": sorted(self.discovery.known_peers),
            "peer_addr_to_node_id": dict(self.peer_addr_to_node_id),
            "excluded_nodes": sorted(self.excluded_nodes),
            "seeds": self.settings.seeds,
        }

    def nodes_view(self) -> Dict[str, Any]:
        # Always include self
        nodes: List[Dict[str, Any]] = []
        nodes.append({
            "node_id": self.node_id,
            "peer_addr": self.node_id_to_peer_addr.get(self.node_id),
            "metrics": self.metrics_by_node.get(self.node_id, {}),
            "excluded": self.node_id in self.excluded_nodes,
        })

        # Include known peers (canonical by node_id if available)
        seen: Set[str] = {self.node_id}

        for peer_addr in sorted(self.discovery.known_peers):
            nid = self.peer_addr_to_node_id.get(peer_addr)
            if nid:
                if nid in seen:
                    continue
                seen.add(nid)
                nodes.append({
                    "node_id": nid,
                    "peer_addr": peer_addr,
                    "metrics": self.metrics_by_node.get(nid, {}),
                    "excluded": nid in self.excluded_nodes,
                })
            else:
                # Unknown identity yet (before HELLO/METRICS arrives)
                nodes.append({
                    "node_id": None,
                    "peer_addr": peer_addr,
                    "metrics": {},
                    "excluded": False,
                })

        return {"nodes": nodes}


# -------------------------
# Peer handler
# -------------------------
async def peer_handler(ctx: NodeRuntime, msg: dict, peer_id: str) -> dict:
    t = msg.get("type")

    if t == "PING":
        return {"type": "PONG", "from": ctx.node_id}

    if t == "HELLO":
        # peer_id here is remote tcp addr:port, not the peer listen addr
        # we learn listen addr and (optionally) node_id if provided
        peer_listen = msg.get("listen")
        peer_node_id = msg.get("node_id")

        if isinstance(peer_listen, str) and ":" in peer_listen:
            ctx.discovery.merge([peer_listen])

        if isinstance(peer_listen, str) and isinstance(peer_node_id, str):
            ctx.learn_peer_identity(peer_listen, peer_node_id)

        return {
            "type": "HELLO_ACK",
            "from": ctx.node_id,
            "peers": sorted(ctx.discovery.known_peers),
        }

    if t == "PEER_LIST_REQ":
        return {"type": "PEER_LIST", "peers": sorted(ctx.discovery.known_peers)}

    if t == "GOSSIP":
        peers = msg.get("peers", [])
        if isinstance(peers, list):
            ctx.discovery.merge([p for p in peers if isinstance(p, str)])
        return {"type": "GOSSIP_ACK", "peers": sorted(ctx.discovery.known_peers)}

    if t == "METRICS_PUSH":
        metrics = msg.get("metrics", {})
        sender = msg.get("sender")
        peer_listen = msg.get("listen")  # optional

        if isinstance(sender, str) and isinstance(metrics, dict):
            ctx.upsert_peer_metrics(sender, metrics)

        if isinstance(peer_listen, str) and isinstance(sender, str):
            ctx.learn_peer_identity(peer_listen, sender)

        return {"type": "METRICS_ACK"}

    return {"type": "ERROR", "reason": f"Unknown type {t}"}


# -------------------------
# Loops
# -------------------------
async def discovery_loop(ctx: NodeRuntime) -> None:
    listen = f"{ctx.settings.peer_host}:{ctx.settings.peer_port}"
    ctx.log_event("DISCOVERY_STARTED", listen=listen, seeds=ctx.settings.seeds)

    while True:
        # Seed bootstrap
        for seed in list(ctx.settings.seeds):
            try:
                host, port = parse_hostport(seed)
                resp = await send_message(host, port, {"type": "PEER_LIST_REQ"})
                peers = resp.get("peers", [])
                if isinstance(peers, list):
                    ctx.discovery.merge([p for p in peers if isinstance(p, str)])

                # Send HELLO with our node_id + listen addr
                await send_message(host, port, {"type": "HELLO", "listen": listen, "node_id": ctx.node_id})
            except Exception:
                continue

        # Gossip
        targets = ctx.discovery.pick_targets(k=2)
        payload = {"type": "GOSSIP", "peers": sorted(ctx.discovery.known_peers)}
        for tgt in targets:
            try:
                host, port = parse_hostport(tgt)
                resp = await send_message(host, port, payload)
                peers = resp.get("peers", [])
                if isinstance(peers, list):
                    ctx.discovery.merge([p for p in peers if isinstance(p, str)])

                # Also HELLO to learn identity mapping sooner
                await send_message(host, port, {"type": "HELLO", "listen": listen, "node_id": ctx.node_id})
            except Exception:
                continue

        await asyncio.sleep(ctx.settings.gossip_interval_sec)


async def metrics_loop(ctx: NodeRuntime) -> None:
    while True:
        if not ctx.zeta_proc:
            await asyncio.sleep(1)
            continue

        st = ctx.zeta_proc.status()
        if not st.running:
            await asyncio.sleep(1)
            continue

        async for line in ctx.zeta_proc.stdout_lines():
            parsed = parse_metrics_line(line)
            if parsed:
                ctx.upsert_peer_metrics(ctx.node_id, parsed)
                if has_min_disk_free(LOG_DIR):
                    append_jsonl(
                        METRICS_LOG,
                        {
                            "node_id": ctx.node_id,
                            "sequence_id": ctx.next_seq(),
                            "metrics": parsed,
                        },
                    )

        await asyncio.sleep(0.2)


async def metrics_push_loop(ctx: NodeRuntime) -> None:
    listen = f"{ctx.settings.peer_host}:{ctx.settings.peer_port}"

    while True:
        await asyncio.sleep(1.0)

        local = ctx.metrics_by_node.get(ctx.node_id)
        if not local:
            continue

        for peer in list(ctx.discovery.known_peers):
            try:
                host, port = parse_hostport(peer)
                await send_message(
                    host,
                    port,
                    {
                        "type": "METRICS_PUSH",
                        "sender": ctx.node_id,
                        "listen": listen,
                        "metrics": local,
                    },
                    timeout=2.0,
                )
            except Exception:
                continue


# -------------------------
# App
# -------------------------
def create_app() -> FastAPI:
    load_dotenv(dotenv_path=str(ENV_FILE), override=True)
    ensure_dirs()

    settings = load_settings()
    node_id = load_or_create_node_id()

    ctx = NodeRuntime(
        node_id=node_id,
        settings=settings,
        discovery=Discovery(settings.seeds),
        metrics_by_node={node_id: {}},
    )
    ctx.log_event("NODE_BOOTED", seeds=settings.seeds)

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        peer_server = PeerServer(
            host=settings.peer_host,
            port=settings.peer_port,
            handler=lambda msg, peer: peer_handler(ctx, msg, peer),
            ssl=None,
        )
        await peer_server.start()
        ctx.log_event("PEER_SERVER_STARTED", host=settings.peer_host, port=settings.peer_port)

        t1 = asyncio.create_task(discovery_loop(ctx))
        t2 = asyncio.create_task(metrics_loop(ctx))
        t3 = asyncio.create_task(metrics_push_loop(ctx))

        try:
            yield
        finally:
            t1.cancel()
            t2.cancel()
            t3.cancel()
            await peer_server.stop()
            ctx.log_event("NODE_STOPPED")

    app = FastAPI(title="ZETA-SYNC Cluster (M1+M2)", lifespan=lifespan)
    app.state.ctx = ctx

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # UI
    @app.get("/", response_class=HTMLResponse)
    async def ui_index(request: Request):
        return templates.TemplateResponse("index.html", {"request": request})

    @app.get("/nodes", response_class=HTMLResponse)
    async def ui_nodes(request: Request):
        return templates.TemplateResponse("nodes.html", {"request": request})

    @app.get("/events", response_class=HTMLResponse)
    async def ui_events(request: Request):
        return templates.TemplateResponse("events.html", {"request": request})

    # Mgmt
    @app.post("/mgmt/cluster/start")
    async def mgmt_start():
        try:
            await app.state.ctx.start_sync()
            return {"ok": True}
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/mgmt/cluster/stop")
    async def mgmt_stop():
        await app.state.ctx.stop_sync()
        return {"ok": True}

    # API v1
    @app.get("/api/v1/health")
    async def api_health():
        return {"ok": True}

    @app.get("/api/v1/cluster/status")
    async def api_cluster_status():
        return app.state.ctx.cluster_status()

    @app.get("/api/v1/nodes")
    async def api_nodes():
        return app.state.ctx.nodes_view()

    @app.get("/api/v1/cluster/events")
    async def api_events():
        return {"events": tail_jsonl(EVENTS_LOG, limit=200)}

    @app.get("/api/v1/debug/env")
    async def api_debug_env():
        c = app.state.ctx
        return {
            "HTTP_HOST": c.settings.http_host,
            "HTTP_PORT": c.settings.http_port,
            "PEER_HOST": c.settings.peer_host,
            "PEER_PORT": c.settings.peer_port,
            "SEEDS": c.settings.seeds,
            "GOSSIP_INTERVAL_SEC": c.settings.gossip_interval_sec,
            "ZETA_SYNC_CMD": c.settings.zeta_sync_cmd,
            "ZETA_SYNC_ARGS": c.settings.zeta_sync_args,
            "ZETA_SYNC_WORKDIR": c.settings.zeta_sync_workdir,
        }

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=app.state.ctx.settings.http_host,
        port=app.state.ctx.settings.http_port,
        log_level="info",
    )
