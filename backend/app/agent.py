"""에이전트 오케스트레이션.

입력 → (경로 분기) → 의도/엔티티 → 데이터 상태 점검 → Tool 플랜 → 실행 → 판단(신호등) → 템플릿 설명
      → (선택) LLM 쉬운 말 보강

판단 포인트(자율 수행 범위)
  1) 품목을 못 찾으면 되묻기            2) 기준일이 휴장이면 직전 거래일로 전환
  3) 관측소 응답이 없으면 대체 관측소     4) 자료 부족이면 신호를 '관망'으로 강등하고 사유 표시
  5) 의도에 따라 실행할 Tool 만 고른다 (overview 면 전부)
모든 판단은 trace 에 기록되어 화면 '에이전트가 한 일' 과 기획서 근거로 쓰인다.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Callable

import pandas as pd

from . import config, tools, templates
from .data_store import DataStore
from .intent import Intent, extract
from .judge import check_data_state, decide
from .llm import LLM

PLAN_BY_INTENT: dict[str, list[str]] = {
    "price_now": ["price_now", "trend_ma", "yoy_compare"],          # 신호등엔 3개가 항상 필요
    "trend": ["price_now", "trend_ma", "yoy_compare"],
    "yoy": ["price_now", "trend_ma", "yoy_compare"],
    "weather": ["price_now", "trend_ma", "yoy_compare", "weather_effect"],
    "market": ["price_now", "trend_ma", "yoy_compare", "market_compare"],
    "volume": ["price_now", "trend_ma", "yoy_compare", "my_volume"],
    "overview": ["price_now", "trend_ma", "yoy_compare", "weather_effect", "market_compare"],
}


@dataclass
class AgentRequest:
    item: str | None = None            # items.yaml 키
    cultivar: str | None = None
    question: str | None = None        # 자유 질문(음성 포함)
    intents: list[str] | None = None   # 버튼 경로에서 직접 지정
    boxes: float | None = None
    asof: date | None = None
    use_llm_explain: bool = True


@dataclass
class AgentResponse:
    ok: bool
    mode: str
    item: str | None
    item_name: str | None
    cultivar: str | None
    asof: str
    signal: dict | None
    headline: str | None
    bullets: list[str]
    extra_sentences: list[str]
    llm_explanation: str | None
    tools: dict
    data_state: dict | None
    footnotes: list[str]
    clarify: list[dict] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    intent: dict | None = None

    def as_dict(self) -> dict:
        return asdict(self)


class Agent:
    def __init__(self, store: DataStore | None = None, llm: LLM | None = None,
                 llm_json: Callable[[str], dict | None] | None = None):
        self.store = store or DataStore()
        self.llm = llm if llm is not None else LLM()
        self._llm_json = llm_json if llm_json is not None else (self.llm.complete_json if self.llm.enabled else None)

    # ---- 1. 의도 ----------------------------------------------------------
    def _resolve_intent(self, req: AgentRequest, trace: list[str]) -> tuple[Intent, str]:
        if req.item:
            it = Intent(req.item, req.cultivar, req.intents or ["overview"], req.boxes, "button", 1.0, raw=req.question or "")
            trace.append(f"버튼 경로: 품목={req.item}, 의도={it.intents} (LLM 호출 없음)")
            return it, "button"
        it = extract(req.question or "", self._llm_json)
        trace.append(f"자유 질문 경로: 추출={it.source}, 품목={it.item}, 의도={it.intents}, 상자={it.boxes}")
        if req.boxes:
            it.boxes = req.boxes
        return it, "text"

    # ---- 2. 데이터 -----------------------------------------------------------
    def _load(self, item_key: str, cultivar: str | None, trace: list[str]) -> tuple[dict, str, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        cfg = config.items()[item_key]
        cv = cultivar or cfg["cultivars"]["default"]
        stats = self.store.stats(cv)
        if stats.empty and cultivar is None:
            # 기본 품종 자료가 없으면 같은 품목의 다른 품종으로 대체
            for alt in cfg["cultivars"]["all"]:
                stats = self.store.stats(alt)
                if not stats.empty:
                    trace.append(f"기본 품종 '{cv}' 자료가 없어 '{alt}' 으로 대체")
                    cv = alt
                    break
        trades = self.store.trades(cv)
        station = cfg["station"]["primary"]
        weather = self.store.weather(station)
        if weather.empty:
            for fb in cfg["station"].get("fallback", []):
                weather = self.store.weather(fb)
                if not weather.empty:
                    trace.append(f"관측소 '{station}' 자료가 없어 '{fb}' 로 대체")
                    station = fb
                    break
        return cfg, cv, stats, trades, weather

    # ---- 3~6. 실행 ------------------------------------------------------------
    def run(self, req: AgentRequest) -> AgentResponse:
        trace: list[str] = []
        asof = req.asof or date.today()
        it, mode = self._resolve_intent(req, trace)

        if it.needs_clarification or not it.item:
            trace.append("품목을 찾지 못해 되묻기")
            return AgentResponse(False, mode, None, None, None, asof.isoformat(), None,
                                 "어떤 작물이 궁금하세요?", [], [], None, {}, None, [],
                                 clarify=it.clarify_options, trace=trace, intent=it.as_dict())

        cfg, cv, stats, trades, weather = self._load(it.item, it.cultivar, trace)
        state = check_data_state(stats, asof)
        state.collection_incomplete = self.store.collection_incomplete(cv)
        incomplete_reason = "이 품종의 자료 수집이 완료되지 않아 비교와 판단을 보류해요."
        if state.collection_incomplete:
            state.warnings.append(incomplete_reason)
        trace.append(f"데이터 상태: 거래일 {state.trading_days_30}/30일, 신뢰도={state.confidence}, 마지막 거래일={state.last_trading_day}")
        if not state.ok:
            return AgentResponse(False, mode, it.item, cfg["name"], cv, asof.isoformat(), None,
                                 f"{cfg['name']} 거래 자료를 아직 불러오지 못했어요.", state.warnings, [], None, {},
                                 state.as_dict(), templates.footnotes(cfg, state.as_dict(), "", True),
                                 trace=trace, intent=it.as_dict())

        plan: list[str] = []
        for i in it.intents:
            for t in PLAN_BY_INTENT.get(i, PLAN_BY_INTENT["overview"]):
                if t not in plan:
                    plan.append(t)
        if not config.rules().get("market_compare_enabled", True) and "market_compare" in plan:
            plan.remove("market_compare")
            trace.append("시장 비교는 허브 거래 정보 API 가 하루 10행 표본만 제공해 비활성화")
        trace.append(f"Tool 플랜: {plan}")

        res: dict = {}
        res["price_now"] = tools.price_now(stats, asof)
        if res["price_now"].get("is_asof_closed"):
            trace.append(f"기준일 가격 자료 없음 → 마지막 거래일 {res['price_now']['date']} 기준으로 전환")
        if state.collection_incomplete:
            # 마지막 관측값은 제시하되, 누락 구간에 의존할 수 있는 파생값은 보류한다.
            res["price_now"].update(prev_date=None, dod_pct=None)
            for tool in plan:
                if tool != "price_now":
                    res[tool] = {"ok": False, "reason": incomplete_reason}
        else:
            res["trend_ma"] = tools.trend_ma(stats, asof)
            res["yoy_compare"] = tools.yoy_compare(stats, asof)
            if "weather_effect" in plan:
                res["weather_effect"] = tools.weather_effect(stats, weather, asof)
            if "market_compare" in plan:
                res["market_compare"] = tools.market_compare(trades, asof)
            if "my_volume" in plan:
                res["my_volume"] = tools.my_volume(res["price_now"], res["trend_ma"], res["yoy_compare"],
                                                   it.boxes or 0, cfg["unit"]["kg"], cfg["unit"]["label"])
                if res["my_volume"].get("ok") and not cfg["unit"].get("verify"):
                    res["my_volume"]["note"] = (f"1{cfg['unit']['label']} {cfg['unit']['kg']}kg을 가정한 예시예요. "
                                                 + res["my_volume"]["note"])
        for k, v in res.items():
            if not v.get("ok"):
                trace.append(f"{k}: {v.get('reason')}")

        signal = decide(res["price_now"], res["trend_ma"], res["yoy_compare"], res.get("weather_effect"), state)
        trace.append(f"판단: {signal.color} (조건 {signal.score}/3, 신뢰도 {signal.confidence})")

        unit_price = None
        if res["price_now"].get("ok") and cfg["unit"].get("verify"):
            unit_price = res["price_now"]["price_kg"] * cfg["unit"]["kg"]
        head = templates.headline(cfg["name"], cfg["unit"]["label"], unit_price, signal)
        if state.collection_incomplete:
            head = f"{cfg['name']}, 아직 수집이 끝나지 않았어요."
        elif (state.days_since_last or 0) > config.MAX_PRICE_AGE_DAYS:
            head = f"{cfg['name']}, 마지막 거래가 {state.days_since_last}일 전이라 판단을 보류해요."
        bl = templates.bullets(res["price_now"], res["trend_ma"], res["yoy_compare"], cfg["name"])
        if not res["yoy_compare"].get("ok"):
            bl.append(res["yoy_compare"]["reason"])
        extra = [s for s in (templates.weather_sentence(res.get("weather_effect", {})),
                             templates.market_sentence(res.get("market_compare", {}))) if s]
        if res.get("my_volume", {}).get("ok"):
            mv = res["my_volume"]
            extra.append(f"{mv['boxes']:g}{mv['unit_label']}({mv['total_kg']:,.0f}kg)면 도매가 기준 약 {mv['low']:,}원 ~ {mv['high']:,}원이에요. {mv['note']}")

        foot = templates.footnotes(cfg, state.as_dict(), config.share_footnote(cfg["jeju_share"]),
                                   cfg["unit"].get("verify", False))

        if (self.store.root / "SYNTHETIC").exists():
            foot.insert(0, "시연용 합성 자료입니다. 실제 시세나 출하 판단에 사용하지 마세요.")

        explanation = None
        if mode == "text" and req.use_llm_explain and self.llm.enabled:
            facts = "\n".join(f"- {b}" for b in [head, *bl, *extra, *signal.notes])
            explanation = self.llm.complete(templates.LLM_EXPLAIN_PROMPT.format(
                item=cfg["name"], signal_label=signal.label, color=signal.color, facts=facts))
            trace.append(f"LLM 설명: {'생성(' + str(self.llm.last_backend) + ')' if explanation else '실패 → 템플릿 사용'}")

        return AgentResponse(True, mode, it.item, cfg["name"], cv, asof.isoformat(), signal.as_dict(), head, bl, extra,
                             explanation, res, state.as_dict(), foot, trace=trace, intent=it.as_dict())
