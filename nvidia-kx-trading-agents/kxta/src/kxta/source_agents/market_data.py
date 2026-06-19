# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Market data source — quotes + technical indicators (yfinance / Alpha Vantage)."""

from kxta.source_agents._vendor.agents.market_data_agent import create_market_data_agent_async
from kxta.source_agents.agent_base import AgentSource


class MarketDataSource(AgentSource):
    name = "market_data"
    label = "Market Data"
    description = "Live and historical quotes, volume, and technical indicators for tickers."
    keywords = [
        "price",
        "stock",
        "ticker",
        "volume",
        "ohlc",
        "moving average",
        "volatility",
        "returns",
        "market",
        "trading",
        "shares"
    ]
    # The market tools use Alpha Vantage as the primary data source (yfinance is only a
    # fallback for some asset types), so the key is genuinely required, not optional.
    requires_env = ["ALPHAVANTAGE_API_KEY"]
    requires_modules = ["yfinance"]

    async def _build_graph(self):
        return await create_market_data_agent_async()

    def _initial_state(self, query: str) -> dict:
        return {
            "research_query": query,
            "messages": [],
            "market_details": [],
            "summaries": {},
            "next_step": "",
            "iteration_count": 0
        }
