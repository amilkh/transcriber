# 竹本研 Seminar Assistant

Real-time Japanese/English/Mandarin transcription and translation for the Takemoto Lab seminar.
Audio is captured in the browser, transcribed on a GPU server, and translated by a local LLM —
no cloud, no data leaves the university network.

---

## Architecture

```
Browser (teacher)          GPU server (e.g. takelab 10.10.5.59, RTX 5090)
─────────────────          ──────────────────────────────────────────────
Mic → PCM 16kHz  ──WS──▶  FastAPI app  ──WS──▶  Whisper large-v3 (CUDA)
                           │                        │
                           │◀── partial/final text ─┘
                           │
                           ├──POST /api/translate──▶  Ollama qwen2.5:14b
                           └──POST /api/ask       ──▶  (RAG over context/)

Browser (viewer)  ──WS──▶  /ws/view  (receive-only, no mic)
```

The GPU server runs everything. The teacher's laptop only needs a browser and SSH.
Recordings are saved as WAV files to `~/recordings/` on the GPU server.

---

## Setting Up a New GPU Server (Windows + WSL2)

Follow these steps in order on the new machine.

### 1. Enable WSL2 (Windows, admin PowerShell)

```powershell
wsl --install
# Reboot when prompted, then open Ubuntu from the Start menu to finish setup
```

If WSL is already installed but on version 1:
```powershell
wsl --set-default-version 2
```

### 2. Install NVIDIA drivers and CUDA (Windows)

- Install the latest **NVIDIA Game Ready or Studio driver** from nvidia.com (Windows version — not Linux).
- WSL2 shares the Windows GPU driver automatically; no separate Linux driver needed.
- Verify inside WSL2 after driver install:
  ```bash
  nvidia-smi
  ```

### 3. Enable SSH server in WSL2

```bash
# You may need to enable VPN to connect to apt https://www.cii.u-fukui.ac.jp/service/local/net/vpninfo.html
sudo apt update && sudo apt install -y openssh-server
# Allow password or key auth — edit /etc/ssh/sshd_config if needed
sudo service ssh start
# Make SSH start automatically (add to ~/.bashrc or use a startup task):
echo 'sudo service ssh start 2>/dev/null' >> ~/.bashrc
```

Get the WSL2 IP (needed for portproxy later):
```bash
ip addr show eth0 | grep 'inet '
# e.g. inet 172.28.250.189/20 — note this address
```

### 4. Set up SSH key access from your laptop

On your **laptop** (the machine you'll run the browser from):
```bash
# Generate a key if you don't have one
ssh-keygen -t ed25519

# Copy it to the GPU server's WSL2
ssh-copy-id <your-wsl2-username>@<windows-lan-ip>
```

Add an entry to `~/.ssh/config` on your laptop:
```
Host takelab
    HostName 10.10.5.59        # replace with the Windows LAN IP
    User amil                  # replace with your WSL2 username
    ServerAliveInterval 10
    ServerAliveCountMax 3
```

Test:
```bash
ssh takelab 'echo ok'
```

### 5. Install Python and repo dependencies (WSL2)

```bash
sudo apt install -y python3 python3-venv python3-pip git

git clone https://github.com/amilkh/transcriber.git ~/remote-transcriber
cd ~/remote-transcriber
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi "uvicorn[standard]" websockets httpx pydantic \
            faster-whisper soundfile numpy ctranslate2
```

### 6. Install Ollama and pull the LLM (WSL2)

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &         # or set up as a service
ollama pull qwen2.5:14b
```

Verify:
```bash
curl http://127.0.0.1:11434/api/tags
```

### 7. Find the CUDA library path (WSL2)

faster-whisper needs CUDA libraries at runtime. Find them:
```bash
find /usr/local/lib/ollama -name 'libcublas*' 2>/dev/null | head -3
find ~/.venv -name 'libcublas*' 2>/dev/null | head -3
# e.g. /usr/local/lib/ollama/cuda_v12 and
#      ~/llm/lib/python3.10/site-packages/nvidia/cublas/lib
```

Update `scripts/start_takelab_app.sh` with your paths (the `LD_LIBRARY_PATH` line).

### 8. Generate a self-signed TLS certificate (WSL2)

Required for HTTPS on port 8443 (needed for `getUserMedia` on phones over LAN):
```bash
cd ~/remote-transcriber
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 3650 -nodes \
  -subj "/CN=seminar-assistant"
```

### 9. Expose WSL2 to the LAN (Windows, admin PowerShell)

WSL2 is not directly reachable on the LAN — Windows portproxy bridges the gap.
This script forwards **SSH (22), HTTP (8080), and HTTPS (8443)** from the Windows
LAN IP → WSL2. Run it once per reboot (WSL2 IP changes on every restart):

```powershell
# From repo root in admin PowerShell:
.\scripts\setup_windows_portproxy.ps1
```

The script auto-detects the WSL2 IP and prints the correct SSH and app URLs when done.

> You must run this before you can SSH into WSL2 from your laptop or access the app on the LAN.

---

## Starting the System

Run this once per session from this repo **on your laptop**:

```bash
bash scripts/start_takelab_app.sh
```

This:
1. Starts Whisper large-v3 on the GPU server (port 19001)
2. Starts the web app (HTTP :8080, HTTPS :8443)
3. Opens SSH tunnels: `localhost:8088` → HTTP, `localhost:8444` → HTTPS

### Manual start (if the script fails)

```bash
# 1. Start Whisper large-v3 on GPU
ssh takelab '
  cd ~/remote-transcriber && source .venv/bin/activate
  LD_LIBRARY_PATH=/home/amil/llm/lib/python3.10/site-packages/nvidia/cublas/lib:/usr/local/lib/ollama/cuda_v12 \
  STT_ENGINE=whisper WHISPER_MODEL=large-v3 WHISPER_DEVICE=cuda WHISPER_COMPUTE=float16 \
  nohup uvicorn remote_server:app --host 127.0.0.1 --port 19001 > /tmp/transcriber.log 2>&1 &
'

# 2. Start web app
ssh takelab '
  cd ~/remote-transcriber && source .venv/bin/activate
  REMOTE_WS_URL=ws://127.0.0.1:19001/ws OLLAMA_URL=http://127.0.0.1:11434 \
  nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080 > /tmp/app.log 2>&1 &
  REMOTE_WS_URL=ws://127.0.0.1:19001/ws OLLAMA_URL=http://127.0.0.1:11434 \
  nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8443 --ssl-keyfile key.pem --ssl-certfile cert.pem > /tmp/app_ssl.log 2>&1 &
'

# 3. SSH tunnel (laptop → GPU server)
ssh -N -f -o ServerAliveInterval=10 -o ServerAliveCountMax=3 \
  -L 8088:127.0.0.1:8080 -L 8444:127.0.0.1:8443 takelab
```

---

## Accessing the App

| Who | URL | Mic |
|-----|-----|-----|
| Teacher (laptop) | `http://localhost:8088` | ✓ secure via tunnel |
| Professor / students (LAN) | `http://10.10.5.59:8080/?view` | read-only |
| Phone / tablet (LAN, HTTPS) | `https://10.10.5.59:8443/?view` | read-only |

> Replace `10.10.5.59` with your GPU server's Windows LAN IP.

**Phone setup (first time only):** Open `https://10.10.5.59:8443/?view`, tap Advanced →
Accept the self-signed certificate warning once.

**Viewer mode** (`?view`): auto-connects, shows live transcript + Lab Assistant Q&A, no mic.

---

## Language & Translation

- Default transcription: **Japanese** (`ja`)
- Switch to **Auto (JA/EN)** for mixed sessions — auto-detects per utterance, prefers JA
- Translation target: **→ English** or **→ 中文** (select in top bar)
- Silence detection: ~600 ms of quiet triggers a final transcript entry and translation

---

## Recordings & Transcripts

Recordings are saved automatically to `~/recordings/` on the GPU server as WAV files
(16 kHz, 16-bit mono) whenever the mic is active.

**Batch transcribe a session:**

```bash
# Transcribes all recordings from today, saves to transcripts/
bash scripts/transcribe_batch.sh

# Specific date and label
bash scripts/transcribe_batch.sh 20260413 mot_class
```

Output: `transcripts/<date>_<label>_transcript.txt`

---

## Knowledge Base (Lab Assistant RAG)

Drop `.txt`, `.md`, or `.csv` files into `context/` and restart the web app.
The Lab Assistant answers questions by searching these files **and** the current
session's transcript (last 50 utterances).

Current content: LINE chat history (178 chunks).

---

## Health Checks

```bash
# Whisper transcriber (on GPU server)
ssh takelab 'curl -s http://127.0.0.1:19001/health'

# Web app (via tunnel)
no_proxy=127.0.0.1 curl -s http://127.0.0.1:8088/api/health

# Web app (LAN direct)
curl -s http://10.10.5.59:8080/api/health

# Ollama
ssh takelab 'curl -s http://127.0.0.1:11434/api/tags'

# List recordings
ssh takelab 'ls -lh ~/recordings/'

# Live logs
ssh takelab 'tail -f /tmp/transcriber.log'
ssh takelab 'tail -f /tmp/app.log'
```

---

## Key Files

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI: WebSocket bridge, translate, ask, RAG, WAV recorder |
| `app/static/app.js` | Browser: mic capture, transcript display, streaming translation |
| `app/static/index.html` | Two-panel layout (transcript + Q&A) |
| `remote/remote_server.py` | Whisper transcriber (runs on GPU server) |
| `scripts/start_takelab_app.sh` | One-command startup (run from laptop) |
| `scripts/transcribe_batch.sh` | Batch transcribe recordings → transcript file |
| `scripts/setup_windows_portproxy.ps1` | Windows portproxy for LAN access (run once as admin per reboot) |
| `context/` | Knowledge base files (gitignored — drop files here) |
| `transcripts/` | Session transcripts (gitignored) |
