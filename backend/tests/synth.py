"""합성 데이터 — 허브 원본 컬럼명 그대로 생성해 normalize() 까지 함께 검증한다.

패턴: 계절성(겨울 고가) + 완만한 추세 + 노이즈, 일요일·공휴일 0/0/0 휴장, 한파 다음 거래일 가격 +12%, 우천 뒤 +4%.
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta

MARKETS = ["가락시장", "강서시장", "구리시장", "대구북부", "제주시도매시장", "광주각화"]
HOLIDAYS = {(1, 1), (3, 1), (5, 5), (6, 6), (8, 15), (10, 3), (10, 9), (12, 25)}


def make_weather(start: date, end: date, station: str = "구좌", seed: int = 1) -> list[dict]:
    rnd = random.Random(seed)
    rows = []
    d = start
    while d <= end:
        doy = d.timetuple().tm_yday
        base = 15 - 10 * math.cos((doy - 20) / 365 * 2 * math.pi)  # 1월 저온
        tmin = base - 4 + rnd.gauss(0, 2.5)
        rain = 0.0 if rnd.random() > 0.22 else rnd.uniform(1, 40)
        rows.append({"observatoryName": station, "baseDate": d.strftime("%Y%m%d"),
                     "averageTemperature": round(base, 1), "lowestTemperature": round(tmin, 1),
                     "highestTemperature": round(base + 5, 1), "dailyRainfall": round(rain, 1),
                     "maximumWindSpeed": 5.0, "averageWindSpeed": 2.0})
        d += timedelta(days=1)
    return rows


def make_stats_and_trades(start: date, end: date, cultivar: str = "당근(일반)", weather: list[dict] | None = None,
                          seed: int = 2, trend_per_year: float = 0.05, level: float = 1800.0) -> tuple[list[dict], list[dict]]:
    rnd = random.Random(seed)
    wmap = {w["baseDate"]: w for w in (weather or [])}
    stats, trades = [], []
    d = start
    prev_cold = False
    prev_rain = False
    while d <= end:
        ds = d.strftime("%Y%m%d")
        closed = d.weekday() == 6 or (d.month, d.day) in HOLIDAYS
        if closed:
            stats.append({"baseDate": ds, "cultivar": cultivar, "averagePrice": "0.00",
                          "transactionVolume": "0.00", "transactionAmount": "0.00"})
            d += timedelta(days=1)
            continue
        years = (d - start).days / 365
        doy = d.timetuple().tm_yday
        season = 1 + 0.25 * math.cos((doy - 15) / 365 * 2 * math.pi)  # 1월 중순 피크
        price = level * season * (1 + trend_per_year * years) * (1 + rnd.gauss(0, 0.04))
        if prev_cold:
            price *= 1.12
        elif prev_rain:
            price *= 1.04
        vol = max(5.0, 120 * (2 - season) * (1 + rnd.gauss(0, 0.2)))
        stats.append({"baseDate": ds, "cultivar": cultivar, "averagePrice": f"{price:.2f}",
                      "transactionVolume": f"{vol:.2f}", "transactionAmount": f"{price * vol / 1000:.2f}"})
        for m in MARKETS:
            share = {"가락시장": 0.45, "강서시장": 0.15, "구리시장": 0.1, "대구북부": 0.1, "제주시도매시장": 0.1, "광주각화": 0.1}[m]
            adj = {"가락시장": 1.05, "강서시장": 1.0, "구리시장": 0.97, "대구북부": 0.95, "제주시도매시장": 0.9, "광주각화": 0.94}[m]
            mp = price * adj * (1 + rnd.gauss(0, 0.02))
            mv = vol * share
            trades.append({"baseDate": ds, "cultivar": cultivar, "wholesaleMarket": m, "corporation": "합동청과",
                           "wholesalePrice": f"{mp:.2f}", "transactionVolume": f"{mv:.2f}",
                           "transactionAmount": f"{mp * mv / 1000:.2f}"})
        w = wmap.get(ds)
        prev_cold = bool(w and w["lowestTemperature"] <= 0)
        prev_rain = bool(w and w["dailyRainfall"] >= 10)
        d += timedelta(days=1)
    return stats, trades
