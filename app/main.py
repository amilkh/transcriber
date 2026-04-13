import asyncio
import json
import logging
import os
import threading
import wave
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Optional, Set

import httpx
import websockets
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logger = logging.getLogger("app")

REMOTE_WS_URL  = os.getenv("REMOTE_WS_URL", "ws://127.0.0.1:19001/ws")
OLLAMA_URL     = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL   = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
CONTEXT_DIR    = Path("context")
RECORDINGS_DIR = Path(os.getenv("RECORDINGS_DIR", Path.home() / "recordings"))

app = FastAPI(title="Takemoto Lab Seminar Assistant")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Single persistent client — reused across all ollama requests (no per-request TCP handshake)
_http: Optional[httpx.AsyncClient] = None

# Queues for viewer WebSocket broadcast (one queue per connected viewer)
_viewer_queues: Set[asyncio.Queue] = set()


# ---------------------------------------------------------------------------
# WAV recorder — writes incoming PCM to ~/recordings/session_<timestamp>.wav
# 16 kHz, 16-bit, mono (matches the browser PCM worklet output).
# Thread-safe: write() is called from asyncio executor threads.
# ---------------------------------------------------------------------------

class WavRecorder:
    """Opens a WAV file immediately; finalises the header on close()."""

    SAMPLE_RATE  = 16000
    SAMPLE_WIDTH = 2   # 16-bit LE
    CHANNELS     = 1

    def __init__(self) -> None:
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = RECORDINGS_DIR / f"session_{ts}.wav"
        self._wf   = wave.open(str(self.path), "wb")
        self._wf.setnchannels(self.CHANNELS)
        self._wf.setsampwidth(self.SAMPLE_WIDTH)
        self._wf.setframerate(self.SAMPLE_RATE)
        self._lock = threading.Lock()
        logger.info("Recording started: %s", self.path)

    def write(self, data: bytes) -> None:
        with self._lock:
            self._wf.writeframes(data)

    def close(self) -> None:
        with self._lock:
            self._wf.close()
        logger.info("Recording saved: %s", self.path)


# ---------------------------------------------------------------------------
# RAG index — loaded once at startup from context/
# ---------------------------------------------------------------------------

_chunks: list[str] = []
_chunk_tokens: list[set[str]] = []


def _tokenize(text: str) -> set[str]:
    tokens: set[str] = set()
    tokens.update(text.lower().split())
    for i in range(len(text) - 1):
        pair = text[i : i + 2]
        if any(ord(c) > 0x3000 for c in pair):
            tokens.add(pair)
    return tokens


def _index_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    size, step = 500, 350
    for i in range(0, max(1, len(text) - size + 1), step):
        chunk = text[i : i + size].strip()
        if len(chunk) > 40:
            _chunks.append(chunk)
            _chunk_tokens.append(_tokenize(chunk))


def _retrieve(query: str, k: int = 6) -> list[str]:
    if not _chunks:
        return []
    q_tokens = _tokenize(query)
    scores = [len(q_tokens & ct) for ct in _chunk_tokens]
    top = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
    return [_chunks[i] for i in top if scores[i] > 0]


@app.on_event("startup")
async def startup() -> None:
    global _http
    _http = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))
    if CONTEXT_DIR.exists():
        for p in CONTEXT_DIR.iterdir():
            if p.suffix in {".txt", ".md", ".csv"} and p.name != ".gitkeep":
                _index_file(p)


@app.on_event("shutdown")
async def shutdown() -> None:
    if _http:
        await _http.aclose()


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------


class TranslateRequest(BaseModel):
    text: str


class AskRequest(BaseModel):
    question: str


@app.get("/")
async def index() -> FileResponse:
    return FileResponse("app/static/index.html")


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "remote_ws_url": REMOTE_WS_URL, "ollama": OLLAMA_URL, "chunks": len(_chunks)}


@app.post("/api/translate")
async def translate(req: TranslateRequest) -> StreamingResponse:
    """Stream translation tokens as plain text — client renders them progressively."""
    if not req.text.strip():
        async def _empty():
            return
            yield
        return StreamingResponse(_empty(), media_type="text/plain; charset=utf-8")

    prompt = f"Translate to English. Reply with the translation only, no explanation.\n\n{req.text}"

    async def token_stream():
        try:
            async with _http.stream(
                "POST",
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": True,
                    "options": {"temperature": 0, "num_predict": 256},
                },
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except Exception:
                        continue
                    token = data.get("response", "")
                    if token:
                        yield token.encode()
                    if data.get("done"):
                        break
        except Exception as exc:
            logger.error("Streaming translate error: %s", exc)

    return StreamingResponse(token_stream(), media_type="text/plain; charset=utf-8")


@app.post("/api/ask")
async def ask(req: AskRequest) -> dict:
    chunks = _retrieve(req.question)
    context_text = "\n---\n".join(chunks) if chunks else "(no relevant context found)"

    prompt = (
        "You are a helpful assistant for the Takemoto Lab at the University of Fukui. "
        "Answer the question concisely using the provided lab context. "
        "If the context does not contain enough information, say so briefly.\n\n"
        f"Lab Context:\n{context_text}\n\n"
        f"Question: {req.question}\nAnswer:"
    )

    try:
        resp = await _http.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
                  "options": {"temperature": 0}},
        )
        resp.raise_for_status()
        return {"answer": resp.json().get("response", "").strip()}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# ---------------------------------------------------------------------------
# WebSocket — mic client (teacher): relays audio to remote transcriber
# and broadcasts transcript to viewer clients
# ---------------------------------------------------------------------------


@app.websocket("/ws")
async def bridge(client_ws: WebSocket) -> None:
    await client_ws.accept()

    try:
        remote_ws = await websockets.connect(
            REMOTE_WS_URL,
            ping_interval=20,
            ping_timeout=20,
            max_size=4 * 1024 * 1024,
        )
    except Exception as exc:
        await client_ws.send_text(
            json.dumps({"type": "error", "message": f"Could not connect to remote transcriber: {exc}"})
        )
        await client_ws.close()
        return

    recorder: Optional[WavRecorder] = None
    loop = asyncio.get_event_loop()

    async def client_to_remote() -> None:
        nonlocal recorder
        while True:
            msg = await client_ws.receive()
            if "bytes" in msg and msg["bytes"] is not None:
                data = msg["bytes"]
                await remote_ws.send(data)
                # Lazy-open the WAV file on first audio chunk
                if recorder is None:
                    recorder = await loop.run_in_executor(None, WavRecorder)
                await loop.run_in_executor(None, recorder.write, data)
            elif "text" in msg and msg["text"] is not None:
                await remote_ws.send(msg["text"])
            elif msg.get("type") == "websocket.disconnect":
                break

    async def remote_to_client() -> None:
        async for message in remote_ws:
            if isinstance(message, bytes):
                await client_ws.send_bytes(message)
            else:
                await client_ws.send_text(message)
                # Broadcast transcript to all viewer clients
                for q in list(_viewer_queues):
                    q.put_nowait(message)

    relay_tasks = [
        asyncio.create_task(client_to_remote()),
        asyncio.create_task(remote_to_client()),
    ]

    done, pending = await asyncio.wait(relay_tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    for task in done:
        with suppress(Exception):
            task.result()

    if recorder is not None:
        await loop.run_in_executor(None, recorder.close)

    with suppress(Exception):
        await remote_ws.close()
    with suppress(WebSocketDisconnect, RuntimeError, Exception):
        await client_ws.close()


# ---------------------------------------------------------------------------
# WebSocket — viewer client (students / professor): receive-only transcript
# ---------------------------------------------------------------------------


@app.websocket("/ws/view")
async def viewer(client_ws: WebSocket) -> None:
    await client_ws.accept()
    q: asyncio.Queue = asyncio.Queue()
    _viewer_queues.add(q)

    async def send_loop() -> None:
        while True:
            msg = await q.get()
            await client_ws.send_text(msg)

    async def recv_loop() -> None:
        while True:
            msg = await client_ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break

    tasks = [
        asyncio.create_task(send_loop()),
        asyncio.create_task(recv_loop()),
    ]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    for task in done:
        with suppress(Exception):
            task.result()

    _viewer_queues.discard(q)
    with suppress(WebSocketDisconnect, Exception):
        await client_ws.close()
