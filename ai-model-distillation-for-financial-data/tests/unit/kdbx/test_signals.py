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
"""Tests for kdbx.signals — batch signal writer."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import call

import pykx as kx
import pytest

from kdbx.signals import write_signals_batch


@pytest.fixture(autouse=True)
def patch_signals_pykx(mock_pykx_connection):
    """Ensure kdbx.signals also sees the mocked pykx_connection."""
    from unittest.mock import patch as _patch
    from contextlib import contextmanager

    @contextmanager
    def _fake_ctx():
        yield mock_pykx_connection

    with _patch("kdbx.signals.pykx_connection", _fake_ctx):
        yield


def _make_signal(**overrides):
    base = {
        "signal_id": "sig-001",
        "timestamp": datetime(2026, 1, 15, 10, 0, 0),
        "sym": "AAPL",
        "direction": "BUY",
        "confidence": 0.0,
        "model_id": "meta/llama-3.1-8b-instruct",
        "rationale": "Strong earnings expected",
    }
    base.update(overrides)
    return base


class TestWriteSignalsBatch:
    def test_empty_list_returns_zero(self, mock_pykx_connection):
        assert write_signals_batch([]) == 0
        mock_pykx_connection.assert_not_called()

    def test_single_signal_inserts_correctly(self, mock_pykx_connection):
        sig = _make_signal()
        count = write_signals_batch([sig])

        assert count == 1
        mock_pykx_connection.assert_called_once()

        # Verify the q call used typed vectors
        args = mock_pykx_connection.call_args_list[0]
        q_string = args[0][0]
        assert "`signals insert flip" in q_string

    def test_multiple_signals(self, mock_pykx_connection):
        sigs = [
            _make_signal(signal_id="sig-001", sym="AAPL", direction="BUY"),
            _make_signal(signal_id="sig-002", sym="MSFT", direction="SELL"),
            _make_signal(signal_id="sig-003", sym="GOOG", direction="HOLD"),
        ]
        count = write_signals_batch(sigs)

        assert count == 3
        mock_pykx_connection.assert_called_once()

    def test_uses_symbol_vectors_for_symbol_cols(self, mock_pykx_connection):
        sig = _make_signal()
        write_signals_batch([sig])

        args, kwargs = mock_pykx_connection.call_args_list[0]
        # args[0] is q string, args[1:] are the typed vectors
        # signal_id, sym, direction, model_id should be SymbolVectors
        symbol_args = [args[1], args[3], args[4], args[6]]
        for arg in symbol_args:
            assert isinstance(arg, kx.SymbolVector)

    def test_uses_timestamp_vector(self, mock_pykx_connection):
        sig = _make_signal()
        write_signals_batch([sig])

        args, kwargs = mock_pykx_connection.call_args_list[0]
        # args[2] is timestamp
        assert isinstance(args[2], kx.TimestampVector)
