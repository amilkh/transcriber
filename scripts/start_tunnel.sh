#!/usr/bin/env bash
set -euo pipefail

# Forwards:
#   local :19001 -> takelab :19001  (vosk/whisper transcriber)
#   local :11435 -> takelab :11434  (ollama LLM — uses 11435 locally to avoid
#                                    conflict with any local ollama on 11434)
exec ssh -N \
  -L 19001:127.0.0.1:19001 \
  -L 11435:127.0.0.1:11434 \
  takelab
