"""Daily EOD sync command.

Usage::

    python manage.py sync_eod                 # today (IST), default broker
    python manage.py sync_eod --date 2026-07-03
    python manage.py sync_eod --broker angelone
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from ingestion.broker import TTBroker
from ingestion.eod import run_eod

IST = ZoneInfo("Asia/Kolkata")


class Command(BaseCommand):
    help = "Fetch and store one trading day of 1-minute candles for the watchlist."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--date",
            dest="day",
            help="Trading day to fetch (YYYY-MM-DD, IST). Defaults to today.",
        )
        parser.add_argument(
            "--broker",
            default=getattr(settings, "DEFAULT_BROKER", "zerodha"),
            help="Broker id to source data from.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-fetch instrument-days even if already stored.",
        )

    def handle(self, *args: object, **options: object) -> None:
        day = self._resolve_day(options.get("day"))
        broker_id = str(options["broker"])
        self.stdout.write(f"EOD sync for {day} via {broker_id}")
        with TTBroker(broker_id) as broker:
            stats = run_eod(
                broker,
                day,
                min_interval=getattr(settings, "EOD_MIN_INTERVAL_SEC", 0.4),
                retries=getattr(settings, "EOD_MAX_RETRIES", 3),
                force=bool(options["force"]),
            )
        self.stdout.write(
            self.style.SUCCESS(
                "done: {written}/{total} written, {rows} rows, "
                "{existing} present, {empty} empty, {failed} failed".format(**stats)
            )
        )
        failed_keys = stats.get("failed_keys") or []
        if failed_keys:
            self.stdout.write(self.style.WARNING("failed: " + ", ".join(failed_keys)))

    @staticmethod
    def _resolve_day(raw: object) -> date:
        if not raw:
            return datetime.now(IST).date()
        try:
            return date.fromisoformat(str(raw))
        except ValueError as exc:
            raise CommandError(f"invalid --date {raw!r}, expected YYYY-MM-DD") from exc
