from __future__ import annotations
from pathlib import Path
from typing import Any, Dict
import json
import os

def append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")

def tail_jsonl(path: Path, limit: int = 200) -> list[Dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[Dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out

def has_min_disk_free(dir_path: Path, min_free_bytes: int = 50 * 1024 * 1024) -> bool:
    try:
        st = os.statvfs(str(dir_path))
        free = st.f_bavail * st.f_frsize
        return free >= min_free_bytes
    except Exception:
        return True
