# data-store

Historical (t-1) market data store for tiny-trader. Stores OHLCV candles for a
curated set of equity and F&O symbols and serves them over a REST API for
backtesting. Data is sourced through [`tt-connect`](../tt-connect), not broker
SDKs directly.

- **Instrument/contract catalog** lives in a relational DB (SQLite in dev).
- **Candle/OHLCV data** is stored in Parquet files under `PARQUET_ROOT`.
- Runs as a standalone service on its own server, so consumers fetch over HTTP.

See the repo-root `AGENTS.md` for the design rationale (notably: data-store owns
its durable catalog; `tt-connect` is the ingestion-time resolver).

## Stack

- Python 3.14 (pinned via `.python-version`; managed with pyenv)
- Django 6.0 + Django REST Framework
- Poetry for dependency management

## Setup

```bash
cd data-store
poetry env use "$(pyenv which python)"
poetry install
cp .env.example .env        # then edit as needed
make migrate
make run                    # http://localhost:8000/admin/
```

Create an admin user to browse the catalog:

```bash
make superuser
```

## Commands

```bash
make lint         # ruff check
make format       # ruff format
make check        # django system checks
make test         # pytest
make migrations   # makemigrations
make migrate      # apply migrations
make run          # dev server
```

## Layout

```text
data-store/
├── config/            # Django project (settings, urls, wsgi/asgi)
├── catalog/           # Instrument/contract catalog (system of record)
│   ├── enums.py       # canonical enums mirrored from tt-connect
│   ├── models.py      # Instrument, BrokerToken
│   └── admin.py
└── manage.py
```

## Catalog model

`Instrument` mirrors `tt-connect`'s canonical fields (exchange, symbol, segment,
lot/tick size, expiry, strike, option_type) and adds the lifecycle columns
`tt-connect` omits: `is_tracked`, `status` (expired F&O rows are retained),
and data-availability lineage (`data_start`, `data_end`, `data_gaps`). Each row
has a deterministic `key` (e.g. `NFO:NIFTY:OPTION:2026-01-29:22000:CE`) so syncs
are idempotent. `BrokerToken` maps an instrument to per-broker tokens/symbols.

## Status

Early scaffold. In place: project skeleton, IST-aware settings, the durable
instrument catalog, and admin.

Not yet built: `tt-connect`-backed ingestion (candles + chains), Parquet
read/write, REST API endpoints, and scheduling.
