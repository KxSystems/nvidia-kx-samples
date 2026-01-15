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

"""
KDB.AI Vector Database implementation for RAG applications.

This module provides the KdbaiVDB class which implements the VDBRag interface
for KDB.AI vector database. It supports:

- Collection management (create, check, list, delete)
- Document management (get, delete by source)
- Metadata schema storage
- Vector similarity search via LangChain integration
- NV-Ingest pipeline integration for document ingestion
- GPU-accelerated indexing via NVIDIA cuVS (CAGRA index)

GPU Acceleration (cuVS):
    When using the KDB.AI cuVS Docker image (e.g., kdbai-db:*-cuvs), set
    enable_gpu_index=True to use GPU-accelerated vector indexing. This
    automatically maps compatible index types (hnsw, flat) to 'cagra'
    (CUDA Approximate Graph-based Nearest Neighbor) for GPU acceleration.

    Supported GPU Index Types:
    - cagra: NVIDIA cuVS CAGRA index (GPU-accelerated approximate nearest neighbor)

    CPU Index Types (default):
    - hnsw: Hierarchical Navigable Small World
    - flat: Brute-force exact search

NV-Ingest Client VDB Operations:
1. _check_index_exists: Check if the table exists in KDB.AI
2. create_index: Create a table in KDB.AI
3. write_to_index: Write records to the KDB.AI table
4. run: Run the process of ingestion of records to the KDB.AI table

Connection Management:
5. Session-based connection to KDB.AI Cloud or Server
6. Database and table management

Collection Management:
7. create_collection: Create a new table with vector index
8. check_collection_exists: Check if table exists
9. get_collection: List all tables with metadata schemas
10. delete_collections: Drop tables and clean metadata

Document Management:
11. get_documents: Get unique documents from a table
12. delete_documents: Delete documents by source filter

Metadata Schema Management:
13. create_metadata_schema_collection: Initialize metadata storage table
14. add_metadata_schema: Store schema for a collection
15. get_metadata_schema: Retrieve schema for a collection

Retrieval Operations:
16. get_langchain_vectorstore: Get LangChain KDBAI VectorStore
17. retrieval_langchain: Perform semantic search via LangChain
"""

import json
import logging
import os
import time
from typing import Any, List, Optional
from uuid import uuid4

import pandas as pd
from langchain_community.vectorstores import KDBAI
from langchain_community.vectorstores.kdbai import DistanceStrategy
from langchain_core.documents import Document
from langchain_core.runnables import RunnableAssign, RunnableLambda
from nv_ingest_client.util.milvus import cleanup_records
from opentelemetry import context as otel_context

from nvidia_rag.utils.common import get_config
from nvidia_rag.utils.vdb import DEFAULT_METADATA_SCHEMA_COLLECTION
from nvidia_rag.utils.vdb.kdbai.kdbai_filters import (
    build_source_filter,
    milvus_to_kdbai_filter,
)
from nvidia_rag.utils.vdb.vdb_base import VDBRag

logger = logging.getLogger(__name__)

# Enable verbose debug logging via environment variable
KDBAI_DEBUG = os.getenv("KDBAI_DEBUG", "false").lower() == "true"

# Batch size for inserting records into KDB.AI
# Can be overridden via environment variable for performance tuning
KDBAI_INSERT_BATCH_SIZE = int(os.getenv("KDBAI_INSERT_BATCH_SIZE", "200"))

# CAGRA extend workaround: cuvsCagraExtend() crashes when extending existing index.
# Set to "true" to force single-batch insert for GPU indexes (avoids extend).
# When KDB.AI/cuVS fixes this issue, set to "false" to use normal batch size.
KDBAI_CAGRA_SINGLE_BATCH = os.getenv("KDBAI_CAGRA_SINGLE_BATCH", "true").lower() == "true"

# cuVS CAGRA itopk_size: number of candidates considered during GPU search.
# Higher values = better accuracy but slower. Must be >= top_k.
# Default 128 provides good balance. Set higher (256, 512) for large top_k.
KDBAI_CAGRA_ITOPK_SIZE = int(os.getenv("KDBAI_CAGRA_ITOPK_SIZE", "128"))

try:
    import kdbai_client as kdbai
except ImportError:
    logger.warning("kdbai_client module not installed. Install with: pip install kdbai-client")
    kdbai = None

CONFIG = get_config()

# Default schema for document tables
DEFAULT_TABLE_SCHEMA = [
    {"name": "id", "type": "str"},
    {"name": "text", "type": "str"},
    {"name": "vector", "type": "float32s"},
    {"name": "source", "type": "str"},
    {"name": "content_metadata", "type": "str"},  # JSON string
]

# Schema for metadata storage table
METADATA_SCHEMA_TABLE_SCHEMA = [
    {"name": "id", "type": "str"},
    {"name": "collection_name", "type": "str"},
    {"name": "metadata_schema", "type": "str"},  # JSON string
]


class KdbaiVDB(VDBRag):
    """
    KDB.AI Vector Database implementation for RAG applications.

    Uses the kdbai_client SDK to interface with KDB.AI Cloud or Server
    for vector storage and similarity search operations.
    """

    def __init__(
        self,
        collection_name: str,
        kdbai_endpoint: str,
        api_key: Optional[str] = None,
        database_name: str = "default",
        embedding_model=None,
        index_type: str = "hnsw",
        metric: str = "L2",
        enable_gpu_index: bool = False,
        enable_gpu_search: bool = False,
        **kwargs,
    ):
        """
        Initialize KDB.AI VDB.

        Args:
            collection_name: Default collection/table name
            kdbai_endpoint: KDB.AI endpoint URL (cloud or server)
            api_key: API key for KDB.AI Cloud (optional for local server)
            database_name: Database name in KDB.AI
            embedding_model: LangChain embedding model for retrieval
            index_type: Index type (flat, hnsw, ivf, ivfpq, or cuVS types)
            metric: Distance metric (L2, CS for cosine, IP for inner product)
            enable_gpu_index: Enable GPU-accelerated indexing via cuVS
            enable_gpu_search: Enable GPU-accelerated search via cuVS
        """
        if kdbai is None:
            raise ImportError(
                "kdbai_client is required for KDB.AI support. "
                "Install with: pip install kdbai-client"
            )

        self._collection_name = collection_name
        self.kdbai_endpoint = kdbai_endpoint
        self.api_key = api_key
        self.database_name = database_name
        self.embedding_model = embedding_model
        self.index_type = index_type
        self.metric = metric

        # GPU/cuVS configuration
        self.enable_gpu_index = enable_gpu_index
        self.enable_gpu_search = enable_gpu_search

        # Resolve effective index type based on GPU settings
        self._effective_index_type = self._resolve_index_type(index_type)

        # Store additional kwargs for metadata handling (NV-Ingest Client compatibility)
        self.meta_dataframe = kwargs.get("meta_dataframe")
        self.meta_source_field = kwargs.get("meta_source_field")
        self.meta_fields = kwargs.get("meta_fields")
        self.csv_file_path = kwargs.get("csv_file_path")

        # Initialize session
        self._session = self._create_session()
        self._database = self._get_or_create_database()

        gpu_status = f", GPU index={enable_gpu_index}, GPU search={enable_gpu_search}" if enable_gpu_index or enable_gpu_search else ""
        logger.info(
            f"Connected to KDB.AI at {kdbai_endpoint}, database: {database_name}{gpu_status}"
        )

    def _create_session(self) -> "kdbai.Session":
        """Create KDB.AI session."""
        session_kwargs = {"endpoint": self.kdbai_endpoint}
        if self.api_key:
            session_kwargs["api_key"] = self.api_key

        return kdbai.Session(**session_kwargs)

    def _get_or_create_database(self) -> "kdbai.Database":
        """Get or create the database."""
        try:
            return self._session.database(self.database_name)
        except Exception:
            # Database might not exist, try to create it
            try:
                self._session.create_database(self.database_name)
                return self._session.database(self.database_name)
            except Exception as e:
                logger.warning(f"Could not create database {self.database_name}: {e}")
                # Fall back to default database
                return self._session.database("default")

    # GPU index type: cuVS CAGRA (CUDA Approximate Graph-based Nearest Neighbor)
    # When GPU indexing is enabled, compatible index types are mapped to 'cagra'
    # itopk_size parameter controls max results (default 64, configurable via KDBAI_CAGRA_ITOPK_SIZE)
    GPU_INDEX_TYPE = "cagra"
    GPU_COMPATIBLE_INDEX_TYPES = {"hnsw", "flat"}

    def _resolve_index_type(self, requested_type: str) -> str:
        """
        Resolve the effective index type based on GPU settings.

        When GPU indexing is enabled, maps compatible index types to 'cagra'
        for GPU-accelerated search via NVIDIA cuVS.

        Args:
            requested_type: The originally requested index type

        Returns:
            The effective index type (cagra for GPU mode, or original)
        """
        normalized_type = requested_type.lower()

        if self.enable_gpu_index:
            # If already cagra, use it directly
            if normalized_type == self.GPU_INDEX_TYPE:
                logger.info(
                    f"GPU indexing enabled with '{normalized_type}' (cuVS). "
                    f"itopk_size={KDBAI_CAGRA_ITOPK_SIZE} (set KDBAI_CAGRA_ITOPK_SIZE to change)."
                )
                return normalized_type
            elif normalized_type in self.GPU_COMPATIBLE_INDEX_TYPES:
                logger.info(
                    f"GPU indexing enabled: mapping '{normalized_type}' -> 'cagra' (cuVS). "
                    f"itopk_size={KDBAI_CAGRA_ITOPK_SIZE} (set KDBAI_CAGRA_ITOPK_SIZE to change)."
                )
                return self.GPU_INDEX_TYPE
            else:
                logger.warning(
                    f"GPU indexing enabled but '{normalized_type}' is not GPU-compatible. "
                    f"Supported types: {self.GPU_COMPATIBLE_INDEX_TYPES} or 'cagra'. "
                    f"Using '{normalized_type}' as-is (CPU)."
                )

        return normalized_type

    def close(self):
        """Close the KDB.AI session."""
        if self._session:
            try:
                self._session.close()
                logger.debug("Closed KDB.AI session")
            except Exception as e:
                logger.warning(f"Error closing KDB.AI session: {e}")

    def __enter__(self):
        """Enter context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager."""
        self.close()

    @property
    def collection_name(self) -> str:
        """Get the collection name."""
        return self._collection_name

    @collection_name.setter
    def collection_name(self, value: str):
        """Set the collection name."""
        self._collection_name = value

    # -------------------------------------------------------------------------
    # NV-Ingest Client VDB Interface Methods
    # -------------------------------------------------------------------------
    def _check_index_exists(self, table_name: str) -> bool:
        """
        Check if the table exists in KDB.AI.

        This method is part of the nv-ingest-client VDB interface.
        """
        return self.check_collection_exists(table_name)

    def create_index(self) -> None:
        """
        Create a table in KDB.AI.

        This method is part of the nv-ingest-client VDB interface.
        Creates the table if it doesn't exist using the configured collection name.
        """
        logger.info(f"Creating KDB.AI table if not exists: {self._collection_name}")
        self.create_collection(
            collection_name=self._collection_name,
            dimension=CONFIG.embeddings.dimensions,
        )

    def write_to_index(self, records: list, **kwargs) -> None:
        """
        Write records to the KDB.AI table in batches.

        This method is part of the nv-ingest-client VDB interface.
        It processes records from the nv-ingest pipeline and stores them in KDB.AI.

        Args:
            records: List of records from nv-ingest pipeline
            **kwargs: Additional arguments (unused)
        """
        # Clean up and flatten records to pull appropriate fields
        cleaned_records = cleanup_records(
            records=records,
            meta_dataframe=self.meta_dataframe,
            meta_source_field=self.meta_source_field,
            meta_fields=self.meta_fields,
        )

        # Prepare data for KDB.AI insertion
        data_rows = []
        for cleaned_record in cleaned_records:
            # Extract source - can be a dict (source_metadata) or string
            source_data = cleaned_record.get("source", "")
            if isinstance(source_data, dict):
                # source_metadata dict has 'source_name' key
                source = source_data.get("source_name", "")
            else:
                source = str(source_data) if source_data else ""

            row = {
                "id": str(uuid4()),
                "text": cleaned_record.get("text", ""),
                "vector": cleaned_record.get("vector", []),
                "source": source,
                "content_metadata": json.dumps(cleaned_record.get("content_metadata", {})),
            }
            data_rows.append(row)

        total_records = len(data_rows)
        uploaded_count = 0

        # CAGRA (cuVS GPU) index limitation: cuvsCagraExtend() can crash when
        # extending an existing index. To avoid this, insert all data in a single
        # batch when GPU indexing is enabled AND the workaround is active.
        #
        # When KDB.AI/cuVS fixes cuvsCagraExtend(), set KDBAI_CAGRA_SINGLE_BATCH=false
        # to use normal batch size (200) for better memory efficiency.
        if self.enable_gpu_index and KDBAI_CAGRA_SINGLE_BATCH:
            batch_size = total_records  # Single batch for CAGRA to avoid extend
            logger.info(
                f"GPU indexing enabled (CAGRA) with single-batch workaround. "
                f"Inserting {total_records} records at once to avoid cuvsCagraExtend() crash. "
                f"Set KDBAI_CAGRA_SINGLE_BATCH=false when KDB.AI fixes this issue."
            )
        else:
            batch_size = KDBAI_INSERT_BATCH_SIZE

        logger.info(
            f"Commencing KDB.AI ingestion process for {total_records} records..."
        )

        # Get the table
        table = self._database.table(self._collection_name)

        # Log first record's vector dimension for debugging
        if data_rows:
            first_vector = data_rows[0].get("vector", [])
            logger.info(
                f"First record vector dimension: {len(first_vector) if first_vector else 0}"
            )
            if KDBAI_DEBUG and first_vector:
                logger.debug(f"First record vector sample (first 5): {first_vector[:5]}")

        # Process records in batches
        for i in range(0, total_records, batch_size):
            end_idx = min(i + batch_size, total_records)
            batch_data = data_rows[i:end_idx]

            # Convert to DataFrame for KDB.AI insertion
            batch_df = pd.DataFrame(batch_data)

            # Insert batch into KDB.AI with detailed error handling
            try:
                table.insert(batch_df)
            except Exception as insert_error:
                error_msg = str(insert_error)
                logger.error(
                    f"KDB.AI insert failed at batch {i//batch_size + 1} "
                    f"(records {i}-{end_idx}): {error_msg}"
                )
                # Log sample record details for debugging
                if batch_data:
                    sample = batch_data[0]
                    sample_vector = sample.get("vector", [])
                    logger.error(
                        f"Sample record - id: {sample.get('id')}, "
                        f"text length: {len(sample.get('text', ''))}, "
                        f"vector dim: {len(sample_vector) if sample_vector else 0}, "
                        f"source: {sample.get('source', '')[:50]}"
                    )
                # Re-raise with more context
                raise RuntimeError(
                    f"KDB.AI insert failed for batch {i//batch_size + 1}: {error_msg}"
                ) from insert_error

            uploaded_count += len(batch_data)

            # Log progress every 5 batches (1000 records)
            if (
                uploaded_count % (5 * batch_size) == 0
                or uploaded_count == total_records
            ):
                logger.info(
                    f"Successfully ingested {uploaded_count} records into KDB.AI table {self._collection_name}"
                )

        logger.info(
            f"KDB.AI ingestion completed. Total records processed: {uploaded_count}"
        )

    def run(self, records: list) -> None:
        """
        Run the full ingestion process to KDB.AI table.

        This method is part of the nv-ingest-client VDB interface.
        Creates the index if needed and writes all records.

        Args:
            records: List of records from nv-ingest pipeline
        """
        self.create_index()
        self.write_to_index(records)

    def retrieval(self, queries: list, **kwargs) -> List[dict[str, Any]]:
        """
        Retrieve documents from KDB.AI based on queries.

        This method is part of the nv-ingest-client VDB interface.

        Args:
            queries: List of query strings or vectors
            **kwargs: Additional arguments (top_k, filter, etc.)

        Returns:
            List of retrieved documents
        """
        # This is a placeholder - the main retrieval is done via retrieval_langchain
        raise NotImplementedError("Use retrieval_langchain for KDB.AI retrieval")

    def reindex(self, records: list, **kwargs) -> None:
        """
        Reindex documents in KDB.AI.

        This method is part of the nv-ingest-client VDB interface.

        Args:
            records: List of records to reindex
            **kwargs: Additional arguments
        """
        # For reindex, we delete and recreate
        logger.info(f"Reindexing {len(records)} records in {self._collection_name}")

        # Delete existing table and recreate
        if self.check_collection_exists(self._collection_name):
            table = self._database.table(self._collection_name)
            table.drop()

        # Run full ingestion
        self.run(records)

    # -------------------------------------------------------------------------
    # Health Check
    # -------------------------------------------------------------------------
    async def check_health(self) -> dict[str, Any]:
        """Check KDB.AI health status including GPU configuration."""
        status = {
            "service": "KDB.AI",
            "url": self.kdbai_endpoint,
            "status": "unknown",
            "error": None,
            "gpu_index_enabled": self.enable_gpu_index,
            "gpu_search_enabled": self.enable_gpu_search,
            "effective_index_type": self._effective_index_type,
        }

        if not self.kdbai_endpoint:
            status["status"] = "skipped"
            status["error"] = "No endpoint provided"
            return status

        try:
            start_time = time.time()

            # Test connection by listing tables
            tables = self._database.tables
            version_info = self._session.version()

            status["status"] = "healthy"
            status["latency_ms"] = round((time.time() - start_time) * 1000, 2)
            status["tables"] = len(tables) if tables else 0
            status["version"] = str(version_info) if version_info else "unknown"

        except Exception as e:
            status["status"] = "error"
            status["error"] = str(e)

        return status

    # -------------------------------------------------------------------------
    # Collection Management
    # -------------------------------------------------------------------------
    def create_collection(
        self,
        collection_name: str,
        dimension: int = 2048,
        collection_type: str = "text",
    ) -> None:
        """
        Create a new table in KDB.AI with vector index.

        Args:
            collection_name: Name of the table to create
            dimension: Vector dimension (default 2048)
            collection_type: Type of collection (text, image, etc.)
        """
        # Check if already exists
        if self.check_collection_exists(collection_name):
            logger.info(f"Table {collection_name} already exists")
            return

        # Build schema with correct dimension
        schema = [
            {"name": "id", "type": "str"},
            {"name": "text", "type": "str"},
            {"name": "vector", "type": "float32s"},
            {"name": "source", "type": "str"},
            {"name": "content_metadata", "type": "str"},
        ]

        # Build index configuration
        index_config = self._build_index_config(dimension)

        if KDBAI_DEBUG:
            logger.debug(f"Creating KDB.AI table with schema: {schema}")
            logger.debug(f"Index configuration: {index_config}")

        try:
            self._database.create_table(
                table=collection_name,
                schema=schema,
                indexes=index_config,
            )
            logger.info(
                f"Created KDB.AI table: {collection_name} with {self.index_type} index"
            )

        except Exception as e:
            logger.error(f"Failed to create table {collection_name}: {e}")
            raise

    def _build_index_config(self, dimension: int) -> List[dict]:
        """
        Build index configuration based on index_type and GPU settings.

        When GPU indexing is enabled with the cuVS image, the index type is
        resolved to 'cagra' (CUDA Approximate Graph-based Nearest Neighbor)
        which uses GPU acceleration from NVIDIA cuVS library.
        """
        # Use the effective index type (resolved based on GPU settings)
        index_type = self._effective_index_type

        # Map common names to KDB.AI types
        type_mapping = {
            "hnsw": "hnsw",
            "flat": "flat",
            "qflat": "qFlat",
            "qhnsw": "qHNSW",
            "ivf": "ivf",
            "ivfpq": "ivfpq",
            "cagra": "cagra",  # GPU-accelerated index from NVIDIA cuVS
        }
        kdbai_type = type_mapping.get(index_type, index_type)

        # Build base index parameters
        index_params = {
            "name": "vectorIndex",  # Use camelCase as per KDB.AI examples
            "type": kdbai_type,
            "column": "vector",
            "params": {},
        }

        # Add type-specific parameters
        if kdbai_type == "cagra":
            # CAGRA (cuVS GPU index) - only requires metric parameter
            index_params["params"]["metric"] = self.metric
        elif kdbai_type in ("hnsw", "qHNSW"):
            index_params["params"].update({
                "dims": dimension,
                "metric": self.metric,
                "M": 8,
                "efConstruction": 8,
            })
        elif kdbai_type in ("flat", "qFlat"):
            index_params["params"].update({
                "dims": dimension,
                "metric": self.metric,
            })
        elif kdbai_type == "ivf":
            index_params["params"].update({
                "nlist": 8,
            })
        elif kdbai_type == "ivfpq":
            index_params["params"].update({
                "nlist": 8,
                "nbits": 8,
                "nsplits": 8,
            })
        else:
            # Default params for unknown types
            index_params["params"].update({
                "dims": dimension,
                "metric": self.metric,
            })

        is_gpu = kdbai_type == "cagra"
        gpu_status = " (GPU cuVS)" if is_gpu else ""
        logger.info(f"Built index config{gpu_status}: {index_params}")
        return [index_params]

    def check_collection_exists(self, collection_name: str) -> bool:
        """Check if a table exists in KDB.AI."""
        try:
            tables = self._database.tables
            if tables is None:
                return False
            # tables is a list of table names or table objects
            table_names = [
                t.name if hasattr(t, "name") else str(t) for t in tables
            ]
            return collection_name in table_names
        except Exception as e:
            logger.warning(f"Error checking table existence: {e}")
            return False

    def _get_table(self, collection_name: str) -> Optional[Any]:
        """Get a table object by name."""
        try:
            return self._database.table(collection_name)
        except Exception as e:
            logger.warning(f"Could not get table {collection_name}: {e}")
            return None

    def get_collection(self) -> List[dict[str, Any]]:
        """Get all collections with their metadata schemas."""
        self.create_metadata_schema_collection()

        collection_info = []
        try:
            tables = self._database.tables or []

            for table in tables:
                table_name = table.name if hasattr(table, "name") else str(table)

                # Skip the metadata schema table
                if table_name == DEFAULT_METADATA_SCHEMA_COLLECTION:
                    continue

                # Get row count
                try:
                    table_obj = self._database.table(table_name)
                    # KDB.AI doesn't have a direct count method
                    # Query with only 'id' column to minimize data transfer
                    result = table_obj.query()
                    if result is not None and hasattr(result, '__len__'):
                        num_entities = len(result)
                    elif result is not None and hasattr(result, 'shape'):
                        # Handle pandas DataFrame
                        num_entities = result.shape[0]
                    else:
                        num_entities = 0
                except Exception as e:
                    if KDBAI_DEBUG:
                        logger.debug(f"Error getting row count for {table_name}: {e}")
                    num_entities = 0

                # Get metadata schema
                metadata_schema = self.get_metadata_schema(table_name)

                collection_info.append({
                    "collection_name": table_name,
                    "num_entities": num_entities,
                    "metadata_schema": metadata_schema,
                })

        except Exception as e:
            logger.error(f"Error listing collections: {e}")

        return collection_info

    def delete_collections(self, collection_names: List[str]) -> dict[str, Any]:
        """Delete collections and their metadata schemas."""
        deleted = []
        failed = []

        for name in collection_names:
            try:
                if self.check_collection_exists(name):
                    table = self._database.table(name)
                    table.drop()
                    deleted.append(name)
                    logger.info(f"Deleted table: {name}")

                    # Delete metadata schema entry
                    self._delete_metadata_schema_entry(name)
                else:
                    failed.append({
                        "collection_name": name,
                        "error_message": f"Table {name} not found",
                    })
            except Exception as e:
                failed.append({
                    "collection_name": name,
                    "error_message": str(e),
                })
                logger.error(f"Failed to delete table {name}: {e}")

        return {
            "message": "Collection deletion completed",
            "successful": deleted,
            "failed": failed,
            "total_success": len(deleted),
            "total_failed": len(failed),
        }

    # -------------------------------------------------------------------------
    # Document Management
    # -------------------------------------------------------------------------
    def get_documents(self, collection_name: str) -> List[dict[str, Any]]:
        """Get unique documents from a collection."""
        metadata_schema = self.get_metadata_schema(collection_name)

        try:
            table = self._database.table(collection_name)

            # Query all records to get unique sources
            # Note: KDB.AI may have pagination limits
            result = table.query(limit=10000)

            if result is None or len(result) == 0:
                return []

            # Convert to DataFrame if not already
            if not isinstance(result, pd.DataFrame):
                result = pd.DataFrame(result)

            # Get unique sources
            documents = []
            seen_sources = set()

            for _, row in result.iterrows():
                source = row.get("source", "")
                if not source or source in seen_sources:
                    continue

                seen_sources.add(source)
                filename = os.path.basename(source) if source else ""

                # Parse content metadata
                content_meta_str = row.get("content_metadata", "{}")
                try:
                    content_meta = json.loads(content_meta_str) if content_meta_str else {}
                except (json.JSONDecodeError, TypeError):
                    content_meta = {}

                # Build metadata dict based on schema
                metadata_dict = {}
                for schema_item in metadata_schema:
                    field_name = schema_item.get("name")
                    metadata_dict[field_name] = content_meta.get(field_name)

                documents.append({
                    "document_name": filename,
                    "metadata": metadata_dict,
                })

            return documents

        except Exception as e:
            logger.error(f"Error getting documents from {collection_name}: {e}")
            return []

    def delete_documents(
        self,
        collection_name: str,
        source_values: List[str],
    ) -> bool:
        """Delete documents by source values."""
        try:
            table = self._database.table(collection_name)
            deleted = False

            for source_value in source_values:
                # Build filter for source
                filter_expr = build_source_filter(source_value)

                try:
                    # KDB.AI delete with filter
                    # Note: API may vary - check kdbai_client docs
                    table.delete(filter=filter_expr)
                    deleted = True
                    logger.info(f"Deleted documents with source: {source_value}")
                except Exception as e:
                    logger.warning(f"Could not delete by filter, trying query: {e}")
                    # Fallback: query and delete by IDs
                    results = table.query(filter=filter_expr, limit=10000)
                    if results is not None and len(results) > 0:
                        ids_to_delete = [r.get("id") for r in results if r.get("id")]
                        if ids_to_delete:
                            for doc_id in ids_to_delete:
                                try:
                                    table.delete(filter=[("=", "id", doc_id)])
                                except Exception:
                                    pass
                            deleted = True

            return deleted

        except Exception as e:
            logger.error(f"Error deleting documents: {e}")
            return False

    # -------------------------------------------------------------------------
    # Metadata Schema Management
    # -------------------------------------------------------------------------
    def create_metadata_schema_collection(self) -> None:
        """Create the metadata schema storage table."""
        if self.check_collection_exists(DEFAULT_METADATA_SCHEMA_COLLECTION):
            return

        try:
            # KDB.AI requires tables to have a schema
            # For metadata storage, we use a simple schema without vector index
            schema = [
                {"name": "id", "type": "str"},
                {"name": "collection_name", "type": "str"},
                {"name": "metadata_schema", "type": "str"},
            ]

            self._database.create_table(
                table=DEFAULT_METADATA_SCHEMA_COLLECTION,
                schema=schema,
            )
            logger.info(f"Created metadata schema table: {DEFAULT_METADATA_SCHEMA_COLLECTION}")

        except Exception as e:
            # Table might already exist or creation failed
            logger.error(f"Could not create metadata schema table: {e}")

    def add_metadata_schema(
        self,
        collection_name: str,
        metadata_schema: List[dict[str, Any]],
    ) -> None:
        """Store metadata schema for a collection."""
        if KDBAI_DEBUG:
            logger.debug(f"Adding metadata schema for {collection_name}: {metadata_schema}")
        self.create_metadata_schema_collection()

        try:
            table = self._database.table(DEFAULT_METADATA_SCHEMA_COLLECTION)

            # Delete existing schema for this collection
            self._delete_metadata_schema_entry(collection_name)

            # Insert new schema
            schema_json = json.dumps(metadata_schema)
            data = pd.DataFrame([{
                "id": str(uuid4()),
                "collection_name": collection_name,
                "metadata_schema": schema_json,
            }])

            table.insert(data)
            logger.info(f"Added metadata schema for {collection_name}")

        except Exception as e:
            logger.error(f"Error adding metadata schema for {collection_name}: {e}")

    def _delete_metadata_schema_entry(self, collection_name: str) -> None:
        """Delete metadata schema entry for a collection."""
        try:
            if not self.check_collection_exists(DEFAULT_METADATA_SCHEMA_COLLECTION):
                return

            table = self._database.table(DEFAULT_METADATA_SCHEMA_COLLECTION)
            # KDB.AI filter format: list of tuples ("operator", "column", value)
            filter_expr = [("=", "collection_name", collection_name)]

            try:
                table.delete(filter=filter_expr)
            except Exception:
                # Fallback: query and delete by ID
                results = table.query(filter=filter_expr, limit=100)
                if results is not None:
                    for row in results:
                        if isinstance(row, dict) and row.get("id"):
                            try:
                                table.delete(filter=[("=", "id", row["id"])])
                            except Exception:
                                pass

        except Exception as e:
            logger.warning(f"Error deleting metadata schema entry: {e}")

    def get_metadata_schema(self, collection_name: str) -> List[dict[str, Any]]:
        """Get metadata schema for a collection."""
        try:
            if not self.check_collection_exists(DEFAULT_METADATA_SCHEMA_COLLECTION):
                if KDBAI_DEBUG:
                    logger.debug("Metadata schema table does not exist")
                return []

            table = self._database.table(DEFAULT_METADATA_SCHEMA_COLLECTION)
            # KDB.AI filter format: list of tuples ("operator", "column", value)
            filter_expr = [("=", "collection_name", collection_name)]

            results = table.query(filter=filter_expr, limit=1)

            if results is not None and len(results) > 0:
                # Handle both list and DataFrame results
                if isinstance(results, list):
                    row = results[0]
                elif hasattr(results, 'iloc'):
                    row = results.iloc[0].to_dict()
                else:
                    row = results

                schema_json = row.get("metadata_schema", "[]")
                parsed_schema = json.loads(schema_json) if schema_json else []
                if KDBAI_DEBUG:
                    logger.debug(f"Retrieved metadata schema for {collection_name}: {parsed_schema}")
                return parsed_schema

        except Exception as e:
            logger.error(f"Error getting metadata schema for {collection_name}: {e}")

        return []

    # -------------------------------------------------------------------------
    # Retrieval Operations
    # -------------------------------------------------------------------------
    def get_langchain_vectorstore(self, collection_name: str) -> KDBAI:
        """
        Get LangChain KDBAI VectorStore for a collection.

        Args:
            collection_name: Name of the table

        Returns:
            LangChain KDBAI VectorStore instance
        """
        table = self._database.table(collection_name)

        # Map metric to DistanceStrategy
        distance_strategy = DistanceStrategy.EUCLIDEAN_DISTANCE
        if self.metric == "CS":
            distance_strategy = DistanceStrategy.COSINE
        elif self.metric == "IP":
            distance_strategy = DistanceStrategy.DOT_PRODUCT

        return KDBAI(
            table=table,
            embedding=self.embedding_model,
            distance_strategy=distance_strategy,
        )

    def retrieval_langchain(
        self,
        query: str,
        collection_name: str,
        vectorstore: KDBAI = None,
        top_k: int = 10,
        filter_expr: str = "",
        otel_ctx: otel_context = None,
    ) -> List[Document]:
        """
        Retrieve documents using direct KDB.AI table search.

        The LangChain KDBAI integration has a compatibility issue with newer
        kdbai_client versions where vectors must be passed as a dict, not a list.
        This method bypasses LangChain and calls the table.search directly.

        Args:
            query: Search query string
            collection_name: Collection to search
            vectorstore: Optional pre-created vectorstore (unused, kept for API compat)
            top_k: Number of results to return
            filter_expr: Optional filter expression (Milvus-style)
            otel_ctx: OpenTelemetry context

        Returns:
            List of retrieved Document objects
        """
        start_time = time.time()
        token = otel_context.attach(otel_ctx)

        try:
            # Get the table directly
            table = self._database.table(collection_name)

            # Embed the query using the embedding model
            query_embedding = self.embedding_model.embed_query(query)

            # Convert filter expression if provided
            kdbai_filter = None
            if filter_expr:
                kdbai_filter = milvus_to_kdbai_filter(filter_expr)

            # Call table.search with vectors as dict (kdbai_client format)
            # The key is the INDEX NAME (not column name), value is list of embeddings
            # Format: {"indexName": [[vector1], [vector2], ...]} for batch queries
            effective_top_k = top_k

            search_kwargs = {
                "vectors": {"vectorIndex": [query_embedding]},
                "n": effective_top_k,
            }

            # For cagra (GPU) index, set itopk_size via index_params
            # itopk_size controls the number of candidates considered during search
            # Must be >= n (top_k). Higher values = better accuracy, slower search.
            if self.enable_gpu_search:
                # Set itopk_size to at least top_k, or use configured default
                itopk_size = max(effective_top_k, KDBAI_CAGRA_ITOPK_SIZE)
                search_kwargs["index_params"] = {"itopk_size": itopk_size}
                logger.info(
                    f"GPU search enabled: using itopk_size={itopk_size} for n={effective_top_k}"
                )

            if kdbai_filter:
                search_kwargs["filter"] = kdbai_filter

            try:
                matches = table.search(**search_kwargs)
                if KDBAI_DEBUG:
                    logger.debug(f"KDB.AI search returned: type={type(matches)}")
            except Exception as search_error:
                error_msg = str(search_error)
                if "Index not found" in error_msg or "Neither Sparse nor Dense" in error_msg:
                    logger.error(
                        f"Vector index not found for table '{collection_name}'. "
                        f"The table may have been created without an index. "
                        f"Please delete and recreate the collection, then re-ingest documents."
                    )
                raise

            # Process results into LangChain Documents
            docs = []
            if matches is not None:
                # matches is a list of DataFrames (one per query vector)
                if isinstance(matches, list) and len(matches) > 0:
                    results_df = matches[0]
                else:
                    results_df = matches

                if hasattr(results_df, "to_dict"):
                    records = results_df.to_dict(orient="records")
                    if KDBAI_DEBUG:
                        logger.debug(f"Got {len(records)} records from search")
                        if records:
                            logger.debug(f"First record keys: {list(records[0].keys())}")

                    for i, row in enumerate(records):
                        text = row.get("text", "")

                        # Decode bytes if necessary
                        if isinstance(text, bytes):
                            text = text.decode("utf-8")
                        elif isinstance(text, (list, tuple)) and len(text) > 0:
                            # Handle case where text is stored as list of bytes
                            if isinstance(text[0], int):
                                text = bytes(text).decode("utf-8")
                            else:
                                text = str(text)

                        # Skip empty text
                        if not text or not text.strip():
                            if KDBAI_DEBUG:
                                logger.debug(f"Empty text in record {i}")
                            continue

                        if KDBAI_DEBUG and i == 0:
                            logger.debug(f"First record text (first 200 chars): {text[:200]}")

                        # Build metadata from row
                        metadata = {}
                        for key, value in row.items():
                            if key not in ("text", "vector", "__nn_distance"):
                                if key == "content_metadata" and isinstance(value, str):
                                    try:
                                        metadata[key] = json.loads(value)
                                    except json.JSONDecodeError:
                                        metadata[key] = value
                                else:
                                    metadata[key] = value

                        docs.append(Document(page_content=text, metadata=metadata))
                else:
                    logger.warning(f"results_df has no to_dict method: {type(results_df)}")

            latency = time.time() - start_time
            logger.info(f"KDB.AI retrieval: {len(docs)} docs in {latency:.4f}s")

            if KDBAI_DEBUG and docs:
                first_doc = docs[0]
                logger.debug(f"First doc page_content (first 300 chars): {first_doc.page_content[:300] if first_doc.page_content else 'EMPTY'}")
                logger.debug(f"First doc metadata: {first_doc.metadata}")

            return self._add_collection_name_to_docs(docs, collection_name)

        finally:
            otel_context.detach(token)

    @staticmethod
    def _add_collection_name_to_docs(
        docs: List[Document],
        collection_name: str,
    ) -> List[Document]:
        """Add collection name to document metadata for citation tracking."""
        for doc in docs:
            doc.metadata["collection_name"] = collection_name
        return docs
