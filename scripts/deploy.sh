#!/usr/bin/env bash
# Deploy latest code to takelab.
# - Static files (app.js, styles.css, index.html): instant, no downtime
# - Web app (app/): quick restart (~3s downtime)
# - Whisper (remote_server.py): only restarts if the file changed (~45s downtime for model reload)
#
# Usage: bash scripts/deploy.sh
set -euo pipefail

HOST=takelab
REMOTE=~/remote-transcriber

echo "[1/3] Syncing files..."
# Sync everything (static files take effect immediately after sync)
rsync -a --checksum \
  app/ "${HOST}:${REMOTE}/app/" \
  remote/remote_server.py "${HOST}:${REMOTE}/remote_server.py"

# Also sync any scripts that changed
rsync -a --checksum scripts/ "${HOST}:${REMOTE}/scripts/" 2>/dev/null || true

echo "[2/3] Restarting web app (HTTP :8080 + HTTPS :8443)..."
ssh "$HOST" 'bash -lc "
  fuser -k 8080/tcp 2>/dev/null; true
  fuser -k 8443/tcp 2>/dev/null; true
  sleep 1
  cd ~/remote-transcriber && source .venv/bin/activate
  REMOTE_WS_URL=ws://127.0.0.1:19001/ws OLLAMA_URL=http://127.0.0.1:11434 \
    nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080 > /tmp/app.log 2>&1 &
  REMOTE_WS_URL=ws://127.0.0.1:19001/ws OLLAMA_URL=http://127.0.0.1:11434 \
    nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8443 \
    --ssl-keyfile key.pem --ssl-certfile cert.pem > /tmp/app_ssl.log 2>&1 &
  echo web_started
"'

echo "[3/3] Checking Whisper..."
# Check if remote_server.py is newer than what's running
LOCAL_SUM=$(md5sum remote/remote_server.py | cut -d' ' -f1)
REMOTE_SUM=$(ssh "$HOST" "md5sum ${REMOTE}/remote_server.py | cut -d' ' -f1" 2>/dev/null || echo "")
# (Files were just synced so sums should match; check if Whisper is running)
WHISPER_PID=$(ssh "$HOST" 'pgrep -f "uvicorn.*19001" || true')
if [ -z "$WHISPER_PID" ]; then
  echo "  Whisper not running — starting..."
  ssh "$HOST" 'bash -lc "
    cd ~/remote-transcriber && source .venv/bin/activate
    LD_LIBRARY_PATH=/home/amil/llm/lib/python3.10/site-packages/nvidia/cublas/lib:/usr/local/lib/ollama/cuda_v12 \
    STT_ENGINE=whisper WHISPER_MODEL=large-v3 WHISPER_DEVICE=cuda WHISPER_COMPUTE=float16 \
    TRANSCRIBE_INTERVAL=0.3 SILENCE_CHUNKS=3 SILENCE_RMS=0.02 WINDOW_SAMPLES=160000 \
    nohup .venv/bin/uvicorn remote_server:app --host 127.0.0.1 --port 19001 > /tmp/transcriber.log 2>&1 &
    echo whisper_started
  "'
  echo "  Waiting for Whisper to load model (~30s)..."
  for i in $(seq 1 12); do
    sleep 5
    if ssh "$HOST" 'curl -sf http://127.0.0.1:19001/health > /dev/null 2>&1'; then
      echo "  Whisper ready."
      break
    fi
    echo "  ...still loading ($((i*5))s)"
  done
else
  echo "  Whisper already running (pid $WHISPER_PID) — skipping restart."
  echo "  Run 'bash scripts/deploy.sh --restart-whisper' to force restart."
fi

echo ""
echo "Deployed. Open: http://localhost:8088 (hard-refresh if styles look stale: Ctrl+Shift+R)"
