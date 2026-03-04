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
"""Tests for kdbx.es_adapter -- ES-compatible adapter with native HNSW vector search.

Covers the 6 public functions that mirror ``src/lib/integration/es_client.py``:

1. get_es_client     -- returns KDBXClient singleton, calls create_all_tables + _init_hnsw_module
2. ensure_embeddings_index -- no-op (does not call q)
3. index_embeddings_to_es  -- inserts rows, builds HNSW index server-side, returns index_name
4. search_similar_embeddings -- native HNSW search via KDB-X AI module
5. delete_embeddings_index -- calls q delete, removes HNSW index and metadata cache
6. close_es_client   -- clears both global references
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_module_globals():
    """Reset the module-level singletons between tests."""
    import kdbx.es_adapter as mod

    mod._kdbx_client = None
    mod._metadata_cache = {}


def _make_hnsw_result(scores, indices):
    """Build a mock object mimicking HNSW search result (scores, indices)."""
    mock_scores = MagicMock()
    mock_scores.np.return_value = np.array(scores, dtype=np.float32)
    mock_indices = MagicMock()
    mock_indices.np.return_value = np.array(indices, dtype=np.int64)
    result = MagicMock()
    result.__getitem__ = lambda self, i: [mock_scores, mock_indices][i]
    return result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_globals():
    """Ensure each test starts with fresh module-level state."""
    _reset_module_globals()
    yield
    _reset_module_globals()


@pytest.fixture()
def mock_q():
    """Patch ``pykx_connection`` where es_adapter.py imports it.

    Also patches ``create_all_tables``, ``extract_user_query``, and
    ``kx`` (pykx) so the adapter can be tested in isolation without
    requiring a real kdb+ license.

    Yields a tuple of (mock_conn, mock_create_all_tables, mock_extract).
    """
    mock_conn = MagicMock(name="SyncQConnection")

    @contextmanager
    def _fake_ctx():
        yield mock_conn

    with (
        patch("kdbx.es_adapter.pykx_connection", _fake_ctx),
        patch("kdbx.es_adapter.create_all_tables") as mock_create,
        patch("kdbx.es_adapter.extract_user_query", return_value="hello world") as mock_extract,
        patch("kdbx.es_adapter.kx") as mock_kx,
    ):
        # Wire up atom constructors to return tagged strings so tests
        # can verify type conversion without real PyKX.
        mock_kx.SymbolAtom.side_effect = lambda v: f"sym:{v}"
        mock_kx.LongAtom.side_effect = lambda v: f"long:{v}"
        mock_kx.FloatAtom.side_effect = lambda v: f"float:{v}"
        yield mock_conn, mock_create, mock_extract


# ---------------------------------------------------------------------------
# 1. get_es_client
# ---------------------------------------------------------------------------


class TestGetEsClient:
    """Tests for get_es_client()."""

    def test_returns_kdbx_client(self, mock_q):
        """get_es_client() returns a KDBXClient instance."""
        from kdbx.es_adapter import KDBXClient, get_es_client

        client = get_es_client()
        assert isinstance(client, KDBXClient)

    def test_calls_create_all_tables_on_first_connection(self, mock_q):
        """First call to get_es_client triggers create_all_tables()."""
        from kdbx.es_adapter import get_es_client

        mock_conn, mock_create, _ = mock_q
        mock_conn.return_value = True

        get_es_client()
        mock_create.assert_called_once()

    def test_inits_hnsw_module(self, mock_q):
        """First call to get_es_client loads the AI module."""
        from kdbx.es_adapter import get_es_client

        mock_conn, _, _ = mock_q
        mock_conn.return_value = True

        get_es_client()

        # _init_hnsw_module issues two q calls for AI module + HNSW globals
        q_calls = [str(c) for c in mock_conn.call_args_list]
        ai_loaded = any(".ai" in c for c in q_calls)
        assert ai_loaded, "Expected .ai module init call"

    def test_returns_singleton(self, mock_q):
        """Repeated calls return the same KDBXClient instance."""
        from kdbx.es_adapter import get_es_client

        mock_conn, _, _ = mock_q
        mock_conn.return_value = True

        client1 = get_es_client()
        client2 = get_es_client()
        assert client1 is client2

    def test_kdbx_client_has_ping(self, mock_q):
        """KDBXClient.ping() returns True (always healthy)."""
        from kdbx.es_adapter import get_es_client

        mock_conn, _, _ = mock_q
        mock_conn.return_value = True

        client = get_es_client()
        assert client.ping() is True


# ---------------------------------------------------------------------------
# 1b. _rebuild_hnsw_from_table
# ---------------------------------------------------------------------------


class TestRebuildHnswFromTable:
    """Tests for _rebuild_hnsw_from_table() — startup index reconstruction."""

    def test_rebuild_skips_when_table_empty(self, mock_q):
        """No indexes rebuilt when flywheel_embeddings is empty."""
        import kdbx.es_adapter as mod
        from kdbx.es_adapter import _rebuild_hnsw_from_table

        mock_conn, _, _ = mock_q
        # exec distinct index_name returns empty
        mock_conn.return_value = []

        _rebuild_hnsw_from_table()

        assert mod._metadata_cache == {}

    def test_rebuild_populates_metadata_cache(self, mock_q):
        """Rebuild reads table rows and populates _metadata_cache."""
        import kdbx.es_adapter as mod
        from kdbx.es_adapter import _rebuild_hnsw_from_table

        mock_conn, _, _ = mock_q

        # First call: distinct index_name returns one name
        # Subsequent calls: table query, HNSW build
        call_count = {"n": 0}
        def _side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # distinct index_name query
                return ["idx_wl1_cl1_123"]
            if call_count["n"] == 2:
                # select embedding, tool_name, record query
                rows = MagicMock()
                rows.__getitem__ = lambda self, key: {
                    "embedding": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
                    "tool_name": ["tool_a", "tool_b"],
                    "record": ['{"id": "a"}', '{"id": "b"}'],
                }[key]
                return rows
            # HNSW build call — return value unused
            return None

        mock_conn.side_effect = _side_effect

        _rebuild_hnsw_from_table()

        assert "idx_wl1_cl1_123" in mod._metadata_cache
        tool_names, records = mod._metadata_cache["idx_wl1_cl1_123"]
        assert tool_names == ["tool_a", "tool_b"]
        assert records == [{"id": "a"}, {"id": "b"}]

    def test_rebuild_builds_hnsw_index(self, mock_q):
        """Rebuild issues HNSW put call for each persisted index."""
        from kdbx.es_adapter import _rebuild_hnsw_from_table

        mock_conn, _, _ = mock_q

        call_count = {"n": 0}
        def _side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return ["idx1"]
            if call_count["n"] == 2:
                rows = MagicMock()
                rows.__getitem__ = lambda self, key: {
                    "embedding": [[0.1, 0.2]],
                    "tool_name": ["tool_a"],
                    "record": ['{"id": "a"}'],
                }[key]
                return rows
            return None

        mock_conn.side_effect = _side_effect

        _rebuild_hnsw_from_table()

        q_calls = [str(c) for c in mock_conn.call_args_list]
        hnsw_built = any(".ai.hnsw.put" in c for c in q_calls)
        assert hnsw_built, "Expected HNSW build call during rebuild"

    def test_rebuild_handles_bad_json_gracefully(self, mock_q):
        """Records with invalid JSON don't crash rebuild."""
        import kdbx.es_adapter as mod
        from kdbx.es_adapter import _rebuild_hnsw_from_table

        mock_conn, _, _ = mock_q

        call_count = {"n": 0}
        def _side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return ["idx1"]
            if call_count["n"] == 2:
                rows = MagicMock()
                rows.__getitem__ = lambda self, key: {
                    "embedding": [[0.1, 0.2]],
                    "tool_name": ["tool_a"],
                    "record": ["not-valid-json"],
                }[key]
                return rows
            return None

        mock_conn.side_effect = _side_effect

        _rebuild_hnsw_from_table()

        assert "idx1" in mod._metadata_cache
        _, records = mod._metadata_cache["idx1"]
        assert records == [{}]  # fallback to empty dict


# ---------------------------------------------------------------------------
# 2. ensure_embeddings_index
# ---------------------------------------------------------------------------


class TestEnsureEmbeddingsIndex:
    """Tests for ensure_embeddings_index()."""

    def test_is_noop(self, mock_q):
        """ensure_embeddings_index does not call q -- table created at startup."""
        from kdbx.es_adapter import ensure_embeddings_index

        mock_conn, _, _ = mock_q
        ensure_embeddings_index(client=None, index_name="test_idx")

        # The mock q connection should not have been called
        mock_conn.assert_not_called()


# ---------------------------------------------------------------------------
# 3. index_embeddings_to_es
# ---------------------------------------------------------------------------


class TestIndexEmbeddingsToEs:
    """Tests for index_embeddings_to_es()."""

    def test_returns_index_name_with_correct_prefix(self, mock_q):
        """Returned index_name starts with the expected prefix."""
        from kdbx.es_adapter import index_embeddings_to_es

        mock_conn, _, mock_extract = mock_q

        binned_data = {
            "tool_a": [
                ([0.1, 0.2, 0.3], {"workload_id": "wl1", "timestamp": 1234}),
            ],
        }

        result = index_embeddings_to_es(
            client=None,
            binned_data=binned_data,
            workload_id="wl1",
            client_id="cl1",
        )

        assert result.startswith("flywheel_embeddings_index_wl1_cl1_")

    def test_calls_q_insert(self, mock_q):
        """Each record in binned_data should trigger a q insert call."""
        from kdbx.es_adapter import index_embeddings_to_es

        mock_conn, _, mock_extract = mock_q

        binned_data = {
            "tool_a": [
                ([0.1, 0.2], {"workload_id": "wl1", "timestamp": 1234}),
                ([0.3, 0.4], {"workload_id": "wl1", "timestamp": 5678}),
            ],
            "tool_b": [
                ([0.5, 0.6], {"workload_id": "wl1", "timestamp": 9012}),
            ],
        }

        index_embeddings_to_es(
            client=None,
            binned_data=binned_data,
            workload_id="wl1",
            client_id="cl1",
        )

        # Should have called q for inserts + HNSW build
        assert mock_conn.call_count >= 3  # 3 inserts + 1 HNSW build

    def test_calls_extract_user_query(self, mock_q):
        """extract_user_query is called for each record."""
        from kdbx.es_adapter import index_embeddings_to_es

        mock_conn, _, mock_extract = mock_q

        record1 = {"workload_id": "wl1", "timestamp": 1234}
        record2 = {"workload_id": "wl1", "timestamp": 5678}
        binned_data = {
            "tool_a": [([0.1], record1), ([0.2], record2)],
        }

        index_embeddings_to_es(
            client=None,
            binned_data=binned_data,
            workload_id="wl1",
            client_id="cl1",
        )

        assert mock_extract.call_count == 2
        mock_extract.assert_any_call(record1)
        mock_extract.assert_any_call(record2)

    def test_populates_metadata_cache(self, mock_q):
        """After indexing, _metadata_cache should contain the index_name."""
        import kdbx.es_adapter as mod
        from kdbx.es_adapter import index_embeddings_to_es

        mock_conn, _, _ = mock_q

        binned_data = {
            "tool_a": [([0.1, 0.2], {"workload_id": "wl1", "timestamp": 1})],
        }

        index_name = index_embeddings_to_es(
            client=None,
            binned_data=binned_data,
            workload_id="wl1",
            client_id="cl1",
        )

        assert index_name in mod._metadata_cache
        tool_names, records = mod._metadata_cache[index_name]
        assert tool_names == ["tool_a"]
        assert len(records) == 1

    def test_builds_hnsw_index_server_side(self, mock_q):
        """After inserts, a q call to build HNSW index should be issued."""
        from kdbx.es_adapter import index_embeddings_to_es

        mock_conn, _, _ = mock_q

        binned_data = {
            "tool_a": [([0.1, 0.2], {"workload_id": "wl1", "timestamp": 1})],
        }

        index_embeddings_to_es(
            client=None,
            binned_data=binned_data,
            workload_id="wl1",
            client_id="cl1",
        )

        # Find the HNSW build call (contains .ai.hnsw.put)
        q_calls = [str(c) for c in mock_conn.call_args_list]
        hnsw_built = any(".ai.hnsw.put" in c for c in q_calls)
        assert hnsw_built, "Expected HNSW index build q call"

    def test_handles_empty_binned_data(self, mock_q):
        """Empty binned_data should still return a valid index_name."""
        from kdbx.es_adapter import index_embeddings_to_es

        result = index_embeddings_to_es(
            client=None,
            binned_data={},
            workload_id="wl1",
            client_id="cl1",
        )

        assert result.startswith("flywheel_embeddings_index_wl1_cl1_")


# ---------------------------------------------------------------------------
# 4. search_similar_embeddings
# ---------------------------------------------------------------------------


class TestSearchSimilarEmbeddings:
    """Tests for search_similar_embeddings()."""

    def test_returns_empty_list_when_index_not_in_cache(self, mock_q):
        """If index_name is not in _metadata_cache, return []."""
        from kdbx.es_adapter import search_similar_embeddings

        result = search_similar_embeddings(
            client=None,
            query_embedding=[0.1, 0.2, 0.3],
            index_name="nonexistent_index",
            max_candidates=10,
        )

        assert result == []

    def test_returns_ranked_results(self, mock_q):
        """HNSW search returns results ordered by score."""
        import kdbx.es_adapter as mod
        from kdbx.es_adapter import search_similar_embeddings

        mock_conn, _, _ = mock_q

        # Pre-populate metadata cache
        tool_names = ["tool_a", "tool_b"]
        records = [{"id": "a"}, {"id": "b"}]
        mod._metadata_cache["test_idx"] = (tool_names, records)

        # Mock HNSW search result: tool_a (idx 0) scores higher
        mock_conn.return_value = _make_hnsw_result(
            scores=[0.95, 0.42],
            indices=[0, 1],
        )

        result = search_similar_embeddings(
            client=None,
            query_embedding=[0.9, 0.1],
            index_name="test_idx",
            max_candidates=10,
        )

        assert len(result) == 2
        assert result[0][1] == "tool_a"
        assert result[1][1] == "tool_b"
        assert result[0][0] > result[1][0]
        assert all(isinstance(r[0], float) for r in result)

    def test_respects_max_candidates(self, mock_q):
        """Only returns up to max_candidates results."""
        import kdbx.es_adapter as mod
        from kdbx.es_adapter import search_similar_embeddings

        mock_conn, _, _ = mock_q

        tool_names = ["t1", "t2", "t3"]
        records = [{"i": 1}, {"i": 2}, {"i": 3}]
        mod._metadata_cache["idx"] = (tool_names, records)

        # Mock returns 2 results (clamped by k=2)
        mock_conn.return_value = _make_hnsw_result(
            scores=[0.9, 0.5],
            indices=[0, 2],
        )

        result = search_similar_embeddings(
            client=None,
            query_embedding=[1.0, 0.0, 0.0],
            index_name="idx",
            max_candidates=2,
        )

        assert len(result) == 2

    def test_returns_empty_for_empty_cache_entry(self, mock_q):
        """Empty cache entry (no vectors) returns []."""
        import kdbx.es_adapter as mod
        from kdbx.es_adapter import search_similar_embeddings

        mod._metadata_cache["empty_idx"] = ([], [])

        result = search_similar_embeddings(
            client=None,
            query_embedding=[0.1, 0.2],
            index_name="empty_idx",
            max_candidates=10,
        )

        assert result == []

    def test_calls_hnsw_search_server_side(self, mock_q):
        """search_similar_embeddings should issue an HNSW search q call."""
        import kdbx.es_adapter as mod
        from kdbx.es_adapter import search_similar_embeddings

        mock_conn, _, _ = mock_q

        mod._metadata_cache["idx"] = (["tool_a"], [{"id": "a"}])
        mock_conn.return_value = _make_hnsw_result(
            scores=[0.9], indices=[0],
        )

        search_similar_embeddings(
            client=None,
            query_embedding=[0.1, 0.2],
            index_name="idx",
            max_candidates=10,
        )

        q_calls = [str(c) for c in mock_conn.call_args_list]
        hnsw_searched = any(".ai.hnsw.search" in c for c in q_calls)
        assert hnsw_searched, "Expected HNSW search q call"


# ---------------------------------------------------------------------------
# 5. delete_embeddings_index
# ---------------------------------------------------------------------------


class TestDeleteEmbeddingsIndex:
    """Tests for delete_embeddings_index()."""

    def test_calls_q_delete(self, mock_q):
        """delete_embeddings_index should call q with delete from table."""
        import kdbx.es_adapter as mod
        from kdbx.es_adapter import delete_embeddings_index

        mock_conn, _, _ = mock_q

        mod._metadata_cache["test_idx"] = ([], [])

        delete_embeddings_index(client=None, index_name="test_idx")

        # Should have called q for table delete + HNSW cleanup
        assert mock_conn.call_count >= 2
        q_calls = [str(c) for c in mock_conn.call_args_list]
        assert any("delete" in c and "flywheel_embeddings" in c for c in q_calls)

    def test_cleans_up_hnsw_index(self, mock_q):
        """delete_embeddings_index should issue HNSW cleanup q call."""
        import kdbx.es_adapter as mod
        from kdbx.es_adapter import delete_embeddings_index

        mock_conn, _, _ = mock_q
        mod._metadata_cache["test_idx"] = ([], [])

        delete_embeddings_index(client=None, index_name="test_idx")

        q_calls = [str(c) for c in mock_conn.call_args_list]
        hnsw_cleaned = any(".hnsw.idx" in c for c in q_calls)
        assert hnsw_cleaned, "Expected HNSW cleanup q call"

    def test_removes_from_metadata_cache(self, mock_q):
        """After deletion, the index should be removed from _metadata_cache."""
        import kdbx.es_adapter as mod
        from kdbx.es_adapter import delete_embeddings_index

        mock_conn, _, _ = mock_q

        mod._metadata_cache["test_idx"] = ([], [])

        delete_embeddings_index(client=None, index_name="test_idx")

        assert "test_idx" not in mod._metadata_cache

    def test_handles_missing_index_gracefully(self, mock_q):
        """Deleting an index not in the cache should not raise."""
        from kdbx.es_adapter import delete_embeddings_index

        mock_conn, _, _ = mock_q

        # Should not raise
        delete_embeddings_index(client=None, index_name="nonexistent")


# ---------------------------------------------------------------------------
# 6. close_es_client
# ---------------------------------------------------------------------------


class TestCloseEsClient:
    """Tests for close_es_client()."""

    def test_clears_client_global(self, mock_q):
        """close_es_client sets _kdbx_client to None."""
        import kdbx.es_adapter as mod
        from kdbx.es_adapter import close_es_client, get_es_client

        mock_conn, _, _ = mock_q
        mock_conn.return_value = True

        get_es_client()  # populate the singleton
        assert mod._kdbx_client is not None

        close_es_client()
        assert mod._kdbx_client is None

    def test_clears_metadata_cache(self, mock_q):
        """close_es_client clears _metadata_cache dict."""
        import kdbx.es_adapter as mod
        from kdbx.es_adapter import close_es_client

        mod._metadata_cache["idx1"] = (["tool_a"], [{"wl": "1"}])
        mod._metadata_cache["idx2"] = (["tool_b"], [{"wl": "2"}])

        close_es_client()

        assert mod._metadata_cache == {}

    def test_close_idempotent(self, mock_q):
        """Calling close_es_client multiple times should not raise."""
        from kdbx.es_adapter import close_es_client

        close_es_client()
        close_es_client()  # should not raise


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Verify exported constants."""

    def test_embedding_dims(self):
        from kdbx.es_adapter import EMBEDDING_DIMS

        assert EMBEDDING_DIMS == 2048

    def test_hnsw_hyperparameters(self):
        from kdbx.es_adapter import _HNSW_M, _HNSW_EF, _HNSW_EFS

        assert _HNSW_M > 0
        assert _HNSW_EF > 0
        assert _HNSW_EFS > 0
