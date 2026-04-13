#!/usr/bin/env bash
# Batch-transcribes all WAV recordings from a given date (default: today)
# and saves a cleaned transcript to ~/transcriber/transcripts/<date>_transcript.txt
# Usage: bash transcribe_batch.sh [YYYYMMDD] [label]
# Example: bash transcribe_batch.sh 20260413 mot_class
set -euo pipefail

DATE=${1:-$(date +%Y%m%d)}
LABEL=${2:-class}
OUT_LOCAL="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)/transcripts/${DATE}_${LABEL}_transcript.txt"

echo "[1/2] Running Whisper large-v3 on takelab for date $DATE..."
ssh takelab bash << REMOTE
  source ~/remote-transcriber/.venv/bin/activate
  LD_LIBRARY_PATH=/home/amil/llm/lib/python3.10/site-packages/nvidia/cublas/lib:/usr/local/lib/ollama/cuda_v12 \
  python3 - << 'PYEOF'
import os, re
from pathlib import Path
from faster_whisper import WhisperModel

date = "$DATE"
RECORDINGS = Path.home() / "recordings"
OUT = RECORDINGS / f"{date}_${LABEL}_transcript.txt"

model = WhisperModel("large-v3", device="cuda", compute_type="float16")
files = sorted(RECORDINGS.glob(f"session_{date}_*.wav"))
if not files:
    print(f"No recordings found for {date}")
    raise SystemExit(1)
print(f"Transcribing {len(files)} file(s)...", flush=True)

GARBAGE = re.compile(
    r"^\s*[\[\(].*?[\]\)]\s*$|^\s*\.+\s*$|^\s*♪.*♪\s*$|^\s*$",
    re.IGNORECASE
)
lines, prev = [], ""
for wav in files:
    segments, _ = model.transcribe(str(wav), language="ja", beam_size=5,
        vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False, temperature=0.0)
    for seg in segments:
        t = seg.text.strip()
        if not t or GARBAGE.match(t) or t == prev:
            continue
        prev = t
        lines.append(f"[{int(seg.start//60):02d}:{int(seg.start%60):02d}] {t}")

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"Saved {len(lines)} lines → {OUT}")
PYEOF
REMOTE

echo "[2/2] Copying transcript to local..."
scp "takelab:~/recordings/${DATE}_${LABEL}_transcript.txt" "$OUT_LOCAL"
echo "Done: $OUT_LOCAL"
