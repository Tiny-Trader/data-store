"""Canonical enums, mirrored from tt-connect so identifiers line up.

Values here must match ``tt_connect.core.models.enums`` exactly. data-store owns
its own durable catalog, but keeps the same canonical vocabulary (exchange codes,
option types) to avoid drift with the ingestion-time resolver.
"""

from django.db import models


class Exchange(models.TextChoices):
    NSE = "NSE", "NSE"
    BSE = "BSE", "BSE"
    NFO = "NFO", "NSE F&O"
    BFO = "BFO", "BSE F&O"
    CDS = "CDS", "Currency Derivatives"
    MCX = "MCX", "Commodity"


class InstrumentType(models.TextChoices):
    EQUITY = "EQUITY", "Equity"
    INDEX = "INDEX", "Index"
    FUTURE = "FUTURE", "Future"
    OPTION = "OPTION", "Option"
    CURRENCY = "CURRENCY", "Currency"
    COMMODITY = "COMMODITY", "Commodity"


class OptionType(models.TextChoices):
    CE = "CE", "Call"
    PE = "PE", "Put"


class Status(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"
    EXPIRED = "EXPIRED", "Expired"
