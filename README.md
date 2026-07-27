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
- `tt-connect` (git dependency) for broker-backed discovery and candle pulls

## Setup

```bash
cd data-store
poetry env use "$(pyenv which python)"
poetry install
cp .env.example .env        # broker creds: TT_<BROKER>_CONFIG JSON blobs
make migrate
make run                    # http://localhost:8000/admin/
```

Create an admin user to browse the catalog:

```bash
make superuser
```

Seed the tracked universe (NIFTY50 equities + NIFTY/SENSEX F&O), then sync a day:

```bash
poetry run python manage.py seed_watchlist
poetry run python manage.py sync_eod --date YYYY-MM-DD --broker angelone
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
├── candles/           # Parquet paths, schema, write, DuckDB read/resample
├── ingestion/         # Watchlist, tt-connect bridge, EOD sync
├── scripts/           # One-off backfill (not part of the daily job)
├── deploy/systemd/    # Weekday EOD timer (18:30 IST)
└── manage.py
```

## Catalog model

`Instrument` mirrors `tt-connect`'s canonical fields (exchange, symbol, segment,
lot/tick size, expiry, strike, option_type) and adds the lifecycle columns
`tt-connect` omits: `is_tracked`, `status` (expired F&O rows are retained),
and data-availability lineage (`data_start`, `data_end`, `data_gaps`). Each row
has a deterministic `key` (e.g. `NFO:NIFTY:OPTION:2026-01-29:22000:CE`) so syncs
are idempotent. `BrokerToken` maps an instrument to per-broker tokens/symbols.

## Parquet candle layer

`candles/` stores 1-minute OHLCV(+OI) as the single source of truth and derives
coarser intervals on read.

- **Layout** (`candles/paths.py`): one root, identity encoded in the path.
  Equity/index partition by year; F&O contracts get one readable file each
  (`options/{underlying}/{expiry}/{strike}_{CE|PE}.parquet`).
- **Writes** (`candles/storage.py`): atomic (temp file + swap), idempotent
  (dedupe on `ts`, last wins), equity rows split per year.
- **Reads** (`candles/reader.py`): DuckDB over Parquet with predicate pushdown;
  intervals derived via `time_bucket` anchored to the 09:15 IST session open, so
  30-/60-minute candles match broker conventions. Volume sums; OI takes the last
  value in the bucket (a level, not a flow).

## Ingestion (EOD)

Tracking is declared at the **underlying** level via `Watchlist` (admin-editable
or `seed_watchlist`). The daily job expands each entry at run time into concrete
contracts — nearest `n_expiries` and, for options, ATM ± `strike_window` strikes
(ATM ≈ median listed strike) — so F&O rolls need no hand-managed contract list.

`sync_eod` fetches one trading day of 1-minute candles via `tt-connect`, writes
through the broker-agnostic Parquet layer, and updates `data_start`/`data_end`.
It is paced, retried with backoff, and resumable (already-stored instrument-days
are skipped unless `--force`). Schedule: `deploy/systemd/` (Mon–Fri 18:30 IST).

## Chains

Option/future chains are a **view, not a separate store**. The contract roster
lives in the `catalog` (one `Instrument` per contract, queryable by underlying +
expiry); per-strike OHLCV/OI over time lives in the candle layer. "The chain on
date D" is therefore the catalog roster intersected with candles at D — nothing
extra is persisted. (Candles carry OHLCV+OI only; if bid/ask/IV/greeks are ever
needed, that would be a separate product.)

## Backfill & data sources

Ongoing updates are the EOD job above. Historical backfill is a **manual**
operation (`scripts/backfill_candles.py`), chunked for broker per-request limits.
Backfill data may also be **purchased/uploaded**. Sources are **complementary —
they fill gaps, not overwrite each other** (this is a backtesting store, not a
professional-grade multi-source feed), so no per-candle provenance or conflict
resolution is tracked. Because `storage.write()` is broker-agnostic (it takes a
plain frame), vendor uploads and broker pulls share the same write path.
Coverage/gaps are derived from stored data when needed rather than tracked in a
separate ledger.

## Status

In place: IST-aware settings, durable catalog + admin, Parquet candle layer
(write + DuckDB read/resample), watchlist + `tt-connect` EOD ingestion,
backfill script, systemd scheduling, and tests.

Not yet built: purchased-data upload path, chain view helper, and REST API
endpoints for consumers.
