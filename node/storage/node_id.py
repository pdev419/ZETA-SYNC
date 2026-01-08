from __future__ import annotations
import uuid
from ..constants import NODE_ID_FILE

def load_or_create_node_id() -> str:
    NODE_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    if NODE_ID_FILE.exists():
        return NODE_ID_FILE.read_text(encoding="utf-8").strip()
    node_id = f"node-{uuid.uuid4().hex[:8]}"
    NODE_ID_FILE.write_text(node_id, encoding="utf-8")
    return node_id
