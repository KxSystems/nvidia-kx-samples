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
"""Tests for the /api/data/* explorer endpoints."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from kdbx.schema import TABLE_NAMES, VALID_COLUMNS


# ---------------------------------------------------------------------------
# App fixture — patches heavy imports so the FastAPI app can be created
# without real KDB-X / Celery / NeMo dependencies.
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    """Create a TestClient with all external deps mocked."""
    with (
        patch("src.api.db.init_db"),
        patch("src.api.endpoints.run_nim_workflow_dag"),
        patch("src.app.validate_llm_judge"),
    ):
        from src.app import app

        yield TestClient(app)


@pytest.fixture()
def mock_db():
    """Provide a MagicMock KDBXDatabase and patch ``get_db`` to return it."""
    db = MagicMock(name="KDBXDatabase")
    with patch("src.api.endpoints.get_db", return_value=db):
        yield db


# ---------------------------------------------------------------------------
# GET /api/data/schema
# ---------------------------------------------------------------------------


class TestGetSchema:
    def test_returns_all_tables(self, client, mock_db):
        resp = client.get("/api/data/schema")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body["tables"].keys()) == set(TABLE_NAMES)

    def test_columns_are_sorted(self, client, mock_db):
        resp = client.get("/api/data/schema")
        body = resp.json()
        for table, cols in body["tables"].items():
            assert cols == sorted(cols), f"{table} columns not sorted"

    def test_column_counts_match_schema(self, client, mock_db):
        resp = client.get("/api/data/schema")
        body = resp.json()
        for table in TABLE_NAMES:
            assert len(body["tables"][table]) == len(VALID_COLUMNS[table])


# ---------------------------------------------------------------------------
# GET /api/data/{table}
# ---------------------------------------------------------------------------


class TestGetTableRows:
    def test_unknown_table_returns_404(self, client, mock_db):
        resp = client.get("/api/data/nonexistent")
        assert resp.status_code == 404
        assert "nonexistent" in resp.json()["detail"]

    def test_returns_rows(self, client, mock_db):
        fake_rows = [
            {"_id": "abc123", "workload_id": "wl1", "status": "pending"},
        ]
        mock_db.flywheel_runs.find.return_value = fake_rows

        resp = client.get("/api/data/flywheel_runs")
        assert resp.status_code == 200
        body = resp.json()
        assert body["table"] == "flywheel_runs"
        assert body["count"] == 1
        assert body["rows"] == fake_rows

    def test_default_limit_is_50(self, client, mock_db):
        mock_db.flywheel_runs.find.return_value = []
        client.get("/api/data/flywheel_runs")
        mock_db.flywheel_runs.find.assert_called_once_with({}, limit=50)

    def test_custom_limit(self, client, mock_db):
        mock_db.flywheel_runs.find.return_value = []
        client.get("/api/data/flywheel_runs?limit=5")
        mock_db.flywheel_runs.find.assert_called_once_with({}, limit=5)

    def test_limit_clamped_to_1000(self, client, mock_db):
        resp = client.get("/api/data/flywheel_runs?limit=9999")
        assert resp.status_code == 422  # validation error

    def test_column_filter(self, client, mock_db):
        mock_db.flywheel_runs.find.return_value = []
        client.get("/api/data/flywheel_runs?status=pending&workload_id=wl1")
        mock_db.flywheel_runs.find.assert_called_once_with(
            {"status": "pending", "workload_id": "wl1"}, limit=50
        )

    def test_ignores_unknown_params(self, client, mock_db):
        mock_db.flywheel_runs.find.return_value = []
        client.get("/api/data/flywheel_runs?bogus=123&status=ok")
        mock_db.flywheel_runs.find.assert_called_once_with(
            {"status": "ok"}, limit=50
        )

    def test_serializes_objectid(self, client, mock_db):
        oid = ObjectId()
        mock_db.flywheel_runs.find.return_value = [{"_id": oid}]
        resp = client.get("/api/data/flywheel_runs")
        assert resp.json()["rows"][0]["_id"] == str(oid)

    def test_serializes_datetime(self, client, mock_db):
        dt = datetime(2025, 6, 15, 12, 0, 0)
        mock_db.flywheel_runs.find.return_value = [{"started_at": dt}]
        resp = client.get("/api/data/flywheel_runs")
        assert resp.json()["rows"][0]["started_at"] == "2025-06-15T12:00:00"


# ---------------------------------------------------------------------------
# GET /api/data/{table}/count
# ---------------------------------------------------------------------------


class TestGetTableCount:
    def test_unknown_table_returns_404(self, client, mock_db):
        resp = client.get("/api/data/nonexistent/count")
        assert resp.status_code == 404

    def test_returns_count(self, client, mock_db):
        mock_db.nims.find.return_value = [{"_id": "a"}, {"_id": "b"}]
        resp = client.get("/api/data/nims/count")
        assert resp.status_code == 200
        body = resp.json()
        assert body["table"] == "nims"
        assert body["count"] == 2

    def test_count_with_filter(self, client, mock_db):
        mock_db.flywheel_runs.find.return_value = [{"_id": "x"}]
        resp = client.get("/api/data/flywheel_runs/count?status=done")
        assert resp.status_code == 200
        mock_db.flywheel_runs.find.assert_called_once_with(
            {"status": "done"}, limit=None
        )
        assert resp.json()["count"] == 1

    def test_count_empty_table(self, client, mock_db):
        mock_db.evaluations.find.return_value = []
        resp = client.get("/api/data/evaluations/count")
        assert resp.json()["count"] == 0
