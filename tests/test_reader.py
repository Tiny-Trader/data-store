"""Read path: DuckDB resampling correctness and session alignment."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from candles import reader, storage
from candles.intervals import Interval
from tests.conftest import make_candles

IST = ZoneInfo("Asia/Kolkata")


def _day_bounds(day: str) -> tuple[datetime, datetime]:
    start = datetime.fromisoformat(f"{day} 00:00").replace(tzinfo=IST)
    return start, start + timedelta(days=1)


def _read(instrument, interval, day="2024-06-03"):
    start, end = _day_bounds(day)
    df = reader.read(instrument, interval, start, end)
    df = df.copy()
    df["ts"] = pd.to_datetime(df["ts"]).dt.tz_convert("Asia/Kolkata")
    return df


def test_raw_minute_passthrough(store, equity):
    storage.write(equity, make_candles("2024-06-03", 30))
    out = _read(equity, Interval.MINUTE_1)
    assert len(out) == 30
    assert out.iloc[0]["open"] == 100.0
    assert out.iloc[-1]["close"] == 129.0


def test_resample_5minute(store, equity):
    storage.write(equity, make_candles("2024-06-03", 30))
    out = _read(equity, Interval.MINUTE_5)
    assert len(out) == 6
    first = out.iloc[0]
    assert first["ts"].strftime("%H:%M") == "09:15"
    assert first["open"] == 100.0   # first minute
    assert first["high"] == 104.0   # max over bucket
    assert first["low"] == 100.0    # min over bucket
    assert first["close"] == 104.0  # last minute
    assert first["volume"] == 5
    assert first["oi"] == 1004      # last value in bucket, not sum


def test_resample_15minute(store, equity):
    storage.write(equity, make_candles("2024-06-03", 30))
    out = _read(equity, Interval.MINUTE_15)
    assert len(out) == 2
    assert out.iloc[0]["ts"].strftime("%H:%M") == "09:15"
    assert out.iloc[1]["ts"].strftime("%H:%M") == "09:30"
    assert out.iloc[1]["close"] == 129.0
    assert out.iloc[1]["volume"] == 15


def test_resample_30minute_is_session_aligned(store, equity):
    # 30 one-minute candles from 09:15 collapse to a single 09:15 bucket only if
    # the origin is anchored to session open (not clock-hour boundaries).
    storage.write(equity, make_candles("2024-06-03", 30))
    out = _read(equity, Interval.MINUTE_30)
    assert len(out) == 1
    assert out.iloc[0]["ts"].strftime("%H:%M") == "09:15"
    assert out.iloc[0]["open"] == 100.0
    assert out.iloc[0]["close"] == 129.0
    assert out.iloc[0]["volume"] == 30


def test_resample_day(store, equity):
    storage.write(equity, make_candles("2024-06-03", 30))
    out = _read(equity, Interval.DAY)
    assert len(out) == 1
    assert out.iloc[0]["open"] == 100.0
    assert out.iloc[0]["close"] == 129.0
    assert out.iloc[0]["volume"] == 30
    assert out.iloc[0]["oi"] == 1029


def test_read_missing_returns_empty(store, equity):
    out = reader.read(equity, Interval.MINUTE_5, *_day_bounds("2024-06-03"))
    assert out.empty
