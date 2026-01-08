from __future__ import annotations
from ..constants import DATA_DIR, STATE_DIR, LOG_DIR, TLS_DIR

def ensure_dirs() -> None:
    for p in [DATA_DIR, STATE_DIR, LOG_DIR, TLS_DIR]:
        p.mkdir(parents=True, exist_ok=True)
