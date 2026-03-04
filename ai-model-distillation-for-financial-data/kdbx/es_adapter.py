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
"""KDB-X adapter replacing Elasticsearch for embeddings and vector search.

Drop-in replacement for the 6 public functions in
``src/lib/integration/es_client.py``, backed by KDB-X tables for
persistence and native HNSW vector search via the KDB-X AI module.

Public API
----------
get_es_client()              -> KDBXClient
close_es_client()            -> None
ensure_embeddings_index()    -> None  (no-op)
index_embeddings_to_es()     -> str   (index_name)
search_similar_embeddings()  -> list[tuple[float, str, dict]]
delete_embeddings_index()    -> None

Module-level state
------------------
_kdbx_client      : singleton KDBXClient (or None)
_metadata_cache    : dict mapping index_name -> (tool_names, records)

KDB-X server-side state (persists across connections)
-----------------------------------------------------
.hnsw.idx          : dict mapping index_name symbol -> HNSW index object
.hnsw.vecs         : dict mapping index_name symbol -> real[][] vector matrix
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import UTC as _UTC
from datetime import datetime
from typing import Any

import numpy as np
import pykx as kx

from kdbx.connection import pykx_connection
from kdbx.schema import create_all_tables
from src.lib.flywheel.util import extract_user_query

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMBEDDING_DIMS: int = 2048

# HNSW hyperparameters
_HNSW_M: int = 32       # graph connectivity (higher = more accurate, slower build)
_HNSW_EF: int = 64      # construction beam width
_HNSW_EFS: int = 64     # search beam width

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_kdbx_client: KDBXClient | None = None  # noqa: F821 — forward ref resolved below
_metadata_cache: dict[str, tuple[list[str], list[dict[str, Any]]]] = {}
# index_name -> (tool_names, records)


# ---------------------------------------------------------------------------
# KDBXClient — lightweight wrapper so callers have a client object
# ---------------------------------------------------------------------------


class KDBXClient:
    """Thin wrapper returned by :func:`get_es_client`.

    Provides a ``ping()`` method for compatibility with code that
    checks ``client.ping()`` (mirroring ``Elasticsearch.ping()``).
    """

    def ping(self) -> bool:
        """Always returns ``True`` — KDB-X liveness is checked at connect time."""
        return True


# Fix the forward reference now that the class is defined.
_kdbx_client = None


# ---------------------------------------------------------------------------
# 1. get_es_client
# ---------------------------------------------------------------------------


def get_es_client() -> KDBXClient:
    """Return a :class:`KDBXClient` singleton, creating tables on first call.

    Retry logic mirrors the original Elasticsearch adapter: up to 30
    attempts with 1-second sleeps.
    """
    global _kdbx_client

    if _kdbx_client is not None:
        return _kdbx_client

    with _lock:
        # Double-check after acquiring lock.
        if _kdbx_client is not None:
            return _kdbx_client

        for attempt in range(30):
            try:
                with pykx_connection() as q:
                    q("1b")  # lightweight ping
                logger.info("KDB-X is reachable (attempt %d)", attempt + 1)
                _kdbx_client = KDBXClient()
                create_all_tables()
                _init_hnsw_module()
                return _kdbx_client
            except Exception:
                if attempt == 29:
                    msg = "Could not connect to KDB-X after 30 attempts"
                    logger.error(msg)
                    raise RuntimeError(msg)
                time.sleep(1)

    msg = "KDB-X did not become healthy in time"
    logger.error(msg)
    raise RuntimeError(msg)


def _init_hnsw_module() -> None:
    """Load the KDB-X AI module and initialise HNSW storage globals."""
    with pykx_connection() as q:
        q("if[not `.ai in key `; .ai:use`kx.ai]")
        q("if[not `.hnsw in key `; .hnsw.idx:(`symbol$())!(); .hnsw.vecs:.hnsw.idx]")
    logger.info("KDB-X AI module loaded, HNSW storage initialised")
    _rebuild_hnsw_from_table()


def _rebuild_hnsw_from_table() -> None:
    """Rebuild HNSW indexes from persisted ``flywheel_embeddings`` rows.

    On KDB-X restart the in-memory ``.hnsw.idx`` / ``.hnsw.vecs`` globals
    are lost, but the embedding data survives in the table.  This function
    scans for any existing index names and rebuilds the HNSW indexes +
    Python-side metadata cache so search works immediately after restart.
    """
    with pykx_connection() as q:
        names = q("exec distinct index_name from flywheel_embeddings")

    index_names: list[str] = []
    try:
        index_names = [str(n) for n in names]
    except TypeError:
        pass  # empty table

    if not index_names:
        return

    logger.info("Rebuilding %d HNSW index(es) from persisted data", len(index_names))

    for idx_name in index_names:
        with pykx_connection() as q:
            rows = q(
                "{[name] select embedding, tool_name, record "
                "from flywheel_embeddings where index_name = name}",
                kx.SymbolAtom(idx_name),
            )

            embeddings = rows["embedding"]
            tool_syms = rows["tool_name"]
            record_jsons = rows["record"]

        # Convert to Python lists
        tool_names = [str(t) for t in tool_syms]
        records: list[dict[str, Any]] = []
        for r in record_jsons:
            try:
                records.append(json.loads(str(r)))
            except (json.JSONDecodeError, TypeError):
                records.append({})

        if not tool_names:
            _metadata_cache[idx_name] = ([], [])
            continue

        # Build vector matrix and HNSW index
        mat = np.array([list(e) for e in embeddings], dtype=np.float32)
        with pykx_connection() as q:
            q(
                "{[name;vecs;M;ef] "
                ".hnsw.vecs[name]: `real$vecs; "
                ".hnsw.idx[name]: .ai.hnsw.put[(); (); `real$vecs; `CS; M; 1%log M; ef]}",
                kx.SymbolAtom(idx_name),
                mat,
                _HNSW_M,
                _HNSW_EF,
            )

        _metadata_cache[idx_name] = (tool_names, records)
        logger.info(
            "Rebuilt HNSW index %s (%d vectors)", idx_name, len(tool_names),
        )


# ---------------------------------------------------------------------------
# 2. close_es_client
# ---------------------------------------------------------------------------


def close_es_client() -> None:
    """Clear the global client reference and caches."""
    global _kdbx_client, _metadata_cache
    with _lock:
        _kdbx_client = None
        _metadata_cache = {}


# ---------------------------------------------------------------------------
# 3. ensure_embeddings_index
# ---------------------------------------------------------------------------


def ensure_embeddings_index(client: Any, index_name: str) -> None:
    """No-op.  The ``flywheel_embeddings`` table is created at startup by
    :func:`get_es_client` via :func:`create_all_tables`.  HNSW indexes
    are built per-workflow inside :func:`index_embeddings_to_es`.
    """


# ---------------------------------------------------------------------------
# 4. index_embeddings_to_es
# ---------------------------------------------------------------------------


def index_embeddings_to_es(
    client: Any,
    binned_data: dict[str, list[tuple[list[float], dict[str, Any]]]],
    workload_id: str,
    client_id: str,
) -> str:
    """Insert embeddings into KDB-X and build a native HNSW index.

    Embeddings are persisted to the ``flywheel_embeddings`` table and a
    native HNSW index is built server-side in the KDB-X process for fast
    approximate nearest-neighbour search.

    Parameters
    ----------
    client:
        Ignored (kept for API compatibility).
    binned_data:
        ``{tool_name: [(embedding_vector, record), ...]}``
    workload_id, client_id:
        Used to build the unique ``index_name``.

    Returns
    -------
    str
        The generated ``index_name`` (used to look up the cache later).
    """
    ts = int(datetime.now(tz=_UTC).timestamp())
    index_name = f"flywheel_embeddings_index_{workload_id}_{client_id}_{ts}"

    all_vecs: list[list[float]] = []
    all_tool_names: list[str] = []
    all_records: list[dict[str, Any]] = []

    with pykx_connection() as q:
        for tool_name, examples in binned_data.items():
            for embedding_vector, record in examples:
                user_query = extract_user_query(record)
                doc_id = (
                    f"{tool_name}_{hash(user_query)}"
                    f"_{record.get('timestamp', time.time())}"
                )

                # Persist row in KDB-X table
                q(
                    "{[d;idx;emb;tn;qt;rid;ts;rec] "
                    "`flywheel_embeddings insert "
                    "`doc_id`index_name`embedding`tool_name"
                    "`query_text`record_id`timestamp`record!"
                    "(d;idx;emb;tn;qt;rid;ts;rec)}",
                    kx.SymbolAtom(doc_id),
                    kx.SymbolAtom(index_name),
                    embedding_vector,
                    kx.SymbolAtom(tool_name),
                    str(user_query) if user_query else "",
                    kx.SymbolAtom(str(record.get("workload_id", ""))),
                    record.get("timestamp", 0),
                    json.dumps(record),
                )

                all_vecs.append(embedding_vector)
                all_tool_names.append(tool_name)
                all_records.append(record)

    # Build native HNSW index server-side in KDB-X
    if all_vecs:
        mat = np.array(all_vecs, dtype=np.float32)
        with pykx_connection() as q:
            q(
                "{[name;vecs;M;ef] "
                ".hnsw.vecs[name]: `real$vecs; "
                ".hnsw.idx[name]: .ai.hnsw.put[(); (); `real$vecs; `CS; M; 1%log M; ef]}",
                kx.SymbolAtom(index_name),
                mat,
                _HNSW_M,
                _HNSW_EF,
            )
        with _lock:
            _metadata_cache[index_name] = (all_tool_names, all_records)
    else:
        with _lock:
            _metadata_cache[index_name] = ([], [])

    logger.info(
        "Indexed %d embeddings into %s (HNSW)", len(all_vecs), index_name
    )
    return index_name


# ---------------------------------------------------------------------------
# 5. search_similar_embeddings
# ---------------------------------------------------------------------------


def search_similar_embeddings(
    client: Any,
    query_embedding: list[float],
    index_name: str,
    max_candidates: int = 50,
) -> list[tuple[float, str, dict[str, Any]]]:
    """Search for similar embeddings using native HNSW vector search.

    Parameters
    ----------
    client:
        Ignored (kept for API compatibility).
    query_embedding:
        The query vector.
    index_name:
        Must match a key previously stored via ``index_embeddings_to_es``.
    max_candidates:
        Number of nearest neighbours to return.

    Returns
    -------
    list[tuple[float, str, dict]]
        ``(score, tool_name, record)`` triples, best match first.
        Returns ``[]`` if *index_name* is not in the cache.
    """
    with _lock:
        if index_name not in _metadata_cache:
            return []
        tool_names, records = _metadata_cache[index_name]

    if not tool_names:
        return []

    k = min(max_candidates, len(tool_names))
    if k == 0:
        return []

    qvec = np.array(query_embedding, dtype=np.float32)

    with pykx_connection() as q:
        res = q(
            "{[name;qvec;k;efs] "
            ".ai.hnsw.search["
            ".hnsw.vecs[name]; .hnsw.idx[name]; `real$qvec; k; `CS; efs]}",
            kx.SymbolAtom(index_name),
            qvec,
            k,
            _HNSW_EFS,
        )

    # HNSW search returns (scores, indices) — CS metric, higher = better
    scores = res[0].np()
    indices = res[1].np()

    return [
        (float(scores[i]), tool_names[int(idx)], records[int(idx)])
        for i, idx in enumerate(indices)
    ]


# ---------------------------------------------------------------------------
# 6. delete_embeddings_index
# ---------------------------------------------------------------------------


def delete_embeddings_index(client: Any, index_name: str) -> None:
    """Delete rows from ``flywheel_embeddings`` and clean up the HNSW index.

    Parameters
    ----------
    client:
        Ignored (kept for API compatibility).
    index_name:
        The index to remove.
    """
    with pykx_connection() as q:
        q(
            "{[idx] delete from `flywheel_embeddings where index_name = idx}",
            kx.SymbolAtom(index_name),
        )
        q(
            "{[name] "
            "if[name in key .hnsw.idx; "
            ".hnsw.idx: name _ .hnsw.idx; "
            ".hnsw.vecs: name _ .hnsw.vecs]}",
            kx.SymbolAtom(index_name),
        )

    with _lock:
        _metadata_cache.pop(index_name, None)
    logger.info("Deleted embeddings index: %s", index_name)
