"""깨끗하게 복사한 개발 트리에서 로컬 실행과 재시작을 검증한다."""

from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
import json
import os
from pathlib import Path
from statistics import quantiles
import subprocess
import tempfile
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def request(port: int, path: str, payload: dict | None = None):
    req = Request(f"http://127.0.0.1:{port}{path}",
                  data=json.dumps(payload).encode() if payload is not None else None,
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=5) as response:
        return response.read()


def wait_ready(process: subprocess.Popen, port: int) -> None:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("실행 스크립트가 서버 준비 전에 종료됐다.")
        try:
            if json.loads(request(port, "/api/health"))["data"]["daily_stats"]:
                return
        except OSError:
            time.sleep(0.5)
    raise TimeoutError("서버 준비가 180초 안에 끝나지 않았다.")


def verify(port: int) -> tuple[str, float, float]:
    lookup = {"item": "carrot", "intents": ["price_now"], "use_llm_explain": False}
    start = time.perf_counter()
    result = json.loads(request(port, "/api/ask", lookup))
    elapsed = time.perf_counter() - start
    price = result["tools"]["price_now"]
    assert result["ok"] and result["cultivar"] == "당근(일반)" and price["ok"]
    return price["date"], price["price_kg"], elapsed


def stop(process: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=True, capture_output=True)
    else:
        process.terminate()
    process.wait(timeout=15)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18767)
    parser.add_argument("--minutes", type=float, default=0)
    parser.add_argument("--sample", action="store_true", help="빈 캐시에 검사용 합성 거래를 넣는다.")
    opt = parser.parse_args()
    if (ROOT / ".env").exists():
        raise SystemExit(".env가 없는 별도의 개발 검증 폴더에서 실행하세요.")
    env = {k: v for k, v in os.environ.items()
           if k not in {"JEJU_HUB_PROJECT_KEY", "OPENAI_API_KEY", "DATA_DIR"}}
    env.update(LLM_PROVIDER="none", PYTHONUTF8="1")
    cache = ROOT / "data" / "cache"
    if opt.sample:
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "SYNTHETIC").touch()
        with (cache / "daily_stats.csv").open("x", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["date", "cultivar", "price", "volume", "amount", "closed"])
            for index in range(35, 0, -1):
                writer.writerow([date.today() - timedelta(days=index), "당근(일반)", 2000, 1, 2, False])
    cmd = ["cmd.exe", "/d", "/c", "start.bat"] if os.name == "nt" else ["bash", "start.sh"]
    with tempfile.TemporaryDirectory() as temp:
        for attempt in (1, 2):
            with (Path(temp) / "start.log").open("wb") as log:
                started_at = time.monotonic()
                process = subprocess.Popen([*cmd, "--no-browser", "--port", str(opt.port)],
                                           cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    wait_ready(process, opt.port)
                    assert "출하 신호등" in request(opt.port, "/").decode()
                    trade_day, price, elapsed = verify(opt.port)
                    assert not (ROOT / ".env").exists()
                    if opt.sample:
                        assert price == 2000
                        assert json.loads(request(opt.port, "/api/health"))["synthetic"]
                    print(f"{attempt}회 실행: 준비 {time.monotonic()-started_at:.2f}초, "
                          f"당근 {trade_day} {price:,.0f}원/kg, 응답 {elapsed:.3f}초", flush=True)
                    if attempt == 1:
                        expected_price = (trade_day, price)
                        if opt.minutes > 0:
                            times = [elapsed]
                            deadline = time.monotonic() + opt.minutes * 60
                            while time.monotonic() < deadline:
                                time.sleep(min(5, max(0, deadline - time.monotonic())))
                                current_date, current_price, value = verify(opt.port)
                                assert (current_date, current_price) == expected_price
                                times.append(value)
                            p95 = quantiles(times, n=100, method="inclusive")[94]
                            print(f"{opt.minutes:g}분 반복: {len(times)}회, 오류 0, p95 {p95:.3f}초")
                            assert p95 <= 3
                    else:
                        assert (trade_day, price) == expected_price
                except Exception:
                    print(Path(log.name).read_text(encoding="utf-8", errors="replace"))
                    raise
                finally:
                    if process.poll() is None:
                        stop(process)


if __name__ == "__main__":
    main()
