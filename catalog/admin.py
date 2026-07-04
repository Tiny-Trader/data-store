from django.contrib import admin

from catalog.models import BrokerToken, Instrument


class BrokerTokenInline(admin.TabularInline):
    model = BrokerToken
    extra = 0


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
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
        "data_start",
        "data_end",
    )
    list_filter = ("instrument_type", "exchange", "status", "is_tracked")
    search_fields = ("key", "symbol", "name", "isin")
    readonly_fields = ("key", "created", "updated")
    inlines = [BrokerTokenInline]


@admin.register(BrokerToken)
class BrokerTokenAdmin(admin.ModelAdmin):
    list_display = ("instrument", "broker_id", "token", "broker_symbol")
    list_filter = ("broker_id",)
    search_fields = ("token", "broker_symbol", "instrument__symbol")
