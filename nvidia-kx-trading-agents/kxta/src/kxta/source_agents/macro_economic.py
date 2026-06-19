# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Macroeconomic data source (FRED) via vendored fredapi @tools."""

from kxta.source_agents.agent_base import AgentSource
from kxta.source_agents.tool_agent import ToolAgentSource


def _load_tools() -> list:
    from kxta.source_agents._vendor.tools.fred_economy import get_fred_series
    from kxta.source_agents._vendor.tools.fred_economy import get_fred_series_info
    from kxta.source_agents._vendor.tools.fred_economy import search_fred_series
    return [search_fred_series, get_fred_series, get_fred_series_info]


_SYSTEM_PROMPT = ("You are a research assistant with access to FRED economic data. Search for the right "
                  "series id, then fetch its observations (and metadata if useful) to answer the question. "
                  "Report concrete dated values and the series used. Use only FRED data.")


class MacroEconomicSource(ToolAgentSource, AgentSource):
    name = "macro_economic"
    label = "Macroeconomic Data (FRED)"
    description = "U.S./global macro indicators from FRED — CPI/inflation, unemployment, GDP, rates."
    keywords = [
        "inflation",
        "cpi",
        "gdp",
        "unemployment",
        "interest rate",
        "fed funds",
        "macro",
        "economic",
        "treasury",
        "yield",
        "recession",
        "fred"
    ]
    requires_env = ["FRED_API_KEY"]
    requires_modules = ["fredapi"]
    system_prompt = _SYSTEM_PROMPT
    max_iterations = 4

    @property
    def tools(self) -> list:
        return _load_tools()
