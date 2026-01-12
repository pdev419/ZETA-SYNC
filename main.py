from __future__ import annotations

import asyncio
import os
import secrets
import socket
import ssl
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from node.agent.discovery import Discovery, parse_hostport
from node.constants import ENV_FILE, EVENTS_LOG, LOG_DIR, METRICS_LOG, PROJECT_ROOT
from node.peer.client import send_message
from node.peer.server import PeerServer
from node.peer.tls import TLSPaths, build_client_ssl_context, build_server_ssl_context
from node.security.ca import (
    CAPaths,
    ensure_cluster_ca,
    issue_node_cert,
    load_ca,
    sha256_fingerprint_from_cert_pem,
    sign_csr,
)
from node.security.store import SecurityStore
from node.storage.jsonl import append_jsonl, has_min_disk_free, tail_jsonl
from node.storage.node_id import load_or_create_node_id
from node.storage.paths import ensure_dirs
from node.sync.metrics_reader import parse_metrics_line
from node.sync.process_manager import ZetaSyncProcess


TEMPLATES_DIR = PROJECT_ROOT / "apps" / "web" / "templates"
STATIC_DIR = PROJECT_ROOT / "apps" / "web" / "static"

# --- Internal persistence paths ---
SECURITY_JSON = PROJECT_ROOT / "data" / "state" / "security" / "security.json"
TLS_DIR = PROJECT_ROOT / "data" / "state" / "tls"
CA_KEY = TLS_DIR / "ca.key"
CA_CERT = TLS_DIR / "ca.crt"
NODE_KEY = TLS_DIR / "node.key"
NODE_CERT = TLS_DIR / "node.crt"


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


def split_hostport(addr: str) -> Tuple[str, int]:
    host, port = parse_hostport(addr)
    return host, int(port)


def detect_lan_ip() -> Optional[str]:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return None


def _cn_from_peer_cert(peer_cert: dict | None) -> Optional[str]:
    # ssl.getpeercert() dict: {'subject': ((('commonName','node-xxx'),), ...), ...}
    if not peer_cert:
        return None
    try:
        subject = peer_cert.get("subject", [])
        for tup in subject:
            for k, v in tup:
                if k == "commonName":
                    return v
    except Exception:
        return None
    return None


@dataclass(frozen=True)
class Settings:
    http_host: str
    http_port: int
    peer_host: str
    peer_port: int
    peer_advertise_host: str
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
        peer_advertise_host=env_str("PEER_ADVERTISE_HOST", ""),
        seeds=parse_csv_seeds(env_str("SEEDS", "")),
        gossip_interval_sec=env_float("GOSSIP_INTERVAL_SEC", 2.0),
        zeta_sync_cmd=env_str("ZETA_SYNC_CMD", "./bin/zeta-sync"),
        zeta_sync_args=[a for a in env_str("ZETA_SYNC_ARGS", "").split() if a.strip()],
        zeta_sync_workdir=env_str("ZETA_SYNC_WORKDIR", "./data/state"),
    )


@dataclass
class NodeRuntime:
    node_id: str
    settings: Settings
    discovery: Discovery
    self_advertise_addr: str

    metrics_by_node: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    peer_addr_to_node_id: Dict[str, str] = field(default_factory=dict)
    node_id_to_peer_addr: Dict[str, str] = field(default_factory=dict)

    excluded_nodes: Set[str] = field(default_factory=set)
    local_seq: int = 0
    zeta_proc: Optional[ZetaSyncProcess] = None

    def advertise_addr(self) -> str:
        return self.self_advertise_addr

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
            raise RuntimeError(f"ZETA_SYNC_CMD not found. Check .env ZETA_SYNC_CMD='{self.settings.zeta_sync_cmd}'.") from e
        except PermissionError as e:
            self.log_event("SYNC_START_FAILED", severity="ERROR", reason="PERMISSION_DENIED", detail=str(e))
            raise RuntimeError(f"ZETA_SYNC_CMD not executable. chmod +x '{self.settings.zeta_sync_cmd}'.") from e

        self.log_event("SYNC_STARTED", cmd=[self.settings.zeta_sync_cmd] + self.settings.zeta_sync_args)

    async def stop_sync(self) -> None:
        if self.zeta_proc:
            await self.zeta_proc.stop()
        self.log_event("SYNC_STOPPED")

    def learn_peer_identity(self, peer_addr: str, node_id: str) -> None:
        if not peer_addr or not node_id:
            return
        if node_id == self.node_id:
            return
        self.peer_addr_to_node_id[peer_addr] = node_id
        self.node_id_to_peer_addr[node_id] = peer_addr

    def upsert_peer_metrics(self, node_id: str, metrics: Dict[str, Any]) -> None:
        if not node_id or not isinstance(metrics, dict):
            return
        self.metrics_by_node[node_id] = metrics

    def nodes_view(self, include_unknown: bool = False) -> Dict[str, Any]:
        nodes: List[Dict[str, Any]] = []
        nodes.append({
            "node_id": self.node_id,
            "peer_addr": self.advertise_addr(),
            "metrics": self.metrics_by_node.get(self.node_id, {}),
            "excluded": self.node_id in self.excluded_nodes,
        })

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
                if include_unknown:
                    nodes.append({"node_id": None, "peer_addr": peer_addr, "metrics": {}, "excluded": False})
        return {"nodes": nodes}

    def cluster_status(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "advertise_addr": self.advertise_addr(),
            "known_peers": sorted(self.discovery.known_peers),
        }


# --- Simple admin auth for mgmt ---
security_basic = HTTPBasic()

def require_admin(creds: HTTPBasicCredentials = Depends(security_basic)):
    user = os.getenv("ADMIN_USER", "admin")
    pw = os.getenv("ADMIN_PASS", "admin123")
    ok_user = secrets.compare_digest(creds.username, user)
    ok_pw = secrets.compare_digest(creds.password, pw)
    if not (ok_user and ok_pw):
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})
    return True


async def peer_handler(ctx: NodeRuntime, msg: dict, meta: dict, app: FastAPI) -> dict:
    t = msg.get("type")

    tls_enabled = bool(app.state.tls_enabled)
    require_allow = bool(app.state.tls_require_allow)
    store: SecurityStore = app.state.security_store

    peer_cert = meta.get("peer_cert") if isinstance(meta, dict) else None
    peer_node_id = _cn_from_peer_cert(peer_cert) if tls_enabled else None

    # Enforce mTLS + allowlist/blocklist
    if tls_enabled:
        if not peer_node_id:
            ctx.log_event("SECURITY_AUTH_FAILED", severity="ERROR", reason="no_peer_cert", peer=meta.get("peer_id"))
            return {"type": "ERROR", "reason": "mTLS_required"}

        if store.is_blocked(peer_node_id):
            ctx.log_event("SECURITY_AUTH_FAILED", severity="ERROR", reason="blocklisted", node_id=peer_node_id)
            return {"type": "ERROR", "reason": "blocklisted"}

        if require_allow and (not store.is_allowed(peer_node_id)):
            now = time.time()
            fp_key = f"cn:{peer_node_id}"
            rec = store.load()
            last = float(rec.pending.get(fp_key, {}).get("last_seen", 0))
            if now - last >= float(app.state.tls_join_throttle):
                store.upsert_pending(
                    fp_key,
                    {
                        "node_id": peer_node_id,
                        "peer": meta.get("peer_id"),
                        "peer_cert_subject": peer_cert.get("subject") if isinstance(peer_cert, dict) else None,
                        "first_seen": rec.pending.get(fp_key, {}).get("first_seen", now),
                        "last_seen": now,
                    },
                )
                ctx.log_event("NODE_JOIN_REQUESTED", reason_code="not_allowlisted", node_id=peer_node_id)
            return {"type": "ERROR", "reason": "pending_approval"}

    # Normal peer messages
    if t == "PING":
        return {"type": "PONG", "from": ctx.node_id}

    if t == "HELLO":
        peer_listen = msg.get("listen")
        if isinstance(peer_listen, str) and ":" in peer_listen:
            ctx.discovery.merge([peer_listen])
            if tls_enabled and peer_node_id:
                ctx.learn_peer_identity(peer_listen, peer_node_id)

        return {"type": "HELLO_ACK", "from": ctx.node_id, "peers": sorted(ctx.discovery.known_peers)}

    if t == "PEER_LIST_REQ":
        return {"type": "PEER_LIST", "peers": sorted(ctx.discovery.known_peers)}

    if t == "GOSSIP":
        peers = msg.get("peers", [])
        if isinstance(peers, list):
            ctx.discovery.merge([p for p in peers if isinstance(p, str)])
        return {"type": "GOSSIP_ACK", "peers": sorted(ctx.discovery.known_peers)}

    if t == "METRICS_PUSH":
        metrics = msg.get("metrics", {})
        sender = peer_node_id if tls_enabled else msg.get("sender")
        if isinstance(sender, str) and isinstance(metrics, dict):
            ctx.upsert_peer_metrics(sender, metrics)
        return {"type": "METRICS_ACK"}

    return {"type": "ERROR", "reason": f"Unknown type {t}"}


async def discovery_loop(ctx: NodeRuntime, app: FastAPI) -> None:
    advertise = ctx.advertise_addr()
    ctx.log_event("DISCOVERY_STARTED", advertise=advertise, seeds=ctx.settings.seeds)

    while True:
        for seed in list(ctx.settings.seeds):
            try:
                host, port = parse_hostport(seed)

                resp = await send_message(host, port, {"type": "PEER_LIST_REQ"}, ssl_ctx=app.state.client_ssl_ctx)
                peers = resp.get("peers", [])
                if isinstance(peers, list):
                    ctx.discovery.merge([p for p in peers if isinstance(p, str)])

                await send_message(host, port, {"type": "HELLO", "listen": advertise}, ssl_ctx=app.state.client_ssl_ctx)
            except Exception:
                continue

        targets = ctx.discovery.pick_targets(k=2)
        payload = {"type": "GOSSIP", "peers": sorted(ctx.discovery.known_peers)}
        for tgt in targets:
            try:
                host, port = parse_hostport(tgt)
                resp = await send_message(host, port, payload, ssl_ctx=app.state.client_ssl_ctx)
                peers = resp.get("peers", [])
                if isinstance(peers, list):
                    ctx.discovery.merge([p for p in peers if isinstance(p, str)])

                await send_message(host, port, {"type": "HELLO", "listen": advertise}, ssl_ctx=app.state.client_ssl_ctx)
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
                    append_jsonl(METRICS_LOG, {"node_id": ctx.node_id, "sequence_id": ctx.next_seq(), "metrics": parsed})
        await asyncio.sleep(0.2)


async def metrics_push_loop(ctx: NodeRuntime, app: FastAPI) -> None:
    advertise = ctx.advertise_addr()

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
                    {"type": "METRICS_PUSH", "sender": ctx.node_id, "listen": advertise, "metrics": local},
                    timeout=2.0,
                    ssl_ctx=app.state.client_ssl_ctx,
                )
            except Exception:
                continue


def create_app() -> FastAPI:
    load_dotenv(dotenv_path=str(ENV_FILE), override=True)
    ensure_dirs()

    settings = load_settings()
    node_id = load_or_create_node_id()

    adv_host = settings.peer_advertise_host.strip() or detect_lan_ip() or "127.0.0.1"
    self_advertise_addr = f"{adv_host}:{settings.peer_port}"

    ctx = NodeRuntime(
        node_id=node_id,
        settings=settings,
        discovery=Discovery(settings.seeds),
        self_advertise_addr=self_advertise_addr,
        metrics_by_node={node_id: {}},
    )
    ctx.log_event("NODE_BOOTED", advertise=ctx.advertise_addr(), seeds=settings.seeds)

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    app = FastAPI(title="ZETA-SYNC Cluster (M3)", lifespan=None)
    app.state.ctx = ctx

    # security store
    store = SecurityStore(SECURITY_JSON)
    app.state.security_store = store

    # TLS flags
    app.state.tls_enabled = os.getenv("TLS_ENABLED", "0").strip() == "1"
    app.state.tls_require_allow = os.getenv("TLS_REQUIRE_ALLOWLIST", "1").strip() == "1"
    app.state.tls_join_throttle = float(os.getenv("TLS_JOIN_THROTTLE_SEC", "5"))
    ca_days = int(os.getenv("TLS_CA_VALIDITY_DAYS", "3650"))
    node_days = int(os.getenv("TLS_NODE_VALIDITY_DAYS", "365"))
    app.state.node_validity_days = node_days

    # TLS paths
    app.state.ca_key_path = CA_KEY
    app.state.ca_cert_path = CA_CERT
    app.state.node_key_path = NODE_KEY
    app.state.node_cert_path = NODE_CERT

    # Init CA if TLS enabled
    if app.state.tls_enabled:
        ensure_cluster_ca(CAPaths(CA_KEY, CA_CERT), validity_days=ca_days)

    # Build SSL contexts if node has certs
    app.state.server_ssl_ctx = None
    app.state.client_ssl_ctx = None
    if app.state.tls_enabled and NODE_CERT.exists() and NODE_KEY.exists():
        app.state.server_ssl_ctx = build_server_ssl_context(TLSPaths(CA_CERT, NODE_CERT, NODE_KEY))
        app.state.client_ssl_ctx = build_client_ssl_context(TLSPaths(CA_CERT, NODE_CERT, NODE_KEY))

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @asynccontextmanager
    async def lifespan(app_: FastAPI):
        peer_server = PeerServer(
            host=settings.peer_host,
            port=settings.peer_port,
            handler=lambda msg, meta: peer_handler(ctx, msg, meta, app_),
            ssl=app_.state.server_ssl_ctx if app_.state.tls_enabled else None,
        )
        await peer_server.start()
        ctx.log_event("PEER_SERVER_STARTED", bind=f"{settings.peer_host}:{settings.peer_port}", advertise=ctx.advertise_addr())

        t1 = asyncio.create_task(discovery_loop(ctx, app_))
        t2 = asyncio.create_task(metrics_loop(ctx))
        t3 = asyncio.create_task(metrics_push_loop(ctx, app_))

        try:
            yield
        finally:
            t1.cancel()
            t2.cancel()
            t3.cancel()
            await peer_server.stop()
            ctx.log_event("NODE_STOPPED")

    app.router.lifespan_context = lifespan

    # ---------------- UI Pages ----------------
    @app.get("/", response_class=HTMLResponse)
    async def ui_index(request: Request):
        return templates.TemplateResponse("index.html", {"request": request})

    @app.get("/nodes", response_class=HTMLResponse)
    async def ui_nodes(request: Request):
        return templates.TemplateResponse("nodes.html", {"request": request})

    @app.get("/events", response_class=HTMLResponse)
    async def ui_events(request: Request):
        return templates.TemplateResponse("events.html", {"request": request})

    @app.get("/security", response_class=HTMLResponse)
    async def ui_security(request: Request):
        return templates.TemplateResponse("security.html", {"request": request})

    # ---------------- Mgmt cluster controls ----------------
    @app.post("/mgmt/cluster/start", dependencies=[Depends(require_admin)])
    async def mgmt_start():
        try:
            await app.state.ctx.start_sync()
            return {"ok": True}
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/mgmt/cluster/stop", dependencies=[Depends(require_admin)])
    async def mgmt_stop():
        await app.state.ctx.stop_sync()
        return {"ok": True}

    # ---------------- Mgmt security endpoints ----------------
    @app.post("/mgmt/security/ca/init", dependencies=[Depends(require_admin)])
    async def mgmt_ca_init():
        ensure_cluster_ca(CAPaths(app.state.ca_key_path, app.state.ca_cert_path), validity_days=int(os.getenv("TLS_CA_VALIDITY_DAYS", "3650")))
        return {"ok": True, "ca_cert_path": str(app.state.ca_cert_path)}

    @app.get("/mgmt/security/ca/cert", dependencies=[Depends(require_admin)])
    async def mgmt_ca_cert():
        if not app.state.ca_cert_path.exists():
            raise HTTPException(status_code=404, detail="CA cert missing, init first")
        return {"ca_cert_pem": app.state.ca_cert_path.read_text(encoding="utf-8")}

    @app.post("/mgmt/security/nodes/issue", dependencies=[Depends(require_admin)])
    async def mgmt_issue_node_cert(node_id: str):
        ca_key, ca_cert = load_ca(CAPaths(app.state.ca_key_path, app.state.ca_cert_path))
        node_key_pem, node_cert_pem = issue_node_cert(ca_key, ca_cert, node_id=node_id, validity_days=app.state.node_validity_days)
        fp = sha256_fingerprint_from_cert_pem(node_cert_pem)

        return {
            "node_id": node_id,
            "fingerprint": fp,
            "ca_cert_pem": app.state.ca_cert_path.read_text(encoding="utf-8"),
            "node_cert_pem": node_cert_pem.decode("utf-8"),
            "node_key_pem": node_key_pem.decode("utf-8"),
            "install_to": "data/state/tls/",
            "files": {"ca.crt": "ca_cert_pem", "node.crt": "node_cert_pem", "node.key": "node_key_pem"},
        }

    @app.post("/mgmt/security/nodes/sign-csr", dependencies=[Depends(require_admin)])
    async def mgmt_sign_csr(csr_pem: str):
        ca_key, ca_cert = load_ca(CAPaths(app.state.ca_key_path, app.state.ca_cert_path))
        cert_pem = sign_csr(ca_key, ca_cert, csr_pem.encode("utf-8"), validity_days=app.state.node_validity_days)
        return {"cert_pem": cert_pem.decode("utf-8"), "ca_cert_pem": app.state.ca_cert_path.read_text(encoding="utf-8")}

    @app.get("/mgmt/security/nodes/pending", dependencies=[Depends(require_admin)])
    async def mgmt_pending():
        rec = app.state.security_store.load()
        return {"pending": rec.pending}

    @app.post("/mgmt/security/nodes/approve", dependencies=[Depends(require_admin)])
    async def mgmt_approve(node_id: str, pending_key: str):
        rec = app.state.security_store.load()
        info = rec.pending.get(pending_key)
        if not info:
            raise HTTPException(status_code=404, detail="pending entry not found")

        # minimal subject for storage
        subj = {"commonName": info.get("node_id")}
        app.state.security_store.approve_node(node_id=node_id, fingerprint=pending_key, cert_subject=subj)
        app.state.ctx.log_event("NODE_APPROVED", node_id=node_id)
        return {"ok": True}

    @app.post("/mgmt/security/nodes/deny", dependencies=[Depends(require_admin)])
    async def mgmt_deny(pending_key: str, reason: str = "denied"):
        app.state.security_store.deny_pending(pending_key, reason=reason)
        app.state.ctx.log_event("NODE_DENIED", severity="WARNING", fingerprint=pending_key, reason=reason)
        return {"ok": True}

    @app.post("/mgmt/security/nodes/block", dependencies=[Depends(require_admin)])
    async def mgmt_block(node_id: str, reason: str = "revoked"):
        app.state.security_store.block_node(node_id=node_id, reason=reason)
        app.state.ctx.log_event("NODE_BLOCKED", severity="WARNING", node_id=node_id, reason=reason)
        return {"ok": True}

    @app.get("/mgmt/security/state", dependencies=[Depends(require_admin)])
    async def mgmt_security_state():
        rec = app.state.security_store.load()
        return {"allowlist": rec.allowlist, "blocklist": rec.blocklist, "pending": rec.pending}

    # ---------------- Public API (read-only) ----------------
    @app.get("/api/v1/health")
    async def api_health():
        return {"ok": True, "tls_enabled": bool(app.state.tls_enabled)}

    @app.get("/api/v1/cluster/status")
    async def api_cluster_status():
        return app.state.ctx.cluster_status()

    @app.get("/api/v1/nodes")
    async def api_nodes(include_unknown: bool = Query(False)):
        return app.state.ctx.nodes_view(include_unknown=include_unknown)

    @app.get("/api/v1/cluster/events")
    async def api_events():
        return {"events": tail_jsonl(EVENTS_LOG, limit=200)}

    return app


app = create_app()

if __name__ == "__main__":
    env = os.getenv("APP_ENV", "dev").lower()
    uvicorn.run(
        "main:app",
        host=app.state.ctx.settings.http_host,
        port=app.state.ctx.settings.http_port,
        reload=(env == "dev"),
        workers=1,
        log_level=("debug" if env == "dev" else "info"),
    )
