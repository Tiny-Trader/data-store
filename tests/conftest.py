"""Shared test fixtures for the candles layer."""

from __future__ import annotations

import pandas as pd
import pytest

from catalog.enums import Exchange, InstrumentType, OptionType
from catalog.models import Instrument


@pytest.fixture
def store(settings, tmp_path):
    """Point PARQUET_ROOT at a temp dir for the duration of a test."""
    settings.PARQUET_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def equity() -> Instrument:
    return Instrument(
        instrument_type=InstrumentType.EQUITY, exchange=Exchange.NSE, symbol="RELIANCE"
    )


@pytest.fixture
def option() -> Instrument:
    return Instrument(
        instrument_type=InstrumentType.OPTION,
        exchange=Exchange.NFO,
        symbol="NIFTY",
        expiry=pd.Timestamp("2026-01-29").date(),
        strike=22000,
        option_type=OptionType.CE,
    )


def make_candles(day: str, n: int, *, base: float = 100.0, oi_base: int = 1000) -> pd.DataFrame:
    """Deterministic 1-minute candles from 09:15 IST.

    o=h=l=c = base + i (monotonic), volume = 1, oi = oi_base + i. Monotonicity
    makes resampled open/low the first value and close/high the last, so
    aggregations are easy to assert.
    """
    idx = pd.date_range(f"{day} 09:15", periods=n, freq="1min", tz="Asia/Kolkata")
    prices = [base + i for i in range(n)]
    return pd.DataFrame(
        {
            "ts": idx,
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [1] * n,
            "oi": [oi_base + i for i in range(n)],
        }
    )
