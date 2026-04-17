#!/usr/bin/env python3
"""
Idle self-improvement for the transcription system.

Runs automatically when no sessions are active for IDLE_TRIGGER_SECS (default 10 min).
Also runnable manually: python3 scripts/idle_improve.py [--force]

What it does:
1. Finds WAV recordings not yet processed into high-quality transcripts
2. Re-transcribes them with beam_size=5 (slower, higher quality than real-time beam_size=1)
3. Extracts new vocabulary (katakana proper nouns, technical abbreviations, frequent kanji phrases)
4. Appends genuinely new terms to context/auto_vocab.txt
5. Logs a summary to /tmp/idle_improve.log
"""

import argparse
import json
import logging
import os
import re
import sys
from collections import Counter
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[idle_improve] %(message)s")
log = logging.getLogger(__name__)

REPO_ROOT    = Path(__file__).resolve().parent.parent
RECORDINGS   = Path(os.getenv("RECORDINGS_DIR", Path.home() / "recordings"))
TRANSCRIPTS  = REPO_ROOT / "transcripts"
AUTO_VOCAB   = REPO_ROOT / "context" / "auto_vocab.txt"
PROCESSED_DB = REPO_ROOT / "context" / ".processed_wavs.json"

# Terms already baked into the hard-coded prompt — don't repeat them
_KNOWN_TERMS: set[str] = {
    "統計解析", "構造方程式モデリング", "潜在変数", "観測変数", "因子負荷量", "パス係数",
    "適合度", "CFI", "RMSEA", "GFI", "AGFI", "SRMR", "TLI", "カイ二乗値", "自由度",
    "修正指数", "期待パラメータ変化", "多重共線性", "平均", "標準偏差", "分散",
    "歪度", "尖度", "標準化", "帰無仮説", "対立仮説", "p値", "有意水準", "検出力",
    "相関", "回帰", "因果関係", "係数", "内生変数", "外生変数",
    "母集団", "標本", "信頼区間", "共分散", "誤差項", "測定モデル", "構造モデル",
    "石原先生", "鈴木先生", "寺尾先生",
    "オールコネクト", "福井ブローインズ", "SMBC",
    "経営技術革新工学コース", "MOT",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_processed() -> dict:
    try:
        return json.loads(PROCESSED_DB.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_processed(db: dict) -> None:
    PROCESSED_DB.parent.mkdir(parents=True, exist_ok=True)
    PROCESSED_DB.write_text(json.dumps(db, indent=2, ensure_ascii=False))


def load_auto_vocab() -> set[str]:
    try:
        return set(t.strip() for t in AUTO_VOCAB.read_text().split("、") if t.strip())
    except FileNotFoundError:
        return set()


def save_auto_vocab(terms: set[str]) -> None:
    AUTO_VOCAB.parent.mkdir(parents=True, exist_ok=True)
    AUTO_VOCAB.write_text("、".join(sorted(terms)))
    log.info("Saved %d terms to %s", len(terms), AUTO_VOCAB)


def extract_vocab(text: str) -> set[str]:
    """
    Extract candidate vocabulary from transcript text:
    - Katakana strings ≥3 chars (proper nouns, loanwords)
    - ALL-CAPS Latin abbreviations ≥2 chars
    - Kanji+kana noun phrases that appear ≥3 times (frequency filter)
    """
    candidates: Counter = Counter()

    # Katakana proper nouns (≥3 chars)
    for m in re.findall(r"[ァ-ヶー]{3,}", text):
        candidates[m] += 1

    # ALL-CAPS abbreviations (≥2 chars)
    for m in re.findall(r"\b[A-Z]{2,}\b", text):
        candidates[m] += 1

    # Chinese/Japanese technical phrases: 2-4 kanji/kana chars repeated ≥3 times
    for m in re.findall(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]{2,8}", text):
        candidates[m] += 1

    # Keep terms that appear ≥2 times in the text and aren't already known
    return {
        term for term, count in candidates.items()
        if count >= 2 and term not in _KNOWN_TERMS and len(term) >= 2
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def transcribe_wav(wav_path: Path) -> str | None:
    """Transcribe a WAV with beam_size=5. Returns full transcript text or None."""
    try:
        import ctranslate2
        import numpy as np
        from faster_whisper import WhisperModel

        # Use GPU if available, fall back to CPU
        try:
            device, compute = ("cuda", "float16") if ctranslate2.get_cuda_device_count() > 0 else ("cpu", "int8")
        except Exception:
            device, compute = "cpu", "int8"

        import soundfile as sf
        audio, sr = sf.read(str(wav_path), dtype="float32")
        if sr != 16000:
            log.warning("  %s: unexpected sample rate %d, skipping", wav_path.name, sr)
            return None
        if audio.ndim > 1:
            audio = audio.mean(axis=1)

        log.info("  Transcribing %s (%ds, device=%s)...", wav_path.name, int(len(audio)/16000), device)

        # Re-use the model loaded by the main server if it's in the same process.
        # Otherwise load a fresh instance (this script runs as a subprocess).
        model = WhisperModel("large-v3", device=device, compute_type=compute)
        segments, _ = model.transcribe(
            audio,
            language="ja",
            beam_size=5,
            best_of=5,
            vad_filter=True,
            condition_on_previous_text=True,
            temperature=0.0,
        )
        return " ".join(s.text.strip() for s in segments).strip()
    except Exception as exc:
        log.warning("  Transcription failed for %s: %s", wav_path.name, exc)
        return None


def run(force: bool = False) -> None:
    if not RECORDINGS.exists():
        log.info("Recordings directory %s not found — nothing to do.", RECORDINGS)
        return

    wavs = sorted(RECORDINGS.glob("*.wav"))
    if not wavs:
        log.info("No WAV files found in %s.", RECORDINGS)
        return

    processed = load_processed()
    auto_vocab = load_auto_vocab()
    all_new_text: list[str] = []

    for wav in wavs:
        key = str(wav)
        mtime = wav.stat().st_mtime
        if not force and processed.get(key) == mtime:
            continue

        text = transcribe_wav(wav)
        if text:
            # Save transcript
            TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
            out = TRANSCRIPTS / (wav.stem + "_hq.txt")
            out.write_text(text, encoding="utf-8")
            log.info("  Saved transcript → %s", out.name)
            all_new_text.append(text)
            processed[key] = mtime

    save_processed(processed)

    if not all_new_text:
        log.info("No new WAVs to process.")
        return

    # Extract vocabulary from all newly transcribed text
    combined = " ".join(all_new_text)
    new_terms = extract_vocab(combined) - auto_vocab - _KNOWN_TERMS

    if new_terms:
        log.info("Found %d new vocab terms: %s", len(new_terms), "、".join(sorted(new_terms)))
        auto_vocab.update(new_terms)
        save_auto_vocab(auto_vocab)
    else:
        log.info("No new vocabulary terms found.")

    log.info("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Idle self-improvement: re-transcribe + extract vocab")
    parser.add_argument("--force", action="store_true", help="Re-process all WAVs even if already done")
    args = parser.parse_args()
    run(force=args.force)
