#!/usr/bin/env python3
"""수집한 CSV 캐시 검증 — 허브를 호출하지 않고 로컬 파일만 읽는다.

사용법:  python scripts/validate_cache.py                  # 기본 캐시(data/cache) 전체 품종
        python scripts/validate_cache.py --default-only   # 품목별 기본 품종만 필수로 본다
        python scripts/validate_cache.py --item carrot    # 한 품목만
        python scripts/validate_cache.py --data-dir outputs/local-demo/cache --allow-synthetic
        python scripts/validate_cache.py --json           # 기계가 읽을 수 있는 결과

확인 항목
  거래 통계: 파일·필수 열, 날짜 형식, (날짜, 품종) 중복, 미래 날짜, 품종 문자열, 품종별 행 수·기간·최신일,
            음수·0원 가격, 가격 범위(원/kg), 휴장일이 아닌데 가격이 빈 행, 날짜 공백(누락 구간 의심),
            단위 일치(거래금액[백만원] ≈ 평균가[원/kg] × 거래량[톤] ÷ 1000)
  기상:     필수 열, (날짜, 관측소) 중복, 필요한 관측소, 기온·강수 범위
  수집 범위: 품종별 첫 날짜가 수집 기간(기본 2년) 시작보다 크게 늦지 않은지, 기본 품종 거래일 수
  수집 상태: collect_state.json 의 실패 구간·미완료 상태, 합성 자료 표시(SYNTHETIC), 남은 임시 파일
  ※ 거래 통계에는 산지 필드가 없다. 전국 공영도매시장 기준이며 산지 범위는 이 도구로 검증할 수 없다.

종료 코드: 0 통과(경고는 허용) / 1 오류 있음 / 2 --strict 에서 경고 있음
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import config  # noqa: E402

STATE_FILE = "collect_state.json"
STATS_REQUIRED = ["date", "cultivar", "price", "volume", "amount"]
WEATHER_REQUIRED = ["date", "station", "temp_min", "rain"]
PRICE_RANGE = (10.0, 100_000.0)     # 원/kg - 벗어나면 단위·파싱 오류 의심
TEMP_RANGE = (-30.0, 45.0)          # ℃
UNIT_TOLERANCE = 0.05               # 거래금액 대조 허용 오차(중앙값 기준)
START_SLACK_DAYS = 45               # 첫 날짜가 수집 기간 시작보다 이만큼 넘게 늦으면 앞 구간 누락 의심
MIN_TRADING_DAYS_PER_YEAR = 100     # 기본 품종의 연간 거래일 하한(출하기만 거래되는 품종 고려)
STATE_NOT_DONE = {"quota": "하루 예산 소진으로 중단", "aborted": "연속 실패로 중단", "running": "실행 도중 중단",
                  "empty": "받은 자료 0행", "partial": "실패 구간 남음"}


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)
    cultivars: dict = field(default_factory=dict)
    weather: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings, "info": self.info,
                "cultivars": self.cultivars, "weather": self.weather}


def _read_csv(path: Path, rep: Report, label: str) -> pd.DataFrame | None:
    try:
        return pd.read_csv(path, encoding="utf-8")
    except Exception as e:  # 빈 파일·깨진 CSV·인코딩 오류를 모두 '읽을 수 없음'으로 보고한다
        rep.errors.append(f"{label}: 파일을 읽을 수 없습니다 ({type(e).__name__}: {e})")
        return None


def _parse_dates(df: pd.DataFrame, rep: Report, label: str) -> pd.DataFrame:
    parsed = pd.to_datetime(df["date"], errors="coerce")
    bad = int(parsed.isna().sum())
    if bad:
        rep.errors.append(f"{label}: 날짜를 읽을 수 없는 행 {bad}개")
    df = df.loc[parsed.notna()].copy()
    df["date"] = parsed[parsed.notna()].dt.date
    return df


def _scope(items: list[str] | None, default_only: bool) -> tuple[list[str], list[str], list[str]]:
    """(필수 품종, 선택 품종, 필요한 관측소)"""
    required, optional, stations = [], [], []
    for key, it in config.items().items():
        if items and key not in items:
            continue
        required.append(it["cultivars"]["default"])
        if not default_only:
            optional += [c for c in it["cultivars"]["all"] if c != it["cultivars"]["default"]]
        if it["station"]["primary"] not in stations:
            stations.append(it["station"]["primary"])
    return required, optional, stations


def _years_ago(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:  # 2월 29일
        return d.replace(year=d.year - years, day=28)


def _gaps(dates: list[date], max_gap_days: int) -> list[tuple[date, date, int]]:
    out = []
    for a, b in zip(dates, dates[1:]):
        if (b - a).days > max_gap_days:
            out.append((a, b, (b - a).days))
    return out


def _check_stats(root: Path, rep: Report, today: date, required: list[str], optional: list[str],
                 max_stale_days: int, max_gap_days: int, years: int) -> None:
    path = root / "daily_stats.csv"
    if not path.exists():
        rep.errors.append("거래 통계: daily_stats.csv 가 없습니다. 먼저 scripts/collect.py 를 실행하세요.")
        return
    df = _read_csv(path, rep, "거래 통계")
    if df is None:
        return
    missing = [c for c in STATS_REQUIRED if c not in df.columns]
    if missing:
        rep.errors.append(f"거래 통계: 필수 열이 없습니다 {missing}")
        return
    if df.empty:
        rep.errors.append("거래 통계: 행이 없습니다.")
        return
    if "closed" not in df.columns:
        rep.warnings.append("거래 통계: closed(휴장) 열이 없습니다. 휴장일 처리를 확인하세요.")
    df = _parse_dates(df, rep, "거래 통계")
    df["cultivar"] = df["cultivar"].astype(str).str.strip()
    for c in ("price", "volume", "amount"):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    dup = int(df.duplicated(subset=["date", "cultivar"]).sum())
    if dup:
        rep.errors.append(f"거래 통계: (날짜, 품종) 중복 행 {dup}개")
    future = int((df["date"] > today).sum())
    if future:
        rep.errors.append(f"거래 통계: 기준일({today}) 이후 날짜 행 {future}개")

    known = set(required) | set(optional)
    all_known = {c for it in config.items().values() for c in it["cultivars"]["all"]}
    present = set(df["cultivar"].unique())
    for cv in sorted(present - all_known):
        rep.warnings.append(f"거래 통계: 설정에 없는 품종 문자열 '{cv}'")
    for cv in required:
        if cv not in present:
            rep.errors.append(f"거래 통계: 기본 품종 '{cv}' 자료가 없습니다.")
    for cv in optional:
        if cv not in present:
            rep.warnings.append(f"거래 통계: 품종 '{cv}' 자료가 없습니다.")

    for cv in sorted(present & known):
        sub = df[df["cultivar"] == cv].sort_values("date")
        closed = sub["closed"].astype(str).str.lower().eq("true") if "closed" in sub.columns else sub["price"].isna()
        traded = sub[sub["price"].notna()]
        first, last = min(sub["date"]), max(sub["date"])
        summary = {"rows": int(len(sub)), "trading_days": int(len(traded)), "first": first.isoformat(),
                   "last": last.isoformat(), "stale_days": (today - last).days}
        rep.cultivars[cv] = summary
        tag = f"거래 통계[{cv}]"
        if traded.empty:
            rep.errors.append(f"{tag}: 가격이 있는 거래일이 없습니다.")
            continue
        late = (first - _years_ago(today, years)).days
        if late > START_SLACK_DAYS:
            rep.warnings.append(f"{tag}: 첫 날짜가 {first} 입니다. 수집 기간({years}년) 시작보다 {late}일 늦습니다 "
                                "(앞 구간 누락 의심, 원래 자료가 없는 품종이면 정상).")
        if cv in required and len(traded) < MIN_TRADING_DAYS_PER_YEAR * years:
            rep.warnings.append(f"{tag}: 거래일이 {len(traded)}일뿐입니다 ({years}년 기준 최소 {MIN_TRADING_DAYS_PER_YEAR * years}일 기대).")
        last_trade = max(traded["date"])
        summary["last_trading_day"] = last_trade.isoformat()
        if (today - last_trade).days > max_stale_days:
            rep.warnings.append(f"{tag}: 마지막 거래일 {last_trade} - 기준일보다 {(today - last_trade).days}일 지났습니다.")
        negative = int(((sub["price"] < 0) | (sub["volume"] < 0) | (sub["amount"] < 0)).sum())
        if negative:
            rep.errors.append(f"{tag}: 음수 값 행 {negative}개")
        zero_price = int((sub["price"] == 0).sum())
        if zero_price:
            rep.errors.append(f"{tag}: 가격 0원 행 {zero_price}개 - 휴장일 규칙(0 → 빈값)이 적용되지 않았습니다.")
        out_of_range = int(((traded["price"] < PRICE_RANGE[0]) | (traded["price"] > PRICE_RANGE[1])).sum())
        if out_of_range:
            rep.warnings.append(f"{tag}: 가격이 {PRICE_RANGE[0]:.0f}~{PRICE_RANGE[1]:.0f}원/kg 범위를 벗어난 행 {out_of_range}개")
        blank = int((sub["price"].isna() & ~closed).sum())
        if blank:
            rep.warnings.append(f"{tag}: 휴장일이 아닌데 가격이 빈 행 {blank}개 - 숫자 형식(쉼표 등)을 확인하세요.")
        summary["median_price"] = round(float(traded["price"].median()), 1)
        gaps = _gaps(sorted(set(sub["date"])), max_gap_days)
        if gaps:
            shown = ", ".join(f"{a}→{b}({n}일)" for a, b, n in gaps[:3])
            rep.warnings.append(f"{tag}: 날짜 공백 {len(gaps)}곳 (누락 구간 의심, 출하기 밖 품종이면 정상일 수 있음): {shown}")
        summary["gaps"] = len(gaps)
        full = traded[traded["volume"].notna() & traded["amount"].notna() & (traded["volume"] > 0) & (traded["amount"] > 0)]
        if len(full) >= 5:
            expected = full["price"] * full["volume"] / 1000.0
            rel = ((full["amount"] - expected).abs() / expected).median()
            summary["unit_error_median"] = round(float(rel), 4)
            if rel > UNIT_TOLERANCE:
                rep.warnings.append(f"{tag}: 거래금액이 평균가×거래량÷1000 과 중앙값 기준 {rel:.1%} 다릅니다 - 단위(원/kg·톤·백만원)를 확인하세요.")
        sundays = int((pd.to_datetime(traded["date"]).dt.day_of_week == 6).sum())
        if sundays:
            rep.info.append(f"{tag}: 일요일 거래 행 {sundays}개")


def _check_weather(root: Path, rep: Report, today: date, stations: list[str]) -> None:
    path = root / "weather_daily.csv"
    if not path.exists():
        rep.warnings.append("기상: weather_daily.csv 가 없습니다. 날씨 비교는 '자료 없음'으로 표시됩니다.")
        return
    df = _read_csv(path, rep, "기상")
    if df is None:
        return
    missing = [c for c in WEATHER_REQUIRED if c not in df.columns]
    if missing:
        rep.errors.append(f"기상: 필수 열이 없습니다 {missing}")
        return
    if df.empty:
        rep.warnings.append("기상: 행이 없습니다.")
        return
    df = _parse_dates(df, rep, "기상")
    if df.empty:
        return
    df["station"] = df["station"].astype(str).str.strip()
    dup = int(df.duplicated(subset=["date", "station"]).sum())
    if dup:
        rep.errors.append(f"기상: (날짜, 관측소) 중복 행 {dup}개")
    future = int((df["date"] > today).sum())
    if future:
        rep.errors.append(f"기상: 기준일({today}) 이후 날짜 행 {future}개")
    present = set(df["station"].unique())
    for st in stations:
        if st not in present:
            rep.warnings.append(f"기상: 산지 대표 관측소 '{st}' 자료가 없습니다.")
    temps = [c for c in ("temp_avg", "temp_min", "temp_max") if c in df.columns]
    for c in [*temps, "rain"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    odd = int(sum(((df[c] < TEMP_RANGE[0]) | (df[c] > TEMP_RANGE[1])).sum() for c in temps))
    if odd:
        rep.warnings.append(f"기상: 기온이 {TEMP_RANGE[0]:.0f}~{TEMP_RANGE[1]:.0f}℃ 범위를 벗어난 값 {odd}개")
    if "temp_max" in df.columns:
        inverted = int((df["temp_min"] > df["temp_max"]).sum())
        if inverted:
            rep.warnings.append(f"기상: 최저기온이 최고기온보다 높은 행 {inverted}개")
    if int((df["rain"] < 0).sum()):
        rep.errors.append(f"기상: 강수량 음수 행 {int((df['rain'] < 0).sum())}개")
    rep.weather = {"rows": int(len(df)), "stations": int(df["station"].nunique()),
                   "first": min(df["date"]).isoformat(), "last": max(df["date"]).isoformat()}
    rep.info.append(f"기상: 최신일 {rep.weather['last']} (허브 갱신 지연 구간이 있을 수 있음)")


def _check_state(root: Path, rep: Report, allow_synthetic: bool) -> None:
    if (root / "SYNTHETIC").exists():
        msg = "합성 자료 표시(SYNTHETIC)가 있는 캐시입니다. 실데이터가 아닙니다."
        (rep.info if allow_synthetic else rep.errors).append(msg)
    leftovers = sorted(p.name for p in root.glob(".*.tmp"))
    if leftovers:
        rep.info.append(f"저장 도중 중단돼 남은 임시 파일 {len(leftovers)}개 (지워도 됩니다): {', '.join(leftovers[:3])}")
    path = root / STATE_FILE
    if not path.exists():
        rep.info.append("수집 상태 파일이 없습니다 (예전 수집기로 받았거나 다른 곳에서 복사한 캐시).")
        return
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        stats = state.get("stats", {}) if isinstance(state, dict) else {}
        weather_failed = (state.get("weather") or {}).get("failed", []) if isinstance(state, dict) else []
        for cv, entry in sorted(stats.items()):
            failed = entry.get("failed", []) if isinstance(entry, dict) else []
            status = entry.get("status") if isinstance(entry, dict) else None
            if failed:
                spans = ", ".join(f"{f.get('start')}~{f.get('end')}" for f in failed[:3])
                rep.warnings.append(f"수집 상태[{cv}]: 실패 구간 {len(failed)}개가 남았습니다 ({spans}) → collect.py --retry-failed")
            elif status in STATE_NOT_DONE:
                rep.warnings.append(f"수집 상태[{cv}]: 마지막 수집이 끝나지 않았습니다 ({STATE_NOT_DONE[status]}) → collect.py 다시 실행")
        weather_status = (state.get("weather") or {}).get("status") if isinstance(state, dict) else None
        if not weather_failed and weather_status in STATE_NOT_DONE:
            rep.warnings.append(f"수집 상태[기상]: 마지막 수집이 끝나지 않았습니다 ({STATE_NOT_DONE[weather_status]}) → collect.py --weather-only 다시 실행")
        if weather_failed:
            rep.warnings.append(f"수집 상태[기상]: 실패 날짜 {len(weather_failed)}건이 남았습니다 → collect.py --weather-only --retry-failed")
    except (OSError, ValueError, AttributeError) as e:
        rep.warnings.append(f"수집 상태 파일을 읽을 수 없습니다 ({type(e).__name__})")


def validate(root: Path, today: date | None = None, items: list[str] | None = None, default_only: bool = False,
             allow_synthetic: bool = False, max_stale_days: int = 7, max_gap_days: int = 10,
             years: int | None = None) -> Report:
    root = Path(root)
    today = today or date.today()
    rep = Report()
    if not root.is_dir():
        rep.errors.append(f"캐시 폴더가 없습니다: {root}")
        return rep
    required, optional, stations = _scope(items, default_only)
    years = years or config.collect_config().get("years", 2)
    _check_stats(root, rep, today, required, optional, max_stale_days, max_gap_days, years)
    _check_weather(root, rep, today, stations)
    _check_state(root, rep, allow_synthetic)
    rep.info.append("거래 통계에는 산지 필드가 없습니다. 전국 공영도매시장 기준이며 산지 범위는 검증 대상이 아닙니다.")
    return rep


def _print(rep: Report, root: Path) -> None:
    print(f"캐시 검증: {root}")
    for cv, s in rep.cultivars.items():
        print(f"  {cv}: {s['rows']}행, 거래일 {s['trading_days']}일, {s['first']}~{s['last']}"
              + (f", 가격 중앙값 {s['median_price']}원/kg" if "median_price" in s else ""))
    if rep.weather:
        w = rep.weather
        print(f"  기상: {w['rows']}행, 관측소 {w['stations']}곳, {w['first']}~{w['last']}")
    for title, rows in (("오류", rep.errors), ("경고", rep.warnings), ("참고", rep.info)):
        if rows:
            print(f"\n[{title}] {len(rows)}건")
            for r in rows:
                print(f"  - {r}")
    print("\n결과:", "통과" if rep.ok and not rep.warnings else "통과(경고 있음)" if rep.ok else "실패")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="수집한 CSV 캐시 검증 (허브 호출 없음)")
    ap.add_argument("--data-dir", default=None, help="캐시 폴더 (기본: .env 의 DATA_DIR 또는 data/cache)")
    ap.add_argument("--item", action="append", default=None, help="품목 키. 여러 번 지정 가능")
    ap.add_argument("--default-only", action="store_true", help="품목별 기본 품종만 확인")
    ap.add_argument("--allow-synthetic", action="store_true", help="합성 자료 캐시를 오류로 보지 않음")
    ap.add_argument("--asof", default=None, help="기준일 YYYY-MM-DD (기본: 오늘)")
    ap.add_argument("--max-stale-days", type=int, default=7)
    ap.add_argument("--max-gap-days", type=int, default=10)
    ap.add_argument("--years", type=int, default=None, help="수집 기간(년). 기본: config 의 collect.years")
    ap.add_argument("--strict", action="store_true", help="경고가 있으면 종료 코드 2")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # 콘솔 인코딩(cp949 등)에 없는 글자 때문에 죽지 않게 한다
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    for key in args.item or []:
        if key not in config.items():
            print(f"! 알 수 없는 품목: {key} (사용 가능: {', '.join(config.items())})")
            return 1
    if args.data_dir:
        root = Path(args.data_dir)
        root = root if root.is_absolute() else ROOT / root
    else:
        root = config.data_dir()
    try:
        today = date.fromisoformat(args.asof) if args.asof else date.today()
    except ValueError:
        print(f"! 기준일 형식이 잘못됐습니다: {args.asof} (예: 2026-11-17)")
        return 1
    rep = validate(root, today, args.item, args.default_only, args.allow_synthetic,
                   args.max_stale_days, args.max_gap_days, args.years)
    if args.json:
        print(json.dumps(rep.as_dict(), ensure_ascii=False, indent=2))
    else:
        _print(rep, root)
    if not rep.ok:
        return 1
    return 2 if args.strict and rep.warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
