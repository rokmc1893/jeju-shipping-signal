from datetime import date

import numpy as np
import pandas as pd

from app import tools
from app.agent import Agent, AgentRequest
from app.data_store import normalize, apply_closed_day_rule
from app.intent import rule_extract, extract
from app.judge import check_data_state, decide, GREEN, YELLOW, RED
from app.llm import LLM

SAT = date(2026, 11, 7)   # 거래일
SUN = date(2026, 11, 8)   # 휴장


# ---------------- 데이터 레이어 ----------------
def test_closed_day_rule_turns_zero_into_nan():
    df = pd.DataFrame({"date": [date(2026, 1, 1), date(2026, 1, 2)], "price": [0.0, 1500.0],
                       "volume": [0.0, 20.0], "amount": [0.0, 30.0]})
    out = apply_closed_day_rule(df)
    assert np.isnan(out.loc[0, "price"]) and np.isnan(out.loc[0, "volume"]) and out.loc[0, "closed"]
    assert out.loc[1, "price"] == 1500.0 and not out.loc[1, "closed"]


def test_normalize_maps_hub_columns():
    rows = [{"baseDate": "20260107", "cultivar": "당근(일반)", "averagePrice": "1,800.50", "transactionVolume": "10", "transactionAmount": "18"}]
    df = normalize(rows, "daily_stats")
    assert list(df.columns)[:5] == ["date", "cultivar", "price", "volume", "amount"]
    # '1,800.50' 같은 천단위 콤마는 to_numeric 이 NaN 처리 → 허브가 콤마를 주면 수집 단계에서 제거해야 함을 테스트로 고정
    assert np.isnan(df.loc[0, "price"])


def test_store_has_sundays_as_closed(store):
    s = store.stats("당근(일반)")
    sundays = s[pd.to_datetime(s["date"]).dt.day_of_week == 6]
    assert len(sundays) > 90 and sundays["price"].isna().all()
    weekdays = s[pd.to_datetime(s["date"]).dt.day_of_week < 6]
    assert weekdays["price"].notna().mean() > 0.95


# ---------------- Tools ----------------
def test_price_now_switches_to_last_trading_day(store):
    r = tools.price_now(store.stats("당근(일반)"), SUN)
    assert r["ok"] and r["is_asof_closed"] and r["date"] == SAT.isoformat()
    r2 = tools.price_now(store.stats("당근(일반)"), SAT)
    assert not r2["is_asof_closed"]


def test_trend_uses_trading_days_only(store):
    r = tools.trend_ma(store.stats("당근(일반)"), SUN)
    assert r["ok"] and r["trading_days_used"] == 30
    assert all(x["price"] is not None and not np.isnan(x["price"]) for x in r["series"])
    assert r["direction"] in ("up", "down", "flat")


def test_yoy_window_has_trading_days(store):
    r = tools.yoy_compare(store.stats("당근(일반)"), SUN)
    assert r["ok"] and 4 <= r["last_year_days"] <= 7   # ±3일 창 7일 중 일요일 1일 제외
    assert r["yoy_pct"] is not None
    assert len(r["series_this_year"]) > 40 and len(r["series_last_year"]) > 40


def test_weather_effect_detects_cold_premium(store):
    r = tools.weather_effect(store.stats("당근(일반)"), store.weather("구좌"), SUN)
    assert r["ok"] and r["cold"]["enough"]
    assert r["cold"]["change_pct"] > 3.0   # 합성 데이터는 한파 다음 거래일 +12%


def test_market_compare_ranks_and_finds_jeju(store):
    r = tools.market_compare(store.trades("당근(일반)"), SUN)
    assert r["ok"] and r["best"]["market"] == "가락시장"
    assert r["jeju"] and "제주" in r["jeju"]["market"]
    assert sum(m["volume_ton"] for m in r["markets"]) > 0


def test_my_volume_range(store):
    s = store.stats("당근(일반)")
    p, t, y = tools.price_now(s, SUN), tools.trend_ma(s, SUN), tools.yoy_compare(s, SUN)
    r = tools.my_volume(p, t, y, boxes=100, unit_kg=20, unit_label="상자")
    assert r["ok"] and r["total_kg"] == 2000 and r["low"] <= r["high"]
    assert abs(r["revenue"]["오늘 가격"] - p["price_kg"] * 2000) < 1


# ---------------- 판단 엔진 ----------------
def _fake(price_vs_ma, direction, yoy, conf="high"):
    price = {"ok": True, "price_kg": 2000}
    trend = {"ok": True, "price_vs_ma_long_pct": price_vs_ma, "direction": direction, "short_change_pct": 3.0 if direction == "up" else -3.0,
             "ma_short": 2000, "ma_long": 1900, "volume_ratio": 1.0}
    y = {"ok": True, "yoy_pct": yoy, "last_year_mean": 1800}
    from app.judge import DataState
    st = DataState(True, "2026-11-07", 0, 24, 600, "2024-11-01", conf)
    return price, trend, y, st


def test_signal_green_when_all_three():
    s = decide(*_fake(5.0, "up", 10.0)[:3], None, _fake(5.0, "up", 10.0)[3])
    assert s.color == GREEN and s.score == 3


def test_signal_red_when_none():
    p, t, y, st = _fake(-5.0, "down", -10.0)
    assert decide(p, t, y, None, st).color == RED


def test_signal_yellow_partial_and_low_confidence():
    p, t, y, st = _fake(5.0, "down", -1.0)
    assert decide(p, t, y, None, st).color == YELLOW
    p, t, y, st = _fake(5.0, "up", 10.0, conf="low")
    s = decide(p, t, y, None, st)
    assert s.color == YELLOW and any("부족" in n for n in s.notes)


def test_signal_exposes_condition_details():
    p, t, y, st = _fake(5.0, "up", 10.0)
    s = decide(p, t, y, None, st)
    assert len(s.conditions) == 3 and all(c.detail for c in s.conditions)


def test_data_state_warns_when_stale(store):
    st = check_data_state(store.stats("당근(일반)"), date(2026, 11, 20))
    assert st.ok and st.days_since_last == 13 and any("13일 전" in w for w in st.warnings)


# ---------------- 의도 추출 ----------------
def test_rule_extract_items_and_intents():
    it = rule_extract("구좌 당근 요즘 얼마예요? 작년보다 비싸요?")
    assert it.item == "carrot" and "yoy" in it.intents and "trend" in it.intents and not it.needs_clarification
    it = rule_extract("무 값 어때요")
    assert it.item == "radish"
    it = rule_extract("무조건 비싸게 팔고 싶어요")   # '무조건' 오탐 방지
    assert it.item is None and it.needs_clarification
    it = rule_extract("양배추 300망 있는데 얼마 받아요")
    assert it.item == "cabbage" and it.boxes == 300 and "volume" in it.intents
    it = rule_extract("한파 오면 마늘 값 뛰나요")
    assert it.item == "garlic" and "weather" in it.intents


def test_extract_merges_llm_but_rule_item_wins():
    fake = lambda prompt: {"item": "양파", "intents": ["market"], "boxes": None}
    it = extract("당근 어느 시장이 더 쳐줘요", fake)
    assert it.item == "carrot" and "market" in it.intents and it.source == "rule+llm"
    it = extract("요즘 뭐가 좋아요", fake)       # 규칙이 품목 못 찾음 → LLM 품목 채택
    assert it.item == "onion" and it.source == "llm"
    bad = lambda prompt: (_ for _ in ()).throw(RuntimeError("down"))
    it = extract("당근 얼마", bad)
    assert it.item == "carrot" and it.source == "rule"


# ---------------- 에이전트 E2E ----------------
def _agent(store):
    llm = LLM()
    llm.provider = "none"
    return Agent(store, llm)


def test_agent_button_path_full_overview(store):
    r = _agent(store).run(AgentRequest(item="carrot", intents=["overview"], asof=SUN))
    assert r.ok and r.signal["color"] in (GREEN, YELLOW, RED)
    assert r.headline and len(r.bullets) == 3 and len(r.extra_sentences) >= 1
    assert set(r.tools) >= {"price_now", "trend_ma", "yoy_compare", "weather_effect"}
    assert "market_compare" not in r.tools   # 허브 1362 는 하루 10행 표본 → 기본 비활성화
    assert any("LLM 호출 없음" in t for t in r.trace) and any("휴장" in t for t in r.trace)
    assert any("산지 구분" in f for f in r.footnotes) and any("예측이 아니" in f for f in r.footnotes)


def test_agent_text_path_selects_tools(store):
    r = _agent(store).run(AgentRequest(question="당근 작년보다 비싸요?", asof=SAT))
    assert r.ok and "weather_effect" not in r.tools and "market_compare" not in r.tools
    assert r.intent["intents"] == ["yoy"]


def test_agent_clarifies_unknown_item(store):
    r = _agent(store).run(AgentRequest(question="요즘 뭐 팔면 좋아요", asof=SAT))
    assert not r.ok and len(r.clarify) == 5 and r.headline.startswith("어떤 작물")


def test_agent_handles_missing_item_data(store):
    r = _agent(store).run(AgentRequest(item="onion", intents=["overview"], asof=SAT))
    assert not r.ok and r.item_name == "양파" and r.data_state["confidence"] == "none"


def test_agent_volume_sentence(store):
    r = _agent(store).run(AgentRequest(question="당근 50상자 있는데 얼마나 받아요", asof=SAT))
    assert r.ok and r.tools["my_volume"]["ok"] and any("50상자" in s for s in r.extra_sentences)


def test_signal_counts_numpy_bools_from_real_tools(store):
    """회귀: np.True_ is True 가 False 라서 조건 3개 충족인데 2/3 로 세던 버그."""
    import json
    s = store.stats("당근(일반)")
    p, t, y = tools.price_now(s, SUN), tools.trend_ma(s, SUN), tools.yoy_compare(s, SUN)
    sig = decide(p, t, y, None, check_data_state(s, SUN))
    assert sig.score == sum(1 for c in sig.conditions if c.met)
    assert all(type(c.met) is bool for c in sig.conditions)
    json.dumps({"p": p, "t": t, "y": y, "m": tools.market_compare(store.trades("당근(일반)"), SUN)})  # JSON 직렬화 가능


# ---------------- 허브 클라이언트 (실측 특성 회귀) ----------------
def test_fetch_range_splits_window_when_truncated(monkeypatch):
    """10행 한도 + hasMore → 창을 반으로 쪼개 전부 회수. 페이징 파라미터는 없다."""
    from app.hub_client import HubClient, HubResponse
    import os
    os.environ["JEJU_HUB_PROJECT_KEY"] = "testkey-testkey-testkey"
    hub = HubClient(sleep_between=0)
    calls = []

    def fake_call(data_key, **p):
        s, e = p["startDate"], p["endDate"]
        calls.append((s, e))
        days = [date(2026, 11, d) for d in range(int(s[-2:]), int(e[-2:]) + 1)]
        rows = [{"baseDate": d.strftime("%Y%m%d"), "cultivar": "x", "averagePrice": "1", "transactionVolume": "1", "transactionAmount": "1"}
                for d in days if d.weekday() != 6]
        trunc = len(rows) > 10
        return HubResponse(rows[:10], len(rows), [], "", 200, 1, {"hasMore": trunc})

    monkeypatch.setattr(hub, "call", fake_call)
    rows = hub.fetch_range("daily_stats", date(2026, 11, 1), date(2026, 11, 30), window_days=30)
    got = sorted({r["baseDate"] for r in rows})
    assert len(got) == 25            # 11월 30일 중 일요일 5일 제외
    assert len(calls) >= 3           # 분할이 일어났다
