#!/usr/bin/env python3
"""macOS에서 로컬 서버와 갤럭시 크기 Android 앱을 함께 실행한다."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / "frontend"
LOGS = ROOT / "outputs" / "mobile-dev"
AVD = "Jeju_Galaxy_S24"
PACKAGE = "io.github.rokmc1893.jejusignal"


def ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            body = response.read().decode("utf-8")
            if url.endswith("/api/health"):
                import json
                data = json.loads(body)
                return response.status == 200 and "data" in data and "llm" in data
            return response.status == 200 and "출하 신호등" in body
    except (OSError, urllib.error.URLError, ValueError):
        return False


def main() -> int:
    LOGS.mkdir(parents=True, exist_ok=True)
    children = []
    handles = []
    emulator = None

    def start(args, name, cwd=ROOT, env=None):
        handle = (LOGS / f"{name}.log").open("a")
        handles.append(handle)
        child = subprocess.Popen(args, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT)
        children.append(child)
        return child

    def run(args, cwd=ROOT, env=None):
        subprocess.run(args, cwd=cwd, env=env, check=True)

    def tool(name):
        found = shutil.which(name)
        if not found:
            raise RuntimeError(f"{name}을 찾지 못했습니다. Android SDK 도구 경로를 PATH에 추가하세요.")
        return found

    def serial_for_avd(adb):
        devices = subprocess.check_output([adb, "devices"], text=True).splitlines()[1:]
        for line in devices:
            parts = line.split()
            if len(parts) < 2 or parts[1] != "device" or not parts[0].startswith("emulator-"):
                continue
            name = subprocess.check_output([adb, "-s", parts[0], "emu", "avd", "name"], text=True)
            if name.splitlines()[0] == AVD:
                return parts[0]
        return None

    try:
        python = ROOT / ".venv" / "bin" / "python"
        if not python.exists() or not (FRONT / "node_modules").exists():
            raise RuntimeError("먼저 Python 가상환경·requirements.txt와 frontend의 npm ci 설치를 완료하세요.")
        adb, emulator_tool = tool("adb"), tool("emulator")
        if AVD not in subprocess.check_output([emulator_tool, "-list-avds"], text=True).splitlines():
            raise RuntimeError(f"{AVD} 가상 기기를 먼저 만들어 주세요. docs/MOBILE.md를 참조하세요.")
        env = os.environ.copy()
        env.update(DATA_DIR=str(LOGS / "cache"), LLM_PROVIDER="none")
        if not (LOGS / "cache" / "daily_stats.csv").exists():
            run([str(python), "scripts/demo_data.py"], env=env)
        if not ready("http://127.0.0.1:8000/api/health"):
            start([str(python), "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--reload", "--reload-dir", "backend", "--port", "8000"], "backend", env=env)
        if not ready("http://127.0.0.1:5173"):
            start(["npm", "run", "dev", "--", "--host", "127.0.0.1", "--strictPort"], "frontend", cwd=FRONT)
        for _ in range(30):
            if ready("http://127.0.0.1:8000/api/health") and ready("http://127.0.0.1:5173"):
                break
            time.sleep(1)
        else:
            raise RuntimeError(f"개발 서버 시작에 실패했습니다. {LOGS}의 로그를 확인하세요.")
        serial = serial_for_avd(adb)
        if not serial:
            emulator = start([emulator_tool, "-avd", AVD, "-no-boot-anim", "-gpu", "host"], "emulator")
        for _ in range(120):
            serial = serial_for_avd(adb)
            if serial and subprocess.check_output([adb, "-s", serial, "shell", "getprop", "sys.boot_completed"], text=True).strip() == "1":
                break
            time.sleep(1)
        else:
            raise RuntimeError("Android 부팅을 완료하지 못했습니다. 에뮬레이터 창을 확인하세요.")
        run(["npm", "run", "build"], cwd=FRONT)
        native_env = os.environ.copy()
        native_env["CAPACITOR_DEV_SERVER_URL"] = "http://localhost:5173"
        run(["npx", "cap", "sync", "android"], cwd=FRONT, env=native_env)
        sdk = Path(adb).resolve().parent.parent
        (FRONT / "android" / "local.properties").write_text(f"sdk.dir={sdk}\n")
        run(["./gradlew", ":app:assembleDebug"], cwd=FRONT / "android")
        run([adb, "-s", serial, "reverse", "tcp:5173", "tcp:5173"])
        run([adb, "-s", serial, "install", "-r", str(FRONT / "android/app/build/outputs/apk/debug/app-debug.apk")])
        run([adb, "-s", serial, "shell", "am", "force-stop", PACKAGE])
        run([adb, "-s", serial, "shell", "am", "start", "-n", f"{PACKAGE}/.MainActivity"])
        print("출하 신호등 앱을 열었습니다. 화면 수정은 자동 반영됩니다. 종료는 Ctrl+C입니다.")
        print("Google 로그인은 필요하지 않습니다. 이 디버그 앱은 다른 사람에게 배포하지 마세요.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print(f"모바일 개발 실행 실패: {error}")
        return 1
    finally:
        for child in reversed(children):
            if child is emulator:
                continue  # 사용자가 보고 있는 에뮬레이터는 남겨 둔다.
            child.terminate()
        for handle in handles:
            handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
