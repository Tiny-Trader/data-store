"""Seed the catalog + watchlist for the tracked universe.

Creates the underlying catalog rows and watchlist entries; tt-connect resolves
broker tokens at fetch time and the EOD job upserts F&O contracts lazily, so no
full instrument-master sync is needed here.

Tracked universe:
  - NIFTY50 stocks (from ingestion/data/nifty50.txt) -> equity candles
  - NIFTY (NSE) and SENSEX (BSE)                     -> equity + futures + options

Idempotent: safe to re-run after editing the constituent list.

Usage::

    python manage.py seed_watchlist
    python manage.py seed_watchlist --n-expiries 4 --strike-window 15
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandParser

from catalog.enums import Exchange, InstrumentType
from catalog.models import Instrument
from ingestion.models import Watchlist

NIFTY50_FILE = Path(__file__).resolve().parents[2] / "data" / "nifty50.txt"

# (symbol, exchange) of the index underlyings tracked for F&O.
INDICES = [("NIFTY", Exchange.NSE), ("SENSEX", Exchange.BSE)]


def _read_symbols(path: Path) -> list[str]:
    lines = path.read_text().splitlines()
    return [s.strip() for s in lines if s.strip() and not s.startswith("#")]


class Command(BaseCommand):
    help = "Seed catalog underlyings and watchlist entries for the tracked universe."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--n-expiries", type=int, default=3)
        parser.add_argument("--strike-window", type=int, default=10)

    def _ensure_underlying(self, symbol: str, exchange: str, itype: str) -> Instrument:
        inst, _ = Instrument.objects.get_or_create(
            instrument_type=itype,
            exchange=exchange,
            symbol=symbol,
            defaults={"is_tracked": True},
        )
        return inst

    def handle(self, *args: object, **options: object) -> None:
        n_expiries = int(options["n_expiries"])
        strike_window = int(options["strike_window"])

        stocks = _read_symbols(NIFTY50_FILE)
        for symbol in stocks:
            inst = self._ensure_underlying(symbol, Exchange.NSE, InstrumentType.EQUITY)
            Watchlist.objects.update_or_create(
                underlying=inst,
                defaults={"track_equity": True, "is_active": True},
            )

        for symbol, exchange in INDICES:
            inst = self._ensure_underlying(symbol, exchange, InstrumentType.INDEX)
            Watchlist.objects.update_or_create(
                underlying=inst,
                defaults={
                    "track_equity": True,
                    "track_futures": True,
                    "track_options": True,
                    "n_expiries": n_expiries,
                    "strike_window": strike_window,
                    "is_active": True,
                },
            )

        # Reconcile the equity roster: the file is authoritative, so equity
        # entries no longer listed (e.g. removed on an index reshuffle) are
        # deactivated rather than left to fail daily. Index and any other
        # entries are managed explicitly above and untouched here.
        deactivated = (
            Watchlist.objects.filter(
                is_active=True, underlying__instrument_type=InstrumentType.EQUITY
            )
            .exclude(underlying__symbol__in=stocks)
            .update(is_active=False)
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"seeded {len(stocks)} stocks + {len(INDICES)} indices; "
                f"deactivated {deactivated} off-roster; "
                f"watchlist now {Watchlist.objects.filter(is_active=True).count()} active"
            )
        )
