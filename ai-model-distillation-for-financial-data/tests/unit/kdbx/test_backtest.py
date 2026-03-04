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
"""Tests for kdbx.backtest module.

Covers:
  - Parameterized q (values not in string)
  - model_id -> SymbolAtom, cost -> FloatAtom, universe -> SymbolVector
  - Returns dict with 5 expected keys
  - q string contains aj[
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_q():
    """Patch pykx_connection and kx where backtest.py uses them."""
    mock_conn = MagicMock(name="SyncQConnection")

    @contextmanager
    def _fake_ctx():
        yield mock_conn

    with (
        patch("kdbx.backtest.pykx_connection", _fake_ctx),
        patch("kdbx.backtest.kx") as mock_kx,
    ):
        mock_kx.SymbolAtom.side_effect = lambda v: ("SymbolAtom", v)
        mock_kx.SymbolVector.side_effect = lambda v: ("SymbolVector", list(v))
        mock_kx.FloatAtom.side_effect = lambda v: ("FloatAtom", v)
        yield mock_conn, mock_kx


# ---------------------------------------------------------------------------
# q string validation
# ---------------------------------------------------------------------------


class TestBacktestQStrings:
    """Verify the q lambda contains expected patterns."""

    def test_q_contains_aj(self):
        from kdbx.backtest import _BACKTEST_Q

        assert "aj[" in _BACKTEST_Q, "Backtest q must use aj[] for as-of join"

    def test_q_contains_aj_universe(self):
        from kdbx.backtest import _BACKTEST_UNIVERSE_Q

        assert "aj[" in _BACKTEST_UNIVERSE_Q

    def test_q_contains_ternary(self):
        from kdbx.backtest import _BACKTEST_Q

        assert "$[" in _BACKTEST_Q, "Backtest q should use $[cond;...] ternary"

    def test_q_does_not_contain_user_values(self):
        """The q string should not embed any model_id or cost values."""
        from kdbx.backtest import _BACKTEST_Q

        # These are parameter placeholders, not user values
        assert "mid" in _BACKTEST_Q  # parameter name
        assert "cost" in _BACKTEST_Q  # parameter name
        # No hardcoded model IDs or cost values
        for bad in ["model_alpha", "5.0", "AAPL"]:
            assert bad not in _BACKTEST_Q


# ---------------------------------------------------------------------------
# run_backtest() tests
# ---------------------------------------------------------------------------


class TestRunBacktest:
    """Tests for run_backtest()."""

    def _make_result_mock(self):
        """Create a mock that behaves like a q dictionary result."""
        result = MagicMock()
        result.__getitem__ = MagicMock(side_effect={
            "sharpe": MagicMock(__float__=lambda self: 1.5),
            "max_drawdown": MagicMock(__float__=lambda self: -0.05),
            "total_return": MagicMock(__float__=lambda self: 0.12),
            "win_rate": MagicMock(__float__=lambda self: 0.55),
            "n_trades": MagicMock(__int__=lambda self: 100),
        }.__getitem__)
        return result

    def test_model_id_passed_as_symbol_atom(self, mock_q):
        mock_conn, mock_kx = mock_q
        mock_conn.return_value = self._make_result_mock()

        from kdbx.backtest import run_backtest

        run_backtest("model_alpha")

        # First positional arg after q string should be SymbolAtom(model_id)
        call_args = mock_conn.call_args.args
        assert call_args[1] == ("SymbolAtom", "model_alpha")

    def test_cost_passed_as_float_atom(self, mock_q):
        mock_conn, mock_kx = mock_q
        mock_conn.return_value = self._make_result_mock()

        from kdbx.backtest import run_backtest

        run_backtest("model_alpha", cost_bps=10.0)

        call_args = mock_conn.call_args.args
        assert call_args[2] == ("FloatAtom", 10.0)

    def test_universe_passed_as_symbol_vector(self, mock_q):
        mock_conn, mock_kx = mock_q
        mock_conn.return_value = self._make_result_mock()

        from kdbx.backtest import run_backtest

        run_backtest("model_alpha", universe=["AAPL", "NVDA"])

        call_args = mock_conn.call_args.args
        assert call_args[3] == ("SymbolVector", ["AAPL", "NVDA"])

    def test_returns_dict_with_expected_keys(self, mock_q):
        mock_conn, mock_kx = mock_q
        mock_conn.return_value = self._make_result_mock()

        from kdbx.backtest import run_backtest

        result = run_backtest("model_alpha")

        expected_keys = {"sharpe", "max_drawdown", "total_return", "win_rate", "n_trades"}
        assert set(result.keys()) == expected_keys

    def test_values_not_in_q_string(self, mock_q):
        """User values must not appear in the q lambda string."""
        mock_conn, mock_kx = mock_q
        mock_conn.return_value = self._make_result_mock()

        from kdbx.backtest import run_backtest

        run_backtest("model_alpha", cost_bps=7.5)

        q_string = mock_conn.call_args.args[0]
        assert "model_alpha" not in q_string
        assert "7.5" not in q_string

    def test_without_universe_uses_base_lambda(self, mock_q):
        mock_conn, mock_kx = mock_q
        mock_conn.return_value = self._make_result_mock()

        from kdbx.backtest import run_backtest

        run_backtest("model_alpha")

        q_string = mock_conn.call_args.args[0]
        # Base lambda takes 2 params: mid, cost
        assert "{[mid;cost]" in q_string

    def test_with_universe_uses_universe_lambda(self, mock_q):
        mock_conn, mock_kx = mock_q
        mock_conn.return_value = self._make_result_mock()

        from kdbx.backtest import run_backtest

        run_backtest("model_alpha", universe=["AAPL"])

        q_string = mock_conn.call_args.args[0]
        # Universe lambda takes 3 params: mid, cost, syms
        assert "{[mid;cost;syms]" in q_string
