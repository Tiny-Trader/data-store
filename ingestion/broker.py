"""Thin wrapper over tt-connect for the EOD job.

Translates data-store catalog instruments into tt-connect canonical instruments,
and exposes just the calls the daily job needs: historical candles plus F&O
discovery. tt-connect imports are lazy so this module (and migrations/tests that
mock the broker) load without the dependency installed.

Broker credentials are read from a per-broker JSON env var, ``TT_<BROKER>_CONFIG``
(e.g. ``TT_ZERODHA_CONFIG``), and passed straight to ``TTConnect`` — data-store
stays agnostic about each broker's exact config keys.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from django.core.exceptions import ImproperlyConfigured

from catalog.enums import InstrumentType
from catalog.models import Instrument

if TYPE_CHECKING:  # pragma: no cover - typing only
    from tt_connect.core.models.instruments import Instrument as TTInstrument
    from tt_connect.core.models.responses import Candle

IST = ZoneInfo("Asia/Kolkata")


def to_ttconnect(instrument: Instrument) -> TTInstrument:
    """Translate a catalog instrument into its tt-connect canonical form."""
    from tt_connect.instruments import Equity, Future, Index, Option

    itype = instrument.instrument_type
    if itype == InstrumentType.EQUITY:
        return Equity(exchange=instrument.exchange, symbol=instrument.symbol)
    if itype == InstrumentType.INDEX:
        return Index(exchange=instrument.exchange, symbol=instrument.symbol)
    if itype == InstrumentType.FUTURE:
        return Future(
            exchange=instrument.exchange, symbol=instrument.symbol, expiry=instrument.expiry
        )
    if itype == InstrumentType.OPTION:
        return Option(
            exchange=instrument.exchange,
            symbol=instrument.symbol,
            expiry=instrument.expiry,
            strike=float(instrument.strike),
            option_type=instrument.option_type,
        )
    raise ValueError(f"unsupported instrument_type for tt-connect: {itype}")


class TTBroker:
    """Context-managed tt-connect session scoped to a single broker."""

    def __init__(self, broker_id: str) -> None:
        self.broker_id = broker_id
        self._client: Any = None

    def _load_config(self) -> dict[str, Any]:
        raw = os.getenv(f"TT_{self.broker_id.upper()}_CONFIG")
        if not raw:
            raise ImproperlyConfigured(
                f"missing broker config env var TT_{self.broker_id.upper()}_CONFIG"
            )
        return json.loads(raw)

    def __enter__(self) -> TTBroker:
        from tt_connect import TTConnect

        self._client = TTConnect(self.broker_id, self._load_config())
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def historical_1m_range(
        self, instrument: Instrument, start: datetime, end: datetime
    ) -> list[Candle]:
        """Fetch 1-minute candles for an explicit [start, end] window.

        No chunking — the broker's own per-request span limits apply, so callers
        fetching long ranges (e.g. backfill) must window their requests.
        """
        from tt_connect.enums import CandleInterval

        return self._client.get_historical(
            to_ttconnect(instrument), CandleInterval.MINUTE_1, start, end
        )

    def historical_1m(self, instrument: Instrument, day: date) -> list[Candle]:
        """Fetch 1-minute candles for a single trading day (full IST session)."""
        start = datetime(day.year, day.month, day.day, 0, 0, tzinfo=IST)
        end = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=IST)
        return self.historical_1m_range(instrument, start, end)

    def futures(self, underlying: Instrument) -> list[Any]:
        return self._client.get_futures(to_ttconnect(underlying))

    def options(self, underlying: Instrument, expiry: date) -> list[Any]:
        return self._client.get_options(to_ttconnect(underlying), expiry)

    def expiries(self, underlying: Instrument) -> list[date]:
        return self._client.get_expiries(to_ttconnect(underlying))
