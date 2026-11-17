"""수집기·캐시 검증 도구 회귀 테스트다. 실제 허브 API 는 호출하지 않는다(가짜 허브만 사용)."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import urllib.error
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from app import config, data_store, hub_client
from app.data_store import DataStore
from app.hub_client import HubClient, HubError, HubResponse

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
TODAY = date(2026, 11, 17)
CARROT = "당근(일반)"
FAKE_KEY = "test-project-key-0000"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass 가 모듈을 찾을 수 있게 등록
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def collector():
    return _load("collect")


@pytest.fixture(scope="module")
def validator():
    return _load("validate_cache")


@pytest.fixture
def store(tmp_path):
    return DataStore(tmp_path / "cache")


class FakeHub(HubClient):
    """네트워크 대신 메모리에서 응답하는 허브. 창 분할·hasMore 처리는 실제 HubClient 코드를 그대로 탄다."""

    def __init__(self, fail=None, attempts_per_call=1, interrupt_at=None, no_rows=False):
        super().__init__(project_key=FAKE_KEY, base_url="https://hub.invalid/api", sleep_between=0, verbose=False)
        self.fail = fail or (lambda params: False)
        self.attempts_per_call = attempts_per_call
        self.interrupt_at = interrupt_at
        self.no_rows = no_rows
        self.requests: list[dict] = []

    def call(self, data_key, **params):
        if self.interrupt_at is not None and len(self.requests) == self.interrupt_at:
            raise KeyboardInterrupt
        self.requests.append(params)
        self.attempts += self.attempts_per_call
        if self.fail(params):
            raise HubError(f"HTTP 500 ({self.build_url(data_key, params)}) 서버 오류 {self.project_key}")
        self.calls += 1
        if "searchDate" in params:
            rows = [{"observatoryName": params.get("observatoryName", "서광"), "baseDate": params["searchDate"],
                     "averageTemperature": 8.0, "lowestTemperature": 3.0, "highestTemperature": 12.0,
                     "dailyRainfall": 0.0, "maximumWindSpeed": 5.0, "averageWindSpeed": 2.0}]
        else:
            rows = []
            d = date.fromisoformat(f"{params['startDate'][:4]}-{params['startDate'][4:6]}-{params['startDate'][6:]}")
            end = date.fromisoformat(f"{params['endDate'][:4]}-{params['endDate'][4:6]}-{params['endDate'][6:]}")
            while d <= end:
                if d.weekday() != 6:  # 실제 허브처럼 일요일 행은 없다
                    rows.append({"baseDate": d.strftime("%Y%m%d"), "cultivar": params["cultivar"],
                                 "averagePrice": "1500.00", "transactionVolume": "20.00", "transactionAmount": "30.00"})
                d += timedelta(days=1)
        if self.no_rows:
            rows = []
        return HubResponse(rows, len(rows), ["totCnt", "hasMore", "data"], "masked", 200, 1, {"hasMore": False})


def _stats(collector, hub, store, today=TODAY, **kw):
    kw.setdefault("default_only", True)
    return collector.collect_stats(hub, store, "carrot", 1, today, **kw)


def _state(store):
    return json.loads((store.root / "collect_state.json").read_text(encoding="utf-8"))


# ---------------- 안전한 CSV 교체 ----------------
def test_save_failure_keeps_previous_csv_and_leaves_no_temp_file(store, monkeypatch):
    good = pd.DataFrame({"date": [date(2026, 1, 2)], "cultivar": [CARROT], "price": [1500.0]})
    store.save("daily_stats", good)
    before = store.path("daily_stats").read_bytes()

    def broken(self, f, **kwargs):
        f.write("date,cultivar,pri")  # 일부만 쓰고 죽는 상황
        raise OSError("디스크가 가득 찼습니다")

    monkeypatch.setattr(pd.DataFrame, "to_csv", broken)
    with pytest.raises(OSError):
        store.save("daily_stats", good)
    assert store.path("daily_stats").read_bytes() == before
    assert [p.name for p in store.root.iterdir()] == ["daily_stats.csv"]


def test_save_retries_when_target_is_briefly_locked(store, monkeypatch):
    real_replace, tries = os.replace, []

    def flaky(src, dst):
        tries.append(1)
        if len(tries) < 3:
            raise PermissionError("다른 프로그램이 사용 중")
        real_replace(src, dst)

    monkeypatch.setattr(data_store.os, "replace", flaky)
    monkeypatch.setattr(data_store.time, "sleep", lambda s: None)
    store.save("daily_stats", pd.DataFrame({"date": [date(2026, 1, 2)], "price": [1.0]}))
    assert len(tries) == 3 and len(store.load("daily_stats")) == 1
    assert not list(store.root.glob(".*.tmp"))


def test_save_gives_up_after_repeated_lock_and_cleans_up(store, monkeypatch):
    store.save("daily_stats", pd.DataFrame({"date": [date(2026, 1, 2)], "price": [1.0]}))

    def locked(src, dst):
        raise PermissionError("잠김")

    monkeypatch.setattr(data_store.os, "replace", locked)
    monkeypatch.setattr(data_store.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        store.save("daily_stats", pd.DataFrame({"date": [date(2026, 1, 3)], "price": [2.0]}))
    monkeypatch.undo()
    assert store.load("daily_stats")["price"].tolist() == [1.0]
    assert not list(store.root.glob(".*.tmp"))


# ---------------- 허브 호출 수 집계 ----------------
def test_hub_counts_every_attempt_including_retries(monkeypatch):
    outcomes = [urllib.error.URLError("끊김"), urllib.error.URLError("끊김"), b'{"totCnt": 0, "hasMore": false, "data": []}']

    class Resp:
        status = 200

        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self.body

    def fake_urlopen(req, timeout=None):
        out = outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return Resp(out)

    monkeypatch.setattr(hub_client.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(hub_client.time, "sleep", lambda s: None)
    hub = HubClient(project_key=FAKE_KEY, base_url="https://hub.invalid/api", sleep_between=0, verbose=False)
    assert hub.call("datakey", searchDate="20260101").rows == []
    assert hub.attempts == 3 and hub.calls == 1


# ---------------- 거래 통계: 중간 저장·실패 재시도 ----------------
def test_stats_full_run_saves_and_records_progress(collector, store):
    hub = FakeHub()
    [res] = _stats(collector, hub, store)
    assert res["status"] == "ok" and res["failed"] == 0 and res["received"] == res["total"] > 300
    saved = store.stats(CARROT)
    assert max(saved["date"]) == TODAY and not saved.duplicated(subset=["date", "cultivar"]).any()
    entry = _state(store)["stats"][CARROT]
    assert entry["done_through"] == TODAY.isoformat() and entry["status"] == "ok" and entry["failed"] == []
    assert _state(store)["quota"][TODAY.isoformat()]["daily_stats"] == hub.attempts == len(hub.requests)
    assert collector.exit_code([res], None) == collector.EXIT_OK


def test_stats_failed_window_is_recorded_then_filled_by_retry(collector, store):
    bad = lambda p: p.get("startDate", "").startswith("202603")  # noqa: E731  3월에 시작하는 창만 실패
    [res] = _stats(collector, FakeHub(fail=bad), store)
    assert res["status"] == "partial" and res["failed"] == 3
    assert collector.exit_code([res], None) == collector.EXIT_PARTIAL
    saved = store.stats(CARROT)
    assert max(saved["date"]) == TODAY  # 실패한 창 뒤의 자료도 저장됐다
    failed = _state(store)["stats"][CARROT]["failed"]
    assert all(f["start"].startswith("2026-03") and f["tries"] == 1 for f in failed)
    hole_start, hole_end = date.fromisoformat(failed[0]["start"]), date.fromisoformat(failed[-1]["end"])
    assert not ((saved["date"] >= hole_start) & (saved["date"] <= hole_end)).any()

    # 다시 실패하면 시도 횟수만 늘고, 새 구간은 받지 않는다
    hub2 = FakeHub(fail=bad)
    [res2] = _stats(collector, hub2, store, retry_only=True)
    assert res2["status"] == "partial" and len(hub2.requests) == 3
    assert [f["tries"] for f in _state(store)["stats"][CARROT]["failed"]] == [2, 2, 2]

    hub3 = FakeHub()
    [res3] = _stats(collector, hub3, store, retry_only=True)
    assert res3["status"] == "ok" and len(hub3.requests) == 3
    filled = store.stats(CARROT)
    assert ((filled["date"] >= hole_start) & (filled["date"] <= hole_end)).any()
    assert _state(store)["stats"][CARROT]["failed"] == []
    assert not filled.duplicated(subset=["date", "cultivar"]).any()


def test_stats_normal_run_retries_failed_windows_first(collector, store):
    _stats(collector, FakeHub(fail=lambda p: p.get("startDate", "").startswith("202603")), store)
    hub = FakeHub()
    [res] = _stats(collector, hub, store)
    assert res["status"] == "ok"
    assert hub.requests[0]["startDate"].startswith("202603")
    assert len(hub.requests) == 3 + 1  # 실패 창 3개 + 최근 겹침 구간 1개


def test_stats_interrupted_run_keeps_rows_and_resumes(collector, store):
    hub = FakeHub(interrupt_at=10)
    with pytest.raises(KeyboardInterrupt):
        _stats(collector, hub, store)
    partial = store.stats(CARROT)
    assert len(partial) > 60  # 중단 전 10개 창이 디스크에 남았다
    entry = _state(store)["stats"][CARROT]
    done = date.fromisoformat(entry["done_through"])
    assert done == date(2025, 11, 17) + timedelta(days=10 * 10 - 1)  # 정확히 10번째 창의 끝
    assert max(partial["date"]) == done and entry["status"] == "running"

    hub2 = FakeHub()
    [res] = _stats(collector, hub2, store)
    assert res["status"] == "ok" and max(store.stats(CARROT)["date"]) == TODAY
    first = date.fromisoformat(f"{hub2.requests[0]['startDate'][:4]}-{hub2.requests[0]['startDate'][4:6]}-{hub2.requests[0]['startDate'][6:]}")
    assert first == done - timedelta(days=collector.OVERLAP_DAYS)  # 처음부터가 아니라 끊긴 곳에서 이어받는다
    assert len(hub2.requests) < 37 - 8


def test_stats_legacy_cache_without_state_resumes_from_last_date(collector, store):
    _stats(collector, FakeHub(), store, today=date(2026, 10, 1))
    (store.root / "collect_state.json").unlink()
    hub = FakeHub()
    [res] = _stats(collector, hub, store)
    assert res["status"] == "ok" and hub.requests[0]["startDate"] == "20260924"


def test_stats_restarts_when_cache_was_deleted_but_state_remains(collector, store):
    _stats(collector, FakeHub(), store)
    store.path("daily_stats").unlink()
    hub = FakeHub()
    [res] = _stats(collector, hub, store)
    assert res["status"] == "ok" and hub.requests[0]["startDate"] == "20251117"
    assert len(store.stats(CARROT)) > 300


def test_stats_stops_after_consecutive_failures(collector, store):
    hub = FakeHub(fail=lambda p: True)
    results = collector.collect_stats(hub, store, None, 1, TODAY, default_only=True)
    assert results[0]["status"] == "aborted"
    assert len(hub.requests) == collector.MAX_CONSECUTIVE_FAILURES
    assert [r["status"] for r in results[1:]] == ["skipped"] * 4
    assert collector.exit_code(results, None) == collector.EXIT_PARTIAL
    assert not store.path("daily_stats").exists()


def test_stale_failed_windows_do_not_block_new_data(collector, store):
    always_bad = lambda p: "20251207" <= p.get("startDate", "") <= "20260116"  # noqa: E731  연속한 창 5개가 계속 실패
    [first] = _stats(collector, FakeHub(fail=always_bad), store)
    assert first["status"] == "aborted" and first["failed"] == collector.MAX_CONSECUTIVE_FAILURES
    hub = FakeHub(fail=always_bad)
    [res] = _stats(collector, hub, store)
    assert res["status"] == "partial" and max(store.stats(CARROT)["date"]) == TODAY  # 재시도가 막혀도 최신 자료는 받는다
    assert [f["tries"] for f in _state(store)["stats"][CARROT]["failed"]] == [2] * 5
    [again] = _stats(collector, FakeHub(fail=always_bad), store, retry_only=True)
    assert again["status"] == "aborted"  # 재시도만 하는 실행은 연속 실패에서 멈춘다


def test_all_empty_responses_are_not_recorded_as_done(collector, store):
    [res] = _stats(collector, FakeHub(no_rows=True), store)
    assert res["status"] == "empty" and res["total"] == 0 and res["default"]
    assert collector.exit_code([res], None) == collector.EXIT_PARTIAL
    assert _state(store)["stats"][CARROT]["done_through"] is None
    hub = FakeHub()
    [res2] = _stats(collector, hub, store)  # 다음 실행은 최근 며칠이 아니라 처음부터 다시 받는다
    assert res2["status"] == "ok" and hub.requests[0]["startDate"] == "20251117" and res2["total"] > 300


def test_non_default_cultivar_with_failures_is_partial_and_empty_one_is_not_refetched(collector, store):
    # 흙당근만 3월 창이 실패하고 나머지는 0행, 세척당근은 전부 0행인 상황
    def call_plan(hub):
        real = hub.call

        def call(data_key, **params):
            if params["cultivar"] == "흙당근" and params["startDate"].startswith("202603"):
                hub.requests.append(params)
                hub.attempts += 1
                raise HubError("HTTP 500 서버 오류")
            hub.no_rows = params["cultivar"] != CARROT
            return real(data_key, **params)

        hub.call = call
        return hub

    results = collector.collect_stats(call_plan(FakeHub()), store, "carrot", 1, TODAY)
    by = {r["cultivar"]: r for r in results}
    assert by[CARROT]["status"] == "ok" and by["흙당근"]["status"] == "partial" and by["흙당근"]["failed"] == 3
    assert by["세척당근"]["status"] == "empty" and not by["세척당근"]["default"]
    assert collector.exit_code(results, None) == collector.EXIT_PARTIAL
    assert collector.exit_code([by[CARROT], by["세척당근"]], None) == collector.EXIT_OK  # 비기본 품종 0행만으로는 실패가 아니다
    hub = call_plan(FakeHub())
    collector.collect_stats(hub, store, "carrot", 1, TODAY)
    assert sum(1 for r in hub.requests if r["cultivar"] == "세척당근") == 1  # 0행 품종을 매번 전체 기간 다시 받지 않는다


def test_retry_only_run_on_empty_default_cultivar_is_not_done(collector, store):
    hub = FakeHub(fail=lambda p: p.get("startDate", "").startswith("202603"), no_rows=True)
    [first] = _stats(collector, hub, store)
    assert first["status"] == "partial" and first["total"] == 0
    [retry] = _stats(collector, FakeHub(no_rows=True), store, retry_only=True)
    assert retry["status"] == "empty" and collector.exit_code([retry], None) == collector.EXIT_PARTIAL
    assert _state(store)["stats"][CARROT]["done_through"] is None


def test_retry_failures_do_not_carry_over_into_new_windows(collector, store):
    bad = lambda p: "20251206" <= p.get("startDate", "") <= "20260105"  # noqa: E731  연속한 창 4개 실패
    [first] = _stats(collector, FakeHub(fail=bad), store, today=date(2026, 3, 1))
    assert first["failed"] == 4
    # 재시도 4개가 다시 실패한 직후 첫 신규 창도 한 번 실패한다 → 연속 5회로 세어 멈추면 안 된다
    hub = FakeHub(fail=lambda p: bad(p) or p.get("startDate") == "20260222")
    [res] = _stats(collector, hub, store)
    assert res["status"] == "partial" and res["failed"] == 5 and max(store.stats(CARROT)["date"]) == TODAY


def test_retry_only_run_does_not_mark_unfinished_collection_as_done(collector, store, validator):
    [res] = _stats(collector, FakeHub(), store, budget=5)
    assert res["status"] == "quota"
    [retry] = _stats(collector, FakeHub(), store, retry_only=True, today=TODAY + timedelta(days=1))
    assert retry["status"] == "ok" and _state(store)["stats"][CARROT]["status"] == "quota"
    # 실패 구간을 하나 심어 재시도가 실패(partial)했다가 성공해도 '예산 소진' 표시는 유지된다
    state = _state(store)
    state["stats"][CARROT]["failed"] = [{"start": "2025-01-01", "end": "2025-01-10", "error": "x", "tries": 1, "last_try": None}]
    (store.root / "collect_state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    [bad] = _stats(collector, FakeHub(fail=lambda p: True), store, retry_only=True, today=TODAY + timedelta(days=1))
    assert bad["status"] == "partial" and _state(store)["stats"][CARROT]["status"] == "quota"
    [good] = _stats(collector, FakeHub(), store, retry_only=True, today=TODAY + timedelta(days=1))
    assert good["status"] == "ok" and _state(store)["stats"][CARROT]["status"] == "quota"
    warnings = validator.validate(store.root, TODAY, items=["carrot"], default_only=True, years=1).warnings
    assert any("마지막 수집이 끝나지 않았습니다" in w for w in warnings)
    [done] = _stats(collector, FakeHub(), store, today=TODAY + timedelta(days=1))
    assert done["status"] == "ok" and _state(store)["stats"][CARROT]["status"] == "ok"


@pytest.mark.parametrize("payload, is_error", [
    ({"message": "일일 호출 한도를 초과했습니다"}, True),
    ({"data": None, "message": "일일 호출 한도를 초과했습니다"}, True),
    ({"data": {"msg": "오류"}}, True),
    ({}, True),
    ({"totCnt": 0, "hasMore": False, "data": []}, False),
    ({"data": []}, False),
    ({"body": {"items": []}}, False),
    ({"totCnt": 0}, False),
])
def test_unexpected_response_shape_is_a_failure_not_an_empty_window(payload, is_error):
    class CannedHub(HubClient):
        def call(self, data_key, **params):
            rows, total, meta = hub_client._find_rows(payload)
            return HubResponse(rows, total, list(payload.keys()), "masked", 200, 1, meta)

    hub = CannedHub(project_key=FAKE_KEY, base_url="https://hub.invalid/api", sleep_between=0, verbose=False)
    fetch = lambda: hub.fetch_window("daily_stats", date(2026, 11, 1), date(2026, 11, 10), cultivar=CARROT)  # noqa: E731
    if is_error:
        with pytest.raises(HubError, match="응답 형식이 예상과 다릅니다"):
            fetch()
    else:
        assert fetch() == []


def test_extending_years_registers_and_fetches_earlier_windows(collector, store):
    _stats(collector, FakeHub(), store)
    assert min(store.stats(CARROT)["date"]) == date(2025, 11, 17)
    with pytest.raises(KeyboardInterrupt):  # 앞 구간을 받다가 끊겨도 남은 구간을 잊지 않는다
        collector.collect_stats(FakeHub(interrupt_at=5), store, "carrot", 2, TODAY, default_only=True)
    pending = _state(store)["stats"][CARROT]["failed"]
    assert len(pending) == 37 - 5 and pending[0]["error"] == "수집 기간 확장(미수집)"
    [res] = collector.collect_stats(FakeHub(), store, "carrot", 2, TODAY, default_only=True)
    saved = store.stats(CARROT)
    assert res["status"] == "ok" and min(saved["date"]) == date(2024, 11, 18)  # 11-17 은 일요일
    assert not saved.duplicated(subset=["date", "cultivar"]).any()
    assert not [g for g in zip(sorted(saved["date"]), sorted(saved["date"])[1:]) if (g[1] - g[0]).days > 2]


def test_state_never_stores_key_or_url(collector, store):
    _stats(collector, FakeHub(fail=lambda p: p.get("startDate", "").startswith("202603")), store)
    text = (store.root / "collect_state.json").read_text(encoding="utf-8")
    assert FAKE_KEY not in text and "http" not in text and "서버 오류" in text


# ---------------- 하루 누적 쿼터 ----------------
def test_quota_accumulates_across_runs_on_same_day(collector, store):
    hub = FakeHub()
    [res] = _stats(collector, hub, store, budget=5)
    assert res["status"] == "quota" and len(hub.requests) == 5
    assert collector.exit_code([res], None) == collector.EXIT_QUOTA
    assert len(store.stats(CARROT)) > 30  # 예산 안에서 받은 자료는 저장됐다

    hub2 = FakeHub()
    [res2] = _stats(collector, hub2, store, budget=5)
    assert res2["status"] == "quota" and hub2.requests == []  # 같은 날 다시 실행해도 더 부르지 않는다

    hub3 = FakeHub()
    [res3] = _stats(collector, hub3, store, today=TODAY + timedelta(days=1), budget=5)
    assert len(hub3.requests) == 5  # 날짜가 바뀌면 이어서 받는다
    quota = _state(store)["quota"]
    assert quota[TODAY.isoformat()]["daily_stats"] == 5
    assert quota[(TODAY + timedelta(days=1)).isoformat()]["daily_stats"] == 5


def test_quota_counts_retry_attempts(collector, store):
    hub = FakeHub(attempts_per_call=3)
    [res] = _stats(collector, hub, store, budget=7)
    assert res["status"] == "quota" and len(hub.requests) == 3  # 3회 × 3시도 = 9 ≥ 7
    assert _state(store)["quota"][TODAY.isoformat()]["daily_stats"] == 9


def test_quota_stop_skips_remaining_cultivars(collector, store):
    results = collector.collect_stats(FakeHub(), store, "carrot", 1, TODAY, budget=2)
    assert [r["status"] for r in results] == ["quota", "skipped", "skipped"]


def test_old_quota_days_are_pruned(collector, store):
    state = collector.CollectState(store.root)
    state.charge(TODAY - timedelta(days=30), "daily_stats", 10)
    state.charge(TODAY, "daily_stats", 3)
    state.prune(TODAY)
    assert list(state.data["quota"]) == [TODAY.isoformat()]


def test_corrupt_state_file_is_set_aside(collector, store, capsys):
    (store.root / "collect_state.json").write_text("{ 깨진 파일", encoding="utf-8")
    state = collector.CollectState(store.root)
    assert state.data["stats"] == {} and (store.root / "collect_state.json.corrupt").exists()
    assert "호출 기록이 사라졌으니" in capsys.readouterr().out
    # 메모장 등에서 다른 인코딩(cp949)으로 저장된 파일도 죽지 않고 같은 방식으로 처리한다
    (store.root / "collect_state.json").write_bytes('{"version": 1, "x": "당근"}'.encode("cp949"))
    assert collector.CollectState(store.root, read_only=True).recovered
    assert collector.CollectState(store.root).recovered and not (store.root / "collect_state.json").exists()


# ---------------- 기상 ----------------
def _use_one_station(monkeypatch):
    monkeypatch.setattr(config, "collect_config", lambda: {"weather_months": list(range(1, 13)), "weather_free_stations": ["서광"]})
    monkeypatch.setattr(config, "items", lambda: {"test": {"station": {"primary": "구좌", "fallback": []}}})


@pytest.fixture
def one_station(monkeypatch):
    _use_one_station(monkeypatch)


def _weather(collector, hub, store, today=date(2026, 1, 11), budget=1000, **kw):
    # 1년 전체가 아니라 최근 10일만 보도록 캐시에 이전 날짜를 채워 둔다
    if not store.path("weather_daily").exists():
        d, rows = date(2025, 1, 11), []
        while d <= date(2025, 12, 31):
            rows += [{"date": d, "station": "서광", "temp_min": 1.0, "rain": 0.0},
                     {"date": d, "station": "구좌", "temp_min": 1.0, "rain": 0.0}]
            d += timedelta(days=1)
        store.save("weather_daily", pd.DataFrame(rows))
    return collector.collect_weather(hub, store, 1, today, budget, **kw)


def test_weather_failure_is_recorded_and_retried(collector, store, one_station):
    hub = FakeHub(fail=lambda p: p["searchDate"] == "20260105" and p.get("observatoryName") == "구좌")
    res = _weather(collector, hub, store)
    assert res["status"] == "partial" and res["failed"] == 1 and len(hub.requests) == 20
    assert _state(store)["weather"]["failed"][0] == {
        "station": "구좌", "date": "2026-01-05", "error": "HTTP 500 서버 오류 ****", "tries": 1, "last_try": "2026-01-11"}
    w = store.weather("구좌")
    assert date(2026, 1, 4) in set(w["date"]) and date(2026, 1, 5) not in set(w["date"])

    hub2 = FakeHub()
    res2 = _weather(collector, hub2, store, retry_only=True)
    assert res2["status"] == "ok" and len(hub2.requests) == 1
    assert date(2026, 1, 5) in set(store.weather("구좌")["date"])
    assert _state(store)["weather"]["failed"] == []


def test_weather_budget_is_daily_cumulative(collector, store, one_station):
    hub = FakeHub()
    res = _weather(collector, hub, store, budget=6)
    assert res["status"] == "quota" and len(hub.requests) == 6
    assert len(store.weather()[store.weather()["date"] >= date(2026, 1, 1)]) == 6  # 호출마다 저장된다
    hub2 = FakeHub()
    assert _weather(collector, hub2, store, budget=6)["status"] == "quota" and hub2.requests == []
    hub3 = FakeHub()
    res3 = _weather(collector, hub3, store, today=date(2026, 1, 12), budget=1000)
    assert res3["status"] == "ok" and len(hub3.requests) == 14 + 2


def test_weather_retry_only_keeps_quota_status(collector, store, one_station):
    assert _weather(collector, FakeHub(), store, budget=3)["status"] == "quota"
    hub = FakeHub()
    assert _weather(collector, hub, store, retry_only=True, today=date(2026, 1, 12))["status"] == "ok" and hub.requests == []
    assert _state(store)["weather"]["status"] == "quota"


def test_weather_interrupt_saves_what_was_received(collector, store, one_station):
    with pytest.raises(KeyboardInterrupt):
        _weather(collector, FakeHub(interrupt_at=7), store)
    assert len(store.weather()[store.weather()["date"] >= date(2026, 1, 1)]) == 7
    assert _state(store)["quota"]["2026-01-11"]["weather_daily"] == 7


# ---------------- main: 종료 코드 ----------------
@pytest.fixture
def run_main(collector, store, monkeypatch):
    def run(hub, *argv):
        monkeypatch.setattr(collector, "HubClient", lambda: hub)
        monkeypatch.setattr(collector, "DataStore", lambda: store)
        monkeypatch.setattr(collector, "_today", lambda: TODAY)
        return collector.main(["--years", "1", "--item", "carrot", "--default-only", "--no-weather", *argv])
    return run


def test_main_exit_codes(collector, store, run_main, capsys):
    bad = lambda p: p.get("startDate", "").startswith("202603")  # noqa: E731
    assert run_main(FakeHub(fail=bad)) == collector.EXIT_PARTIAL
    assert "--retry-failed" in capsys.readouterr().out
    assert run_main(FakeHub(), "--retry-failed") == collector.EXIT_OK
    assert run_main(FakeHub(), "--stats-budget", "0") == collector.EXIT_QUOTA
    assert run_main(FakeHub(interrupt_at=0), "--stats-budget", "9999") == collector.EXIT_INTERRUPTED
    assert run_main(FakeHub(), "--status") == collector.EXIT_OK
    assert CARROT in capsys.readouterr().out


def test_main_reports_save_failure_and_keeps_state_behind_data(collector, store, run_main, monkeypatch, capsys):
    real_upsert, calls = store.upsert, []

    def flaky_upsert(dataset, new, keys):
        calls.append(1)
        if len(calls) >= 4:
            raise PermissionError("다른 프로그램이 daily_stats.csv 를 사용 중")
        return real_upsert(dataset, new, keys)

    monkeypatch.setattr(store, "upsert", flaky_upsert)
    hub = FakeHub()
    assert run_main(hub) == collector.EXIT_PARTIAL
    assert "저장하지 못해" in capsys.readouterr().out
    saved = store.stats(CARROT)
    entry = _state(store)["stats"][CARROT]
    assert date.fromisoformat(entry["done_through"]) == max(saved["date"]) == date(2025, 11, 17) + timedelta(days=29)
    assert entry["rows_saved"] == len(saved)
    assert _state(store)["quota"][TODAY.isoformat()]["daily_stats"] == len(hub.requests) == 4
    monkeypatch.setattr(store, "upsert", real_upsert)
    assert run_main(FakeHub()) == collector.EXIT_OK and max(store.stats(CARROT)["date"]) == TODAY


def test_main_flags_run_after_corrupt_state(collector, store, run_main, capsys):
    assert run_main(FakeHub()) == collector.EXIT_OK
    (store.root / "collect_state.json").write_text("{ 깨진 파일", encoding="utf-8")
    assert run_main(FakeHub(), "--status") == collector.EXIT_PARTIAL  # 상태 보기는 깨진 파일을 치우지 않는다
    assert not (store.root / "collect_state.json.corrupt").exists()
    assert run_main(FakeHub()) == collector.EXIT_PARTIAL
    assert (store.root / "collect_state.json.corrupt").exists()
    assert "validate_cache.py" in capsys.readouterr().out
    assert run_main(FakeHub()) == collector.EXIT_OK


def test_main_refuses_synthetic_cache_and_unknown_item(collector, store, run_main, monkeypatch):
    hub = FakeHub()
    assert collector.main(["--item", "tangerine"]) == collector.EXIT_SETUP
    (store.root / "SYNTHETIC").write_text("합성 자료", encoding="utf-8")
    assert run_main(hub) == collector.EXIT_SETUP and hub.requests == []


def test_main_reports_missing_key_without_traceback(collector, store, monkeypatch):
    def no_key():
        raise HubError("JEJU_HUB_PROJECT_KEY 가 비어 있습니다. .env 를 확인하세요.")

    monkeypatch.setattr(collector, "HubClient", no_key)
    monkeypatch.setattr(collector, "DataStore", lambda: store)
    assert collector.main(["--no-weather"]) == collector.EXIT_SETUP


# ---------------- 캐시 검증 도구 ----------------
def _collected(collector, store):
    _stats(collector, FakeHub(), store)
    return store


def test_validate_passes_on_clean_cache(collector, validator, store):
    _collected(collector, store)
    rep = validator.validate(store.root, TODAY, items=["carrot"], default_only=True)
    assert rep.ok and rep.errors == []
    summary = rep.cultivars[CARROT]
    assert summary["last"] == TODAY.isoformat() and summary["gaps"] == 0 and summary["unit_error_median"] == 0
    assert any("weather_daily.csv" in w for w in rep.warnings)
    assert validator.main(["--data-dir", str(store.root), "--item", "carrot", "--default-only", "--asof", TODAY.isoformat()]) == 0
    assert validator.main(["--data-dir", str(store.root), "--item", "carrot", "--default-only", "--asof", TODAY.isoformat(), "--strict"]) == 2


def test_validate_reports_missing_file_and_missing_default_cultivar(collector, validator, store):
    rep = validator.validate(store.root, TODAY)
    assert not rep.ok and any("daily_stats.csv 가 없습니다" in e for e in rep.errors)
    _collected(collector, store)
    rep = validator.validate(store.root, TODAY, default_only=True)
    assert sum("기본 품종" in e for e in rep.errors) == 4  # 당근만 받았으므로 나머지 4품목이 없다
    assert validator.main(["--data-dir", str(store.root)]) == 1


def test_validate_detects_duplicates_gaps_stale_and_bad_values(collector, validator, store):
    _collected(collector, store)
    path = store.path("daily_stats")
    df = pd.read_csv(path)
    df = df[~df["date"].between("2026-05-01", "2026-05-31")]             # 한 달 누락
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)                 # 중복 행
    df.loc[1, "price"] = 0                                                 # 0원 가격
    df.loc[2, "amount"] = -5                                               # 음수
    df.loc[3, "price"] = None                                              # 휴장일이 아닌데 빈 가격
    df.to_csv(path, index=False)
    rep = validator.validate(store.root, TODAY + timedelta(days=30), items=["carrot"], default_only=True)
    text = "\n".join(rep.errors + rep.warnings)
    for expected in ("중복 행 1개", "가격 0원 행 1개", "음수 값 행 1개", "날짜 공백 1곳", "일 지났습니다", "가격이 빈 행 1개"):
        assert expected in text, expected
    assert not rep.ok


def test_validate_flags_unit_mismatch_and_unknown_cultivar(collector, validator, store):
    _collected(collector, store)
    path = store.path("daily_stats")
    df = pd.read_csv(path)
    df["amount"] = df["amount"] * 1000  # 백만원이 아니라 천원 단위로 들어온 경우
    df.loc[0, "cultivar"] = "당근"
    df.to_csv(path, index=False)
    rep = validator.validate(store.root, TODAY, items=["carrot"], default_only=True)
    text = "\n".join(rep.warnings)
    assert "단위(원/kg·톤·백만원)" in text and "설정에 없는 품종 문자열 '당근'" in text


def test_validate_reports_state_failures_synthetic_and_weather(collector, validator, store, monkeypatch):
    [res] = _stats(collector, FakeHub(fail=lambda p: p.get("startDate", "").startswith("202603")), store)
    assert res["failed"] == 3
    hub = FakeHub(fail=lambda p: p.get("searchDate") == "20260105" and p.get("observatoryName") == "구좌")
    with monkeypatch.context() as m:
        _use_one_station(m)
        _weather(collector, hub, store)
    wpath = store.path("weather_daily")
    w = pd.read_csv(wpath)
    w = pd.concat([w, w.iloc[[0]]], ignore_index=True)
    w.loc[1, "temp_min"] = 80
    w.to_csv(wpath, index=False)
    (store.root / "SYNTHETIC").write_text("합성 자료", encoding="utf-8")
    rep = validator.validate(store.root, TODAY)
    text = "\n".join(rep.errors + rep.warnings)
    for expected in ("실패 구간 3개가 남았습니다", "실패 날짜 1건이 남았습니다", "(날짜, 관측소) 중복 행 1개",
                     "범위를 벗어난 값 1개", "합성 자료 표시"):
        assert expected in text, expected
    assert validator.validate(store.root, TODAY, allow_synthetic=True).errors != rep.errors


def test_validate_warns_when_history_is_missing_or_run_unfinished(collector, validator, store):
    _stats(collector, FakeHub(), store, today=TODAY, budget=None)
    assert not any("첫 날짜" in w for w in validator.validate(store.root, TODAY, items=["carrot"], default_only=True, years=1).warnings)
    rep2 = validator.validate(store.root, TODAY, items=["carrot"], default_only=True, years=2)
    text = "\n".join(rep2.warnings)
    assert "앞 구간 누락 의심" in text and rep2.ok
    assert "거래일이 314일뿐" in "\n".join(validator.validate(store.root, TODAY, items=["carrot"], default_only=True, years=4).warnings)

    state = _state(store)
    state["stats"][CARROT]["status"] = "quota"
    (store.root / "collect_state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    text = "\n".join(validator.validate(store.root, TODAY, items=["carrot"], default_only=True, years=1).warnings)
    assert "마지막 수집이 끝나지 않았습니다 (하루 예산 소진으로 중단)" in text


def test_validate_handles_unreadable_csv(validator, store):
    store.path("daily_stats").write_bytes(b"")
    rep = validator.validate(store.root, TODAY)
    assert not rep.ok and any("읽을 수 없습니다" in e for e in rep.errors)

# ---------------- Codex 최종 재검토 회귀 ----------------
@pytest.mark.parametrize('payload', [
    {'totCnt': 0, 'message': 'quota exceeded'},
    {'totCnt': 0, 'data': [], 'message': '일일 호출 한도 초과'},
    {'data': [], 'success': False},
    {'data': [], 'resultCode': '403'},
    {'data': [], 'error': {'message': 'quota exceeded'}},
    {'message': 'quota exceeded'},
])
def test_business_error_is_not_an_empty_success(payload):
    rows, total, meta = hub_client._find_rows(payload)
    response = HubResponse(rows, total, list(payload), 'masked', 200, 1, meta)
    with pytest.raises(HubError):
        hub_client.validate_response(response)


def test_weather_records_business_error_as_failed(collector, store, one_station):
    class ErrorHub(FakeHub):
        def call(self, data_key, **params):
            self.attempts += 1
            self.requests.append(params)
            return HubResponse([], 0, ['totCnt', 'message'], 'masked', 200, 1,
                               {'message': 'quota exceeded'})
    hub = ErrorHub()
    result = _weather(collector, hub, store)
    assert result['status'] == 'aborted'
    assert result['ok_calls'] == 0 and result['failed'] == collector.MAX_CONSECUTIVE_FAILURES
    assert max(store.weather()['date']) == date(2025, 12, 31)
    assert len(store.weather()) == 710


def test_lock_blocks_another_process_and_releases_after_exit(collector, store):
    import subprocess
    code = '''
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('collect_child', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
try:
    with module.collection_lock(Path(sys.argv[2])):
        pass
except module.CollectorBusy:
    raise SystemExit(19)
'''
    args = [sys.executable, '-c', code, str(SCRIPTS / 'collect.py'), str(store.root)]
    with collector.collection_lock(store.root):
        assert subprocess.run(args, capture_output=True).returncode == 19
    assert subprocess.run(args, capture_output=True).returncode == 0


def test_main_does_not_request_hub_while_locked(collector, store, run_main):
    hub = FakeHub()
    with collector.collection_lock(store.root):
        assert run_main(hub) == collector.EXIT_SETUP
        assert hub.requests == []
        assert run_main(hub, '--status') == collector.EXIT_OK
    assert run_main(hub, '--stats-budget', '0') == collector.EXIT_QUOTA


@pytest.mark.parametrize('status', [401, 403])
def test_auth_failure_stops_after_first_request(collector, store, run_main, status):
    class DeniedHub(FakeHub):
        def call(self, data_key, **params):
            self.attempts += 1
            self.requests.append(params)
            raise HubError('HTTP 인증 거부', status=status)
    hub = DeniedHub()
    assert run_main(hub) == collector.EXIT_SETUP
    assert len(hub.requests) == 1
    assert len(_state(store)['stats'][CARROT]['failed']) == 1


@pytest.mark.parametrize('contents', [b'', b'date,cultivar,price\nnot-a-date,x,1\n'])
def test_main_reports_broken_csv_without_destroying_it(collector, store, run_main, capsys, contents):
    path = store.path('daily_stats')
    path.write_bytes(contents)
    hub = FakeHub()
    assert run_main(hub) == collector.EXIT_PARTIAL
    assert path.read_bytes() == contents and hub.requests == []
    assert '형식이 손상' in capsys.readouterr().out


def test_validator_returns_report_when_all_weather_dates_are_invalid(validator, store):
    store.path('weather_daily').write_text('date,station,temp_min,rain\nnot-a-date,구좌,1,0\n', encoding='utf-8')
    report = validator.validate(store.root)
    assert any('날짜를 읽을 수 없는' in error for error in report.errors)
    assert report.weather == {}
