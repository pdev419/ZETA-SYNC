#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SERVICE_NAME="zeta-sync.service"
TEMPLATE_PATH="$ROOT/deploy/systemd/zeta-sync.service.template"
USER_SYSTEMD_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
OUT_PATH="$USER_SYSTEMD_DIR/$SERVICE_NAME"

if [[ ! -f "$TEMPLATE_PATH" ]]; then
  echo "Missing template: $TEMPLATE_PATH" >&2
  exit 1
fi

# We rely on repo-local .env for configuration (loaded by main.py).
if [[ ! -f "$ROOT/.env" ]]; then
  echo "Missing $ROOT/.env" >&2
  echo "Create it (example): cp env.example .env" >&2
  exit 1
fi

# Ensure venv + deps exist (kept inside repo).
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  python3 -m venv "$ROOT/.venv"
fi

"$ROOT/.venv/bin/pip" install -r "$ROOT/requirements.txt"

# Render service with absolute project path.
mkdir -p "$USER_SYSTEMD_DIR"
python3 - "$TEMPLATE_PATH" "$OUT_PATH" "$ROOT" <<'PY'
import sys
from pathlib import Path

template_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
root = sys.argv[3]

text = template_path.read_text(encoding="utf-8")
text = text.replace("__PROJECT_DIR__", root)

out_path.write_text(text, encoding="utf-8")
PY

systemctl --user daemon-reload
systemctl --user enable --now "$SERVICE_NAME"

cat <<EOF
Installed and started: $SERVICE_NAME

Check status:
  systemctl --user status $SERVICE_NAME

View logs:
  journalctl --user -u $SERVICE_NAME -f

Note: to run at boot even when you're not logged in, enable linger:
  loginctl enable-linger "\$USER"
EOF

