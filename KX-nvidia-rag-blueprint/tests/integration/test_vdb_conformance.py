# SPDX-FileCopyrightText: Copyright (c) 2026 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Parametrized VDB conformance test — exercises KdbxVDB (and optionally KdbaiVDB)
against the same lifecycle contract.

VDB selection
-------------
- ``kdbx``   — always present when the ``kdbx_endpoint`` fixture resolves.
- ``kdbai``  — present only when the ``KDBAI_ENDPOINT`` env var is set.

SCOPE NOTE (review-2): CI never sets ``KDBAI_ENDPOINT``, so in practice this
suite only exercises the kdbx leg there — the kdbai parametrization runs in
environments with a live KDB.AI endpoint. Each backend is also checked in
ISOLATION against the lifecycle contract; no cross-backend result-equivalence
is asserted (that would require both backends live with identical data).

Deviations from plan (KdbaiVDB API differences)
------------------------------------------------
- KdbaiVDB.__init__ requires ``collection_name`` (positional) and ``kdbai_endpoint``
  as mandatory keyword args, plus an optional ``api_key``.  KdbxVDB requires only
  ``kdbx_endpoint``.  The fixture handles both shapes.
- KdbaiVDB.retrieval_langchain accepts an extra ``vectorstore`` arg (unused in
  tests) — calling with positional ``query, collection_name, top_k`` works for both.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import numpy as np
import pytest

_COLLECTION = "conformance_test"
_DIM = 128


# ---------------------------------------------------------------------------
# VDB fixtures
# ---------------------------------------------------------------------------


def _make_embedder(dim: int = _DIM) -> MagicMock:
    embedder = MagicMock()
    embedder.embed_documents.side_effect = lambda docs: [
        np.random.rand(dim).astype(np.float32).tolist() for _ in docs
    ]
    embedder.embed_query.side_effect = lambda q: np.random.rand(dim).astype(np.float32).tolist()
    return embedder


@pytest.fixture
def kdbx_vdb(kdbx_endpoint):
    """KdbxVDB backed by the integration KDB-X server."""
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    vdb = KdbxVDB(kdbx_endpoint=kdbx_endpoint, embedding_model=_make_embedder())
    yield vdb
    try:
        vdb.delete_collections([_COLLECTION])
    except Exception:
        pass


@pytest.fixture
def kdbai_vdb():
    """KdbaiVDB backed by a KDB.AI server — skipped when KDBAI_ENDPOINT is not set.

    Deviation: KdbaiVDB.__init__ requires collection_name (positional, first arg)
    and kdbai_endpoint; KdbxVDB does not require collection_name at construction.
    """
    endpoint = os.environ.get("KDBAI_ENDPOINT", "").strip()
    if not endpoint:
        pytest.skip("KDBAI_ENDPOINT not set — skipping kdbai conformance test.")

    from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

    api_key = os.environ.get("KDBAI_API_KEY", None)
    vdb = KdbaiVDB(
        collection_name=_COLLECTION,
        kdbai_endpoint=endpoint,
        api_key=api_key,
        embedding_model=_make_embedder(),
    )
    yield vdb
    try:
        vdb.delete_collections([_COLLECTION])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Conformance tests — parametrize over available VDB fixtures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("vdb_fixture", ["kdbx_vdb", "kdbai_vdb"])
def test_conformance_create_collection(request, vdb_fixture):
    """Creating a collection must make check_collection_exists return True."""
    vdb = request.getfixturevalue(vdb_fixture)
    try:
        vdb.delete_collections([_COLLECTION])
    except Exception:
        pass

    vdb.create_collection(_COLLECTION, dimension=_DIM)
    assert vdb.check_collection_exists(_COLLECTION)
    vdb.delete_collections([_COLLECTION])


@pytest.mark.parametrize("vdb_fixture", ["kdbx_vdb", "kdbai_vdb"])
def test_conformance_upload_and_search(request, vdb_fixture):
    """Uploading documents and searching must return the requested top_k results."""
    vdb = request.getfixturevalue(vdb_fixture)
    try:
        vdb.delete_collections([_COLLECTION])
    except Exception:
        pass

    vdb.create_collection(_COLLECTION, dimension=_DIM)

    docs = [f"conformance document {i}" for i in range(20)]
    metas = [{"source": "conformance.pdf", "page": i} for i in range(20)]
    vdb.upload_text(_COLLECTION, docs, metas)

    results = vdb.retrieval_langchain(
        query="conformance",
        collection_name=_COLLECTION,
        top_k=5,
    )
    assert len(results) == 5, f"Expected 5 results, got {len(results)}"

    vdb.delete_collections([_COLLECTION])
    assert not vdb.check_collection_exists(_COLLECTION)


@pytest.mark.parametrize("vdb_fixture", ["kdbx_vdb", "kdbai_vdb"])
def test_conformance_delete_nonexistent(request, vdb_fixture):
    """Deleting a collection that does not exist should not raise."""
    vdb = request.getfixturevalue(vdb_fixture)
    # Ensure it doesn't exist first
    try:
        vdb.delete_collections(["nonexistent_conformance_xyz"])
    except Exception as exc:
        pytest.fail(f"delete_collections raised on non-existent collection: {exc}")
