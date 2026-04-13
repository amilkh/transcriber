# 竹本研 Seminar Assistant

Real-time Japanese/English transcription and translation for the Takemoto Lab seminar.
Audio is captured in the browser, transcribed on the lab GPU server (`takelab`), and
translated by a local LLM — no cloud, no data leaves the university network.

---

## Architecture

```
Browser (teacher)          takelab (10.10.5.59, RTX 5090)
─────────────────          ──────────────────────────────
Mic → PCM 16kHz  ──WS──▶  FastAPI app  ──WS──▶  Whisper large-v3 (CUDA)
                           │                        │
                           │◀── partial/final text ─┘
                           │
                           ├──POST /api/translate──▶  Ollama qwen2.5:14b
                           └──POST /api/ask       ──▶  (RAG over context/)

Browser (viewer)  ──WS──▶  /ws/view  (receive-only, no mic)
```

**Recordings:** Every mic session is saved as a WAV file to `~/recordings/` on takelab.

---

## Prerequisites

### On `takelab` (one-time setup)

```bash
# Python venv with dependencies
cd ~/remote-transcriber
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn[standard] websockets httpx pydantic \
            faster-whisper soundfile numpy

# Ollama (already running as systemd service)
# Model: qwen2.5:14b (already pulled)

# Vosk models (fallback, optional)
# ~/voice/vosk-model-small-ja-0.22
# ~/voice/vosk-model-small-en-us-0.15
```

### Windows portproxy on `takelab` (one-time, admin PowerShell)

Run once so classroom devices can reach the app directly at `http://10.10.5.59:8080`:

```powershell
# Get WSL2 IP first (run in WSL2): ip addr show eth0 | grep "inet "
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=8080 connectaddress=172.28.250.189 connectport=8080
netsh advfirewall firewall add rule name="transcriber-8080" dir=in action=allow protocol=TCP localport=8080
```

> Note: WSL2 IP changes on reboot. Re-run with the new IP from `ssh takelab 'ip addr show eth0 | grep inet'`.
> The setup script at `scripts/setup_windows_portproxy.ps1` automates this.

---

## Starting the System

**Everything in one command** (run from this repo on the local machine):

```bash
bash scripts/start_takelab_app.sh
```

This starts Whisper + the web app on takelab and opens an SSH tunnel to `localhost:8088`.

### Manual steps (if needed)

```bash
# 1. Start Whisper large-v3 on GPU
ssh takelab '
  cd ~/remote-transcriber && source .venv/bin/activate
  LD_LIBRARY_PATH=/home/amil/llm/lib/python3.10/site-packages/nvidia/cublas/lib:/usr/local/lib/ollama/cuda_v12 \
  STT_ENGINE=whisper WHISPER_MODEL=large-v3 WHISPER_DEVICE=cuda WHISPER_COMPUTE=float16 \
  nohup uvicorn remote_server:app --host 127.0.0.1 --port 19001 > /tmp/transcriber.log 2>&1 &
'

# 2. Start web app on takelab
ssh takelab '
  cd ~/remote-transcriber && source .venv/bin/activate
  REMOTE_WS_URL=ws://127.0.0.1:19001/ws OLLAMA_URL=http://127.0.0.1:11434 \
  nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080 > /tmp/app.log 2>&1 &
'

# 3. SSH tunnel (for teacher mic on local machine)
ssh -N -f -o ServerAliveInterval=10 -o ServerAliveCountMax=3 \
  -L 8088:127.0.0.1:8080 takelab
```

---

## Accessing the App

| Who | URL | Mic |
|-----|-----|-----|
| Teacher (you) | `http://localhost:8088` | ✓ secure via tunnel |
| Teacher — alternative | `http://10.10.5.59:8080` + Chrome flag¹ | ✓ |
| Professor / students | `http://10.10.5.59:8080/?view` | read-only |
| Phone / tablet | `http://10.10.5.59:8080/?view` | read-only |

¹ To enable mic at the LAN IP, open `chrome://flags/#unsafely-treat-insecure-origin-as-secure`,
add `http://10.10.5.59:8080`, click Enable, relaunch Chrome.

### Viewer mode (`?view`)
- Auto-connects to the live transcript feed
- Shows transcript + Lab Assistant Q&A
- No mic controls — safe to share with students

---

## Language & Transcription

- Default: **Japanese** (`ja`) — Whisper forced to Japanese ASR
- Switch to **Auto (JA/EN)** for mixed-language sessions (runs language detection per utterance)
- Silence detection: ~600 ms of quiet after speech commits a sentence as final and triggers translation

---

## Recordings & Transcripts

Recordings are saved automatically to `~/recordings/` on takelab as WAV files
(16 kHz, 16-bit mono) every time the mic is active.

**Batch transcribe a session:**

```bash
# Transcribes all recordings from today, saves to transcripts/
bash scripts/transcribe_batch.sh

# Specific date and label
bash scripts/transcribe_batch.sh 20260413 mot_class
```

Output is saved to `transcripts/<date>_<label>_transcript.txt` in this repo.

---

## Knowledge Base (RAG)

Drop `.txt`, `.md`, or `.csv` files into `context/` and restart the app.
The Lab Assistant Q&A searches these files for answers.

Current content: LINE chat history (178 chunks).

---

## Health Checks

```bash
# Whisper transcriber
ssh takelab 'curl -s http://127.0.0.1:19001/health'

# Web app (via tunnel)
no_proxy=127.0.0.1 curl -s http://127.0.0.1:8088/api/health

# Web app (LAN)
curl -s http://10.10.5.59:8080/api/health

# Ollama model
ssh takelab 'curl -s http://127.0.0.1:11434/api/tags'

# List recordings
ssh takelab 'ls -lh ~/recordings/'
```

---

## Key Files

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI: WebSocket bridge, translate, ask, RAG, WAV recorder |
| `app/static/app.js` | Browser: mic capture, transcript display, streaming translation |
| `app/static/index.html` | Two-panel layout (transcript + Q&A) |
| `remote/remote_server.py` | Whisper/Vosk transcriber on takelab |
| `scripts/start_takelab_app.sh` | One-command startup |
| `scripts/transcribe_batch.sh` | Batch transcribe recordings → transcript file |
| `scripts/setup_windows_portproxy.ps1` | Windows portproxy for LAN access (run once as admin) |
| `context/` | Knowledge base files (gitignored, drop files here) |
| `transcripts/` | Session transcripts (gitignored) |
