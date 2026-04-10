import asyncio
import json
import os
from contextlib import suppress
from pathlib import Path

import httpx
import websockets
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

REMOTE_WS_URL = os.getenv("REMOTE_WS_URL", "ws://127.0.0.1:19001/ws")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
CONTEXT_DIR = Path("context")

app = FastAPI(title="Takemoto Lab Seminar Assistant")
app.mount("/static", StaticFiles(directory="app/static"), name="static")


# ---------------------------------------------------------------------------
# RAG index — loaded once at startup from context/
# Uses character-level bigrams for CJK + word tokens for ASCII.
# Good enough for a prototype demo without any extra dependencies.
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
def startup() -> None:
    if CONTEXT_DIR.exists():
        for p in CONTEXT_DIR.iterdir():
            if p.suffix in {".txt", ".md", ".csv"} and p.name != ".gitkeep":
                _index_file(p)


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
async def translate(req: TranslateRequest) -> dict:
    if not req.text.strip():
        return {"translation": ""}

    prompt = (
        "Translate the following Japanese to natural English. "
        "Reply with only the English translation, nothing else.\n\n"
        f"Japanese: {req.text}\nEnglish:"
    )

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
        return {"translation": resp.json().get("response", "").strip()}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


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
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
        return {"answer": resp.json().get("response", "").strip()}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# ---------------------------------------------------------------------------
# WebSocket bridge (unchanged — relays to remote transcriber)
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

    async def client_to_remote() -> None:
        while True:
            msg = await client_ws.receive()
            if "bytes" in msg and msg["bytes"] is not None:
                await remote_ws.send(msg["bytes"])
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

    with suppress(Exception):
        await remote_ws.close()
    with suppress(WebSocketDisconnect):
        await client_ws.close()
