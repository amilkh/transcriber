# 竹本研 Seminar Assistant

Real-time Japanese/English/Mandarin transcription and translation for the Takemoto Lab seminar.
Audio is captured in the browser, transcribed on a GPU server, and translated by a local LLM —
no cloud, no data leaves the university network.

---

## Architecture

```
Browser (teacher)          GPU server (e.g. 10.10.5.60, RTX GPU)
─────────────────          ────────────────────────────────────
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

Steps 1–2 require physical access to the machine. Everything after that is SSH only.

---

### Step 1 — Install WSL2 + Ubuntu (Windows, admin PowerShell, one-time)

```powershell
wsl --install -d Ubuntu
```

Reboot when prompted. After reboot, Ubuntu opens automatically — set your Linux
username and password, then close the window.

---

### Step 2 — NVIDIA drivers + SSH + LAN access (Windows, admin PowerShell)

Install NVIDIA drivers first if not already installed:
**https://www.nvidia.com/Download/index.aspx** — select your GPU, choose Game Ready
or Studio driver, Windows version. WSL2 inherits it automatically (no Linux driver needed).

Then run these commands. Re-run after reboot only if the WSL2 IP changed
(check: `netsh interface portproxy show all`).

```powershell
# Verify GPU is visible in WSL2 (install drivers above first if this fails)
wsl -d Ubuntu -- nvidia-smi

# Install SSH, generate host keys (fixes 'connection reset' on first run), start SSH
wsl -d Ubuntu -- bash -c "sudo apt-get update -qq && sudo apt-get install -y -qq openssh-server zstd && sudo ssh-keygen -A && sudo service ssh restart && grep -q 'service ssh' ~/.bashrc || echo 'sudo service ssh start 2>/dev/null' >> ~/.bashrc"

# Get WSL2 IP
$wslIp = (wsl -d Ubuntu -- ip addr show eth0 2>$null | Select-String "inet ").ToString().Trim().Split()[1].Split("/")[0]
Write-Host "WSL2 IP: $wslIp"

# Portproxy: forward ports 22, 8080, 8443 from Windows LAN IP -> WSL2
foreach ($port in @(22, 8080, 8443)) {
    netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$port 2>$null
    netsh interface portproxy add    v4tov4 listenaddress=0.0.0.0 listenport=$port connectaddress=$wslIp connectport=$port
}

# Firewall
netsh advfirewall firewall delete rule name="transcriber" 2>$null
netsh advfirewall firewall add    rule name="transcriber" dir=in action=allow protocol=TCP localport=22,8080,8443

# Print Windows LAN IP + SSH command
$winIp = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notmatch '^(127\.|172\.|169\.)' } | Select-Object -First 1).IPAddress
Write-Host "SSH in from your laptop:  ssh <username>@$winIp"
```

You can now leave the machine — everything after this is remote.

> **Lock-screen note:** WSL2 can be suspended when Windows locks, killing SSH and
> all running processes. The script registers a Task Scheduler task (`WSL2-KeepAlive`)
> that runs `wsl -d Ubuntu -- sleep infinity` at startup/login to prevent this.
> If WSL2 still dies after a lock, re-run the script or start the task manually:
> `Start-ScheduledTask -TaskName "WSL2-KeepAlive"`

---

### Step 3 — SSH key setup (on your laptop)

Generate a key if you don't have one yet:
```bash
ls ~/.ssh/id_ed25519.pub 2>/dev/null || ssh-keygen -t ed25519
```

Copy it to the server (enter the Linux password you set in Step 1 when prompted):
```bash
ssh-copy-id -i ~/.ssh/id_ed25519.pub <username>@<windows-lan-ip>
```

Add the server to `~/.ssh/config`:
```
Host takelab2
    HostName 10.10.5.60        # replace with Windows LAN IP
    User amil                  # replace with your WSL2 username
    IdentityFile ~/.ssh/id_ed25519
    ServerAliveInterval 10
    ServerAliveCountMax 3
```

Test:
```bash
ssh takelab2 'echo ok'
```

---

### Step 4 — Install dependencies (via SSH)

```bash
ssh takelab2
sudo apt-get install -y python3 python3-venv python3-pip git zstd
```

---

### Step 5 — Clone the repo and install Python packages (via SSH)

```bash
git clone https://github.com/amilkh/transcriber.git ~/remote-transcriber
cd ~/remote-transcriber
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi "uvicorn[standard]" websockets httpx pydantic \
            faster-whisper soundfile numpy ctranslate2
```

---

### Step 6 — Install Ollama and pull the LLM (via SSH)

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &
ollama pull qwen2.5:14b
```

Verify:
```bash
curl http://127.0.0.1:11434/api/tags
```

---

### Step 7 — Find the CUDA library path (via SSH)

faster-whisper needs CUDA shared libraries at runtime. Find them:
```bash
find /usr/local/lib/ollama -name 'libcublas*' 2>/dev/null | head -2
find ~/.venv -name 'libcublas*' 2>/dev/null | head -2
python3 --version
```

Open `scripts/start_takelab_app.sh` and update the `LD_LIBRARY_PATH` line with your
paths (substitute the Python version returned above, e.g. `python3.12`).

---

### Step 8 — Generate a self-signed TLS certificate (via SSH)

Required for HTTPS on port 8443 (phones need HTTPS for microphone access):
```bash
cd ~/remote-transcriber
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 3650 -nodes \
  -subj "/CN=seminar-assistant"
```

---

## Starting the System

Run once per session from this repo **on your laptop**:

```bash
bash scripts/start_takelab_app.sh
```

This:
1. Starts Whisper large-v3 on the GPU server (port 19001)
2. Starts the web app (HTTP :8080, HTTPS :8443)
3. Opens SSH tunnels: `localhost:8088` → HTTP, `localhost:8444` → HTTPS

### Manual start (if the script fails)

```bash
# 1. Whisper transcriber
ssh takelab '
  cd ~/remote-transcriber && source .venv/bin/activate
  LD_LIBRARY_PATH=/home/amil/llm/lib/python3.10/site-packages/nvidia/cublas/lib:/usr/local/lib/ollama/cuda_v12 \
  STT_ENGINE=whisper WHISPER_MODEL=large-v3 WHISPER_DEVICE=cuda WHISPER_COMPUTE=float16 \
  nohup uvicorn remote_server:app --host 127.0.0.1 --port 19001 > /tmp/transcriber.log 2>&1 &
'

# 2. Web app
ssh takelab '
  cd ~/remote-transcriber && source .venv/bin/activate
  REMOTE_WS_URL=ws://127.0.0.1:19001/ws OLLAMA_URL=http://127.0.0.1:11434 \
  nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080 > /tmp/app.log 2>&1 &
  REMOTE_WS_URL=ws://127.0.0.1:19001/ws OLLAMA_URL=http://127.0.0.1:11434 \
  nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8443 --ssl-keyfile key.pem --ssl-certfile cert.pem > /tmp/app_ssl.log 2>&1 &
'

# 3. SSH tunnels (laptop → GPU server)
ssh -N -f -o ServerAliveInterval=10 -o ServerAliveCountMax=3 \
  -L 8088:127.0.0.1:8080 -L 8444:127.0.0.1:8443 takelab
```

---

## Accessing the App

| Who | URL | Mic |
|-----|-----|-----|
| Teacher (laptop) | `http://localhost:8088` | ✓ secure via tunnel |
| Professor / students (LAN) | `http://10.10.5.60:8080/?view` | read-only |
| Phone / tablet (LAN, HTTPS) | `https://10.10.5.60:8443/?view` | read-only |

> Replace `10.10.5.60` with your GPU server's Windows LAN IP.

**Phone setup (first time only):** Open `https://10.10.5.60:8443/?view`, tap Advanced →
Accept the self-signed certificate warning once.

**Viewer mode** (`?view`): auto-connects, shows live transcript + Lab Assistant Q&A, no mic.
Mic auto-starts on page load for the teacher URL.

---

## Language & Translation

- Default transcription: **Japanese** (`ja`)
- Switch to **Auto (JA/EN)** for mixed sessions — auto-detects per utterance, prefers JA
- Translation target: **→ English** or **→ 中文** (select in top bar)
- Silence detection: ~600 ms of quiet triggers a final entry and translation

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

---

## Health Checks

```bash
# Whisper transcriber
ssh takelab 'curl -s http://127.0.0.1:19001/health'

# Web app (via tunnel)
no_proxy=127.0.0.1 curl -s http://127.0.0.1:8088/api/health

# Web app (LAN direct)
curl -s http://10.10.5.60:8080/api/health

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
| `scripts/setup_windows_portproxy.ps1` | Windows setup: WSL2, SSH, portproxy (run as admin, re-run per reboot if IP changed) |
| `context/` | Knowledge base files (gitignored — drop files here) |
| `transcripts/` | Session transcripts (gitignored) |
