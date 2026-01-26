# ZETA-SYNC Cluster

A high-availability, peer-discovery & state-synchronization cluster node for modern distributed networks.

---

## Features
- **Cluster Node Discovery & Synchronization**
- Simple JSON-based configuration
- Dev & Production management (pm2 supported)
- Minimalist web UI for cluster state view

---

## Install
```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

---

## Configure
This app loads configuration from the repo-local `.env` at startup.

- Edit `.env` on each node (change `SEEDS`).
- See `env.example` for available keys/values.

---

## Run (Development)
```bash
APP_ENV=dev ./.venv/bin/python main.py
```

---

## Run (Production/pm2)
```bash
pm2 start ecosystem.config.js
pm2 logs zeta-sync
```

---

## Autostart on reboot (recommended: systemd user service)
This repo includes an install script that creates a **user-level** `systemd` service pointing at this checkout (no repo edits outside this folder).

```bash
# from repo root
bash bin/install-autostart-user-service.sh
```

Useful commands:

```bash
systemctl --user status zeta-sync.service
journalctl --user -u zeta-sync.service -f
```

If you need it to start at boot even when you are not logged in:

```bash
loginctl enable-linger "$USER"
```

To remove:

```bash
bash bin/uninstall-autostart-user-service.sh
```

---

## Web UI
- [`http://<node-ip>:8080/`](http://<node-ip>:8080/) – status overview
- [`http://<node-ip>:8080/nodes`](http://<node-ip>:8080/nodes) – peer list
- [`http://<node-ip>:8080/events`](http://<node-ip>:8080/events) – recent events

---
