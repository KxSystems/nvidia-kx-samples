# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Vendored into the KXTA source-agents layer from the KX "agentic-anomaly-market-research" project
# (faithful copy; imports rewritten and heavy imports made lazy -- no logic changes).
"""
Base agent state and common utilities.
"""

from typing import TypedDict, Annotated, Sequence, List, Dict, Any
from langchain_core.messages import BaseMessage
import operator


class BaseAgentState(TypedDict):
    """Base state with common fields - all agents use messages."""
    messages: Annotated[Sequence[BaseMessage], operator.add]


class SocialMediaAgentState(BaseAgentState):
    """State for social media agent."""
    summary: str
    # Standardized output fields
    key_findings: List[str]
    data_summary: Dict[str, Any]
    sources: List[Dict[str, Any]]


class WebResearchState(BaseAgentState):
    """State for web search agent."""
    query: str
    findings: List[dict]
    iteration_count: int
    final_report: str
    # Standardized output fields
    key_findings: List[str]
    data_summary: Dict[str, Any]
    sources: List[Dict[str, Any]]


class NewsHeadlinesAgentState(BaseAgentState):
    """State for news headlines agent."""
    research_query: str
    relevant_headlines: list
    next_step: str
    iteration_count: int
    summary: str  # Final summary report
    # Standardized output fields
    key_findings: List[str]
    data_summary: Dict[str, Any]
    sources: List[Dict[str, Any]]


class MarketDataAgentState(BaseAgentState):
    """State for market data agent."""
    research_query: str
    market_details: list
    summaries: Dict[str, Any]  # Summarized findings: quote_summary, indicators_summary
    next_step: str
    iteration_count: int
    # Standardized output fields
    research_report: str
    key_findings: List[str]
    data_summary: Dict[str, Any]
    sources: List[Dict[str, Any]]


class QuantContextAgentState(TypedDict):
    """State for persona insights agent."""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    research_findings: Dict[str, Any]  # Input: raw market research findings
    persona_insights: Dict[str, Any]  # Output: persona-specific insights in JSON format
    ticker: str
    next_step: str


class FundamentalsAgentState(BaseAgentState):
    """State for fundamentals agent."""
    research_query: str
    fundamental_data: list
    summaries: Dict[str, Any]
    next_step: str
    iteration_count: int
    # Standardized output fields
    research_report: str
    key_findings: List[str]
    data_summary: Dict[str, Any]
    sources: List[Dict[str, Any]]


class OneTickAgentState(BaseAgentState):
    """State for OneTick tick data agent.

    Simplified state - no intermediate summarization, just messages and control flow.
    """
    research_query: str
    next_step: str
    iteration_count: int
    # Standardized output fields
    research_report: str
    key_findings: List[str]
    data_summary: Dict[str, Any]
    sources: List[Dict[str, Any]]
