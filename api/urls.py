from django.urls import path

from api.views import CandlesView, FuturesChainView, HealthView, OptionsChainView

urlpatterns = [
    path("health/", HealthView.as_view(), name="api-health"),
    path("candles/", CandlesView.as_view(), name="api-candles"),
    path("chains/futures/", FuturesChainView.as_view(), name="api-chains-futures"),
    path("chains/options/", OptionsChainView.as_view(), name="api-chains-options"),
]
