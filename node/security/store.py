from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


@dataclass
class SecurityRecord:
    allowlist: Dict[str, Dict[str, Any]]   # node_id -> info
    blocklist: Dict[str, Dict[str, Any]]   # node_id -> info
    pending: Dict[str, Dict[str, Any]]     # fingerprint -> info
    updated_at: float


class SecurityStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> SecurityRecord:
        if not self.path.exists():
            rec = SecurityRecord(allowlist={}, blocklist={}, pending={}, updated_at=time.time())
            self.save(rec)
            return rec

        obj = json.loads(self.path.read_text(encoding="utf-8"))
        return SecurityRecord(
            allowlist=obj.get("allowlist", {}) or {},
            blocklist=obj.get("blocklist", {}) or {},
            pending=obj.get("pending", {}) or {},
            updated_at=float(obj.get("updated_at", time.time())),
        )

    def save(self, rec: SecurityRecord) -> None:
        data = {
            "allowlist": rec.allowlist,
            "blocklist": rec.blocklist,
            "pending": rec.pending,
            "updated_at": time.time(),
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def upsert_pending(self, fingerprint: str, info: Dict[str, Any]) -> None:
        rec = self.load()
        existing = rec.pending.get(fingerprint, {})
        merged = {**existing, **info}
        rec.pending[fingerprint] = merged
        self.save(rec)

    def approve_node(self, node_id: str, fingerprint: str, cert_subject: Dict[str, Any]) -> None:
        rec = self.load()
        rec.allowlist[node_id] = {
            "fingerprint": fingerprint,
            "subject": cert_subject,
            "approved_at": time.time(),
        }
        rec.pending.pop(fingerprint, None)
        self.save(rec)

    def deny_pending(self, fingerprint: str, reason: str = "denied") -> None:
        rec = self.load()
        rec.pending.pop(fingerprint, None)
        self.save(rec)

    def block_node(self, node_id: str, reason: str = "revoked") -> None:
        rec = self.load()
        rec.blocklist[node_id] = {"reason": reason, "blocked_at": time.time()}
        rec.allowlist.pop(node_id, None)
        self.save(rec)

    def unblock_node(self, node_id: str) -> None:
        rec = self.load()
        rec.blocklist.pop(node_id, None)
        self.save(rec)

    def is_blocked(self, node_id: str) -> bool:
        rec = self.load()
        return node_id in rec.blocklist

    def is_allowed(self, node_id: str) -> bool:
        rec = self.load()
        return node_id in rec.allowlist
