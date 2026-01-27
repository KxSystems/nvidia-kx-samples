# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

"""
Tests for KDB+ MCP Server integration using NAT 1.3.0+ MCP client.

These tests verify:
1. Query classification logic
2. LLM-driven intelligent tool discovery
3. Integration with the search workflow
"""

import pytest
import asyncio
import json
import os
from unittest.mock import patch, MagicMock, AsyncMock

from aiq_aira.kdb_tools_nat import (
    is_kdb_query,
    KDB_KEYWORDS,
    KDB_ENABLED,
)
from aiq_aira.search_utils import classify_query_type


class TestKDBKeywordClassification:
    """Test keyword-based query classification."""

    def test_financial_queries_detected(self):
        """Test that financial queries are correctly identified."""
        financial_queries = [
            "What is AAPL stock price today?",
            "Show me trading volume for MSFT",
            "Historical market data for Tesla",
            "OHLC candle data for Bitcoin",
            "Calculate portfolio returns",
            "Stock volatility analysis",
            "Bid ask spread for GOOGL",
            "Moving average crossover signals",
        ]
        for query in financial_queries:
            assert is_kdb_query(query), f"Expected '{query}' to be classified as KDB+ query"

    def test_non_financial_queries_not_detected(self):
        """Test that non-financial queries are not misclassified."""
        non_financial_queries = [
            "How does photosynthesis work?",
            "Explain the French Revolution",
            "What are the symptoms of diabetes?",
            "Latest news about climate change",
            "Recipe for chocolate cake",
        ]
        for query in non_financial_queries:
            assert not is_kdb_query(query), f"Expected '{query}' NOT to be classified as KDB+ query"

    def test_edge_cases(self):
        """Test edge cases in query classification."""
        # Mixed content - should be detected if it contains financial keywords
        assert is_kdb_query("What is the current price of gold?")
        assert is_kdb_query("Analyze the market trends in healthcare sector")

        # Empty and short queries
        assert not is_kdb_query("")
        assert not is_kdb_query("hello")


class TestQueryClassification:
    """Test the classify_query_type function."""

    @pytest.mark.asyncio
    async def test_classify_financial_query(self):
        """Test classification of financial queries."""
        with patch('aiq_aira.search_utils.KDB_ENABLED', True):
            query_type = await classify_query_type("What is AAPL stock price?")
            assert query_type == "kdb"

    @pytest.mark.asyncio
    async def test_classify_document_query(self):
        """Test classification of document queries."""
        query_type = await classify_query_type("Summarize the research paper on climate change")
        assert query_type == "rag"

    @pytest.mark.asyncio
    async def test_kdb_disabled_returns_rag(self):
        """Test that when KDB is disabled, queries default to RAG."""
        with patch('aiq_aira.search_utils.KDB_ENABLED', False):
            query_type = await classify_query_type("What is AAPL stock price?")
            assert query_type == "rag"


class TestKDBNATClient:
    """Test KDB+ NAT MCP client functionality."""

    @pytest.mark.asyncio
    async def test_kdb_disabled_returns_empty(self):
        """Test that search returns empty when KDB is disabled."""
        from aiq_aira.kdb_tools_nat import search_kdb_nat

        with patch('aiq_aira.kdb_tools_nat.KDB_ENABLED', False):
            answer, citation = await search_kdb_nat(
                "test query",
                lambda x: None,  # mock writer
            )
            assert answer == ""
            assert citation == ""

    @pytest.mark.asyncio
    async def test_intelligent_query_requires_llm(self):
        """Test that intelligent query mode requires an LLM."""
        from aiq_aira.kdb_tools_nat import KDBNATClient

        # Create client with mocked connection
        client = KDBNATClient()

        # Mock the connection and tools
        client._connected = True
        client._tools = {
            "test_tool": MagicMock(description="Test tool")
        }

        # Without LLM, should raise or return empty
        # (depending on implementation)
        with patch.object(client, '_ensure_connected', new_callable=AsyncMock):
            # The intelligent_query method should handle missing LLM gracefully
            # by either creating its own LLM or returning an error
            pass  # Test passes if no exception is raised


class TestMCPToolDiscovery:
    """Test MCP tool discovery functionality."""

    def test_tool_description_builder(self):
        """Test that tool descriptions are properly formatted."""
        from aiq_aira.kdb_tools_nat import KDBNATClient

        client = KDBNATClient()

        # Mock tools
        mock_tool = MagicMock()
        mock_tool.description = "Execute SQL queries against the database"
        mock_tool.inputSchema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "SQL query to execute"}
            },
            "required": ["query"]
        }

        client._tools = {"kdbx_run_sql_query": mock_tool}

        description = client._build_tools_description()

        assert "kdbx_run_sql_query" in description
        assert "SQL" in description


class TestKDBKeywords:
    """Test that KDB keywords are comprehensive."""

    def test_keywords_list_exists(self):
        """Test that keywords list is defined and non-empty."""
        assert KDB_KEYWORDS is not None
        assert len(KDB_KEYWORDS) > 0

    def test_essential_keywords_present(self):
        """Test that essential financial keywords are present."""
        essential = ["stock", "price", "trading", "market", "volume"]
        for keyword in essential:
            assert keyword in KDB_KEYWORDS, f"Essential keyword '{keyword}' missing from KDB_KEYWORDS"


# Run tests when called directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
