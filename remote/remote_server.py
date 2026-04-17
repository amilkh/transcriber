import asyncio
import json
import logging
import os
from contextlib import suppress
from threading import Lock
from typing import Optional

import ctranslate2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from faster_whisper import WhisperModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("remote-transcriber")

MODEL_SIZE = os.getenv("WHISPER_MODEL", "large-v3")
DEVICE = os.getenv("WHISPER_DEVICE", "cuda")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE", "float16")
MIN_SAMPLES = int(os.getenv("MIN_SAMPLES", str(16000)))
WINDOW_SAMPLES = int(os.getenv("WINDOW_SAMPLES", str(16000 * 6)))
TRANSCRIBE_INTERVAL = float(os.getenv("TRANSCRIBE_INTERVAL", "0.6"))
VAD_FILTER = os.getenv("VAD_FILTER", "false").lower() == "true"
ENGINE = os.getenv("STT_ENGINE", "auto").lower()

# Domain vocabulary prompt — primes the Whisper decoder to prefer these tokens.
# Override with WHISPER_PROMPT env var; set to "" to disable.
_DEFAULT_PROMPT = (
    "統計解析、構造方程式モデリング、潜在変数、観測変数、因子負荷量、パス係数、"
    "適合度、CFI、RMSEA、GFI、AGFI、SRMR、TLI、カイ二乗値、自由度、"
    "修正指数、期待パラメータ変化、多重共線性、"
    "平均、標準偏差、分散、歪度、尖度、標準化、"
    "帰無仮説、対立仮説、p値、有意水準、検出力、"
    "相関、回帰、因果関係、係数、内生変数、外生変数、"
    "母集団、標本、信頼区間、共分散、誤差項、測定モデル、構造モデル"
)
INITIAL_PROMPT: str | None = os.getenv("WHISPER_PROMPT", _DEFAULT_PROMPT) or None
VOSK_SCRIPT = os.getenv("VOSK_STREAM_SCRIPT", os.path.expanduser("~/voice/remote_stream_stt.py"))

app = FastAPI(title="Remote Whisper Server")


def resolve_engine() -> str:
    if ENGINE in {"vosk", "whisper"}:
        return ENGINE
    if os.path.isfile(VOSK_SCRIPT):
        return "vosk"
    return "whisper"


ACTIVE_ENGINE = resolve_engine()


def resolve_runtime() -> tuple[str, str]:
    # Use GPU-first defaults, but avoid hard failure if CUDA is missing.
    device = DEVICE
    compute = COMPUTE_TYPE
    if device == "cuda":
        try:
            if ctranslate2.get_cuda_device_count() == 0:
                logger.warning("CUDA requested but not available; falling back to CPU int8")
                return "cpu", "int8"
        except Exception:
            logger.warning("Could not detect CUDA devices; falling back to CPU int8")
            return "cpu", "int8"
    return device, compute


RUNTIME_DEVICE, RUNTIME_COMPUTE = resolve_runtime()
model: WhisperModel | None = None
model_lock = Lock()


def _run_warmup(test_model: WhisperModel) -> None:
    # Run a tiny inference to catch missing CUDA runtime libs early.
    warmup_audio = np.zeros(16000, dtype=np.float32)
    segments, _ = test_model.transcribe(
        warmup_audio,
        language="en",
        beam_size=1,
        best_of=1,
        vad_filter=False,
        condition_on_previous_text=False,
        without_timestamps=True,
        temperature=0.0,
    )
    # Force eager execution to surface backend errors now.
    _ = list(segments)


def _load_model(device: str, compute_type: str) -> WhisperModel:
    loaded = WhisperModel(MODEL_SIZE, device=device, compute_type=compute_type)
    _run_warmup(loaded)
    return loaded


def _is_cuda_runtime_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    needles = ["libcublas", "libcudnn", "cuda", "cublas", "cannot be loaded"]
    return any(n in msg for n in needles)


def ensure_model() -> None:
    global model, RUNTIME_DEVICE, RUNTIME_COMPUTE
    with model_lock:
        if model is not None:
            return
        try:
            model = _load_model(RUNTIME_DEVICE, RUNTIME_COMPUTE)
        except Exception as exc:
            if RUNTIME_DEVICE == "cuda" and _is_cuda_runtime_error(exc):
                logger.warning("CUDA runtime unavailable, falling back to CPU int8: %s", exc)
                RUNTIME_DEVICE, RUNTIME_COMPUTE = "cpu", "int8"
                model = _load_model(RUNTIME_DEVICE, RUNTIME_COMPUTE)
            else:
                raise


def force_cpu_fallback() -> None:
    global model, RUNTIME_DEVICE, RUNTIME_COMPUTE
    with model_lock:
        RUNTIME_DEVICE, RUNTIME_COMPUTE = "cpu", "int8"
        model = _load_model(RUNTIME_DEVICE, RUNTIME_COMPUTE)


if ACTIVE_ENGINE == "whisper":
    ensure_model()


@app.get("/health")
async def health() -> dict:
    payload = {
        "ok": True,
        "engine": ACTIVE_ENGINE,
        "model": MODEL_SIZE,
        "device": RUNTIME_DEVICE,
        "compute_type": RUNTIME_COMPUTE,
    }
    if ACTIVE_ENGINE == "vosk":
        payload["vosk_script"] = VOSK_SCRIPT
    return payload


@app.websocket("/ws")
async def ws_transcribe(ws: WebSocket) -> None:
    if ACTIVE_ENGINE == "vosk":
        await ws_transcribe_vosk(ws)
        return
    await ws_transcribe_whisper(ws)


SILENCE_RMS_THRESHOLD = float(os.getenv("SILENCE_RMS", "0.008"))  # ~-42 dB
SILENCE_CHUNKS_FINAL  = int(os.getenv("SILENCE_CHUNKS", "3"))      # 3 × 200 ms = 600 ms

# Lower = more aggressive silence filtering (0.0–1.0; default faster-whisper=0.6).
# Note: common hallucinations have high logprob so this alone won't catch them;
# the _HALLUCINATIONS blocklist below is the primary guard.
NO_SPEECH_THRESHOLD = float(os.getenv("NO_SPEECH_THRESHOLD", "0.5"))

# Known Whisper hallucinations to silently discard (exact match after strip)
_HALLUCINATIONS: set[str] = {
    "ご視聴ありがとうございました",
    "ありがとうございました",
    "字幕は自動生成されています",
    "字幕制作",
    "チャンネル登録をお願いします",
    "お疲れ様でした",
    "ご清聴ありがとうございました",
    "モデルの設定",
    "設定",
    "コンプリート",
    "このようなモデルを使用することができます",
    "このようなモデルを使用することができます。",
    "モデルパーティー数分間",
    "Thank you for watching.",
    "Thank you for watching",
    "Please subscribe.",
    "Subtitles by",
    "[Music]",
    "[Applause]",
    "[Laughter]",
}


def _is_hallucination(text: str) -> bool:
    t = text.strip().rstrip("。．.")
    return t in _HALLUCINATIONS or text.strip() in _HALLUCINATIONS


def _is_repetitive_loop(text: str) -> bool:
    """Detect Whisper looping: same short phrase repeated many times."""
    # Split on common Japanese/English delimiters
    parts = [p.strip() for p in text.replace("、", ",").replace("。", ",").split(",") if p.strip()]
    if len(parts) < 4:
        return False
    unique = set(parts)
    # If fewer than 30% of segments are unique, it's a loop
    return len(unique) / len(parts) < 0.3


def _chunk_rms(data: bytes) -> float:
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(samples ** 2))) / 32768.0


PARTIAL_TIMEOUT = float(os.getenv("PARTIAL_TIMEOUT", "3.0"))  # commit partial as final after this many seconds unchanged


async def ws_transcribe_whisper(ws: WebSocket) -> None:
    await ws.accept()
    pcm              = bytearray()
    language         = "auto"
    last_sent        = ""
    last_lang        = "ja"
    silent_count     = 0      # consecutive silent 200-ms chunks
    last_sent_time   = 0.0    # when last_sent was last updated
    stop_event       = asyncio.Event()

    async def transcribe_loop() -> None:
        nonlocal last_sent, last_lang, last_sent_time
        while not stop_event.is_set():
            await asyncio.sleep(TRANSCRIBE_INTERVAL)
            if len(pcm) // 2 < MIN_SAMPLES:
                continue

            # Time-based fallback: if partial hasn't changed for PARTIAL_TIMEOUT seconds, commit it
            if last_sent and (asyncio.get_event_loop().time() - last_sent_time) >= PARTIAL_TIMEOUT:
                await ws.send_text(json.dumps({"type": "final", "text": last_sent, "lang": last_lang}))
                del pcm[:]
                last_sent = ""
                silent_count = 0
                continue

            start_byte = max(0, len(pcm) - WINDOW_SAMPLES * 2)
            chunk = bytes(pcm[start_byte:])
            audio = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
            lang_arg = None if language == "auto" else language

            try:
                segments, info = model.transcribe(
                    audio,
                    language=lang_arg,
                    beam_size=1,
                    best_of=1,
                    vad_filter=VAD_FILTER,
                    condition_on_previous_text=False,
                    without_timestamps=True,
                    temperature=0.0,
                    initial_prompt=INITIAL_PROMPT,
                    no_speech_threshold=NO_SPEECH_THRESHOLD,
                )
            except Exception as exc:
                if RUNTIME_DEVICE == "cuda" and _is_cuda_runtime_error(exc):
                    try:
                        force_cpu_fallback()
                        await ws.send_text(json.dumps({"type": "status", "message": "CUDA libs missing, switched to CPU int8"}))
                        continue
                    except Exception:
                        logger.exception("CPU fallback failed")
                logger.exception("Transcription failed")
                await ws.send_text(json.dumps({"type": "error", "message": f"Transcription error: {exc}"}))
                continue

            text = " ".join(seg.text.strip() for seg in segments).strip()
            if text and text != last_sent and not _is_hallucination(text) and not _is_repetitive_loop(text):
                last_sent = text
                last_lang = info.language
                last_sent_time = asyncio.get_event_loop().time()
                await ws.send_text(json.dumps({"type": "partial", "text": text, "lang": info.language}))

    task = asyncio.create_task(transcribe_loop())
    await ws.send_text(
        json.dumps(
            {
                "type": "status",
                "message": (
                    f"Remote ready ({MODEL_SIZE}, {RUNTIME_DEVICE}/{RUNTIME_COMPUTE}, "
                    f"vad_filter={VAD_FILTER})"
                ),
            }
        )
    )

    try:
        while True:
            msg = await ws.receive()
            if "bytes" in msg and msg["bytes"] is not None:
                data = msg["bytes"]
                pcm.extend(data)
                cap = WINDOW_SAMPLES * 2 * 4
                if len(pcm) > cap:
                    del pcm[: len(pcm) - cap]

                # Silence detection — emit final when mic goes quiet after speech
                if _chunk_rms(data) < SILENCE_RMS_THRESHOLD:
                    silent_count += 1
                    if silent_count == SILENCE_CHUNKS_FINAL and last_sent:
                        await ws.send_text(json.dumps({"type": "final", "text": last_sent, "lang": last_lang}))
                        del pcm[:]
                        last_sent = ""
                        silent_count = 0
                else:
                    silent_count = 0

            elif "text" in msg and msg["text"] is not None:
                payload = json.loads(msg["text"])
                ptype = payload.get("type")
                if ptype == "config":
                    selected = payload.get("language", "auto")
                    language = selected if selected in {"auto", "en", "ja"} else "auto"
                    await ws.send_text(json.dumps({"type": "status", "message": f"Language set to {language}"}))
                elif ptype == "stop":
                    break
            elif msg.get("type") == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket session failed")
    finally:
        # Flush any remaining partial as final
        if last_sent:
            with suppress(Exception):
                await ws.send_text(json.dumps({"type": "final", "text": last_sent, "lang": last_lang}))
        stop_event.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        with suppress(Exception):
            await ws.close()


async def ws_transcribe_vosk(ws: WebSocket) -> None:
    await ws.accept()
    language = "auto"
    proc: Optional[asyncio.subprocess.Process] = None
    reader_task: Optional[asyncio.Task] = None

    async def start_proc(lang: str) -> tuple[asyncio.subprocess.Process, asyncio.Task]:
        if not os.path.isfile(VOSK_SCRIPT):
            raise FileNotFoundError(f"Vosk stream script not found: {VOSK_SCRIPT}")

        cmd = [
            "python3",
            VOSK_SCRIPT,
            "--sample-rate",
            "16000",
            "--language",
            lang,
        ]
        p = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def read_stdout() -> None:
            assert p.stdout is not None
            while True:
                line = await p.stdout.readline()
                if not line:
                    break
                raw = line.decode("utf-8", errors="replace").strip()
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except Exception:
                    await ws.send_text(json.dumps({"type": "error", "message": raw}))
                    continue

                ptype = payload.get("type")
                if ptype == "result":
                    await ws.send_text(
                        json.dumps(
                            {
                                "type": "final",
                                "text": payload.get("text", ""),
                                "lang": payload.get("language", lang),
                            }
                        )
                    )
                elif ptype == "partial":
                    await ws.send_text(
                        json.dumps(
                            {
                                "type": "partial",
                                "text": payload.get("text", ""),
                                "lang": payload.get("language", lang),
                            }
                        )
                    )
                else:
                    await ws.send_text(json.dumps(payload))

        return p, asyncio.create_task(read_stdout())

    async def stop_proc() -> None:
        nonlocal proc, reader_task
        if proc is None:
            return

        if proc.stdin is not None:
            with suppress(Exception):
                proc.stdin.close()

        with suppress(Exception):
            await asyncio.wait_for(proc.wait(), timeout=1.5)
        if proc.returncode is None:
            with suppress(Exception):
                proc.terminate()
            with suppress(Exception):
                await asyncio.wait_for(proc.wait(), timeout=1.5)
        if proc.returncode is None:
            with suppress(Exception):
                proc.kill()

        if reader_task is not None:
            reader_task.cancel()
            with suppress(asyncio.CancelledError):
                await reader_task

        proc = None
        reader_task = None

    try:
        proc, reader_task = await start_proc(language)
        await ws.send_text(
            json.dumps(
                {
                    "type": "status",
                    "message": f"Remote ready (vosk, language={language})",
                }
            )
        )

        while True:
            msg = await ws.receive()
            if "bytes" in msg and msg["bytes"] is not None:
                if proc is None or proc.stdin is None:
                    await ws.send_text(json.dumps({"type": "error", "message": "Vosk process not running"}))
                    continue
                proc.stdin.write(msg["bytes"])
                await proc.stdin.drain()
            elif "text" in msg and msg["text"] is not None:
                payload = json.loads(msg["text"])
                ptype = payload.get("type")
                if ptype == "config":
                    selected = payload.get("language", "auto")
                    selected = selected if selected in {"auto", "en", "ja"} else "auto"
                    if selected != language:
                        language = selected
                        await stop_proc()
                        proc, reader_task = await start_proc(language)
                    await ws.send_text(
                        json.dumps(
                            {
                                "type": "status",
                                "message": f"Language set to {language}",
                            }
                        )
                    )
                elif ptype == "stop":
                    break
            elif msg.get("type") == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception("Vosk websocket session failed")
        with suppress(Exception):
            await ws.send_text(json.dumps({"type": "error", "message": f"Vosk error: {exc}"}))
    finally:
        await stop_proc()
        with suppress(Exception):
            await ws.close()
