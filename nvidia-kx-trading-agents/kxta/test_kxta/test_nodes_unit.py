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

"""Unit tests for nodes.py with mocked LLM chains."""

import asyncio
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from conftest import CaptureWriter, make_mock_llm
from kxta.nodes import generate_query, reflect_on_summary
from kxta.schema import KXTAState, ConfigSchema, GeneratedQuery


def _make_config(llm, **overrides):
    """Helper to build a config dict for node functions."""
    defaults = ConfigSchema(
        llm=llm,
        report_organization="Test report organization",
        collection="test-collection",
        number_of_queries=2,
        rag_url="http://mock-rag:8081/v1",
        num_reflections=2,
        search_web=False,
        topic="Test topic",
    )
    defaults.update(overrides)
    return {"configurable": defaults}


class TestGenerateQuery:

    @pytest.mark.asyncio
    async def test_timeout(self):
        """TimeoutError -> {'queries': []}."""
        writer = CaptureWriter()
        mock_llm = MagicMock()
        mock_llm.model = "test-model"
        mock_llm.model_name = "test-model"

        async def mock_astream_timeout(*args, **kwargs):
            raise asyncio.TimeoutError()
            yield  # noqa: E501

        mock_llm.astream = mock_astream_timeout

        config = _make_config(mock_llm)
        state = KXTAState()

        with patch('kxta.nodes.ASYNC_TIMEOUT', 0.001):
            result = await generate_query(state, config, writer)

        assert result == {"queries": []}
        assert writer.has_event_matching("generating_questions", "Timeout")

    @pytest.mark.asyncio
    async def test_no_think_tag(self):
        """No </think> tag -> {'queries': []}."""
        writer = CaptureWriter()
        # Response without </think> tag
        llm = make_mock_llm(["Some response without think tag"])
        config = _make_config(llm)
        state = KXTAState()

        result = await generate_query(state, config, writer)
        assert result == {"queries": []}

    @pytest.mark.asyncio
    async def test_json_parse_error(self):
        """Invalid JSON after </think> -> {'queries': []}."""
        writer = CaptureWriter()
        llm = make_mock_llm(["<think>reasoning</think>", "this is not valid json"])
        config = _make_config(llm)
        state = KXTAState()

        result = await generate_query(state, config, writer)
        assert result == {"queries": []}

    @pytest.mark.asyncio
    async def test_success(self):
        """Valid response -> list of GeneratedQuery."""
        writer = CaptureWriter()
        queries_json = json.dumps([
            {"query": "What is transformer architecture", "report_section": "Introduction", "rationale": "Foundation"},
            {"query": "Attention mechanism explained", "report_section": "Technical", "rationale": "Core concept"},
        ])
        llm = make_mock_llm([f"<think>thinking</think>\n```json\n{queries_json}\n```"])
        config = _make_config(llm)
        state = KXTAState()

        result = await generate_query(state, config, writer)
        assert "queries" in result
        assert len(result["queries"]) == 2
        assert all(isinstance(q, GeneratedQuery) for q in result["queries"])


class TestReflectOnSummary:

    @pytest.mark.asyncio
    async def test_no_think_tag_returns_existing(self):
        """No </think> in LLM response -> returns existing summary unchanged."""
        writer = CaptureWriter()
        llm = make_mock_llm(["Some response without think tag ending"])

        state = KXTAState(
            queries=[GeneratedQuery(query="q1", report_section="s1", rationale="r1")],
            web_research_results=["<sources/>"],
            citations="cite1",
            running_summary="# Existing Report\n\nContent here.",
        )
        config = _make_config(llm, num_reflections=1)

        result = await reflect_on_summary(state, config, writer)
        assert result["running_summary"] == "# Existing Report\n\nContent here."

    @pytest.mark.asyncio
    async def test_successful_reflection(self):
        """Valid reflection -> processes query and extends report."""
        writer = CaptureWriter()
        reflection_json = json.dumps({
            "query": "What are performance benchmarks",
            "report_section": "Analysis",
            "rationale": "Missing benchmarks",
        })
        llm = make_mock_llm([f"<think>analyzing gaps</think>\n```json\n{reflection_json}\n```"])

        state = KXTAState(
            queries=[GeneratedQuery(query="q1", report_section="s1", rationale="r1")],
            web_research_results=["<sources/>"],
            citations="cite1",
            running_summary="# Existing Report\n\nInitial content.",
        )
        config = _make_config(llm, num_reflections=1)

        mock_search_result = ("answer", "citation", {"score": "yes"}, None, None)

        with patch('kxta.nodes.process_single_query', new_callable=AsyncMock, return_value=mock_search_result), \
             patch('kxta.nodes.summarize_report', new_callable=AsyncMock, return_value="# Extended Report\n\nMore content."):
            result = await reflect_on_summary(state, config, writer)

        assert "running_summary" in result
