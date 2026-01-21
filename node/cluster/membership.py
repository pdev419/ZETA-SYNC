# node/cluster/membership.py
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


def _env_float(key: str, default: float) -> float:
    v = os.getenv(key)
    if v is None or str(v).strip() == "":
        return default
    return float(v)


METRICS_STALE_SEC = _env_float("METRICS_STALE_SEC", 5.0)


@dataclass
class MemberInfo:
    node_id: str
    peer_addr: Optional[str] = None

    last_seen: float = field(default_factory=lambda: time.time())
    online: bool = True
    # last time we observed metrics for this node
    last_metrics_ts: float = 0.0

    excluded: bool = False
    exclude_reason: Optional[str] = None

    state: str = "DISCOVERING"

    outlier_streak: int = 0
    recover_streak: int = 0

    metrics: Dict[str, Any] = field(default_factory=dict)

    def has_fresh_metrics(self, now: float) -> bool:
        return self.last_metrics_ts > 0 and (now - self.last_metrics_ts) <= METRICS_STALE_SEC


@dataclass
class ClusterDerived:
    cluster_health: str = "RECOVERING"
    quorum: str = "0/0"
    active_nodes: int = 0
    expected_nodes: int = 3
    quorum_needed: int = 2

    excluded_nodes: list[str] = field(default_factory=list)
    exclude_reasons: Dict[str, str] = field(default_factory=dict)

    reference_z: Optional[float] = None
    reference_method: Optional[str] = None  # median3 | mean2 | single

    healthy_streak: int = 0
    healthy_required: int = 10
    healthy_stability_threshold: float = 0.995

    last_update: float = field(default_factory=lambda: time.time())


class MembershipTracker:
    def __init__(
        self,
        expected_cluster_size: int = 3,
        offline_after_sec: float = 10.0,
        outlier_z_abs_threshold: float = 0.002,
        outlier_consecutive: int = 5,
        recover_stability_threshold: float = 0.995,
        recover_consecutive: int = 10,
        healthy_stability_threshold: float = 0.995,
        healthy_consecutive: int = 10,
    ):
        self.expected_cluster_size = max(1, int(expected_cluster_size))
        self.offline_after_sec = offline_after_sec
        self.outlier_z_abs_threshold = outlier_z_abs_threshold
        self.outlier_consecutive = outlier_consecutive
        self.recover_stability_threshold = recover_stability_threshold
        self.recover_consecutive = recover_consecutive

        self.members: Dict[str, MemberInfo] = {}
        self.cluster = ClusterDerived(
            expected_nodes=self.expected_cluster_size,
            healthy_required=int(healthy_consecutive),
            healthy_stability_threshold=float(healthy_stability_threshold),
        )

    def ensure_member(self, node_id: str, peer_addr: Optional[str] = None) -> MemberInfo:
        m = self.members.get(node_id)
        if not m:
            m = MemberInfo(node_id=node_id, peer_addr=peer_addr, state="DISCOVERING")
            self.members[node_id] = m
        if peer_addr:
            m.peer_addr = peer_addr
        return m

    def observe(
        self,
        node_id: str,
        peer_addr: Optional[str],
        metrics: Optional[Dict[str, Any]] = None,
        sync_running: Optional[bool] = None,
    ) -> MemberInfo:
        now = time.time()
        m = self.ensure_member(node_id, peer_addr)
        m.last_seen = now
        m.online = True

        if sync_running is not None:
            m.sync_running = bool(sync_running)

        if metrics and isinstance(metrics, dict):
            m.metrics = metrics
            m.last_metrics_ts = now

        if not m.online:
            m.state = "OFFLINE"
        elif m.excluded:
            m.state = "RECOVERING"
        elif not m.sync_running:
            m.state = "PAUSED"
        else:
            if m.has_fresh_metrics(now):
                m.state = "ACTIVE"
            else:
                m.state = "JOINING"

        return m

    def tick(self) -> Dict[str, Any]:
        now = time.time()
        became_offline: list[str] = []
        became_online: list[str] = []
        excluded: list[tuple[str, str]] = []
        reincluded: list[str] = []

        for node_id, m in self.members.items():
            was_online = m.online
            if now - m.last_seen > self.offline_after_sec:
                m.online = False
                m.state = "OFFLINE"
                if was_online:
                    became_offline.append(node_id)
                if not m.excluded:
                    m.excluded = True
                    m.exclude_reason = "UNREACHABLE"
                    excluded.append((node_id, "UNREACHABLE"))
            else:
                m.online = True
                if not was_online:
                    became_online.append(node_id)
                if m.excluded and m.exclude_reason == "UNREACHABLE":
                    m.state = "RECOVERING"

        for node_id, m in self.members.items():
            if not m.online or m.state == "PAUSED":
                continue

            z = m.metrics.get("z")
            stability = m.metrics.get("stability")

            if isinstance(z, (int, float)) and abs(float(z) - 1.0) > self.outlier_z_abs_threshold:
                m.outlier_streak += 1
            else:
                m.outlier_streak = 0

            if (not m.excluded) and m.outlier_streak >= self.outlier_consecutive:
                m.excluded = True
                m.exclude_reason = "OUTLIER"
                m.state = "RECOVERING"
                excluded.append((node_id, "OUTLIER"))

            if m.excluded:
                if isinstance(stability, (int, float)) and float(stability) >= self.recover_stability_threshold:
                    m.recover_streak += 1
                else:
                    m.recover_streak = 0

                if m.recover_streak >= self.recover_consecutive:
                    m.excluded = False
                    m.exclude_reason = None
                    m.recover_streak = 0
                    m.outlier_streak = 0
                    if not m.sync_running:
                        m.state = "PAUSED"
                    else:
                        m.state = "ACTIVE" if m.has_fresh_metrics(now) else "JOINING"
                    reincluded.append(node_id)

        for m in self.members.values():
            if not m.online:
                m.state = "OFFLINE"
                continue
            if m.excluded:
                m.state = "RECOVERING"
                continue
            if not m.sync_running:
                m.state = "PAUSED"
                continue
            m.state = "ACTIVE" if m.has_fresh_metrics(now) else "JOINING"

        self._derive(now)
        return {
            "became_offline": became_offline,
            "became_online": became_online,
            "excluded": excluded,
            "reincluded": reincluded,
        }

    def _derive(self, now: float) -> None:
        expected = self.expected_cluster_size
        quorum_needed = (expected // 2) + 1
        self.cluster.expected_nodes = expected
        self.cluster.quorum_needed = quorum_needed

        participating = [
            m for m in self.members.values()
            if m.online and (not m.excluded) and m.sync_running and m.has_fresh_metrics(now)
        ]
        active = len(participating)

        self.cluster.active_nodes = active
        self.cluster.quorum = f"{active}/{expected}"

        excluded_nodes = [m.node_id for m in self.members.values() if m.excluded]
        self.cluster.excluded_nodes = excluded_nodes
        self.cluster.exclude_reasons = {
            m.node_id: (m.exclude_reason or "UNKNOWN") for m in self.members.values() if m.excluded
        }

        zs = []
        for m in participating:
            z = m.metrics.get("z")
            if isinstance(z, (int, float)):
                zs.append(float(z))

        if len(zs) >= 3:
            zs_sorted = sorted(zs)
            self.cluster.reference_z = zs_sorted[len(zs_sorted) // 2]
            self.cluster.reference_method = "median3"
        elif len(zs) == 2:
            self.cluster.reference_z = (zs[0] + zs[1]) / 2.0
            self.cluster.reference_method = "mean2"
        elif len(zs) == 1:
            self.cluster.reference_z = zs[0]
            self.cluster.reference_method = "single"
        else:
            self.cluster.reference_z = None
            self.cluster.reference_method = None

        has_quorum = active >= quorum_needed
        has_exclusions = len(excluded_nodes) > 0
        all_required_active = (active >= expected)

        stabs = []
        for m in participating:
            s = m.metrics.get("stability")
            if isinstance(s, (int, float)):
                stabs.append(float(s))
        stabs.sort()
        cluster_stab = stabs[len(stabs) // 2] if stabs else None

        healthy_now = (
            all_required_active
            and has_quorum
            and (not has_exclusions)
            and (cluster_stab is not None)
            and (cluster_stab >= self.cluster.healthy_stability_threshold)
        )

        if active == 0:
            self.cluster.cluster_health = "OFFLINE"
            self.cluster.healthy_streak = 0
        else:
            if healthy_now:
                self.cluster.healthy_streak += 1
            else:
                self.cluster.healthy_streak = 0

            if self.cluster.healthy_streak >= self.cluster.healthy_required:
                self.cluster.cluster_health = "HEALTHY"
            else:
                if expected >= 3 and active < expected:
                    self.cluster.cluster_health = "DEGRADED"
                else:
                    self.cluster.cluster_health = "RECOVERING" if (not has_exclusions) else "DEGRADED"

        self.cluster.last_update = time.time()

    def export_nodes(self) -> list[dict]:
        out = []
        for m in self.members.values():
            out.append(
                {
                    "node_id": m.node_id,
                    "peer_addr": m.peer_addr,
                    "state": m.state,
                    "online": m.online,
                    "last_seen": m.last_seen,
                    "sync_running": m.sync_running,
                    "last_metrics_ts": m.last_metrics_ts,
                    "excluded": m.excluded,
                    "reason": m.exclude_reason,
                    "metrics": m.metrics,
                }
            )
        out.sort(key=lambda x: (x["node_id"] or ""))
        return out

    def export_cluster(self) -> dict:
        c = self.cluster
        return {
            "cluster_health": c.cluster_health,
            "quorum": c.quorum,
            "quorum_needed": c.quorum_needed,
            "active_nodes": c.active_nodes,
            "expected_nodes": c.expected_nodes,
            "excluded_nodes": c.excluded_nodes,
            "exclude_reasons": c.exclude_reasons,
            "reference_z": c.reference_z,
            "reference_method": c.reference_method,
            "healthy_streak": c.healthy_streak,
            "healthy_required": c.healthy_required,
            "healthy_stability_threshold": c.healthy_stability_threshold,
            "last_update": c.last_update,
        }
