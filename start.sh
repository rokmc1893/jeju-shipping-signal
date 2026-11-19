#!/bin/bash
# 출하 신호등 — macOS/Linux 실행 스크립트
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "가상환경을 만드는 중..."
  python3 -m venv .venv
fi
source .venv/bin/activate
if ! python -c "import pandas, yaml, fastapi, uvicorn, pydantic" >/dev/null 2>&1; then
  python -m pip install -r requirements.txt
fi
if [ ! -f frontend/dist/index.html ]; then
  command -v npm >/dev/null || { echo "최초 화면 빌드에는 Node.js 22 LTS가 필요합니다."; exit 1; }
  npm --prefix frontend ci
  npm --prefix frontend run build
fi
exec python scripts/run_local.py "$@"
