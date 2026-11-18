"""쉬운 말 템플릿 — LLM 없이도 완결된 설명을 만든다. 숫자는 전부 Tool 결과에서만 가져온다."""
from __future__ import annotations

from .judge import Signal, GREEN, YELLOW, RED


def won(v: float | None) -> str:
    return "-" if v is None else f"{v:,.0f}원"


def headline(item_name: str, unit_label: str, unit_price: float | None, signal: Signal) -> str:
    base = {GREEN: f"{item_name}, 지금은 출하를 생각해 볼 만해요.",
            YELLOW: f"{item_name}, 조금 더 지켜보는 게 좋겠어요.",
            RED: f"{item_name}, 지금 출하는 조심하세요."}[signal.color]
    if unit_price is not None:
        base += f" 최근 거래일 1{unit_label} {won(unit_price)}쯤이에요."
    return base


def bullets(price: dict, trend: dict, yoy: dict, item_name: str) -> list[str]:
    out: list[str] = []
    if price.get("ok"):
        s = f"최근 거래일 도매가는 1kg에 {won(price['price_kg'])}"
        if price.get("dod_pct") is not None:
            s += f", 전 거래일보다 {price['dod_pct']:+.1f}%"
        out.append(s + "예요.")
    if trend.get("ok"):
        d = {"up": "오르는 중", "down": "내리는 중", "flat": "비슷한 수준", "unknown": "판단 어려움"}[trend["direction"]]
        out.append(f"최근 7거래일 평균은 {won(trend['ma_short'])}이고 {d}이에요. 30거래일 평균은 {won(trend['ma_long'])}이에요.")
    if yoy.get("ok"):
        v = yoy["yoy_pct"]
        word = "높아요" if v >= 0 else "낮아요"
        out.append(f"작년 이맘때({won(yoy['last_year_mean'])})보다 {abs(v):.1f}% {word}.")
    return out


def weather_sentence(weather: dict) -> str | None:
    if not weather.get("ok"):
        return None
    parts = []
    c, r = weather["cold"], weather["rain"]
    if c.get("enough"):
        parts.append(f"한파(최저 {weather['thresholds']['cold_temp_min']:.0f}℃ 이하) 뒤 {weather['after_days']}거래일은 평소보다 {c['change_pct']:+.1f}% ({c['events']}회 기준)")
    if r.get("enough"):
        parts.append(f"비 {weather['thresholds']['rain_mm']:.0f}mm 이상 온 뒤는 평소보다 {r['change_pct']:+.1f}% ({r['events']}회 기준)")
    if not parts:
        return "날씨와 가격 관계를 말할 만큼 사례가 아직 모이지 않았어요."
    return "과거 2년을 보면 " + ", ".join(parts) + "였어요."


def market_sentence(market: dict) -> str | None:
    if not market.get("ok"):
        return None
    b = market["best"]
    s = f"최근 거래에선 {b['market']}이 1kg {won(b['price_kg'])}로 가장 높았어요(전체 평균 대비 {b['vs_overall_pct']:+.1f}%)."
    if market.get("jeju"):
        j = market["jeju"]
        s += f" {j['market']}은 {won(j['price_kg'])}이에요."
    return s


def footnotes(item_cfg: dict, state: dict, share_note: str, unit_verified: bool) -> list[str]:
    notes = ["출처: 제주데이터허브 ‘농산물 품종별 일일 거래 통계·거래 정보’(원천 aT 도매유통정보시스템), ‘일별 기상 정보’. 전국 공영도매시장 거래 기준이며 산지 구분은 없어요."]
    if share_note:
        notes.append(share_note)
    if state.get("first_date"):
        notes.append(f"자료 기간 {state['first_date']} ~ {state['last_trading_day']}, 거래일 {state['trading_days_total']}일. 휴장일은 계산에서 뺐어요.")
    if not unit_verified:
        notes.append(f"1{item_cfg['unit']['label']} = {item_cfg['unit']['kg']}kg 기준 환산은 가정한 예시예요. 실제 포장 중량을 확인해 주세요.")
    notes.append("과거 거래 자료로 만든 참고 신호예요. 가격 예측이 아니며 출하 결정의 책임은 농가에 있어요.")
    return notes


LLM_EXPLAIN_PROMPT = """너는 제주 농가 어르신께 도매 시세를 설명하는 농협 직원이야.
아래 '사실'만 사용해서 3문장 이내, 쉬운 말, 존댓말로 설명해. 숫자를 새로 만들거나 바꾸지 마. 예측하지 마. 색(신호)을 바꾸지 마.

품목: {item}
신호: {signal_label} ({color})
사실:
{facts}
"""
