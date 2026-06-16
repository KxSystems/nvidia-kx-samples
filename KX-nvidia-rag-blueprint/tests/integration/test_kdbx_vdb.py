# SPDX-FileCopyrightText: Copyright (c) 2026 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Real KDB-X round-trip via PyKX. Requires the ``kdbx_endpoint`` fixture."""
from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture
def vdb(kdbx_endpoint):
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB
    from unittest.mock import MagicMock

    embedder = MagicMock()
    embedder.embed_documents.side_effect = lambda docs: [
        np.random.rand(128).astype(np.float32).tolist() for _ in docs
    ]
    embedder.embed_query.side_effect = lambda q: np.random.rand(128).astype(np.float32).tolist()

    vdb = KdbxVDB(kdbx_endpoint=kdbx_endpoint, embedding_model=embedder)
    yield vdb
    try:
        vdb.delete_collections(["it_test"])
    except Exception:
        pass


def test_full_lifecycle(vdb):
    # 1. Create collection
    vdb.create_collection("it_test", dimension=128)
    assert vdb.check_collection_exists("it_test")

    # 2. Insert documents
    docs = [f"document {i}" for i in range(50)]
    metas = [{"source": "test.pdf", "page": i} for i in range(50)]
    vdb.upload_text("it_test", docs, metas)

    # 3. Search — retrieval_langchain(query, collection_name, top_k)
    results = vdb.retrieval_langchain(query="hi", collection_name="it_test", top_k=5)
    assert len(results) == 5

    # 4. Delete collection
    vdb.delete_collections(["it_test"])
    assert not vdb.check_collection_exists("it_test")


# ---------------------------------------------------------------------------
# WP3 ship-readiness tests (docs/kdbx-ship-readiness-todo.md §5.2)
# ---------------------------------------------------------------------------

def _basis_embedder(dim: int):
    """Deterministic embedder: text 'doc <i>' -> one-hot basis vector e_i.

    Makes nearest-neighbour results ASSERTABLE (query 'doc 3' must return
    'doc 3' at distance 0) instead of the count-only checks random vectors
    allow.
    """
    from unittest.mock import MagicMock

    def _vec(text: str) -> list[float]:
        i = int(text.split()[-1]) % dim
        v = np.zeros(dim, dtype=np.float32)
        v[i] = 1.0
        return v.tolist()

    emb = MagicMock()
    emb.embed_documents.side_effect = lambda docs: [_vec(d) for d in docs]
    emb.embed_query.side_effect = _vec
    return emb


def _make_vdb(kdbx_endpoint, embedder):
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    return KdbxVDB(kdbx_endpoint=kdbx_endpoint, embedding_model=embedder)


def _entity_count(vdb, cname: str) -> int:
    rows = vdb.get_collection()
    for r in rows:
        if r.get("collection_name") == cname:
            return int(r.get("num_entities", -1))
    return -1


def test_restart_rehydrate_round_trip(kdbx_endpoint, kdbx_restart):
    """A collection must survive a kdbx restart intact (TODO 5.2a).

    Exercises the FULL persistence + rehydrate path against a real server:
    rows, metadata and the rebuilt index must serve identical results after
    `docker compose restart kdbx`.
    """
    cname = "it_rehydrate"
    vdb = _make_vdb(kdbx_endpoint, _basis_embedder(64))
    try:
        vdb.create_collection(cname, dimension=64)
        docs = [f"doc {i}" for i in range(40)]
        metas = [{"source": "rehydrate.pdf", "page": i} for i in range(40)]
        vdb.upload_text(cname, docs, metas)

        before = vdb.retrieval_langchain(query="doc 7", collection_name=cname, top_k=3)
        assert before and before[0].page_content == "doc 7"
        assert _entity_count(vdb, cname) == 40

        kdbx_restart()

        after = vdb.retrieval_langchain(query="doc 7", collection_name=cname, top_k=3)
        assert after and after[0].page_content == "doc 7", (
            "rehydrated index did not reproduce pre-restart results"
        )
        assert _entity_count(vdb, cname) == 40
    finally:
        try:
            vdb.delete_collections([cname])
        except Exception:
            pass


def test_delete_then_search_correctness(kdbx_endpoint):
    """Deleting a source removes its rows AND the index serves only the
    survivors — position remapping after row removal is a classic vector-DB
    bug source (TODO 5.2b)."""
    cname = "it_delete"
    vdb = _make_vdb(kdbx_endpoint, _basis_embedder(64))
    try:
        vdb.create_collection(cname, dimension=64)
        docs_a = [f"doc {i}" for i in range(20)]            # source a.pdf
        docs_b = [f"doc {i}" for i in range(20, 40)]        # source b.pdf
        vdb.upload_text(cname, docs_a, [{"source": "a.pdf"} for _ in docs_a])
        vdb.upload_text(cname, docs_b, [{"source": "b.pdf"} for _ in docs_b])
        assert _entity_count(vdb, cname) == 40

        assert vdb.delete_documents(cname, ["a.pdf"]) is True
        assert _entity_count(vdb, cname) == 20

        # A surviving doc must still be retrievable as the exact top hit...
        hit = vdb.retrieval_langchain(query="doc 25", collection_name=cname, top_k=3)
        assert hit and hit[0].page_content == "doc 25"
        # ...and nothing from the deleted source may surface.
        gone = vdb.retrieval_langchain(query="doc 5", collection_name=cname, top_k=10)
        returned = {d.page_content for d in gone}
        assert returned and returned.issubset(set(docs_b)), (
            f"deleted-source docs leaked back into search: {returned - set(docs_b)}"
        )
    finally:
        try:
            vdb.delete_collections([cname])
        except Exception:
            pass


def test_production_dimension_2048(kdbx_endpoint):
    """Insert + search at the production embedding dim (2048) — every other
    automated test uses toy dims (TODO 5.2)."""
    from unittest.mock import MagicMock

    cname = "it_dim2048"
    emb = MagicMock()
    emb.embed_documents.side_effect = lambda docs: [
        np.random.rand(2048).astype(np.float32).tolist() for _ in docs
    ]
    emb.embed_query.side_effect = lambda q: np.random.rand(2048).astype(np.float32).tolist()
    vdb = _make_vdb(kdbx_endpoint, emb)
    try:
        vdb.create_collection(cname, dimension=2048)
        vdb.upload_text(cname, [f"d{i}" for i in range(5)], [{} for _ in range(5)])
        out = vdb.retrieval_langchain(query="x", collection_name=cname, top_k=3)
        assert len(out) == 3
    finally:
        try:
            vdb.delete_collections([cname])
        except Exception:
            pass


def test_multibatch_upload(kdbx_endpoint):
    """upload_text slices into batches of 200 — the >1-batch path was never
    executed by any automated test (TODO 5.2)."""
    from unittest.mock import MagicMock

    cname = "it_multibatch"
    emb = MagicMock()
    emb.embed_documents.side_effect = lambda docs: [
        np.random.rand(16).astype(np.float32).tolist() for _ in docs
    ]
    emb.embed_query.side_effect = lambda q: np.random.rand(16).astype(np.float32).tolist()
    vdb = _make_vdb(kdbx_endpoint, emb)
    try:
        vdb.create_collection(cname, dimension=16)
        n = 450  # 3 batches: 200 + 200 + 50
        vdb.upload_text(cname, [f"doc {i}" for i in range(n)], [{} for _ in range(n)])
        assert _entity_count(vdb, cname) == n
    finally:
        try:
            vdb.delete_collections([cname])
        except Exception:
            pass
