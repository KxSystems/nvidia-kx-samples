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

import kxta.kdb_docs_settings as kds
import kxta.kdb_vector as kv
from kxta.source_agents.registry import KdbDocsSource


def test_available_requires_host_and_collection(monkeypatch):
    src = KdbDocsSource()
    # is_available() does a call-time `from ... import get_selected_collection` and
    # `from ... import embedding_configured`, so patching the module attributes is
    # picked up at call time.
    monkeypatch.setattr(kds, "get_selected_collection", lambda: "smoke_cloud")
    monkeypatch.setenv("KDB_DB_HOST", "kdbx")
    monkeypatch.setattr(kv, "embedding_configured", lambda: True)
    assert src.is_available() is True

    monkeypatch.setattr(kds, "get_selected_collection", lambda: None)
    assert src.is_available() is False

    monkeypatch.setattr(kds, "get_selected_collection", lambda: "smoke_cloud")
    monkeypatch.delenv("KDB_DB_HOST", raising=False)
    assert src.is_available() is False


def test_available_requires_embedding(monkeypatch):
    src = KdbDocsSource()
    monkeypatch.setenv("KDB_DB_HOST", "kdbx")
    monkeypatch.setattr(kds, "get_selected_collection", lambda: "sec")
    monkeypatch.setattr(kv, "embedding_configured", lambda: True)
    assert src.is_available() is True
    monkeypatch.setattr(kv, "embedding_configured", lambda: False)
    assert src.is_available() is False


def test_state_of_reason_when_unavailable(monkeypatch):
    from kxta.source_agents.registry import SourceRegistry
    monkeypatch.delenv("KDB_DB_HOST", raising=False)
    monkeypatch.setattr(kds, "get_selected_collection", lambda: None)
    src = KdbDocsSource()
    state = SourceRegistry()._state_of(src)
    assert state["state"] == "unavailable"
    assert "KDB_DB_HOST" in state["reason"]

    # Host set, no collection — reaches collection gate (embedding gate not reached).
    monkeypatch.setenv("KDB_DB_HOST", "kdbx")
    state = SourceRegistry()._state_of(src)
    assert state["state"] == "unavailable"
    assert "collection" in state["reason"].lower()

    # Host + collection set, embedding not configured — reaches embedding gate.
    monkeypatch.setattr(kds, "get_selected_collection", lambda: "sec")
    monkeypatch.setattr(kv, "embedding_configured", lambda: False)
    state = SourceRegistry()._state_of(src)
    assert state["state"] == "unavailable"
    assert "embedding" in state["reason"].lower()


def test_embedding_configured(monkeypatch):
    for v in ("KDB_VECTOR_EMBED_URL", "EMBEDDING_NIM_URL", "NVIDIA_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    assert kv.embedding_configured() is False                      # hosted default, no key
    monkeypatch.setenv("NVIDIA_API_KEY", "x")
    assert kv.embedding_configured() is True                       # hosted default + key
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setenv("EMBEDDING_NIM_URL", "http://nemo-embed:8000")
    assert kv.embedding_configured() is True                       # explicit in-cluster endpoint


def test_run_uses_config_table(monkeypatch):
    captured = {}

    async def fake_search(query, n=5, table=None, **kw):
        captured["table"] = table
        return {"isError": False, "rows": [{"score": 0.9, "text": "hello world"}]}

    monkeypatch.setattr(kv, "kdb_vector_search", fake_search)
    src = KdbDocsSource()
    cfg = {"configurable": {"kdb_vector_table": "picked_coll"}}
    res = asyncio.run(src.run("risk factors", cfg, lambda e: None))
    assert captured["table"] == "picked_coll"
    assert res.source == "kdb_docs"
    assert "hello world" in res.content


def test_run_falls_back_to_selected_setting(monkeypatch):
    captured = {}

    async def fake_search(query, n=5, table=None, **kw):
        captured["table"] = table
        return {"isError": False, "rows": [{"score": 0.5, "text": "x"}]}

    monkeypatch.setattr(kv, "kdb_vector_search", fake_search)
    monkeypatch.setattr(kds, "get_selected_collection", lambda: "from_settings")
    src = KdbDocsSource()
    res = asyncio.run(src.run("q", {"configurable": {}}, lambda e: None))
    assert captured["table"] == "from_settings"
    assert res.source == "kdb_docs"


def test_planner_lists_kdb_docs_and_routes_filings_to_it(monkeypatch):
    from kxta.source_agents.registry import SourceRegistry
    # Make kdb_docs available: KDB_DB_HOST set + a selected collection + embedding configured.
    monkeypatch.setenv("KDB_DB_HOST", "kdbx")
    monkeypatch.setattr(kds, "get_selected_collection", lambda: "smoke_cloud")
    monkeypatch.setattr(kv, "embedding_configured", lambda: True)
    section = SourceRegistry().describe_for_planner({"use_kdb_docs": True, "use_rag": False})
    # kdb_docs is advertised to the planner...
    assert "`kdb_docs`" in section
    # ...and the filings routing rule resolves to kdb_docs (preferred over sec_filings).
    assert "filings content, risk factors, MD&A" in section
    assert "→ `kdb_docs`" in section
