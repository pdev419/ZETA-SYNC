#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SERVICE_NAME="zeta-sync.service"
USER_SYSTEMD_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
OUT_PATH="$USER_SYSTEMD_DIR/$SERVICE_NAME"

systemctl --user disable --now "$SERVICE_NAME" 2>/dev/null || true

if [[ -f "$OUT_PATH" ]]; then
  rm -f "$OUT_PATH"
fi

systemctl --user daemon-reload

echo "Uninstalled: $SERVICE_NAME"

