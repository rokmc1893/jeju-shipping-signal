"""분석 Tool 6종 — 전부 결정론적(pandas). LLM 은 여기에 손대지 않는다.

공통 규약
- 입력은 DataStore 가 돌려준 표준 DataFrame + 기준일(asof)
- '거래일' = price 가 NaN 이 아닌 날. 이동평균·추세·비교는 모두 거래일 기준
- 결과는 dict (JSON 직렬화 가능). 숫자는 round, 날짜는 ISO 문자열
- 데이터가 모자라면 예외 대신 {"ok": False, "reason": ...} 로 돌려주고 판단 엔진이 처리
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import config


def _iso(d) -> str | None:
    return None if d is None or pd.isna(d) else pd.Timestamp(d).date().isoformat()


def _py(obj):
    """numpy/pandas 스칼라를 순수 파이썬 값으로 재귀 변환 (JSON 직렬화·`is True` 비교 안전)."""
    if isinstance(obj, dict):
        return {k: _py(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_py(v) for v in obj]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return None if np.isnan(obj) else float(obj)
    if isinstance(obj, float) and np.isnan(obj):
        return None
    return obj


def jsonsafe(fn):
    """Tool 반환값을 항상 순수 파이썬 타입으로 맞추는 데코레이터."""
    def wrapper(*a, **kw):
        return _py(fn(*a, **kw))
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def trading_days(stats: pd.DataFrame, asof: date) -> pd.DataFrame:
    df = stats[(stats["date"] <= asof) & stats["price"].notna()]
    return df.sort_values("date").reset_index(drop=True)


def _pct(a: float, b: float) -> float | None:
    if b is None or b == 0 or pd.isna(a) or pd.isna(b):
        return None
    return round((a / b - 1.0) * 100.0, 1)


# ---------------------------------------------------------------------------
@jsonsafe
def price_now(stats: pd.DataFrame, asof: date) -> dict:
    """가장 최근 거래일의 가격·거래량. asof 가 휴장이면 직전 거래일로 자동 전환하고 그 사실을 알린다."""
    td = trading_days(stats, asof)
    if td.empty:
        return {"ok": False, "reason": "거래 데이터가 없어요."}
    last = td.iloc[-1]
    prev = td.iloc[-2] if len(td) >= 2 else None
    return {
        "ok": True,
        "date": _iso(last["date"]),
        "is_asof_closed": pd.Timestamp(last["date"]).date() != asof,
        "price_kg": round(float(last["price"]), 0),
        "volume_ton": None if pd.isna(last.get("volume")) else round(float(last["volume"]), 1),
        "prev_date": _iso(prev["date"]) if prev is not None else None,
        "dod_pct": _pct(last["price"], prev["price"]) if prev is not None else None,
    }


@jsonsafe
def trend_ma(stats: pd.DataFrame, asof: date, short: int | None = None, long: int | None = None) -> dict:
    """거래일 기준 단기/장기 이동평균과 추세 방향."""
    r = config.rules()
    short = short or r["ma_short_days"]
    long = long or r["ma_long_days"]
    td = trading_days(stats, asof)
    if len(td) < short + 1:
        return {"ok": False, "reason": f"최근 거래일이 {len(td)}일뿐이라 추세를 계산하기 어려워요."}
    p = td["price"].to_numpy(dtype=float)
    ma_s = float(np.mean(p[-short:]))
    ma_l = float(np.mean(p[-long:])) if len(p) >= long else float(np.mean(p))
    ma_s_prev = float(np.mean(p[-2 * short:-short])) if len(p) >= 2 * short else None
    change = _pct(ma_s, ma_s_prev) if ma_s_prev is not None else None
    thr = r["trend_threshold_pct"]
    if change is None:
        direction = "unknown"
    elif change > thr:
        direction = "up"
    elif change < -thr:
        direction = "down"
    else:
        direction = "flat"
    vol = td["volume"].dropna().to_numpy(dtype=float)
    vol_today = float(vol[-1]) if len(vol) else None
    vol_avg = float(np.mean(vol[-long:])) if len(vol) >= 5 else None
    series = td.tail(long)[["date", "price", "volume"]].copy()
    series["date"] = series["date"].map(_iso)
    return {
        "ok": True,
        "ma_short": round(ma_s, 0), "ma_long": round(ma_l, 0),
        "ma_short_prev": None if ma_s_prev is None else round(ma_s_prev, 0),
        "short_change_pct": change, "direction": direction,
        "price_vs_ma_long_pct": _pct(p[-1], ma_l),
        "trading_days_used": int(min(len(td), long)),
        "volume_today": None if vol_today is None else round(vol_today, 1),
        "volume_avg": None if vol_avg is None else round(vol_avg, 1),
        "volume_ratio": None if not vol_today or not vol_avg else round(vol_today / vol_avg, 2),
        "series": series.to_dict(orient="records"),
    }


@jsonsafe
def yoy_compare(stats: pd.DataFrame, asof: date, window: int | None = None) -> dict:
    """작년 같은 시기(±window 일, 거래일만) 평균가와 비교. 올해/작년 60일 시리즈도 함께 제공."""
    r = config.rules()
    window = window or r["yoy_window_days"]
    td_all = stats[stats["price"].notna()].sort_values("date")
    now = trading_days(stats, asof)
    if now.empty:
        return {"ok": False, "reason": "올해 거래 데이터가 없어요."}
    age = (asof - now.iloc[-1]["date"]).days
    if age > config.MAX_PRICE_AGE_DAYS:
        return {"ok": False, "reason": f"마지막 거래 자료가 {age}일 전이라 기준일의 전년 비교를 보류해요."}
    cur_price = float(now.iloc[-1]["price"])
    try:
        ly_center = asof.replace(year=asof.year - 1)
    except ValueError:  # 2/29
        ly_center = asof.replace(year=asof.year - 1, day=28)
    lo, hi = ly_center - timedelta(days=window), ly_center + timedelta(days=window)
    ly = td_all[(td_all["date"] >= lo) & (td_all["date"] <= hi)]
    if ly.empty:
        return {"ok": False, "reason": "작년 같은 시기 자료가 없어요."}
    ly_mean = float(ly["price"].mean())
    # 겹쳐 그릴 시리즈 (최근 60일 vs 작년 동일 60일)
    span = 60
    cur_s = td_all[(td_all["date"] > asof - timedelta(days=span)) & (td_all["date"] <= asof)]
    ly_s = td_all[(td_all["date"] > ly_center - timedelta(days=span)) & (td_all["date"] <= ly_center)]

    def _ser(df: pd.DataFrame) -> list[dict]:
        return [{"date": _iso(d), "price": round(float(p), 0)} for d, p in zip(df["date"], df["price"])]

    return {
        "ok": True,
        "price_now": round(cur_price, 0),
        "last_year_mean": round(ly_mean, 0),
        "last_year_window": [lo.isoformat(), hi.isoformat()],
        "last_year_days": int(len(ly)),
        "yoy_pct": _pct(cur_price, ly_mean),
        "series_this_year": _ser(cur_s),
        "series_last_year": _ser(ly_s),
    }


@jsonsafe
def weather_effect(stats: pd.DataFrame, weather: pd.DataFrame, asof: date,
                   lookback_days: int = 730) -> dict:
    """산지 관측소 기상 이벤트(한파·우천) 직후 N거래일 평균가가 평소 대비 몇 % 달랐는지.

    '평소' = 이벤트 영향 구간을 제외한 전체 거래일 평균. 과거 패턴 기술이지 예측이 아니다.
    """
    r = config.rules()
    if weather.empty:
        return {"ok": False, "reason": "기상 자료가 없어요."}
    td = trading_days(stats, asof)
    td = td[td["date"] > asof - timedelta(days=lookback_days)]
    if len(td) < 30:
        return {"ok": False, "reason": "날씨 영향을 보기엔 거래일이 부족해요."}
    w = weather[(weather["date"] <= asof) & (weather["date"] > asof - timedelta(days=lookback_days))].copy()
    cold_days = set(w.loc[w["temp_min"] <= r["cold_day_temp_min"], "date"])
    rain_days = set(w.loc[w["rain"] >= r["rain_day_mm"], "date"])
    after_n = r["weather_after_days"]
    dates = list(td["date"])
    prices = td["price"].to_numpy(dtype=float)
    idx_of = {d: i for i, d in enumerate(dates)}

    def _after_mean(event_days: set) -> tuple[list[float], set]:
        vals, affected = [], set()
        for ed in sorted(event_days):
            # 이벤트일 이후 첫 거래일부터 after_n 거래일
            later = [i for d, i in idx_of.items() if d > ed]
            if not later:
                continue
            start = min(later)
            seg = list(range(start, min(start + after_n, len(prices))))
            if len(seg) < after_n:
                continue
            affected.update(seg)
            vals.append(float(np.mean(prices[seg])))
        return vals, affected

    cold_vals, cold_idx = _after_mean(cold_days)
    rain_vals, rain_idx = _after_mean(rain_days)
    baseline_idx = [i for i in range(len(prices)) if i not in cold_idx and i not in rain_idx]
    if len(baseline_idx) < 15:
        return {"ok": False, "reason": "평소 가격을 잡을 거래일이 부족해요."}
    baseline = float(np.mean(prices[baseline_idx]))

    def _summ(vals: list[float], n_events: int) -> dict:
        if n_events < r["weather_min_events"] or not vals:
            return {"events": n_events, "enough": False, "change_pct": None}
        return {"events": n_events, "enough": True, "change_pct": _pct(float(np.mean(vals)), baseline)}

    # 최근 7일 안에 이벤트가 있었는지 (현재 신호에 참고)
    recent = asof - timedelta(days=7)
    return {
        "ok": True,
        "baseline_price": round(baseline, 0),
        "after_days": after_n,
        "cold": _summ(cold_vals, len(cold_vals)),
        "rain": _summ(rain_vals, len(rain_vals)),
        "recent_cold_day": any(d > recent for d in cold_days),
        "recent_rain_day": any(d > recent for d in rain_days),
        "thresholds": {"cold_temp_min": r["cold_day_temp_min"], "rain_mm": r["rain_day_mm"]},
    }


@jsonsafe
def market_compare(trades: pd.DataFrame, asof: date, days: int = 7, top: int = 6) -> dict:
    """최근 N거래일 시장별 거래량 가중 평균가. 제주 시장이 있으면 표시."""
    if trades.empty or "market" not in trades.columns:
        return {"ok": False, "reason": "시장별 자료가 없어요."}
    t = trades[(trades["date"] <= asof) & trades["price"].notna()]
    if t.empty:
        return {"ok": False, "reason": "시장별 자료가 없어요."}
    recent_dates = sorted(t["date"].unique())[-days:]
    t = t[t["date"].isin(recent_dates)].copy()
    t["w"] = t["volume"].fillna(0)
    g = t.groupby("market").apply(
        lambda x: pd.Series({
            "price_kg": float(np.average(x["price"], weights=x["w"])) if x["w"].sum() > 0 else float(x["price"].mean()),
            "volume_ton": float(x["w"].sum()),
        }), include_groups=False)
    g = g[g["volume_ton"] > 0].sort_values("volume_ton", ascending=False)
    if g.empty:
        return {"ok": False, "reason": "시장별 자료가 없어요."}
    overall = float(np.average(g["price_kg"], weights=g["volume_ton"]))
    rows = [{"market": m, "price_kg": round(v.price_kg, 0), "volume_ton": round(v.volume_ton, 1),
             "vs_overall_pct": _pct(v.price_kg, overall)} for m, v in g.head(top).iterrows()]
    jeju = [r_ for r_ in rows if "제주" in r_["market"]]
    best = max(rows, key=lambda r_: r_["price_kg"])
    return {"ok": True, "period": [recent_dates[0].isoformat(), recent_dates[-1].isoformat()],
            "overall_price_kg": round(overall, 0), "markets": rows, "best": best,
            "jeju": jeju[0] if jeju else None}


@jsonsafe
def my_volume(price_now_res: dict, trend_res: dict, yoy_res: dict, boxes: float, unit_kg: float,
              unit_label: str) -> dict:
    """내 물량(상자/망 수) × 단위 kg × 가격 시나리오 → 예상 매출 범위. 수수료·운임 미반영 명시."""
    if boxes <= 0 or not price_now_res.get("ok"):
        return {"ok": False, "reason": "물량을 입력해 주세요."}
    kg = boxes * unit_kg
    scen = {"오늘 가격": price_now_res["price_kg"]}
    if trend_res.get("ok"):
        scen["최근 30거래일 평균"] = trend_res["ma_long"]
    if yoy_res.get("ok"):
        scen["작년 이맘때 평균"] = yoy_res["last_year_mean"]
    rev = {k: round(v * kg) for k, v in scen.items()}
    return {"ok": True, "boxes": boxes, "unit_label": unit_label, "unit_kg": unit_kg, "total_kg": kg,
            "unit_price": {k: round(v * unit_kg) for k, v in scen.items()},
            "revenue": rev, "low": min(rev.values()), "high": max(rev.values()),
            "note": "도매가격 기준 단순 계산이에요. 수수료·운임·상하차비는 빠져 있어요."}
