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
    """Get the KDB-X database instance."""
    global _db
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _db


def init_db() -> KDBXDatabase:
    """Initialize KDB-X connection and create tables."""
    global _db

    # Return existing instance if available
    if _db is not None:
        return _db

    for attempt in range(30):
        try:
            with pykx_connection() as q:
                q("1+1")  # lightweight health check
            logger.info("KDB-X is reachable (attempt %d)", attempt + 1)
            create_all_tables()
            _db = KDBXDatabase()
            return _db
        except Exception:
            if attempt == 29:
                msg = "Could not connect to KDB-X after 30 attempts"
                logger.error(msg)
                raise RuntimeError(msg)
            time.sleep(1)

    msg = "KDB-X did not become healthy in time"
    logger.error(msg)
    raise RuntimeError(msg)


def close_db() -> None:
    """Close the KDB-X database connection."""
    global _db
    _db = None
