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
"""Tests for kdbx.schema module."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# TABLE_NAMES
# ---------------------------------------------------------------------------

EXPECTED_TABLE_NAMES = [
    "flywheel_runs",
    "nims",
    "evaluations",
    "customizations",
    "llm_judge_runs",
    "flywheel_logs",
    "flywheel_embeddings",
]


class TestTableNames:
    """Tests for TABLE_NAMES constant."""

    def test_contains_exactly_seven_tables(self):
        from kdbx.schema import TABLE_NAMES

        assert len(TABLE_NAMES) == 7

    def test_contains_all_expected_names(self):
        from kdbx.schema import TABLE_NAMES

        assert set(TABLE_NAMES) == set(EXPECTED_TABLE_NAMES)

    def test_order_matches(self):
        from kdbx.schema import TABLE_NAMES

        assert list(TABLE_NAMES) == EXPECTED_TABLE_NAMES


# ---------------------------------------------------------------------------
# _TABLE_DDL
# ---------------------------------------------------------------------------


class TestTableDDL:
    """Tests for _TABLE_DDL dict."""

    def test_has_all_seven_entries(self):
        from kdbx.schema import _TABLE_DDL

        assert len(_TABLE_DDL) == 7

    def test_keys_match_table_names(self):
        from kdbx.schema import TABLE_NAMES, _TABLE_DDL

        assert set(_TABLE_DDL.keys()) == set(TABLE_NAMES)

    def test_ddl_values_are_strings(self):
        from kdbx.schema import _TABLE_DDL

        for name, ddl in _TABLE_DDL.items():
            assert isinstance(ddl, str), f"DDL for {name} should be a string"

    def test_ddl_contains_table_name(self):
        """Each DDL statement should reference its own table name."""
        from kdbx.schema import _TABLE_DDL

        for name, ddl in _TABLE_DDL.items():
            assert name in ddl, f"DDL for {name} should contain the table name"

    def test_flywheel_runs_ddl_has_expected_columns(self):
        from kdbx.schema import _TABLE_DDL

        ddl = _TABLE_DDL["flywheel_runs"]
        for col in [
            "_id",
            "workload_id",
            "client_id",
            "status",
            "started_at",
            "finished_at",
            "num_records",
            "datasets",
            "error",
        ]:
            assert col in ddl, f"flywheel_runs DDL missing column {col}"

    def test_flywheel_embeddings_ddl_has_expected_columns(self):
        from kdbx.schema import _TABLE_DDL

        ddl = _TABLE_DDL["flywheel_embeddings"]
        for col in [
            "doc_id",
            "index_name",
            "embedding",
            "tool_name",
            "query_text",
            "record_id",
            "timestamp",
            "record",
        ]:
            assert col in ddl, f"flywheel_embeddings DDL missing column {col}"


# ---------------------------------------------------------------------------
# Helper: mock_q_connection fixture local to these tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_q():
    """Patch ``kdbx.schema.pykx_connection`` so tests never need a real KDB-X.

    Yields the mock connection object (callable MagicMock) that stands in
    for the ``q`` handle inside ``create_all_tables``.
    """
    mock_conn = MagicMock(name="SyncQConnection")

    @contextmanager
    def _fake_ctx():
        yield mock_conn

    with patch("kdbx.schema.pykx_connection", _fake_ctx):
        yield mock_conn


# ---------------------------------------------------------------------------
# create_all_tables
# ---------------------------------------------------------------------------


class TestCreateAllTables:
    """Tests for create_all_tables function."""

    def test_creates_all_seven_tables(self, mock_q):
        from kdbx.schema import TABLE_NAMES, _TABLE_DDL, create_all_tables

        # Simulate no tables existing yet
        mock_q.return_value = []

        create_all_tables()

        # Collect all call arg strings
        q_calls = mock_q.call_args_list
        # Verify DDL was executed for each table
        for name in TABLE_NAMES:
            ddl = _TABLE_DDL[name]
            ddl_found = any(c.args[0] == ddl for c in q_calls if c.args)
            assert ddl_found, f"Expected DDL call for {name}"

    def test_does_not_load_ai_module(self, mock_q):
        """Vector search uses numpy; no AI module loading needed."""
        from kdbx.schema import create_all_tables

        mock_q.return_value = []

        create_all_tables()

        q_calls = mock_q.call_args_list
        ai_load_calls = [
            c for c in q_calls
            if c.args and ("\\l ai.q" in c.args[0] or ".hnsw" in c.args[0])
        ]
        assert len(ai_load_calls) == 0

    def test_skips_existing_tables(self, mock_q):
        from kdbx.schema import _TABLE_DDL, create_all_tables

        # Simulate all tables already existing
        all_table_names = list(_TABLE_DDL.keys())

        def side_effect(query):
            if query == "tables[]":
                return all_table_names
            return None

        mock_q.side_effect = side_effect

        create_all_tables()

        # Should NOT have executed any DDL (all tables exist)
        q_calls = mock_q.call_args_list
        for name in all_table_names:
            ddl = _TABLE_DDL[name]
            ddl_found = any(c.args[0] == ddl for c in q_calls if c.args)
            assert not ddl_found, f"Should not have created {name} (already exists)"

    def test_drop_existing_drops_and_recreates(self, mock_q):
        from kdbx.schema import TABLE_NAMES, _TABLE_DDL, create_all_tables

        # Simulate all tables existing
        all_table_names = list(_TABLE_DDL.keys())

        def side_effect(query):
            if query == "tables[]":
                return all_table_names
            return None

        mock_q.side_effect = side_effect

        create_all_tables(drop_existing=True)

        q_calls = mock_q.call_args_list
        call_args = [c.args[0] for c in q_calls if c.args]

        # Should have drop calls for each existing table
        for name in TABLE_NAMES:
            drop_stmt = f"delete {name} from `."
            assert drop_stmt in call_args, f"Expected drop call for {name}"

        # Should have DDL calls for each table
        for name in TABLE_NAMES:
            ddl = _TABLE_DDL[name]
            assert ddl in call_args, f"Expected DDL call for {name}"

    def test_uses_pykx_connection_context_manager(self, mock_q):
        """Verify that create_all_tables uses the pykx_connection context manager."""
        from kdbx.schema import create_all_tables

        mock_q.return_value = []

        # If we get here without error, the mock context manager was used
        create_all_tables()

        # The mock was called at least once (proving pykx_connection was used)
        assert mock_q.called
