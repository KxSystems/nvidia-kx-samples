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
"""Persisted selection of the KDB-X vector collection the kdb_docs agent searches.

Single global app setting, stored in Redis (key below). Falls back to the
KDB_VECTOR_TABLE env var when Redis holds no value (back-compat with the
deploy-time default). Used by KdbDocsSource.is_available() and .run().
"""
import logging
import os

logger = logging.getLogger(__name__)

_REDIS_KEY = "kxta:settings:kdb_vector_table"
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
            logger.warning("kdb_docs_settings: Redis unavailable (%s); env fallback only", e)
            return None
    return _redis_client


def get_selected_collection() -> str | None:
    """Selected collection name: Redis value if set, else KDB_VECTOR_TABLE env, else None."""
    c = _client()
    if c is not None:
        try:
            v = c.get(_REDIS_KEY)
            if v and v.strip():
                return v.strip()
        except Exception as e:  # noqa: BLE001
            logger.warning("kdb_docs_settings: Redis get failed (%s); env fallback", e)
    env = os.getenv("KDB_VECTOR_TABLE", "").strip()
    return env or None


def set_selected_collection(name: str | None) -> str | None:
    """Persist the selection (or clear it when name is falsy). Returns the resolved value.

    Raises RuntimeError when Redis is unavailable (the selection cannot be persisted).
    """
    c = _client()
    if c is None:
        raise RuntimeError("Redis unavailable: cannot persist KDB-X document collection selection")
    try:
        if name and name.strip():
            c.set(_REDIS_KEY, name.strip())
        else:
            c.delete(_REDIS_KEY)
    except Exception as e:  # noqa: BLE001
        global _redis_client
        _redis_client = None  # allow reconnect on next call
        raise RuntimeError(f"Failed to persist KDB-X document collection selection: {e}")
    return get_selected_collection()
