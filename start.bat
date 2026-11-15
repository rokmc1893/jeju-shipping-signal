@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [출하 신호등] 시작합니다...
if not exist .venv (
  python -m venv .venv
  if errorlevel 1 goto fail
)
call .venv\Scripts\activate
if errorlevel 1 goto fail
python -c "import pandas, yaml, fastapi, uvicorn, pydantic" >nul 2>&1
if errorlevel 1 (
  python -m pip install -r requirements.txt
  if errorlevel 1 goto fail
)
if not exist .env (
  copy .env.example .env >nul
  echo .env에 프로젝트 키를 입력한 뒤 다시 실행하세요.
  notepad .env
  exit /b 0
)
if not exist frontend\dist\index.html (
  where npm >nul 2>&1
  if errorlevel 1 (
    echo 최초 화면 빌드에는 Node.js 22 LTS가 필요합니다.
    goto fail
  )
  call npm --prefix frontend ci
  if errorlevel 1 goto fail
  call npm --prefix frontend run build
  if errorlevel 1 goto fail
)
if not exist data\cache\daily_stats.csv (
  echo 거래 자료를 수집합니다. 기상 자료는 이후 별도로 수집하세요.
  python scripts\collect.py --no-weather
  if errorlevel 1 goto fail
)
if not exist data\cache\daily_stats.csv goto fail
start "" http://127.0.0.1:8000
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
exit /b %errorlevel%

:fail
echo 실행 준비에 실패했습니다. 위의 오류를 확인하세요.
pause
exit /b 1
