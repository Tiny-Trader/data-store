"""Path resolver layout and formatting."""

from __future__ import annotations

from datetime import date

import pytest

from candles import paths
from catalog.enums import Exchange, InstrumentType, OptionType
from catalog.models import Instrument


def test_equity_year_file(store, equity):
    p = paths.file_for_year(equity, 2024)
    assert p == store / "candles" / "1minute" / "equity" / "NSE" / "RELIANCE" / "2024.parquet"
    assert paths.is_year_partitioned(equity)


def test_index_year_file(store):
    idx = Instrument(instrument_type=InstrumentType.INDEX, exchange=Exchange.NSE, symbol="NIFTY")
    p = paths.file_for_year(idx, 2025)
    assert p == store / "candles" / "1minute" / "index" / "NSE" / "NIFTY" / "2025.parquet"


def test_future_contract_file(store):
    fut = Instrument(
        instrument_type=InstrumentType.FUTURE,
        exchange=Exchange.NFO,
        symbol="NIFTY",
        expiry=date(2026, 1, 29),
    )
    p = paths.contract_file(fut)
    assert p == store / "candles" / "1minute" / "futures" / "NIFTY" / "2026-01-29.parquet"
    assert not paths.is_year_partitioned(fut)


def test_option_contract_file(store, option):
    expected = store.joinpath(
        "candles", "1minute", "options", "NIFTY", "2026-01-29", "22000_CE.parquet"
    )
    assert paths.contract_file(option) == expected


def test_option_strike_trailing_zeros(store):
    opt = Instrument(
        instrument_type=InstrumentType.OPTION,
        exchange=Exchange.NFO,
        symbol="BANKNIFTY",
        expiry=date(2026, 1, 29),
        strike=22500.50,
        option_type=OptionType.PE,
    )
    assert paths.contract_file(opt).name == "22500.5_PE.parquet"


def test_unsupported_type_raises(store):
    cur = Instrument(
        instrument_type=InstrumentType.CURRENCY, exchange=Exchange.CDS, symbol="USDINR"
    )
    with pytest.raises(ValueError):
        paths.entity_dir(cur)
