#!/usr/bin/env bash
set -euo pipefail

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-local.txt

REMOTE_WS_URL=${REMOTE_WS_URL:-ws://127.0.0.1:19001/ws}
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080
