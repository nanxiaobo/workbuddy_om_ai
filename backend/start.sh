#!/usr/bin/env bash
# 一键启动后端并托管前端（Linux / macOS）
set -e
cd "$(dirname "$0")/backend"
python3 -m pip install -q -r requirements.txt 2>/dev/null || true
python3 -m uvicorn main:app --host 127.0.0.1 --port 61050
