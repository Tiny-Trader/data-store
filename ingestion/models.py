"""Watchlist: the user-owned control surface for the daily EOD job.

Tracking is declared at the underlying level and expanded to concrete contracts
at run time (see ``ingestion.eod``), so F&O rolls are handled automatically and
you never hand-manage individual contracts. Edit entries anytime via the admin.
"""

from __future__ import annotations

from django.db import models

from catalog.models import Instrument, TimeStampedModel


class Watchlist(TimeStampedModel):
    underlying = models.ForeignKey(
        Instrument,
        on_delete=models.CASCADE,
        related_name="watchlist_entries",
        help_text="Equity or index instrument to track",
    )
    track_equity = models.BooleanField(
        default=False, help_text="Fetch the underlying's own candles (equity/index)"
    )
    track_futures = models.BooleanField(default=False)
    track_options = models.BooleanField(default=False)
    n_expiries = models.PositiveSmallIntegerField(
        default=5, help_text="Nearest N expiries to pull for F&O"
    )
    strike_window = models.PositiveSmallIntegerField(
        default=20, help_text="ATM +/- K strikes to pull for options"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "watchlist"
        ordering = ["underlying__symbol"]
        constraints = [
            models.UniqueConstraint(fields=["underlying"], name="uniq_watchlist_underlying")
        ]

    def __str__(self) -> str:
        flags = [
            name
            for name, on in (
                ("EQ", self.track_equity),
                ("FUT", self.track_futures),
                ("OPT", self.track_options),
            )
            if on
        ]
        return f"{self.underlying.symbol} [{','.join(flags) or 'none'}]"
