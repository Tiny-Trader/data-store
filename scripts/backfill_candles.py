"""One-off historical backfill of 1-minute candles for a single instrument.

This is deliberately NOT part of the running system (the EOD job only fetches
t-1). Backfill is a manual, occasional operation, so it lives here as a script.

AngelOne caps 1-minute history per request (~30 days), so the range is fetched
in windows and merged idempotently into the Parquet store.

Usage::

    poetry run python scripts/backfill_candles.py \
        --symbol NIFTY --exchange NSE --type index \
        --start 2026-06-01 --end 2026-06-30 --broker angelone
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from candles import storage  # noqa: E402
from catalog.enums import Exchange, InstrumentType  # noqa: E402
from catalog.models import Instrument  # noqa: E402
from ingestion.broker import TTBroker  # noqa: E402
from ingestion.normalize import candles_to_frame  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def _ensure_instrument(symbol: str, exchange: str, itype: str) -> Instrument:
    inst, created = Instrument.objects.get_or_create(
        instrument_type=itype,
        exchange=exchange,
        symbol=symbol,
        defaults={"is_tracked": True},
    )
    print(f"{'created' if created else 'found'} instrument {inst.key}")
    return inst


def _windows(start: date, end: date, chunk_days: int):
    cur = start
    while cur <= end:
        win_end = min(cur + timedelta(days=chunk_days - 1), end)
        yield (
            datetime(cur.year, cur.month, cur.day, 0, 0, tzinfo=IST),
            datetime(win_end.year, win_end.month, win_end.day, 23, 59, 59, tzinfo=IST),
        )
        cur = win_end + timedelta(days=1)


def backfill(inst: Instrument, broker: TTBroker, start: date, end: date, chunk_days: int) -> None:
    total = 0
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    for win_start, win_end in _windows(start, end, chunk_days):
        candles = broker.historical_1m_range(inst, win_start, win_end)
        if not candles:
            print(f"  {win_start.date()}..{win_end.date()}: 0 candles")
            continue
        frame = candles_to_frame(candles)
        rows = storage.write(inst, frame)
        total += rows
        first_ts = min(first_ts or candles[0].timestamp, candles[0].timestamp)
        last_ts = max(last_ts or candles[-1].timestamp, candles[-1].timestamp)
        print(f"  {win_start.date()}..{win_end.date()}: {rows} rows")

    if total and first_ts and last_ts:
        inst.data_start = min(inst.data_start or first_ts.date(), first_ts.date())
        inst.data_end = max(inst.data_end or last_ts.date(), last_ts.date())
        inst.save(update_fields=["data_start", "data_end", "updated"])
    print(f"done: {total} rows, coverage {inst.data_start}..{inst.data_end}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--exchange", default=Exchange.NSE, choices=[e.value for e in Exchange])
    parser.add_argument(
        "--type",
        dest="itype",
        default=InstrumentType.INDEX,
        choices=[t.value for t in InstrumentType],
    )
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--broker", default=os.getenv("DEFAULT_BROKER", "angelone"))
    parser.add_argument("--chunk-days", type=int, default=20)
    args = parser.parse_args()

    inst = _ensure_instrument(args.symbol, args.exchange, args.itype)
    print(f"backfill {inst.symbol} {args.start}..{args.end} via {args.broker}")
    with TTBroker(args.broker) as broker:
        backfill(inst, broker, args.start, args.end, args.chunk_days)


if __name__ == "__main__":
    main()
