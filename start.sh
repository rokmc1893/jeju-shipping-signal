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
if [ ! -f .env ]; then
  cp .env.example .env
  echo ".env를 만들었습니다. 프로젝트 키를 입력한 뒤 다시 실행하세요."
  exit 0
fi
if [ ! -f frontend/dist/index.html ]; then
  command -v npm >/dev/null || { echo "최초 화면 빌드에는 Node.js 22 LTS가 필요합니다."; exit 1; }
  npm --prefix frontend ci
  npm --prefix frontend run build
fi
if [ ! -f data/cache/daily_stats.csv ]; then
  echo "거래 자료를 수집합니다. 기상 자료는 이후 별도로 수집할 수 있습니다."
  # 종료 코드 2(일부 구간 실패)·3(하루 예산 소진)은 받은 자료로 계속 진행한다. 그 밖의 실패(1 시작 불가, 130 중단)는 멈춘다.
  collect_code=0
  python scripts/collect.py --no-weather || collect_code=$?
  if [ "$collect_code" -eq 2 ] || [ "$collect_code" -eq 3 ]; then
    echo "거래 자료를 모두 받지 못했습니다. 받은 자료가 있으면 그대로 시작합니다. 나중에 python scripts/collect.py 를 다시 실행해 채우세요."
  elif [ "$collect_code" -ne 0 ]; then
    echo "거래 자료 수집을 시작하지 못했거나 중단됐습니다. 위의 안내를 확인하세요."
    exit 1
  fi
fi
[ -f data/cache/daily_stats.csv ] || { echo "거래 자료 수집에 실패했습니다. 위의 오류를 확인하세요."; exit 1; }
(sleep 2; open "http://127.0.0.1:8000" 2>/dev/null || xdg-open "http://127.0.0.1:8000" 2>/dev/null || true) &
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
