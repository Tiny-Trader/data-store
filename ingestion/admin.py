from django.contrib import admin

from ingestion.models import Watchlist


@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = (
        "underlying",
        "track_equity",
        "track_futures",
        "track_options",
        "n_expiries",
        "strike_window",
        "is_active",
    )
    list_filter = ("is_active", "track_equity", "track_futures", "track_options")
    search_fields = ("underlying__symbol",)
    autocomplete_fields = ("underlying",)
