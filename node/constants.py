from pathlib import Path

APP_NAME = "zeta-sync-cluster"

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # repo_root/node/constants.py -> repo_root

DATA_DIR = PROJECT_ROOT / "data"
STATE_DIR = DATA_DIR / "state"
LOG_DIR = DATA_DIR / "logs"
TLS_DIR = DATA_DIR / "tls"

NODE_ID_FILE = STATE_DIR / "node_id"

EVENTS_LOG = LOG_DIR / "events.jsonl"
METRICS_LOG = LOG_DIR / "metrics.jsonl"
SECURITY_LOG = LOG_DIR / "security.jsonl"

ENV_FILE = PROJECT_ROOT / ".env"
