"""Parquet candle storage layer.

Stores 1-minute OHLCV(+OI) candles as the single source of truth and derives
coarser intervals on read via DuckDB. Storage identity lives in the file path;
the ``catalog`` app is the index. See ``paths`` for the on-disk layout.
"""
