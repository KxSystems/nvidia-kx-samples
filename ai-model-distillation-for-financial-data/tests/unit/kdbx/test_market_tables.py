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
"""Tests for kdbx.market_tables module.

Covers:
  - DDL strings contain expected column names
  - MARKET_VALID_COLUMNS match DDL definitions
  - create_market_tables() DDL execution, skip-existing, drop-existing
  - load_parquet_data() batch insert and sorted attribute application
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, call, patch

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fixture: mock q connection at the market_tables module level
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_q():
    """Patch ``pykx_connection`` and ``kx`` where market_tables.py uses them."""
    mock_conn = MagicMock(name="SyncQConnection")

    @contextmanager
    def _fake_ctx():
        yield mock_conn

    with (
        patch("kdbx.market_tables.pykx_connection", _fake_ctx),
        patch("kdbx.market_tables.kx") as mock_kx,
    ):
        mock_kx.SymbolAtom.side_effect = lambda v: ("SymbolAtom", v)
        mock_kx.SymbolVector.side_effect = lambda v: ("SymbolVector", list(v))
        mock_kx.FloatAtom.side_effect = lambda v: ("FloatAtom", v)
        mock_kx.toq.side_effect = lambda v: ("toq", v)
        yield mock_conn


# ---------------------------------------------------------------------------
# DDL content tests
# ---------------------------------------------------------------------------


class TestDDLDefinitions:
    """Verify that DDL strings contain expected columns."""

    def test_market_ticks_ddl_has_all_columns(self):
        from kdbx.market_tables import _MARKET_TABLE_DDL

        ddl = _MARKET_TABLE_DDL["market_ticks"]
        for col in ["sym", "timestamp", "open", "high", "low", "close",
                     "volume", "vwap", "trade_count", "source"]:
            assert col in ddl, f"Column {col!r} missing from market_ticks DDL"

    def test_order_book_ddl_has_all_columns(self):
        from kdbx.market_tables import _MARKET_TABLE_DDL

        ddl = _MARKET_TABLE_DDL["order_book"]
        for col in ["sym", "timestamp", "bid_price", "bid_size",
                     "ask_price", "ask_size", "mid", "spread"]:
            assert col in ddl, f"Column {col!r} missing from order_book DDL"

    def test_signals_ddl_has_all_columns(self):
        from kdbx.market_tables import _MARKET_TABLE_DDL

        ddl = _MARKET_TABLE_DDL["signals"]
        for col in ["signal_id", "timestamp", "sym", "direction", "confidence",
                     "model_id", "rationale", "realized_pnl", "realized_at"]:
            assert col in ddl, f"Column {col!r} missing from signals DDL"

    def test_backtest_results_ddl_has_all_columns(self):
        from kdbx.market_tables import _MARKET_TABLE_DDL

        ddl = _MARKET_TABLE_DDL["backtest_results"]
        for col in ["run_id", "timestamp", "model_id", "sharpe", "max_drawdown",
                     "total_return", "win_rate", "n_trades", "params"]:
            assert col in ddl, f"Column {col!r} missing from backtest_results DDL"

    def test_ddl_uses_flip_syntax(self):
        """All DDL statements use the flip-based syntax."""
        from kdbx.market_tables import _MARKET_TABLE_DDL

        for name, ddl in _MARKET_TABLE_DDL.items():
            assert ddl.startswith(f"{name}:flip"), \
                f"{name} DDL should start with '{name}:flip'"


# ---------------------------------------------------------------------------
# VALID_COLUMNS tests
# ---------------------------------------------------------------------------


class TestValidColumns:
    """Verify MARKET_VALID_COLUMNS match DDL definitions."""

    def test_market_ticks_columns_match(self):
        from kdbx.market_tables import MARKET_VALID_COLUMNS, _MARKET_TABLE_DDL

        ddl = _MARKET_TABLE_DDL["market_ticks"]
        for col in MARKET_VALID_COLUMNS["market_ticks"]:
            assert col in ddl, f"VALID_COLUMNS has {col!r} but DDL does not"

    def test_order_book_columns_match(self):
        from kdbx.market_tables import MARKET_VALID_COLUMNS, _MARKET_TABLE_DDL

        ddl = _MARKET_TABLE_DDL["order_book"]
        for col in MARKET_VALID_COLUMNS["order_book"]:
            assert col in ddl, f"VALID_COLUMNS has {col!r} but DDL does not"

    def test_signals_columns_match(self):
        from kdbx.market_tables import MARKET_VALID_COLUMNS, _MARKET_TABLE_DDL

        ddl = _MARKET_TABLE_DDL["signals"]
        for col in MARKET_VALID_COLUMNS["signals"]:
            assert col in ddl, f"VALID_COLUMNS has {col!r} but DDL does not"

    def test_backtest_results_columns_match(self):
        from kdbx.market_tables import MARKET_VALID_COLUMNS, _MARKET_TABLE_DDL

        ddl = _MARKET_TABLE_DDL["backtest_results"]
        for col in MARKET_VALID_COLUMNS["backtest_results"]:
            assert col in ddl, f"VALID_COLUMNS has {col!r} but DDL does not"

    def test_all_four_tables_present(self):
        from kdbx.market_tables import MARKET_VALID_COLUMNS

        expected = {"market_ticks", "order_book", "signals", "backtest_results"}
        assert set(MARKET_VALID_COLUMNS.keys()) == expected


# ---------------------------------------------------------------------------
# create_market_tables tests
# ---------------------------------------------------------------------------


class TestCreateMarketTables:
    """Tests for create_market_tables()."""

    def test_creates_all_tables_when_none_exist(self, mock_q):
        from kdbx.market_tables import MARKET_TABLE_NAMES, create_market_tables

        # tables[] returns empty list
        mock_q.return_value = MagicMock(__iter__=MagicMock(side_effect=TypeError))

        create_market_tables()

        # Should call tables[] once, then 4 DDL executions
        q_calls = [c.args[0] for c in mock_q.call_args_list]
        assert q_calls[0] == "tables[]"
        for name in MARKET_TABLE_NAMES:
            assert any(name in c for c in q_calls), \
                f"DDL for {name!r} not executed"

    def test_skips_existing_tables(self, mock_q):
        from kdbx.market_tables import create_market_tables

        # Pretend all 4 tables already exist
        mock_q.return_value = MagicMock(
            __iter__=lambda self: iter(["market_ticks", "order_book", "signals", "backtest_results"])
        )

        create_market_tables(drop_existing=False)

        q_calls = [c.args[0] for c in mock_q.call_args_list]
        # Only the tables[] call, no DDL
        assert q_calls == ["tables[]"]

    def test_drops_and_recreates_when_requested(self, mock_q):
        from kdbx.market_tables import create_market_tables

        mock_q.return_value = MagicMock(
            __iter__=lambda self: iter(["market_ticks", "order_book", "signals", "backtest_results"])
        )

        create_market_tables(drop_existing=True)

        q_calls = [c.args[0] for c in mock_q.call_args_list]
        # Should have delete + DDL for each table
        assert any("delete market_ticks from `." in c for c in q_calls)
        assert any("delete order_book from `." in c for c in q_calls)
        assert any("delete signals from `." in c for c in q_calls)
        assert any("delete backtest_results from `." in c for c in q_calls)


# ---------------------------------------------------------------------------
# load_parquet_data tests
# ---------------------------------------------------------------------------


class TestLoadParquetData:
    """Tests for load_parquet_data()."""

    def _make_sample_df(self) -> pd.DataFrame:
        """Create a minimal Parquet-like DataFrame."""
        return pd.DataFrame({
            "sym": ["AAPL", "NVDA"],
            "timestamp": pd.to_datetime(["2025-01-02 09:30:00", "2025-01-02 09:31:00"]),
            "open": [175.0, 500.0],
            "high": [176.0, 502.0],
            "low": [174.0, 498.0],
            "close": [175.5, 501.0],
            "volume": [1000, 2000],
            "vwap": [175.17, 500.33],
            "trade_count": [10, 20],
            "bid_price": [175.4, 500.9],
            "bid_size": [500, 600],
            "ask_price": [175.6, 501.1],
            "ask_size": [400, 500],
            "mid": [175.5, 501.0],
            "spread": [0.2, 0.2],
        })

    def test_batch_insert_uses_toq(self, mock_q):
        from kdbx.market_tables import load_parquet_data

        df = self._make_sample_df()
        mock_q.return_value = MagicMock(py=MagicMock(return_value=2))

        with patch("kdbx.market_tables.pd.read_parquet", return_value=df):
            result = load_parquet_data("/fake/path.parquet")

        # Should have called kx.toq for batch insert
        q_calls = [c.args[0] for c in mock_q.call_args_list]
        tick_insert = [c for c in q_calls if "market_ticks" in c and "insert" in c]
        book_insert = [c for c in q_calls if "order_book" in c and "insert" in c]
        assert len(tick_insert) >= 1, "Should batch insert into market_ticks"
        assert len(book_insert) >= 1, "Should batch insert into order_book"

    def test_applies_sorted_attribute(self, mock_q):
        from kdbx.market_tables import load_parquet_data

        df = self._make_sample_df()
        mock_q.return_value = MagicMock(py=MagicMock(return_value=2))

        with patch("kdbx.market_tables.pd.read_parquet", return_value=df):
            load_parquet_data("/fake/path.parquet")

        q_calls = [c.args[0] for c in mock_q.call_args_list]
        xasc_calls = [c for c in q_calls if "xasc" in c]
        # One for market_ticks, one for order_book
        assert len(xasc_calls) == 2, \
            "Should xasc sort both market_ticks and order_book"

    def test_returns_row_counts(self, mock_q):
        from kdbx.market_tables import load_parquet_data

        df = self._make_sample_df()
        mock_q.return_value = MagicMock(py=MagicMock(return_value=2))

        with patch("kdbx.market_tables.pd.read_parquet", return_value=df):
            result = load_parquet_data("/fake/path.parquet")

        assert "market_ticks" in result
        assert "order_book" in result
        assert result["market_ticks"] == 2
        assert result["order_book"] == 2
