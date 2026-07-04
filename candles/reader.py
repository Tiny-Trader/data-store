"""Read path for Parquet candles, powered by DuckDB.

Stored data is 1-minute only; coarser intervals are derived here via DuckDB
``time_bucket`` aggregation with predicate pushdown over the Parquet files.

Session alignment: Indian equity/F&O sessions open at 09:15 IST. Intraday
buckets are anchored to a 09:15 origin so 30-/60-minute candles line up with the
session open (matching broker conventions) rather than clock-hour boundaries.
Volume is summed (a flow); OHLC use the first/last by ``ts``; OI takes the last
value in the bucket (a level, not a flow).
"""

from __future__ import annotations

from datetime import datetime

import duckdb
import pandas as pd

from candles import paths
from candles.intervals import Interval, bucket_width
from candles.schema import COLUMNS, IST
from catalog.models import Instrument

# 09:15 IST origin for time_bucket alignment (India has no DST, fixed +05:30).
_SESSION_ORIGIN = "TIMESTAMPTZ '1970-01-01 09:15:00+05:30'"


def _aggregate_select(interval: Interval) -> str:
    """Build the SELECT that derives ``interval`` from 1-minute rows."""
    if interval is Interval.DAY:
        bucket = "date_trunc('day', ts)"
    else:
        bucket = f"time_bucket(INTERVAL '{bucket_width(interval)}', ts, {_SESSION_ORIGIN})"
    return (
        f"SELECT {bucket} AS ts, "
        "arg_min(open, ts) AS open, max(high) AS high, min(low) AS low, "
        "arg_max(close, ts) AS close, sum(volume) AS volume, arg_max(oi, ts) AS oi "
        "FROM read_parquet($files) "
        "WHERE ts >= $start AND ts < $end "
        "GROUP BY 1 ORDER BY 1"
    )


def _raw_select() -> str:
    return (
        "SELECT ts, open, high, low, close, volume, oi "
        "FROM read_parquet($files) "
        "WHERE ts >= $start AND ts < $end ORDER BY ts"
    )


def read(
    instrument: Instrument,
    interval: Interval,
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    """Return candles for ``instrument`` in ``[start, end)`` at ``interval``.

    ``start``/``end`` must be timezone-aware. Missing files are skipped; if none
    exist an empty (correctly-typed) frame is returned.
    """
    files = [
        str(p)
        for p in paths.files_for_range(instrument, start.year, end.year)
        if p.exists()
    ]
    if not files:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in COLUMNS})

    sql = _raw_select() if interval is Interval.MINUTE_1 else _aggregate_select(interval)

    con = duckdb.connect()
    try:
        con.execute(f"SET TimeZone='{IST}'")
        return con.execute(sql, {"files": files, "start": start, "end": end}).fetch_df()
    finally:
        con.close()
