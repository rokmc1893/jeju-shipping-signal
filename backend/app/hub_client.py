"""제주데이터허브 Open API 클라이언트.

- 표준 라이브러리(urllib)만 사용 → 센터 PC 에서 추가 설치 없이 check_api.py 실행 가능
- 응답 구조가 문서와 다를 수 있어 '리스트[dict]' 를 유연하게 찾아낸다
- 범위 조회(startDate/endDate)는 월 단위로 쪼개고, 하루 조회(searchDate)는 날짜별로 호출
- 프로젝트 키는 로그/예외 메시지에서 마스킹
"""
from __future__ import annotations

import http.client
import json
import re
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
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


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
    return url.replace(key, "****") if key else url


def validate_response(response: HubResponse) -> None:
    """거래·기상 공통 검증이다. HTTP 200 오류를 거래 없는 날로 저장하지 않는다."""
    meta = response.meta
    message = " ".join(str(meta.get(k, "")) for k in ("message", "msg", "error"))
    failed = meta.get("success") is False or bool(meta.get("error"))
    for key in ("resultCode", "errorCode", "status", "code", "result"):
        value = meta.get(key)
        if value is not None and str(value).strip().lower() not in ("0", "00", "0000", "200", "ok", "success", "true"):
            failed = True
    if re.search(r"초과|실패|오류|유효하지|인증|권한|quota|exceed|error|fail|unauthori|forbidden|invalid|limit", message, re.I):
        failed = True
    if message.strip() and not response.rows and not meta.get("rows_found") and "data" not in response.raw_keys:
        failed = True
    if failed or (not response.rows and response.total is None and not meta.get("rows_found")):
        # 응답 본문은 키나 URL이 포함될 수 있으므로 오류 종류만 남긴다.
        raise HubError("응답 형식이 예상과 다릅니다: 허브 오류 또는 정상 자료 목록이 없는 응답입니다.")


def _find_rows(payload: Any) -> tuple[list[dict], int | None, dict]:
    """허브 응답에서 데이터 행 리스트와 총 건수를 찾는다. 알려진 키 우선, 없으면 첫 번째 dict 리스트."""
    meta: dict = {}
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)], len(payload), meta
    if not isinstance(payload, dict):
        return [], None, meta
    if payload.get("error"):
        meta["error"] = True  # 구조화된 오류 객체도 정상 빈 목록으로 처리하지 않는다.

    total = None
    for k in ("totCnt", "totalCount", "total", "recordsTotal", "count"):
        if k in payload and isinstance(payload[k], (int, str)):
            try:
                total = int(payload[k])
                break
            except ValueError:
                pass
    for k in ("result", "resultCode", "status", "message", "msg", "hasMore", "success", "error", "errorCode", "code"):
        if k in payload and not isinstance(payload[k], (list, dict)):
            meta[k] = payload[k]

    for k in ("data", "list", "items", "rows", "result", "body"):
        v = payload.get(k)
        if isinstance(v, list):
            meta["rows_found"] = True  # 행 목록 자체는 있었다(비어 있어도 정상 응답)
            return [r for r in v if isinstance(r, dict)], total, meta
        if isinstance(v, dict):
            rows, t2, m2 = _find_rows(v)
            if rows or t2 is not None or m2.get("rows_found"):
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
        self.calls = 0      # 성공한 호출 수
        self.attempts = 0   # 실패·재시도를 포함해 허브로 실제 보낸 요청 수 → 하루 쿼터 계산은 이 값을 쓴다
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
                self.attempts += 1
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
                    raise HubError(f"JSON 파싱 실패 ({_mask(url, self.project_key)})") from e
                rows, total, meta = _find_rows(payload)
                meta = {k: _mask(v, self.project_key) if isinstance(v, str) else v for k, v in meta.items()}
                keys = list(payload.keys()) if isinstance(payload, dict) else ["<list>"]
                if self.sleep_between:
                    time.sleep(self.sleep_between)
                response = HubResponse(rows, total, keys, _mask(url, self.project_key), status, elapsed, meta)
                validate_response(response)
                return response
            except urllib.error.HTTPError as e:
                last_err = HubError(f"HTTP {e.code} ({_mask(url, self.project_key)})", status=e.code)
                if e.code in (400, 401, 403, 404):
                    break  # 재시도 무의미
            except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as e:
                last_err = HubError(f"네트워크 오류 ({_mask(url, self.project_key)}): {type(e).__name__}")
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

    def fetch_window(self, dataset: str, start: date, end: date, **params: Any) -> list[dict]:
        """창 하나만 조회한다. 수집기가 창 단위로 저장·실패 기록·재시도를 하려고 쓴다. 실패하면 HubError."""
        ds = config.datasets()[dataset]
        return self._fetch_window(ds, ds.get("date_format", "%Y%m%d"), start, end, params)

    def _fetch_window(self, ds: dict, fmt: str, s: date, e: date, params: dict) -> list[dict]:
        r = self.call(ds["data_key"], startDate=s.strftime(fmt), endDate=e.strftime(fmt), **params)
        validate_response(r)
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
