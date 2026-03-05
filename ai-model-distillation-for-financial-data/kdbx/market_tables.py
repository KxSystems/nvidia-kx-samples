# SPDX-FileCopyrightText: Copyright (c) 2026 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""KDB-X financial market table definitions and data loading.

Defines 4 tables for the Phase 2 financial analytics demo and provides
a Parquet loader for bulk-inserting market data.

Tables
------
market_ticks      -- 1-minute OHLCV bars
order_book        -- bid/ask snapshots
signals           -- model trading signals
backtest_results  -- backtest run metrics
"""

from __future__ import annotations

import logging

import pandas as pd
import pykx as kx

from kdbx.connection import pykx_connection
from kdbx.schema import flip_ddl

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table names (canonical order)
# ---------------------------------------------------------------------------

MARKET_TABLE_NAMES: list[str] = [
    "market_ticks",
    "order_book",
    "signals",
    "backtest_results",
]

# ---------------------------------------------------------------------------
# DDL statements
# ---------------------------------------------------------------------------

_MARKET_TABLE_DDL: dict[str, str] = {
    "market_ticks": flip_ddl("market_ticks", [
        ("sym", "`symbol$()"), ("timestamp", "`timestamp$()"),
        ("open", "`float$()"), ("high", "`float$()"), ("low", "`float$()"),
        ("close", "`float$()"), ("volume", "`long$()"), ("vwap", "`float$()"),
        ("trade_count", "`long$()"), ("source", "`symbol$()"),
    ]),
    "order_book": flip_ddl("order_book", [
        ("sym", "`symbol$()"), ("timestamp", "`timestamp$()"),
        ("bid_price", "`float$()"), ("bid_size", "`long$()"),
        ("ask_price", "`float$()"), ("ask_size", "`long$()"),
        ("mid", "`float$()"), ("spread", "`float$()"),
    ]),
    "signals": flip_ddl("signals", [
        ("signal_id", "`symbol$()"), ("timestamp", "`timestamp$()"),
        ("sym", "`symbol$()"), ("direction", "`symbol$()"),
        ("confidence", "`float$()"), ("model_id", "`symbol$()"),
        ("rationale", "()"), ("realized_pnl", "`float$()"),
        ("realized_at", "`timestamp$()"),
    ]),
    "backtest_results": flip_ddl("backtest_results", [
        ("run_id", "`symbol$()"), ("timestamp", "`timestamp$()"),
        ("model_id", "`symbol$()"), ("sharpe", "`float$()"),
        ("max_drawdown", "`float$()"), ("total_return", "`float$()"),
        ("win_rate", "`float$()"), ("n_trades", "`long$()"),
        ("params", "()"),
    ]),
}

# ---------------------------------------------------------------------------
# Per-table valid column sets
# ---------------------------------------------------------------------------

MARKET_VALID_COLUMNS: dict[str, frozenset[str]] = {
    "market_ticks": frozenset({
        "sym", "timestamp", "open", "high", "low", "close",
        "volume", "vwap", "trade_count", "source",
    }),
    "order_book": frozenset({
        "sym", "timestamp", "bid_price", "bid_size",
        "ask_price", "ask_size", "mid", "spread",
    }),
    "signals": frozenset({
        "signal_id", "timestamp", "sym", "direction", "confidence",
        "model_id", "rationale", "realized_pnl", "realized_at",
    }),
    "backtest_results": frozenset({
        "run_id", "timestamp", "model_id", "sharpe", "max_drawdown",
        "total_return", "win_rate", "n_trades", "params",
    }),
}


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------


def create_market_tables(drop_existing: bool = False) -> None:
    """Create all 4 financial market tables.

    Parameters
    ----------
    drop_existing : bool
        If ``True``, drop each table before recreating it.
    """
    with pykx_connection() as q:
        existing = q("tables[]")
        try:
            existing_names = [str(t) for t in existing]
        except TypeError:
            existing_names = []

        for name in MARKET_TABLE_NAMES:
            if name in existing_names:
                if drop_existing:
                    logger.info("Dropping existing table: %s", name)
                    q(f"delete {name} from `.")
                else:
                    logger.info("Table %s already exists, skipping", name)
                    continue

            logger.info("Creating table: %s", name)
            q(_MARKET_TABLE_DDL[name])

        logger.info("All %d market tables ready", len(MARKET_TABLE_NAMES))


# ---------------------------------------------------------------------------
# Parquet data loading
# ---------------------------------------------------------------------------

# Columns for each target table
_TICK_COLS = ["sym", "timestamp", "open", "high", "low", "close", "volume", "vwap", "trade_count"]
_BOOK_COLS = ["sym", "timestamp", "bid_price", "bid_size", "ask_price", "ask_size", "mid", "spread"]


def load_parquet_data(parquet_path: str) -> dict[str, int]:
    """Load market data from a Parquet file into KDB-X tables.

    Splits the Parquet into ``market_ticks`` and ``order_book`` columns
    and batch-inserts via ``kx.toq()``.

    Parameters
    ----------
    parquet_path : str
        Path to the Parquet file produced by ``generate_sample_data.py``.

    Returns
    -------
    dict[str, int]
        Row counts per table: ``{"market_ticks": N, "order_book": N}``.
    """
    df = pd.read_parquet(parquet_path)
    logger.info("Read %d rows from %s", len(df), parquet_path)

    # --- market_ticks ---
    ticks = df[_TICK_COLS].copy()
    ticks["source"] = "generated"
    # Sort by sym+timestamp so s# (sorted attribute) succeeds and aj gets
    # optimal performance (sym ascending, timestamp ascending within each sym)
    ticks = ticks.sort_values(["sym", "timestamp"]).reset_index(drop=True)

    # --- order_book ---
    book = df[_BOOK_COLS].copy()
    book = book.sort_values(["sym", "timestamp"]).reset_index(drop=True)

    with pykx_connection() as q:
        # Batch insert market_ticks using typed vectors (unlicensed IPC mode)
        q(
            "{[s;ts;o;h;l;c;v;vw;tc;src] `market_ticks insert flip `sym`timestamp`open`high`low`close`volume`vwap`trade_count`source!(s;ts;o;h;l;c;v;vw;tc;src)}",
            kx.SymbolVector(ticks["sym"].tolist()),
            kx.TimestampVector(ticks["timestamp"].tolist()),
            kx.toq(ticks["open"].values),
            kx.toq(ticks["high"].values),
            kx.toq(ticks["low"].values),
            kx.toq(ticks["close"].values),
            kx.toq(ticks["volume"].values),
            kx.toq(ticks["vwap"].values),
            kx.toq(ticks["trade_count"].values),
            kx.SymbolVector(ticks["source"].tolist()),
        )
        # Apply sorted attribute on sym for fast aj lookups
        q("update `s#sym from `market_ticks")
        tick_count = int(q("count market_ticks").py())
        logger.info("Inserted %d rows into market_ticks", tick_count)

        # Batch insert order_book using typed vectors (unlicensed IPC mode)
        q(
            "{[s;ts;bp;bs;ap;as;m;sp] `order_book insert flip `sym`timestamp`bid_price`bid_size`ask_price`ask_size`mid`spread!(s;ts;bp;bs;ap;as;m;sp)}",
            kx.SymbolVector(book["sym"].tolist()),
            kx.TimestampVector(book["timestamp"].tolist()),
            kx.toq(book["bid_price"].values),
            kx.toq(book["bid_size"].values),
            kx.toq(book["ask_price"].values),
            kx.toq(book["ask_size"].values),
            kx.toq(book["mid"].values),
            kx.toq(book["spread"].values),
        )
        q("update `s#sym from `order_book")
        book_count = int(q("count order_book").py())
        logger.info("Inserted %d rows into order_book", book_count)

    return {"market_ticks": tick_count, "order_book": book_count}
