# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from src.api.db import close_db, get_db, init_db


@pytest.fixture(autouse=True)
def reset_db_state():
    """Ensure clean database state before and after each test."""
    import src.api.db

    src.api.db._db = None

    yield

    src.api.db._db = None


class TestGetDb:
    """Test cases for the get_db function."""

    def test_get_db_not_initialized(self):
        """Test get_db raises RuntimeError when database is not initialized."""
        with pytest.raises(
            RuntimeError, match="Database not initialized. Call init_db\\(\\) first."
        ):
            get_db()

    def test_get_db_initialized(self):
        """Test get_db returns database when initialized."""
        import src.api.db

        mock_database = MagicMock()
        src.api.db._db = mock_database

        result = get_db()
        assert result == mock_database


class TestInitDb:
    """Test cases for the init_db function."""

    @patch("src.api.db.KDBXDatabase")
    @patch("src.api.db.create_all_tables")
    @patch("src.api.db.pykx_connection")
    def test_init_db_new_connection(self, mock_pykx_conn, mock_create_tables, mock_kdbx_db):
        """Test init_db creates new connection and tables."""
        mock_q = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_q)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_pykx_conn.return_value = mock_ctx

        mock_db_instance = MagicMock()
        mock_kdbx_db.return_value = mock_db_instance

        result = init_db()

        mock_pykx_conn.assert_called_once()
        mock_q.assert_called_once_with("1+1")
        mock_create_tables.assert_called_once()
        mock_kdbx_db.assert_called_once()
        assert result == mock_db_instance

    @patch("src.api.db.KDBXDatabase")
    @patch("src.api.db.create_all_tables")
    @patch("src.api.db.pykx_connection")
    def test_init_db_existing_connection(self, mock_pykx_conn, mock_create_tables, mock_kdbx_db):
        """Test init_db reuses existing connection when already initialized."""
        import src.api.db

        existing_db = MagicMock()
        src.api.db._db = existing_db

        result = init_db()

        mock_pykx_conn.assert_not_called()
        mock_create_tables.assert_not_called()
        mock_kdbx_db.assert_not_called()
        assert result == existing_db

    @patch("src.api.db.time.sleep")
    @patch("src.api.db.pykx_connection")
    def test_init_db_retry_on_failure(self, mock_pykx_conn, mock_sleep):
        """Test init_db retries on connection failure and eventually raises."""
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(side_effect=Exception("Connection failed"))
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_pykx_conn.return_value = mock_ctx

        with pytest.raises(RuntimeError, match="Could not connect to KDB-X after 30 attempts"):
            init_db()

        assert mock_pykx_conn.call_count == 30
        assert mock_sleep.call_count == 29

    @patch("src.api.db.KDBXDatabase")
    @patch("src.api.db.create_all_tables")
    @patch("src.api.db.time.sleep")
    @patch("src.api.db.pykx_connection")
    def test_init_db_retry_then_success(
        self, mock_pykx_conn, mock_sleep, mock_create_tables, mock_kdbx_db
    ):
        """Test init_db retries on failure then succeeds."""
        mock_q = MagicMock()

        call_count = 0

        @contextmanager
        def side_effect_func():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise Exception("Connection failed")
            yield mock_q

        mock_pykx_conn.side_effect = side_effect_func

        mock_db_instance = MagicMock()
        mock_kdbx_db.return_value = mock_db_instance

        result = init_db()

        assert mock_pykx_conn.call_count == 3
        assert mock_sleep.call_count == 2
        mock_create_tables.assert_called_once()
        assert result == mock_db_instance

    @patch("src.api.db.create_all_tables")
    @patch("src.api.db.pykx_connection")
    def test_init_db_create_tables_error(self, mock_pykx_conn, mock_create_tables):
        """Test init_db handles table creation errors."""
        mock_q = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_q)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_pykx_conn.return_value = mock_ctx

        mock_create_tables.side_effect = Exception("Table creation failed")

        with pytest.raises(RuntimeError, match="Could not connect to KDB-X after 30 attempts"):
            init_db()


class TestCloseDb:
    """Test cases for the close_db function."""

    def test_close_db_with_connection(self):
        """Test close_db resets the database instance."""
        import src.api.db

        src.api.db._db = MagicMock()

        close_db()

        assert src.api.db._db is None

        with pytest.raises(RuntimeError):
            get_db()

    def test_close_db_no_connection(self):
        """Test close_db works when no connection exists."""
        close_db()

        with pytest.raises(RuntimeError):
            get_db()


class TestIntegration:
    """Integration test cases for the db module."""

    @patch("src.api.db.KDBXDatabase")
    @patch("src.api.db.create_all_tables")
    @patch("src.api.db.pykx_connection")
    def test_full_lifecycle(self, mock_pykx_conn, mock_create_tables, mock_kdbx_db):
        """Test complete lifecycle: init -> get -> close."""
        mock_q = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_q)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_pykx_conn.return_value = mock_ctx

        mock_db_instance = MagicMock()
        mock_kdbx_db.return_value = mock_db_instance

        # Initialize database
        db1 = init_db()
        assert db1 == mock_db_instance

        # Get database
        db2 = get_db()
        assert db2 == mock_db_instance
        assert db1 == db2

        # Close database
        close_db()

        # Verify get_db raises error after closing
        with pytest.raises(RuntimeError):
            get_db()

    @patch("src.api.db.KDBXDatabase")
    @patch("src.api.db.create_all_tables")
    @patch("src.api.db.pykx_connection")
    def test_multiple_init_calls(self, mock_pykx_conn, mock_create_tables, mock_kdbx_db):
        """Test multiple init_db calls with connection reuse."""
        mock_q = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_q)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_pykx_conn.return_value = mock_ctx

        mock_db_instance = MagicMock()
        mock_kdbx_db.return_value = mock_db_instance

        # Call init_db multiple times
        db1 = init_db()
        db2 = init_db()
        db3 = init_db()

        # Verify all return same instance
        assert db1 == db2 == db3 == mock_db_instance

        # Verify pykx_connection was called only once (subsequent calls reuse)
        mock_pykx_conn.assert_called_once()
