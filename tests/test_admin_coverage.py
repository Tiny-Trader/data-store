"""Admin coverage helpers and typed instrument changelists."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from catalog.coverage import coverage_summary, type_coverage
from catalog.enums import Exchange, InstrumentType, OptionType
from catalog.models import Instrument
from ingestion.models import Watchlist

DAY = date(2024, 6, 3)
EXPIRY = date(2024, 6, 27)


@pytest.fixture
def admin_user(db):
    User = get_user_model()
    return User.objects.create_superuser("admin", "a@b.co", "pass")


@pytest.fixture
def admin_client(admin_user) -> Client:
    client = Client()
    client.force_login(admin_user)
    return client


@pytest.fixture
def seeded(db) -> dict[str, Instrument]:
    nifty = Instrument.objects.create(
        instrument_type=InstrumentType.INDEX,
        exchange=Exchange.NSE,
        symbol="NIFTY",
        is_tracked=True,
        data_start=DAY,
        data_end=DAY,
    )
    equity = Instrument.objects.create(
        instrument_type=InstrumentType.EQUITY,
        exchange=Exchange.NSE,
        symbol="RELIANCE",
        is_tracked=True,
        data_start=DAY,
        data_end=DAY,
    )
    fut = Instrument.objects.create(
        instrument_type=InstrumentType.FUTURE,
        exchange=Exchange.NFO,
        symbol="NIFTY",
        underlying=nifty,
        expiry=EXPIRY,
        is_tracked=True,
        data_start=DAY,
        data_end=DAY,
    )
    call = Instrument.objects.create(
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
    empty_put = Instrument.objects.create(
        instrument_type=InstrumentType.OPTION,
        exchange=Exchange.NFO,
        symbol="NIFTY",
        underlying=nifty,
        expiry=EXPIRY,
        strike=Decimal("22100"),
        option_type=OptionType.PE,
        is_tracked=True,
    )
    Watchlist.objects.create(
        underlying=nifty,
        track_equity=True,
        track_futures=True,
        track_options=True,
        is_active=True,
    )
    Watchlist.objects.create(
        underlying=equity,
        track_equity=True,
        is_active=True,
    )
    return {
        "nifty": nifty,
        "equity": equity,
        "fut": fut,
        "call": call,
        "empty_put": empty_put,
    }


def test_type_coverage_counts(seeded):
    rows = {r.instrument_type: r for r in type_coverage()}
    assert rows["OPTION"].tracked == 2
    assert rows["OPTION"].with_data == 1
    assert rows["OPTION"].empty == 1
    assert rows["INDEX"].with_data == 1


def test_coverage_summary_fno_only_for_fno_watchlist(seeded):
    summary = coverage_summary()
    assert summary["tracked"] == 5
    assert summary["with_data"] == 4
    assert summary["empty"] == 1
    assert summary["watchlist_active"] == 2
    fno = summary["fno"]
    assert len(fno) == 1
    assert fno[0].symbol == "NIFTY"
    assert fno[0].options_tracked == 2
    assert fno[0].options_with_data == 1
    assert fno[0].options_empty == 1


def test_admin_index_shows_coverage(admin_client: Client, seeded):
    resp = admin_client.get("/admin/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Coverage" in body
    assert "NIFTY" in body
    assert "empty" in body.lower()


def test_option_changelist_filters_empty(admin_client: Client, seeded):
    resp = admin_client.get("/admin/catalog/optioninstrument/", {"has_data": "no"})
    assert resp.status_code == 200
    body = resp.content.decode()
    assert seeded["empty_put"].key in body
    assert seeded["call"].key not in body


def test_watchlist_changelist_rollups(admin_client: Client, seeded):
    resp = admin_client.get("/admin/ingestion/watchlist/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "1/2" in body  # options with_data/total for NIFTY
    assert "1/1" in body  # futures
