"""Write path: append idempotency, dedupe, year partitioning, validation."""

from __future__ import annotations

import pandas as pd
import pytest

from candles import paths, storage
from candles.schema import CandleValidationError
from tests.conftest import make_candles


def test_write_creates_file_and_reads_back(store, equity):
    written = storage.write(equity, make_candles("2024-06-03", 30))
    assert written == 30
    assert paths.file_for_year(equity, 2024).exists()
    assert len(storage.read_raw(equity, 2024, 2024)) == 30


def test_append_is_idempotent(store, equity):
    df = make_candles("2024-06-03", 30)
    storage.write(equity, df)
    storage.write(equity, df)  # same range again
    assert len(storage.read_raw(equity, 2024, 2024)) == 30


def test_dedupe_last_write_wins(store, equity):
    storage.write(equity, make_candles("2024-06-03", 5))
    updated = make_candles("2024-06-03", 5)
    updated.loc[updated.index[-1], "close"] = 999.0
    updated.loc[updated.index[-1], "high"] = 999.0
    storage.write(equity, updated)

    out = storage.read_raw(equity, 2024, 2024)
    assert len(out) == 5
    assert out.iloc[-1]["close"] == 999.0


def test_year_partitioning_splits_files(store, equity):
    # 09:15 for the last minute of 2024 and first minute of 2025.
    ts = pd.to_datetime(
        ["2024-12-31 09:15", "2025-01-01 09:15"]
    ).tz_localize("Asia/Kolkata")
    df = pd.DataFrame(
        {
            "ts": ts,
            "open": [100.0, 101.0],
            "high": [100.0, 101.0],
            "low": [100.0, 101.0],
            "close": [100.0, 101.0],
            "volume": [1, 1],
            "oi": [10, 11],
        }
    )
    storage.write(equity, df)
    assert paths.file_for_year(equity, 2024).exists()
    assert paths.file_for_year(equity, 2025).exists()
    assert len(storage.read_raw(equity, 2024, 2024)) == 1
    assert len(storage.read_raw(equity, 2025, 2025)) == 1


def test_write_to_option_contract_file(store, option):
    storage.write(option, make_candles("2026-01-20", 10))
    assert paths.contract_file(option).exists()


def test_invalid_ohlc_rejected(store, equity):
    bad = make_candles("2024-06-03", 3)
    bad.loc[0, "low"] = 10_000.0  # low > high
    with pytest.raises(CandleValidationError):
        storage.write(equity, bad)


def test_naive_timestamps_rejected(store, equity):
    naive = make_candles("2024-06-03", 3)
    naive["ts"] = naive["ts"].dt.tz_localize(None)
    with pytest.raises(CandleValidationError):
        storage.write(equity, naive)
