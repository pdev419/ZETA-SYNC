from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class SecurityRecord:
    allowlist: Dict[str, Dict[str, Any]]   # node_id -> info
    blocklist: Dict[str, Dict[str, Any]]   # node_id -> info
    pending: Dict[str, Dict[str, Any]]     # fingerprint -> info
    bootstrap: Dict[str, Any]              # { token_hash, created_at }
    updated_at: float


class SecurityStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> SecurityRecord:
        if not self.path.exists():
            rec = SecurityRecord(allowlist={}, blocklist={}, pending={}, bootstrap={}, updated_at=time.time())
            self.save(rec)
            return rec

        obj = json.loads(self.path.read_text(encoding="utf-8"))
        return SecurityRecord(
            allowlist=obj.get("allowlist", {}) or {},
            blocklist=obj.get("blocklist", {}) or {},
            pending=obj.get("pending", {}) or {},
            bootstrap=obj.get("bootstrap", {}) or {},
            updated_at=float(obj.get("updated_at", time.time())),
        )

    def save(self, rec: SecurityRecord) -> None:
        data = {
            "allowlist": rec.allowlist,
            "blocklist": rec.blocklist,
            "pending": rec.pending,
            "bootstrap": rec.bootstrap,
            "updated_at": time.time(),
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    # ---------- allow/block/pending ----------
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

    def is_blocked(self, node_id: str) -> bool:
        rec = self.load()
        return node_id in rec.blocklist

    def is_allowed(self, node_id: str) -> bool:
        rec = self.load()
        return node_id in rec.allowlist

    # ---------- bootstrap token ----------
    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_bootstrap_token(self) -> str:
        """
        Creates a new bootstrap token and stores only its hash.
        Returns the plaintext token (show once in UI).
        """
        token = secrets.token_urlsafe(32)
        rec = self.load()
        rec.bootstrap = {
            "token_hash": self._hash_token(token),
            "created_at": time.time(),
        }
        self.save(rec)
        return token

    def verify_bootstrap_token(self, token: str) -> bool:
        rec = self.load()
        h = rec.bootstrap.get("token_hash")
        if not h:
            return False
        return secrets.compare_digest(h, self._hash_token(token))
