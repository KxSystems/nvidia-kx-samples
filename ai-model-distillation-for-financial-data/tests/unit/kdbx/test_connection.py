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
"""Tests for kdbx.connection module."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# _parse_endpoint
# ---------------------------------------------------------------------------


class TestParseEndpoint:
    """Tests for _parse_endpoint helper."""

    def test_parses_host_and_port(self):
        from kdbx.connection import _parse_endpoint

        host, port = _parse_endpoint("myhost:9999")
        assert host == "myhost"
        assert port == 9999

    def test_default_endpoint(self):
        from kdbx.connection import _parse_endpoint

        host, port = _parse_endpoint("localhost:8082")
        assert host == "localhost"
        assert port == 8082

    def test_raises_on_non_numeric_port(self):
        from kdbx.connection import _parse_endpoint

        with pytest.raises(ValueError, match="Invalid port"):
            _parse_endpoint("host:abc")

    def test_raises_on_negative_port(self):
        from kdbx.connection import _parse_endpoint

        with pytest.raises(ValueError, match="Invalid port"):
            _parse_endpoint("host:-1")

    def test_raises_on_port_exceeding_65535(self):
        from kdbx.connection import _parse_endpoint

        with pytest.raises(ValueError, match="Invalid port"):
            _parse_endpoint("host:70000")

    def test_raises_on_missing_colon(self):
        from kdbx.connection import _parse_endpoint

        with pytest.raises(ValueError, match="Expected"):
            _parse_endpoint("localhost")


# ---------------------------------------------------------------------------
# get_kdbx_mode
# ---------------------------------------------------------------------------


class TestGetKdbxMode:
    """Tests for get_kdbx_mode."""

    def test_defaults_to_ipc(self):
        from kdbx.connection import get_kdbx_mode

        with patch.dict(os.environ, {}, clear=False):
            # Remove KDBX_MODE if it exists
            os.environ.pop("KDBX_MODE", None)
            assert get_kdbx_mode() == "ipc"

    def test_returns_embedded_when_set(self):
        from kdbx.connection import get_kdbx_mode

        with patch.dict(os.environ, {"KDBX_MODE": "embedded"}):
            assert get_kdbx_mode() == "embedded"

    def test_returns_ipc_when_set(self):
        from kdbx.connection import get_kdbx_mode

        with patch.dict(os.environ, {"KDBX_MODE": "ipc"}):
            assert get_kdbx_mode() == "ipc"


# ---------------------------------------------------------------------------
# pykx_connection
# ---------------------------------------------------------------------------


def _make_mock_sync_conn():
    """Create a MagicMock that behaves as a SyncQConnection context manager.

    The mock's ``__enter__`` returns itself so ``with ... as conn:`` gives
    the same object, matching real SyncQConnection behaviour.
    """
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    return mock_conn


class TestPykxConnection:
    """Tests for pykx_connection context manager."""

    @patch("kdbx.connection.kx")
    def test_creates_connection_from_env(self, mock_kx):
        from kdbx.connection import pykx_connection

        mock_conn = _make_mock_sync_conn()
        mock_kx.SyncQConnection.return_value = mock_conn

        with patch.dict(os.environ, {"KDBX_ENDPOINT": "remotehost:5001"}):
            with pykx_connection() as conn:
                assert conn is mock_conn
            mock_kx.SyncQConnection.assert_called_once_with(host="remotehost", port=5001)

    @patch("kdbx.connection.kx")
    def test_defaults_to_localhost_when_embedded(self, mock_kx):
        from kdbx.connection import pykx_connection

        mock_conn = _make_mock_sync_conn()
        mock_kx.SyncQConnection.return_value = mock_conn

        with patch.dict(os.environ, {"KDBX_MODE": "embedded"}, clear=False):
            os.environ.pop("KDBX_ENDPOINT", None)
            with pykx_connection() as conn:
                assert conn is mock_conn
            mock_kx.SyncQConnection.assert_called_once_with(host="localhost", port=8082)

    def test_raises_when_endpoint_missing_and_not_embedded(self):
        from kdbx.connection import pykx_connection

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KDBX_ENDPOINT", None)
            os.environ.pop("KDBX_MODE", None)
            with pytest.raises(RuntimeError, match="KDBX_ENDPOINT"):
                with pykx_connection():
                    pass  # pragma: no cover

    @patch("kdbx.connection.kx")
    def test_raises_value_error_on_invalid_port(self, mock_kx):
        from kdbx.connection import pykx_connection

        with patch.dict(os.environ, {"KDBX_ENDPOINT": "host:notaport"}):
            with pytest.raises(ValueError, match="Invalid port"):
                with pykx_connection():
                    pass  # pragma: no cover

    @patch("kdbx.connection.kx")
    def test_connection_closed_via_context_manager(self, mock_kx):
        """PyKX SyncQConnection.__exit__ is called to release the connection."""
        from kdbx.connection import pykx_connection

        mock_conn = _make_mock_sync_conn()
        mock_kx.SyncQConnection.return_value = mock_conn

        with patch.dict(os.environ, {"KDBX_ENDPOINT": "localhost:8082"}):
            with pykx_connection() as _conn:
                pass
            mock_conn.__exit__.assert_called_once()

    @patch("kdbx.connection.kx")
    def test_connection_closed_on_exception(self, mock_kx):
        """PyKX SyncQConnection.__exit__ is called even when body raises."""
        from kdbx.connection import pykx_connection

        mock_conn = _make_mock_sync_conn()
        mock_kx.SyncQConnection.return_value = mock_conn

        with patch.dict(os.environ, {"KDBX_ENDPOINT": "localhost:8082"}):
            with pytest.raises(RuntimeError):
                with pykx_connection() as _conn:
                    raise RuntimeError("boom")
            mock_conn.__exit__.assert_called_once()

    @patch("kdbx.connection.kx")
    def test_auth_env_vars_passed_through(self, mock_kx):
        """KDBX_USERNAME and KDBX_PASSWORD are passed to SyncQConnection."""
        from kdbx.connection import pykx_connection

        mock_conn = _make_mock_sync_conn()
        mock_kx.SyncQConnection.return_value = mock_conn

        env = {
            "KDBX_ENDPOINT": "remotehost:5001",
            "KDBX_USERNAME": "testuser",
            "KDBX_PASSWORD": "testpass",
        }
        with patch.dict(os.environ, env):
            with pykx_connection() as conn:
                assert conn is mock_conn
            mock_kx.SyncQConnection.assert_called_once_with(
                host="remotehost", port=5001, username="testuser", password="testpass"
            )

    @patch("kdbx.connection.kx")
    def test_no_auth_when_username_empty(self, mock_kx):
        """When KDBX_USERNAME is empty, username/password are not passed."""
        from kdbx.connection import pykx_connection

        mock_conn = _make_mock_sync_conn()
        mock_kx.SyncQConnection.return_value = mock_conn

        with patch.dict(os.environ, {"KDBX_ENDPOINT": "localhost:8082"}):
            os.environ.pop("KDBX_USERNAME", None)
            os.environ.pop("KDBX_PASSWORD", None)
            with pykx_connection() as conn:
                assert conn is mock_conn
            mock_kx.SyncQConnection.assert_called_once_with(host="localhost", port=8082)
