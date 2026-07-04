"""On-disk layout for Parquet candle files.

One root, one resolver. Identity is encoded in the path (files stay pure OHLCV).
Layout is keyed by instrument lifetime:

    candles/{stored_interval}/equity/{exchange}/{symbol}/{year}.parquet
    candles/{stored_interval}/index/{exchange}/{symbol}/{year}.parquet
    candles/{stored_interval}/futures/{underlying}/{expiry}.parquet
    candles/{stored_interval}/options/{underlying}/{expiry}/{strike}_{CE|PE}.parquet

Long-lived instruments (equity/index) partition by year; short-lived F&O
contracts get one file for their whole life.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from django.conf import settings

from candles.intervals import STORED
from catalog.enums import InstrumentType
from catalog.models import Instrument

_YEAR_PARTITIONED = {InstrumentType.EQUITY, InstrumentType.INDEX}
_TYPE_DIR = {
    InstrumentType.EQUITY: "equity",
    InstrumentType.INDEX: "index",
    InstrumentType.FUTURE: "futures",
    InstrumentType.OPTION: "options",
}


def candles_root() -> Path:
    """Root directory for stored (1-minute) candle files."""
    return Path(settings.PARQUET_ROOT) / "candles" / STORED.value


def _safe(component: str) -> str:
    """Make a single path component filesystem-safe."""
    return component.replace("/", "_").replace("\\", "_").strip()


def _fmt_strike(strike: Decimal | float | int) -> str:
    """Format a strike without trailing zeros (e.g. 22000, 22500.5)."""
    return format(Decimal(str(strike)).normalize(), "f")


def is_year_partitioned(instrument: Instrument) -> bool:
    """Whether this instrument's candles are split into per-year files."""
    return instrument.instrument_type in _YEAR_PARTITIONED


def _underlying_symbol(instrument: Instrument) -> str:
    """Symbol used to group F&O contracts (falls back to the instrument's own)."""
    if instrument.underlying_id is not None and instrument.underlying is not None:
        return instrument.underlying.symbol
    return instrument.symbol


def entity_dir(instrument: Instrument) -> Path:
    """Directory holding this instrument's candle file(s)."""
    root = candles_root()
    itype = instrument.instrument_type
    type_dir = _TYPE_DIR.get(InstrumentType(itype))
    if type_dir is None:
        raise ValueError(f"unsupported instrument_type for candle storage: {itype}")

    if itype in _YEAR_PARTITIONED:
        return root / type_dir / _safe(instrument.exchange) / _safe(instrument.symbol)
    if itype == InstrumentType.FUTURE:
        return root / type_dir / _safe(_underlying_symbol(instrument))
    # OPTION
    return root / type_dir / _safe(_underlying_symbol(instrument)) / instrument.expiry.isoformat()


def file_for_year(instrument: Instrument, year: int) -> Path:
    """Year-partitioned file path (equity/index only)."""
    if not is_year_partitioned(instrument):
        raise ValueError("file_for_year is only valid for equity/index instruments")
    return entity_dir(instrument) / f"{year}.parquet"


def contract_file(instrument: Instrument) -> Path:
    """Single per-contract file path (futures/options)."""
    itype = instrument.instrument_type
    if itype == InstrumentType.FUTURE:
        return entity_dir(instrument) / f"{instrument.expiry.isoformat()}.parquet"
    if itype == InstrumentType.OPTION:
        name = f"{_fmt_strike(instrument.strike)}_{instrument.option_type}.parquet"
        return entity_dir(instrument) / name
    raise ValueError("contract_file is only valid for futures/options instruments")


def files_for_range(instrument: Instrument, start_year: int, end_year: int) -> list[Path]:
    """Candidate files covering a year range (existing or not)."""
    if is_year_partitioned(instrument):
        return [file_for_year(instrument, y) for y in range(start_year, end_year + 1)]
    return [contract_file(instrument)]
