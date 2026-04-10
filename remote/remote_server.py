import asyncio
import json
import logging
import os
from contextlib import suppress

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from faster_whisper import WhisperModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("remote-transcriber")

MODEL_SIZE = os.getenv("WHISPER_MODEL", "small")
DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE", "int8")
MIN_SAMPLES = int(os.getenv("MIN_SAMPLES", str(16000 * 2)))
WINDOW_SAMPLES = int(os.getenv("WINDOW_SAMPLES", str(16000 * 8)))

app = FastAPI(title="Remote Whisper Server")
model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "model": MODEL_SIZE,
        "device": DEVICE,
        "compute_type": COMPUTE_TYPE,
    }


@app.websocket("/ws")
async def ws_transcribe(ws: WebSocket) -> None:
    await ws.accept()
    pcm = bytearray()
    language = "auto"
    last_sent = ""
    stop_event = asyncio.Event()

    async def transcribe_loop() -> None:
        nonlocal last_sent
        while not stop_event.is_set():
            await asyncio.sleep(0.9)

            sample_count = len(pcm) // 2
            if sample_count < MIN_SAMPLES:
                continue

            start_byte = max(0, len(pcm) - WINDOW_SAMPLES * 2)
            chunk = bytes(pcm[start_byte:])
            audio = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0

            lang_arg = None if language == "auto" else language

            segments, info = model.transcribe(
                audio,
                language=lang_arg,
                beam_size=1,
                best_of=1,
                vad_filter=True,
                condition_on_previous_text=False,
                without_timestamps=True,
                temperature=0.0,
            )

            text = " ".join(seg.text.strip() for seg in segments).strip()
            if text and text != last_sent:
                last_sent = text
                await ws.send_text(
                    json.dumps(
                        {
                            "type": "partial",
                            "text": text,
                            "lang": info.language,
                        }
                    )
                )

    task = asyncio.create_task(transcribe_loop())

    try:
        while True:
            msg = await ws.receive()
            if "bytes" in msg and msg["bytes"] is not None:
                pcm.extend(msg["bytes"])
                cap = WINDOW_SAMPLES * 2 * 4
                if len(pcm) > cap:
                    del pcm[: len(pcm) - cap]
            elif "text" in msg and msg["text"] is not None:
                payload = json.loads(msg["text"])
                ptype = payload.get("type")
                if ptype == "config":
                    selected = payload.get("language", "auto")
                    language = selected if selected in {"auto", "en", "ja"} else "auto"
                elif ptype == "stop":
                    break
            elif msg.get("type") == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket session failed")
    finally:
        stop_event.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        with suppress(Exception):
            await ws.close()
