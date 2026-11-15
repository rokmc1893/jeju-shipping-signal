"""제주데이터허브 Open API 클라이언트.

- 표준 라이브러리(urllib)만 사용 → 센터 PC 에서 추가 설치 없이 check_api.py 실행 가능
- 응답 구조가 문서와 다를 수 있어 '리스트[dict]' 를 유연하게 찾아낸다
- 범위 조회(startDate/endDate)는 월 단위로 쪼개고, 하루 조회(searchDate)는 날짜별로 호출
- 프로젝트 키는 로그/예외 메시지에서 마스킹
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Iterable

from . import config

USER_AGENT = "JejuShippingSignal/0.1 (hackathon; local-agent)"


class HubError(RuntimeError):
    pass


@dataclass
class HubResponse:
    rows: list[dict]
    total: int | None
    raw_keys: list[str]
    url: str  # 키 마스킹된 URL
    status: int
    elapsed_ms: int
    meta: dict = field(default_factory=dict)


def _mask(url: str, key: str) -> str:
    return url.replace(key, key[:4] + "****" + key[-2:]) if key and len(key) > 8 else url


def _find_rows(payload: Any) -> tuple[list[dict], int | None, dict]:
    """허브 응답에서 데이터 행 리스트와 총 건수를 찾는다. 알려진 키 우선, 없으면 첫 번째 dict 리스트."""
    meta: dict = {}
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)], len(payload), meta
    if not isinstance(payload, dict):
        return [], None, meta

    total = None
    for k in ("totCnt", "totalCount", "total", "recordsTotal", "count"):
        if k in payload and isinstance(payload[k], (int, str)):
            try:
                total = int(payload[k])
                break
            except ValueError:
                pass
    for k in ("result", "resultCode", "status", "message", "msg", "hasMore"):
        if k in payload and not isinstance(payload[k], (list, dict)):
            meta[k] = payload[k]

    for k in ("data", "list", "items", "rows", "result", "body"):
        v = payload.get(k)
        if isinstance(v, list):
            return [r for r in v if isinstance(r, dict)], total, meta
        if isinstance(v, dict):
            rows, t2, m2 = _find_rows(v)
            if rows or t2 is not None:
                meta.update(m2)
                return rows, total if total is not None else t2, meta
    for v in payload.values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v, total, meta
    return [], total, meta


class HubClient:
    def __init__(self, project_key: str | None = None, base_url: str | None = None,
                 timeout: float = 12.0, retries: int = 4, sleep_between: float = 1.2, verbose: bool = True):
        self.project_key = project_key or config.env("JEJU_HUB_PROJECT_KEY")
        self.base_url = (base_url or config.env("JEJU_HUB_BASE_URL",
                                                  "https://open.jejudatahub.net/api/proxy")).rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.sleep_between = sleep_between
        self.calls = 0
        self.verbose = verbose
        if not self.project_key:
            raise HubError("JEJU_HUB_PROJECT_KEY 가 비어 있습니다. .env 를 확인하세요.")

    # ---- low level -------------------------------------------------------
    def build_url(self, data_key: str, params: dict[str, Any]) -> str:
        clean = {k: v for k, v in params.items() if v not in (None, "")}
        qs = urllib.parse.urlencode(clean, encoding="utf-8")
        return f"{self.base_url}/{data_key}/{self.project_key}" + (f"?{qs}" if qs else "")

    def call(self, data_key: str, **params: Any) -> HubResponse:
        url = self.build_url(data_key, params)
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            t0 = time.time()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    status = resp.status
                    body = resp.read().decode("utf-8", errors="replace")
                self.calls += 1
                elapsed = int((time.time() - t0) * 1000)
                if self.verbose:
                    print(".", end="", flush=True)
                try:
                    payload = json.loads(body) if body.strip() else {}
                except json.JSONDecodeError as e:
                    raise HubError(f"JSON 파싱 실패 ({_mask(url, self.project_key)}): {body[:200]}") from e
                rows, total, meta = _find_rows(payload)
                keys = list(payload.keys()) if isinstance(payload, dict) else ["<list>"]
                if self.sleep_between:
                    time.sleep(self.sleep_between)
                return HubResponse(rows, total, keys, _mask(url, self.project_key), status, elapsed, meta)
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", errors="replace")[:300] if e.fp else ""
                last_err = HubError(f"HTTP {e.code} ({_mask(url, self.project_key)}) {detail}")
                if e.code in (400, 401, 403, 404):
                    break  # 재시도 무의미
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = HubError(f"네트워크 오류 ({_mask(url, self.project_key)}): {e}")
                if self.verbose:
                    print("x", end="", flush=True)
            time.sleep(1.5 * (attempt + 1))
        raise last_err or HubError("알 수 없는 오류")

    # ---- dataset helpers --------------------------------------------------
    # 2026-11-15 실호출로 확인된 허브 Open API 특성:
    #  - 응답은 {totCnt, hasMore, data[]} 이며 한 번에 최대 10행. page/offset 등 페이징 파라미터는 전부 무시됨.
    #  - 일요일·공휴일 행은 아예 없음(0/0/0 행 없음) → 10일 창이면 거래일 ≤ 9 → 10행 한도 안에 들어옴.
    #  - 연속 호출 시 간헐적 실패(초당 1회 수준 제한으로 보임) → 호출 간격 1.2s + 재시도.
    PAGE_LIMIT = 10
    DEFAULT_WINDOW_DAYS = 10

    @staticmethod
    def day_chunks(start: date, end: date, days: int) -> Iterable[tuple[date, date]]:
        cur = start
        while cur <= end:
            nxt = min(cur + timedelta(days=days - 1), end)
            yield cur, nxt
            cur = nxt + timedelta(days=1)

    def fetch_range(self, dataset: str, start: date, end: date, window_days: int | None = None,
                    **params: Any) -> list[dict]:
        """범위 조회. 창을 작게 잘라 10행 한도를 피하고, 그래도 hasMore 면 창을 반으로 쪼개 재호출."""
        ds = config.datasets()[dataset]
        fmt = ds.get("date_format", "%Y%m%d")
        rows: list[dict] = []
        for s, e in self.day_chunks(start, end, window_days or self.DEFAULT_WINDOW_DAYS):
            rows.extend(self._fetch_window(ds, fmt, s, e, params))
        return rows

    def _fetch_window(self, ds: dict, fmt: str, s: date, e: date, params: dict) -> list[dict]:
        r = self.call(ds["data_key"], startDate=s.strftime(fmt), endDate=e.strftime(fmt), **params)
        truncated = r.meta.get("hasMore") is True or (r.total is not None and r.total > len(r.rows))
        if truncated and s < e:
            mid = s + (e - s) // 2
            return self._fetch_window(ds, fmt, s, mid, params) + self._fetch_window(ds, fmt, mid + timedelta(days=1), e, params)
        if truncated:
            r.meta["truncated_single_day"] = True  # 하루에 10행 초과(거래 정보 1362) → 표본만 확보됨
        return r.rows

    def fetch_days(self, dataset: str, start: date, end: date, **params: Any) -> list[dict]:
        ds = config.datasets()[dataset]
        fmt = ds.get("date_format", "%Y%m%d")
        rows: list[dict] = []
        d = start
        while d <= end:
            r = self.call(ds["data_key"], searchDate=d.strftime(fmt), **params)
            rows.extend(r.rows)
            d += timedelta(days=1)
        return rows

    def fetch_static(self, dataset: str, **params: Any) -> list[dict]:
        ds = config.datasets()[dataset]
        return self.call(ds["data_key"], **params).rows
