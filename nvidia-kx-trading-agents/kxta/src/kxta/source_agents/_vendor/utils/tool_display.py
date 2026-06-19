# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Vendored into the KXTA source-agents layer from the KX "agentic-anomaly-market-research" project
# (faithful copy; imports rewritten and heavy imports made lazy -- no logic changes).
"""
Tool display name mapping for SSE events.

This module provides a centralized registry of tool display names and a helper
function to look them up. Display names are user-friendly labels shown in SSE
events instead of technical tool identifiers.
"""

from typing import Dict

# Canonical display names for all tools
# Maps technical tool name -> user-friendly display name
TOOL_DISPLAY_NAMES: Dict[str, str] = {
    # Market data & news tools
    "get_news_tool": "Fetch News",
    "get_quote_tool": "Fetch Quote",

  # Technical indicators tools
    "get_stock_data_tool": "Fetch Stock Data",
    "get_indicators_tool": "Calculate Indicators",

  # Reddit tools
    "search_reddit_tool": "Search Reddit",
    "get_reddit_submission_details_tool": "Fetch Reddit Post Details",

  # X (Twitter) tools
    "search_x_tool": "Search X",
    "get_x_user_posts_tool": "Fetch X User Posts",
    "get_x_tweet_details_tool": "Fetch X Tweet Details",

  # Fundamental tools
    "get_company_overview_tool": "Fetch Company Overview",
    "get_financial_statements_tool": "Fetch Financial Statements",
    "get_valuation_ratios_tool": "Fetch Valuation Ratios",
    "get_earnings_data_tool": "Fetch Earnings Data",
    "get_dividend_data_tool": "Fetch Dividend Data",
    "get_analyst_ratings_tool": "Fetch Analyst Ratings",

  # Web search tools (Firecrawl MCP)
    "firecrawl_search": "Search Web",
    "firecrawl_scrape": "Scrape Page",
    "firecrawl_crawl": "Crawl Site",
    "firecrawl_map": "Map Site",

  # Google search tools
    "google_search": "Search Google",
    "google_search_tool": "Search Google",

  # KDB-X tools
    "kdbx_run_sql_query": "Run SQL Query KDB-X",
    "kdbx_sim_search": "Similarity Search KDB-X",

  # OneTick MCP tools
    "get_market_data": "Fetch Market Data",
    "analyze_market_data": "Analyze Market Data",
    "get_technical_indicators": "Calculate Indicators",
}


def get_tool_display_name(tool_name: str) -> str:
    """
    Get the user-friendly display name for a tool.
    
    Args:
        tool_name: Technical tool name (e.g., 'get_quote_tool')
        
    Returns:
        User-friendly display name (e.g., 'Fetch Quote').
        Falls back to the tool_name if no mapping exists.
    """
    return TOOL_DISPLAY_NAMES.get(tool_name, tool_name)
