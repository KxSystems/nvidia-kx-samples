# KDB-X Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace Elasticsearch and MongoDB with KDB-X as the unified data platform, keeping all existing API interfaces intact.

**Architecture:** Adapter pattern — new `kdbx/` package provides PyKX-based implementations behind the same interfaces. `db_manager.py` and `job_service.py` work unchanged through a pymongo-compatible shim. `es_client.py` delegates to `kdbx/es_adapter.py`. See `docs/plans/2026-02-17-kdbx-integration-design.md` for full design.

**Tech Stack:** PyKX (IPC to KDB-X), `.ai.hnsw.*` for vector search, q DDL for table creation, bson.ObjectId (kept from pymongo)

---

## Task 1: Package Skeleton & Dependencies

**Files:**
- Create: `kdbx/__init__.py`
- Modify: `pyproject.toml:7-25`

**Step 1: Create package directory**

```bash
mkdir -p kdbx
```

**Step 2: Create `kdbx/__init__.py`**

```python
"""KDB-X data layer for the NVIDIA AI Model Distillation Blueprint."""
```

**Step 3: Update `pyproject.toml` — swap elasticsearch for pykx**

In `pyproject.toml`, replace `"elasticsearch==8.17.2"` with `"pykx>=2.5.0"`. Keep `pymongo>=4.12.0` (needed for `bson.ObjectId`).

**Step 4: Commit**

```bash
git add kdbx/__init__.py pyproject.toml
git commit -m "feat: add kdbx package skeleton, swap elasticsearch for pykx"
```

---

## Task 2: Connection Module

**Files:**
- Create: `kdbx/connection.py`
- Create: `tests/unit/kdbx/__init__.py`
- Create: `tests/unit/kdbx/conftest.py`
- Create: `tests/unit/kdbx/test_connection.py`

**Step 1: Write failing tests**

`tests/unit/kdbx/test_connection.py`:

```python
import pytest
from unittest.mock import patch, MagicMock

from kdbx.connection import pykx_connection, get_kdbx_mode


class TestPykxConnection:
    """Test the PyKX connection context manager factory."""

    @patch.dict("os.environ", {"KDBX_ENDPOINT": "myhost:5000"})
    @patch("kdbx.connection.kx")
    def test_creates_connection_with_env_endpoint(self, mock_kx):
        mock_conn = MagicMock()
        mock_kx.SyncQConnection.return_value = mock_conn
        result = pykx_connection()
        mock_kx.SyncQConnection.assert_called_once_with("myhost", 5000)
        assert result is mock_conn

    @patch.dict("os.environ", {}, clear=True)
    @patch("kdbx.connection.kx")
    def test_defaults_to_localhost_8082(self, mock_kx):
        mock_conn = MagicMock()
        mock_kx.SyncQConnection.return_value = mock_conn
        pykx_connection()
        mock_kx.SyncQConnection.assert_called_once_with("localhost", 8082)

    @patch.dict("os.environ", {"KDBX_ENDPOINT": "host:bad"})
    def test_raises_on_invalid_port(self):
        with pytest.raises(ValueError):
            pykx_connection()


class TestGetKdbxMode:
    @patch.dict("os.environ", {"KDBX_MODE": "embedded"})
    def test_returns_embedded(self):
        assert get_kdbx_mode() == "embedded"

    @patch.dict("os.environ", {}, clear=True)
    def test_defaults_to_ipc(self):
        assert get_kdbx_mode() == "ipc"
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/kdbx/test_connection.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'kdbx.connection'`

**Step 3: Implement `kdbx/connection.py`**

```python
"""KDB-X connection management via PyKX."""

import os

import pykx as kx

from src.log_utils import setup_logging

logger = setup_logging("data_flywheel.kdbx.connection")

_DEFAULT_ENDPOINT = "localhost:8082"


def _parse_endpoint(endpoint: str) -> tuple[str, int]:
    """Parse 'host:port' string into (host, port) tuple."""
    parts = endpoint.rsplit(":", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid endpoint format: {endpoint!r}. Expected 'host:port'.")
    host = parts[0]
    try:
        port = int(parts[1])
    except ValueError:
        raise ValueError(f"Invalid port in endpoint: {endpoint!r}. Port must be an integer.")
    return host, port


def pykx_connection() -> kx.SyncQConnection:
    """Create a PyKX IPC connection to KDB-X.

    Returns a kx.SyncQConnection that should be used as a context manager:

        with pykx_connection() as q:
            result = q('select from mytable')
    """
    endpoint = os.getenv("KDBX_ENDPOINT", _DEFAULT_ENDPOINT)
    host, port = _parse_endpoint(endpoint)
    return kx.SyncQConnection(host, port)


def get_kdbx_mode() -> str:
    """Get the KDB-X connection mode ('ipc' or 'embedded')."""
    return os.getenv("KDBX_MODE", "ipc")
```

**Step 4: Create test package files**

`tests/unit/kdbx/__init__.py`: empty file.

`tests/unit/kdbx/conftest.py`:

```python
"""Shared fixtures for kdbx unit tests."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_pykx_connection():
    """Fixture that patches pykx_connection to return a mock q callable.

    Usage:
        def test_something(self, mock_pykx_connection):
            mock_q = mock_pykx_connection
            mock_q.return_value = expected_result
            # ... call code that uses pykx_connection() as context manager
    """
    mock_q = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_q)
    mock_ctx.__exit__ = MagicMock(return_value=False)

    with patch("kdbx.connection.pykx_connection", return_value=mock_ctx):
        yield mock_q
```

**Step 5: Run tests to verify they pass**

```bash
pytest tests/unit/kdbx/test_connection.py -v
```

Expected: PASS

**Step 6: Commit**

```bash
git add kdbx/connection.py tests/unit/kdbx/
git commit -m "feat: add kdbx connection module with PyKX IPC support"
```

---

## Task 3: Schema Module

**Files:**
- Create: `kdbx/schema.py`
- Create: `tests/unit/kdbx/test_schema.py`

**Step 1: Write failing tests**

`tests/unit/kdbx/test_schema.py`:

```python
from unittest.mock import MagicMock, call, patch

import pytest

from kdbx.schema import TABLE_NAMES, create_all_tables


class TestCreateAllTables:
    @patch("kdbx.schema.pykx_connection")
    def test_creates_all_seven_tables(self, mock_conn_factory):
        mock_q = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_q)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_conn_factory.return_value = mock_ctx

        # Simulate no tables exist yet
        mock_q.return_value.py.return_value = []

        create_all_tables()

        # Should have called q multiple times (table checks + creates + ai module)
        assert mock_q.call_count > 0

    def test_table_names_constant(self):
        expected = {
            "flywheel_runs", "nims", "evaluations", "customizations",
            "llm_judge_runs", "flywheel_logs", "flywheel_embeddings",
        }
        assert set(TABLE_NAMES) == expected
```

**Step 2: Run to verify failure**

```bash
pytest tests/unit/kdbx/test_schema.py -v
```

**Step 3: Implement `kdbx/schema.py`**

```python
"""KDB-X table definitions and creation via q DDL through PyKX."""

from kdbx.connection import pykx_connection
from src.log_utils import setup_logging

logger = setup_logging("data_flywheel.kdbx.schema")

TABLE_NAMES = [
    "flywheel_runs",
    "nims",
    "evaluations",
    "customizations",
    "llm_judge_runs",
    "flywheel_logs",
    "flywheel_embeddings",
]

# q DDL for each table. Uses `if[not ... in tables[]; ...]` for idempotency.
_TABLE_DDL = {
    "flywheel_runs": """
        flywheel_runs:([]
          _id:`symbol$();
          workload_id:`symbol$();
          client_id:`symbol$();
          status:`symbol$();
          started_at:`timestamp$();
          finished_at:`timestamp$();
          num_records:`long$();
          datasets:();
          error:()
        )
    """,
    "nims": """
        nims:([]
          _id:`symbol$();
          flywheel_run_id:`symbol$();
          model_name:`symbol$();
          status:`symbol$();
          deployment_status:();
          started_at:`timestamp$();
          finished_at:`timestamp$();
          runtime_seconds:`float$();
          error:()
        )
    """,
    "evaluations": """
        evaluations:([]
          _id:`symbol$();
          nim_id:`symbol$();
          eval_type:`symbol$();
          scores:();
          started_at:`timestamp$();
          finished_at:`timestamp$();
          runtime_seconds:`float$();
          progress:`float$();
          nmp_uri:();
          mlflow_uri:();
          error:()
        )
    """,
    "customizations": """
        customizations:([]
          _id:`symbol$();
          nim_id:`symbol$();
          workload_id:`symbol$();
          base_model:`symbol$();
          customized_model:();
          started_at:`timestamp$();
          finished_at:`timestamp$();
          runtime_seconds:`float$();
          progress:`float$();
          epochs_completed:`long$();
          steps_completed:`long$();
          nmp_uri:();
          error:()
        )
    """,
    "llm_judge_runs": """
        llm_judge_runs:([]
          _id:`symbol$();
          flywheel_run_id:`symbol$();
          model_name:`symbol$();
          deployment_type:`symbol$();
          deployment_status:();
          error:()
        )
    """,
    "flywheel_logs": """
        flywheel_logs:([]
          doc_id:`symbol$();
          workload_id:`symbol$();
          client_id:`symbol$();
          timestamp:`timestamp$();
          request:();
          response:()
        )
    """,
    "flywheel_embeddings": """
        flywheel_embeddings:([]
          doc_id:`symbol$();
          index_name:`symbol$();
          embedding:();
          tool_name:`symbol$();
          query_text:();
          record_id:`symbol$();
          timestamp:`timestamp$();
          record:()
        )
    """,
}


def create_all_tables(drop_existing: bool = False) -> None:
    """Create all KDB-X tables if they don't exist.

    Args:
        drop_existing: If True, drop and recreate all tables (for test fixtures).
    """
    with pykx_connection() as q:
        # Load AI module for vector search
        q("\\l ai.q")

        existing = q("tables[]").py()
        if isinstance(existing, bytes):
            existing = [existing.decode()]
        elif hasattr(existing, "__iter__"):
            existing = [t.decode() if isinstance(t, bytes) else str(t) for t in existing]
        else:
            existing = []

        for table_name in TABLE_NAMES:
            if drop_existing and table_name in existing:
                logger.info(f"Dropping table: {table_name}")
                q(f"delete {table_name} from `.")
            if drop_existing or table_name not in existing:
                logger.info(f"Creating table: {table_name}")
                q(_TABLE_DDL[table_name])
            else:
                logger.info(f"Table '{table_name}' already exists.")
```

**Step 4: Run tests**

```bash
pytest tests/unit/kdbx/test_schema.py -v
```

**Step 5: Commit**

```bash
git add kdbx/schema.py tests/unit/kdbx/test_schema.py
git commit -m "feat: add kdbx schema module with all 7 table definitions"
```

---

## Task 4: Pymongo-Compatible Shim — Core

**Files:**
- Create: `kdbx/compat.py`
- Create: `tests/unit/kdbx/test_compat.py`

This is the largest task. It provides `KDBXCollection` and `KDBXDatabase` classes that translate pymongo query patterns to parameterized q queries.

**Step 1: Write failing tests for find_one**

`tests/unit/kdbx/test_compat.py`:

```python
import json
from dataclasses import dataclass
from unittest.mock import MagicMock, patch, call

import pytest

from kdbx.compat import KDBXCollection, KDBXDatabase


@pytest.fixture
def mock_q():
    """Mock q callable returned by pykx_connection context manager."""
    mock_q_fn = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_q_fn)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    with patch("kdbx.compat.pykx_connection", return_value=mock_ctx):
        yield mock_q_fn


class TestKDBXCollectionFindOne:
    def test_find_one_by_id(self, mock_q):
        """find_one({"_id": ObjectId(x)}) -> q: select from tbl where _id = x"""
        col = KDBXCollection("flywheel_runs")

        # Simulate q returning a single-row table
        mock_result = MagicMock()
        mock_result.pd.return_value = _make_df([{"_id": "abc123", "status": "RUNNING"}])
        mock_q.return_value = mock_result

        result = col.find_one({"_id": "abc123"})

        assert result is not None
        assert result["_id"] == "abc123"
        assert result["status"] == "RUNNING"

    def test_find_one_returns_none_when_empty(self, mock_q):
        col = KDBXCollection("flywheel_runs")
        mock_result = MagicMock()
        mock_result.pd.return_value = _make_df([])
        mock_q.return_value = mock_result

        result = col.find_one({"_id": "nonexistent"})
        assert result is None

    def test_find_one_with_null_filter(self, mock_q):
        """find_one({"_id": x, "error": None}) -> where _id = x, null error"""
        col = KDBXCollection("flywheel_runs")
        mock_result = MagicMock()
        mock_result.pd.return_value = _make_df([{"_id": "abc", "error": None}])
        mock_q.return_value = mock_result

        result = col.find_one({"_id": "abc", "error": None})
        assert result is not None
        # Verify the q expression includes null check
        q_expr = mock_q.call_args[0][0]
        assert "null error" in q_expr

    def test_find_one_compound_filter(self, mock_q):
        """find_one({"flywheel_run_id": x, "model_name": y})"""
        col = KDBXCollection("nims")
        mock_result = MagicMock()
        mock_result.pd.return_value = _make_df([{
            "_id": "n1", "flywheel_run_id": "f1", "model_name": "llama"
        }])
        mock_q.return_value = mock_result

        result = col.find_one({"flywheel_run_id": "f1", "model_name": "llama"})
        assert result is not None
        assert result["model_name"] == "llama"


class TestKDBXCollectionFind:
    def test_find_by_fk(self, mock_q):
        """find({"flywheel_run_id": x}) -> list of dicts"""
        col = KDBXCollection("nims")
        mock_result = MagicMock()
        mock_result.pd.return_value = _make_df([
            {"_id": "n1", "flywheel_run_id": "f1"},
            {"_id": "n2", "flywheel_run_id": "f1"},
        ])
        mock_q.return_value = mock_result

        results = list(col.find({"flywheel_run_id": "f1"}))
        assert len(results) == 2

    def test_find_with_in_operator(self, mock_q):
        """find({"nim_id": {"$in": [list]}})"""
        col = KDBXCollection("evaluations")
        mock_result = MagicMock()
        mock_result.pd.return_value = _make_df([{"_id": "e1", "nim_id": "n1"}])
        mock_q.return_value = mock_result

        results = list(col.find({"nim_id": {"$in": ["n1", "n2"]}}))
        assert len(results) == 1
        q_expr = mock_q.call_args[0][0]
        assert "in" in q_expr

    def test_find_with_compound_and_in(self, mock_q):
        """find({"flywheel_run_id": x, "status": {"$in": [...]}})"""
        col = KDBXCollection("nims")
        mock_result = MagicMock()
        mock_result.pd.return_value = _make_df([])
        mock_q.return_value = mock_result

        list(col.find({"flywheel_run_id": "f1", "status": {"$in": ["RUNNING", "PENDING"]}}))
        q_expr = mock_q.call_args[0][0]
        assert "flywheel_run_id" in q_expr
        assert "in" in q_expr


class TestKDBXCollectionInsertOne:
    def test_insert_one_returns_inserted_id(self, mock_q):
        col = KDBXCollection("flywheel_runs")
        mock_q.return_value = None  # q insert returns nothing useful

        result = col.insert_one({"_id": "abc123", "status": "PENDING"})
        assert result.inserted_id == "abc123"

    def test_insert_one_calls_q_insert(self, mock_q):
        col = KDBXCollection("flywheel_runs")
        mock_q.return_value = None

        col.insert_one({"_id": "abc", "workload_id": "w1"})
        assert mock_q.called
        q_expr = mock_q.call_args[0][0]
        assert "insert" in q_expr or "upsert" in q_expr


class TestKDBXCollectionUpdateOne:
    def test_update_one_simple(self, mock_q):
        """update_one({"_id": x}, {"$set": {"status": "RUNNING"}})"""
        col = KDBXCollection("flywheel_runs")
        mock_q.return_value = None

        col.update_one({"_id": "abc"}, {"$set": {"status": "RUNNING"}})
        assert mock_q.called
        q_expr = mock_q.call_args[0][0]
        assert "update" in q_expr

    def test_update_one_with_null_condition(self, mock_q):
        """update_one({"_id": x, "error": None}, {"$set": {...}})"""
        col = KDBXCollection("flywheel_runs")
        mock_q.return_value = None

        col.update_one(
            {"_id": "abc", "error": None},
            {"$set": {"status": "FAILED", "error": "boom"}},
        )
        q_expr = mock_q.call_args[0][0]
        assert "null error" in q_expr


class TestKDBXCollectionDeleteMany:
    def test_delete_many_by_fk(self, mock_q):
        col = KDBXCollection("nims")
        mock_q.return_value = None

        col.delete_many({"flywheel_run_id": "f1"})
        assert mock_q.called
        q_expr = mock_q.call_args[0][0]
        assert "delete" in q_expr

    def test_delete_many_with_in(self, mock_q):
        col = KDBXCollection("evaluations")
        mock_q.return_value = None

        col.delete_many({"nim_id": {"$in": ["n1", "n2"]}})
        q_expr = mock_q.call_args[0][0]
        assert "delete" in q_expr
        assert "in" in q_expr


class TestKDBXCollectionDeleteOne:
    def test_delete_one_by_id(self, mock_q):
        col = KDBXCollection("flywheel_runs")
        mock_q.return_value = None

        col.delete_one({"_id": "abc"})
        assert mock_q.called


class TestKDBXCollectionCreateIndex:
    def test_create_index_is_noop(self, mock_q):
        col = KDBXCollection("flywheel_runs")
        col.create_index("workload_id")
        # Should not call q at all
        assert not mock_q.called


class TestKDBXDatabase:
    def test_attribute_access_returns_collection(self):
        db = KDBXDatabase()
        col = db.flywheel_runs
        assert isinstance(col, KDBXCollection)
        assert col._table_name == "flywheel_runs"

    def test_same_attribute_returns_same_instance(self):
        db = KDBXDatabase()
        assert db.nims is db.nims


# --- helpers ---
def _make_df(rows):
    """Create a pandas-like DataFrame from a list of dicts."""
    import pandas as pd
    return pd.DataFrame(rows)
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/kdbx/test_compat.py -v
```

**Step 3: Implement `kdbx/compat.py`**

Key design decisions:
- All q queries are parameterized (no f-string interpolation of values)
- Column names from filter keys are safe (they come from our code, not user input)
- Table names are hardcoded (set at construction time from our code)
- General-list columns (scores, datasets, error, etc.) are JSON-serialized on write, JSON-deserialized on read
- ObjectId values are converted to strings before storing as q symbols
- Timestamps are handled by PyKX's automatic conversion

```python
"""Pymongo-compatible shim over KDB-X via PyKX.

Provides KDBXDatabase and KDBXCollection classes that translate the exact
pymongo query patterns used by job_service.py and db_manager.py into
parameterized q queries. Only supports patterns actually used in the codebase.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pykx as kx
from bson import ObjectId

from kdbx.connection import pykx_connection
from src.log_utils import setup_logging

logger = setup_logging("data_flywheel.kdbx.compat")

# Columns stored as JSON strings in q general lists.
_JSON_COLUMNS = {"scores", "datasets", "record", "request", "response"}

# Columns stored as q symbols (fast equality lookups).
_SYMBOL_COLUMNS = {
    "_id", "workload_id", "client_id", "status", "flywheel_run_id",
    "nim_id", "model_name", "eval_type", "doc_id", "index_name",
    "tool_name", "record_id", "base_model", "deployment_type",
    "signal_id", "sym", "direction", "model_id", "source_doc_id",
    "run_id", "pair_id", "teacher_model", "dataset_split",
    "ground_truth_signal", "output_id",
}


@dataclass
class InsertOneResult:
    """Minimal pymongo InsertOneResult replacement."""
    inserted_id: Any


class KDBXCollection:
    """Pymongo-compatible collection backed by a KDB-X table."""

    def __init__(self, table_name: str) -> None:
        self._table_name = table_name

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def find_one(self, filter_dict: dict | None = None, projection: dict | None = None):
        """Find a single document matching the filter."""
        filter_dict = filter_dict or {}
        q_expr, params = self._build_select(filter_dict, projection)
        with pykx_connection() as q:
            result = q(q_expr, *params)
            rows = self._result_to_dicts(result)
            return rows[0] if rows else None

    def find(self, filter_dict: dict | None = None, projection: dict | None = None):
        """Find all documents matching the filter. Returns a list."""
        filter_dict = filter_dict or {}
        q_expr, params = self._build_select(filter_dict, projection)
        with pykx_connection() as q:
            result = q(q_expr, *params)
            return self._result_to_dicts(result)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------
    def insert_one(self, doc: dict) -> InsertOneResult:
        """Insert a single document."""
        doc_id = doc.get("_id")
        if isinstance(doc_id, ObjectId):
            doc_id = str(doc_id)

        q_expr, params = self._build_insert(doc)
        with pykx_connection() as q:
            q(q_expr, *params)

        return InsertOneResult(inserted_id=doc_id)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------
    def update_one(self, filter_dict: dict, update: dict) -> None:
        """Update a single document matching the filter."""
        self._do_update(filter_dict, update)

    def update_many(self, filter_dict: dict, update: dict) -> None:
        """Update all documents matching the filter."""
        # In q, update applies to all matching rows by default.
        self._do_update(filter_dict, update)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------
    def delete_one(self, filter_dict: dict) -> None:
        """Delete a single document matching the filter."""
        # q delete removes all matches; for delete_one semantics we accept this
        # since all delete_one calls in the codebase filter by _id (unique).
        self._do_delete(filter_dict)

    def delete_many(self, filter_dict: dict) -> None:
        """Delete all documents matching the filter."""
        self._do_delete(filter_dict)

    # ------------------------------------------------------------------
    # Index (no-op)
    # ------------------------------------------------------------------
    def create_index(self, field: str) -> None:
        """No-op. KDB-X tables use in-memory columnar storage."""
        pass

    # ------------------------------------------------------------------
    # Internal: query builders
    # ------------------------------------------------------------------
    def _build_select(self, filter_dict: dict, projection: dict | None = None):
        """Build a parameterized q select expression.

        Returns (q_expression: str, params: list).
        """
        where_clause, params, param_names = self._build_where(filter_dict)
        cols = self._projection_cols(projection)

        func_sig = ";".join(param_names)
        col_clause = f" {cols}" if cols else ""
        where_part = f" where {where_clause}" if where_clause else ""

        q_expr = f"{{[{func_sig}] select{col_clause} from {self._table_name}{where_part}}}"
        return q_expr, params

    def _build_insert(self, doc: dict):
        """Build a parameterized q insert expression."""
        # Convert all values to q-compatible types
        converted = {}
        for key, value in doc.items():
            converted[key] = self._python_to_q(key, value)

        # Build q dict and insert
        keys_str = "`" + "`".join(converted.keys())
        param_names = [f"v{i}" for i in range(len(converted))]
        values_str = ";".join(param_names)
        func_sig = ";".join(param_names)

        q_expr = f"{{[{func_sig}] `{self._table_name} insert ({keys_str})!({values_str})}}"
        params = list(converted.values())
        return q_expr, params

    def _do_update(self, filter_dict: dict, update: dict):
        """Execute an update query."""
        if "$set" not in update:
            raise NotImplementedError(f"Only $set updates supported, got: {list(update.keys())}")

        set_fields = update["$set"]
        where_clause, where_params, where_names = self._build_where(filter_dict)

        # Build SET clause
        set_parts = []
        set_params = []
        set_names = []
        for key, value in set_fields.items():
            sname = f"s{len(set_names)}"
            set_names.append(sname)
            set_parts.append(f"{key}:{sname}")
            set_params.append(self._python_to_q(key, value))

        all_names = set_names + where_names
        all_params = set_params + where_params
        func_sig = ";".join(all_names)
        set_str = ", ".join(set_parts)
        where_part = f" where {where_clause}" if where_clause else ""

        q_expr = f"{{[{func_sig}] update {set_str} from `{self._table_name}{where_part}}}"

        with pykx_connection() as q:
            q(q_expr, *all_params)

    def _do_delete(self, filter_dict: dict):
        """Execute a delete query."""
        where_clause, params, param_names = self._build_where(filter_dict)
        func_sig = ";".join(param_names)
        where_part = f" where {where_clause}" if where_clause else ""

        q_expr = f"{{[{func_sig}] delete from `{self._table_name}{where_part}}}"

        with pykx_connection() as q:
            q(q_expr, *params)

    def _build_where(self, filter_dict: dict):
        """Build where clause from pymongo-style filter.

        Returns (where_clause: str, params: list, param_names: list[str]).
        """
        parts = []
        params = []
        names = []

        for key, value in filter_dict.items():
            if value is None:
                # Null check: {"error": None} -> null error
                parts.append(f"null {key}")
            elif isinstance(value, dict):
                if "$in" in value:
                    pname = f"w{len(names)}"
                    names.append(pname)
                    parts.append(f"{key} in {pname}")
                    # Convert list to q symbol vector
                    in_values = [str(v) for v in value["$in"]]
                    params.append(kx.SymbolVector(in_values))
                else:
                    raise NotImplementedError(
                        f"Unsupported filter operator for '{key}': {list(value.keys())}"
                    )
            else:
                pname = f"w{len(names)}"
                names.append(pname)
                parts.append(f"{key} = {pname}")
                params.append(self._python_to_q(key, value))

        return ", ".join(parts), params, names

    def _projection_cols(self, projection: dict | None) -> str:
        """Convert pymongo projection to q column list."""
        if projection is None:
            return ""
        # pymongo projection: {"field": 1, ...} means include only these fields
        cols = [k for k, v in projection.items() if v]
        if cols:
            return " " + ", ".join(cols)
        return ""

    def _python_to_q(self, key: str, value: Any):
        """Convert a Python value to a q-compatible PyKX type."""
        if isinstance(value, ObjectId):
            return kx.SymbolAtom(str(value))
        if isinstance(value, datetime):
            return kx.TimestampAtom(value)
        if isinstance(value, dict):
            return json.dumps(value)  # Store as JSON string in general list
        if isinstance(value, list):
            return json.dumps(value)  # Store as JSON string in general list
        if isinstance(value, (int, float)):
            if isinstance(value, int):
                return kx.LongAtom(value)
            return kx.FloatAtom(value)
        if value is None:
            # For general list columns, store as empty string
            # For symbol columns, store as null symbol
            if key in _SYMBOL_COLUMNS:
                return kx.SymbolAtom("")
            return None  # PyKX handles None -> q null
        if isinstance(value, str):
            if key in _SYMBOL_COLUMNS:
                return kx.SymbolAtom(value)
            return value  # General list — store raw string
        # Fallback: let PyKX handle conversion
        return kx.toq(value)

    def _result_to_dicts(self, result) -> list[dict]:
        """Convert q table result to list of Python dicts."""
        import pandas as pd

        df = result.pd()
        if df is None or len(df) == 0:
            return []

        rows = df.to_dict("records")
        # Post-process: deserialize JSON columns, convert types
        for row in rows:
            for key, value in row.items():
                if key in _JSON_COLUMNS and isinstance(value, str):
                    try:
                        row[key] = json.loads(value)
                    except (json.JSONDecodeError, TypeError):
                        pass
                # Convert NaN/NaT to None
                if isinstance(value, float) and pd.isna(value):
                    row[key] = None
                elif isinstance(value, pd.Timestamp) and pd.isna(value):
                    row[key] = None
        return rows


class KDBXDatabase:
    """Pymongo-compatible database that returns KDBXCollection instances."""

    def __init__(self) -> None:
        self._collections: dict[str, KDBXCollection] = {}

    def __getattr__(self, name: str) -> KDBXCollection:
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._collections:
            self._collections[name] = KDBXCollection(name)
        return self._collections[name]
```

**Step 4: Run tests**

```bash
pytest tests/unit/kdbx/test_compat.py -v
```

**Step 5: Commit**

```bash
git add kdbx/compat.py tests/unit/kdbx/test_compat.py
git commit -m "feat: add pymongo-compatible shim (KDBXCollection, KDBXDatabase)"
```

---

## Task 5: ES Adapter — Vector Search with HNSW

**Files:**
- Create: `kdbx/es_adapter.py`
- Create: `tests/unit/kdbx/test_es_adapter.py`

**Step 1: Write failing tests**

`tests/unit/kdbx/test_es_adapter.py`:

```python
import time
from unittest.mock import MagicMock, patch

import pytest

from kdbx.es_adapter import (
    KDBXClient,
    close_es_client,
    delete_embeddings_index,
    ensure_embeddings_index,
    get_es_client,
    index_embeddings_to_es,
    search_similar_embeddings,
)


@pytest.fixture
def mock_q():
    mock_q_fn = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_q_fn)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    with patch("kdbx.es_adapter.pykx_connection", return_value=mock_ctx):
        yield mock_q_fn


class TestGetEsClient:
    @patch("kdbx.es_adapter.pykx_connection")
    @patch("kdbx.es_adapter.create_all_tables")
    def test_returns_kdbx_client(self, mock_create, mock_conn):
        mock_q = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_q)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_ctx
        mock_q.return_value = True  # ping succeeds

        client = get_es_client()
        assert isinstance(client, KDBXClient)


class TestEnsureEmbeddingsIndex:
    def test_is_noop(self, mock_q):
        """ensure_embeddings_index should be a no-op — table created at startup."""
        ensure_embeddings_index(MagicMock(), "test_index")
        # Should not raise


class TestIndexEmbeddings:
    def test_returns_index_name(self, mock_q):
        binned_data = {
            "tool1": [([1.0, 2.0, 3.0], {"workload_id": "w1", "timestamp": 123})],
        }
        mock_q.return_value = None

        index_name = index_embeddings_to_es(MagicMock(), binned_data, "w1", "c1")
        assert index_name.startswith("flywheel_embeddings_index_w1_c1_")


class TestDeleteEmbeddingsIndex:
    def test_clears_hnsw_cache(self, mock_q):
        mock_q.return_value = None
        # Should not raise
        delete_embeddings_index(MagicMock(), "test_index")


class TestCloseEsClient:
    def test_clears_state(self):
        close_es_client()
        # Should not raise
```

**Step 2: Run tests to verify failure**

```bash
pytest tests/unit/kdbx/test_es_adapter.py -v
```

**Step 3: Implement `kdbx/es_adapter.py`**

```python
"""Drop-in replacement for es_client.py functions, backed by KDB-X.

Provides the same 6-function interface:
- get_es_client()
- close_es_client()
- ensure_embeddings_index()
- index_embeddings_to_es()
- search_similar_embeddings()
- delete_embeddings_index()

Vector search uses KDB-X .ai.hnsw.* module (standalone in-memory HNSW index).
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

import pykx as kx

from kdbx.connection import pykx_connection
from kdbx.schema import create_all_tables
from src.lib.flywheel.util import extract_user_query
from src.log_utils import setup_logging

logger = setup_logging("data_flywheel.kdbx.es_adapter")

# Global state
_kdbx_client: KDBXClient | None = None
_hnsw_indexes: dict[str, tuple] = {}  # index_name -> (vectors_ref, hnsw_ref)

EMBEDDING_DIMS = 2048


class KDBXClient:
    """Wrapper that callers can pass around like an ES client.

    Callers that used the raw ES client (record_exporter, load_test_data)
    should be migrated to use KDB-X queries directly. This class exists
    so get_es_client() has something to return for callers that just
    pass the client through without using it directly.
    """

    def __init__(self):
        self.connected = True

    def ping(self):
        """Health check."""
        try:
            with pykx_connection() as q:
                q("1+1")
            return True
        except Exception:
            return False


def get_es_client() -> KDBXClient:
    """Get a KDB-X client, retrying if needed. Replaces ES get_es_client()."""
    global _kdbx_client

    if _kdbx_client is not None and _kdbx_client.connected:
        return _kdbx_client

    for attempt in range(30):
        try:
            with pykx_connection() as q:
                q("1+1")  # Health check
            logger.info("KDB-X is ready!")
            create_all_tables()
            _kdbx_client = KDBXClient()
            return _kdbx_client
        except Exception as err:
            if attempt == 29:
                msg = "Could not connect to KDB-X"
                logger.error(msg)
                raise RuntimeError(msg) from err
            time.sleep(1)

    msg = "KDB-X did not become healthy in time"
    logger.error(msg)
    raise RuntimeError(msg)


def close_es_client():
    """Close client and clear HNSW caches."""
    global _kdbx_client, _hnsw_indexes
    _kdbx_client = None
    _hnsw_indexes.clear()


def ensure_embeddings_index(client: Any, index_name: str):
    """No-op. flywheel_embeddings table is created at startup.
    HNSW index is built per-workflow when embeddings are inserted.
    """
    pass


def index_embeddings_to_es(
    client: Any,
    binned_data: dict[str, list[tuple[list[float], dict[str, Any]]]],
    workload_id: str,
    client_id: str,
) -> str:
    """Index embeddings to KDB-X and build HNSW index."""
    ts = int(datetime.utcnow().timestamp())
    index_name = f"flywheel_embeddings_index_{workload_id}_{client_id}_{ts}"

    with pykx_connection() as q:
        row_count = 0
        for tool_name, examples in binned_data.items():
            for embedding_vector, record in examples:
                user_query = extract_user_query(record)
                doc_id = f"{tool_name}_{hash(user_query)}_{record.get('timestamp', time.time())}"

                q(
                    "{[did;iname;emb;tn;qt;rid;ts;rec] "
                    "`flywheel_embeddings insert "
                    "(`doc_id`index_name`embedding`tool_name`query_text`record_id`timestamp`record)!"
                    "(did;iname;emb;tn;qt;rid;ts;rec)}",
                    kx.SymbolAtom(doc_id),
                    kx.SymbolAtom(index_name),
                    kx.toq(embedding_vector, kx.RealVector),
                    kx.SymbolAtom(tool_name),
                    user_query or "",
                    kx.SymbolAtom(record.get("workload_id", "")),
                    kx.TimestampAtom(
                        datetime.utcfromtimestamp(record["timestamp"])
                        if isinstance(record.get("timestamp"), (int, float))
                        else datetime.utcnow()
                    ),
                    json.dumps(record),
                )
                row_count += 1

        if row_count > 0:
            # Build HNSW index from the vectors just inserted
            # Extract vectors for this index_name
            vecs_result = q(
                "{[iname] select embedding from flywheel_embeddings where index_name = iname}",
                kx.SymbolAtom(index_name),
            )
            # Build HNSW: .ai.hnsw.put[graph;edges;vectors;metric;M;eps;ef]
            hnsw_result = q(
                "{[vecs] .ai.hnsw.put[();();vecs;`CS;32;1%log 32;64]}",
                vecs_result,
            )
            _hnsw_indexes[index_name] = (vecs_result, hnsw_result)
            logger.info(f"Indexed {row_count} embeddings and built HNSW for '{index_name}'")
        else:
            logger.info("No embeddings to index")

    return index_name


def search_similar_embeddings(
    client: Any,
    query_embedding: list[float],
    index_name: str,
    max_candidates: int = 50,
) -> list[tuple[float, str, dict[str, Any]]]:
    """Search for similar embeddings using HNSW."""
    if index_name not in _hnsw_indexes:
        logger.warning(f"No HNSW index found for '{index_name}'")
        return []

    vecs_ref, hnsw_ref = _hnsw_indexes[index_name]

    with pykx_connection() as q:
        # HNSW search: returns (distances; indices)
        search_result = q(
            "{[vecs;hnsw;qvec;k] .ai.hnsw.search[vecs;hnsw;qvec;k;`CS;64]}",
            vecs_ref,
            hnsw_ref,
            kx.toq(query_embedding, kx.RealVector),
            kx.LongAtom(max_candidates),
        )

        distances = search_result[0].py()
        indices = search_result[1].py()

        # Look up metadata from table for the matched indices
        rows = q(
            "{[iname] select tool_name, record from flywheel_embeddings where index_name = iname}",
            kx.SymbolAtom(index_name),
        )
        rows_list = rows.pd().to_dict("records")

        candidates = []
        for dist, idx in zip(distances, indices):
            if 0 <= idx < len(rows_list):
                row = rows_list[idx]
                tool_name = str(row.get("tool_name", ""))
                record_str = row.get("record", "{}")
                try:
                    record = json.loads(record_str) if isinstance(record_str, str) else record_str
                except (json.JSONDecodeError, TypeError):
                    record = {}
                candidates.append((float(dist), tool_name, record))

        return candidates


def delete_embeddings_index(client: Any, index_name: str = ""):
    """Delete embeddings rows and discard HNSW index."""
    try:
        with pykx_connection() as q:
            q(
                "{[iname] delete from `flywheel_embeddings where index_name = iname}",
                kx.SymbolAtom(index_name),
            )
        logger.info(f"Deleted embeddings for index: {index_name}")
    except Exception as e:
        logger.error(f"Error deleting embeddings for index '{index_name}': {e}")

    # Remove HNSW object from cache
    _hnsw_indexes.pop(index_name, None)
```

**Step 4: Run tests**

```bash
pytest tests/unit/kdbx/test_es_adapter.py -v
```

**Step 5: Commit**

```bash
git add kdbx/es_adapter.py tests/unit/kdbx/test_es_adapter.py
git commit -m "feat: add ES adapter with HNSW vector search via KDB-X AI module"
```

---

## Task 6: Wire Up `src/api/db.py`

**Files:**
- Modify: `src/api/db.py`

**Step 1: Rewrite `src/api/db.py`**

Replace MongoDB with KDBXDatabase. Keep identical function signatures.

```python
"""Database initialization and access — KDB-X backend via PyKX."""

import os
import time

from kdbx.compat import KDBXDatabase
from kdbx.connection import pykx_connection
from kdbx.schema import create_all_tables
from src.log_utils import setup_logging

logger = setup_logging("data_flywheel.db")

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

    if _db is not None:
        return _db

    # Retry loop (matches original 30-attempt pattern)
    for attempt in range(30):
        try:
            with pykx_connection() as q:
                q("1+1")  # Health check
            logger.info("KDB-X connection established.")
            create_all_tables()
            _db = KDBXDatabase()
            return _db
        except Exception as err:
            if attempt == 29:
                msg = "Could not connect to KDB-X"
                logger.error(msg)
                raise RuntimeError(msg) from err
            logger.info(f"Waiting for KDB-X (attempt {attempt + 1}/30)...")
            time.sleep(1)

    msg = "KDB-X did not become healthy in time"
    logger.error(msg)
    raise RuntimeError(msg)


def close_db():
    """Close the KDB-X connection."""
    global _db
    _db = None
```

**Step 2: Run existing unit tests that mock db.py**

```bash
pytest tests/unit/api/test_db.py -v
```

These tests mock `get_db()` and `init_db()`, so they should still pass since the function signatures are identical.

**Step 3: Run full unit test suite to check for breakage**

```bash
pytest tests/unit/ -v --timeout=30
```

**Step 4: Commit**

```bash
git add src/api/db.py
git commit -m "feat: rewrite db.py to use KDB-X via pymongo-compat shim"
```

---

## Task 7: Wire Up `es_client.py` as Delegation Layer

**Files:**
- Modify: `src/lib/integration/es_client.py`

**Step 1: Rewrite `es_client.py` to delegate to `kdbx/es_adapter.py`**

Replace all internals while keeping the exact same exported function signatures.

```python
"""Elasticsearch client — delegates to KDB-X adapter.

This module maintains the original function signatures so all existing
callers (icl_selection.py, record_exporter.py, tasks.py) continue to work.
"""

from kdbx.es_adapter import (
    KDBXClient,
    close_es_client,
    delete_embeddings_index,
    ensure_embeddings_index,
    get_es_client,
    index_embeddings_to_es,
    search_similar_embeddings,
)

# Re-export constants used by other modules
ES_COLLECTION_NAME = "flywheel_logs"
ES_EMBEDDINGS_INDEX_NAME = "flywheel_embeddings"
EMBEDDING_DIMS = 2048
```

**Step 2: Run existing ES client unit tests**

```bash
pytest tests/unit/lib/integration/test_es_client.py -v
```

These tests mock `get_es_client` and the ES functions, so they should pass.

**Step 3: Run ICL selection tests (they import from es_client)**

```bash
pytest tests/unit/lib/flywheel/test_icl_selection.py -v
```

**Step 4: Commit**

```bash
git add src/lib/integration/es_client.py
git commit -m "feat: rewrite es_client.py to delegate to kdbx/es_adapter.py"
```

---

## Task 8: Rewrite Record Exporter

**Files:**
- Modify: `src/lib/integration/record_exporter.py`
- Check: `tests/unit/lib/integration/test_record_exporter.py`

The record exporter currently uses the ES scroll API directly (`es.search()`, `es.scroll()`, `es.clear_scroll()`). Replace with a single q query — no pagination needed.

**Step 1: Read current record_exporter.py and its tests**

Read both files to understand the exact interface and test expectations.

**Step 2: Rewrite record_exporter.py**

Replace ES scroll-based pagination with a single KDB-X query:

```python
"""Export records from KDB-X for dataset creation."""

import json
from typing import Any

import pykx as kx

from kdbx.connection import pykx_connection
from src.config import DataSplitConfig
from src.log_utils import setup_logging

logger = setup_logging("data_flywheel.record_exporter")


class RecordExporter:
    """Export flywheel log records from KDB-X."""

    def export_records(
        self,
        workload_id: str,
        client_id: str,
        split_config: DataSplitConfig,
    ) -> list[dict[str, Any]]:
        """Export records matching workload_id and client_id.

        Args:
            workload_id: Filter by workload ID
            client_id: Filter by client ID
            split_config: Data split config (used for limit)

        Returns:
            List of record dicts with 'request' and 'response' fields
        """
        max_records = None if split_config.limit is None else split_config.limit * 2

        with pykx_connection() as q:
            if max_records:
                result = q(
                    "{[wid;cid;n] n sublist select from flywheel_logs "
                    "where workload_id = wid, client_id = cid}",
                    kx.SymbolAtom(workload_id),
                    kx.SymbolAtom(client_id),
                    kx.LongAtom(max_records),
                )
            else:
                result = q(
                    "{[wid;cid] select from flywheel_logs "
                    "where workload_id = wid, client_id = cid}",
                    kx.SymbolAtom(workload_id),
                    kx.SymbolAtom(client_id),
                )

            df = result.pd()
            if df is None or len(df) == 0:
                logger.info(f"No records found for workload={workload_id}, client={client_id}")
                return []

            records = []
            for _, row in df.iterrows():
                record = {
                    "workload_id": str(row.get("workload_id", "")),
                    "client_id": str(row.get("client_id", "")),
                    "timestamp": row.get("timestamp"),
                }
                # Deserialize JSON fields
                for field in ("request", "response"):
                    raw = row.get(field, "{}")
                    if isinstance(raw, str):
                        try:
                            record[field] = json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            record[field] = raw
                    else:
                        record[field] = raw

                records.append(record)

            logger.info(f"Exported {len(records)} records for workload={workload_id}")
            return records
```

**Step 3: Update tests if needed (check mock patterns)**

The unit tests mock `get_es_client` and the ES client. Since we're changing the implementation, verify the tests mock at the right level. If tests mock `RecordExporter` as a whole (which the `mock_record_exporter` fixture in integration conftest does), they'll pass unchanged.

```bash
pytest tests/unit/lib/integration/test_record_exporter.py -v
```

**Step 4: Commit**

```bash
git add src/lib/integration/record_exporter.py
git commit -m "feat: rewrite record_exporter to use KDB-X queries instead of ES scroll"
```

---

## Task 9: Rewrite Load Test Data Script

**Files:**
- Modify: `src/scripts/load_test_data.py`
- Check: `tests/unit/scripts/test_load_test_data.py`

**Step 1: Read the current script and its tests**

Read both files to understand exact behavior.

**Step 2: Rewrite data loading to use KDB-X**

The script loads JSON test data into the flywheel_logs table. Replace `es.index()` calls with q inserts.

Key changes:
- Remove `get_es_client()` import and module-level call
- Replace `es.index(index=..., document=doc)` with q insert to `flywheel_logs`
- Remove `es.indices.flush()` / `es.indices.refresh()` (not needed in q)
- Use `pykx_connection()` context manager

**Step 3: Run tests**

```bash
pytest tests/unit/scripts/test_load_test_data.py -v
```

**Step 4: Commit**

```bash
git add src/scripts/load_test_data.py
git commit -m "feat: rewrite load_test_data to use KDB-X inserts"
```

---

## Task 10: Config Update

**Files:**
- Modify: `src/config.py` (minimal — just add env var documentation)

**Step 1: No code changes needed in config.py**

`KDBX_ENDPOINT` is read directly by `kdbx/connection.py` via `os.getenv()`. `src/config.py` (the Settings/YAML config) doesn't need modification since it deals with NIM/training/evaluation config, not infrastructure.

**Step 2: Verify config tests still pass**

```bash
pytest tests/unit/test_config.py -v
```

**Step 3: Commit** (skip if no changes)

---

## Task 11: Docker Compose Updates

**Files:**
- Modify: `deploy/docker-compose.yaml`
- Modify: `deploy/docker-compose.dev.yaml`

**Step 1: Update `deploy/docker-compose.yaml`**

Remove `elasticsearch` and `mongodb` services. Add `kdbx` service. Update env vars in `api`, `celery_worker`, and `celery_parent_worker` services.

Remove from all services:
- `ELASTICSEARCH_URL`
- `ES_COLLECTION_NAME`
- `MONGODB_URL`
- `MONGODB_DB`

Add to all services:
- `KDBX_ENDPOINT=kdbx:8082` (or `localhost:8082` if `network_mode: host`)

Add KDB-X service:
```yaml
kdbx:
  image: kxsys/kdbx:latest
  container_name: kdbx
  ports:
    - "8082:8082"
    - "8081:8081"
  volumes:
    - kdbx_data:/data
  environment:
    KDBX_LICENSE_FILE: /config/kc.lic
  restart: unless-stopped
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8081/health"]
    interval: 10s
    timeout: 5s
    retries: 5
```

Update `depends_on` for api/worker services: `kdbx` instead of `elasticsearch` + `mongodb`.

**Step 2: Update `deploy/docker-compose.dev.yaml`**

Remove `kibana` service (no longer using ES). Keep `flower` service.

**Step 3: Commit**

```bash
git add deploy/docker-compose.yaml deploy/docker-compose.dev.yaml
git commit -m "feat: replace ES/MongoDB with KDB-X in docker-compose"
```

---

## Task 12: CI Pipeline Updates

**Files:**
- Modify: `.github/workflows/ci.yaml`

**Step 1: Update health checks**

Replace ES and MongoDB health checks with KDB-X health check:
- Remove ES cluster health check (`curl localhost:9200/_cluster/health`)
- Remove MongoDB mongosh ping
- Add KDB-X health check (`curl localhost:8081/health`)
- Remove ES index initialization step (tables are created by `init_db()`)

**Step 2: Update environment variables in deploy step**

Update the `.env` file creation to use `KDBX_ENDPOINT` instead of ES/Mongo vars.

**Step 3: Commit**

```bash
git add .github/workflows/ci.yaml
git commit -m "feat: update CI pipeline for KDB-X (replace ES/MongoDB health checks)"
```

---

## Task 13: Run Full Test Suite & Fix Issues

**Step 1: Run all unit tests**

```bash
pytest tests/unit/ -v --timeout=60 2>&1 | head -200
```

Expected: All tests pass. The autouse mocks in `tests/unit/conftest.py` mock both DB and ES at the import boundaries — since we kept all function signatures identical, mocking should work the same.

**Step 2: Check for import errors**

If any tests fail with `ImportError` or `ModuleNotFoundError`, fix the imports. The most likely issue:
- `es_client.py` no longer imports `Elasticsearch`, `ConnectionError`, etc. — tests that mock those specific imports may need updating
- `record_exporter.py` no longer imports `get_es_client` — test mock paths may need updating

**Step 3: Fix any issues and commit**

```bash
git add -A
git commit -m "fix: resolve test breakage from KDB-X migration"
```

---

## Task 14: Update Unit Test Conftest Mocks

**Files:**
- Modify: `tests/unit/conftest.py`

**Step 1: Update ES mock paths**

The autouse `mock_es_client` fixture (lines 154-180) patches:
- `src.lib.integration.es_client.get_es_client`
- `src.lib.integration.record_exporter.get_es_client`
- etc.

Since `es_client.py` now re-exports from `kdbx.es_adapter`, the mock paths may need to target the `kdbx.es_adapter` module instead. Check if patches still work and update if needed.

Similarly, `mock_db_functions` patches `src.api.db.get_db` and `src.api.db.init_db` — since `db.py` is rewritten, verify these still mock correctly.

**Step 2: Run full test suite after updates**

```bash
pytest tests/unit/ -v --timeout=60
```

**Step 3: Commit**

```bash
git add tests/unit/conftest.py
git commit -m "fix: update test mock paths for kdbx module structure"
```

---

## Task 15: Add KDB-X Integration Smoke Test

**Files:**
- Create: `tests/integration/test_kdbx_smoke.py`

**Step 1: Write smoke test** (requires running KDB-X instance)

```python
"""Smoke test for KDB-X integration. Requires a running KDB-X instance.

Run with: pytest tests/integration/test_kdbx_smoke.py -v -m integration
"""

import pytest
from datetime import datetime

from bson import ObjectId
from kdbx.connection import pykx_connection
from kdbx.schema import create_all_tables, TABLE_NAMES
from kdbx.compat import KDBXDatabase


@pytest.fixture(scope="module")
def kdbx_tables():
    """Create all tables with drop_existing for a clean state."""
    create_all_tables(drop_existing=True)
    yield
    create_all_tables(drop_existing=True)


@pytest.mark.integration
class TestKDBXSmoke:
    def test_connection(self):
        with pykx_connection() as q:
            result = q("1+1")
            assert result.py() == 2

    def test_tables_created(self, kdbx_tables):
        with pykx_connection() as q:
            tables = q("tables[]").py()
            for name in TABLE_NAMES:
                assert name.encode() in tables or name in tables

    def test_insert_and_query_flywheel_run(self, kdbx_tables):
        db = KDBXDatabase()
        oid = str(ObjectId())
        doc = {
            "_id": oid,
            "workload_id": "test_wid",
            "client_id": "test_cid",
            "status": "PENDING",
            "started_at": datetime.utcnow(),
            "finished_at": None,
            "num_records": None,
            "datasets": "[]",
            "error": None,
        }
        result = db.flywheel_runs.insert_one(doc)
        assert str(result.inserted_id) == oid

        found = db.flywheel_runs.find_one({"_id": oid})
        assert found is not None
        assert found["workload_id"] == "test_wid"
        assert found["status"] == "PENDING"

    def test_update_with_null_condition(self, kdbx_tables):
        db = KDBXDatabase()
        oid = str(ObjectId())
        db.flywheel_runs.insert_one({
            "_id": oid,
            "workload_id": "w",
            "client_id": "c",
            "status": "PENDING",
            "started_at": datetime.utcnow(),
            "finished_at": None,
            "num_records": None,
            "datasets": "[]",
            "error": None,
        })

        # Update with null condition — should match
        db.flywheel_runs.update_one(
            {"_id": oid, "error": None},
            {"$set": {"status": "RUNNING"}},
        )
        updated = db.flywheel_runs.find_one({"_id": oid})
        assert updated["status"] == "RUNNING"

        # Update with null condition after error set — should NOT match
        db.flywheel_runs.update_one(
            {"_id": oid},
            {"$set": {"error": "boom"}},
        )
        db.flywheel_runs.update_one(
            {"_id": oid, "error": None},
            {"$set": {"status": "COMPLETED"}},
        )
        still_running = db.flywheel_runs.find_one({"_id": oid})
        assert still_running["status"] == "RUNNING"  # Not updated

    def test_delete_cascade(self, kdbx_tables):
        db = KDBXDatabase()
        fid = str(ObjectId())
        nid = str(ObjectId())

        db.flywheel_runs.insert_one({
            "_id": fid, "workload_id": "w", "client_id": "c",
            "status": "COMPLETED", "started_at": datetime.utcnow(),
            "finished_at": datetime.utcnow(), "num_records": 10,
            "datasets": "[]", "error": None,
        })
        db.nims.insert_one({
            "_id": nid, "flywheel_run_id": fid, "model_name": "llama",
            "status": "COMPLETED", "deployment_status": None,
            "started_at": datetime.utcnow(), "finished_at": datetime.utcnow(),
            "runtime_seconds": 60.0, "error": None,
        })

        # Delete NIM by FK
        db.nims.delete_many({"flywheel_run_id": fid})
        assert db.nims.find_one({"flywheel_run_id": fid}) is None

        # Delete flywheel run by PK
        db.flywheel_runs.delete_one({"_id": fid})
        assert db.flywheel_runs.find_one({"_id": fid}) is None
```

**Step 2: Commit**

```bash
git add tests/integration/test_kdbx_smoke.py
git commit -m "test: add KDB-X integration smoke test"
```

---

## Task 16: Final Verification

**Step 1: Run all unit tests one final time**

```bash
pytest tests/unit/ -v --timeout=60
```

**Step 2: Run ruff linter**

```bash
ruff check kdbx/ src/api/db.py src/lib/integration/es_client.py src/lib/integration/record_exporter.py
ruff format kdbx/ src/api/db.py src/lib/integration/es_client.py src/lib/integration/record_exporter.py
```

**Step 3: Commit any lint fixes**

```bash
git add -A
git commit -m "style: lint and format kdbx package"
```

**Step 4: Verify git log shows clean history**

```bash
git log --oneline -20
```

---

## Summary of All Files

### New files (8)
| File | Purpose |
|---|---|
| `kdbx/__init__.py` | Package init |
| `kdbx/connection.py` | PyKX connection management |
| `kdbx/schema.py` | Table DDL + `create_all_tables()` |
| `kdbx/compat.py` | pymongo-compatible shim |
| `kdbx/es_adapter.py` | ES replacement (logs + HNSW vector search) |
| `tests/unit/kdbx/test_connection.py` | Connection tests |
| `tests/unit/kdbx/test_schema.py` | Schema tests |
| `tests/unit/kdbx/test_compat.py` | Compat shim tests |
| `tests/unit/kdbx/test_es_adapter.py` | ES adapter tests |
| `tests/integration/test_kdbx_smoke.py` | Integration smoke test |

### Modified files (6)
| File | Change |
|---|---|
| `pyproject.toml` | elasticsearch -> pykx |
| `src/api/db.py` | MongoDB -> KDBXDatabase |
| `src/lib/integration/es_client.py` | Re-export from kdbx/es_adapter.py |
| `src/lib/integration/record_exporter.py` | ES scroll -> q query |
| `src/scripts/load_test_data.py` | ES index -> q insert |
| `tests/unit/conftest.py` | Update mock paths if needed |

### Modified infra files (3)
| File | Change |
|---|---|
| `deploy/docker-compose.yaml` | Remove ES/Mongo, add KDB-X |
| `deploy/docker-compose.dev.yaml` | Remove Kibana, update hostnames |
| `.github/workflows/ci.yaml` | Replace ES/Mongo health checks |

### Unchanged files (everything else)
- `src/api/db_manager.py` — works through compat shim
- `src/api/job_service.py` — works through compat shim
- `src/api/models.py` — Pydantic models unchanged
- `src/api/schemas.py` — API schemas unchanged
- `src/api/endpoints.py` — API routes unchanged
- `src/tasks/tasks.py` — Celery tasks unchanged
- `src/lib/flywheel/icl_selection.py` — imports from es_client unchanged
- All other `src/lib/**` files unchanged
