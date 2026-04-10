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
- Default remote model is `small` (decent quality/speed on CPU).
- You can switch model by setting env var on remote:

```bash
ssh takelab 'cd ~/remote-transcriber && source .venv/bin/activate && WHISPER_MODEL=medium uvicorn remote_server:app --host 127.0.0.1 --port 19001'
```

## Stop remote server

```bash
ssh takelab "pkill -f 'uvicorn remote_server:app'"
```
