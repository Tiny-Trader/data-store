from __future__ import annotations

from django.contrib import admin
from django.db.models import Count, Q, QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html

from catalog.enums import InstrumentType
from ingestion.models import Watchlist


@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = (
        "underlying",
        "is_active",
        "track_equity",
        "track_futures",
        "track_options",
        "n_expiries",
        "strike_window",
        "underlying_coverage",
        "futures_coverage",
        "options_coverage",
    )
    list_filter = ("is_active", "track_equity", "track_futures", "track_options")
    search_fields = ("underlying__symbol", "underlying__key")
    autocomplete_fields = ("underlying",)
    list_select_related = ("underlying",)
    list_per_page = 100
    ordering = ("underlying__symbol",)

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        qs = super().get_queryset(request)
        return qs.annotate(
            fut_total=Count(
                "underlying__derivatives",
                filter=Q(
                    underlying__derivatives__instrument_type=InstrumentType.FUTURE,
                    underlying__derivatives__is_tracked=True,
                ),
                distinct=True,
            ),
            fut_with_data=Count(
                "underlying__derivatives",
                filter=Q(
                    underlying__derivatives__instrument_type=InstrumentType.FUTURE,
                    underlying__derivatives__is_tracked=True,
                    underlying__derivatives__data_start__isnull=False,
                ),
                distinct=True,
            ),
            opt_total=Count(
                "underlying__derivatives",
                filter=Q(
                    underlying__derivatives__instrument_type=InstrumentType.OPTION,
                    underlying__derivatives__is_tracked=True,
                ),
                distinct=True,
            ),
            opt_with_data=Count(
                "underlying__derivatives",
                filter=Q(
                    underlying__derivatives__instrument_type=InstrumentType.OPTION,
                    underlying__derivatives__is_tracked=True,
                    underlying__derivatives__data_start__isnull=False,
                ),
                distinct=True,
            ),
        )

    @admin.display(description="Underlying data")
    def underlying_coverage(self, obj: Watchlist) -> str:
        und = obj.underlying
        if und.data_start and und.data_end:
            return f"{und.data_start} → {und.data_end}"
        return "—"

    @admin.display(description="Futures")
    def futures_coverage(self, obj: Watchlist) -> str:
        total = getattr(obj, "fut_total", 0)
        with_data = getattr(obj, "fut_with_data", 0)
        if not obj.track_futures and total == 0:
            return "—"
        url = (
            reverse("admin:catalog_futureinstrument_changelist")
            + f"?underlying={obj.underlying_id}"
        )
        return format_html('<a href="{}">{}/{}</a>', url, with_data, total)

    @admin.display(description="Options")
    def options_coverage(self, obj: Watchlist) -> str:
        total = getattr(obj, "opt_total", 0)
        with_data = getattr(obj, "opt_with_data", 0)
        if not obj.track_options and total == 0:
            return "—"
        url = (
            reverse("admin:catalog_optioninstrument_changelist")
            + f"?underlying={obj.underlying_id}"
        )
        return format_html('<a href="{}">{}/{}</a>', url, with_data, total)
