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
"""Tests for kdbx.compat module -- pymongo-compatible shim.

Covers every query pattern used in ``db_manager.py`` and ``job_service.py``:
  - find_one with equality, compound, null-condition, and projection filters
  - find with equality, $in, compound, and projection filters
  - insert_one returning InsertOneResult
  - update_one / update_many with $set
  - delete_one / delete_many with equality and $in
  - KDBXDatabase.__getattr__ returning cached KDBXCollection instances
  - create_index as a no-op
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fixture: mock q connection at the compat module level
# ---------------------------------------------------------------------------


class _FakeCharVector(tuple):
    """Tuple subclass so ``isinstance(val, kx.CharVector)`` works with mocks."""

    def __new__(cls, v):
        return super().__new__(cls, ("CharVector", v))


class _FakeList(tuple):
    """Tuple subclass so ``isinstance(val, kx.List)`` works with mocks."""

    def __new__(cls, v):
        return super().__new__(cls, ("List", v))


@pytest.fixture()
def mock_q():
    """Patch ``pykx_connection`` where compat.py uses it and ``kx`` atom ctors.

    Yields the mock q connection object so tests can set return values
    and inspect call args.
    """
    mock_conn = MagicMock(name="SyncQConnection")

    @contextmanager
    def _fake_ctx():
        yield mock_conn

    with (
        patch("kdbx.compat.pykx_connection", _fake_ctx),
        patch("kdbx.compat.kx") as mock_kx,
    ):
        # Wire up atom constructors to return tagged tuples so tests can
        # verify which converter was called.
        mock_kx.SymbolAtom.side_effect = lambda v: ("SymbolAtom", v)
        mock_kx.TimestampAtom.side_effect = lambda v: ("TimestampAtom", v)
        mock_kx.LongAtom.side_effect = lambda v: ("LongAtom", v)
        mock_kx.FloatAtom.side_effect = lambda v: ("FloatAtom", v)
        mock_kx.CharVector = _FakeCharVector
        mock_kx.List = _FakeList
        mock_kx.SymbolVector.side_effect = lambda v: ("SymbolVector", list(v))
        mock_kx.toq.side_effect = lambda v: ("toq", v)
        yield mock_conn


# ---------------------------------------------------------------------------
# InsertOneResult
# ---------------------------------------------------------------------------


class TestInsertOneResult:
    """Tests for the InsertOneResult dataclass."""

    def test_has_inserted_id_attribute(self):
        from kdbx.compat import InsertOneResult

        r = InsertOneResult(inserted_id="abc123")
        assert r.inserted_id == "abc123"

    def test_equality(self):
        from kdbx.compat import InsertOneResult

        assert InsertOneResult(inserted_id="x") == InsertOneResult(inserted_id="x")


# ---------------------------------------------------------------------------
# KDBXCollection -- find_one
# ---------------------------------------------------------------------------


class TestFindOne:
    """Tests for KDBXCollection.find_one."""

    def test_simple_id_lookup(self, mock_q):
        """find_one({"_id": ObjectId(x)}) -> select from tbl where _id = x"""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        mock_q.return_value = pd.DataFrame(
            [{"_id": str(oid), "status": "RUNNING"}]
        )

        col = KDBXCollection("flywheel_runs")
        result = col.find_one({"_id": oid})

        q_call = mock_q.call_args
        q_expr = q_call.args[0]
        assert "select" in q_expr
        assert "flywheel_runs" in q_expr
        assert "_id" in q_expr
        assert result is not None
        assert str(result["_id"]) == str(oid)

    def test_id_with_null_condition(self, mock_q):
        """find_one({"_id": x, "error": None}) -> where _id = w0, 0=count each error"""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        mock_q.return_value = pd.DataFrame(
            [{"_id": str(oid), "error": None}]
        )

        col = KDBXCollection("flywheel_runs")
        col.find_one({"_id": oid, "error": None})

        q_expr = mock_q.call_args.args[0]
        # error is a general-list column — uses count-based null check
        assert "0=count each error" in q_expr

    def test_id_with_two_null_conditions(self, mock_q):
        """find_one({"_id": x, "error": None, "finished_at": None})"""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        mock_q.return_value = pd.DataFrame(
            [{"_id": str(oid), "error": None, "finished_at": None}]
        )

        col = KDBXCollection("flywheel_runs")
        col.find_one({"_id": oid, "error": None, "finished_at": None})

        q_expr = mock_q.call_args.args[0]
        # error is general-list, finished_at is typed (timestamp)
        assert "0=count each error" in q_expr
        assert "null finished_at" in q_expr

    def test_fk_lookup(self, mock_q):
        """find_one({"flywheel_run_id": ObjectId(x)})"""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        mock_q.return_value = pd.DataFrame(
            [{"_id": "abc", "flywheel_run_id": str(oid)}]
        )

        col = KDBXCollection("nims")
        result = col.find_one({"flywheel_run_id": oid})

        q_expr = mock_q.call_args.args[0]
        assert "flywheel_run_id" in q_expr
        assert result is not None

    def test_compound_fk_and_string(self, mock_q):
        """find_one({"flywheel_run_id": ObjectId(x), "model_name": str})"""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        mock_q.return_value = pd.DataFrame(
            [{"_id": "abc", "flywheel_run_id": str(oid), "model_name": "gpt"}]
        )

        col = KDBXCollection("nims")
        result = col.find_one({"flywheel_run_id": oid, "model_name": "gpt"})

        q_expr = mock_q.call_args.args[0]
        assert "flywheel_run_id" in q_expr
        assert "model_name" in q_expr

    def test_compound_string_fields(self, mock_q):
        """find_one({"workload_id": str, "customized_model": str})"""
        from kdbx.compat import KDBXCollection

        mock_q.return_value = pd.DataFrame(
            [{"_id": "abc", "workload_id": "wl1", "customized_model": "m1"}]
        )

        col = KDBXCollection("customizations")
        col.find_one({"workload_id": "wl1", "customized_model": "m1"})

        q_expr = mock_q.call_args.args[0]
        assert "workload_id" in q_expr
        assert "customized_model" in q_expr

    def test_with_projection(self, mock_q):
        """find_one({"_id": x}, {"status": 1}) -> select status from tbl"""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        mock_q.return_value = pd.DataFrame([{"status": "RUNNING"}])

        col = KDBXCollection("flywheel_runs")
        result = col.find_one({"_id": oid}, {"status": 1})

        q_expr = mock_q.call_args.args[0]
        assert "status" in q_expr
        assert result is not None
        assert "status" in result

    def test_returns_none_for_empty_result(self, mock_q):
        """find_one returns None when no rows match."""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        mock_q.return_value = pd.DataFrame()

        col = KDBXCollection("flywheel_runs")
        result = col.find_one({"_id": oid})

        assert result is None

    def test_no_filter_selects_all(self, mock_q):
        """find_one() with no filter returns first row with select[1]."""
        from kdbx.compat import KDBXCollection

        mock_q.return_value = pd.DataFrame(
            [{"_id": "abc", "status": "RUNNING"}]
        )

        col = KDBXCollection("flywheel_runs")
        result = col.find_one()

        q_expr = mock_q.call_args.args[0]
        assert "select[1]" in q_expr
        assert "flywheel_runs" in q_expr
        assert "where" not in q_expr
        # No parameters should be passed (no function wrapper)
        assert len(mock_q.call_args.args) == 1
        assert result is not None
        assert result["_id"] == "abc"

    def test_empty_filter_selects_all(self, mock_q):
        """find_one({}) with empty dict uses select[1]."""
        from kdbx.compat import KDBXCollection

        mock_q.return_value = pd.DataFrame(
            [{"_id": "abc", "status": "PENDING"}]
        )

        col = KDBXCollection("flywheel_runs")
        result = col.find_one({})

        q_expr = mock_q.call_args.args[0]
        assert "select[1]" in q_expr
        assert "where" not in q_expr
        assert result is not None

    def test_json_columns_deserialized(self, mock_q):
        """find_one deserialises JSON columns (scores, datasets, etc.)."""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        scores_data = {"accuracy": 0.95}
        mock_q.return_value = pd.DataFrame(
            [{"_id": str(oid), "scores": json.dumps(scores_data)}]
        )

        col = KDBXCollection("evaluations")
        result = col.find_one({"_id": oid})

        assert result["scores"] == scores_data


# ---------------------------------------------------------------------------
# KDBXCollection -- find
# ---------------------------------------------------------------------------


class TestFind:
    """Tests for KDBXCollection.find."""

    def test_fk_lookup(self, mock_q):
        """find({"flywheel_run_id": ObjectId(x)}) -> FK lookup returning list."""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        mock_q.return_value = pd.DataFrame(
            [
                {"_id": "a", "flywheel_run_id": str(oid)},
                {"_id": "b", "flywheel_run_id": str(oid)},
            ]
        )

        col = KDBXCollection("nims")
        results = col.find({"flywheel_run_id": oid})

        assert isinstance(results, list)
        assert len(results) == 2

    def test_dollar_in_filter(self, mock_q):
        """find({"nim_id": {"$in": [list]}}) -> where nim_id in (...)."""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        ids = [ObjectId(), ObjectId()]
        mock_q.return_value = pd.DataFrame(
            [{"_id": "e1", "nim_id": str(ids[0])}, {"_id": "e2", "nim_id": str(ids[1])}]
        )

        col = KDBXCollection("evaluations")
        results = col.find({"nim_id": {"$in": ids}})

        q_expr = mock_q.call_args.args[0]
        assert "nim_id" in q_expr
        assert " in " in q_expr
        assert len(results) == 2

    def test_dollar_in_with_strings(self, mock_q):
        """find({"status": {"$in": ["RUNNING", "PENDING"]}})."""
        from kdbx.compat import KDBXCollection

        mock_q.return_value = pd.DataFrame(
            [{"_id": "a", "status": "RUNNING"}, {"_id": "b", "status": "PENDING"}]
        )

        col = KDBXCollection("flywheel_runs")
        results = col.find({"status": {"$in": ["RUNNING", "PENDING"]}})

        q_expr = mock_q.call_args.args[0]
        assert "status" in q_expr
        assert " in " in q_expr

    def test_compound_with_dollar_in(self, mock_q):
        """find({"flywheel_run_id": x, "status": {"$in": [...]}})."""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        mock_q.return_value = pd.DataFrame(
            [{"_id": "a", "flywheel_run_id": str(oid), "status": "RUNNING"}]
        )

        col = KDBXCollection("nims")
        results = col.find(
            {
                "flywheel_run_id": oid,
                "status": {"$in": ["RUNNING", "PENDING"]},
            }
        )

        q_expr = mock_q.call_args.args[0]
        assert "flywheel_run_id" in q_expr
        assert "status" in q_expr
        assert " in " in q_expr

    def test_with_projection(self, mock_q):
        """find({"flywheel_run_id": x}, {"_id": 1}) -> select _id from ..."""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        mock_q.return_value = pd.DataFrame(
            [{"_id": "a"}, {"_id": "b"}]
        )

        col = KDBXCollection("nims")
        results = col.find({"flywheel_run_id": oid}, {"_id": 1})

        q_expr = mock_q.call_args.args[0]
        assert "_id" in q_expr

    def test_returns_empty_list_for_no_matches(self, mock_q):
        """find returns [] when no rows match."""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        mock_q.return_value = pd.DataFrame()

        col = KDBXCollection("nims")
        results = col.find({"flywheel_run_id": oid})

        assert results == []

    def test_no_filter_selects_all(self, mock_q):
        """find() with no filter uses select[10000] by default."""
        from kdbx.compat import KDBXCollection

        mock_q.return_value = pd.DataFrame(
            [
                {"_id": "a", "status": "RUNNING"},
                {"_id": "b", "status": "PENDING"},
            ]
        )

        col = KDBXCollection("flywheel_runs")
        results = col.find()

        q_expr = mock_q.call_args.args[0]
        assert "select[10000]" in q_expr
        assert "flywheel_runs" in q_expr
        assert "where" not in q_expr
        assert len(mock_q.call_args.args) == 1
        assert len(results) == 2

    def test_empty_filter_selects_all(self, mock_q):
        """find({}) with empty dict uses select[10000]."""
        from kdbx.compat import KDBXCollection

        mock_q.return_value = pd.DataFrame(
            [{"_id": "a", "status": "RUNNING"}]
        )

        col = KDBXCollection("flywheel_runs")
        results = col.find({})

        q_expr = mock_q.call_args.args[0]
        assert "select[10000]" in q_expr
        assert "where" not in q_expr
        assert len(results) == 1

    def test_custom_limit(self, mock_q):
        """find(limit=5) uses select[5]."""
        from kdbx.compat import KDBXCollection

        mock_q.return_value = pd.DataFrame(
            [{"_id": "a", "status": "RUNNING"}]
        )

        col = KDBXCollection("flywheel_runs")
        col.find(limit=5)

        q_expr = mock_q.call_args.args[0]
        assert "select[5]" in q_expr

    def test_no_limit(self, mock_q):
        """find(limit=None) uses plain select (no row cap)."""
        from kdbx.compat import KDBXCollection

        mock_q.return_value = pd.DataFrame(
            [{"_id": "a", "status": "RUNNING"}]
        )

        col = KDBXCollection("flywheel_runs")
        col.find(limit=None)

        q_expr = mock_q.call_args.args[0]
        assert "select " in q_expr
        assert "select[" not in q_expr


# ---------------------------------------------------------------------------
# KDBXCollection -- insert_one
# ---------------------------------------------------------------------------


class TestInsertOne:
    """Tests for KDBXCollection.insert_one."""

    def test_returns_insert_one_result_with_id(self, mock_q):
        """insert_one returns InsertOneResult with the _id."""
        from bson import ObjectId

        from kdbx.compat import InsertOneResult, KDBXCollection

        oid = ObjectId()
        doc = {"_id": oid, "status": "PENDING", "model_name": "gpt"}

        col = KDBXCollection("nims")
        result = col.insert_one(doc)

        assert isinstance(result, InsertOneResult)
        assert result.inserted_id == oid

    def test_converts_objectid_to_symbol(self, mock_q):
        """ObjectId values are converted to kx.SymbolAtom(str(oid))."""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        fk_oid = ObjectId()
        doc = {"_id": oid, "flywheel_run_id": fk_oid, "status": "PENDING"}

        col = KDBXCollection("nims")
        col.insert_one(doc)

        q_args = mock_q.call_args
        # New format: q(q_expr, col_names, values_list)
        values = q_args.args[2]
        assert any(
            isinstance(p, tuple) and p[0] == "SymbolAtom" and p[1] == str(oid)
            for p in values
        )

    def test_converts_datetime_to_timestamp(self, mock_q):
        """datetime values are converted to kx.TimestampAtom."""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        now = datetime(2025, 1, 1, 12, 0, 0)
        doc = {"_id": oid, "started_at": now, "status": "RUNNING"}

        col = KDBXCollection("nims")
        col.insert_one(doc)

        q_args = mock_q.call_args
        values = q_args.args[2]
        assert any(
            isinstance(p, tuple) and p[0] == "TimestampAtom" and p[1] == now
            for p in values
        )

    def test_converts_dict_to_json_string(self, mock_q):
        """dict/list values in JSON columns are serialised to CharVector(json)."""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        scores = {"accuracy": 0.95}
        doc = {"_id": oid, "scores": scores}

        col = KDBXCollection("evaluations")
        col.insert_one(doc)

        q_args = mock_q.call_args
        values = q_args.args[2]
        assert any(
            isinstance(p, tuple) and p[0] == "CharVector" and p[1] == json.dumps(scores)
            for p in values
        )

    def test_converts_int_to_long(self, mock_q):
        """int values are converted to kx.LongAtom."""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        doc = {"_id": oid, "num_records": 42}

        col = KDBXCollection("flywheel_runs")
        col.insert_one(doc)

        q_args = mock_q.call_args
        values = q_args.args[2]
        assert any(
            isinstance(p, tuple) and p[0] == "LongAtom" and p[1] == 42
            for p in values
        )

    def test_converts_float_to_float_atom(self, mock_q):
        """float values are converted to kx.FloatAtom."""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        doc = {"_id": oid, "runtime_seconds": 3.14}

        col = KDBXCollection("evaluations")
        col.insert_one(doc)

        q_args = mock_q.call_args
        values = q_args.args[2]
        assert any(
            isinstance(p, tuple) and p[0] == "FloatAtom" and p[1] == 3.14
            for p in values
        )

    def test_uses_keyed_insert(self, mock_q):
        """insert_one passes column names and values as two args for keyed insert."""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        doc = {"_id": oid, "status": "PENDING", "num_records": 0}

        col = KDBXCollection("flywheel_runs")
        col.insert_one(doc)

        q_expr = mock_q.call_args.args[0]
        col_names = mock_q.call_args.args[1]
        # q expression uses {[n;v] ... n!v} pattern
        assert "n!v" in q_expr
        assert "insert" in q_expr
        # Column names passed as SymbolVector
        assert col_names[0] == "SymbolVector"
        assert "_id" in col_names[1]
        assert "status" in col_names[1]
        assert "num_records" in col_names[1]


# ---------------------------------------------------------------------------
# KDBXCollection -- update_one / update_many
# ---------------------------------------------------------------------------


class TestUpdateOne:
    """Tests for KDBXCollection.update_one."""

    def test_simple_id_update(self, mock_q):
        """update_one({"_id": x}, {"$set": {"status": "RUNNING"}})"""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()

        col = KDBXCollection("flywheel_runs")
        col.update_one({"_id": oid}, {"$set": {"status": "RUNNING"}})

        q_expr = mock_q.call_args.args[0]
        assert "update" in q_expr
        assert "flywheel_runs" in q_expr
        assert "status" in q_expr
        assert "_id" in q_expr

    def test_conditional_null_update(self, mock_q):
        """update_one({"_id": x, "error": None}, {"$set": {...}})"""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()

        col = KDBXCollection("flywheel_runs")
        col.update_one(
            {"_id": oid, "error": None},
            {"$set": {"status": "FAILED", "error": "boom"}},
        )

        q_expr = mock_q.call_args.args[0]
        assert "0=count each error" in q_expr

    def test_two_null_conditions(self, mock_q):
        """update_one({"_id": x, "error": None, "finished_at": None}, {...})"""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()

        col = KDBXCollection("nims")
        col.update_one(
            {"_id": oid, "error": None, "finished_at": None},
            {"$set": {"status": "CANCELLED"}},
        )

        q_expr = mock_q.call_args.args[0]
        # error is general-list, finished_at is typed (timestamp)
        assert "0=count each error" in q_expr
        assert "null finished_at" in q_expr

    def test_started_at_null_condition(self, mock_q):
        """update_one({"_id": x, "started_at": None}, {"$set": {...}})"""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()

        col = KDBXCollection("nims")
        col.update_one(
            {"_id": oid, "started_at": None},
            {"$set": {"started_at": datetime(2025, 1, 1)}},
        )

        q_expr = mock_q.call_args.args[0]
        assert "null started_at" in q_expr

    def test_fk_based_update(self, mock_q):
        """update_one({"flywheel_run_id": x}, {"$set": {...}})"""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()

        col = KDBXCollection("llm_judge_runs")
        col.update_one(
            {"flywheel_run_id": oid},
            {"$set": {"deployment_status": "COMPLETED"}},
        )

        q_expr = mock_q.call_args.args[0]
        assert "flywheel_run_id" in q_expr
        assert "deployment_status" in q_expr

    def test_update_with_datetime_value(self, mock_q):
        """update_one with datetime in $set -> kx.TimestampAtom."""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        now = datetime(2025, 6, 1, 12, 0, 0)

        col = KDBXCollection("flywheel_runs")
        col.update_one(
            {"_id": oid, "error": None},
            {"$set": {"finished_at": now, "status": "COMPLETED"}},
        )

        q_args = mock_q.call_args
        params = q_args.args[1:]
        assert any(
            isinstance(p, tuple) and p[0] == "TimestampAtom" and p[1] == now
            for p in params
        )


class TestUpdateMany:
    """Tests for KDBXCollection.update_many."""

    def test_fk_based_update_many(self, mock_q):
        """update_many({"flywheel_run_id": x, "error": None}, {"$set": {...}})"""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()

        col = KDBXCollection("nims")
        col.update_many(
            {"flywheel_run_id": oid, "error": None},
            {"$set": {"error": "cancelled", "status": "FAILED"}},
        )

        q_expr = mock_q.call_args.args[0]
        assert "update" in q_expr
        assert "nims" in q_expr
        assert "0=count each error" in q_expr


# ---------------------------------------------------------------------------
# KDBXCollection -- delete_one / delete_many
# ---------------------------------------------------------------------------


class TestDeleteOne:
    """Tests for KDBXCollection.delete_one."""

    def test_id_delete(self, mock_q):
        """delete_one({"_id": x}) -> delete from tbl where _id = x"""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()

        col = KDBXCollection("flywheel_runs")
        col.delete_one({"_id": oid})

        q_expr = mock_q.call_args.args[0]
        assert "delete" in q_expr
        assert "flywheel_runs" in q_expr
        assert "_id" in q_expr


class TestDeleteMany:
    """Tests for KDBXCollection.delete_many."""

    def test_fk_delete(self, mock_q):
        """delete_many({"flywheel_run_id": x})"""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()

        col = KDBXCollection("nims")
        col.delete_many({"flywheel_run_id": oid})

        q_expr = mock_q.call_args.args[0]
        assert "delete" in q_expr
        assert "nims" in q_expr
        assert "flywheel_run_id" in q_expr

    def test_dollar_in_delete(self, mock_q):
        """delete_many({"nim_id": {"$in": [list]}})"""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        ids = [ObjectId(), ObjectId()]

        col = KDBXCollection("evaluations")
        col.delete_many({"nim_id": {"$in": ids}})

        q_expr = mock_q.call_args.args[0]
        assert "delete" in q_expr
        assert "nim_id" in q_expr
        assert " in " in q_expr


# ---------------------------------------------------------------------------
# KDBXCollection -- create_index
# ---------------------------------------------------------------------------


class TestCreateIndex:
    """Tests for KDBXCollection.create_index."""

    def test_create_index_is_noop(self, mock_q):
        """create_index should be a no-op (does not call q)."""
        from kdbx.compat import KDBXCollection

        col = KDBXCollection("flywheel_runs")
        col.create_index("status")

        # No q calls should have been made
        mock_q.assert_not_called()


# ---------------------------------------------------------------------------
# KDBXDatabase
# ---------------------------------------------------------------------------


class TestKDBXDatabase:
    """Tests for KDBXDatabase."""

    def test_getattr_returns_collection(self):
        """db.flywheel_runs returns a KDBXCollection("flywheel_runs")."""
        from kdbx.compat import KDBXCollection, KDBXDatabase

        db = KDBXDatabase()
        col = db.flywheel_runs

        assert isinstance(col, KDBXCollection)
        assert col._table == "flywheel_runs"

    def test_getattr_caches_collections(self):
        """Same attribute access returns the same instance."""
        from kdbx.compat import KDBXDatabase

        db = KDBXDatabase()
        col1 = db.nims
        col2 = db.nims

        assert col1 is col2

    def test_different_attrs_return_different_collections(self):
        """Different attributes return different collection instances."""
        from kdbx.compat import KDBXDatabase

        db = KDBXDatabase()
        nims = db.nims
        evals = db.evaluations

        assert nims is not evals
        assert nims._table == "nims"
        assert evals._table == "evaluations"


# ---------------------------------------------------------------------------
# q injection prevention -- parameterised queries
# ---------------------------------------------------------------------------


class TestParameterisedQueries:
    """Verify that all values are passed as parameters, never interpolated."""

    def test_find_one_values_are_parameterised(self, mock_q):
        """Values must appear as positional args, not in the q string."""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        mock_q.return_value = pd.DataFrame()

        col = KDBXCollection("flywheel_runs")
        col.find_one({"_id": oid})

        q_call = mock_q.call_args
        q_expr = q_call.args[0]
        # The actual ObjectId string should NOT appear in the q expression
        assert str(oid) not in q_expr
        # It should appear in the parameters
        params = q_call.args[1:]
        assert len(params) > 0

    def test_update_values_are_parameterised(self, mock_q):
        """$set values must be passed as parameters."""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()

        col = KDBXCollection("flywheel_runs")
        col.update_one({"_id": oid}, {"$set": {"status": "RUNNING"}})

        q_call = mock_q.call_args
        q_expr = q_call.args[0]
        # Neither the OID nor the value "RUNNING" should be in the q string
        assert str(oid) not in q_expr
        assert "RUNNING" not in q_expr
        # But they should be in the parameters
        params = q_call.args[1:]
        assert len(params) > 0


# ---------------------------------------------------------------------------
# Type conversion on read -- NaN/NaT to None
# ---------------------------------------------------------------------------


class TestReadConversions:
    """Test that q result data is properly converted to Python dicts."""

    def test_nan_converted_to_none(self, mock_q):
        """NaN values in DataFrame should become None in the returned dict."""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        df = pd.DataFrame([{"_id": str(oid), "error": float("nan")}])
        mock_q.return_value = df

        col = KDBXCollection("flywheel_runs")
        result = col.find_one({"_id": oid})

        assert result["error"] is None

    def test_nat_converted_to_none(self, mock_q):
        """NaT values in DataFrame should become None in the returned dict."""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        df = pd.DataFrame([{"_id": str(oid), "finished_at": pd.NaT}])
        mock_q.return_value = df

        col = KDBXCollection("flywheel_runs")
        result = col.find_one({"_id": oid})

        assert result["finished_at"] is None


# ---------------------------------------------------------------------------
# Identifier validation
# ---------------------------------------------------------------------------


class TestIdentifierValidation:
    """Tests for _validate_table and _validate_column."""

    def test_validate_table_rejects_unknown(self):
        """Creating a KDBXCollection with unknown table raises ValueError."""
        from kdbx.compat import KDBXCollection

        with pytest.raises(ValueError, match="Unknown table"):
            KDBXCollection("hacked_table")

    def test_validate_table_accepts_known(self):
        """Creating a KDBXCollection with a known table succeeds."""
        from kdbx.compat import KDBXCollection

        col = KDBXCollection("flywheel_runs")
        assert col._table == "flywheel_runs"

    def test_validate_column_rejects_unknown(self, mock_q):
        """Filtering on an unknown column raises ValueError."""
        from kdbx.compat import KDBXCollection

        col = KDBXCollection("flywheel_runs")
        with pytest.raises(ValueError, match="Unknown column"):
            col.find_one({"hacked_col": "value"})

    def test_validate_column_rejects_bad_identifier(self, mock_q):
        """Filtering with a non-identifier column name raises ValueError."""
        from kdbx.compat import KDBXCollection

        col = KDBXCollection("flywheel_runs")
        with pytest.raises(ValueError, match="Invalid column name"):
            col.find_one({"a;drop table": "value"})

    def test_insert_skips_unknown_columns(self, mock_q):
        """insert_one silently skips columns not in the table schema."""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        col = KDBXCollection("flywheel_runs")
        oid = ObjectId()
        col.insert_one({"_id": oid, "hacked_col": "value"})

        # Only _id should be in column names, hacked_col skipped
        col_names = mock_q.call_args.args[1]
        assert "hacked_col" not in col_names[1]
        assert "_id" in col_names[1]

    def test_update_validates_set_columns(self, mock_q):
        """update_one $set with an unknown column raises ValueError."""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        col = KDBXCollection("flywheel_runs")
        with pytest.raises(ValueError, match="Unknown column"):
            col.update_one({"_id": oid}, {"$set": {"hacked_col": "value"}})

    def test_projection_validates_columns(self, mock_q):
        """find_one with unknown projection column raises ValueError."""
        from bson import ObjectId

        from kdbx.compat import KDBXCollection

        oid = ObjectId()
        mock_q.return_value = pd.DataFrame()

        col = KDBXCollection("flywheel_runs")
        with pytest.raises(ValueError, match="Unknown column"):
            col.find_one({"_id": oid}, {"hacked_col": 1})

    def test_database_getattr_rejects_unknown_table(self):
        """KDBXDatabase.__getattr__ raises AttributeError for unknown tables."""
        from kdbx.compat import KDBXDatabase

        db = KDBXDatabase()
        with pytest.raises(AttributeError, match="Unknown table"):
            db.nonexistent_table
