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

The goal is to minimise time on the physical machine — after step 2 everything
is done over SSH from your laptop.

---

### Step 1 — Windows machine (physical access, admin PowerShell)

This is the only step that requires sitting at the machine.
Open an **admin PowerShell** and run `scripts/setup_windows_portproxy.ps1`,
or paste the commands below directly.

**What it does:**
- Installs WSL2 + Ubuntu (reboots if needed — re-run after reboot)
- Installs `openssh-server` and `zstd` in WSL2
- Starts SSH so you can connect remotely
- Sets up Windows portproxy: LAN IP → WSL2 for ports 22 (SSH), 8080, 8443
- Adds firewall rules
- Prints the SSH command to use from your laptop

```powershell
# Detect WSL2 IP
$wslIp = (wsl -d Ubuntu -- ip addr show eth0 2>$null | Select-String "inet ").ToString().Trim().Split()[1].Split("/")[0]

# Install SSH + zstd in WSL2, start SSH, add to .bashrc
wsl -d Ubuntu -- bash -c "sudo apt-get update -qq && sudo apt-get install -y -qq openssh-server zstd && sudo service ssh start && grep -q 'service ssh' ~/.bashrc || echo 'sudo service ssh start 2>/dev/null' >> ~/.bashrc"

# Portproxy: forward ports 22, 8080, 8443 from Windows LAN -> WSL2
foreach ($port in @(22, 8080, 8443)) {
    netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$port 2>$null
    netsh interface portproxy add    v4tov4 listenaddress=0.0.0.0 listenport=$port connectaddress=$wslIp connectport=$port
}

# Firewall
netsh advfirewall firewall delete rule name="transcriber" 2>$null
netsh advfirewall firewall add    rule name="transcriber" dir=in action=allow protocol=TCP localport=22,8080,8443

# Print LAN IP + SSH command
$winIp = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notmatch '^(127\.|172\.|169\.)' } | Select-Object -First 1).IPAddress
Write-Host "SSH in from your laptop: ssh <username>@$winIp"
```

> **First time only:** If WSL2/Ubuntu is not installed yet, run `wsl --install -d Ubuntu`
> first, reboot, open Ubuntu from the Start menu to set your username/password, then
> run the block above.

> **Per reboot:** The portproxy may need to be re-run if the WSL2 IP changed.
> Check with `wsl -d Ubuntu -- ip addr show eth0` — if the IP is the same as the
> portproxy entry (`netsh interface portproxy show all`) no action needed.

---

### Step 2 — From your laptop (SSH only from here)

Add the server to `~/.ssh/config` on your laptop:

```
Host takelab
    HostName 10.10.5.60        # replace with Windows LAN IP printed in step 1
    User amil                  # replace with your WSL2 username
    ServerAliveInterval 10
    ServerAliveCountMax 3
```

Copy your SSH key (or use password auth for now):
```bash
ssh-copy-id amil@10.10.5.60
```

Test:
```bash
ssh takelab 'echo ok'
```

---

### Step 3 — Install NVIDIA drivers (Windows machine, one-time)

Download and install the latest driver from:
**https://www.nvidia.com/Download/index.aspx**

Select your GPU model, choose **Game Ready** or **Studio** driver, Windows version.
WSL2 inherits the Windows GPU driver automatically — no separate Linux driver needed.

Verify over SSH after install:
```bash
ssh takelab2 'nvidia-smi'
```

---

### Step 4 — Install dependencies (via SSH)

```bash
ssh takelab
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
