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
from unittest.mock import AsyncMock

from kxta.source_agents.agent_base import AgentSource


class _FakeGraph:
    def __init__(self, result):
        self._result = result
        self.ainvoke = AsyncMock(return_value=result)


class _DummySource(AgentSource):
    name = "dummy"
    label = "Dummy"
    description = "test"
    keywords = ["dummy"]
    requires_env = []
    requires_modules = []

    async def _build_graph(self):
        return _FakeGraph({
            "research_report": "REPORT BODY",
            "key_findings": ["a", "b"],
            "data_summary": {"articles_analyzed": 3},
            "sources": [{"title": "T", "url": "http://x"}],
        })

    def _initial_state(self, query):
        return {"query": query}


def test_agent_source_maps_result_to_source_result():
    cfg = {"configurable": {"llm": object()}}
    src = _DummySource()
    res = asyncio.run(src.run("a dummy query", cfg, writer=lambda e: None))
    assert res.source == "dummy"
    assert "REPORT BODY" in res.content
    assert res.record_count == 3
    assert "http://x" in res.citation


def test_agent_source_failure_returns_empty(monkeypatch):
    cfg = {"configurable": {"llm": object()}}
    src = _DummySource()
    monkeypatch.setattr(src, "_build_graph", AsyncMock(side_effect=RuntimeError("boom")))
    res = asyncio.run(src.run("q", cfg, writer=lambda e: None))
    assert res.content == ""
    assert res.source == "dummy"


def test_agent_source_failure_logs_type_and_traceback(monkeypatch, caplog):
    """A generic failure must log the exception type + traceback (not an empty message)."""
    import logging
    cfg = {"configurable": {"llm": object()}}
    src = _DummySource()
    monkeypatch.setattr(src, "_build_graph", AsyncMock(side_effect=ValueError("boom-detail")))
    with caplog.at_level(logging.ERROR, logger="kxta.source_agents.agent_base"):
        asyncio.run(src.run("q", cfg, writer=lambda e: None))
    text = caplog.text
    assert "ValueError" in text and "boom-detail" in text
    assert "Traceback" in text  # logger.exception attaches the traceback


def test_agent_source_timeout_logs_clear_message(monkeypatch, caplog):
    """A timeout (empty str()) must log a clear 'timed out' message with the limit."""
    import logging
    cfg = {"configurable": {"llm": object()}}
    src = _DummySource()
    monkeypatch.setattr(src, "_build_graph", AsyncMock(side_effect=asyncio.TimeoutError()))
    with caplog.at_level(logging.ERROR, logger="kxta.source_agents.agent_base"):
        res = asyncio.run(src.run("q", cfg, writer=lambda e: None))
    assert res.content == ""
    assert "timed out" in caplog.text
    assert "ASYNC_TIMEOUT" in caplog.text
