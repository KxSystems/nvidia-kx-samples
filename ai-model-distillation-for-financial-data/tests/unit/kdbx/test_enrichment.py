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
"""Tests for kdbx.enrichment module.

Covers:
  - q contains aj[
  - sym -> SymbolAtom, timestamp -> TimestampAtom
  - Original record keys preserved
  - Batch: single q call for multiple records
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_q():
    """Patch pykx_connection and kx where enrichment.py uses them."""
    mock_conn = MagicMock(name="SyncQConnection")

    @contextmanager
    def _fake_ctx():
        yield mock_conn

    with (
        patch("kdbx.enrichment.pykx_connection", _fake_ctx),
        patch("kdbx.enrichment.kx") as mock_kx,
    ):
        mock_kx.SymbolAtom.side_effect = lambda v: ("SymbolAtom", v)
        mock_kx.TimestampAtom.side_effect = lambda v: ("TimestampAtom", v)
        mock_kx.SymbolVector.side_effect = lambda v: ("SymbolVector", list(v))
        mock_kx.TimestampVector.side_effect = lambda v: ("TimestampVector", list(v))
        mock_kx.FloatAtom.side_effect = lambda v: ("FloatAtom", v)
        mock_kx.toq.side_effect = lambda v: ("toq", v)
        yield mock_conn, mock_kx


# ---------------------------------------------------------------------------
# q string validation
# ---------------------------------------------------------------------------


class TestEnrichmentQStrings:
    """Verify the q lambdas contain expected patterns."""

    def test_single_q_contains_aj(self):
        from kdbx.enrichment import _ENRICH_Q

        assert "aj[" in _ENRICH_Q, "Single enrichment q must use aj[]"

    def test_batch_q_contains_aj(self):
        from kdbx.enrichment import _ENRICH_BATCH_Q

        assert "aj[" in _ENRICH_BATCH_Q, "Batch enrichment q must use aj[]"

    def test_single_q_contains_lj(self):
        from kdbx.enrichment import _ENRICH_Q

        assert "lj" in _ENRICH_Q, "Single enrichment q should use lj to merge"

    def test_batch_q_contains_lj(self):
        from kdbx.enrichment import _ENRICH_BATCH_Q

        assert "lj" in _ENRICH_BATCH_Q


# ---------------------------------------------------------------------------
# enrich_training_pair() tests
# ---------------------------------------------------------------------------


class TestEnrichTrainingPair:
    """Tests for enrich_training_pair()."""

    def _make_result_mock(self):
        """Create a mock that returns a q dictionary (from ``first``)."""
        result = MagicMock()
        result.py.return_value = {
            "sym": "AAPL",
            "timestamp": pd.Timestamp("2025-06-15 10:30:00"),
            "close": 178.5,
            "vwap": 178.2,
            "high": 179.0,
            "low": 177.5,
            "volume": 50000,
            "bid_price": 178.4,
            "ask_price": 178.6,
            "spread": 0.2,
            "mid": 178.5,
        }
        return result

    def test_sym_passed_as_symbol_atom(self, mock_q):
        mock_conn, mock_kx = mock_q
        mock_conn.return_value = self._make_result_mock()

        from kdbx.enrichment import enrich_training_pair

        enrich_training_pair({"question": "test"}, "AAPL", "2025-06-15T10:30:00")

        call_args = mock_conn.call_args.args
        assert call_args[1] == ("SymbolAtom", "AAPL")

    def test_timestamp_passed_as_timestamp_atom(self, mock_q):
        mock_conn, mock_kx = mock_q
        mock_conn.return_value = self._make_result_mock()

        from kdbx.enrichment import enrich_training_pair

        enrich_training_pair({"question": "test"}, "AAPL", "2025-06-15T10:30:00")

        call_args = mock_conn.call_args.args
        assert call_args[2] == ("TimestampAtom", pd.Timestamp("2025-06-15T10:30:00"))

    def test_original_record_preserved(self, mock_q):
        mock_conn, mock_kx = mock_q
        mock_conn.return_value = self._make_result_mock()

        from kdbx.enrichment import enrich_training_pair

        original = {"question": "What is AAPL?", "answer": "Apple Inc."}
        result = enrich_training_pair(original, "AAPL", "2025-06-15T10:30:00")

        assert result["question"] == "What is AAPL?"
        assert result["answer"] == "Apple Inc."

    def test_enriched_fields_added(self, mock_q):
        mock_conn, mock_kx = mock_q
        mock_conn.return_value = self._make_result_mock()

        from kdbx.enrichment import enrich_training_pair

        result = enrich_training_pair({}, "AAPL", "2025-06-15T10:30:00")

        for key in ["market_close", "market_vwap", "market_high", "market_low",
                     "market_volume", "market_bid", "market_ask", "market_spread",
                     "market_mid"]:
            assert key in result, f"Missing enriched field: {key!r}"

    def test_enriched_values_are_floats(self, mock_q):
        mock_conn, mock_kx = mock_q
        mock_conn.return_value = self._make_result_mock()

        from kdbx.enrichment import enrich_training_pair

        result = enrich_training_pair({}, "AAPL", "2025-06-15T10:30:00")

        assert result["market_close"] == 178.5
        assert result["market_vwap"] == 178.2


# ---------------------------------------------------------------------------
# enrich_training_pairs_batch() tests
# ---------------------------------------------------------------------------


class TestEnrichTrainingPairsBatch:
    """Tests for enrich_training_pairs_batch()."""

    def _make_batch_result_mock(self, n: int):
        """Create a mock returning n-row DataFrame."""
        result = MagicMock()
        rows = [{
            "sym": "AAPL",
            "timestamp": pd.Timestamp("2025-06-15 10:30:00"),
            "close": 178.5 + i,
            "vwap": 178.2 + i,
            "high": 179.0 + i,
            "low": 177.5 + i,
            "volume": 50000 + i * 1000,
            "bid_price": 178.4 + i,
            "ask_price": 178.6 + i,
            "spread": 0.2,
            "mid": 178.5 + i,
        } for i in range(n)]
        result.pd.return_value = pd.DataFrame(rows)
        return result

    def test_single_q_call_for_multiple_records(self, mock_q):
        """Batch should make exactly 1 q call (not N)."""
        mock_conn, mock_kx = mock_q
        mock_conn.return_value = self._make_batch_result_mock(3)

        from kdbx.enrichment import enrich_training_pairs_batch

        records = [
            {"sym": "AAPL", "timestamp": "2025-06-15T10:30:00", "data": "r1"},
            {"sym": "AAPL", "timestamp": "2025-06-15T10:31:00", "data": "r2"},
            {"sym": "NVDA", "timestamp": "2025-06-15T10:30:00", "data": "r3"},
        ]

        enrich_training_pairs_batch(records)

        # Only 1 q call (the batch lambda)
        assert mock_conn.call_count == 1

    def test_batch_preserves_original_records(self, mock_q):
        mock_conn, mock_kx = mock_q
        mock_conn.return_value = self._make_batch_result_mock(2)

        from kdbx.enrichment import enrich_training_pairs_batch

        records = [
            {"sym": "AAPL", "timestamp": "2025-06-15T10:30:00", "question": "q1"},
            {"sym": "NVDA", "timestamp": "2025-06-15T10:31:00", "question": "q2"},
        ]

        result = enrich_training_pairs_batch(records)

        assert len(result) == 2
        assert result[0]["question"] == "q1"
        assert result[1]["question"] == "q2"

    def test_batch_empty_returns_empty(self, mock_q):
        mock_conn, mock_kx = mock_q

        from kdbx.enrichment import enrich_training_pairs_batch

        result = enrich_training_pairs_batch([])

        assert result == []
        mock_conn.assert_not_called()

    def test_batch_sends_symbol_and_timestamp_vectors(self, mock_q):
        """Batch should send SymbolVector and TimestampVector (no license needed)."""
        mock_conn, mock_kx = mock_q
        mock_conn.return_value = self._make_batch_result_mock(1)

        from kdbx.enrichment import enrich_training_pairs_batch

        records = [{"sym": "AAPL", "timestamp": "2025-06-15T10:30:00"}]
        enrich_training_pairs_batch(records)

        # Should use SymbolVector and TimestampVector (not toq)
        mock_kx.SymbolVector.assert_called_once()
        mock_kx.TimestampVector.assert_called_once()
        mock_kx.toq.assert_not_called()
