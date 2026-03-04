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
"""Shared fixtures for kdbx unit tests.

The ``mock_pykx_connection`` fixture patches ``kdbx.connection.pykx_connection``
so that downstream test modules (schema, compat, etc.) never need a real KDB-X
instance.

We override the parent-level ``mock_db_functions`` autouse fixture that is not
relevant to the kdbx layer.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Override parent-level autouse fixture that fails outside the src context
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_db_functions():
    """No-op override of the parent-level ``mock_db_functions`` fixture."""
    yield


# ---------------------------------------------------------------------------
# Shared mock_pykx_connection fixture for kdbx tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_pykx_connection():
    """Patch ``kdbx.connection.pykx_connection`` to yield a ``MagicMock``.

    Usage in tests::

        def test_something(mock_pykx_connection):
            conn = mock_pykx_connection  # the MagicMock connection object
            conn("select from trade").return_value = ...
    """
    mock_conn = MagicMock(name="SyncQConnection")

    @contextmanager
    def _fake_ctx():
        yield mock_conn

    with patch("kdbx.connection.pykx_connection", _fake_ctx):
        yield mock_conn
