# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""News headlines source — relevant headlines + light analysis."""

from kxta.source_agents._vendor.agents.news_headlines_agent import create_news_headlines_agent_async
from kxta.source_agents.agent_base import AgentSource


class NewsHeadlinesSource(AgentSource):
    name = "news_headlines"
    label = "News Headlines"
    description = "Recent, relevant news headlines and their summarized analysis for a topic or ticker."
    keywords = ["news", "headline", "headlines", "announced", "press", "report", "latest", "story"]
    requires_env = ["ALPHAVANTAGE_API_KEY"]  # get_news_tool -> Alpha Vantage NEWS_SENTIMENT (raises without key)
    requires_modules = ["langchain_community"]  # MarketDataAndNewsTools lazily imports the Alpha Vantage wrapper

    async def _build_graph(self):
        return await create_news_headlines_agent_async()

    def _initial_state(self, query: str) -> dict:
        return {
            "research_query": query, "messages": [], "relevant_headlines": [], "next_step": "", "iteration_count": 0
        }
