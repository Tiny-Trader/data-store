"""Lookup helpers for candles and chain endpoints."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from rest_framework.exceptions import NotFound, ValidationError

from candles.intervals import Interval
from catalog.enums import InstrumentType
from catalog.models import Instrument

IST = ZoneInfo("Asia/Kolkata")

# Max [start, end) span by interval — keeps JSON responses bounded.
_MAX_SPAN: dict[Interval, timedelta] = {
    Interval.MINUTE_1: timedelta(days=5),
    Interval.MINUTE_3: timedelta(days=15),
    Interval.MINUTE_5: timedelta(days=30),
    Interval.MINUTE_10: timedelta(days=30),
    Interval.MINUTE_15: timedelta(days=60),
    Interval.MINUTE_30: timedelta(days=90),
    Interval.HOUR_1: timedelta(days=180),
    Interval.DAY: timedelta(days=365 * 5),
}


def parse_day(raw: str | None, *, field: str = "date") -> date:
    if not raw:
        raise ValidationError({field: "required (YYYY-MM-DD)"})
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValidationError({field: "invalid date, expected YYYY-MM-DD"}) from exc


def parse_datetime(raw: str | None, *, field: str) -> datetime:
    if not raw:
        raise ValidationError({field: "required (ISO-8601 datetime)"})
    # Query strings decode "+" as space, so "+05:30" often arrives as " 05:30".
    normalized = raw.strip().replace("Z", "+00:00")
    if " " in normalized and "+" not in normalized[10:]:
        normalized = normalized.replace(" ", "+", 1)
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValidationError({field: "invalid datetime, expected ISO-8601"}) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt


def parse_interval(raw: str | None) -> Interval:
    value = raw or Interval.DAY.value
    try:
        return Interval(value)
    except ValueError as exc:
        allowed = ", ".join(i.value for i in Interval)
        raise ValidationError({"interval": f"invalid; allowed: {allowed}"}) from exc


def check_range(interval: Interval, start: datetime, end: datetime) -> None:
    if end <= start:
        raise ValidationError({"end": "must be after start"})
    max_span = _MAX_SPAN[interval]
    if end - start > max_span:
        raise ValidationError(
            {
                "end": (
                    f"range too large for interval {interval.value}; "
                    f"max span is {max_span.days} days"
                )
            }
        )


def resolve_instrument(params: dict[str, str | None]) -> Instrument:
    """Resolve by ``key`` or by canonical composite fields."""
    key = (params.get("key") or "").strip()
    if key:
        try:
            return Instrument.objects.get(key=key)
        except Instrument.DoesNotExist as exc:
            raise NotFound("instrument not found") from exc

    exchange = (params.get("exchange") or "").strip()
    symbol = (params.get("symbol") or "").strip()
    itype = (params.get("instrument_type") or "").strip()
    if not (exchange and symbol and itype):
        raise ValidationError(
            {
                "detail": (
                    "provide key=… or exchange + symbol + instrument_type "
                    "(plus expiry/strike/option_type for F&O)"
                )
            }
        )

    filters: dict[str, object] = {
        "exchange": exchange,
        "symbol": symbol,
        "instrument_type": itype,
    }

    expiry_raw = (params.get("expiry") or "").strip()
    if expiry_raw:
        filters["expiry"] = parse_day(expiry_raw, field="expiry")
    elif itype in {InstrumentType.FUTURE, InstrumentType.OPTION}:
        raise ValidationError({"expiry": "required for futures/options"})

    if itype == InstrumentType.OPTION:
        strike_raw = (params.get("strike") or "").strip()
        option_type = (params.get("option_type") or "").strip()
        if not strike_raw or not option_type:
            raise ValidationError({"detail": "strike and option_type required for options"})
        try:
            filters["strike"] = Decimal(strike_raw)
        except InvalidOperation as exc:
            raise ValidationError({"strike": "invalid decimal"}) from exc
        filters["option_type"] = option_type

    try:
        return Instrument.objects.get(**filters)
    except Instrument.DoesNotExist as exc:
        raise NotFound("instrument not found") from exc
    except Instrument.MultipleObjectsReturned as exc:
        raise ValidationError({"detail": "ambiguous instrument; use key="}) from exc


def resolve_underlying(symbol: str | None, exchange: str | None) -> Instrument:
    if not symbol or not exchange:
        raise ValidationError({"detail": "underlying and exchange are required"})
    qs = Instrument.objects.filter(
        symbol=symbol.strip(),
        exchange=exchange.strip(),
        instrument_type__in=[InstrumentType.EQUITY, InstrumentType.INDEX],
    )
    try:
        return qs.get()
    except Instrument.DoesNotExist as exc:
        raise NotFound("underlying not found") from exc
    except Instrument.MultipleObjectsReturned as exc:
        raise ValidationError({"detail": "ambiguous underlying"}) from exc


def chain_contracts(
    underlying: Instrument,
    itype: str,
    day: date,
    *,
    expiry: date | None = None,
) -> list[Instrument]:
    """Catalog contracts for ``underlying`` with coverage spanning ``day``."""
    qs = Instrument.objects.filter(
        underlying=underlying,
        instrument_type=itype,
        data_start__isnull=False,
        data_end__isnull=False,
        data_start__lte=day,
        data_end__gte=day,
    )
    if expiry is not None:
        qs = qs.filter(expiry=expiry)
    return list(qs.order_by("expiry", "strike", "option_type", "symbol"))


def serialize_contract(inst: Instrument) -> dict[str, object]:
    return {
        "key": inst.key,
        "instrument_type": inst.instrument_type,
        "exchange": inst.exchange,
        "symbol": inst.symbol,
        "expiry": inst.expiry.isoformat() if inst.expiry else None,
        "strike": str(inst.strike) if inst.strike is not None else None,
        "option_type": inst.option_type or None,
        "data_start": inst.data_start.isoformat() if inst.data_start else None,
        "data_end": inst.data_end.isoformat() if inst.data_end else None,
    }
