"""Daily EOD sync: watchlist -> concrete instruments -> t-1 candles -> Parquet.

This is the only thing the running system does. Watchlist entries are expanded
to concrete contracts at run time: F&O underlyings roll into their nearest N
expiries and (for options) an ATM +/- K strike window. ATM is approximated by
the median listed strike, which keeps expansion dependency-free (no spot lookup)
and is good enough for a bounded research window.

One-time historical backfill is intentionally out of scope here — do that with
standalone scripts.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from candles import storage
from catalog.enums import InstrumentType
from catalog.models import Instrument
from ingestion.models import Watchlist
from ingestion.normalize import candles_to_frame

if TYPE_CHECKING:  # pragma: no cover - typing only
    from tt_connect.core.models.responses import Candle

    from ingestion.broker import TTBroker

logger = logging.getLogger(__name__)

_MAX_BACKOFF_SEC = 30.0


class _Throttle:
    """Minimum-interval pacing to stay under the broker's request-rate limit."""

    def __init__(self, min_interval: float) -> None:
        self.min_interval = min_interval
        self._last = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        delta = time.monotonic() - self._last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last = time.monotonic()


def _build_fields(underlying: Instrument, tt_inst: object, itype: str) -> dict[str, object]:
    fields: dict[str, object] = {
        "instrument_type": itype,
        "exchange": str(tt_inst.exchange),  # type: ignore[attr-defined]
        "symbol": tt_inst.symbol,  # type: ignore[attr-defined]
        "expiry": tt_inst.expiry,  # type: ignore[attr-defined]
        "underlying": underlying,
        "is_tracked": True,
    }
    if itype == InstrumentType.OPTION:
        fields["strike"] = Decimal(str(tt_inst.strike))  # type: ignore[attr-defined]
        fields["option_type"] = str(tt_inst.option_type)  # type: ignore[attr-defined]
    return fields


def _upsert(underlying: Instrument, tt_inst: object, itype: str) -> Instrument:
    """Create or refresh the catalog row for a discovered contract."""
    fields = _build_fields(underlying, tt_inst, itype)
    key = Instrument(**fields).build_key()
    obj, _ = Instrument.objects.update_or_create(key=key, defaults=fields)
    return obj


def _select_strikes(strikes: Sequence[float], window: int) -> set[float]:
    """Pick ATM +/- ``window`` strikes, using the median listed strike as ATM."""
    ordered = sorted(set(strikes))
    if not ordered:
        return set()
    median = ordered[len(ordered) // 2]
    atm = min(range(len(ordered)), key=lambda i: abs(ordered[i] - median))
    lo = max(0, atm - window)
    hi = min(len(ordered), atm + window + 1)
    return set(ordered[lo:hi])


def _resolve_futures(entry: Watchlist, broker: TTBroker, day: date) -> list[Instrument]:
    futs = sorted(broker.futures(entry.underlying), key=lambda f: f.expiry)
    chosen = [f for f in futs if f.expiry >= day][: entry.n_expiries]
    return [_upsert(entry.underlying, f, InstrumentType.FUTURE) for f in chosen]


def _resolve_options(entry: Watchlist, broker: TTBroker, day: date) -> list[Instrument]:
    expiries = sorted(e for e in broker.expiries(entry.underlying) if e >= day)
    targets: list[Instrument] = []
    for expiry in expiries[: entry.n_expiries]:
        opts = broker.options(entry.underlying, expiry)
        keep = _select_strikes([float(o.strike) for o in opts], entry.strike_window)
        targets += [
            _upsert(entry.underlying, o, InstrumentType.OPTION)
            for o in opts
            if float(o.strike) in keep
        ]
    return targets


def resolve_targets(entry: Watchlist, broker: TTBroker, day: date) -> list[Instrument]:
    """Expand one watchlist entry into the concrete instruments to fetch today."""
    targets: list[Instrument] = []
    if entry.track_equity:
        targets.append(entry.underlying)
    if entry.track_futures:
        targets += _resolve_futures(entry, broker, day)
    if entry.track_options:
        targets += _resolve_options(entry, broker, day)
    return targets


def _record_coverage(instrument: Instrument, day: date) -> None:
    instrument.data_start = min(instrument.data_start or day, day)
    instrument.data_end = max(instrument.data_end or day, day)
    instrument.save(update_fields=["data_start", "data_end", "updated"])


def _build_tasks(
    entries: Iterable[Watchlist],
    broker: TTBroker,
    day: date,
    failed: list[str],
) -> dict[str, Instrument]:
    """Expand watchlist entries into a deduped {key: instrument} task map.

    Discovery failure for one underlying is isolated and recorded, not fatal.
    """
    tasks: dict[str, Instrument] = {}
    for entry in entries:
        try:
            for inst in resolve_targets(entry, broker, day):
                tasks[inst.key] = inst
        except Exception:
            logger.exception("resolve failed for %s", entry.underlying.key)
            failed.append(f"resolve:{entry.underlying.key}")
    return tasks


def _fetch(
    broker: TTBroker,
    inst: Instrument,
    day: date,
    throttle: _Throttle,
    retries: int,
) -> list[Candle]:
    """Fetch one instrument-day with pacing and exponential backoff."""
    for attempt in range(1, retries + 1):
        throttle.wait()
        try:
            return broker.historical_1m(inst, day)
        except Exception:
            if attempt >= retries:
                raise
            backoff = min(2.0**attempt, _MAX_BACKOFF_SEC)
            logger.warning(
                "fetch %s failed (attempt %d/%d), retrying in %.0fs",
                inst.key,
                attempt,
                retries,
                backoff,
                exc_info=True,
            )
            time.sleep(backoff)
    return []


def run_eod(
    broker: TTBroker,
    day: date,
    entries: Iterable[Watchlist] | None = None,
    *,
    min_interval: float = 0.0,
    retries: int = 3,
    force: bool = False,
) -> dict[str, object]:
    """Fetch and store one trading day of 1-minute candles for the watchlist.

    Resumable: instrument-days already present in the store are skipped (unless
    ``force``), so re-running after a failure only fetches the remainder. Each
    fetch is paced (``min_interval``) and retried with backoff; per-instrument
    failures are logged and collected, never aborting the batch.
    """
    if entries is None:
        entries = list(Watchlist.objects.filter(is_active=True).select_related("underlying"))

    failed: list[str] = []
    tasks = _build_tasks(entries, broker, day, failed)
    throttle = _Throttle(min_interval)
    stats: dict[str, object] = {
        "total": len(tasks),
        "written": 0,
        "rows": 0,
        "existing": 0,
        "empty": 0,
        "failed": 0,
    }

    for key, inst in tasks.items():
        if not force and storage.has_day(inst, day):
            stats["existing"] += 1  # type: ignore[operator]
            continue
        try:
            candles = _fetch(broker, inst, day, throttle, retries)
        except Exception:
            logger.error("giving up on %s for %s", key, day, exc_info=True)
            failed.append(key)
            continue
        if not candles:
            stats["empty"] += 1  # type: ignore[operator]
            continue
        stats["rows"] += storage.write(inst, candles_to_frame(candles))  # type: ignore[operator]
        stats["written"] += 1  # type: ignore[operator]
        _record_coverage(inst, day)

    stats["failed"] = len(failed)
    stats["failed_keys"] = failed
    if failed:
        logger.warning("eod %s: %d failed: %s", day, len(failed), ", ".join(failed))
    return stats
