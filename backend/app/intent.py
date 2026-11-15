"""의도·엔티티 추출.

경로 1 (버튼): 프론트가 item/intent 를 직접 보내므로 이 모듈을 거치지 않는다.
경로 2 (자유 질문/음성): 규칙 기반 추출이 1차, LLM 이 있으면 LLM JSON 결과를 검증 후 우선 적용.
   LLM 이 실패/없음 → 규칙 결과로 계속. 품목을 못 찾으면 clarify 로 되묻기 칩을 돌려준다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Callable

from . import config

INTENTS = ("price_now", "trend", "yoy", "weather", "market", "volume", "overview")

INTENT_KEYWORDS: dict[str, list[str]] = {
    "yoy": ["작년", "지난해", "이맘때", "전년", "예년", "작년보다"],
    "weather": ["추위", "한파", "날씨", "비 오", "비오", "눈 오", "눈오", "폭설", "태풍", "바람", "기온", "추우"],
    "market": ["시장", "가락", "어디로", "어디에", "어느 시장", "경매", "도매시장", "쳐주"],
    "volume": ["상자", "박스", "망", "톤", "매출", "얼마 받", "얼마나 받", "내 물량", "개 있", "개 팔"],
    "trend": ["추세", "오르", "내리", "떨어", "흐름", "요즘", "최근", "분위기", "변동"],
    "price_now": ["얼마", "시세", "가격", "값", "팔아도", "팔까", "출하", "지금"],
}

ASK_WORDS_ALL = ["전부", "다 알려", "종합", "전체적으로", "한눈에"]


@dataclass
class Intent:
    item: str | None                   # items.yaml 키 (carrot ...)
    cultivar: str | None
    intents: list[str]
    boxes: float | None = None
    source: str = "rule"               # rule | llm | button
    confidence: float = 0.0
    needs_clarification: bool = False
    clarify_options: list[dict] = field(default_factory=list)
    raw: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _find_item(text: str) -> tuple[str | None, str | None, float]:
    items = config.items()
    best, best_len = None, 0
    cultivar = None
    for key, it in items.items():
        for alias in it["aliases"]:
            if alias in text and len(alias) > best_len:
                best, best_len = key, len(alias)
        for cv in it["cultivars"]["all"]:
            if cv in text:
                best, cultivar = key, cv
                best_len = max(best_len, len(cv))
    # '무' 한 글자는 오탐 위험 → 조사/문맥 체크
    if best == "radish" and best_len == 1:
        if not re.search(r"(^|[\s,])무([\s는은이가값도를]|$)", text):
            best = None
    conf = 0.9 if best else 0.0
    return best, cultivar, conf


def _find_boxes(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(상자|박스|망|개|톤)", text)
    if not m:
        return None
    n = float(m.group(1))
    if m.group(2) == "톤":
        return None  # 톤 단위는 상자 수가 아님 → 프론트에서 kg 입력으로 유도
    return n


def rule_extract(text: str) -> Intent:
    t = text.strip()
    item, cultivar, conf = _find_item(t)
    intents = [k for k, kws in INTENT_KEYWORDS.items() if any(w in t for w in kws)]
    if any(w in t for w in ASK_WORDS_ALL) or not intents:
        intents = ["overview"]
    # price_now 는 다른 의도가 잡혔으면 중복 제거 (overview 가 어차피 포함)
    if len(intents) > 1 and "price_now" in intents:
        intents.remove("price_now")
    boxes = _find_boxes(t)
    if boxes is not None and "volume" not in intents:
        intents.append("volume")
    it = Intent(item, cultivar, intents, boxes, "rule", conf, raw=t)
    if item is None:
        it.needs_clarification = True
        it.clarify_options = [{"item": k, "label": v["name"]} for k, v in config.items().items()]
    return it


LLM_SCHEMA_HINT = (
    "다음 질문에서 JSON 만 출력: {\"item\": 당근|무|양배추|마늘|양파|null, \"intents\": "
    "[price_now|trend|yoy|weather|market|volume|overview 중 해당하는 것], \"boxes\": 숫자|null}. "
    "모르면 null. 설명 금지."
)


def _validate_llm(obj: dict, text: str) -> Intent | None:
    if not isinstance(obj, dict):
        return None
    name_to_key = {v["name"]: k for k, v in config.items().items()}
    item = obj.get("item")
    key = name_to_key.get(item) if isinstance(item, str) else None
    intents = [i for i in (obj.get("intents") or []) if i in INTENTS] or ["overview"]
    boxes = obj.get("boxes")
    boxes = float(boxes) if isinstance(boxes, (int, float)) and boxes > 0 else None
    it = Intent(key, None, intents, boxes, "llm", 0.8 if key else 0.3, raw=text)
    if key is None:
        it.needs_clarification = True
        it.clarify_options = [{"item": k, "label": v["name"]} for k, v in config.items().items()]
    return it


def extract(text: str, llm_json: Callable[[str], dict | None] | None = None) -> Intent:
    """규칙 1차 → LLM 보강. 규칙이 품목을 확실히 잡았으면 LLM 은 의도 보강에만 쓴다."""
    rule = rule_extract(text)
    if llm_json is None:
        return rule
    try:
        obj = llm_json(f"{LLM_SCHEMA_HINT}\n질문: {text}")
    except Exception:
        return rule
    llm = _validate_llm(obj, text) if obj else None
    if llm is None:
        return rule
    # 병합: 품목은 규칙 우선(정확), 의도는 합집합, 상자 수는 규칙 우선
    item = rule.item or llm.item
    intents = list(dict.fromkeys([*rule.intents, *llm.intents]))
    if "overview" in intents and len(intents) > 1:
        intents.remove("overview")
    merged = Intent(item, rule.cultivar, intents, rule.boxes or llm.boxes,
                    "rule+llm" if rule.item else "llm", max(rule.confidence, llm.confidence), raw=text)
    if item is None:
        merged.needs_clarification = True
        merged.clarify_options = rule.clarify_options
    return merged
