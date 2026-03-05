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

import logging
import time

from kdbx.compat import KDBXDatabase
from kdbx.connection import pykx_connection
from kdbx.schema import create_all_tables

logger = logging.getLogger(__name__)

# Global database instance
_db: KDBXDatabase | None = None


def get_db() -> KDBXDatabase:
    """Get the KDB-X database instance, initializing lazily if needed."""
    global _db
    if _db is None:
        init_db()
    return _db


def init_db() -> KDBXDatabase | None:
    """Initialize KDB-X connection and create tables.

    Returns the database instance on success, or ``None`` if KDB-X is
    unreachable after all retry attempts.  This allows Celery workers to
    start even when KDB-X is not yet ready — ``get_db()`` will retry on
    the next task invocation.
    """
    global _db

    # Return existing instance if available
    if _db is not None:
        return _db

    for attempt in range(60):
        try:
            with pykx_connection() as q:
                q("1+1")  # lightweight health check
            logger.info("KDB-X is reachable (attempt %d)", attempt + 1)
            create_all_tables()
            _db = KDBXDatabase()
            return _db
        except Exception:
            if attempt == 59:
                logger.warning(
                    "Could not connect to KDB-X after 60 attempts; "
                    "will retry on next request"
                )
                return None
            time.sleep(1)

    return None


def close_db() -> None:
    """Close the KDB-X database connection."""
    global _db
    _db = None
