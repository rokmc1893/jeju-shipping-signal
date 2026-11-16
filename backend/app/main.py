"""FastAPI 래퍼 — 얇게. 비즈니스 로직은 agent/tools/judge 에 있고 여기선 HTTP 변환만 한다.

실행:  uvicorn app.main:app --host 127.0.0.1 --port 8000   (backend/ 에서)
프론트 빌드(frontend/dist)가 있으면 / 에서 그대로 서빙 → 센터 PC 에선 프로세스 1개.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

from . import config
from .agent import Agent, AgentRequest
from .data_store import DataStore

app = FastAPI(title="출하 신호등 — 제주 월동채소 편", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173",
                                                "https://localhost", "capacitor://localhost"],
                   allow_methods=["*"], allow_headers=["*"])

_store = DataStore()
_agent = Agent(_store)


class AskBody(BaseModel):
    item: str | None = Field(None, description="items.yaml 키 (carrot, radish, cabbage, garlic, onion)")
    cultivar: str | None = None
    question: str | None = Field(None, description="자유 질문/음성 인식 텍스트")
    intents: list[Literal["price_now", "trend", "yoy", "weather", "market", "volume", "overview"]] | None = Field(None, description="버튼 경로: price_now|trend|yoy|weather|market|volume|overview")
    boxes: float | None = Field(None, ge=0, allow_inf_nan=False)
    asof: date | None = None
    use_llm_explain: bool = True

    @field_validator("item")
    @classmethod
    def known_item(cls, value):
        if value is not None and value not in config.items():
            raise ValueError("지원하지 않는 품목이에요.")
        return value

    @model_validator(mode="after")
    def cultivar_matches_item(self):
        if self.item and self.cultivar and self.cultivar not in config.items()[self.item]["cultivars"]["all"]:
            raise ValueError("선택한 품목에 해당하는 품종을 골라 주세요.")
        return self


@app.get("/api/health")
def health():
    return {"ok": True, "llm": _agent.llm.provider, "synthetic": (_store.root / "SYNTHETIC").exists(),
            "data": {k: (_store.last_date(k).isoformat() if _store.last_date(k) else None)
                     for k in ("daily_stats", "daily_trades", "weather_daily")}}


@app.get("/api/items")
def items():
    out = []
    for key, it in config.items().items():
        out.append({"key": key, "name": it["name"], "cultivars": it["cultivars"]["all"], "default_cultivar": it["cultivars"]["default"],
                    "unit": it["unit"], "jeju_share": it["jeju_share"], "region": it["region"],
                    "has_data": not _store.stats(it["cultivars"]["default"]).empty})
    return out


@app.post("/api/ask")
def ask(body: AskBody):
    req = AgentRequest(item=body.item, cultivar=body.cultivar, question=body.question, intents=body.intents,
                       boxes=body.boxes, asof=body.asof, use_llm_explain=body.use_llm_explain)
    return _agent.run(req).as_dict()


@app.get("/api/briefing")
def briefing(asof: date | None = None):
    """5품목 신호등 한 장 — '오늘의 월동채소 시세 브리핑' 인쇄용."""
    out = []
    for key in config.items():
        r = _agent.run(AgentRequest(item=key, intents=["price_now"], asof=asof, use_llm_explain=False))
        out.append({"item": key, "name": r.item_name, "ok": r.ok, "signal": r.signal, "headline": r.headline,
                    "bullets": r.bullets, "data_state": r.data_state})
    return {"asof": (asof or date.today()).isoformat(), "items": out}


_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
