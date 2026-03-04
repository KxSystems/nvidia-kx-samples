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
"""KDB-X connection helpers.

Provides a context-manager factory for PyKX IPC connections and
utilities for reading connection configuration from environment variables.

Environment variables
---------------------
KDBX_ENDPOINT : str
    ``host:port`` of the KDB-X instance.  Required unless
    ``KDBX_MODE=embedded`` (which defaults to ``localhost:8082``).
KDBX_MODE : str
    Either ``"ipc"`` (default) or ``"embedded"``.
KDBX_USERNAME : str
    Optional username for KDB-X authentication.
KDBX_PASSWORD : str
    Optional password for KDB-X authentication.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import pykx as kx

logger = logging.getLogger(__name__)

_DEFAULT_MODE = "ipc"


def _parse_endpoint(endpoint: str) -> tuple[str, int]:
    """Parse a ``host:port`` string and return ``(host, port)``.

    Raises
    ------
    ValueError
        If the string is not in ``host:port`` format or the port is not a
        valid integer in the range 0--65535.
    """
    if ":" not in endpoint:
        raise ValueError(f"Expected 'host:port' format, got {endpoint!r}")

    host, port_str = endpoint.rsplit(":", 1)

    try:
        port = int(port_str)
    except ValueError:
        raise ValueError(
            f"Invalid port {port_str!r} in endpoint {endpoint!r}: port must be a number"
        ) from None

    if port < 0 or port > 65535:
        raise ValueError(
            f"Invalid port {port} in endpoint {endpoint!r}: port must be in range 0-65535"
        )

    return host, port


def get_kdbx_mode() -> str:
    """Return the KDB-X connection mode from the ``KDBX_MODE`` env var.

    Returns ``"ipc"`` (default) or ``"embedded"``.
    """
    return os.environ.get("KDBX_MODE", _DEFAULT_MODE)


@contextmanager
def pykx_connection() -> Generator[kx.SyncQConnection, None, None]:
    """Context manager that yields a :class:`pykx.SyncQConnection`.

    The connection endpoint is read from the ``KDBX_ENDPOINT`` environment
    variable (default ``localhost:8082``).

    Usage::

        with pykx_connection() as q:
            result = q("select from trade")
    """
    endpoint = os.environ.get("KDBX_ENDPOINT", "")
    if not endpoint:
        mode = get_kdbx_mode()
        if mode == "embedded":
            endpoint = "localhost:8082"
        else:
            raise RuntimeError(
                "KDBX_ENDPOINT environment variable is required "
                "(set KDBX_MODE=embedded to allow localhost default)"
            )
    host, port = _parse_endpoint(endpoint)

    username = os.environ.get("KDBX_USERNAME", "")
    password = os.environ.get("KDBX_PASSWORD", "")

    kwargs: dict[str, Any] = {"host": host, "port": port}
    if username:
        kwargs["username"] = username
        kwargs["password"] = password

    logger.info("Connecting to KDB-X at %s:%d", host, port)
    with kx.SyncQConnection(**kwargs) as conn:
        try:
            yield conn
        finally:
            logger.info("Closed KDB-X connection to %s:%d", host, port)
