"""Write path for Parquet candles: atomic, idempotent append.

Appends are read-modify-write per file. New rows are merged with existing rows,
deduplicated on ``ts`` (last write wins), sorted, then written to a temp file and
atomically swapped into place. Re-running a sync over the same range is a no-op.

This module is intentionally broker-agnostic: it takes plain candle rows, not
tt-connect models. Ingestion bridges tt-connect ``Candle`` objects to this layer.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pandas as pd

from candles import paths, schema
from catalog.models import Instrument


def _atomic_write(df: pd.DataFrame, path: Path) -> None:
    """Write ``df`` to ``path`` via a temp file + atomic replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        df.to_parquet(tmp, engine="pyarrow", index=False)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _merge_write(path: Path, new_df: pd.DataFrame) -> None:
    """Merge ``new_df`` into the file at ``path`` (dedupe on ts, last wins)."""
    if path.exists():
        existing = schema.normalize(pd.read_parquet(path, engine="pyarrow"))
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset="ts", keep="last")
        combined = combined.sort_values("ts", ignore_index=True)
    else:
        combined = new_df
    schema.validate(combined)
    _atomic_write(combined, path)


def write(instrument: Instrument, frame: pd.DataFrame) -> int:
    """Persist candles for an instrument, appending idempotently.

    ``frame`` must carry the canonical columns (see :data:`candles.schema.COLUMNS`)
    with a tz-aware ``ts``. Equity/index rows are split into per-year files;
    F&O rows go to the single contract file. Returns the number of rows written.
    """
    df = schema.normalize(frame)
    schema.validate(df)
    if df.empty:
        return 0

    if paths.is_year_partitioned(instrument):
        for year, part in df.groupby(df["ts"].dt.year):
            _merge_write(paths.file_for_year(instrument, int(year)), part.reset_index(drop=True))
    else:
        _merge_write(paths.contract_file(instrument), df)

    return len(df)


def has_day(instrument: Instrument, day: date) -> bool:
    """True if any candle for ``day`` is already stored.

    Used as the resumable-run completion check: writes are atomic per file, so a
    present day is a complete day and can be safely skipped on re-run.
    """
    if paths.is_year_partitioned(instrument):
        path = paths.file_for_year(instrument, day.year)
    else:
        path = paths.contract_file(instrument)
    if not path.exists():
        return False
    ts = pd.read_parquet(path, engine="pyarrow", columns=["ts"])["ts"]
    if ts.empty:
        return False
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize(schema.IST)
    else:
        ts = ts.dt.tz_convert(schema.IST)
    return bool((ts.dt.date == day).any())


def read_raw(instrument: Instrument, start_year: int, end_year: int) -> pd.DataFrame:
    """Read stored 1-minute candles across a year range (no resampling).

    Intended for inspection and the write path. Serving reads should go through
    :mod:`candles.reader`, which pushes filtering and resampling into DuckDB.
    """
    parts = [
        schema.normalize(pd.read_parquet(p, engine="pyarrow"))
        for p in paths.files_for_range(instrument, start_year, end_year)
        if p.exists()
    ]
    if not parts:
        return schema.normalize(pd.DataFrame(columns=schema.COLUMNS))
    out = pd.concat(parts, ignore_index=True)
    return out.sort_values("ts", ignore_index=True)
