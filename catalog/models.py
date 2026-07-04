"""Durable instrument/contract catalog.

data-store owns this catalog as its system of record. It mirrors tt-connect's
canonical instrument fields (exchange, symbol, segment, lot/tick size, expiry,
strike, option_type) so identities line up with the ingestion-time resolver,
then adds the lifecycle columns tt-connect deliberately omits:

- ``is_tracked`` — whether we actively sync data for this instrument
- ``status`` — ACTIVE / INACTIVE / EXPIRED (expired F&O rows are retained,
  since backtests still need contracts that have left the broker master)
- ``data_start`` / ``data_end`` / ``data_gaps`` — availability lineage for the
  Parquet candle files
"""

from __future__ import annotations

from django.db import models

from catalog.enums import Exchange, InstrumentType, OptionType, Status


class TimeStampedModel(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Instrument(TimeStampedModel):
    """A single tradable (or indexable) instrument or derivative contract.

    ``key`` is a deterministic natural identity derived from the canonical
    fields. It makes syncs idempotent and sidesteps SQLite's NULL-distinct
    behavior in unique constraints across the nullable derivative columns.
    """

    key = models.CharField(
        max_length=128,
        unique=True,
        editable=False,
        help_text="Deterministic natural key, e.g. 'NFO:NIFTY:OPTION:2026-01-29:22000:CE'",
    )

    # --- Canonical identity (mirrors tt-connect) ---
    instrument_type = models.CharField(max_length=10, choices=InstrumentType.choices)
    exchange = models.CharField(max_length=3, choices=Exchange.choices)
    symbol = models.CharField(max_length=64, help_text="Canonical trading symbol")

    # --- Canonical metadata ---
    name = models.CharField(max_length=255, blank=True)
    segment = models.CharField(max_length=32, blank=True)
    lot_size = models.PositiveIntegerField(null=True, blank=True)
    tick_size = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    isin = models.CharField(max_length=12, blank=True, help_text="Equities only")

    # --- Derivative fields (F&O only) ---
    underlying = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="derivatives",
        help_text="Underlying instrument for futures/options",
    )
    expiry = models.DateField(null=True, blank=True)
    strike = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    option_type = models.CharField(
        max_length=2, choices=OptionType.choices, blank=True, default=""
    )

    # --- Lifecycle / data lineage (data-store owns these) ---
    is_tracked = models.BooleanField(
        default=False, help_text="Whether data-store actively syncs data for this instrument"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    data_start = models.DateField(null=True, blank=True, help_text="First date with stored data")
    data_end = models.DateField(null=True, blank=True, help_text="Last date with stored data")
    data_gaps = models.JSONField(
        default=list, blank=True, help_text="List of [start, end] date ranges missing from storage"
    )

    class Meta:
        db_table = "instruments"
        ordering = ["exchange", "symbol", "expiry", "strike"]
        indexes = [
            models.Index(fields=["exchange", "symbol"]),
            models.Index(fields=["instrument_type"]),
            models.Index(fields=["expiry"]),
            models.Index(fields=["is_tracked", "status"]),
        ]

    def __str__(self) -> str:
        return self.key

    def save(self, *args: object, **kwargs: object) -> None:
        self.key = self.build_key()
        super().save(*args, **kwargs)  # type: ignore[arg-type]

    def build_key(self) -> str:
        """Compose the deterministic natural key from canonical fields."""
        parts: list[str] = [self.exchange, self.symbol, self.instrument_type]
        if self.expiry is not None:
            parts.append(self.expiry.isoformat())
        if self.strike is not None:
            parts.append(f"{self.strike:f}".rstrip("0").rstrip("."))
        if self.option_type:
            parts.append(self.option_type)
        return ":".join(parts)


class BrokerToken(TimeStampedModel):
    """Maps a canonical instrument to a broker-specific token/symbol.

    Mirrors tt-connect's ``broker_tokens`` cache table, but persisted durably so
    resolution stays available for expired contracts and offline queries.
    """

    instrument = models.ForeignKey(
        Instrument, on_delete=models.CASCADE, related_name="broker_tokens"
    )
    broker_id = models.CharField(max_length=32, help_text="e.g. 'zerodha', 'angelone'")
    token = models.CharField(max_length=64, help_text="Broker-specific instrument token")
    broker_symbol = models.CharField(max_length=128, help_text="Broker-specific trading symbol")

    class Meta:
        db_table = "broker_tokens"
        ordering = ["broker_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["instrument", "broker_id"], name="uniq_instrument_broker"
            )
        ]
        indexes = [models.Index(fields=["broker_id", "token"])]

    def __str__(self) -> str:
        return f"{self.instrument.symbol} @ {self.broker_id} ({self.token})"
