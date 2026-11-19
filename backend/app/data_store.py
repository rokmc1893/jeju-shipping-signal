"""로컬 데이터 저장소.

원칙
- 허브 응답(원본 컬럼명) → 표준 컬럼명(date, cultivar, price, volume, amount, market ...)으로 정규화
- 휴장일 처리: price==0 AND volume==0 → 두 값 모두 NaN (거래 없음 ≠ 가격 0원). 이 규칙이 신호등 오판을 막는다.
- CSV 캐시(데이터셋별 1파일). parquet 의존 없이 센터 PC 에서 동작. 증분 수집은 날짜 기준 upsert.
- 모든 Tool 은 이 모듈의 DataFrame 만 본다 → 인터넷/허브가 끊겨도 같은 질문에 같은 답(재현성).
- 저장은 같은 폴더의 임시 파일에 모두 쓴 뒤 os.replace 로 교체한다 → 쓰는 도중 중단돼도 기존 CSV 가 깨지지 않는다.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import IO, Callable

import numpy as np
import pandas as pd

from . import config

STD_NUMERIC = ("price", "volume", "amount", "temp_avg", "temp_min", "temp_max", "rain", "wind_max", "wind_avg")

TMP_SUFFIX = ".tmp"
REPLACE_ATTEMPTS = 5
REPLACE_DELAY = 0.2


def _replace(tmp: Path, dest: Path) -> None:
    """os.replace 로 교체한다. Windows 는 다른 프로그램이 대상 파일을 잠깐 열고 있으면 PermissionError 를 내므로 몇 번 재시도한다."""
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(tmp, dest)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_DELAY * (attempt + 1))


def atomic_write(dest: Path, writer: Callable[[IO[str]], None]) -> None:
    """dest 를 통째로 안전하게 교체한다.

    같은 폴더의 임시 파일에 쓰고 디스크까지 내려보낸 뒤(fsync) 교체한다. 쓰기·교체 중 어떤 예외가 나도
    기존 dest 는 그대로 남고 임시 파일은 지운다. 강제 종료로 남은 임시 파일(.이름.*.tmp)은 조회에 쓰이지 않는다.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=TMP_SUFFIX, dir=dest.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            writer(f)
            f.flush()
            os.fsync(f.fileno())
        try:  # mkstemp 는 0600 으로 만든다 → 기존 파일 권한(없으면 일반 파일 기본값)에 맞춘다
            os.chmod(tmp, (dest.stat().st_mode & 0o777) if dest.exists() else 0o644)
        except OSError:
            pass
        _replace(tmp, dest)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    try:  # 폴더 항목까지 디스크에 기록(POSIX). Windows 는 폴더를 열 수 없어 건너뛴다.
        dir_fd = os.open(dest.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def atomic_write_text(dest: Path, text: str) -> None:
    atomic_write(dest, lambda f: f.write(text))


def normalize(rows: list[dict], dataset: str) -> pd.DataFrame:
    """허브 원본 행 → 표준 DataFrame."""
    ds = config.datasets()[dataset]
    mapping: dict = ds.get("response", {})
    inv = {src: std for std, src in mapping.items()}
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=list(mapping.keys()))
    df = df.rename(columns={c: inv[c.strip()] for c in df.columns if c.strip() in inv})
    keep = [c for c in mapping.keys() if c in df.columns]
    df = df[keep].copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"].astype(str).str.strip().str.replace("-", ""), format="%Y%m%d",
                                    errors="coerce").dt.date
        df = df.dropna(subset=["date"])
    for c in STD_NUMERIC:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ("cultivar", "market", "corporation", "station"):
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()
    return apply_closed_day_rule(df)


def apply_closed_day_rule(df: pd.DataFrame) -> pd.DataFrame:
    """휴장일(가격 0 & 거래량 0) → NaN. 가격만 0 이거나 거래량만 0 인 행은 이상치로 두되 가격 0 은 NaN."""
    if "price" in df.columns and "volume" in df.columns:
        closed = (df["price"].fillna(0) == 0) & (df["volume"].fillna(0) == 0)
        df.loc[closed, ["price", "volume"]] = np.nan
        if "amount" in df.columns:
            df.loc[closed, "amount"] = np.nan
        df["closed"] = closed
        df.loc[df["price"] == 0, "price"] = np.nan  # 가격 0 은 어떤 경우에도 가격이 아님
    return df


@dataclass
class DataStore:
    root: Path

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else config.data_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    def collection_incomplete(self, cultivar: str) -> bool:
        """기록이 있으면 해당 품종의 수집 완료 여부를 확인한다."""
        try:
            state = json.loads((self.root / "collect_state.json").read_text(encoding="utf-8"))
            if state.get("version") != 1:
                return True
            entry = state["stats"].get(cultivar)
            return entry is not None and (entry.get("status") != "ok" or entry.get("failed") != [])
        except FileNotFoundError:
            return False  # 상태 파일 도입 전의 캐시와 시연용 자료는 기록이 없다.
        except (OSError, ValueError, KeyError, AttributeError, TypeError):
            return True

    def path(self, dataset: str) -> Path:
        return self.root / f"{dataset}.csv"

    def load(self, dataset: str) -> pd.DataFrame:
        p = self.path(dataset)
        if not p.exists():
            return pd.DataFrame()
        df = pd.read_csv(p, encoding="utf-8")
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.date
        if "closed" in df.columns:
            df["closed"] = df["closed"].astype(bool)
        return df

    def save(self, dataset: str, df: pd.DataFrame) -> None:
        """CSV 를 원자적으로 교체한다. 실패하면 기존 파일이 그대로 남는다."""
        atomic_write(self.path(dataset), lambda f: df.to_csv(f, index=False))

    def upsert(self, dataset: str, new: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
        """키 기준 upsert (새 행이 우선)."""
        old = self.load(dataset)
        if old.empty:
            merged = new.copy()
        else:
            merged = pd.concat([old, new], ignore_index=True)
            merged = merged.drop_duplicates(subset=keys, keep="last")
        if "date" in merged.columns:
            merged = merged.sort_values(["date"] + [k for k in keys if k != "date"]).reset_index(drop=True)
        self.save(dataset, merged)
        return merged

    # ---- 조회 헬퍼 ----------------------------------------------------------
    def stats(self, cultivar: str | None = None) -> pd.DataFrame:
        df = self.load("daily_stats")
        if df.empty:
            return df
        if cultivar:
            df = df[df["cultivar"] == cultivar]
        return df.sort_values("date").reset_index(drop=True)

    def trades(self, cultivar: str | None = None) -> pd.DataFrame:
        df = self.load("daily_trades")
        if df.empty:
            return df
        if cultivar:
            df = df[df["cultivar"] == cultivar]
        return df.sort_values("date").reset_index(drop=True)

    def weather(self, station: str | None = None) -> pd.DataFrame:
        df = self.load("weather_daily")
        if df.empty:
            return df
        if station:
            df = df[df["station"] == station]
        return df.sort_values("date").reset_index(drop=True)

    def last_date(self, dataset: str) -> date | None:
        df = self.load(dataset)
        if df.empty or "date" not in df.columns:
            return None
        return max(df["date"])

    def incremental_window(self, dataset: str, default_years: int = 2, overlap_days: int = 7,
                           today: date | None = None) -> tuple[date, date]:
        """증분 수집 구간: 마지막 적재일 - overlap ~ 오늘. 비어 있으면 default_years 전부터."""
        today = today or date.today()
        last = self.last_date(dataset)
        start = (last - timedelta(days=overlap_days)) if last else today.replace(year=today.year - default_years)
        return start, today
