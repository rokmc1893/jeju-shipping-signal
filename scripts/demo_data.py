#!/usr/bin/env python3
"""키 없이 프론트/데모 개발용 합성 캐시 생성 (당근·무·양배추 3품목, 2년치).

사용법: python scripts/demo_data.py
주의: 합성 데이터임을 화면에 표시할 수 있도록 data/cache/SYNTHETIC 마커 파일을 만든다. 실데이터 적재(collect.py) 전에 지우세요.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))

import synth  # noqa: E402
from app import config  # noqa: E402
from app.data_store import DataStore, normalize  # noqa: E402


def main() -> int:
    store = DataStore()
    marker = store.root / "SYNTHETIC"
    if any(store.root.glob("*.csv")) and not marker.exists():
        print("실데이터가 있는 캐시에는 합성 자료를 만들 수 없습니다. 별도 DATA_DIR를 지정하세요.")
        return 1
    marker.write_text("이 캐시는 합성 데이터입니다. 실제 시세가 아닙니다.\n", encoding="utf-8")
    end = date.today() - timedelta(days=1)
    start = end.replace(year=end.year - 2)
    for i, (key, cv, station, level) in enumerate([("carrot", "당근(일반)", "구좌", 1800), ("radish", "월동무", "성산", 700), ("cabbage", "양배추(일반)", "한림", 900)]):
        w = synth.make_weather(start, end, station, seed=10 + i)
        st, tr = synth.make_stats_and_trades(start, end, cv, w, seed=20 + i, level=level)
        store.upsert("daily_stats", normalize(st, "daily_stats"), ["date", "cultivar"])
        store.upsert("daily_trades", normalize(tr, "daily_trades"), ["date", "cultivar", "market", "corporation"])
        store.upsert("weather_daily", normalize(w, "weather_daily"), ["date", "station"])
        print(f"{config.items()[key]['name']}/{cv} 합성 {len(st)}행, 기상 {station} {len(w)}행")
    (store.root / "SYNTHETIC").write_text("이 캐시는 합성 데이터입니다. collect.py 실행 전에 삭제하세요.\n", encoding="utf-8")
    print("캐시:", store.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
