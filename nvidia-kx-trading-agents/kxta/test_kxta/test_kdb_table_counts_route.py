# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
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
import asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
import kxta.fastapi_extensions.routes.kdb_tables_settings as mod


def test_get_includes_table_rows(monkeypatch):
    monkeypatch.setattr(mod, "get_selected_tables", lambda: ["trade"])
    monkeypatch.setattr(mod, "_available_tables", lambda: ["daily", "trade", "quote", "fundamentals"])

    async def fake_counts(tables):
        return {"daily": 12446, "trade": 62230, "quote": 124460, "fundamentals": None}

    monkeypatch.setattr(mod, "kdb_table_counts", fake_counts)
    app = FastAPI()
    asyncio.run(mod.add_kdb_tables_settings_routes(app))
    client = TestClient(app)
    r = client.get("/settings/kdb-tables")
    assert r.status_code == 200
    body = r.json()
    assert body["available_tables"] == ["daily", "trade", "quote", "fundamentals"]
    assert body["table_rows"]["trade"] == 62230
    assert body["table_rows"]["fundamentals"] is None


def test_get_table_rows_best_effort(monkeypatch):
    monkeypatch.setattr(mod, "get_selected_tables", lambda: [])
    monkeypatch.setattr(mod, "_available_tables", lambda: ["daily"])

    async def boom(tables):
        raise RuntimeError("kdbx down")

    monkeypatch.setattr(mod, "kdb_table_counts", boom)
    app = FastAPI()
    asyncio.run(mod.add_kdb_tables_settings_routes(app))
    client = TestClient(app)
    r = client.get("/settings/kdb-tables")
    assert r.status_code == 200
    assert r.json()["table_rows"] == {}
