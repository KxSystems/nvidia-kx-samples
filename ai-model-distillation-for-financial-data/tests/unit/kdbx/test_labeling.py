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
"""Tests for kdbx.labeling module.

Covers:
  - BUY / SELL / HOLD direction from return vs threshold
  - Template rationale format
  - Missing market data → None direction
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fixture — same pattern as test_enrichment.py
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_q():
    """Patch pykx_connection and kx where labeling.py uses them."""
    mock_conn = MagicMock(name="SyncQConnection")

    @contextmanager
    def _fake_ctx():
        yield mock_conn

    with (
        patch("kdbx.labeling.pykx_connection", _fake_ctx),
        patch("kdbx.labeling.kx") as mock_kx,
    ):
        mock_kx.SymbolVector.side_effect = lambda v: ("SymbolVector", list(v))
        mock_kx.TimestampVector.side_effect = lambda v: ("TimestampVector", list(v))
        yield mock_conn, mock_kx


def _make_result(rows: list[dict]) -> MagicMock:
    result = MagicMock()
    result.pd.return_value = pd.DataFrame(rows)
    return result


# ---------------------------------------------------------------------------
# compute_return_labels_batch tests
# ---------------------------------------------------------------------------


class TestReturnLabels:
    def test_buy_when_return_exceeds_threshold(self, mock_q):
        """Return +1.5% with threshold 50bps → BUY."""
        mock_conn, _ = mock_q
        mock_conn.return_value = _make_result([
            {"entry_price": 100.0, "exit_price": 101.5},
        ])

        from kdbx.labeling import compute_return_labels_batch

        labels = compute_return_labels_batch(["AAPL"], ["2025-06-15T10:00:00"], 50.0)

        assert len(labels) == 1
        assert labels[0]["direction"] == "BUY"
        assert labels[0]["return_pct"] == pytest.approx(1.5, abs=0.01)

    def test_sell_when_return_below_negative_threshold(self, mock_q):
        """Return -1.0% with threshold 50bps → SELL."""
        mock_conn, _ = mock_q
        mock_conn.return_value = _make_result([
            {"entry_price": 100.0, "exit_price": 99.0},
        ])

        from kdbx.labeling import compute_return_labels_batch

        labels = compute_return_labels_batch(["AAPL"], ["2025-06-15T10:00:00"], 50.0)

        assert labels[0]["direction"] == "SELL"
        assert labels[0]["return_pct"] == pytest.approx(-1.0, abs=0.01)

    def test_hold_when_return_within_threshold(self, mock_q):
        """Return +0.3% with threshold 50bps → HOLD."""
        mock_conn, _ = mock_q
        mock_conn.return_value = _make_result([
            {"entry_price": 100.0, "exit_price": 100.3},
        ])

        from kdbx.labeling import compute_return_labels_batch

        labels = compute_return_labels_batch(["AAPL"], ["2025-06-15T10:00:00"], 50.0)

        assert labels[0]["direction"] == "HOLD"

    def test_no_exit_price_returns_none(self, mock_q):
        """Missing exit price → direction is None."""
        mock_conn, _ = mock_q
        mock_conn.return_value = _make_result([
            {"entry_price": 100.0, "exit_price": None},
        ])

        from kdbx.labeling import compute_return_labels_batch

        labels = compute_return_labels_batch(["AAPL"], ["2025-06-15T10:00:00"], 50.0)

        assert labels[0]["direction"] is None
        assert labels[0]["entry_price"] is None

    def test_no_entry_price_returns_none(self, mock_q):
        """Missing entry price → direction is None."""
        mock_conn, _ = mock_q
        mock_conn.return_value = _make_result([
            {"entry_price": None, "exit_price": 101.0},
        ])

        from kdbx.labeling import compute_return_labels_batch

        labels = compute_return_labels_batch(["AAPL"], ["2025-06-15T10:00:00"], 50.0)

        assert labels[0]["direction"] is None

    def test_empty_input_returns_empty(self, mock_q):
        mock_conn, _ = mock_q

        from kdbx.labeling import compute_return_labels_batch

        labels = compute_return_labels_batch([], [], 50.0)

        assert labels == []
        mock_conn.assert_not_called()

    def test_batch_multiple_records(self, mock_q):
        """Three records: BUY, SELL, HOLD."""
        mock_conn, _ = mock_q
        mock_conn.return_value = _make_result([
            {"entry_price": 100.0, "exit_price": 102.0},  # +2% → BUY
            {"entry_price": 100.0, "exit_price": 98.0},   # -2% → SELL
            {"entry_price": 100.0, "exit_price": 100.1},  # +0.1% → HOLD
        ])

        from kdbx.labeling import compute_return_labels_batch

        labels = compute_return_labels_batch(
            ["AAPL", "MSFT", "GOOG"],
            ["2025-06-15T10:00:00"] * 3,
            50.0,
        )

        assert len(labels) == 3
        assert labels[0]["direction"] == "BUY"
        assert labels[1]["direction"] == "SELL"
        assert labels[2]["direction"] == "HOLD"


# ---------------------------------------------------------------------------
# generate_template_rationale tests
# ---------------------------------------------------------------------------


class TestTemplateRationale:
    def test_format_buy(self):
        from kdbx.labeling import generate_template_rationale

        result = generate_template_rationale("BUY", "AAPL", 1.50, 185.50, 188.28)

        assert result.startswith("BUY")
        assert "AAPL" in result
        assert "+1.50%" in result
        assert "$185.50" in result
        assert "$188.28" in result

    def test_format_sell(self):
        from kdbx.labeling import generate_template_rationale

        result = generate_template_rationale("SELL", "MSFT", -2.30, 400.00, 390.80)

        assert result.startswith("SELL")
        assert "MSFT" in result
        assert "-2.30%" in result

    def test_format_hold(self):
        from kdbx.labeling import generate_template_rationale

        result = generate_template_rationale("HOLD", "GOOG", 0.10, 150.00, 150.15)

        assert result.startswith("HOLD")
        assert "+0.10%" in result
