"""Rollups for admin coverage views — watchlist / catalog health at a glance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db.models import Count, Max, Q

from catalog.enums import InstrumentType
from catalog.models import Instrument
from ingestion.models import Watchlist


@dataclass(frozen=True)
class TypeCoverage:
    instrument_type: str
    tracked: int
    with_data: int
    empty: int
    data_end: date | None

    @property
    def label(self) -> str:
        return self.instrument_type.title()


@dataclass(frozen=True)
class UnderlyingFnoCoverage:
    symbol: str
    underlying_id: int
    futures_tracked: int
    futures_with_data: int
    options_tracked: int
    options_with_data: int
    equity_data_end: date | None

    @property
    def options_empty(self) -> int:
        return self.options_tracked - self.options_with_data

    @property
    def futures_empty(self) -> int:
        return self.futures_tracked - self.futures_with_data


def type_coverage(*, tracked_only: bool = True) -> list[TypeCoverage]:
    qs = Instrument.objects.all()
    if tracked_only:
        qs = qs.filter(is_tracked=True)
    rows = (
        qs.values("instrument_type")
        .annotate(
            tracked=Count("id"),
            with_data=Count("id", filter=Q(data_start__isnull=False)),
            data_end=Max("data_end"),
        )
        .order_by("instrument_type")
    )
    out: list[TypeCoverage] = []
    for row in rows:
        tracked = row["tracked"]
        with_data = row["with_data"]
        out.append(
            TypeCoverage(
                instrument_type=row["instrument_type"],
                tracked=tracked,
                with_data=with_data,
                empty=tracked - with_data,
                data_end=row["data_end"],
            )
        )
    return out


def watchlist_fno_coverage() -> list[UnderlyingFnoCoverage]:
    """Per active F&O watchlist underlying: tracked vs with-data counts."""
    entries = (
        Watchlist.objects.filter(is_active=True)
        .filter(Q(track_futures=True) | Q(track_options=True))
        .select_related("underlying")
        .order_by("underlying__symbol")
    )
    out: list[UnderlyingFnoCoverage] = []
    for entry in entries:
        und = entry.underlying
        deriv = Instrument.objects.filter(underlying=und, is_tracked=True)
        fut = deriv.filter(instrument_type=InstrumentType.FUTURE)
        opt = deriv.filter(instrument_type=InstrumentType.OPTION)
        out.append(
            UnderlyingFnoCoverage(
                symbol=und.symbol,
                underlying_id=und.pk,
                futures_tracked=fut.count(),
                futures_with_data=fut.exclude(data_start__isnull=True).count(),
                options_tracked=opt.count(),
                options_with_data=opt.exclude(data_start__isnull=True).count(),
                equity_data_end=und.data_end,
            )
        )
    return out


def coverage_summary() -> dict[str, object]:
    types = type_coverage(tracked_only=True)
    tracked = sum(t.tracked for t in types)
    with_data = sum(t.with_data for t in types)
    return {
        "types": types,
        "tracked": tracked,
        "with_data": with_data,
        "empty": tracked - with_data,
        "watchlist_active": Watchlist.objects.filter(is_active=True).count(),
        "fno": watchlist_fno_coverage(),
        "latest_data_end": max((t.data_end for t in types if t.data_end), default=None),
    }
