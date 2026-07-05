"""Convert tt-connect Candle objects into the canonical candle frame.

Output columns match ``candles.schema.COLUMNS``; ``candles.storage.write`` handles
timezone normalization, validation, and idempotent merging on write.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from candles.schema import COLUMNS

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from tt_connect.core.models.responses import Candle


def candles_to_frame(candles: Sequence[Candle]) -> pd.DataFrame:
    """Build a canonical OHLCV+OI frame from tt-connect candles."""
    rows = [
        {
            "ts": c.timestamp,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
            "oi": c.oi,
        }
        for c in candles
    ]
    return pd.DataFrame(rows, columns=COLUMNS)
