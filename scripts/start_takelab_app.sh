#!/usr/bin/env bash
# Run this script once at session start.
# Starts the transcriber (vosk) and web app on takelab, then opens SSH tunnels
# so you can access the app on this machine at http://localhost:8088 (HTTP)
# and https://localhost:8444 (HTTPS — needed for phone getUserMedia).
#
# On takelab's WINDOWS side, run once in an admin PowerShell to expose to LAN:
#   netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=8080 connectaddress=172.28.250.189 connectport=8080
#   netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=8443 connectaddress=172.28.250.189 connectport=8443
#   netsh advfirewall firewall add rule name="transcriber" dir=in action=allow protocol=TCP localport=8080,8443
# Then anyone on the classroom WiFi can open:
#   http://10.10.5.59:8080   (laptop, no mic on phone)
#   https://10.10.5.59:8443  (phone — accept cert warning once)
set -euo pipefail

echo "[1/3] Starting Whisper large-v3 (CUDA) transcriber on takelab..."
ssh takelab 'fuser -k 19001/tcp 2>/dev/null; true'
ssh takelab 'cd ~/remote-transcriber && source .venv/bin/activate &&
  LD_LIBRARY_PATH=/home/amil/llm/lib/python3.10/site-packages/nvidia/cublas/lib:/usr/local/lib/ollama/cuda_v12 \
  STT_ENGINE=whisper WHISPER_MODEL=large-v3 WHISPER_DEVICE=cuda WHISPER_COMPUTE=float16 \
  nohup uvicorn remote_server:app --host 127.0.0.1 --port 19001 > /tmp/transcriber.log 2>&1 &'
sleep 1
ssh takelab 'python3 -c "import urllib.request; print(urllib.request.urlopen(\"http://127.0.0.1:19001/health\",timeout=5).read().decode())"'

echo "[2/3] Starting web app on takelab (HTTP :8080 + HTTPS :8443)..."
ssh takelab 'fuser -k 8080/tcp 2>/dev/null; true'
ssh takelab 'fuser -k 8443/tcp 2>/dev/null; true'
ssh takelab 'cd ~/remote-transcriber && source .venv/bin/activate && REMOTE_WS_URL=ws://127.0.0.1:19001/ws OLLAMA_URL=http://127.0.0.1:11434 nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080 > /tmp/app.log 2>&1 &'
ssh takelab 'cd ~/remote-transcriber && source .venv/bin/activate && REMOTE_WS_URL=ws://127.0.0.1:19001/ws OLLAMA_URL=http://127.0.0.1:11434 nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8443 --ssl-keyfile key.pem --ssl-certfile cert.pem > /tmp/app_ssl.log 2>&1 &'

echo "[3/3] Opening SSH tunnels (this machine → takelab app)..."
# Forwards takelab's app ports to localhost so you can also open locally.
# Runs in background — kill with: pkill -f 'ssh -N.*8088'
ssh -N -f \
  -L 8088:127.0.0.1:8080 \
  -L 8444:127.0.0.1:8443 \
  takelab

echo ""
echo "Done. Open in browser:"
echo "  http://localhost:8088      ← this machine (laptop)"
echo "  https://localhost:8444     ← this machine HTTPS (needed for phone getUserMedia via tunnel)"
echo "  http://10.10.5.59:8080     ← LAN (after portproxy — see comment at top of script)"
echo "  https://10.10.5.59:8443    ← LAN HTTPS for phone"
