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
pip install -r requirements.txt
```

---

## Configure
Edit `.env` on each node (change SEEDS).

---

## Run (Development)
```bash
python3 node/main.py
```

---

## Run (Production/pm2)
```bash
pm2 start ecosystem.config.js
pm2 logs zeta-sync-cluster
```

---

## Web UI
- [`http://<node-ip>:8080/`](http://<node-ip>:8080/) – status overview
- [`http://<node-ip>:8080/nodes`](http://<node-ip>:8080/nodes) – peer list
- [`http://<node-ip>:8080/events`](http://<node-ip>:8080/events) – recent events

---
