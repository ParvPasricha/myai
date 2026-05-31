#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "[PARV-AI] Starting stack..."

# MQTT broker
brew services start mosquitto 2>/dev/null || true

# FastAPI server
echo "[PARV-AI]   http://localhost:8000"
echo "[Dashboard] http://localhost:3000"
.venv/bin/uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
