# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
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
"""Tests for KdbPitSource.is_available() TTL-cached trade/quote probe."""

import kxta.kdb_direct_write as kdw
import kxta.source_agents.registry as reg
from kxta.source_agents.registry import KdbPitSource


def _reset_cache():
    reg._PIT_PROBE["ts"] = 0.0
    reg._PIT_PROBE["ok"] = False


def test_unavailable_without_host(monkeypatch):
    monkeypatch.delenv("KDB_DB_HOST", raising=False)
    assert KdbPitSource().is_available() is False


def test_available_when_trade_and_quote_have_rows(monkeypatch):
    monkeypatch.setenv("KDB_DB_HOST", "kdbx")
    monkeypatch.setattr(kdw, "_table_counts_sync", lambda t: {"trade": 62230, "quote": 124460})
    _reset_cache()
    assert KdbPitSource().is_available() is True


def test_unavailable_when_tables_missing(monkeypatch):
    monkeypatch.setenv("KDB_DB_HOST", "kdbx")
    monkeypatch.setattr(kdw, "_table_counts_sync", lambda t: {"trade": None, "quote": None})
    _reset_cache()
    assert KdbPitSource().is_available() is False


def test_unavailable_when_tables_empty(monkeypatch):
    monkeypatch.setenv("KDB_DB_HOST", "kdbx")
    monkeypatch.setattr(kdw, "_table_counts_sync", lambda t: {"trade": 0, "quote": 0})
    _reset_cache()
    assert KdbPitSource().is_available() is False


def test_unavailable_when_probe_raises(monkeypatch):
    monkeypatch.setenv("KDB_DB_HOST", "kdbx")

    def boom(t):
        raise RuntimeError("kdbx down")

    monkeypatch.setattr(kdw, "_table_counts_sync", boom)
    _reset_cache()
    assert KdbPitSource().is_available() is False


def test_reason_when_no_data(monkeypatch):
    monkeypatch.setenv("KDB_DB_HOST", "kdbx")
    assert "tick data" in KdbPitSource().unavailable_reason.lower()
