"""Read-only REST views: health, candles, futures/options chains."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from api.auth import APIKeyAuthentication, HasAPIKey
from api.resolvers import (
    chain_contracts,
    check_range,
    parse_datetime,
    parse_day,
    parse_interval,
    resolve_instrument,
    resolve_underlying,
    serialize_contract,
)
from candles import reader
from catalog.enums import InstrumentType


def _q(request: Request) -> dict[str, str | None]:
    return {k: request.query_params.get(k) for k in request.query_params}


def _json_safe(value: Any) -> Any:
    """Coerce pandas/numpy scalars to plain JSON types."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _candles_payload(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    rows: list[dict[str, Any]] = []
    for record in df.to_dict(orient="records"):
        rows.append({k: _json_safe(v) for k, v in record.items()})
    return rows


class HealthView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        return Response({"status": "ok"})


class CandlesView(APIView):
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [HasAPIKey]

    def get(self, request: Request) -> Response:
        params = _q(request)
        instrument = resolve_instrument(params)
        interval = parse_interval(params.get("interval"))
        start = parse_datetime(params.get("start"), field="start")
        end = parse_datetime(params.get("end"), field="end")
        check_range(interval, start, end)

        df = reader.read(instrument, interval, start, end)
        candles = _candles_payload(df)
        return Response(
            {
                "key": instrument.key,
                "interval": interval.value,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "count": len(candles),
                "candles": candles,
            }
        )


class FuturesChainView(APIView):
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [HasAPIKey]

    def get(self, request: Request) -> Response:
        params = _q(request)
        day = parse_day(params.get("date"))
        underlying = resolve_underlying(params.get("underlying"), params.get("exchange"))
        contracts = chain_contracts(underlying, InstrumentType.FUTURE, day)
        return Response(
            {
                "underlying": underlying.key,
                "date": day.isoformat(),
                "count": len(contracts),
                "contracts": [serialize_contract(c) for c in contracts],
            }
        )


class OptionsChainView(APIView):
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [HasAPIKey]

    def get(self, request: Request) -> Response:
        params = _q(request)
        day = parse_day(params.get("date"))
        expiry_raw = (params.get("expiry") or "").strip()
        expiry = parse_day(expiry_raw, field="expiry") if expiry_raw else None
        underlying = resolve_underlying(params.get("underlying"), params.get("exchange"))
        contracts = chain_contracts(underlying, InstrumentType.OPTION, day, expiry=expiry)
        return Response(
            {
                "underlying": underlying.key,
                "date": day.isoformat(),
                "expiry": expiry.isoformat() if expiry else None,
                "count": len(contracts),
                "contracts": [serialize_contract(c) for c in contracts],
            }
        )
