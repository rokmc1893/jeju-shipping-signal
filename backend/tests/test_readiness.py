"""공개 전 점검에서 발견한 실행·입력·데이터 표시 회귀 테스트다."""
from datetime import date
from types import SimpleNamespace
import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.agent import Agent, AgentRequest
from app.llm import LLM
from app import main


class CountingLLM:
    enabled = True
    last_backend = "test"

    def __init__(self):
        self.calls = 0

    def complete_json(self, prompt):
        return None

    def complete(self, prompt):
        self.calls += 1
        return "확인된 거래 자료를 참고해 주세요."


def test_button_never_calls_enabled_llm(store):
    llm = CountingLLM()
    response = Agent(store, llm).run(AgentRequest(item="carrot", asof=date(2026, 11, 7)))
    assert response.ok
    assert llm.calls == 0 and response.llm_explanation is None


def test_text_can_use_optional_explanation(store):
    llm = CountingLLM()
    response = Agent(store, llm).run(AgentRequest(question="당근 얼마", asof=date(2026, 11, 7)))
    assert response.ok and llm.calls == 1 and response.llm_explanation


def test_unverified_unit_always_shows_conversion(store):
    response = Agent(store, LLM()).run(AgentRequest(item="carrot", asof=date(2026, 11, 7), use_llm_explain=False))
    assert not config.items()["carrot"]["unit"]["verify"]
    assert any("20kg 기준 환산" in note for note in response.footnotes)


@pytest.fixture
def client(store, monkeypatch):
    llm = LLM()
    llm.provider = "none"
    monkeypatch.setattr(main, "_store", store)
    monkeypatch.setattr(main, "_agent", Agent(store, llm))
    with TestClient(main.app) as c:
        yield c


@pytest.mark.parametrize("body", [
    {"item": "unknown"},
    {"item": "carrot", "cultivar": "월동무"},
    {"item": "carrot", "boxes": -1},
    {"item": "carrot", "intents": ["invalid"]},
])
def test_api_rejects_invalid_inputs(client, body):
    assert client.post("/api/ask", json=body).status_code == 422


def test_api_full_flow_and_missing_data(client):
    assert client.get("/api/health").status_code == 200
    assert len(client.get("/api/items").json()) == 5
    response = client.post("/api/ask", json={"item": "carrot", "asof": "2026-11-08"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] and body["tools"]["price_now"]["date"] == "2026-11-07"
    missing = client.post("/api/ask", json={"item": "onion", "asof": "2026-11-08"})
    assert missing.status_code == 200 and not missing.json()["ok"]
    assert len(client.get("/api/briefing?asof=2026-11-08").json()["items"]) == 5


def test_weather_stops_empty_station_without_skipping_other_station(store, monkeypatch):
    path = Path(__file__).resolve().parents[2] / "scripts" / "collect.py"
    spec = importlib.util.spec_from_file_location("collect_readiness", path)
    collector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collector)
    monkeypatch.setattr(config, "collect_config", lambda: {"weather_months": list(range(1, 13)), "weather_free_stations": []})
    monkeypatch.setattr(config, "items", lambda: {"test": {"station": {"primary": "테스트", "fallback": []}}})
    calls = []

    def call(key, **params):
        calls.append(params.get("observatoryName"))
        return SimpleNamespace(rows=[], total=0, meta={"rows_found": True}, raw_keys=["data"])

    hub = SimpleNamespace(call=call)
    collector.collect_weather(hub, store, 1, date(2026, 1, 1), 1000)
    assert calls.count(None) == 45
    assert calls.count("테스트") == 45


def test_synthetic_cache_is_disclosed(store):
    marker = store.root / "SYNTHETIC"
    marker.write_text("합성 자료", encoding="utf-8")
    try:
        response = Agent(store, LLM()).run(AgentRequest(item="carrot", asof=date(2026, 11, 7), use_llm_explain=False))
        assert "합성 자료" in response.footnotes[0]
    finally:
        marker.unlink()


def test_demo_refuses_existing_real_cache(store, monkeypatch):
    path = Path(__file__).resolve().parents[2] / "scripts" / "demo_data.py"
    spec = importlib.util.spec_from_file_location("demo_readiness", path)
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    monkeypatch.setattr(demo, "DataStore", lambda: store)
    before = store.path("daily_stats").read_bytes()
    assert demo.main() == 1
    assert store.path("daily_stats").read_bytes() == before
    assert not (store.root / "SYNTHETIC").exists()


@pytest.mark.parametrize("origin", ["https://localhost", "capacitor://localhost"])
def test_native_app_origin_can_query_api(client, origin):
    response = client.options("/api/ask", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "access-control-allow-credentials" not in response.headers


def test_untrusted_origin_is_rejected(client):
    response = client.options("/api/ask", headers={
        "Origin": "https://untrusted.example",
        "Access-Control-Request-Method": "POST",
    })
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
