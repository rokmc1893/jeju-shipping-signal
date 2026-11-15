"""판단 엔진 — 데이터 상태 점검 + 신호등 규칙 + 신뢰도.

모든 규칙은 config/items.yaml 의 rules 에서 읽으며, 결과에는 '왜 이 색인가' 를 설명할 조건별 실제 수치가 들어간다.
LLM 은 이 결과를 말로 풀기만 하고 색을 바꿀 수 없다.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, timedelta

import pandas as pd

from . import config
from .tools import trading_days

GREEN, YELLOW, RED = "green", "yellow", "red"
LABEL = {GREEN: "출하 참고", YELLOW: "관망", RED: "주의"}


@dataclass
class DataState:
    ok: bool
    last_trading_day: str | None
    days_since_last: int | None
    trading_days_30: int           # 최근 30일(달력) 중 거래일 수
    trading_days_total: int
    first_date: str | None
    confidence: str                # high | mid | low | none
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def check_data_state(stats: pd.DataFrame, asof: date) -> DataState:
    r = config.rules()
    if stats.empty:
        return DataState(False, None, None, 0, 0, None, "none", ["이 품목의 거래 자료가 아직 없어요."])
    td = trading_days(stats, asof)
    if td.empty:
        return DataState(False, None, None, 0, 0, None, "none", ["기준일 이전 거래 자료가 없어요."])
    last = pd.Timestamp(td.iloc[-1]["date"]).date()
    since = (asof - last).days
    recent = td[td["date"] > asof - timedelta(days=30)]
    n30 = int(len(recent))
    warnings: list[str] = []
    if since > 7:
        warnings.append(f"마지막 거래 자료가 {since}일 전({last.isoformat()})이에요. 허브 갱신을 확인해 주세요.")
    elif since >= 1:
        warnings.append(f"기준일에 거래가 없어 마지막 거래일({last.isoformat()}) 기준으로 보여드려요.")
    if n30 >= r["min_trading_days_high"]:
        conf = "high"
    elif n30 >= r["min_trading_days_mid"]:
        conf = "mid"
        warnings.append(f"최근 30일 중 거래일이 {n30}일뿐이라 참고만 해 주세요.")
    else:
        conf = "low"
        warnings.append(f"최근 30일 중 거래일이 {n30}일이라 신호를 내기 어려워요.")
    return DataState(True, last.isoformat(), since, n30, int(len(td)),
                     pd.Timestamp(td.iloc[0]["date"]).date().isoformat(), conf, warnings)


@dataclass
class Condition:
    key: str
    label: str
    met: bool | None          # None = 판단 불가
    detail: str
    value: float | None


@dataclass
class Signal:
    color: str
    label: str
    score: int                # 충족 조건 수 0~3
    conditions: list[Condition]
    notes: list[str]
    confidence: str

    def as_dict(self) -> dict:
        d = asdict(self)
        return d


def decide(price: dict, trend: dict, yoy: dict, weather: dict | None, state: DataState) -> Signal:
    """3조건 규칙.
    A 오늘가 > 30거래일 평균   B 7거래일 평균 상승 추세   C 작년 동기 대비 ≥ 0%
    3개 → 초록, 1~2개 → 노랑, 0개 → 빨강. 신뢰도 low 또는 판단불가 조건 2개 이상이면 노랑 고정.
    """
    conds: list[Condition] = []
    notes: list[str] = []

    # A
    if trend.get("ok") and trend.get("price_vs_ma_long_pct") is not None:
        v = trend["price_vs_ma_long_pct"]
        conds.append(Condition("above_ma", "오늘 가격이 최근 30거래일 평균보다 높다", bool(v > 0),
                               f"오늘 {price.get('price_kg'):,.0f}원 vs 평균 {trend['ma_long']:,.0f}원 ({v:+.1f}%)", v))
    else:
        conds.append(Condition("above_ma", "오늘 가격이 최근 30거래일 평균보다 높다", None, "자료 부족", None))
    # B
    if trend.get("ok") and trend.get("direction") in ("up", "down", "flat"):
        d = trend["direction"]
        c = trend.get("short_change_pct")
        txt = {"up": "오르는 중", "down": "내리는 중", "flat": "보합"}[d]
        conds.append(Condition("trend_up", "최근 7거래일 평균이 오르는 중이다", bool(d == "up"),
                               f"7거래일 평균 {trend['ma_short']:,.0f}원, 직전 7거래일 대비 {c:+.1f}% → {txt}", c))
    else:
        conds.append(Condition("trend_up", "최근 7거래일 평균이 오르는 중이다", None, "자료 부족", None))
    # C
    if yoy.get("ok") and yoy.get("yoy_pct") is not None:
        v = yoy["yoy_pct"]
        conds.append(Condition("yoy_nonneg", "작년 이맘때보다 싸지 않다", bool(v >= 0),
                               f"작년 같은 시기 평균 {yoy['last_year_mean']:,.0f}원 대비 {v:+.1f}%", v))
    else:
        conds.append(Condition("yoy_nonneg", "작년 이맘때보다 싸지 않다", None, "작년 자료 없음", None))

    met = sum(1 for c in conds if c.met is True)
    unknown = sum(1 for c in conds if c.met is None)

    if met == 3:
        color = GREEN
    elif met == 0 and unknown == 0:
        color = RED
    else:
        color = YELLOW
    if state.confidence == "low" or unknown >= 2:
        color = YELLOW
        notes.append("자료가 부족해 '관망'으로 표시했어요.")

    # 보조 신호 (색은 안 바꾸고 메모만)
    r = config.rules()
    if trend.get("ok") and trend.get("volume_ratio") and trend["volume_ratio"] >= r["volume_spike_ratio"]:
        notes.append(f"오늘 거래량이 평소의 {trend['volume_ratio']:.1f}배예요. 출하가 몰리고 있어 가격이 눌릴 수 있어요.")
    if weather and weather.get("ok"):
        if weather.get("recent_cold_day") and weather["cold"].get("enough"):
            notes.append(f"최근 일주일 안에 한파일이 있었어요. 과거엔 한파 뒤 {weather['after_days']}거래일 가격이 평소보다 {weather['cold']['change_pct']:+.1f}%였어요.")
        if weather.get("recent_rain_day") and weather["rain"].get("enough"):
            notes.append(f"최근 일주일 안에 비가 많이 온 날이 있었어요. 과거엔 비 온 뒤 가격이 평소보다 {weather['rain']['change_pct']:+.1f}%였어요.")
    notes.extend(state.warnings)
    return Signal(color, LABEL[color], met, conds, notes, state.confidence)
