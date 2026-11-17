#!/usr/bin/env python3
"""데이터 적재 — 허브 Open API 실측 특성(10행 한도·페이징 없음·초당 1회) 반영판.

사용법:  python scripts/collect.py                 # 전 품목 증분(없으면 2년) + 기상(하루 예산 내)
        python scripts/collect.py --item carrot    # 한 품목만
        python scripts/collect.py --default-only   # 품목별 기본 품종만 (처음 적재할 때 권장)
        python scripts/collect.py --no-weather     # 거래 통계만
        python scripts/collect.py --weather-only   # 기상만 (일 쿼터 1000 → 예산 900, 여러 날에 나눠 실행)
        python scripts/collect.py --retry-failed   # 지난 실행에서 실패한 구간만 다시 받기
        python scripts/collect.py --status         # 허브 호출 없이 수집 상태만 보기

동작
  - 창(10일) 하나를 받을 때마다 CSV 와 상태 파일(collect_state.json)을 저장한다 → 중간에 끊겨도 받은 만큼 남고 이어서 받는다.
  - 실패한 창은 상태 파일에 남기고 다음 창으로 넘어간다. 다음 실행(또는 --retry-failed)에서 먼저 다시 받는다.
  - 호출 수는 재시도를 포함해 날짜별로 상태 파일에 누적한다. 같은 날 여러 번 실행해도 하루 예산을 넘기지 않는다.
    (check_api.py 등 다른 도구의 호출은 세지 않으므로 예산을 쿼터의 90% 로 잡는다. 한 번의 호출이 재시도로
     예산을 몇 건 넘길 수 있다. 날짜는 실행을 시작한 PC 의 날짜 기준이다.)
  - CSV 는 임시 파일에 쓴 뒤 교체한다 → 쓰는 도중 꺼져도 기존 자료가 깨지지 않는다.

종료 코드
  0   요청한 범위를 모두 받음
  1   시작할 수 없음 (프로젝트 키 없음·합성 캐시 존재·잘못된 품목)
  2   일부 구간 실패가 남았거나 연속 실패로 중단, 기본 품종이 0행, 저장 실패, 상태 파일 손상
      → 안내 문구 확인 후 --retry-failed 또는 다시 실행
  3   하루 예산 소진으로 중단 (실패 구간 없음) → 내일 다시 실행하면 이어서 받음
  130 사용자가 중단(Ctrl+C) — 받은 만큼 저장됨

호출 수 안내 (2년 기준)
  거래 통계: 10일 창 → 약 73콜 × 품종 수 (당근 3 + 무 2 + 양배추 2 + 마늘 1 + 양파 1 = 9품종 ≈ 660콜, 쿼터 3000)
  기상: 관측소별·일별 1콜, 출하기 7개월만 → 구좌·성산·한림 3곳 × 약 420일 ≈ 1260콜 → 2회에 나눠 실행 (예산 900/일)
       서광은 필터 없는 호출의 기본 10곳에 포함되므로 별도 호출 없이 함께 저장됨
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import config  # noqa: E402
from app.data_store import DataStore, atomic_write_text, normalize  # noqa: E402
from app.hub_client import HubClient, HubError, validate_response  # noqa: E402

STATE_FILE = "collect_state.json"
STATE_VERSION = 1
WINDOW_DAYS = HubClient.DEFAULT_WINDOW_DAYS
day_chunks = HubClient.day_chunks

EXIT_OK, EXIT_SETUP, EXIT_PARTIAL, EXIT_QUOTA, EXIT_INTERRUPTED = 0, 1, 2, 3, 130

OVERLAP_DAYS = 7               # 증분 수집 시 최근 며칠을 다시 받아 정정분을 반영
MAX_CONSECUTIVE_FAILURES = 5   # 연속 실패가 이만큼이면 네트워크·키 문제로 보고 중단(쿼터 보호)
QUOTA_KEEP_DAYS = 14           # 날짜별 호출 기록 보관 기간
BUDGET_RATIO = 0.9             # 하루 예산 기본값 = 데이터셋 쿼터 × 0.9

STATUS_LABEL = {"ok": "완료", "partial": "실패 구간 남음", "quota": "예산 소진", "aborted": "연속 실패로 중단",
                "skipped": "실행 안 함", "new": "미수집", "empty": "자료 0행", "running": "중단됨(미완료)"}
UNFINISHED = ("quota", "aborted", "running", "empty", "new")  # 재시도만 한 실행이 '완료'로 덮으면 안 되는 상태


def _today() -> date:
    return date.today()


def _years_ago(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:  # 2월 29일
        return d.replace(year=d.year - years, day=28)


def _parse(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _short_error(err: Exception, secret: str | None = None) -> str:
    """상태 파일·화면에 남길 오류 요약. 호출 URL 과 프로젝트 키는 남기지 않는다."""
    msg = re.sub(r"\s*\(https?://[^)\s]*\)", "", str(err))
    msg = re.sub(r"https?://\S+", "<url>", msg)
    if secret:
        msg = msg.replace(secret, "****")
    return " ".join(msg.split())[:200]


class CollectorBusy(OSError):
    pass


@contextmanager
def collection_lock(root: Path):
    """캐시 폴더별 단일 수집만 허용한다. 프로세스 종료 시 OS가 잠금을 해제한다."""
    lock_file = (Path(root) / ".collect.lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            if lock_file.seek(0, os.SEEK_END) == 0:
                lock_file.write(b"0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        lock_file.close()
        raise CollectorBusy("같은 캐시에서 다른 수집기가 실행 중입니다. 종료 후 다시 실행하세요.") from error
    try:
        yield
    finally:
        try:
            if os.name == "nt":
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()


# ---- 상태 파일 ------------------------------------------------------------
class CollectState:
    """수집 진행 상태. 캐시 폴더의 collect_state.json (data/ 는 git 에 올라가지 않는다).

    quota   : {날짜: {데이터셋: 재시도 포함 호출 수}}
    stats   : {품종: {since, done_through, failed[{start,end,error,tries,last_try}], rows_saved, status, last_run}}
    weather : {failed[{station,date,error,tries,last_try}], status, last_run}
    """

    def __init__(self, root: Path, read_only: bool = False):
        self.path = Path(root) / STATE_FILE
        self.read_only = read_only  # --status 용: 깨진 파일을 옮기지 않는다
        self.recovered = False      # 읽을 수 없는 상태 파일 대신 빈 상태로 시작했는지
        self.data = self._load()

    @staticmethod
    def _empty() -> dict:
        return {"version": STATE_VERSION, "quota": {}, "stats": {}, "weather": {"failed": []}}

    def _load(self) -> dict:
        if not self.path.exists():
            return self._empty()
        raw = self.path.read_bytes()  # 읽기 자체가 안 되면(잠금 등) OSError 그대로 올린다
        try:
            data = json.loads(raw.decode("utf-8"))  # 다른 인코딩으로 저장된 파일도 '읽을 수 없음'으로 처리
            if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
                raise ValueError("형식이 다릅니다")
            if not isinstance(data.get("quota"), dict) or not isinstance(data.get("stats"), dict):
                raise ValueError("필수 항목이 없습니다")
            weather = data.setdefault("weather", {"failed": []})
            if not isinstance(weather, dict) or not isinstance(weather.setdefault("failed", []), list):
                raise ValueError("기상 항목 형식이 다릅니다")
            return data
        except ValueError as e:
            self.recovered = True
            if self.read_only:
                print(f"! 상태 파일을 읽을 수 없습니다 ({e}). 다음 수집 실행에서 새로 만듭니다.")
                return self._empty()
            backup = self.path.with_name(STATE_FILE + ".corrupt")
            try:
                os.replace(self.path, backup)
                kept = f"기존 파일은 {backup.name} 로 옮겼습니다."
            except OSError:
                kept = "기존 파일을 옮기지 못했습니다."
            print(f"! 상태 파일을 읽을 수 없어 새로 시작합니다 ({e}). {kept}\n"
                  "  오늘 이미 수집을 실행했다면 호출 기록이 사라졌으니 --stats-budget / --weather-budget 를 낮춰 실행하세요.\n"
                  "  실패 구간 기록도 사라졌습니다. 수집 뒤 scripts/validate_cache.py 로 날짜 공백을 확인하세요.")
            return self._empty()

    def save(self) -> None:
        atomic_write_text(self.path, json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    def used(self, day: date, dataset: str) -> int:
        return int(self.data["quota"].get(day.isoformat(), {}).get(dataset, 0))

    def charge(self, day: date, dataset: str, n: int) -> None:
        if n > 0:
            bucket = self.data["quota"].setdefault(day.isoformat(), {})
            bucket[dataset] = int(bucket.get(dataset, 0)) + n

    def prune(self, day: date) -> None:
        cutoff = (day - timedelta(days=QUOTA_KEEP_DAYS)).isoformat()
        self.data["quota"] = {k: v for k, v in self.data["quota"].items() if k >= cutoff}

    def stats_entry(self, cultivar: str) -> dict:
        entry = self.data["stats"].setdefault(cultivar, {})
        entry.setdefault("done_through", None)
        entry.setdefault("since", None)  # 이 품종을 받기 시작한 날짜(수집 기간의 시작)
        entry.setdefault("failed", [])
        entry.setdefault("rows_saved", 0)
        entry.setdefault("status", "new")
        entry.setdefault("last_run", None)
        return entry


class Quota:
    """데이터셋 하나의 하루 누적 예산. 호출 수는 HubClient.attempts(재시도 포함) 증가분으로 센다."""

    def __init__(self, state: CollectState, dataset: str, day: date, budget: int):
        self.state, self.dataset, self.day, self.budget = state, dataset, day, int(budget)
        self.spent = 0  # 이번 실행에서 쓴 호출 수

    @property
    def remaining(self) -> int:
        return self.budget - self.state.used(self.day, self.dataset)

    def run(self, hub, fn):
        before = getattr(hub, "attempts", None)
        try:
            return fn()
        finally:
            after = getattr(hub, "attempts", None)
            n = (after - before) if isinstance(before, int) and isinstance(after, int) else 1
            self.state.charge(self.day, self.dataset, n)
            self.spent += max(n, 0)


def default_budget(dataset: str) -> int:
    return int(config.datasets()[dataset].get("quota_per_day", 1000) * BUDGET_RATIO)


def _merge_failed(failed: list[dict], match: dict, error: str, today: date) -> None:
    for f in failed:
        if all(f.get(k) == v for k, v in match.items()):
            f["tries"] = int(f.get("tries", 1)) + 1
            f["error"], f["last_try"] = error, today.isoformat()
            return
    failed.append({**match, "error": error, "tries": 1, "last_try": today.isoformat()})


# ---- 거래 통계 ------------------------------------------------------------
def collect_stats(hub, store: DataStore, item_filter: str | None, years: int, today: date,
                  state: CollectState | None = None, budget: int | None = None,
                  retry_only: bool = False, default_only: bool = False) -> list[dict]:
    """품종별 거래 통계를 창 단위로 받아 저장한다. 품종별 결과 목록을 돌려준다."""
    state = state or CollectState(store.root)
    quota = Quota(state, "daily_stats", today, default_budget("daily_stats") if budget is None else budget)
    start_default = _years_ago(today, years)
    results: list[dict] = []
    stopped: str | None = None
    for key, it in config.items().items():
        if item_filter and key != item_filter:
            continue
        cultivars = [it["cultivars"]["default"]] if default_only else it["cultivars"]["all"]
        for cv in cultivars:
            if stopped:
                results.append({"item": it["name"], "cultivar": cv, "status": "skipped", "received": 0,
                                "calls": 0, "failed": len(state.stats_entry(cv)["failed"]),
                                "default": cv == it["cultivars"]["default"]})
                continue
            is_default = cv == it["cultivars"]["default"]
            res = _collect_cultivar(hub, store, state, quota, it["name"], cv, start_default, today, retry_only, is_default)
            res["default"] = is_default
            results.append(res)
            if res["status"] in ("quota", "aborted"):
                stopped = res["status"]
    return results


def _collect_cultivar(hub, store: DataStore, state: CollectState, quota: Quota, item_name: str, cv: str,
                      start_default: date, today: date, retry_only: bool, is_default: bool = True) -> dict:
    entry = state.stats_entry(cv)
    prev_status = entry["status"]
    existing = store.stats(cv)
    last = max(existing["date"]) if not existing.empty else None
    if last is None and entry["rows_saved"] and not retry_only:
        print(f"[{item_name}/{cv}] 상태 파일에는 수집 기록이 있지만 캐시에 자료가 없어 처음부터 다시 받습니다.")
        entry.update(done_through=None, since=None, failed=[], rows_saved=0)
    if last is None and not entry["since"] and not retry_only:
        entry["done_through"] = None  # 시작 날짜 기록도 자료도 없으면 진행 지점을 믿지 않고 처음부터 받는다

    new_range = ""
    new_tasks: list[tuple[date, date, bool]] = []
    if not retry_only:
        # 상태 파일의 진행 지점이 있으면 그것을, 없으면(예전 수집기로 받은 캐시) 캐시의 마지막 날짜를 기준으로 한다.
        anchor = _parse(entry["done_through"]) or last
        if anchor is None:
            start = start_default
            entry["since"] = start_default.isoformat()
        else:
            start = min(anchor, today) - timedelta(days=OVERLAP_DAYS)
            since = _parse(entry["since"])
            if since is None and not existing.empty:
                since = min(existing["date"])  # 예전 수집기로 받은 캐시: 가장 이른 자료 날짜를 시작으로 본다
            if since and start_default < since:
                # --years 를 늘렸거나 예전 캐시가 더 늦게 시작한다 → 앞 구간을 '받아야 할 구간'으로 등록해 끊겨도 잊지 않게 한다.
                for s, e in day_chunks(start_default, since - timedelta(days=1), WINDOW_DAYS):
                    if not any(f["start"] == s.isoformat() and f["end"] == e.isoformat() for f in entry["failed"]):
                        entry["failed"].append({"start": s.isoformat(), "end": e.isoformat(), "error": "수집 기간 확장(미수집)",
                                                "tries": 0, "last_try": None})
                entry["failed"].sort(key=lambda f: f["start"])
            if since is None or start_default < since:
                entry["since"] = start_default.isoformat()
        new_tasks = [(s, e, False) for s, e in day_chunks(start, today, WINDOW_DAYS)]
        new_range = f", 신규 {start}~{today} {len(new_tasks)}구간"
    # (시작, 끝, 재시도 여부). 실패했던 창을 먼저 다시 받는다.
    tasks: list[tuple[date, date, bool]] = [(_parse(f["start"]), _parse(f["end"]), True) for f in entry["failed"]]
    tasks += new_tasks
    if not retry_only:
        entry["status"] = "running"  # 끝까지 가면 아래에서 결과로 바꾼다. 중단되면 이 값이 남는다.
    n_retry = sum(1 for t in tasks if t[2])
    print(f"[{item_name}/{cv}] 재시도 {n_retry}구간{new_range} (점 = 호출 성공, x = 재시도) ", end="", flush=True)

    p = SimpleNamespace(rows=[], resolved=[], failed=[], done=None)
    received = 0
    secret = getattr(hub, "project_key", None)

    def flush() -> None:
        """자료를 먼저 저장하고, 성공한 뒤에만 진행 상태를 갱신한다(상태가 자료보다 앞서지 않게)."""
        nonlocal received
        if p.rows:
            df = normalize(p.rows, "daily_stats")
            if not df.empty:
                store.upsert("daily_stats", df, ["date", "cultivar"])
            p.rows = []  # 저장이 끝난 행은 바로 비운다(상태 저장이 실패해 다시 불려도 중복 집계하지 않게)
            entry["rows_saved"] += len(df)
            received += len(df)
        if p.resolved:
            done_keys = {(s.isoformat(), e.isoformat()) for s, e in p.resolved}
            entry["failed"] = [f for f in entry["failed"] if (f["start"], f["end"]) not in done_keys]
        for s, e, msg in p.failed:
            _merge_failed(entry["failed"], {"start": s.isoformat(), "end": e.isoformat()}, msg, today)
        entry["failed"].sort(key=lambda f: f["start"])
        if p.done and (not entry["done_through"] or p.done.isoformat() > entry["done_through"]):
            entry["done_through"] = p.done.isoformat()
        p.resolved, p.failed, p.done = [], [], None  # 반영을 마친 뒤 비운다(상태 저장이 실패해 다시 불려도 두 번 세지 않게)
        state.save()

    outcome: str | None = None
    consecutive = 0
    skip_retries = False
    in_new = False
    try:
        for s, e, is_retry in tasks:
            if is_retry and skip_retries:
                continue
            if not is_retry and not in_new:
                in_new = True
                consecutive = 0  # 재시도 구간의 연속 실패는 신규 구간으로 넘기지 않는다
            if quota.remaining <= 0:
                outcome = "quota"
                print(f"\n   ! 거래 통계 하루 예산 {quota.budget}건 소진 → 내일 다시 실행하면 이어서 받습니다.", end="")
                break
            try:
                rows = quota.run(hub, lambda: hub.fetch_window("daily_stats", s, e, cultivar=cv))
            except HubError as err:
                consecutive += 1
                msg = _short_error(err, secret)
                p.failed.append((s, e, msg))
                if getattr(err, "status", None) in (401, 403):
                    raise
                print(f"\n   ! {s}~{e} 실패: {msg} ", end="", flush=True)
            else:
                consecutive = 0
                p.rows.extend(rows)
                if is_retry:
                    p.resolved.append((s, e))
            if not is_retry:
                p.done = e  # 실패한 창도 실패 목록에 남으므로 진행 지점은 넘긴다
            flush()
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                if is_retry and new_tasks:
                    # 오래된 실패 구간이 계속 안 받아져도 최신 자료 수집까지 막지는 않는다.
                    skip_retries = True
                    print(f"\n   ! 재시도 {consecutive}구간 연속 실패 → 남은 재시도는 다음 실행으로 미루고 신규 구간을 받습니다. ", end="")
                    continue
                outcome = "aborted"
                print(f"\n   ! {consecutive}구간 연속 실패 → 네트워크·프로젝트 키를 확인하세요. 수집을 멈춥니다.", end="")
                break
    finally:
        flush()

    mine = store.stats(cv)
    if outcome is None:
        outcome = "partial" if entry["failed"] else "ok"
    if mine.empty and outcome == "ok":
        # 전 구간이 0행이면 '완료'로 굳히지 않는다. 실패 구간이 남아 있으면 그쪽(partial)이 우선이다.
        outcome = "empty"
        if is_default:  # 기본 품종은 화면에 꼭 필요하므로 다음 실행에서 처음부터 다시 받는다
            entry["done_through"] = None
        print("\n   ! 받은 자료가 0행입니다. 품종 문자열과 허브 상태를 scripts/check_api.py 로 확인하세요.", end="")
    if retry_only and outcome in ("ok", "partial") and prev_status in UNFINISHED:
        entry["status"] = prev_status  # 재시도만 한 실행이 끝나지 않은 수집을 '완료'·'실패 구간 남음'으로 덮지 않는다
        print(f"\n   (전체 수집은 아직 끝나지 않았습니다: {STATUS_LABEL[prev_status]} → --retry-failed 없이 다시 실행하세요)", end="")
    else:
        entry["status"] = outcome
    entry["last_run"] = today.isoformat()
    state.save()

    latest = max(mine["date"]).isoformat() if not mine.empty else None
    print(f"\n   → {STATUS_LABEL[outcome]}: 이번 {received}행, 누적 {len(mine)}행, 최신 {latest or '없음'}, "
          f"실패 구간 {len(entry['failed'])}개")
    return {"item": item_name, "cultivar": cv, "status": outcome, "received": received, "total": len(mine),
            "latest": latest, "failed": len(entry["failed"]), "calls": quota.spent}


# ---- 기상 -----------------------------------------------------------------
def _season_days(start: date, end: date, months: list[int]):
    d = start
    while d <= end:
        if d.month in months:
            yield d
        d += timedelta(days=1)


def collect_weather(hub, store: DataStore, years: int, today: date, budget: int,
                    state: CollectState | None = None, retry_only: bool = False) -> dict:
    """기상 자료를 하루 단위로 받는다. budget 은 오늘 누적 호출 한도(재시도 포함)다."""
    state = state or CollectState(store.root)
    quota = Quota(state, "weather_daily", today, budget)
    wstate = state.data["weather"]
    prev_status = wstate.get("status")
    cc = config.collect_config()
    months = cc.get("weather_months", list(range(1, 13)))
    free = set(cc.get("weather_free_stations", []))
    need: list[str] = []
    for it in config.items().values():
        for s_ in [it["station"]["primary"], *it["station"].get("fallback", [])[:1]]:
            if s_ not in need:
                need.append(s_)
    filtered = [s_ for s_ in need if s_ not in free]
    print(f"[기상] 필요 관측소 {need} / 필터 호출 필요 {filtered} / 기본 응답 포함 {sorted(set(need) & free)}")

    existing = store.weather()
    start_default = _years_ago(today, years)
    # 관측소 None = 필터 없는 호출(기본 10곳 — 서광 등)
    jobs: list[tuple[str | None, date]] = []
    for st in [None, *filtered]:
        have = set()
        if not existing.empty:
            sub = existing if st is None else existing[existing["station"] == st]
            have = set(sub["date"]) if st is not None else set(existing[existing["station"].isin(free)]["date"])
        for d in _season_days(start_default, today - timedelta(days=1), months):
            if d not in have:
                jobs.append((st, d))
    job_keys = {(st, d.isoformat()) for st, d in jobs}
    # 이미 자료가 들어왔거나 수집 범위를 벗어난 실패 기록은 정리한다.
    wstate["failed"] = [f for f in wstate["failed"] if (f.get("station"), f.get("date")) in job_keys]
    if retry_only:
        jobs = [(f["station"], _parse(f["date"])) for f in wstate["failed"]]
    print(f"[기상] 남은 호출 {len(jobs)}건, 오늘 남은 예산 {max(quota.remaining, 0)}건 (하루 {quota.budget}건)")

    data_key = config.datasets()["weather_daily"]["data_key"]
    secret = getattr(hub, "project_key", None)
    p = SimpleNamespace(rows=[], resolved=[], failed=[])

    def flush() -> None:
        if p.rows:
            df = normalize(p.rows, "weather_daily")
            if not df.empty:
                store.upsert("weather_daily", df, ["date", "station"])
            p.rows = []
        if p.resolved:
            done_keys = {(st, d.isoformat()) for st, d in p.resolved}
            wstate["failed"] = [f for f in wstate["failed"] if (f.get("station"), f.get("date")) not in done_keys]
        for st, d, msg in p.failed:
            _merge_failed(wstate["failed"], {"station": st, "date": d.isoformat()}, msg, today)
        p.resolved, p.failed = [], []
        state.save()

    used = 0
    consecutive = 0
    outcome: str | None = None
    empty_streak: dict = {}
    skipped_stations: set = set()
    try:
        for st, d in jobs:
            if st in skipped_stations:
                continue
            if quota.remaining <= 0:
                outcome = "quota"
                print(f"[기상] 하루 예산 {quota.budget}건 소진 → 내일 다시 실행하면 이어서 받습니다.")
                break
            params = {"searchDate": d.strftime("%Y%m%d")}
            if st:
                params["observatoryName"] = st
            try:
                def fetch_weather_day():
                    response = hub.call(data_key, **params)
                    validate_response(response)
                    return response
                r = quota.run(hub, fetch_weather_day)
            except HubError as err:
                consecutive += 1
                msg = _short_error(err, secret)
                p.failed.append((st, d, msg))
                if getattr(err, "status", None) in (401, 403):
                    raise
                print(f"  실패: {d} {st or '(기본10곳)'} {msg}")
            else:
                consecutive = 0
                used += 1
                p.resolved.append((st, d))
                if r.rows:
                    p.rows.extend(r.rows)
                    empty_streak[st] = 0
                else:
                    empty_streak[st] = empty_streak.get(st, 0) + 1
                if used % 50 == 0:
                    print(f"  ... {used}콜, 마지막 {d} {st or '(기본10곳)'} rows={len(r.rows)}")
                if empty_streak.get(st, 0) >= 45 and d > date(2025, 1, 1):
                    print(f"  ! {d} 까지 45일 연속 자료 없음 → 허브 기상 갱신이 멈춘 구간으로 보고 이 관측소는 중단")
                    empty_streak[st] = 0
                    skipped_stations.add(st)  # 같은 관측소의 남은 날짜 건너뛰기
            flush()  # 호출마다 저장한다 → 강제 종료돼도 자료와 호출 수 기록이 남는다
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                outcome = "aborted"
                print(f"[기상] {consecutive}건 연속 실패 → 네트워크·프로젝트 키를 확인하세요. 수집을 멈춥니다.")
                break
    finally:
        flush()

    if outcome is None:
        outcome = "partial" if wstate["failed"] else "ok"
    keep_prev = retry_only and outcome in ("ok", "partial") and prev_status in UNFINISHED
    wstate["status"], wstate["last_run"] = (prev_status if keep_prev else outcome), today.isoformat()
    state.save()
    w = store.weather()
    if not w.empty:
        print(f"[기상] 누적 {len(w)}행, 관측소 {w['station'].nunique()}곳, 기간 {min(w['date'])}~{max(w['date'])}")
    print(f"[기상] {STATUS_LABEL[outcome]}: 이번 성공 {used}콜, 실패 날짜 {len(wstate['failed'])}건")
    return {"status": outcome, "calls": quota.spent, "ok_calls": used, "failed": len(wstate["failed"]), "rows": len(w)}


# ---- 요약·진입점 ----------------------------------------------------------
def print_status(state: CollectState, today: date) -> None:
    q = state.data["quota"].get(today.isoformat(), {})
    print(f"상태 파일: {state.path}")
    print(f"오늘({today}) 누적 호출: 거래 통계 {q.get('daily_stats', 0)}건, 기상 {q.get('weather_daily', 0)}건")
    if not state.data["stats"]:
        print("거래 통계: 수집 기록 없음")
    for cv, e in sorted(state.data["stats"].items()):
        print(f"  {cv}: {STATUS_LABEL.get(e.get('status'), e.get('status'))}, 진행 {e.get('done_through') or '-'}, "
              f"저장 {e.get('rows_saved', 0)}행, 실패 구간 {len(e.get('failed', []))}개, 마지막 실행 {e.get('last_run') or '-'}")
        for f in e.get("failed", []):
            print(f"     - {f['start']}~{f['end']} ({f.get('tries', 1)}회 시도) {f.get('error', '')}")
    w = state.data["weather"]
    print(f"기상: {STATUS_LABEL.get(w.get('status'), '수집 기록 없음')}, 실패 날짜 {len(w['failed'])}건, "
          f"마지막 실행 {w.get('last_run') or '-'}")


def _print_summary(results: list[dict], weather: dict | None) -> None:
    print("\n== 수집 결과 ==")
    for r in results:
        print(f"  {r['item']}/{r['cultivar']}: {STATUS_LABEL[r['status']]}"
              + (f", 이번 {r['received']}행, 누적 {r.get('total', 0)}행, 최신 {r.get('latest') or '없음'}"
                 if r["status"] != "skipped" else "")
              + (f", 실패 구간 {r['failed']}개" if r["failed"] else ""))
    if weather:
        print(f"  기상: {STATUS_LABEL[weather['status']]}"
              + (f", 실패 날짜 {weather['failed']}건" if weather.get("failed") else ""))


def exit_code(results: list[dict], weather: dict | None) -> int:
    statuses = [r["status"] for r in results] + ([weather["status"]] if weather else [])
    if any(s in ("partial", "aborted") for s in statuses):
        return EXIT_PARTIAL
    if any(r["status"] == "empty" and r.get("default") for r in results):
        return EXIT_PARTIAL  # 기본 품종이 0행이면 화면에 쓸 자료가 없다
    if "quota" in statuses:
        return EXIT_QUOTA
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="제주데이터허브 거래 통계·기상 자료 수집")
    ap.add_argument("--years", type=int, default=None)
    ap.add_argument("--item", default=None, help="품목 키 (carrot 등)")
    ap.add_argument("--default-only", action="store_true", help="품목별 기본 품종만 수집")
    ap.add_argument("--no-weather", action="store_true")
    ap.add_argument("--weather-only", action="store_true")
    ap.add_argument("--stats-budget", type=int, default=None, help="거래 통계 하루 누적 호출 한도")
    ap.add_argument("--weather-budget", type=int, default=None, help="기상 하루 누적 호출 한도")
    ap.add_argument("--retry-failed", action="store_true", help="실패한 구간만 다시 받기")
    ap.add_argument("--status", action="store_true", help="허브를 호출하지 않고 수집 상태만 출력")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # 콘솔 인코딩(cp949 등)에 없는 글자 때문에 수집이 죽지 않게 한다
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    if args.no_weather and args.weather_only:
        ap.error("--no-weather 와 --weather-only 는 함께 쓸 수 없습니다.")

    cc = config.collect_config()
    years = args.years or cc.get("years", 2)
    if args.item and args.item not in config.items():
        print(f"! 알 수 없는 품목: {args.item} (사용 가능: {', '.join(config.items())})")
        return EXIT_SETUP
    stats_budget = args.stats_budget if args.stats_budget is not None else cc.get(
        "stats_daily_budget", default_budget("daily_stats"))
    weather_budget = args.weather_budget if args.weather_budget is not None else cc.get(
        "weather_daily_budget", default_budget("weather_daily"))

    store = DataStore()
    today = _today()
    if args.status:
        try:
            status_state = CollectState(store.root, read_only=True)
        except OSError as e:
            print(f"! 상태 파일을 열 수 없습니다: {type(e).__name__}: {e}")
            return EXIT_PARTIAL
        print_status(status_state, today)
        return EXIT_PARTIAL if status_state.recovered else EXIT_OK
    try:
        with collection_lock(store.root):
            return _run_collection(args, store, today, years, stats_budget, weather_budget)
    except CollectorBusy as error:
        print(f"! {error}")
        return EXIT_SETUP
    except OSError:
        print("! 수집 잠금을 준비하지 못했습니다. 캐시 폴더의 쓰기 권한을 확인하세요.")
        return EXIT_SETUP


def _run_collection(args, store, today, years, stats_budget, weather_budget) -> int:
    if (store.root / "SYNTHETIC").exists():
        print("! 합성 데이터 캐시가 있습니다. 실데이터와 섞이지 않도록 data/cache 를 비우고 다시 실행하세요.")
        return EXIT_SETUP
    try:
        hub = HubClient()
    except HubError as e:
        print(f"! {e}")
        return EXIT_SETUP

    try:
        state = CollectState(store.root)
    except OSError as e:  # 잠금 등 일시적 읽기 실패 — 기록을 버리지 않고 멈춘다
        print(f"! 상태 파일을 열 수 없어 멈춥니다: {type(e).__name__}: {e}\n  잠시 뒤 다시 실행하세요. 캐시: {store.root}")
        return EXIT_PARTIAL
    state.prune(today)
    results: list[dict] = []
    weather: dict | None = None
    interrupted = False
    save_error: OSError | None = None
    setup_error = False
    format_error = False
    try:
        if not args.weather_only:
            results = collect_stats(hub, store, args.item, years, today, state=state, budget=stats_budget,
                                    retry_only=args.retry_failed, default_only=args.default_only)
        if not args.no_weather:
            if any(r["status"] == "aborted" for r in results):
                print("[기상] 거래 통계가 연속 실패로 멈춰 기상 수집은 건너뜁니다.")
            else:
                weather = collect_weather(hub, store, years, today, weather_budget, state=state,
                                          retry_only=args.retry_failed)
    except HubError:
        setup_error = True
    except ValueError:
        format_error = True
    except KeyboardInterrupt:
        interrupted = True
    except OSError as e:  # 디스크 가득 참, 다른 프로그램(엑셀 등)이 CSV 를 열어 둠
        save_error = e
    finally:
        try:
            state.save()  # 호출 수 기록은 어떤 경우에도 남긴다
        except OSError as e:
            save_error = save_error or e

    q = state.data["quota"].get(today.isoformat(), {})
    if setup_error:
        print("! 허브 인증이 거부돼 중단했습니다. .env 프로젝트 키와 데이터 이용 권한을 확인하세요.")
        return EXIT_SETUP
    if format_error:
        print("! 캐시 또는 수집 상태 형식이 손상됐습니다. validate_cache.py로 확인하세요. 원본 파일은 삭제하지 않습니다.")
        return EXIT_PARTIAL
    if interrupted:
        print(f"\n! 사용자가 중단했습니다. 받은 자료는 저장됐고 다시 실행하면 이어서 받습니다. 캐시: {store.root}")
        return EXIT_INTERRUPTED
    if save_error is not None:
        print(f"\n! 캐시 파일을 저장하지 못해 멈췄습니다: {type(save_error).__name__}: {save_error}\n"
              f"  CSV 를 열어 둔 프로그램(엑셀 등)을 닫고 디스크 여유 공간을 확인한 뒤 다시 실행하세요. "
              f"그 전까지 저장된 자료는 그대로입니다. 캐시: {store.root}")
        return EXIT_PARTIAL
    _print_summary(results, weather)
    print(f"\n오늘 누적 호출(재시도 포함): 거래 통계 {q.get('daily_stats', 0)}/{stats_budget}건, "
          f"기상 {q.get('weather_daily', 0)}/{weather_budget}건. 캐시: {store.root}")
    code = exit_code(results, weather)
    if code == EXIT_OK and state.recovered:
        print("→ 상태 파일을 새로 만들어 이전 실패 구간 기록이 없습니다. `python scripts/validate_cache.py` 로 날짜 공백을 확인하세요.")
        return EXIT_PARTIAL
    if code == EXIT_PARTIAL:
        print("→ 받지 못한 구간이 있습니다. 위 안내를 확인하고 네트워크가 정상이면 `python scripts/collect.py --retry-failed` 를 실행하세요.")
    elif code == EXIT_QUOTA:
        print("→ 하루 예산을 다 썼습니다. 내일 같은 명령을 다시 실행하면 이어서 받습니다.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
