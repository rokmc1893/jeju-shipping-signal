"""로컬 데이터 저장소.

원칙
- 허브 응답(원본 컬럼명) → 표준 컬럼명(date, cultivar, price, volume, amount, market ...)으로 정규화
- 휴장일 처리: price==0 AND volume==0 → 두 값 모두 NaN (거래 없음 ≠ 가격 0원). 이 규칙이 신호등 오판을 막는다.
- CSV 캐시(데이터셋별 1파일). parquet 의존 없이 센터 PC 에서 동작. 증분 수집은 날짜 기준 upsert.
- 모든 Tool 은 이 모듈의 DataFrame 만 본다 → 인터넷/허브가 끊겨도 같은 질문에 같은 답(재현성).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from . import config

STD_NUMERIC = ("price", "volume", "amount", "temp_avg", "temp_min", "temp_max", "rain", "wind_max", "wind_avg")


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
        df.to_csv(self.path(dataset), index=False, encoding="utf-8")

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
