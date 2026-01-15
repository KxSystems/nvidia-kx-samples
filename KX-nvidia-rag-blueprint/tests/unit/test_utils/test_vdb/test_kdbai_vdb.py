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

"""Unit tests for KDB.AI VDB functionality."""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
import pandas as pd
from langchain_core.documents import Document

from nvidia_rag.utils.vdb import DEFAULT_METADATA_SCHEMA_COLLECTION


class TestKdbaiFilters:
    """Test the filter expression translation utilities."""

    def test_milvus_to_kdbai_filter_simple_equality(self):
        """Test simple equality filter."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_filters import milvus_to_kdbai_filter

        result = milvus_to_kdbai_filter("source == 'file.pdf'")
        assert result == [("=", "source", "file.pdf")]

    def test_milvus_to_kdbai_filter_nested_field(self):
        """Test nested field access filter."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_filters import milvus_to_kdbai_filter

        result = milvus_to_kdbai_filter("source['source_name'] == 'file.pdf'")
        assert result == [("=", "source", "file.pdf")]

    def test_milvus_to_kdbai_filter_numeric_comparison(self):
        """Test numeric comparison filter."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_filters import milvus_to_kdbai_filter

        result = milvus_to_kdbai_filter("count > 10")
        assert result == [(">", "count", 10)]

    def test_milvus_to_kdbai_filter_float_comparison(self):
        """Test float comparison filter."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_filters import milvus_to_kdbai_filter

        result = milvus_to_kdbai_filter("score >= 0.5")
        assert result == [(">=", "score", 0.5)]

    def test_milvus_to_kdbai_filter_in_operator(self):
        """Test 'in' operator filter."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_filters import milvus_to_kdbai_filter

        result = milvus_to_kdbai_filter("category in ['A', 'B', 'C']")
        assert result == [("in", "category", ["A", "B", "C"])]

    def test_milvus_to_kdbai_filter_empty(self):
        """Test empty filter expression."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_filters import milvus_to_kdbai_filter

        result = milvus_to_kdbai_filter("")
        assert result is None

        result = milvus_to_kdbai_filter("   ")
        assert result is None

    def test_milvus_to_kdbai_filter_none(self):
        """Test None filter expression."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_filters import milvus_to_kdbai_filter

        result = milvus_to_kdbai_filter(None)
        assert result is None

    def test_build_source_filter(self):
        """Test build_source_filter helper."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_filters import build_source_filter

        result = build_source_filter("document.pdf")
        assert result == [("like", "source", "*document.pdf*")]

    def test_build_metadata_filter(self):
        """Test build_metadata_filter helper."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_filters import build_metadata_filter

        result = build_metadata_filter({"field1": "value1", "field2": 42})
        assert len(result) == 2
        assert ("=", "field1", "value1") in result
        assert ("=", "field2", 42) in result

    def test_build_metadata_filter_empty(self):
        """Test build_metadata_filter with empty dict."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_filters import build_metadata_filter

        result = build_metadata_filter({})
        assert result is None


class TestKdbaiVDB:
    """Test the KdbaiVDB class."""

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_init(self, mock_get_config, mock_kdbai):
        """Test KdbaiVDB initialization."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_config = Mock()
        mock_get_config.return_value = mock_config

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database

        embedding_model = Mock()
        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            api_key="test_key",
            database_name="test_db",
            embedding_model=embedding_model,
            index_type="hnsw",
            metric="L2",
        )

        assert vdb.collection_name == "test_collection"
        assert vdb.kdbai_endpoint == "http://localhost:8082"
        assert vdb.api_key == "test_key"
        assert vdb.database_name == "test_db"
        assert vdb.embedding_model == embedding_model
        assert vdb.index_type == "hnsw"
        assert vdb.metric == "L2"

        mock_kdbai.Session.assert_called_once_with(
            endpoint="http://localhost:8082",
            api_key="test_key",
        )

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_init_without_api_key(self, mock_get_config, mock_kdbai):
        """Test KdbaiVDB initialization without API key."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_config = Mock()
        mock_get_config.return_value = mock_config

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
        )

        # Should be called without api_key
        mock_kdbai.Session.assert_called_once_with(
            endpoint="http://localhost:8082",
        )

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_collection_name_property(self, mock_get_config, mock_kdbai):
        """Test collection_name property getter and setter."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
        )

        assert vdb.collection_name == "test_collection"

        vdb.collection_name = "new_collection"
        assert vdb.collection_name == "new_collection"

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_close(self, mock_get_config, mock_kdbai):
        """Test close method."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
        )

        vdb.close()
        mock_session.close.assert_called_once()

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_context_manager(self, mock_get_config, mock_kdbai):
        """Test context manager behavior."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database

        with KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
        ) as vdb:
            assert vdb is not None

        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    async def test_check_health_healthy(self, mock_get_config, mock_kdbai):
        """Test check_health when KDB.AI is healthy."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database
        mock_session.version.return_value = {"version": "1.0.0"}
        mock_database.tables = ["table1", "table2"]

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
        )

        result = await vdb.check_health()

        assert result["service"] == "KDB.AI"
        assert result["status"] == "healthy"
        assert result["tables"] == 2
        assert "latency_ms" in result

    @pytest.mark.asyncio
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    async def test_check_health_error(self, mock_get_config, mock_kdbai):
        """Test check_health when KDB.AI has an error."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database
        mock_database.tables = property(lambda self: (_ for _ in ()).throw(Exception("Connection error")))

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
        )

        # Make tables raise an exception
        type(mock_database).tables = property(Mock(side_effect=Exception("Connection error")))

        result = await vdb.check_health()

        assert result["status"] == "error"
        assert "Connection error" in result["error"]

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_check_collection_exists_true(self, mock_get_config, mock_kdbai):
        """Test check_collection_exists when collection exists."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database

        # Create mock table objects with name attribute
        mock_table1 = Mock()
        mock_table1.name = "table1"
        mock_table2 = Mock()
        mock_table2.name = "test_collection"
        mock_database.tables = [mock_table1, mock_table2]

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
        )

        result = vdb.check_collection_exists("test_collection")
        assert result is True

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_check_collection_exists_false(self, mock_get_config, mock_kdbai):
        """Test check_collection_exists when collection doesn't exist."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database

        mock_table = Mock()
        mock_table.name = "other_table"
        mock_database.tables = [mock_table]

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
        )

        result = vdb.check_collection_exists("test_collection")
        assert result is False

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_create_collection(self, mock_get_config, mock_kdbai):
        """Test create_collection method."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database
        mock_database.tables = []  # Empty, so collection doesn't exist

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
            index_type="hnsw",
        )

        vdb.create_collection("new_collection", dimension=2048)

        mock_database.create_table.assert_called_once()
        call_kwargs = mock_database.create_table.call_args[1]
        assert call_kwargs["table"] == "new_collection"
        assert len(call_kwargs["schema"]) == 5  # id, text, vector, source, content_metadata
        assert call_kwargs["indexes"][0]["type"] == "hnsw"
        assert call_kwargs["indexes"][0]["params"]["dims"] == 2048

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_create_collection_already_exists(self, mock_get_config, mock_kdbai):
        """Test create_collection when collection already exists."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database

        mock_table = Mock()
        mock_table.name = "existing_collection"
        mock_database.tables = [mock_table]

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
        )

        vdb.create_collection("existing_collection", dimension=2048)

        mock_database.create_table.assert_not_called()

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_delete_collections_success(self, mock_get_config, mock_kdbai):
        """Test delete_collections method with successful deletion."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database

        mock_table = Mock()
        mock_table.name = "collection1"
        mock_database.tables = [mock_table]
        mock_database.table.return_value = mock_table

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
        )

        # Mock check_collection_exists to return True
        with patch.object(vdb, 'check_collection_exists', return_value=True):
            with patch.object(vdb, '_delete_metadata_schema_entry'):
                result = vdb.delete_collections(["collection1"])

        assert result["total_success"] == 1
        assert result["total_failed"] == 0
        assert "collection1" in result["successful"]
        mock_table.drop.assert_called_once()

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_delete_collections_not_found(self, mock_get_config, mock_kdbai):
        """Test delete_collections when collection doesn't exist."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database
        mock_database.tables = []

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
        )

        result = vdb.delete_collections(["nonexistent"])

        assert result["total_success"] == 0
        assert result["total_failed"] == 1
        assert result["failed"][0]["collection_name"] == "nonexistent"

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_get_documents(self, mock_get_config, mock_kdbai):
        """Test get_documents method."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database

        mock_table = Mock()
        mock_database.table.return_value = mock_table

        # Mock query result as DataFrame
        query_result = pd.DataFrame([
            {"source": "/path/to/file1.pdf", "content_metadata": '{"field1": "value1"}'},
            {"source": "/path/to/file2.pdf", "content_metadata": '{"field1": "value2"}'},
        ])
        mock_table.query.return_value = query_result

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
        )

        with patch.object(vdb, 'get_metadata_schema', return_value=[{"name": "field1"}]):
            result = vdb.get_documents("test_collection")

        assert len(result) == 2
        assert result[0]["document_name"] == "file1.pdf"
        assert result[1]["document_name"] == "file2.pdf"

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_add_metadata_schema(self, mock_get_config, mock_kdbai):
        """Test add_metadata_schema method."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database

        mock_table = Mock()
        mock_database.table.return_value = mock_table

        # Make metadata_schema table exist
        mock_schema_table = Mock()
        mock_schema_table.name = DEFAULT_METADATA_SCHEMA_COLLECTION
        mock_database.tables = [mock_schema_table]

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
        )

        metadata_schema = [{"name": "field1", "type": "string"}]

        with patch.object(vdb, 'create_metadata_schema_collection'):
            with patch.object(vdb, '_delete_metadata_schema_entry'):
                vdb.add_metadata_schema("test_collection", metadata_schema)

        mock_table.insert.assert_called_once()

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_get_metadata_schema_found(self, mock_get_config, mock_kdbai):
        """Test get_metadata_schema when schema exists."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database

        mock_table = Mock()
        mock_database.table.return_value = mock_table

        # Mock schema table exists
        mock_schema_table = Mock()
        mock_schema_table.name = DEFAULT_METADATA_SCHEMA_COLLECTION
        mock_database.tables = [mock_schema_table]

        # Mock query result
        mock_table.query.return_value = [
            {"metadata_schema": '[{"name": "field1"}]'}
        ]

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
        )

        result = vdb.get_metadata_schema("test_collection")

        assert result == [{"name": "field1"}]

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_get_metadata_schema_not_found(self, mock_get_config, mock_kdbai):
        """Test get_metadata_schema when schema doesn't exist."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database

        mock_table = Mock()
        mock_database.table.return_value = mock_table
        mock_table.query.return_value = []  # Empty result

        # Mock schema table exists
        mock_schema_table = Mock()
        mock_schema_table.name = DEFAULT_METADATA_SCHEMA_COLLECTION
        mock_database.tables = [mock_schema_table]

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
        )

        result = vdb.get_metadata_schema("test_collection")

        assert result == []

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.KDBAI')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_get_langchain_vectorstore(self, mock_get_config, mock_kdbai, mock_kdbai_vs):
        """Test get_langchain_vectorstore method."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database

        mock_table = Mock()
        mock_database.table.return_value = mock_table

        mock_vectorstore = Mock()
        mock_kdbai_vs.return_value = mock_vectorstore

        embedding_model = Mock()
        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=embedding_model,
            metric="L2",
        )

        result = vdb.get_langchain_vectorstore("test_collection")

        mock_kdbai_vs.assert_called_once()
        call_kwargs = mock_kdbai_vs.call_args[1]
        assert call_kwargs["table"] == mock_table
        assert call_kwargs["embedding"] == embedding_model

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_retrieval_langchain(self, mock_get_config, mock_kdbai):
        """Test retrieval_langchain method."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database

        mock_docs = [
            Document(page_content="doc1", metadata={"source": "file1.txt"}),
            Document(page_content="doc2", metadata={"source": "file2.txt"})
        ]

        mock_vectorstore = Mock()
        mock_retriever = Mock()
        mock_vectorstore.as_retriever.return_value = mock_retriever

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
        )

        with patch.object(vdb, 'get_langchain_vectorstore', return_value=mock_vectorstore), \
             patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.RunnableLambda') as mock_runnable_lambda, \
             patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.RunnableAssign') as mock_runnable_assign, \
             patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.otel_context') as mock_otel:

            mock_chain = Mock()
            mock_chain.invoke.return_value = {"context": mock_docs}

            mock_assign_instance = Mock()
            mock_assign_instance.__ror__ = Mock(return_value=mock_chain)
            mock_runnable_assign.return_value = mock_assign_instance

            mock_token = Mock()
            mock_otel.attach.return_value = mock_token
            mock_ctx = Mock()

            result = vdb.retrieval_langchain(
                query="test query",
                collection_name="test_collection",
                top_k=5,
                otel_ctx=mock_ctx,
            )

            assert len(result) == 2
            for doc in result:
                assert doc.metadata["collection_name"] == "test_collection"

            mock_otel.attach.assert_called_once_with(mock_ctx)
            mock_otel.detach.assert_called_once_with(mock_token)

    def test_add_collection_name_to_docs(self):
        """Test _add_collection_name_to_docs static method."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        docs = [
            Document(page_content="doc1", metadata={"source": "file1.txt"}),
            Document(page_content="doc2", metadata={"source": "file2.txt"})
        ]

        result = KdbaiVDB._add_collection_name_to_docs(docs, "test_collection")

        assert len(result) == 2
        for doc in result:
            assert doc.metadata["collection_name"] == "test_collection"
            assert "source" in doc.metadata

    # -------------------------------------------------------------------------
    # NV-Ingest Client VDB Interface Tests
    # -------------------------------------------------------------------------
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_check_index_exists(self, mock_get_config, mock_kdbai):
        """Test _check_index_exists method (NV-Ingest interface)."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database

        mock_table = Mock()
        mock_table.name = "existing_table"
        mock_database.tables = [mock_table]

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
        )

        assert vdb._check_index_exists("existing_table") is True
        assert vdb._check_index_exists("nonexistent_table") is False

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_create_index(self, mock_get_config, mock_kdbai):
        """Test create_index method (NV-Ingest interface)."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_config = Mock()
        mock_config.embeddings.dimensions = 2048
        mock_get_config.return_value = mock_config

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database
        mock_database.tables = []  # Empty, so table doesn't exist

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
            index_type="hnsw",
        )

        vdb.create_index()

        mock_database.create_table.assert_called_once()
        call_kwargs = mock_database.create_table.call_args[1]
        assert call_kwargs["table"] == "test_collection"
        assert call_kwargs["indexes"][0]["params"]["dims"] == 2048

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.cleanup_records')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.logger')
    def test_write_to_index(self, mock_logger, mock_cleanup_records, mock_get_config, mock_kdbai):
        """Test write_to_index method (NV-Ingest interface)."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_config = Mock()
        mock_get_config.return_value = mock_config

        mock_session = Mock()
        mock_database = Mock()
        mock_table = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database
        mock_database.table.return_value = mock_table

        # Mock cleanup_records return value
        cleaned_records = [
            {
                "text": "Document 1 content",
                "vector": [0.1, 0.2, 0.3],
                "source": "/path/to/doc1.pdf",
                "content_metadata": {"field1": "value1"},
            },
            {
                "text": "Document 2 content",
                "vector": [0.4, 0.5, 0.6],
                "source": "/path/to/doc2.pdf",
                "content_metadata": {"field1": "value2"},
            }
        ]
        mock_cleanup_records.return_value = cleaned_records

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
        )

        # Test data
        records = [{"some": "raw_record_data"}]

        vdb.write_to_index(records)

        # Assertions
        mock_cleanup_records.assert_called_once_with(
            records=records,
            meta_dataframe=None,
            meta_source_field=None,
            meta_fields=None,
        )

        # Verify table.insert was called
        mock_table.insert.assert_called_once()

        # Check the DataFrame passed to insert
        call_args = mock_table.insert.call_args[0][0]
        assert isinstance(call_args, pd.DataFrame)
        assert len(call_args) == 2
        assert "id" in call_args.columns
        assert "text" in call_args.columns
        assert "vector" in call_args.columns
        assert "source" in call_args.columns
        assert "content_metadata" in call_args.columns

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.cleanup_records')
    def test_write_to_index_batching(self, mock_cleanup_records, mock_get_config, mock_kdbai):
        """Test write_to_index batching behavior."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_config = Mock()
        mock_get_config.return_value = mock_config

        mock_session = Mock()
        mock_database = Mock()
        mock_table = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database
        mock_database.table.return_value = mock_table

        # Create 500 records to test batching (should result in 3 batches of 200, 200, 100)
        cleaned_records = [
            {"text": f"Doc {i}", "vector": [0.1], "source": f"doc{i}.pdf", "content_metadata": {}}
            for i in range(500)
        ]
        mock_cleanup_records.return_value = cleaned_records

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
        )

        vdb.write_to_index([])

        # Should be called 3 times (batches of 200, 200, 100)
        assert mock_table.insert.call_count == 3

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.cleanup_records')
    def test_run(self, mock_cleanup_records, mock_get_config, mock_kdbai):
        """Test run method (NV-Ingest interface)."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_config = Mock()
        mock_config.embeddings.dimensions = 2048
        mock_get_config.return_value = mock_config

        mock_session = Mock()
        mock_database = Mock()
        mock_table = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database
        mock_database.table.return_value = mock_table
        mock_database.tables = []  # Empty, so table doesn't exist

        mock_cleanup_records.return_value = [
            {"text": "Doc", "vector": [0.1], "source": "doc.pdf", "content_metadata": {}}
        ]

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
        )

        vdb.run([])

        # Verify create_table and insert were called
        mock_database.create_table.assert_called_once()
        mock_table.insert.assert_called_once()


class TestKdbaiVDBFactory:
    """Test the VDB factory function with KDB.AI."""

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.get_config')
    @patch('nvidia_rag.utils.vdb.get_metadata_configuration')
    def test_get_vdb_op_kdbai(self, mock_get_metadata, mock_get_config, mock_kdbai):
        """Test _get_vdb_op returns KdbaiVDB for kdbai config."""
        from nvidia_rag.utils.vdb import _get_vdb_op
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_config = Mock()
        mock_config.vector_store.name = "kdbai"
        mock_config.vector_store.url = "http://localhost:8082"
        mock_config.vector_store.search_type = "dense"
        mock_get_config.return_value = mock_config

        mock_get_metadata.return_value = (None, None, None)

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database

        with patch.dict('os.environ', {
            'KDBAI_API_KEY': 'test_key',
            'KDBAI_DATABASE': 'test_db',
            'KDBAI_INDEX_TYPE': 'hnsw',
        }):
            vdb = _get_vdb_op(
                vdb_endpoint="http://localhost:8082",
                collection_name="test_collection",
                embedding_model=Mock(),
            )

        assert isinstance(vdb, KdbaiVDB)


class TestKdbaiVDBGPU:
    """Test KDB.AI VDB GPU/cuVS functionality."""

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_init_with_gpu_enabled(self, mock_get_config, mock_kdbai):
        """Test KdbaiVDB initialization with GPU enabled - maps to cagra."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
            index_type="hnsw",
            enable_gpu_index=True,
            enable_gpu_search=True,
        )

        assert vdb.enable_gpu_index is True
        assert vdb.enable_gpu_search is True
        # When GPU enabled, hnsw maps to cagra (cuVS GPU index)
        assert vdb._effective_index_type == "cagra"

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_init_with_gpu_disabled(self, mock_get_config, mock_kdbai):
        """Test KdbaiVDB initialization with GPU disabled (default)."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
            index_type="hnsw",
        )

        assert vdb.enable_gpu_index is False
        assert vdb.enable_gpu_search is False
        assert vdb._effective_index_type == "hnsw"

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_resolve_index_type_cpu_mode(self, mock_get_config, mock_kdbai):
        """Test index type resolution in CPU mode."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database

        # Test various index types in CPU mode
        test_cases = ["hnsw", "flat", "ivf", "ivfpq", "HNSW", "FLAT"]

        for index_type in test_cases:
            vdb = KdbaiVDB(
                collection_name="test_collection",
                kdbai_endpoint="http://localhost:8082",
                embedding_model=Mock(),
                index_type=index_type,
                enable_gpu_index=False,
            )
            assert vdb._effective_index_type == index_type.lower()

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_resolve_index_type_gpu_mode(self, mock_get_config, mock_kdbai):
        """Test index type resolution in GPU mode - maps to cagra."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database

        # GPU-compatible types should map to cagra
        gpu_compatible_cases = [("hnsw", "cagra"), ("flat", "cagra"), ("HNSW", "cagra")]

        for input_type, expected_type in gpu_compatible_cases:
            vdb = KdbaiVDB(
                collection_name="test_collection",
                kdbai_endpoint="http://localhost:8082",
                embedding_model=Mock(),
                index_type=input_type,
                enable_gpu_index=True,
            )
            assert vdb._effective_index_type == expected_type

        # Non-GPU-compatible types should remain as-is
        non_gpu_cases = [("ivf", "ivf"), ("ivfpq", "ivfpq")]

        for input_type, expected_type in non_gpu_cases:
            vdb = KdbaiVDB(
                collection_name="test_collection",
                kdbai_endpoint="http://localhost:8082",
                embedding_model=Mock(),
                index_type=input_type,
                enable_gpu_index=True,
            )
            assert vdb._effective_index_type == expected_type

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_build_index_config_with_gpu(self, mock_get_config, mock_kdbai):
        """Test _build_index_config uses cagra type when GPU enabled."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_config = Mock()
        mock_config.embeddings.dimensions = 2048
        mock_get_config.return_value = mock_config

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
            index_type="hnsw",
            enable_gpu_index=True,
        )

        index_config = vdb._build_index_config(dimension=2048)

        assert len(index_config) == 1
        # When GPU enabled with hnsw, should use cagra (cuVS GPU index)
        assert index_config[0]["type"] == "cagra"
        # cagra only needs metric param (no dims)
        assert "metric" in index_config[0]["params"]
        # No explicit gpu param - the index type itself is GPU-accelerated
        assert "gpu" not in index_config[0]["params"]

    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    def test_build_index_config_without_gpu(self, mock_get_config, mock_kdbai):
        """Test _build_index_config does not include GPU params when disabled."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_config = Mock()
        mock_config.embeddings.dimensions = 2048
        mock_get_config.return_value = mock_config

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
            index_type="hnsw",
            enable_gpu_index=False,
        )

        index_config = vdb._build_index_config(dimension=2048)

        assert len(index_config) == 1
        assert "gpu" not in index_config[0]["params"]

    @pytest.mark.asyncio
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    async def test_check_health_includes_gpu_status(self, mock_get_config, mock_kdbai):
        """Test check_health includes GPU status information."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database
        mock_session.version.return_value = {"version": "1.0.0"}
        mock_database.tables = []

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
            enable_gpu_index=True,
            enable_gpu_search=True,
        )

        result = await vdb.check_health()

        assert result["gpu_index_enabled"] is True
        assert result["gpu_search_enabled"] is True
        assert "effective_index_type" in result
        assert result["status"] == "healthy"

    @pytest.mark.asyncio
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.kdbai')
    @patch('nvidia_rag.utils.vdb.kdbai.kdbai_vdb.get_config')
    async def test_check_health_cpu_mode(self, mock_get_config, mock_kdbai):
        """Test check_health shows CPU mode when GPU disabled."""
        from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB

        mock_session = Mock()
        mock_database = Mock()
        mock_kdbai.Session.return_value = mock_session
        mock_session.database.return_value = mock_database
        mock_session.version.return_value = {"version": "1.0.0"}
        mock_database.tables = []

        vdb = KdbaiVDB(
            collection_name="test_collection",
            kdbai_endpoint="http://localhost:8082",
            embedding_model=Mock(),
            enable_gpu_index=False,
            enable_gpu_search=False,
        )

        result = await vdb.check_health()

        assert result["gpu_index_enabled"] is False
        assert result["gpu_search_enabled"] is False
