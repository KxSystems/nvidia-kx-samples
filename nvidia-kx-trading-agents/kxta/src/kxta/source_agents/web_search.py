# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Web research source — wraps the borrowed multi-iteration web_search ReAct agent."""

from kxta.source_agents._vendor.agents.web_search_agent import create_web_search_agent_async
from kxta.source_agents.agent_base import AgentSource


class WebSearchSource(AgentSource):
    name = "web_search"
    label = "Deep Web Research (Firecrawl)"
    description = "Open-web research via multi-step search + article scraping (current events, general topics)."
    keywords = ["news", "latest", "recent", "current", "today", "announced", "report", "web"]
    requires_env = ["FIRECRAWL_API_KEY"]
    requires_modules = ["langchain_mcp_adapters"]

    async def _build_graph(self):
        return await create_web_search_agent_async()

    def _initial_state(self, query: str) -> dict:
        return {"query": query, "messages": [], "findings": [], "iteration_count": 0}
