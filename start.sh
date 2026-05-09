#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "[PARV-AI] Starting stack..."

# MQTT broker
brew services start mosquitto 2>/dev/null || true

# Grafana (http://localhost:3000 — admin/admin)
brew services start grafana 2>/dev/null || true

# Prometheus
pkill -f "prometheus.*parv-ai" 2>/dev/null || true
/opt/homebrew/bin/prometheus \
  --config.file="$(pwd)/prometheus.yml" \
  --storage.tsdb.path=/tmp/parv-ai-prometheus \
  --web.listen-address=":9090" \
  --log.level=warn &
echo "[Prometheus] http://localhost:9090"
echo "[Grafana]    http://localhost:3000  (admin / admin)"

# FastAPI server
echo "[PARV-AI]   http://localhost:8000"
.venv/bin/uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
