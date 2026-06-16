# SPDX-FileCopyrightText: Copyright (c) 2026 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for KdbxVDB. PyKX is mocked — no real KDB-X required."""

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub out langchain_openai before nvidia_rag.__init__ tries to import it.
# The installed version is incompatible with the installed langchain_core and
# raises ImportError(ModelProfileRegistry) — which nvidia_rag.__init__ only
# catches if it's a ModuleNotFoundError.  A stub module avoids the crash.
# ---------------------------------------------------------------------------
if "langchain_openai" not in sys.modules:
    _fake_loai = types.ModuleType("langchain_openai")
    _fake_loai.ChatOpenAI = MagicMock()
    _fake_loai.AzureChatOpenAI = MagicMock()
    sys.modules["langchain_openai"] = _fake_loai
    sys.modules["langchain_openai.chat_models"] = _fake_loai

# Save the real _assert_server_ready at import time, before any fixture patches it.
# patch.object replaces the class attribute, not the function object itself, so
# this reference stays valid for the duration of the test session.
from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB as _KdbxVDB  # noqa: E402
_REAL_ASSERT_SERVER_READY = _KdbxVDB._assert_server_ready


@pytest.fixture(autouse=True)
def _skip_server_ready_check():
    """No-op the server-ready check for operation tests.

    _assert_server_ready() calls .rag.ping[] and would add an extra conn()
    call that perturbs call-count accounting in operation tests. Operation
    tests are not testing readiness detection; that is covered by the
    dedicated test_assert_server_ready_* tests in this module.
    """
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    with patch.object(KdbxVDB, "_assert_server_ready", lambda self, conn: None):
        yield


@pytest.fixture
def mock_qconn():
    """Patch pykx.SyncQConnection.

    KdbxVDB now uses per-call SyncQConnection inside a `with` block. Return a
    MagicMock that supports both the context-manager protocol and being called
    as `conn(expr)`. `mock_qconn.return_value` and `.side_effect` set what
    `conn(expr)` returns/raises on each call; `mock_qconn.call_count` counts
    `conn(expr)` invocations.
    """
    with patch("pykx.SyncQConnection") as cls:
        conn = MagicMock()
        # `with self._connect() as conn:` — make __enter__ return the same mock.
        cm = MagicMock()
        cm.__enter__.return_value = conn
        cm.__exit__.return_value = False
        cls.return_value = cm
        yield conn


def test_assert_server_ready_raises_when_not_bootstrapped(mock_qconn):
    """_assert_server_ready raises KdbxNotBootstrappedError if .rag.ping fails."""
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxNotBootstrappedError, KdbxVDB

    mock_qconn.return_value = MagicMock(py=lambda: b"0")
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000", embedding_model=None)
    # Call the real (unpatched) implementation directly — the autouse fixture
    # replaced the class attribute, but _REAL_ASSERT_SERVER_READY holds the
    # original function object captured at module import time.
    with pytest.raises(KdbxNotBootstrappedError, match="kdbx-init.q"):
        _REAL_ASSERT_SERVER_READY(vdb, mock_qconn)


def test_assert_server_ready_succeeds_when_ping_ok(mock_qconn):
    """_assert_server_ready sets _server_ready when .rag.ping returns true."""
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    mock_qconn.return_value = MagicMock(py=lambda: b"1")
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000", embedding_model=None)
    assert not vdb._server_ready
    _REAL_ASSERT_SERVER_READY(vdb, mock_qconn)
    assert vdb._server_ready


def test_constructor_parses_endpoint(mock_qconn):
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000", embedding_model=None)
    assert vdb._host == "kdbx"
    assert vdb._port == 5000


def test_constructor_accepts_url_form(mock_qconn):
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    vdb = KdbxVDB(kdbx_endpoint="kdbx://my-host:5050", embedding_model=None)
    assert vdb._host == "my-host"
    assert vdb._port == 5050


def test_no_persistent_connection(mock_qconn):
    """We now open a fresh SyncQConnection per call (no cached self._conn)."""
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    mock_qconn.return_value = "ok"
    # Two _q calls should open two fresh connections.
    vdb._q("`a")
    vdb._q("`b")
    # SyncQConnection should be constructed twice.
    import pykx
    assert pykx.SyncQConnection.call_count == 2


def test_retry_on_connection_error(mock_qconn):
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    # First two calls raise a connection error, third succeeds
    mock_qconn.side_effect = [ConnectionError("dead"), ConnectionError("dead"), "ok"]
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    result = vdb._q("`ping")
    assert result == "ok"
    assert mock_qconn.call_count == 3


def test_q_error_no_retry(mock_qconn):
    import pykx

    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxQError, KdbxVDB

    mock_qconn.side_effect = pykx.QError("'type")
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    with pytest.raises(KdbxQError):
        vdb._q("bad expr")
    assert mock_qconn.call_count == 1  # no retry on q-side error


def test_q_reconnects_on_stale_pykx_exception(mock_qconn):
    """pykx wraps broken IPC as PyKXException('Connection error') — must reconnect."""
    import pykx

    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    mock_qconn.side_effect = [
        pykx.PyKXException("Authentication error"),
        pykx.PyKXException("Connection error"),
        "ok",
    ]
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    result = vdb._q("`ping")
    assert result == "ok"
    assert mock_qconn.call_count == 3


def test_q_retries_against_starting_pod(mock_qconn):
    """Kdbx still starting — first 2 fresh connects fail, third succeeds."""
    import pykx

    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    # Sequence: 1st call fails → 2nd call fails → 3rd call succeeds.
    mock_qconn.side_effect = [
        pykx.PyKXException("Connection error"),
        pykx.PyKXException("Connection error"),
        "pong",                                  # finally connects
    ]
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    assert vdb._q("`ping") == "pong"


def test_q_qerror_signals_still_propagate(mock_qconn):
    """q-side signals must NOT be retried — they're not transient."""
    import pykx

    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxQError, KdbxVDB

    mock_qconn.side_effect = pykx.QError("'length")
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    with pytest.raises(KdbxQError):
        vdb._q("bad")
    assert mock_qconn.call_count == 1


# NB (TODO 5.3): translate_filter is a BUILDING BLOCK that is not yet wired
# into the adapter — retrieval_langchain currently REJECTS every non-empty
# filter (see test_retrieval_langchain_rejects_nonempty_filter). These tests
# pin the translator's contract for when filter support lands; a green run
# here does NOT mean the kdbx backend supports filtering.
def test_filter_eq():
    from nvidia_rag.utils.vdb.kdbx.kdbx_filters import translate_filter
    f = {"key": "source", "op": "==", "value": "doc.pdf"}
    # Expected q functional-select where clause: enlist (=; `source; enlist "doc.pdf")
    assert translate_filter(f) == [["=", "source", ["doc.pdf"]]]


def test_filter_and():
    from nvidia_rag.utils.vdb.kdbx.kdbx_filters import translate_filter
    f = {"op": "and", "args": [
        {"key": "source", "op": "==", "value": "doc.pdf"},
        {"key": "page", "op": ">", "value": 5},
    ]}
    out = translate_filter(f)
    # AND in q functional select = list of where-clauses (implicit AND)
    assert out == [["=", "source", ["doc.pdf"]], [">", "page", 5]]


def test_filter_in():
    from nvidia_rag.utils.vdb.kdbx.kdbx_filters import translate_filter
    f = {"key": "page", "op": "in", "value": [1, 2, 3]}
    assert translate_filter(f) == [["in", "page", [1, 2, 3]]]


# ---------------------------------------------------------------------------
# Task 14 — create/check/delete collection
# ---------------------------------------------------------------------------


def test_create_collection_calls_q(mock_qconn):
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    vdb.create_collection("mycoll", dimension=128)
    call = mock_qconn.call_args
    args_str = str(call)
    assert ".rag.createCollection" in args_str
    assert "mycoll" in args_str
    assert "128" in args_str


def test_check_collection_exists(mock_qconn):
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB
    mock_qconn.return_value = True
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    assert vdb.check_collection_exists("mycoll") is True


def test_delete_collections(mock_qconn):
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB
    mock_qconn.return_value = True
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    result = vdb.delete_collections(["a", "b"])
    assert mock_qconn.call_count == 2
    # CollectionsResponse(**result) shape required by ingestor's DELETE handler.
    assert result["successful"] == ["a", "b"]
    assert result["failed"] == []
    assert result["total_success"] == 2
    assert result["total_failed"] == 0
    assert "message" in result


def test_delete_collections_records_failures(mock_qconn):
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB
    # Second call raises; the first succeeds.
    mock_qconn.side_effect = [True, RuntimeError("boom")]
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    result = vdb.delete_collections(["a", "b"])
    assert result["successful"] == ["a"]
    assert result["total_success"] == 1
    assert result["total_failed"] == 1
    assert result["failed"][0]["collection_name"] == "b"
    assert "boom" in result["failed"][0]["error_message"]


# ---------------------------------------------------------------------------
# Task 15 — upload_text
# ---------------------------------------------------------------------------


def test_upload_text_batches_and_inserts(mock_qconn):
    import numpy as np

    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    vdb._embedding_model = MagicMock()
    vdb._embedding_model.embed_documents.return_value = [
        np.zeros(128, dtype=np.float32).tolist() for _ in range(5)
    ]
    docs = [f"doc {i}" for i in range(5)]
    metas = [{"source": f"f{i}.pdf"} for i in range(5)]
    vdb.upload_text("mycoll", docs, metas)
    args_str = str(mock_qconn.call_args)
    assert ".rag.insert" in args_str


def test_upload_text_raises_without_embedding_model(mock_qconn):
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    with pytest.raises(ValueError, match="embedding_model"):
        vdb.upload_text("mycoll", ["doc"])


def test_index_type_preference_resolution(mock_qconn):
    """WS2: the two kdbai-style GPU toggles collapse to one cagra/hnsw choice."""
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB
    assert KdbxVDB(kdbx_endpoint="k:5000")._index_type == "hnsw"
    assert KdbxVDB(kdbx_endpoint="k:5000", index_type="cagra")._index_type == "cagra"
    assert KdbxVDB(kdbx_endpoint="k:5000", enable_gpu_index=True)._index_type == "cagra"
    assert KdbxVDB(kdbx_endpoint="k:5000", enable_gpu_search=True)._index_type == "cagra"
    assert KdbxVDB(kdbx_endpoint="k:5000", index_type="flat")._index_type == "hnsw"
    assert KdbxVDB(kdbx_endpoint="k:5000", metric="cs")._metric == "CS"


def test_create_collection_sends_index_type_and_reads_chosen(mock_qconn):
    """WS2/WS1: create_collection sends the backend preference as the 4th q arg
    and surfaces the server-chosen type; the metric rides as the 5th arg
    (review-2 #3 — previously stored but never sent)."""
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB
    mock_qconn.return_value = "hnsw"  # server downgraded cagra->hnsw (no cuVS)
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000", index_type="cagra")
    vdb.create_collection("c", dimension=128)
    args = mock_qconn.call_args.args  # conn(".rag.createCollection", cname, dim, [], itype, metric)
    assert args[0] == ".rag.createCollection"
    assert args[1] == "c"
    assert args[4] == "cagra"  # preference sent, even though server returns hnsw
    assert args[5] == "L2"     # default metric


def test_create_collection_threads_requested_metric(mock_qconn):
    """review-2 #3: metric from the dispatcher (search_type) reaches q."""
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB
    mock_qconn.return_value = "hnsw"
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000", metric="cs")  # lower-case in, upper out
    vdb.create_collection("c", dimension=8)
    assert mock_qconn.call_args.args[5] == "CS"


def test_upload_text_ids_globally_unique_across_calls(mock_qconn):
    """WS-IDFIX: two uploads to the same collection must not reuse ids.

    range(len) restarted at 0 each call, colliding across uploads and silently
    overwriting rows via the q keyed upsert. Generated ids must be globally
    unique and within q long range.
    """
    import numpy as np

    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    vdb._embedding_model = MagicMock()
    vdb._embedding_model.embed_documents.side_effect = (
        lambda docs: [np.zeros(8, dtype=np.float32).tolist() for _ in docs]
    )
    docs = [f"d{i}" for i in range(5)]
    vdb.upload_text("c", docs)
    vdb.upload_text("c", docs)

    all_ids: list[int] = []
    for call in mock_qconn.call_args_list:
        args = call.args
        if args and args[0] == ".rag.insert":
            all_ids.extend(args[2])  # _q(".rag.insert", cname, batch_ids, ...)
    assert len(all_ids) == 10
    assert len(set(all_ids)) == 10, "ids collided across upload_text calls"
    assert all(0 <= i < 2**63 for i in all_ids), "ids must be q long-safe"


# ---------------------------------------------------------------------------
# Task 16 — retrieval_langchain
# ---------------------------------------------------------------------------


def test_retrieval_langchain_returns_documents(mock_qconn):
    import numpy as np
    from langchain_core.documents import Document

    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    vdb._embedding_model = MagicMock()
    vdb._embedding_model.embed_query.return_value = np.zeros(128, dtype=np.float32).tolist()

    mock_qconn.return_value = {
        "ids": [0, 1, 2],
        "distances": [0.0, 0.1, 0.2],
        "docs": ["a", "b", "c"],
        "metas": [{}, {"page": 1}, {}],
    }
    out = vdb.retrieval_langchain("query text", "mycoll", top_k=3, filter_expr="")
    assert all(isinstance(d, Document) for d in out)
    assert len(out) == 3
    assert out[1].metadata.get("page") == 1
    # Every result must carry collection_name so the rag-server citation path
    # can build MinIO thumbnail ids for multimodal citations (kdbx-1).
    assert all(d.metadata.get("collection_name") == "mycoll" for d in out)


def test_retrieval_langchain_drops_empty_and_whitespace_chunks(mock_qconn):
    """Empty / whitespace-only chunks must be filtered out before they reach the
    reranker NIM (which 422s on a <1-char passage). Surviving rows keep their
    correct distance/id alignment."""
    import numpy as np

    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    vdb._embedding_model = MagicMock()
    vdb._embedding_model.embed_query.return_value = np.zeros(128, dtype=np.float32).tolist()

    mock_qconn.return_value = {
        "ids": [10, 11, 12, 13],
        "distances": [0.0, 0.1, 0.2, 0.3],
        "docs": ["real one", "", "   \n\t ", "real two"],  # idx 1 empty, idx 2 whitespace
        "metas": [{}, {}, {}, {}],
    }
    out = vdb.retrieval_langchain("q", "mycoll", top_k=4, filter_expr="")
    assert [d.page_content for d in out] == ["real one", "real two"]
    # alignment preserved: the two survivors keep ids 10 and 13 (not 10/11)
    assert [d.metadata["_id"] for d in out] == [10, 13]


def test_retrieval_langchain_rejects_nonempty_filter(mock_qconn):
    """filter_expr is unsupported on kdbx: fail loud, never silently unfiltered."""
    import numpy as np

    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB, UnsupportedFeatureError

    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    vdb._embedding_model = MagicMock()
    vdb._embedding_model.embed_query.return_value = np.zeros(128, dtype=np.float32).tolist()

    with pytest.raises(UnsupportedFeatureError, match="filter"):
        vdb.retrieval_langchain("q", "c", filter_expr="source == 'x'")
    with pytest.raises(UnsupportedFeatureError):
        vdb.retrieval_langchain("q", "c", filter_expr=[{"key": "source", "op": "==", "value": "x"}])
    # Only the EXACT empty string is "no filter" (the default path).  A
    # whitespace-only string is indistinguishable from a filter mangled
    # upstream and is rejected too (TODO 2.3) — fail-loud beats silently
    # returning unfiltered results for what may have been an ACL/temporal
    # filter.
    mock_qconn.return_value = {"ids": [], "distances": [], "docs": [], "metas": []}
    assert vdb.retrieval_langchain("q", "c", filter_expr="") == []
    with pytest.raises(UnsupportedFeatureError):
        vdb.retrieval_langchain("q", "c", filter_expr="   ")


def test_retrieval_langchain_raises_without_embedding_model(mock_qconn):
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    with pytest.raises(ValueError, match="embedding_model"):
        vdb.retrieval_langchain("query", "mycoll")


def test_get_documents_decodes_json_source(mock_qconn):
    """get_documents must extract source_name from the JSON-encoded source dict.

    The ingestor's post-upload `filename not in filenames_in_vdb` check
    compares basenames; if document_name still carries the JSON blob, the
    ingestor falsely reports the upload as failed.
    """
    import json as _json
    from unittest.mock import patch

    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    # q-side .rag.getDocumentsWithMeta returns aligned source + contentMeta cols
    blob_a = _json.dumps({"source_name": "alpha.pdf", "source_id": "alpha.pdf", "source_type": "PDF"})
    blob_b = _json.dumps({"source_name": "beta.pdf",  "source_id": "beta.pdf",  "source_type": "PDF"})
    mock_qconn.return_value = {
        "source": [blob_a, blob_b, blob_a],          # duplicate alpha
        "contentMeta": ["{}", "{}", "{}"],
    }
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    with patch.object(vdb, "get_metadata_schema", return_value=[]):
        docs = vdb.get_documents("mycoll")
    names = [d["document_name"] for d in docs]
    assert names == ["alpha.pdf", "beta.pdf"]  # deduped, plain filenames


def test_get_documents_handles_bare_string_source(mock_qconn):
    """Tolerate legacy collections where source was stored as bare string."""
    from unittest.mock import patch

    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    mock_qconn.return_value = {"source": ["legacy.pdf"], "contentMeta": ["{}"]}
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    with patch.object(vdb, "get_metadata_schema", return_value=[]):
        docs = vdb.get_documents("mycoll")
    assert docs == [{"document_name": "legacy.pdf", "metadata": {}}]


def test_get_documents_populates_schema_metadata(mock_qconn):
    """Per-schema metadata fields come from each row's content_metadata JSON.

    Mirrors kdbai_vdb.get_documents: the content_metadata blob is sliced down
    to exactly the fields the collection's metadata schema declares, and the
    full source path is reduced to its basename.
    """
    import json as _json
    from unittest.mock import patch

    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    blob_src = _json.dumps({
        "source_name": "/tmp-data/uploaded_files/c/report.pdf",
        "source_id": "/tmp-data/uploaded_files/c/report.pdf",
    })
    blob_cm = _json.dumps({"filename": "report.pdf", "page_number": 7, "type": "text"})
    mock_qconn.return_value = {"source": [blob_src], "contentMeta": [blob_cm]}

    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    with patch.object(
        vdb, "get_metadata_schema",
        return_value=[{"name": "filename"}, {"name": "page_number"}],
    ):
        docs = vdb.get_documents("c")
    # basenamed, and content_metadata sliced to schema fields only (no "type").
    assert docs == [{
        "document_name": "report.pdf",
        "metadata": {"filename": "report.pdf", "page_number": 7},
    }]


def test_delete_documents_matches_by_source_name(mock_qconn):
    """delete_documents must resolve filenames → stored source blobs."""
    import json as _json

    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    blob_a = _json.dumps({"source_name": "alpha.pdf", "source_id": "alpha.pdf", "source_type": "PDF"})
    blob_b = _json.dumps({"source_name": "beta.pdf",  "source_id": "beta.pdf",  "source_type": "PDF"})
    blob_c = _json.dumps({"source_name": "gamma.pdf", "source_id": "gamma.pdf", "source_type": "PDF"})

    # First _q call (getDocuments) returns all 3 source blobs;
    # second _q call (deleteDocumentsByMeta) returns the deletion count.
    mock_qconn.side_effect = [
        {"source": [blob_a, blob_b, blob_c]},
        7,  # rows removed for alpha+gamma
    ]
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    ok = vdb.delete_documents("mycoll", ["alpha.pdf", "gamma.pdf"])
    assert ok is True

    # Verify the q deletion call got exactly the alpha and gamma blobs.
    delete_call = mock_qconn.call_args
    args_str = str(delete_call)
    assert ".rag.deleteDocumentsByMeta" in args_str
    assert "alpha.pdf" in args_str and "gamma.pdf" in args_str
    assert "beta.pdf" not in args_str


def test_delete_documents_strips_upload_path_prefix(mock_qconn):
    """nv-ingest stores source_name as the full path; API gives basename."""
    import json as _json

    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    # Stored source_name is the upload-folder path (what nv-ingest writes).
    blob = _json.dumps({
        "source_name": "/tmp-data/uploaded_files/mycoll/report.pdf",
        "source_id":   "/tmp-data/uploaded_files/mycoll/report.pdf",
    })
    mock_qconn.side_effect = [{"source": [blob]}, 3]
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    # API hands us the basename only.
    ok = vdb.delete_documents("mycoll", ["report.pdf"])
    assert ok is True


def test_get_collection_surfaces_row_counts(mock_qconn):
    """num_entities must reflect live row counts (the frontend's entity badge)."""
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    # ONE q call returns (.rag.listCollections[]; .rag.collections) as a
    # 2-list: [name!count dict, keyed-table py shape] (TODO 2.6 — was two
    # sequential round-trips, each a fresh TCP connection).
    mock_qconn.return_value = [
        {"alpha": 19, "beta": 7},
        {
            ("alpha",): {"dim": 2048, "metaSchema": "", "indexFP": "", "indexType": "hnsw"},
            ("beta",):  {"dim": 2048, "metaSchema": "", "indexFP": "", "indexType": "hnsw"},
        },
    ]
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    rows = vdb.get_collection()
    by_name = {r["collection_name"]: r["num_entities"] for r in rows}
    assert by_name == {"alpha": 19, "beta": 7}
    assert mock_qconn.call_count == 1  # single IPC round-trip


def test_get_collection_falls_back_to_zero_when_count_missing(mock_qconn):
    """An entry in the catalogue without a matching count entry gets 0 (defensive)."""
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    mock_qconn.return_value = [
        {},  # empty counts
        {("orphan",): {"dim": 2048, "metaSchema": "", "indexFP": "", "indexType": "hnsw"}},
    ]
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    rows = vdb.get_collection()
    assert rows[0]["num_entities"] == 0


def test_delete_documents_returns_false_when_no_match(mock_qconn):
    """No matching source -> no deletion, returns False without a 2nd _q call."""
    import json as _json

    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    blob = _json.dumps({"source_name": "real.pdf", "source_id": "real.pdf"})
    mock_qconn.return_value = {"source": [blob]}
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    assert vdb.delete_documents("mycoll", ["does_not_exist.pdf"]) is False
    # Should have called getDocuments only, not deleteDocumentsByMeta
    assert mock_qconn.call_count == 1


# ---------------------------------------------------------------------------
# Task 17 — remaining VDBRag methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_health_healthy(mock_qconn):
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB
    mock_qconn.return_value = "pong"
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    result = await vdb.check_health()
    # DatabaseHealthInfo shape required by the ingestor's HealthResponse model.
    assert result["status"] == "healthy"
    assert result["service"] == "KDB-X"
    assert result["url"] == "kdbx://kdbx:5000"


@pytest.mark.asyncio
async def test_check_health_unhealthy(mock_qconn):
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxQError, KdbxVDB
    mock_qconn.side_effect = KdbxQError("connection refused")
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    result = await vdb.check_health()
    assert result["status"] == "unhealthy"
    assert "connection refused" in result["error"]


def test_create_metadata_schema_collection_is_noop(mock_qconn):
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    # Should not raise; should not call _q
    vdb.create_metadata_schema_collection()
    mock_qconn.assert_not_called()


def test_add_metadata_schema_calls_q(mock_qconn):
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    schema = [{"name": "source", "type": "str"}]
    vdb.add_metadata_schema("mycoll", schema)
    args_str = str(mock_qconn.call_args)
    assert ".rag.addMetadataSchema" in args_str
    assert "mycoll" in args_str


def test_collection_name_property(mock_qconn):
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB
    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    # Multi-collection adapter; returns empty string in Phase 1
    assert isinstance(vdb.collection_name, str)


# ---------------------------------------------------------------------------
# kdbai parity — reindex / close / collection_name setter
# ---------------------------------------------------------------------------


def test_reindex_drops_and_reruns(mock_qconn):
    """reindex should drop the existing collection then re-run ingestion."""
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000", collection_name="reidx")
    with patch.object(vdb, "check_collection_exists", return_value=True), \
         patch.object(vdb, "delete_collections") as mock_delete, \
         patch.object(vdb, "run") as mock_run:
        vdb.reindex([{"text": "hi"}])
        mock_delete.assert_called_once_with(["reidx"])
        mock_run.assert_called_once_with([{"text": "hi"}])


def test_reindex_skips_delete_when_collection_absent(mock_qconn):
    """If the collection doesn't exist yet, reindex just runs (no delete)."""
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000", collection_name="fresh")
    with patch.object(vdb, "check_collection_exists", return_value=False), \
         patch.object(vdb, "delete_collections") as mock_delete, \
         patch.object(vdb, "run") as mock_run:
        vdb.reindex([{"text": "hi"}])
        mock_delete.assert_not_called()
        mock_run.assert_called_once_with([{"text": "hi"}])


def test_context_manager_pass_through(mock_qconn):
    """KdbxVDB works as a context manager; close is a no-op."""
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    with KdbxVDB(kdbx_endpoint="kdbx:5000") as vdb:
        assert vdb._host == "kdbx"
        assert vdb._port == 5000
    # Explicit close after exit is also fine; should not raise.
    vdb.close()


def test_context_manager_does_not_swallow_exceptions(mock_qconn):
    """__exit__ returns False so exceptions propagate out of the with-block."""
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    with pytest.raises(ValueError):
        with KdbxVDB(kdbx_endpoint="kdbx:5000"):
            raise ValueError("boom")


def test_collection_name_setter(mock_qconn):
    """collection_name is settable (kdbai parity)."""
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    assert vdb.collection_name == ""
    vdb.collection_name = "fresh"
    assert vdb.collection_name == "fresh"


# ---------------------------------------------------------------------------
# Best-practice-review batch: pykx-1 / pykx-4 / kdbx-2
# ---------------------------------------------------------------------------


def test_retrieval_passes_vector_positionally(mock_qconn):
    """pykx-1: query vector is sent as a positional IPC arg, not a q string."""
    import numpy as np

    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    vdb._embedding_model = MagicMock()
    vec = np.array([0.1, -0.2, 0.3], dtype=np.float32).tolist()
    vdb._embedding_model.embed_query.return_value = vec
    mock_qconn.return_value = {"ids": [], "distances": [], "docs": [], "metas": []}

    vdb.retrieval_langchain("q", "mycoll", top_k=5)

    args, _ = mock_qconn.call_args
    # First positional arg is the q function name (not an interpolated expr),
    # and the vector is passed as a real Python list, not embedded in a string.
    assert args[0] == ".rag.search"
    assert args[1] == "mycoll"
    assert list(args[2]) == vec
    assert args[3] == 5
    # No giant interpolated q-expression string anywhere in the call.
    assert not any(isinstance(a, str) and ".rag.search[" in a for a in args)


def test_map_q_error_named_dim_mismatch(mock_qconn):
    """pykx-4: the q wrapper's named signal maps to DimensionMismatchError."""
    import pykx

    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import DimensionMismatchError, KdbxVDB

    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    mapped = vdb._map_q_error(pykx.QError("insert_dim_mismatch"))
    assert isinstance(mapped, DimensionMismatchError)
    mapped2 = vdb._map_q_error(pykx.QError("createCollection_dim_mismatch"))
    assert isinstance(mapped2, DimensionMismatchError)


def test_map_q_error_native_primitives_still_classified(mock_qconn):
    """pykx-4: native q primitive substrings remain a fallback."""
    import pykx

    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import (
        KdbxOutOfMemoryError,
        KdbxVDB,
        UnsupportedFeatureError,
    )

    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    assert isinstance(vdb._map_q_error(pykx.QError("wsfull")), KdbxOutOfMemoryError)
    assert isinstance(vdb._map_q_error(pykx.QError("nyi")), UnsupportedFeatureError)


def test_retrieval_propagates_otel_context(mock_qconn):
    """kdbx-2: a provided otel_ctx is attached before work and detached after."""
    import numpy as np

    from nvidia_rag.utils.vdb.kdbx import kdbx_vdb as mod
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    vdb._embedding_model = MagicMock()
    vdb._embedding_model.embed_query.return_value = np.zeros(4, dtype=np.float32).tolist()
    mock_qconn.return_value = {"ids": [], "distances": [], "docs": [], "metas": []}

    sentinel_ctx = object()
    sentinel_token = object()
    with patch.object(mod.otel_context, "attach", return_value=sentinel_token) as attach, \
         patch.object(mod.otel_context, "detach") as detach:
        vdb.retrieval_langchain("q", "mycoll", otel_ctx=sentinel_ctx)
        attach.assert_called_once_with(sentinel_ctx)
        detach.assert_called_once_with(sentinel_token)


def test_retrieval_without_otel_does_not_touch_context(mock_qconn):
    """kdbx-2: no otel_ctx -> attach/detach are not called (token stays None)."""
    import numpy as np

    from nvidia_rag.utils.vdb.kdbx import kdbx_vdb as mod
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    vdb._embedding_model = MagicMock()
    vdb._embedding_model.embed_query.return_value = np.zeros(4, dtype=np.float32).tolist()
    mock_qconn.return_value = {"ids": [], "distances": [], "docs": [], "metas": []}

    with patch.object(mod.otel_context, "attach") as attach, \
         patch.object(mod.otel_context, "detach") as detach:
        vdb.retrieval_langchain("q", "mycoll")
        attach.assert_not_called()
        detach.assert_not_called()


# ---------------------------------------------------------------------------
# WP2 ship-readiness fixes (docs/kdbx-ship-readiness-todo.md §2.1-2.4, 2.6)
# ---------------------------------------------------------------------------


def test_whitespace_only_filter_is_rejected(mock_qconn):
    """TODO 2.3: a whitespace-only filter string must raise, not run UNFILTERED.

    The old compound guard let "  " fall through (strip()=="" short-circuited
    the rejection) and the query silently returned unfiltered results.
    """
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB, UnsupportedFeatureError

    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    vdb._embedding_model = MagicMock()
    vdb._embedding_model.embed_query.return_value = [0.0, 0.0, 0.0, 0.0]
    with pytest.raises(UnsupportedFeatureError):
        vdb.retrieval_langchain("q", "mycoll", filter_expr="   ")
    mock_qconn.assert_not_called()  # rejected before any IPC


def test_create_collection_rejects_invalid_name(mock_qconn):
    """TODO 2.4: invalid cname raises a clean ValueError, not a q-side signal."""
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    for bad in ("my-coll", "1coll", "a b", "", "x;system\"ls\""):
        with pytest.raises(ValueError, match="Invalid collection name"):
            vdb.create_collection(bad)
    mock_qconn.assert_not_called()


def test_metadata_schema_methods_reject_invalid_name(mock_qconn):
    """TODO 2.4: schema + existence methods validate the collection name."""
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    with pytest.raises(ValueError):
        vdb.check_collection_exists("bad-name")
    with pytest.raises(ValueError):
        vdb.add_metadata_schema("bad-name", [])
    with pytest.raises(ValueError):
        vdb.get_metadata_schema("bad-name")
    mock_qconn.assert_not_called()


def test_ready_probe_runs_exactly_once_under_concurrency(mock_qconn):
    """TODO 2.1: the double-checked _ready_lock admits exactly ONE readiness
    probe even when many threads race through a cold _q() simultaneously
    (the rag-server calls the adapter from a ThreadPoolExecutor)."""
    import threading as _threading
    import time as _time

    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    mock_qconn.return_value = "ok"

    probes = []

    def fake_probe(conn):
        probes.append(1)
        _time.sleep(0.05)  # widen the race window
        vdb._server_ready = True

    n = 8
    barrier = _threading.Barrier(n)
    errors: list[Exception] = []

    def worker():
        try:
            barrier.wait(timeout=5)
            vdb._q("`x")
        except Exception as e:  # pragma: no cover - failure reporting
            errors.append(e)

    with patch.object(vdb, "_assert_server_ready", side_effect=fake_probe):
        threads = [_threading.Thread(target=worker) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

    assert not errors
    assert len(probes) == 1  # without the lock this races to >1


def test_final_connection_error_is_wrapped(mock_qconn):
    """TODO 2.6: the last-attempt ConnectionError surfaces as KdbxQError so
    callers catching the adapter's error hierarchy see a uniform type."""
    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxQError, KdbxVDB

    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    mock_qconn.side_effect = ConnectionError("refused")
    with pytest.raises(KdbxQError, match="refused"):
        vdb._q("`x", retries=2)


def test_write_to_index_uses_gen_ids_codepath(mock_qconn):
    """TODO 2.6: write_to_index ids come from _gen_ids (single codepath)."""
    from nvidia_rag.utils.vdb.kdbx import kdbx_vdb as mod

    vdb = mod.KdbxVDB(kdbx_endpoint="kdbx:5000", collection_name="mycoll")
    mock_qconn.return_value = 1
    records = [{"vector": [0.1, 0.2], "text": "t", "source": {"source_id": "s"}}]
    with patch.object(mod.KdbxVDB, "_gen_ids", return_value=[42]) as gen, \
         patch.object(mod, "cleanup_records", create=True):
        # cleanup_records is imported inside the function from nv_ingest_client;
        # patch it there instead.
        with patch("nv_ingest_client.util.milvus.cleanup_records", return_value=records):
            vdb.write_to_index(records)
    gen.assert_called_with(1)
    args = mock_qconn.call_args[0]
    assert args[0] == ".rag.insert"
    assert list(args[2]) == [42]


# ---------------------------------------------------------------------------
# Review-2 coverage residue (yellow items)
# ---------------------------------------------------------------------------


def test_map_q_error_branches(mock_qconn):
    """Every _map_q_error branch maps to its dedicated subclass."""
    import pykx

    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import (
        DimensionMismatchError,
        InvalidVectorTypeError,
        KdbxGpuFaultError,
        KdbxOutOfMemoryError,
        KdbxQError,
        KdbxVDB,
        UnsupportedFeatureError,
    )

    cases = {
        "insert_dim_mismatch": DimensionMismatchError,
        "wsfull": KdbxOutOfMemoryError,
        "CUDA error 700": KdbxGpuFaultError,
        "illegal memory access": KdbxGpuFaultError,
        "nyi": UnsupportedFeatureError,
        "length": DimensionMismatchError,
        "type": InvalidVectorTypeError,
        "something else entirely": KdbxQError,
    }
    for msg, exc_type in cases.items():
        mapped = KdbxVDB._map_q_error(pykx.QError(msg))
        assert isinstance(mapped, exc_type), f"{msg!r} -> {type(mapped).__name__}"


def test_retrieval_reshapes_column_major_metas(mock_qconn):
    """q auto-promotes uniform list-of-dicts to a Table; after .py() that is a
    COLUMN-major dict-of-lists. The adapter must reshape it back to row-major
    so each Document gets its own metadata."""
    import json as _json

    from nvidia_rag.utils.vdb.kdbx.kdbx_vdb import KdbxVDB

    vdb = KdbxVDB(kdbx_endpoint="kdbx:5000")
    vdb._embedding_model = MagicMock()
    vdb._embedding_model.embed_query.return_value = [0.0, 0.0]
    src0 = _json.dumps({"source_id": "a.pdf", "source_name": "a.pdf"})
    src1 = _json.dumps({"source_id": "b.pdf", "source_name": "b.pdf"})
    mock_qconn.return_value = {
        "ids": [1, 2],
        "distances": [0.1, 0.2],
        "docs": ["alpha", "beta"],
        # column-major: one dict of equal-length lists
        "metas": {"source": [src0, src1], "content_metadata": ["{}", "{}"]},
    }
    out = vdb.retrieval_langchain("q", "c", top_k=2)
    assert len(out) == 2
    assert out[0].metadata["source"]["source_id"] == "a.pdf"
    assert out[1].metadata["source"]["source_id"] == "b.pdf"


def test_write_to_index_coerces_bare_string_source_and_skips_empty_vectors(mock_qconn):
    """review-2 yellow: the nv-ingest path's source-dict coercion (bare string
    -> dict with source_id/source_name) and the empty-vector skip."""
    import json as _json

    from nvidia_rag.utils.vdb.kdbx import kdbx_vdb as mod

    vdb = mod.KdbxVDB(kdbx_endpoint="kdbx:5000", collection_name="mycoll")
    mock_qconn.return_value = 2
    records = [
        {"vector": [], "text": "skipped", "source": "x.pdf"},          # no vector -> dropped
        {"vector": [0.1, 0.2], "text": "kept1", "source": "plain.pdf"},  # bare-string source
        {"vector": [0.3, 0.4], "text": "kept2", "source": {"source_name": "d.pdf"}},  # no source_id
    ]
    with patch("nv_ingest_client.util.milvus.cleanup_records", return_value=records):
        vdb.write_to_index(records)

    args = mock_qconn.call_args.args  # (".rag.insert", cname, ids, vecs, docs, metas)
    assert args[0] == ".rag.insert"
    docs = args[4]
    assert docs == ["kept1", "kept2"]  # empty-vector record skipped
    metas = args[5]
    src1 = _json.loads(metas[0]["source"])
    assert src1 == {"source_id": "plain.pdf", "source_name": "plain.pdf"}  # coerced
    src2 = _json.loads(metas[1]["source"])
    assert src2["source_id"] == "d.pdf"  # source_id backfilled from source_name
