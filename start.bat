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
python scripts\run_local.py %*
if errorlevel 1 goto fail
exit /b 0

:fail
echo 실행 준비에 실패했습니다. 위의 오류를 확인하세요.
if "%~1" neq "--no-browser" pause
exit /b 1
