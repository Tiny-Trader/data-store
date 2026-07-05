"""Ingestion tests with a mocked broker (no tt-connect session required)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command

from candles import storage
from catalog.enums import Exchange, InstrumentType
from catalog.models import Instrument
from ingestion.eod import resolve_targets, run_eod
from ingestion.models import Watchlist
from ingestion.normalize import candles_to_frame

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 7, 3)


@dataclass
class FakeCandle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    oi: int | None = None


@dataclass
class FakeFuture:
    exchange: str
    symbol: str
    expiry: date


@dataclass
class FakeOption:
    exchange: str
    symbol: str
    expiry: date
    strike: float
    option_type: str


class FakeBroker:
    """Stand-in for TTBroker exposing just the calls eod.py uses."""

    def __init__(
        self, *, candles=None, futures=None, expiries=None, options=None,
        fail_keys=None, fail_times=None,
    ):
        self._candles = candles if candles is not None else []
        self._futures = futures or []
        self._expiries = expiries or []
        self._options = options or {}
        self.fail_keys = set(fail_keys or [])
        self.fail_times = dict(fail_times or {})
        self.fetched: list[str] = []

    def historical_1m(self, instrument, day):
        key = instrument.key
        self.fetched.append(key)
        if key in self.fail_keys:
            raise RuntimeError(f"boom {key}")
        if self.fail_times.get(key, 0) > 0:
            self.fail_times[key] -= 1
            raise RuntimeError(f"transient {key}")
        return list(self._candles)

    def futures(self, underlying):
        return list(self._futures)

    def expiries(self, underlying):
        return list(self._expiries)

    def options(self, underlying, expiry):
        return list(self._options.get(expiry, []))


def _candles(n: int) -> list[FakeCandle]:
    base = datetime(2026, 7, 3, 9, 15, tzinfo=IST)
    return [
        FakeCandle(base + timedelta(minutes=i), 100 + i, 100 + i, 100 + i, 100 + i, 1, 1000 + i)
        for i in range(n)
    ]


# --- normalize --------------------------------------------------------------


def test_candles_to_frame_maps_fields():
    frame = candles_to_frame(_candles(3))
    assert list(frame.columns) == ["ts", "open", "high", "low", "close", "volume", "oi"]
    assert frame.loc[0, "close"] == 100
    assert frame.loc[2, "oi"] == 1002


def test_candles_to_frame_empty():
    frame = candles_to_frame([])
    assert frame.empty
    assert list(frame.columns) == ["ts", "open", "high", "low", "close", "volume", "oi"]


# --- eod: equity flow -------------------------------------------------------


@pytest.mark.django_db
def test_run_eod_writes_equity(store):
    inst = Instrument.objects.create(
        instrument_type=InstrumentType.EQUITY, exchange=Exchange.NSE, symbol="RELIANCE"
    )
    Watchlist.objects.create(underlying=inst, track_equity=True)

    broker = FakeBroker(candles=_candles(5))
    stats = run_eod(broker, DAY)

    assert stats["written"] == 1
    assert stats["rows"] == 5
    assert storage.read_raw(inst, DAY.year, DAY.year).shape[0] == 5

    inst.refresh_from_db()
    assert inst.data_start == DAY
    assert inst.data_end == DAY


@pytest.mark.django_db
def test_run_eod_skips_already_present(store):
    inst = Instrument.objects.create(
        instrument_type=InstrumentType.EQUITY, exchange=Exchange.NSE, symbol="RELIANCE"
    )
    Watchlist.objects.create(underlying=inst, track_equity=True)
    broker = FakeBroker(candles=_candles(5))

    run_eod(broker, DAY)
    stats = run_eod(broker, DAY)

    # Second run resumes: day already stored, so it is skipped (not re-fetched).
    assert stats["existing"] == 1
    assert stats["written"] == 0
    assert broker.fetched == [inst.key]  # fetched exactly once across both runs


@pytest.mark.django_db
def test_run_eod_skips_empty(store):
    inst = Instrument.objects.create(
        instrument_type=InstrumentType.EQUITY, exchange=Exchange.NSE, symbol="TCS"
    )
    Watchlist.objects.create(underlying=inst, track_equity=True)

    stats = run_eod(FakeBroker(candles=[]), DAY)

    assert stats["written"] == 0
    assert stats["empty"] == 1


@pytest.mark.django_db
def test_run_eod_ignores_inactive(store):
    inst = Instrument.objects.create(
        instrument_type=InstrumentType.EQUITY, exchange=Exchange.NSE, symbol="INFY"
    )
    Watchlist.objects.create(underlying=inst, track_equity=True, is_active=False)

    stats = run_eod(FakeBroker(candles=_candles(3)), DAY)

    assert stats["written"] == 0
    assert stats["total"] == 0


# --- eod: F&O expansion -----------------------------------------------------


@pytest.mark.django_db
def test_resolve_options_bounded():
    u = Instrument.objects.create(
        instrument_type=InstrumentType.INDEX, exchange=Exchange.NSE, symbol="NIFTY"
    )
    entry = Watchlist.objects.create(
        underlying=u, track_options=True, n_expiries=1, strike_window=1
    )
    near = date(2026, 7, 31)
    far = date(2026, 8, 28)
    opts = [
        FakeOption("NFO", "NIFTY", near, float(s), ot)
        for s in (90, 95, 100, 105, 110)
        for ot in ("CE", "PE")
    ]
    broker = FakeBroker(expiries=[near, far], options={near: opts})

    targets = resolve_targets(entry, broker, DAY)

    # median strike 100 is ATM; window 1 -> {95, 100, 105}, CE+PE each.
    assert sorted({float(t.strike) for t in targets}) == [95.0, 100.0, 105.0]
    assert len(targets) == 6
    assert all(t.is_tracked for t in targets)
    assert all(t.underlying_id == u.id for t in targets)
    assert all(t.expiry == near for t in targets)  # only nearest expiry pulled


@pytest.mark.django_db
def test_resolve_futures_nearest():
    u = Instrument.objects.create(
        instrument_type=InstrumentType.EQUITY, exchange=Exchange.NSE, symbol="SBIN"
    )
    entry = Watchlist.objects.create(underlying=u, track_futures=True, n_expiries=2)
    exps = [date(2026, 7, 31), date(2026, 8, 28), date(2026, 9, 25)]
    broker = FakeBroker(futures=[FakeFuture("NFO", "SBIN", e) for e in exps])

    targets = resolve_targets(entry, broker, DAY)

    assert [t.expiry for t in targets] == exps[:2]
    assert all(t.instrument_type == InstrumentType.FUTURE for t in targets)


@pytest.mark.django_db
def test_run_eod_retries_then_succeeds(store, monkeypatch):
    monkeypatch.setattr("ingestion.eod.time.sleep", lambda _s: None)
    inst = Instrument.objects.create(
        instrument_type=InstrumentType.EQUITY, exchange=Exchange.NSE, symbol="RELIANCE"
    )
    Watchlist.objects.create(underlying=inst, track_equity=True)
    broker = FakeBroker(candles=_candles(3), fail_times={inst.key: 2})

    stats = run_eod(broker, DAY, retries=3)

    assert stats["written"] == 1
    assert broker.fetched == [inst.key] * 3  # two failures + one success


@pytest.mark.django_db
def test_run_eod_isolates_failures(store, monkeypatch):
    monkeypatch.setattr("ingestion.eod.time.sleep", lambda _s: None)
    good = Instrument.objects.create(
        instrument_type=InstrumentType.EQUITY, exchange=Exchange.NSE, symbol="TCS"
    )
    bad = Instrument.objects.create(
        instrument_type=InstrumentType.EQUITY, exchange=Exchange.NSE, symbol="INFY"
    )
    Watchlist.objects.create(underlying=good, track_equity=True)
    Watchlist.objects.create(underlying=bad, track_equity=True)
    broker = FakeBroker(candles=_candles(3), fail_keys={bad.key})

    stats = run_eod(broker, DAY, retries=2)

    assert stats["written"] == 1
    assert stats["failed"] == 1
    assert stats["failed_keys"] == [bad.key]


@pytest.mark.django_db
def test_seed_watchlist_is_idempotent():
    call_command("seed_watchlist")
    first = Watchlist.objects.count()
    call_command("seed_watchlist")

    assert Watchlist.objects.count() == first
    assert first > 50  # 50+ stocks + NIFTY + SENSEX
    nifty = Watchlist.objects.get(underlying__symbol="NIFTY")
    assert nifty.track_futures and nifty.track_options
    sensex = Watchlist.objects.get(underlying__symbol="SENSEX")
    assert sensex.underlying.exchange == Exchange.BSE


@pytest.mark.django_db
def test_seed_watchlist_reconciles_off_roster():
    stale = Instrument.objects.create(
        instrument_type=InstrumentType.EQUITY, exchange=Exchange.NSE, symbol="ZZZDELISTED"
    )
    Watchlist.objects.create(underlying=stale, track_equity=True, is_active=True)

    call_command("seed_watchlist")

    assert Watchlist.objects.get(underlying=stale).is_active is False
    assert Watchlist.objects.get(underlying__symbol="RELIANCE").is_active is True
    assert Watchlist.objects.get(underlying__symbol="NIFTY").is_active is True  # index untouched


@pytest.mark.django_db
def test_upsert_is_idempotent():
    u = Instrument.objects.create(
        instrument_type=InstrumentType.EQUITY, exchange=Exchange.NSE, symbol="SBIN"
    )
    entry = Watchlist.objects.create(underlying=u, track_futures=True, n_expiries=2)
    broker = FakeBroker(futures=[FakeFuture("NFO", "SBIN", date(2026, 7, 31))])

    resolve_targets(entry, broker, DAY)
    resolve_targets(entry, broker, DAY)

    assert Instrument.objects.filter(instrument_type=InstrumentType.FUTURE).count() == 1
