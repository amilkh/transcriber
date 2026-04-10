# Real-time EN/JA Transcriber over SSH

This app captures microphone audio on this machine and sends it over an SSH tunnel to `takelab` for transcription using `faster-whisper`.

## Features

- Live microphone on/off button
- English and Japanese support (`en`, `ja`, or `auto` detect)
- Remote transcription on `takelab`
- Local web UI

## Architecture

1. Browser captures mic audio and streams 16kHz PCM chunks to local `/ws`.
2. Local FastAPI server proxies websocket traffic to `ws://127.0.0.1:19001/ws`.
3. SSH tunnel maps local port `19001` -> `takelab:19001`.
4. Remote FastAPI runs `faster-whisper` and streams transcript text back.

## Architecture Diagram

```mermaid
flowchart LR
	subgraph Browser[Browser at 127.0.0.1:8080]
		UI[Transcript + Q&A UI]
		Mic[Microphone PCM 16 kHz]
	end

	subgraph Local[Local WSL2 App]
		LAPI[FastAPI app.main]
		WS[WebSocket bridge /ws]
		TAPI[/api/translate]
		AAPI[/api/ask]
		RAG[RAG keyword index\ncontext/*.txt|*.md|*.csv]
	end

	subgraph Tunnel[SSH Tunnel]
		T19001[127.0.0.1:19001 -> takelab:19001]
		T11435[127.0.0.1:11435 -> takelab:11434]
	end

	subgraph Takelab[Remote takelab]
		RSTT[remote_server.py\nVosk or Whisper]
		OLL[Ollama qwen2.5:14b]
	end

	Mic --> UI
	UI -->|audio frames| LAPI
	LAPI --> WS
	WS --> T19001 --> RSTT
	RSTT -->|partial/final text| T19001 --> WS --> UI

	UI -->|translate request| TAPI
	TAPI --> T11435 --> OLL
	OLL --> T11435 --> TAPI -->|EN text| UI

	UI -->|ask question| AAPI
	RAG --> AAPI
	AAPI --> T11435 --> OLL
	OLL --> T11435 --> AAPI -->|answer| UI
```

## 1) Start remote server (on takelab)

From this workspace:

```bash
chmod +x scripts/start_remote.sh scripts/start_tunnel.sh scripts/start_local.sh
./scripts/start_remote.sh
```

Remote server log (on takelab):

```bash
ssh takelab 'tail -f ~/remote-transcriber/server.log'
```

## 2) Start SSH tunnel (local)

```bash
./scripts/start_tunnel.sh
```

Keep this terminal running.

## 3) Start local web app (local)

In a second terminal:

```bash
./scripts/start_local.sh
```

Open:

- http://localhost:8080

## Notes

- First run downloads the Whisper model and can take a while.
- Default remote model is `large-v3` on `cuda` with `float16` for strong-GPU quality.
- If CUDA is unavailable, the remote server auto-falls back to CPU `int8`.
- You can switch model by setting env var on remote:

```bash
WHISPER_MODEL=distil-large-v3 WHISPER_DEVICE=cuda WHISPER_COMPUTE=float16 ./scripts/start_remote.sh
```

## Stop remote server

```bash
ssh takelab "pkill -f 'uvicorn remote_server:app'"
```
