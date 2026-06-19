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

"""Unit tests for loop detection and early termination (Phase 1)."""

import json
import pytest
from unittest.mock import AsyncMock, patch

from conftest import CaptureWriter, make_mock_llm
from kxta.search_utils import compute_query_similarity, is_query_novel
from kxta.nodes import reflect_on_summary
from kxta.schema import KXTAState, ConfigSchema, GeneratedQuery


# --- compute_query_similarity ---

class TestComputeQuerySimilarity:

    def test_identical(self):
        """Same string -> 1.0."""
        assert compute_query_similarity("hello world", "hello world") == 1.0

    def test_disjoint(self):
        """No word overlap -> 0.0."""
        assert compute_query_similarity("hello world", "foo bar") == 0.0

    def test_partial_overlap(self):
        """Partial overlap -> expected Jaccard score."""
        # "hello world" and "hello there" share "hello"
        # union = {"hello", "world", "there"} = 3
        # intersection = {"hello"} = 1
        # Jaccard = 1/3
        result = compute_query_similarity("hello world", "hello there")
        assert abs(result - 1 / 3) < 0.01

    def test_empty_string(self):
        """Empty string -> 0.0."""
        assert compute_query_similarity("", "hello") == 0.0
        assert compute_query_similarity("hello", "") == 0.0
        assert compute_query_similarity("", "") == 0.0

    def test_case_insensitive(self):
        """Comparison is case-insensitive."""
        assert compute_query_similarity("Hello World", "hello world") == 1.0

    def test_subset(self):
        """One query is subset of another."""
        # "stock" vs "stock price analysis"
        # intersection = {"stock"} = 1, union = {"stock", "price", "analysis"} = 3
        result = compute_query_similarity("stock", "stock price analysis")
        assert abs(result - 1 / 3) < 0.01


# --- is_query_novel ---

class TestIsQueryNovel:

    def test_novel_query(self):
        """Different query -> True."""
        assert is_query_novel(
            "quantum computing applications",
            ["stock price analysis", "market trends 2024"]
        ) is True

    def test_duplicate_query(self):
        """Near-duplicate -> False."""
        assert is_query_novel(
            "stock price analysis trends",
            ["stock price analysis"]
        ) is False

    def test_empty_history(self):
        """No previous queries -> always True."""
        assert is_query_novel("any query at all", []) is True

    def test_threshold_boundary(self):
        """Custom threshold changes behavior."""
        # These queries have some overlap
        query = "machine learning applications in finance"
        history = ["machine learning in healthcare"]
        # With default threshold (0.7) this should be novel
        assert is_query_novel(query, history, threshold=0.7) is True
        # With a very low threshold it shouldn't be
        assert is_query_novel(query, history, threshold=0.2) is False


# --- reflect_on_summary integration tests with mocks ---

def _make_reflect_config(llm, num_reflections=2):
    return {
        "configurable": ConfigSchema(
            llm=llm,
            report_organization="Test organization",
            collection="test-collection",
            number_of_queries=2,
            rag_url="http://mock-rag:8081/v1",
            num_reflections=num_reflections,
            search_web=False,
            topic="Test topic",
        )
    }


class TestReflectSkipsSimilarQuery:

    @pytest.mark.asyncio
    async def test_skips_similar_query(self):
        """Mock reflection produces duplicate -> process_single_query call count < num_reflections."""
        writer = CaptureWriter()

        # Both reflections produce same/similar query as the initial query
        reflection_json = json.dumps({
            "query": "What are the key findings on topic A",  # Same as initial query
            "report_section": "Analysis",
            "rationale": "Test",
        })
        llm = make_mock_llm([f"<think>gap analysis</think>\n```json\n{reflection_json}\n```"])

        state = KXTAState(
            queries=[GeneratedQuery(query="What are the key findings on topic A", report_section="s1", rationale="r1")],
            web_research_results=["<sources/>"],
            citations="cite1",
            running_summary="# Report\n\nInitial content.",
        )
        config = _make_reflect_config(llm, num_reflections=2)

        mock_search = AsyncMock(return_value=("answer", "citation", {"score": "yes"}, None, None))

        with patch('kxta.nodes.process_single_query', mock_search), \
             patch('kxta.nodes.summarize_report', new_callable=AsyncMock, return_value="# Extended\n\nMore."):
            await reflect_on_summary(state, config, writer)

        # process_single_query should NOT have been called since queries are duplicates
        assert mock_search.call_count == 0
        assert writer.has_event_matching("reflect_on_summary", "Skipping similar query")


class TestReflectEarlyTermination:

    @pytest.mark.asyncio
    async def test_early_termination_minimal_growth(self):
        """Mock summarize_report with minimal growth -> loop exits early."""
        writer = CaptureWriter()

        reflection_json = json.dumps({
            "query": "What are the performance benchmarks for the technology",
            "report_section": "Analysis",
            "rationale": "Missing benchmarks",
        })
        llm = make_mock_llm([f"<think>analyzing</think>\n```json\n{reflection_json}\n```"])

        existing_summary = "# Report\n\n" + ("Detailed analysis content. " * 50)  # ~1400 chars
        state = KXTAState(
            queries=[GeneratedQuery(query="initial query about AI", report_section="s1", rationale="r1")],
            web_research_results=["<sources/>"],
            citations="cite1",
            running_summary=existing_summary,
        )
        config = _make_reflect_config(llm, num_reflections=3)

        mock_search = AsyncMock(return_value=("answer", "citation", {"score": "yes"}, None, None))
        # Return nearly identical report (minimal growth)
        mock_summarize = AsyncMock(return_value=existing_summary + ".")

        with patch('kxta.nodes.process_single_query', mock_search), \
             patch('kxta.nodes.summarize_report', mock_summarize):
            await reflect_on_summary(state, config, writer)

        # Should have stopped after first reflection due to minimal growth
        assert mock_search.call_count == 1
        assert writer.has_event_matching("reflect_on_summary", "Early stop")


class TestPreviousQueriesInPrompt:

    @pytest.mark.asyncio
    async def test_previous_queries_passed_to_prompt(self):
        """Capture LLM input -> contains 'Previously searched queries'."""
        writer = CaptureWriter()

        # Use a unique query to avoid novelty check skipping
        reflection_json = json.dumps({
            "query": "Completely novel quantum computing performance metrics",
            "report_section": "Analysis",
            "rationale": "Test",
        })
        llm = make_mock_llm([f"<think>thinking</think>\n```json\n{reflection_json}\n```"])

        state = KXTAState(
            queries=[
                GeneratedQuery(query="initial query about neural networks", report_section="s1", rationale="r1"),
                GeneratedQuery(query="deep learning architectures overview", report_section="s2", rationale="r2"),
            ],
            web_research_results=["<sources/>"],
            citations="cite1",
            running_summary="# Report\n\nContent.",
        )
        config = _make_reflect_config(llm, num_reflections=1)

        mock_search = AsyncMock(return_value=("answer", "citation", {"score": "yes"}, None, None))
        mock_summarize = AsyncMock(return_value="# Extended Report\n\n" + ("New content. " * 100))

        captured_inputs = []
        original_astream = llm.astream

        async def capture_astream(input_dict, *args, **kwargs):
            captured_inputs.append(input_dict)
            async for chunk in original_astream(input_dict, *args, **kwargs):
                yield chunk

        with patch('kxta.nodes.process_single_query', mock_search), \
             patch('kxta.nodes.summarize_report', mock_summarize):
            # We need to capture what's passed to the chain
            # The chain is prompt | llm, so we check the prompt formatting
            # The easiest way is to verify the reflection_instructions format call includes previous_queries
            with patch('kxta.nodes.reflection_instructions') as mock_instructions:
                mock_instructions.format.return_value = "mocked prompt with previous queries"
                await reflect_on_summary(state, config, writer)

                # Verify format was called with previous_queries parameter
                call_kwargs = mock_instructions.format.call_args
                assert "previous_queries" in call_kwargs.kwargs or \
                    any("previous_queries" in str(arg) for arg in call_kwargs.args if isinstance(arg, str))
                # Check that our initial queries are included
                previous_queries_val = call_kwargs.kwargs.get("previous_queries", "")
                assert "initial query about neural networks" in previous_queries_val
                assert "deep learning architectures overview" in previous_queries_val
