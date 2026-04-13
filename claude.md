# Handoff Notes for Claude

## Goal
"Takemoto Lab Seminar Assistant" — a local web app that captures mic audio, transcribes JA/EN in real-time via takelab, translates JA→EN using a local LLM (ollama on takelab), and answers questions via RAG over lab knowledge base files.

## Current State
App now runs on takelab directly (no tunnel needed for vosk/ollama).

Running components:
- Remote vosk transcriber on takelab:19001
- Takelab web app: HTTP on takelab:8080, HTTPS on takelab:8443
- SSH tunnel from local: local:8088→takelab:8080, local:8444→takelab:8443
- Ollama service on takelab (systemd, auto-start)

## What Was Built

### Local side (app/)
- FastAPI app: websocket bridge + `/api/translate` + `/api/ask` endpoints
- `/api/translate`: POSTs text to ollama, returns EN translation
- `/api/ask`: keyword-search RAG over context/, sends to ollama, returns answer
- RAG indexer: loads all .txt/.md/.csv from context/ on startup; CJK bigram + word token search
- UI: two-panel layout — transcript (JA+EN) left, Lab Assistant Q&A right
- Language selector change now sends live config update to remote (bug fix)

### Remote side (remote/)
- FastAPI websocket transcriber with vosk/whisper engine routing
- Vosk restarts with correct language model on config change
- Health endpoint at /health

### Context / Knowledge Base
- context/ is gitignored (contents only, .gitkeep tracked)
- Currently indexed: LINE chat history ([LINE]［竹本研］全体連絡用.txt) — 178 chunks
- Drop more files into context/ and restart the local app to re-index

## Infrastructure

### takelab
- Hostname: DESKTOP-E3DS77O (WSL2 Linux)
- GPU: NVIDIA RTX 5090, 32GB VRAM
- Ollama: installed at /usr/local/bin/ollama, systemd service
- Model: qwen2.5:14b (or whatever is pulled — check `ssh takelab 'ollama list'`)
- Vosk models: ~/voice/vosk-model-small-en-us-0.15, ~/voice/vosk-model-small-ja-0.22
- No internet access from takelab (can only be reached via SSH from local)

### Local WSL2 machine
- Python venv at .venv/
- zstd installed at /usr/bin/zstd (needed if re-installing ollama on takelab)

## Restart Commands

Everything in one script:
```
bash scripts/start_takelab_app.sh
```
Then open: http://localhost:8088

Manual steps if needed:

1) Start vosk on takelab:
```
ssh takelab 'fuser -k 19001/tcp 2>/dev/null; cd ~/remote-transcriber && source .venv/bin/activate && STT_ENGINE=vosk nohup uvicorn remote_server:app --host 127.0.0.1 --port 19001 > /tmp/transcriber.log 2>&1 &'
```

2) Start web app on takelab (HTTP + HTTPS):
```
ssh takelab 'cd ~/remote-transcriber && source .venv/bin/activate && REMOTE_WS_URL=ws://127.0.0.1:19001/ws OLLAMA_URL=http://127.0.0.1:11434 nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080 > /tmp/app.log 2>&1 &'
ssh takelab 'cd ~/remote-transcriber && source .venv/bin/activate && REMOTE_WS_URL=ws://127.0.0.1:19001/ws OLLAMA_URL=http://127.0.0.1:11434 nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8443 --ssl-keyfile key.pem --ssl-certfile cert.pem > /tmp/app_ssl.log 2>&1 &'
```

3) Open SSH tunnel:
```
ssh -N -f -L 8088:127.0.0.1:8080 -L 8444:127.0.0.1:8443 takelab
```

4) Open: http://localhost:8088  (or https://localhost:8444 for HTTPS)

## LAN Access (phone / other devices)
takelab is WSL2, so ports are NOT directly reachable at 10.10.5.59 unless
Windows portproxy is configured. Run ONCE in admin PowerShell on takelab's Windows:
```powershell
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=8080 connectaddress=172.28.250.189 connectport=8080
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=8443 connectaddress=172.28.250.189 connectport=8443
netsh advfirewall firewall add rule name="transcriber" dir=in action=allow protocol=TCP localport=8080,8443
```
Then from phone: https://10.10.5.59:8443 (accept self-signed cert warning)
Note: WSL2 IP (172.28.250.189) changes on reboot — re-check with: ssh takelab 'ip addr show eth0 | grep "inet "'

## Health Checks
```bash
# Local
python3 -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8080/api/health", timeout=5).read().decode())'

# Remote transcriber
ssh takelab 'python3 -c "import urllib.request; print(urllib.request.urlopen(\"http://127.0.0.1:19001/health\", timeout=8).read().decode())"'

# Ollama (via tunnel)
curl -s http://127.0.0.1:11434/api/tags

# Change ollama model
# Set OLLAMA_MODEL env var when starting local app, or edit default in app/main.py
```

## Key Files
- app/main.py — FastAPI: ws bridge + translate + ask + RAG indexer
- app/static/app.js — UI logic: mic, ws, translation fetch, Q&A
- app/static/index.html — Two-panel layout
- app/static/styles.css — Styling
- remote/remote_server.py — vosk/whisper transcriber
- scripts/start_tunnel.sh — SSH tunnel (19001 + 11434)
- context/ — Knowledge base files (gitignored, drop files here)

## Known Issues / Quirks
- takelab has no outbound internet; use local machine to download and scp anything needed
  - e.g., zstd was copied: `scp /usr/bin/zstd takelab:/tmp/zstd && ssh takelab 'sudo cp /tmp/zstd /usr/local/bin/zstd'`
- GPU whisper path fails (libcublas.so.12 not found); falls back to CPU int8
- Vosk small models are fast but lower quality; EN model at ~/voice/vosk-model-small-en-us-0.15
- RAG is keyword-based (no embeddings) — good for demo, upgrade to vector DB later

## Suggested Next Steps
1. Add more context files (seminar slides, research notes) to context/ and restart app
2. Upgrade RAG to proper vector embeddings (use ollama embed endpoint + cosine similarity)
3. Add engine selector in UI (vosk vs whisper)
4. Write political justification email to Prof. Takemoto (separate task)
5. Fix CUDA for whisper GPU path on takelab
6. Consider streaming translation (SSE) for lower perceived latency
