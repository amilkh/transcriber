import asyncio
import json
import os
from contextlib import suppress

import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

REMOTE_WS_URL = os.getenv("REMOTE_WS_URL", "ws://127.0.0.1:19001/ws")

app = FastAPI(title="Mic to SSH Transcriber")
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse("app/static/index.html")


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "remote_ws_url": REMOTE_WS_URL}


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
            json.dumps(
                {
                    "type": "error",
                    "message": f"Could not connect to remote transcriber: {exc}",
                }
            )
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
