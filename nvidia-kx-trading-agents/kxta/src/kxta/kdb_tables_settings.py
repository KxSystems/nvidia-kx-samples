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
"""Persisted selection of the KDB-X tables the kdb (time-series) agent may see.

Mirrors kdb_docs_settings: a single global app setting stored in Redis (key below),
falling back to the KDB_VISIBLE_TABLES env var when Redis holds no value. Consumed by
kdb_tools_nat._visible_tables() to narrow the allowlist to the user's selection.
"""
import logging
import os

logger = logging.getLogger(__name__)

_REDIS_KEY = "kxta:settings:kdb_visible_tables"
_redis_client = None


def _client():
    """Return a connected redis client, or None if Redis is unavailable."""
    global _redis_client
    if _redis_client is None:
        try:
            import redis
            url = os.getenv("REDIS_URL", "redis://localhost:6379")
            c = redis.from_url(url, decode_responses=True)
            c.ping()
            _redis_client = c
        except Exception as e:  # noqa: BLE001
            logger.warning("kdb_tables_settings: Redis unavailable (%s); env fallback only", e)
            return None
    return _redis_client


def _split(raw: str) -> list[str]:
    return [t.strip() for t in raw.split(",") if t.strip()]


def get_selected_tables() -> list[str]:
    """Selected table names: Redis value if set, else KDB_VISIBLE_TABLES env, else []."""
    c = _client()
    if c is not None:
        try:
            v = c.get(_REDIS_KEY)
            if v and v.strip():
                return _split(v)
        except Exception as e:  # noqa: BLE001
            logger.warning("kdb_tables_settings: Redis get failed (%s); env fallback", e)
    return _split(os.getenv("KDB_VISIBLE_TABLES", "").strip())


def set_selected_tables(tables: list[str]) -> list[str]:
    """Persist the selection (or clear it when empty). Returns the resolved value.

    Raises RuntimeError when Redis is unavailable (the selection cannot be persisted).
    """
    c = _client()
    if c is None:
        raise RuntimeError("Redis unavailable: cannot persist KDB-X table selection")
    cleaned = [t.strip() for t in (tables or []) if t and t.strip()]
    try:
        if cleaned:
            c.set(_REDIS_KEY, ",".join(cleaned))
        else:
            c.delete(_REDIS_KEY)
    except Exception as e:  # noqa: BLE001
        global _redis_client
        _redis_client = None  # allow reconnect on next call
        raise RuntimeError(f"Failed to persist KDB-X table selection: {e}")
    return get_selected_tables()
