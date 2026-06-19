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

"""Unit tests for search_utils.py pure functions (no LLM/network required)."""

import pytest
from unittest.mock import patch

from kxta.search_utils import (
    SourceResult,
    merge_hybrid_results,
    deduplicate_and_format_sources,
    format_duration,
    classify_query_type,
)
from kxta.schema import GeneratedQuery


# --- merge_hybrid_results ---

class TestMergeHybridResults:

    def test_both_relevant(self):
        """Both KDB+RAG relevant -> merged content with source headers."""
        kdb = SourceResult(source='kdb', content="KDB data here", citation="kdb-cite", is_relevant=True)
        rag = SourceResult(source='rag', content="RAG context here", citation="rag-cite", is_relevant=True)
        content, citation = merge_hybrid_results(kdb, rag, "test query")
        assert "Financial Data (KDB+)" in content
        assert "KDB data here" in content
        assert "Document Analysis (RAG)" in content
        assert "RAG context here" in content
        assert "KDB+ Source" in citation
        assert "Document Source" in citation

    def test_kdb_only(self):
        """Only KDB relevant -> KDB content returned."""
        kdb = SourceResult(source='kdb', content="KDB only data", citation="kdb-cite", is_relevant=True)
        rag = SourceResult(source='rag', content="", citation="", is_relevant=False)
        content, citation = merge_hybrid_results(kdb, rag, "test query")
        assert content == "KDB only data"
        assert citation == "kdb-cite"

    def test_rag_only(self):
        """Only RAG relevant -> RAG content returned."""
        kdb = SourceResult(source='kdb', content="", citation="", is_relevant=False)
        rag = SourceResult(source='rag', content="RAG only data", citation="rag-cite", is_relevant=True)
        content, citation = merge_hybrid_results(kdb, rag, "test query")
        assert content == "RAG only data"
        assert citation == "rag-cite"

    def test_neither_relevant(self):
        """Neither relevant -> best available fallback."""
        kdb = SourceResult(source='kdb', content="Some kdb fallback text that is long enough to pass", citation="kdb-cite", is_relevant=False)
        rag = SourceResult(source='rag', content="", citation="", is_relevant=False)
        content, citation = merge_hybrid_results(kdb, rag, "test query")
        assert "kdb fallback" in content

    def test_both_empty(self):
        """Both None -> 'No relevant information' message."""
        content, citation = merge_hybrid_results(None, None, "test query")
        assert "No relevant information" in content
        assert citation == ""


# --- deduplicate_and_format_sources ---

class TestDeduplicateAndFormatSources:

    def test_valid_xml_structure(self):
        """Produces valid XML <sources> structure."""
        queries = [
            GeneratedQuery(query="test query 1", report_section="Intro", rationale="r1"),
        ]
        sources = ["cite1"]
        answers = ["answer1"]
        relevant = [{"score": "yes"}]
        web = [None]

        result = deduplicate_and_format_sources(sources, answers, relevant, web, queries)
        assert result.startswith("<sources>")
        assert "</sources>" in result
        assert "<query>test query 1</query>" in result
        assert "<answer>answer1</answer>" in result

    def test_web_fallback(self):
        """score='no' uses web_result when available."""
        queries = [
            GeneratedQuery(query="test query", report_section="Body", rationale="r"),
        ]
        sources = ["cite1"]
        answers = ["rag answer"]
        relevant = [{"score": "no"}]
        web = ["web answer"]

        result = deduplicate_and_format_sources(sources, answers, relevant, web, queries)
        assert "<answer>web answer</answer>" in result

    def test_no_fallback_keeps_rag(self):
        """score='no' but no web_result -> uses rag answer (fallback_ans is None)."""
        queries = [
            GeneratedQuery(query="test query", report_section="Body", rationale="r"),
        ]
        sources = ["cite1"]
        answers = ["rag answer"]
        relevant = [{"score": "no"}]
        web = [None]

        result = deduplicate_and_format_sources(sources, answers, relevant, web, queries)
        assert "<answer>rag answer</answer>" in result


# --- format_duration ---

class TestFormatDuration:

    def test_milliseconds(self):
        assert format_duration(0.5) == "500ms"

    def test_seconds(self):
        assert format_duration(5.3) == "5.3s"

    def test_minutes(self):
        assert format_duration(125) == "2m 5s"

    def test_zero(self):
        assert format_duration(0) == "0ms"

    def test_exactly_one_second(self):
        assert format_duration(1.0) == "1.0s"


# --- classify_query_type ---

class TestClassifyQueryType:

    @pytest.mark.asyncio
    async def test_explicit_kdb(self):
        """use_kdb=True -> 'kdb' regardless of query content."""
        result = await classify_query_type("How does photosynthesis work?", use_kdb=True)
        assert result == "kdb"

    @pytest.mark.asyncio
    async def test_explicit_no_kdb(self):
        """use_kdb=False -> 'rag' even for financial query."""
        result = await classify_query_type("What is AAPL stock price?", use_kdb=False)
        assert result == "rag"

    @pytest.mark.asyncio
    async def test_auto_detect_non_financial(self):
        """use_kdb=None + non-financial query -> 'rag'."""
        result = await classify_query_type("Explain quantum computing", use_kdb=None)
        assert result == "rag"


# --- SourceResult.is_empty ---

class TestSourceResultIsEmpty:

    def test_empty_content(self):
        sr = SourceResult(source='rag', content="", citation="")
        assert sr.is_empty() is True

    def test_error_pattern_short(self):
        sr = SourceResult(source='rag', content="error occurred", citation="")
        assert sr.is_empty() is True

    def test_no_data_pattern(self):
        sr = SourceResult(source='kdb', content="no data found", citation="")
        assert sr.is_empty() is True

    def test_valid_long_content(self):
        """Valid long content -> False."""
        sr = SourceResult(source='rag', content="This is a valid detailed answer " * 20, citation="cite")
        assert sr.is_empty() is False

    def test_error_word_in_long_content(self):
        """Error word in long content (>200 chars) -> False (not empty)."""
        long_content = "This analysis discusses error handling in distributed systems. " * 10
        sr = SourceResult(source='rag', content=long_content, citation="cite")
        assert sr.is_empty() is False
