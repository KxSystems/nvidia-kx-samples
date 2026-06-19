# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Company fundamentals source — financials, ratios, valuation (yfinance / Alpha Vantage)."""

from kxta.source_agents._vendor.agents.fundamentals_agent import create_fundamentals_agent_async
from kxta.source_agents.agent_base import AgentSource


class FundamentalsSource(AgentSource):
    name = "fundamentals"
    label = "Company Fundamentals"
    description = "Company financial statements, ratios, earnings and valuation metrics."
    keywords = [
        "earnings",
        "revenue",
        "valuation",
        "balance sheet",
        "income statement",
        "cash flow",
        "margin",
        "pe ratio",
        "eps",
        "dividend",
        "fundamentals"
    ]
    requires_env = []  # yfinance is keyless; Alpha Vantage key is optional fallback
    requires_modules = ["yfinance"]  # tool runtime imports yfinance for fundamentals data

    async def _build_graph(self):
        return await create_fundamentals_agent_async()

    def _initial_state(self, query: str) -> dict:
        return {
            "research_query": query,
            "messages": [],
            "fundamental_data": [],
            "summaries": {},
            "next_step": "",
            "iteration_count": 0
        }
