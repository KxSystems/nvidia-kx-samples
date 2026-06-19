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
import kxta.fastapi_extensions.routes.kdb_docs_settings as mod


def _build(monkeypatch, current="smoke_cloud"):
    holder = {"v": current}
    monkeypatch.setattr(mod, "get_selected_collection", lambda: holder["v"])

    def fake_set(name):
        holder["v"] = (name or None)
        return holder["v"]

    monkeypatch.setattr(mod, "set_selected_collection", fake_set)

    async def fake_list(url):
        return ["smoke_cloud", "sec_docs"]

    monkeypatch.setattr(mod, "_list_rag_collections", fake_list)
    app = FastAPI()
    asyncio.run(mod.add_kdb_docs_settings_routes(app, "http://rag:8082/v1"))
    return TestClient(app), holder


def test_get_settings(monkeypatch):
    client, _ = _build(monkeypatch)
    r = client.get("/settings/kdb-docs")
    assert r.status_code == 200
    body = r.json()
    assert body["collection"] == "smoke_cloud"
    assert body["available_collections"] == ["smoke_cloud", "sec_docs"]


def test_put_settings(monkeypatch):
    client, holder = _build(monkeypatch)
    r = client.put("/settings/kdb-docs", json={"collection": "sec_docs"})
    assert r.status_code == 200
    assert r.json()["collection"] == "sec_docs"
    assert holder["v"] == "sec_docs"


def test_put_clear(monkeypatch):
    client, holder = _build(monkeypatch)
    r = client.put("/settings/kdb-docs", json={"collection": None})
    assert r.status_code == 200
    assert r.json()["collection"] is None
    assert holder["v"] is None
