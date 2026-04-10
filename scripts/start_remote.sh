#!/usr/bin/env bash
set -euo pipefail

REMOTE_DIR=${REMOTE_DIR:-~/remote-transcriber}

ssh takelab "mkdir -p ${REMOTE_DIR}"
scp requirements-remote.txt takelab:${REMOTE_DIR}/requirements.txt
scp remote/remote_server.py takelab:${REMOTE_DIR}/remote_server.py

ssh takelab "
set -euo pipefail
cd ${REMOTE_DIR}
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
nohup .venv/bin/uvicorn remote_server:app --host 127.0.0.1 --port 19001 > server.log 2>&1 &
echo \"remote server started on 127.0.0.1:19001\"
"
