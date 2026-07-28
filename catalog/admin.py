"""Catalog admin: typed instrument lists + coverage on the admin home."""

from __future__ import annotations

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest
from django.urls import reverse

from catalog.coverage import coverage_summary
from catalog.enums import InstrumentType
from catalog.models import (
    BrokerToken,
    EquityInstrument,
    FutureInstrument,
    IndexInstrument,
    Instrument,
    OptionInstrument,
)


class HasDataFilter(admin.SimpleListFilter):
    title = "candle coverage"
    parameter_name = "has_data"

    def lookups(self, request: HttpRequest, model_admin: admin.ModelAdmin):
        return (("yes", "Has data"), ("no", "No data"))

    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        if self.value() == "yes":
            return queryset.exclude(data_start__isnull=True)
        if self.value() == "no":
            return queryset.filter(data_start__isnull=True)
        return queryset


class WatchlistUnderlyingFilter(admin.SimpleListFilter):
    """Limit underlying filter to watchlist underlyings (not every equity)."""

    title = "underlying"
    parameter_name = "underlying"

    def lookups(self, request: HttpRequest, model_admin: admin.ModelAdmin):
        from ingestion.models import Watchlist

        return list(
            Watchlist.objects.filter(is_active=True)
            .order_by("underlying__symbol")
            .values_list("underlying_id", "underlying__symbol")
        )

    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        if self.value():
            return queryset.filter(underlying_id=self.value())
        return queryset


class BrokerTokenInline(admin.TabularInline):
    model = BrokerToken
    extra = 0


class BaseInstrumentAdmin(admin.ModelAdmin):
    list_display = (
        "key",
        "exchange",
        "symbol",
        "is_tracked",
        "status",
        "coverage",
        "data_start",
        "data_end",
    )
    list_filter = ("exchange", "status", "is_tracked", HasDataFilter)
    search_fields = ("key", "symbol", "name", "isin")
    readonly_fields = ("key", "created", "updated")
    autocomplete_fields = ("underlying",)
    list_select_related = ("underlying",)
    list_per_page = 50
    show_full_result_count = False
    inlines = [BrokerTokenInline]
    ordering = ("symbol", "expiry", "strike")

    @admin.display(description="Coverage")
    def coverage(self, obj: Instrument) -> str:
        if obj.data_start and obj.data_end:
            return f"{obj.data_start} → {obj.data_end}"
        if obj.data_start or obj.data_end:
            return f"{obj.data_start or '—'} → {obj.data_end or '—'}"
        return "—"

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        return super().get_queryset(request).defer("data_gaps")


@admin.register(EquityInstrument)
class EquityInstrumentAdmin(BaseInstrumentAdmin):
    def get_queryset(self, request: HttpRequest) -> QuerySet:
        return (
            super()
            .get_queryset(request)
            .filter(instrument_type=InstrumentType.EQUITY)
        )


@admin.register(IndexInstrument)
class IndexInstrumentAdmin(BaseInstrumentAdmin):
    def get_queryset(self, request: HttpRequest) -> QuerySet:
        return (
            super()
            .get_queryset(request)
            .filter(instrument_type=InstrumentType.INDEX)
        )


@admin.register(FutureInstrument)
class FutureInstrumentAdmin(BaseInstrumentAdmin):
    list_display = (
        "key",
        "underlying_link",
        "expiry",
        "is_tracked",
        "status",
        "coverage",
        "data_start",
        "data_end",
    )
    list_filter = (WatchlistUnderlyingFilter, "status", "is_tracked", HasDataFilter, "expiry")

    @admin.display(description="Underlying", ordering="underlying__symbol")
    def underlying_link(self, obj: Instrument) -> str:
        if not obj.underlying_id:
            return "—"
        return obj.underlying.symbol

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        return (
            super()
            .get_queryset(request)
            .filter(instrument_type=InstrumentType.FUTURE)
        )


@admin.register(OptionInstrument)
class OptionInstrumentAdmin(BaseInstrumentAdmin):
    list_display = (
        "key",
        "underlying_link",
        "expiry",
        "strike",
        "option_type",
        "is_tracked",
        "status",
        "coverage",
        "data_start",
        "data_end",
    )
    list_filter = (
        WatchlistUnderlyingFilter,
        "expiry",
        "option_type",
        "status",
        "is_tracked",
        HasDataFilter,
    )
    ordering = ("underlying__symbol", "expiry", "strike", "option_type")

    @admin.display(description="Underlying", ordering="underlying__symbol")
    def underlying_link(self, obj: Instrument) -> str:
        if not obj.underlying_id:
            return "—"
        return obj.underlying.symbol

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        return (
            super()
            .get_queryset(request)
            .filter(instrument_type=InstrumentType.OPTION)
        )


@admin.register(BrokerToken)
class BrokerTokenAdmin(admin.ModelAdmin):
    list_display = ("instrument", "broker_id", "token", "broker_symbol")
    list_filter = ("broker_id",)
    search_fields = ("token", "broker_symbol", "instrument__symbol", "instrument__key")
    autocomplete_fields = ("instrument",)
    list_select_related = ("instrument",)
    list_per_page = 50
    show_full_result_count = False


# Autocomplete for FKs still needs a registered Instrument admin.
@admin.register(Instrument)
class InstrumentAdmin(BaseInstrumentAdmin):
    """Catch-all / autocomplete target — prefer typed lists above."""

    list_display = (
        "key",
        "instrument_type",
        "exchange",
        "symbol",
        "expiry",
        "strike",
        "option_type",
        "is_tracked",
        "status",
        "coverage",
    )
    list_filter = ("instrument_type", "exchange", "status", "is_tracked", HasDataFilter)


def _patch_admin_index() -> None:
    """Inject coverage summary into the admin home page."""
    if getattr(admin.site, "_tt_coverage_patched", False):
        return

    original_index = admin.site.index

    def index(request: HttpRequest, extra_context: dict | None = None):
        extra_context = extra_context or {}
        extra_context["coverage"] = coverage_summary()
        extra_context["coverage_urls"] = {
            "equities": reverse("admin:catalog_equityinstrument_changelist"),
            "indices": reverse("admin:catalog_indexinstrument_changelist"),
            "futures": reverse("admin:catalog_futureinstrument_changelist"),
            "options": reverse("admin:catalog_optioninstrument_changelist"),
            "options_empty": (
                reverse("admin:catalog_optioninstrument_changelist") + "?has_data=no"
            ),
        }
        return original_index(request, extra_context)

    admin.site.index = index  # type: ignore[method-assign]
    admin.site._tt_coverage_patched = True  # type: ignore[attr-defined]
    admin.site.site_header = "tiny-trader data-store"
    admin.site.site_title = "data-store"
    admin.site.index_title = "Coverage & catalog"

    original_get_app_list = admin.site.get_app_list

    def get_app_list(request: HttpRequest, app_label: str | None = None):
        app_list = original_get_app_list(request, app_label)
        # Watchlist first, then Catalog, then the rest.
        order = {"ingestion": 0, "catalog": 1}
        app_list.sort(key=lambda a: order.get(a["app_label"], 50))
        return app_list

    admin.site.get_app_list = get_app_list  # type: ignore[method-assign]


_patch_admin_index()
