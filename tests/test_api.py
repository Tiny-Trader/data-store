"""REST API: health, candles, futures/options chains."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from rest_framework.test import APIClient

from candles import storage
from catalog.enums import Exchange, InstrumentType, OptionType
from catalog.models import Instrument
from tests.conftest import make_candles

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2024, 6, 3)
EXPIRY = date(2024, 6, 27)


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.fixture
def api_key(settings) -> str:
    settings.API_KEY = "test-secret"
    return "test-secret"


@pytest.fixture
def auth_client(client: APIClient, api_key: str) -> APIClient:
    client.credentials(HTTP_X_API_KEY=api_key)
    return client


@pytest.fixture
def nifty(db) -> Instrument:
    return Instrument.objects.create(
        instrument_type=InstrumentType.INDEX,
        exchange=Exchange.NSE,
        symbol="NIFTY",
        is_tracked=True,
    )


@pytest.fixture
def future(db, nifty: Instrument) -> Instrument:
    return Instrument.objects.create(
        instrument_type=InstrumentType.FUTURE,
        exchange=Exchange.NFO,
        symbol="NIFTY",
        underlying=nifty,
        expiry=EXPIRY,
        is_tracked=True,
        data_start=DAY,
        data_end=DAY,
    )


@pytest.fixture
def call(db, nifty: Instrument) -> Instrument:
    return Instrument.objects.create(
        instrument_type=InstrumentType.OPTION,
        exchange=Exchange.NFO,
        symbol="NIFTY",
        underlying=nifty,
        expiry=EXPIRY,
        strike=Decimal("22000"),
        option_type=OptionType.CE,
        is_tracked=True,
        data_start=DAY,
        data_end=DAY,
    )


@pytest.fixture
def put(db, nifty: Instrument) -> Instrument:
    return Instrument.objects.create(
        instrument_type=InstrumentType.OPTION,
        exchange=Exchange.NFO,
        symbol="NIFTY",
        underlying=nifty,
        expiry=EXPIRY,
        strike=Decimal("22000"),
        option_type=OptionType.PE,
        is_tracked=True,
        data_start=DAY,
        data_end=DAY,
    )


def test_health_is_public(client: APIClient):
    resp = client.get("/api/health/")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_candles_requires_api_key_when_configured(client: APIClient, api_key: str, future):
    resp = client.get("/api/candles/", {"key": future.key})
    assert resp.status_code == 401


def test_candles_by_key(auth_client: APIClient, store, future: Instrument):
    storage.write(future, make_candles("2024-06-03", 10))
    resp = auth_client.get(
        "/api/candles/",
        {
            "key": future.key,
            "interval": "1minute",
            "start": "2024-06-03T00:00:00+05:30",
            "end": "2024-06-04T00:00:00+05:30",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["key"] == future.key
    assert body["interval"] == "1minute"
    assert body["count"] == 10
    assert body["candles"][0]["open"] == 100.0
    assert "ts" in body["candles"][0]


def test_candles_by_composite(auth_client: APIClient, store, future: Instrument):
    storage.write(future, make_candles("2024-06-03", 5))
    resp = auth_client.get(
        "/api/candles/",
        {
            "exchange": "NFO",
            "symbol": "NIFTY",
            "instrument_type": "FUTURE",
            "expiry": EXPIRY.isoformat(),
            "interval": "day",
            "start": "2024-06-03T00:00:00+05:30",
            "end": "2024-06-04T00:00:00+05:30",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


def test_candles_rejects_oversized_range(auth_client: APIClient, future: Instrument):
    resp = auth_client.get(
        "/api/candles/",
        {
            "key": future.key,
            "interval": "1minute",
            "start": "2024-01-01T00:00:00+05:30",
            "end": "2024-02-01T00:00:00+05:30",
        },
    )
    assert resp.status_code == 400


def test_candles_unknown_key(auth_client: APIClient, db):
    resp = auth_client.get(
        "/api/candles/",
        {
            "key": "NSE:NOPE:EQUITY",
            "start": "2024-06-03T00:00:00+05:30",
            "end": "2024-06-04T00:00:00+05:30",
        },
    )
    assert resp.status_code == 404


def test_futures_chain_metadata_only(auth_client: APIClient, nifty: Instrument, future: Instrument):
    # Outside coverage — must not appear.
    Instrument.objects.create(
        instrument_type=InstrumentType.FUTURE,
        exchange=Exchange.NFO,
        symbol="NIFTY",
        underlying=nifty,
        expiry=EXPIRY + timedelta(days=28),
        data_start=DAY + timedelta(days=30),
        data_end=DAY + timedelta(days=40),
    )
    resp = auth_client.get(
        "/api/chains/futures/",
        {"underlying": "NIFTY", "exchange": "NSE", "date": DAY.isoformat()},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["underlying"] == nifty.key
    assert body["count"] == 1
    row = body["contracts"][0]
    assert row["key"] == future.key
    assert row["expiry"] == EXPIRY.isoformat()
    assert set(row) <= {
        "key",
        "instrument_type",
        "exchange",
        "symbol",
        "expiry",
        "strike",
        "option_type",
        "data_start",
        "data_end",
    }
    assert "candles" not in body
    assert "open" not in row


def test_options_chain_requires_expiry_and_filters(
    auth_client: APIClient, nifty: Instrument, call: Instrument, put: Instrument
):
    other_expiry = EXPIRY + timedelta(days=7)
    Instrument.objects.create(
        instrument_type=InstrumentType.OPTION,
        exchange=Exchange.NFO,
        symbol="NIFTY",
        underlying=nifty,
        expiry=other_expiry,
        strike=Decimal("22000"),
        option_type=OptionType.CE,
        data_start=DAY,
        data_end=DAY,
    )

    missing = auth_client.get(
        "/api/chains/options/",
        {"underlying": "NIFTY", "exchange": "NSE", "date": DAY.isoformat()},
    )
    assert missing.status_code == 400

    resp = auth_client.get(
        "/api/chains/options/",
        {
            "underlying": "NIFTY",
            "exchange": "NSE",
            "date": DAY.isoformat(),
            "expiry": EXPIRY.isoformat(),
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    keys = {c["key"] for c in body["contracts"]}
    assert keys == {call.key, put.key}


def test_chains_require_api_key(client: APIClient, api_key: str, nifty: Instrument):
    resp = client.get(
        "/api/chains/futures/",
        {"underlying": "NIFTY", "exchange": "NSE", "date": DAY.isoformat()},
    )
    assert resp.status_code == 401
