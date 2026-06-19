# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the PyKX-based direct-write client (no q server required)."""

import pytest

from kxta.kdb_direct_write import KXTA_OWNED_TABLES
from kxta.kdb_direct_write import TABLE_SCHEMAS
from kxta.kdb_direct_write import KdbWriteError
from kxta.kdb_direct_write import _parse_q_date
from kxta.kdb_direct_write import _parse_q_time_ms
from kxta.kdb_direct_write import assert_kxta_owned
from kxta.kdb_direct_write import kdb_insert


def test_parse_q_date():
    assert str(_parse_q_date("2024.01.10")) == "2024-01-10"


def test_parse_q_time_ms():
    assert _parse_q_time_ms("00:00:00.000") == 0
    assert _parse_q_time_ms("09:30:01.255") == ((9 * 60 + 30) * 60 + 1) * 1000 + 255
    assert _parse_q_time_ms("16:00:00") == 16 * 3600 * 1000  # no millis part


def test_guard_rejects_non_kxta_table():
    with pytest.raises(KdbWriteError, match="non-KXTA"):
        assert_kxta_owned("smoke")


def test_guard_accepts_owned_tables():
    for t in KXTA_OWNED_TABLES:
        assert_kxta_owned(t)  # must not raise


def test_every_owned_table_has_a_schema():
    assert set(TABLE_SCHEMAS) == KXTA_OWNED_TABLES


@pytest.mark.asyncio
async def test_kdb_insert_rejects_unowned_table():
    with pytest.raises(KdbWriteError, match="non-KXTA"):
        await kdb_insert("tables_enum", [{"a": 1}])


@pytest.mark.asyncio
async def test_kdb_insert_empty_rows_is_noop():
    result = await kdb_insert("daily", [])
    assert result == {"ok": True, "isError": False, "error": None, "rows": 0}


def test_typed_column_conversion():
    """Needs PyKX installed (unlicensed is fine); skipped otherwise."""
    kx = pytest.importorskip("pykx")
    from kxta.kdb_direct_write import _column

    assert isinstance(_column("date", ["2024.01.10"]), kx.DateVector)
    assert isinstance(_column("time", ["09:30:00.255"]), kx.TimeVector)
    assert isinstance(_column("symbol", ["NVDA"]), kx.SymbolVector)
    assert isinstance(_column("float", [1.5, None]), kx.FloatVector)
    assert isinstance(_column("long", [10, None]), kx.LongVector)
    # strings become a list of bytes -> q char vectors; no escaping involved
    assert _column("string", ['a "quoted"; value', None]) == [b'a "quoted"; value', b""]
    with pytest.raises(KdbWriteError, match="unknown column kind"):
        _column("guid", ["x"])
