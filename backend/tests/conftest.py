import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.data_store import DataStore, normalize  # noqa: E402
import synth  # noqa: E402

START, END = date(2024, 11, 1), date(2026, 11, 7)  # 2026-11-07 토요일(거래일), 11-08 일요일(휴장)


@pytest.fixture(scope="session")
def store(tmp_path_factory):
    root = tmp_path_factory.mktemp("cache")
    s = DataStore(root)
    weather = synth.make_weather(START, END, "구좌")
    stats, trades = synth.make_stats_and_trades(START, END, "당근(일반)", weather)
    s.upsert("daily_stats", normalize(stats, "daily_stats"), ["date", "cultivar"])
    s.upsert("daily_trades", normalize(trades, "daily_trades"), ["date", "cultivar", "market", "corporation"])
    s.upsert("weather_daily", normalize(weather, "weather_daily"), ["date", "station"])
    return s
