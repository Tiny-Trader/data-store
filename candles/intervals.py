"""Canonical candle intervals, mirrored from tt-connect.

Values match ``tt_connect.core.models.enums.CandleInterval`` exactly. We store
only the base interval (1-minute) on disk and derive the rest on read, so each
non-base interval maps to a DuckDB ``time_bucket`` width.
"""

from __future__ import annotations

from enum import StrEnum


class Interval(StrEnum):
    MINUTE_1 = "1minute"
    MINUTE_3 = "3minute"
    MINUTE_5 = "5minute"
    MINUTE_10 = "10minute"
    MINUTE_15 = "15minute"
    MINUTE_30 = "30minute"
    HOUR_1 = "60minute"
    DAY = "day"


#: The only interval persisted to Parquet. Everything else is derived on read.
STORED = Interval.MINUTE_1

#: Intraday intervals -> DuckDB INTERVAL literal used by ``time_bucket``.
_BUCKET_WIDTH: dict[Interval, str] = {
    Interval.MINUTE_3: "3 minutes",
    Interval.MINUTE_5: "5 minutes",
    Interval.MINUTE_10: "10 minutes",
    Interval.MINUTE_15: "15 minutes",
    Interval.MINUTE_30: "30 minutes",
    Interval.HOUR_1: "1 hour",
}


def bucket_width(interval: Interval) -> str:
    """Return the DuckDB INTERVAL width for an intraday derived interval.

    Raises:
        ValueError: for the base interval or ``DAY`` (handled separately).
    """
    try:
        return _BUCKET_WIDTH[interval]
    except KeyError:
        raise ValueError(f"{interval} has no intraday bucket width") from None
