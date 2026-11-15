#!/usr/bin/env python3
"""D-11 Go/No-Go 검증 — 제주데이터허브 Open API 실호출.

사용법:  python scripts/check_api.py            (기본: 최근 60일)
        python scripts/check_api.py --days 120 --item carrot
필요:    .env 에 JEJU_HUB_PROJECT_KEY. 추가 패키지 불필요(표준 라이브러리 + PyYAML).

검증 항목
 1. URL 패턴·응답 구조 (키 마스킹해서 출력)
 2. 품목별 cultivar 문자열이 실제로 데이터를 돌려주는지 → items.yaml 의 verify 해소
 3. 최신 거래일 (2026-11 데이터가 API 로도 나오는지)
 4. 휴장일 0/0/0 패턴 비율
 5. 거래 정보의 wholesaleMarket 목록 → 제주 시장 포함 여부
 6. 기상 API 관측소 목록 → 산지 관측소(구좌·성산·한림·서광) 응답 여부
결과는 outputs/checks/check_<날짜>.json 에 저장.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import config  # noqa: E402
from app.hub_client import HubClient, HubError  # noqa: E402


def banner(t: str) -> None:
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


def check_cultivar(hub: HubClient, cultivar: str, start: date, end: date) -> dict:
    ds = config.datasets()["daily_stats"]
    try:
        r = hub.call(ds["data_key"], startDate=start.strftime("%Y%m%d"), endDate=end.strftime("%Y%m%d"), cultivar=cultivar)
    except HubError as e:
        return {"cultivar": cultivar, "ok": False, "error": str(e)}
    rows = r.rows
    dates = sorted({str(x.get("baseDate", "")) for x in rows if x.get("baseDate")})
    zero = sum(1 for x in rows if str(x.get("averagePrice", "")).strip() in ("0", "0.0", "0.00")
               and str(x.get("transactionVolume", "")).strip() in ("0", "0.0", "0.00"))
    return {
        "cultivar": cultivar, "ok": True, "status": r.status, "rows": len(rows), "total": r.total,
        "columns": sorted(rows[0].keys()) if rows else [], "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None, "zero_rows": zero, "meta": r.meta, "url": r.url,
        "sample": rows[-1] if rows else None, "elapsed_ms": r.elapsed_ms,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--item", default=None, help="items.yaml 키 하나만 검사 (carrot 등)")
    args = ap.parse_args()

    try:
        hub = HubClient()
    except HubError as e:
        print("✗", e)
        return 2
    end = date.today()
    start = end - timedelta(days=args.days)
    report: dict = {"run_at": end.isoformat(), "base_url": hub.base_url, "range": [start.isoformat(), end.isoformat()], "items": {}}

    banner("1·2·3·4  품목별 cultivar 실호출 (일일 거래 통계)")
    items = config.items()
    for key, it in items.items():
        if args.item and key != args.item:
            continue
        print(f"\n[{it['name']}]")
        found = []
        for cv in it["cultivars"]["all"]:
            res = check_cultivar(hub, cv, start, end)
            report["items"].setdefault(key, []).append(res)
            if not res["ok"]:
                print(f"  ✗ {cv:14s} 오류: {res['error']}")
                continue
            mark = "✓" if res["rows"] else "△"
            print(f"  {mark} {cv:14s} rows={res['rows']:<4} total={res['total']} 기간={res['first_date']}~{res['last_date']} 휴장(0/0)={res['zero_rows']} {res['elapsed_ms']}ms")
            if res["rows"]:
                found.append(cv)
                if res["columns"]:
                    print(f"      컬럼: {res['columns']}")
            elif res["meta"]:
                print(f"      응답 메타: {res['meta']}")
        verdict = "GO" if found else "NO-GO (cultivar 문자열 재탐색 필요)"
        print(f"  → {verdict}  확인된 품종: {found}")
        report["items"][key + "_verdict"] = verdict

    banner("5  거래 정보 → 도매시장 목록")
    try:
        ds = config.datasets()["daily_trades"]
        cv = items["carrot"]["cultivars"]["default"]
        r = hub.call(ds["data_key"], startDate=(end - timedelta(days=14)).strftime("%Y%m%d"), endDate=end.strftime("%Y%m%d"), cultivar=cv)
        markets = Counter(str(x.get("wholesaleMarket", "")) for x in r.rows)
        print(f"  rows={len(r.rows)} 시장 수={len(markets)}")
        for m, n in markets.most_common(40):
            print(f"   - {m} ({n}건)")
        jeju = [m for m in markets if "제주" in m]
        print(f"  → 제주 시장 포함: {jeju or '없음'}")
        report["markets"] = dict(markets)
        report["sample_trade"] = r.rows[0] if r.rows else None
    except HubError as e:
        print("  ✗", e)
        report["markets_error"] = str(e)

    banner("6  기상 API → 관측소 목록")
    try:
        ds = config.datasets()["weather_daily"]
        d = end - timedelta(days=1)
        r = hub.call(ds["data_key"], searchDate=d.strftime("%Y%m%d"))
        stations = sorted({str(x.get("observatoryName", "")) for x in r.rows})
        print(f"  {d} rows={len(r.rows)} 관측소={len(stations)}")
        print("  ", stations)
        need = {it["station"]["primary"] for it in items.values()}
        missing = sorted(need - set(stations))
        print(f"  → 산지 관측소 누락: {missing or '없음'} (누락 시 items.yaml fallback 사용)")
        report["stations"] = stations
        report["sample_weather"] = r.rows[0] if r.rows else None
    except HubError as e:
        print("  ✗", e)
        report["weather_error"] = str(e)

    out = ROOT / "outputs" / "checks"
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"check_{end.isoformat()}.json"
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n총 API 호출 {hub.calls}회. 보고서 저장: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
