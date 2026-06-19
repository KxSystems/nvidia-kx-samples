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

"""Unit tests for tool-level progress streaming (Phase 3)."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from conftest import CaptureWriter, make_mock_llm
from kxta.nodes import web_research, reflect_on_summary
from kxta.schema import KXTAState, ConfigSchema, GeneratedQuery
from kxta.source_agents.base import SourceResult
from kxta.source_agents.registry import KdbSource, RagSource


def _make_config(llm, **overrides):
    defaults = ConfigSchema(
        llm=llm,
        report_organization="Test organization",
        collection="test-collection",
        number_of_queries=2,
        rag_url="http://mock-rag:8081/v1",
        num_reflections=2,
        search_web=False,
        topic="Test topic",
    )
    defaults.update(overrides)
    return {"configurable": defaults}


class TestWebResearchProgressEvents:

    @pytest.mark.asyncio
    async def test_query_count_event(self):
        """writer has 'Starting research: N queries'."""
        writer = CaptureWriter()
        llm = make_mock_llm(["test"])

        state = KXTAState(
            queries=[
                GeneratedQuery(query="query one about AI", report_section="s1", rationale="r1"),
                GeneratedQuery(query="query two about ML", report_section="s2", rationale="r2"),
            ],
        )
        config = _make_config(llm)

        mock_result = ("answer", "citation", {"score": "yes"}, None, None)
        with patch('kxta.nodes.process_single_query', new_callable=AsyncMock, return_value=mock_result):
            await web_research(state, config, writer)

        assert writer.has_event_matching("search_progress", "Starting research: 2 queries")

    @pytest.mark.asyncio
    async def test_per_query_events(self):
        """writer has 'Queuing query 1/2', '2/2'."""
        writer = CaptureWriter()
        llm = make_mock_llm(["test"])

        state = KXTAState(
            queries=[
                GeneratedQuery(query="first query", report_section="s1", rationale="r1"),
                GeneratedQuery(query="second query", report_section="s2", rationale="r2"),
            ],
        )
        config = _make_config(llm)

        mock_result = ("answer", "citation", {"score": "yes"}, None, None)
        with patch('kxta.nodes.process_single_query', new_callable=AsyncMock, return_value=mock_result):
            await web_research(state, config, writer)

        assert writer.has_event_matching("search_progress", "Queuing query 1/2")
        assert writer.has_event_matching("search_progress", "Queuing query 2/2")

    @pytest.mark.asyncio
    async def test_completion_event(self):
        """writer has 'All N queries complete'."""
        writer = CaptureWriter()
        llm = make_mock_llm(["test"])

        state = KXTAState(
            queries=[
                GeneratedQuery(query="q1 about something", report_section="s1", rationale="r1"),
                GeneratedQuery(query="q2 about something else", report_section="s2", rationale="r2"),
                GeneratedQuery(query="q3 about another thing", report_section="s3", rationale="r3"),
            ],
        )
        config = _make_config(llm)

        mock_result = ("answer", "citation", {"score": "yes"}, None, None)
        with patch('kxta.nodes.process_single_query', new_callable=AsyncMock, return_value=mock_result):
            await web_research(state, config, writer)

        assert writer.has_event_matching("search_progress", "All 3 queries complete")


class TestMultiSourceProgressEvents:

    @pytest.mark.asyncio
    async def test_multi_source_progress_events(self):
        """Unified body streams a 'Querying ...' progress event naming the chosen
        sources, plus per-source answer events when each source returns content.

        (Formerly TestHybridProgressEvents; the hybrid_mode flag is now obsolete but
        the unified registry path still runs KDB+RAG together when both are enabled.)
        """
        writer = CaptureWriter()
        llm = make_mock_llm(['test'])
        config = _make_config(llm)

        kdb_result = SourceResult(source="kdb", content="kdb answer", citation="kdb cite", record_count=5)
        rag_result = SourceResult(source="rag", content="rag answer", citation="rag cite", record_count=3)

        # KDB must be available for the registry to enable it (use_kdb=True alone is
        # not enough — KdbSource.is_available() gates on the MCP package).
        with patch('kxta.source_agents.registry._mcp_available', True), \
             patch.object(KdbSource, 'run', new=AsyncMock(return_value=kdb_result)), \
             patch.object(RagSource, 'run', new=AsyncMock(return_value=rag_result)), \
             patch.object(RagSource, 'is_available', return_value=True), \
             patch('kxta.search_utils.check_relevancy', new_callable=AsyncMock,
                   return_value={"score": "yes"}):
            from kxta.search_utils import process_single_query
            await process_single_query(
                # Contains a KDB keyword ("stock price") so the router picks KDB too,
                # alongside the always-on RAG floor — exercising the multi-source path.
                query="what is the stock price trend",
                config=config,
                writer=writer,
                collection="test-collection",
                llm=llm,
                search_web=False,
                use_kdb=True,
                hybrid_mode=True,
            )

        # New unified streaming contract: a progress event naming both sources...
        assert writer.has_event_matching("search_progress", "Querying")
        assert writer.has_event_matching("search_progress", "kdb")
        assert writer.has_event_matching("search_progress", "rag")
        # ...and a per-source answer event for each source that returned content.
        assert writer.has_event_matching("kdb_answer", "kdb cite")
        assert writer.has_event_matching("rag_answer", "rag cite")


class TestSingleSourceProgressEvents:

    @pytest.mark.asyncio
    async def test_rag_only_progress_events(self):
        """With only RAG enabled, the unified body streams a 'Querying rag...'
        progress event and a 'rag_answer' event carrying the citation.

        (Formerly TestSequentialProgressEvents; sequential mode is gone — the
        unified registry path drives a single-source RAG query the same way.)
        """
        writer = CaptureWriter()
        llm = make_mock_llm(['test'])
        config = _make_config(llm)

        rag_result = SourceResult(source="rag", content="rag answer", citation="rag cite", record_count=3)

        with patch.object(RagSource, 'run', new=AsyncMock(return_value=rag_result)), \
             patch.object(RagSource, 'is_available', return_value=True), \
             patch('kxta.search_utils.check_relevancy', new_callable=AsyncMock,
                   return_value={"score": "yes"}):
            from kxta.search_utils import process_single_query
            await process_single_query(
                query="test document query",
                config=config,
                writer=writer,
                collection="test-collection",
                llm=llm,
                search_web=False,
                use_kdb=False,
                hybrid_mode=False,
            )

        assert writer.has_event_matching("search_progress", "Querying")
        assert writer.has_event_matching("search_progress", "rag")
        assert writer.has_event_matching("rag_answer", "rag cite")


class TestReflectProgressEvents:

    @pytest.mark.asyncio
    async def test_reflect_progress_events(self):
        """writer has 'Reflection 1/N: Identifying gaps'."""
        writer = CaptureWriter()

        reflection_json = json.dumps({
            "query": "novel query about quantum entanglement effects",
            "report_section": "Analysis",
            "rationale": "Test",
        })
        llm = make_mock_llm([f"<think>analyzing</think>\n```json\n{reflection_json}\n```"])

        state = KXTAState(
            queries=[GeneratedQuery(query="initial query about physics", report_section="s1", rationale="r1")],
            web_research_results=["<sources/>"],
            citations="cite1",
            running_summary="# Report\n\nContent.",
        )
        config = _make_config(llm, num_reflections=2)

        mock_search = AsyncMock(return_value=("answer", "citation", {"score": "yes"}, None, None))
        mock_summarize = AsyncMock(return_value="# Extended Report\n\n" + ("New content. " * 100))

        with patch('kxta.nodes.process_single_query', mock_search), \
             patch('kxta.nodes.summarize_report', mock_summarize):
            await reflect_on_summary(state, config, writer)

        assert writer.has_event_matching("search_progress", "Reflection 1/2: Identifying gaps")
