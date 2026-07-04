"""Canonical candle frame schema, normalization, and validation.

Columns align with tt-connect's ``Candle`` model (lower snake_case): a tz-aware
``ts`` plus OHLCV and optional ``oi`` (open interest, F&O only). Timestamps are
stored in IST (``Asia/Kolkata``); ``ts`` is the sort key and must be unique.
"""

from __future__ import annotations

import pandas as pd

IST = "Asia/Kolkata"

COLUMNS = ["ts", "open", "high", "low", "close", "volume", "oi"]

_FLOAT_COLS = ["open", "high", "low", "close"]


class CandleValidationError(ValueError):
    """Raised when a candle frame violates the storage contract."""


def normalize(frame: pd.DataFrame) -> pd.DataFrame:
    """Coerce an input frame to the canonical schema, dtypes, and IST tz.

    Accepts any frame carrying the required columns. Returns a new frame with
    exactly ``COLUMNS``, sorted by ``ts`` ascending. Does not validate OHLC
    relationships — call :func:`validate` for that.
    """
    missing = [c for c in COLUMNS if c not in frame.columns and c != "oi"]
    if missing:
        raise CandleValidationError(f"missing required columns: {missing}")

    df = frame.copy()

    ts = pd.to_datetime(df["ts"])
    if ts.dt.tz is None:
        raise CandleValidationError("ts must be timezone-aware (IST)")
    df["ts"] = ts.dt.tz_convert(IST)

    for col in _FLOAT_COLS:
        df[col] = df[col].astype("float64")
    df["volume"] = df["volume"].astype("int64")
    if "oi" in df.columns:
        df["oi"] = df["oi"].astype("Int64")
    else:
        df["oi"] = pd.array([pd.NA] * len(df), dtype="Int64")

    df = df[COLUMNS].sort_values("ts", ignore_index=True)
    return df


def validate(df: pd.DataFrame) -> None:
    """Validate a normalized candle frame; raise on any contract violation."""
    if df.empty:
        return

    if df["ts"].duplicated().any():
        raise CandleValidationError("duplicate ts values")
    if not df["ts"].is_monotonic_increasing:
        raise CandleValidationError("ts is not sorted ascending")

    for col in [*_FLOAT_COLS, "volume"]:
        if (df[col] < 0).any():
            raise CandleValidationError(f"negative values in {col}")

    if (df["high"] < df["low"]).any():
        raise CandleValidationError("high < low")
    if ((df["open"] > df["high"]) | (df["open"] < df["low"])).any():
        raise CandleValidationError("open outside [low, high]")
    if ((df["close"] > df["high"]) | (df["close"] < df["low"])).any():
        raise CandleValidationError("close outside [low, high]")
