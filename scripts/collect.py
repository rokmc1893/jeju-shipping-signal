#!/usr/bin/env python3
"""데이터 적재 — 허브 Open API 실측 특성(10행 한도·페이징 없음·초당 1회) 반영판.

사용법:  python scripts/collect.py                 # 전 품목 증분(없으면 2년) + 기상(예산 내)
        python scripts/collect.py --item carrot    # 한 품목만
        python scripts/collect.py --no-weather     # 거래 통계만
        python scripts/collect.py --weather-only   # 기상만 (일 쿼터 1000 → 예산 900, 여러 날에 나눠 실행 가능)

호출 수 안내 (2년 기준)
  거래 통계: 10일 창 → 약 73콜 × 품종 수 (당근 3 + 무 2 + 양배추 2 + 마늘 1 + 양파 1 = 9품종 ≈ 660콜, 쿼터 3000)
  기상: 관측소별·일별 1콜, 출하기 7개월만 → 구좌·성산·한림 3곳 × 약 420일 ≈ 1260콜 → 2회에 나눠 실행 (예산 900/일)
       서광은 필터 없는 호출의 기본 10곳에 포함되므로 별도 호출 없이 함께 저장됨
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import config  # noqa: E402
from app.data_store import DataStore, normalize  # noqa: E402
from app.hub_client import HubClient, HubError  # noqa: E402


def collect_stats(hub: HubClient, store: DataStore, item_filter: str | None, years: int, today: date) -> None:
    for key, it in config.items().items():
        if item_filter and key != item_filter:
            continue
        for cv in it["cultivars"]["all"]:
            existing = store.stats(cv)
            last = max(existing["date"]) if not existing.empty else None
            start = (last - timedelta(days=7)) if last else today.replace(year=today.year - years)
            print(f"[{it['name']}/{cv}] {start}~{today} (점 하나 = 호출 1회 성공, x = 재시도) ", end="", flush=True)
            try:
                rows = hub.fetch_range("daily_stats", start, today, cultivar=cv)
                df = normalize(rows, "daily_stats")
                if df.empty:
                    print("\n   → 0행 (이 기간 거래 없음)")
                    continue
                merged = store.upsert("daily_stats", df, ["date", "cultivar"])
                mine = merged[merged["cultivar"] == cv]
                print(f"\n   → {len(df)}행 수신, 누적 {len(mine)}행, 최신 {max(mine['date'])}")
            except HubError as e:
                print("실패:", e)


def _season_days(start: date, end: date, months: list[int]):
    d = start
    while d <= end:
        if d.month in months:
            yield d
        d += timedelta(days=1)


def collect_weather(hub: HubClient, store: DataStore, years: int, today: date, budget: int) -> None:
    cc = config.collect_config()
    months = cc.get("weather_months", list(range(1, 13)))
    free = set(cc.get("weather_free_stations", []))
    need: list[str] = []
    for it in config.items().values():
        for s_ in [it["station"]["primary"], *it["station"].get("fallback", [])[:1]]:
            if s_ not in need:
                need.append(s_)
    filtered = [s_ for s_ in need if s_ not in free]
    print(f"[기상] 필요 관측소 {need} / 필터 호출 필요 {filtered} / 기본 응답 포함 {sorted(set(need) & free)}")

    existing = store.weather()
    start_default = today.replace(year=today.year - years)
    used = 0
    empty_streak = {}
    skipped_stations = set()
    # 1) 필터 없는 호출 (기본 10곳) — 서광 등
    jobs: list[tuple[str | None, date]] = []
    for st in [None, *filtered]:
        have = set()
        if not existing.empty:
            sub = existing if st is None else existing[existing["station"] == st]
            have = set(sub["date"]) if st is not None else set(existing[existing["station"].isin(free)]["date"])
        for d in _season_days(start_default, today - timedelta(days=1), months):
            if d not in have:
                jobs.append((st, d))
    print(f"[기상] 남은 호출 {len(jobs)}건, 이번 실행 예산 {budget}건")
    buf: list[dict] = []
    for st, d in jobs:
        if st in skipped_stations:
            continue
        if used >= budget:
            print(f"[기상] 예산 {budget}건 소진 → 내일 다시 실행하면 이어서 받습니다.")
            break
        params = {"searchDate": d.strftime("%Y%m%d")}
        if st:
            params["observatoryName"] = st
        try:
            r = hub.call(config.datasets()["weather_daily"]["data_key"], **params)
            used += 1
            if r.rows:
                buf.extend(r.rows)
                empty_streak[st] = 0
            else:
                empty_streak[st] = empty_streak.get(st, 0) + 1
            if len(buf) >= 200:
                store.upsert("weather_daily", normalize(buf, "weather_daily"), ["date", "station"])
                buf = []
            if used % 50 == 0:
                print(f"  ... {used}콜, 마지막 {d} {st or '(기본10곳)'} rows={len(r.rows)}")
            if empty_streak.get(st, 0) >= 45 and d > date(2025, 1, 1):
                print(f"  ! {d} 까지 45일 연속 자료 없음 → 허브 기상 갱신이 멈춘 구간으로 보고 이 관측소는 중단")
                empty_streak[st] = 0
                # 같은 관측소의 남은 날짜 건너뛰기
                skipped_stations.add(st)
        except HubError as e:
            print("  실패:", e)
    if buf:
        store.upsert("weather_daily", normalize(buf, "weather_daily"), ["date", "station"])
    w = store.weather()
    if not w.empty:
        print(f"[기상] 누적 {len(w)}행, 관측소 {w['station'].nunique()}곳, 기간 {min(w['date'])}~{max(w['date'])}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=None)
    ap.add_argument("--item", default=None)
    ap.add_argument("--no-weather", action="store_true")
    ap.add_argument("--weather-only", action="store_true")
    ap.add_argument("--weather-budget", type=int, default=None)
    args = ap.parse_args()

    cc = config.collect_config()
    years = args.years or cc.get("years", 2)
    budget = args.weather_budget or cc.get("weather_daily_budget", 900)
    hub = HubClient()
    store = DataStore()
    today = date.today()
    marker = store.root / "SYNTHETIC"
    if marker.exists():
        print("! 합성 데이터 캐시가 있습니다. 실데이터와 섞이지 않도록 data/cache 를 비우고 다시 실행하세요.")
        return 1

    if not args.weather_only:
        collect_stats(hub, store, args.item, years, today)
    if not args.no_weather:
        collect_weather(hub, store, years, today, budget)
    print(f"\n총 API 호출 {hub.calls}회. 캐시: {store.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
