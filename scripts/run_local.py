"""준비된 시세 캐시와 빌드된 화면을 로컬에서 실행한다."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
from threading import Thread
import webbrowser

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import config  # noqa: E402
from app.data_store import DataStore  # noqa: E402


class LocalServer(uvicorn.Server):
    def __init__(self, open_browser: bool, port: int):
        super().__init__(uvicorn.Config("app.main:app", host="127.0.0.1", port=port))
        self.open_browser = open_browser
        self.url = f"http://127.0.0.1:{port}/"

    async def startup(self, sockets=None):
        await super().startup(sockets=sockets)
        if self.started and self.open_browser:
            Thread(target=webbrowser.open, args=(self.url,), daemon=True).start()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않는다.")
    parser.add_argument("--port", type=int, default=8000, help="로컬 서버 포트(기본: 8000)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("포트는 1~65535 사이로 지정하세요.")
    store = DataStore()
    cache = store.path("daily_stats")
    if not cache.is_file():
        if not (ROOT / ".env").exists():
            (ROOT / ".env").write_bytes((ROOT / ".env.example").read_bytes())
        if config.env("JEJU_HUB_PROJECT_KEY").strip() in ("", "여기에_프로젝트_키"):
            print("거래 캐시가 없습니다. .env에 JEJU_HUB_PROJECT_KEY를 설정하고 다시 실행하세요.")
            return 1
        print("거래 자료를 수집합니다. 품목별 기본 품종만 받습니다.", flush=True)
        code = subprocess.call([sys.executable, str(ROOT / "scripts" / "collect.py"), "--no-weather", "--default-only"])
        if code not in (0, 2, 3) or not cache.is_file():
            return code or 1
    if any(store.collection_incomplete(item["cultivars"]["default"]) for item in config.items().values()):
        print("일부 품종의 수집이 끝나지 않았습니다. 화면에서 조회 상태를 확인하세요.", flush=True)
    server = LocalServer(not args.no_browser, args.port)
    print(f"브라우저 주소: {server.url}", flush=True)
    server.run()
    return 0 if server.started else 1


if __name__ == "__main__":
    raise SystemExit(main())
