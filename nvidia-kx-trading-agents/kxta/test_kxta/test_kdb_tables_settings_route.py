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


def _build(monkeypatch, current=None):
    holder = {"v": list(current or ["daily"])}
    monkeypatch.setattr(mod, "get_selected_tables", lambda: list(holder["v"]))

    def fake_set(tables):
        holder["v"] = [t for t in (tables or []) if t]
        return list(holder["v"])

    monkeypatch.setattr(mod, "set_selected_tables", fake_set)
    monkeypatch.setattr(mod, "_available_tables", lambda: ["daily", "trade", "quote", "fundamentals", "news", "recommendations"])
    app = FastAPI()
    asyncio.run(mod.add_kdb_tables_settings_routes(app))
    return TestClient(app), holder


def test_get_settings(monkeypatch):
    client, _ = _build(monkeypatch, current=["daily"])
    r = client.get("/settings/kdb-tables")
    assert r.status_code == 200
    b = r.json()
    assert b["selected_tables"] == ["daily"]
    assert "quote" in b["available_tables"]


def test_put_settings(monkeypatch):
    client, holder = _build(monkeypatch)
    r = client.put("/settings/kdb-tables", json={"tables": ["daily", "quote"]})
    assert r.status_code == 200
    assert r.json()["selected_tables"] == ["daily", "quote"]
    assert holder["v"] == ["daily", "quote"]


def test_put_clear(monkeypatch):
    client, holder = _build(monkeypatch)
    r = client.put("/settings/kdb-tables", json={"tables": []})
    assert r.status_code == 200
    assert r.json()["selected_tables"] == []
    assert holder["v"] == []
