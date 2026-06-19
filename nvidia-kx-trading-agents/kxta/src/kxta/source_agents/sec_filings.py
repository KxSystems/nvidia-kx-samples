# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""SEC EDGAR primary-filings source (10-K / 10-Q / 8-K) via vendored edgartools @tools."""

from kxta.source_agents.agent_base import AgentSource
from kxta.source_agents.tool_agent import ToolAgentSource


def _load_tools() -> list:
    from kxta.source_agents._vendor.tools.sec_filings import get_sec_filing
    from kxta.source_agents._vendor.tools.sec_filings import get_sec_filing_section
    from kxta.source_agents._vendor.tools.sec_filings import list_sec_filings
    return [list_sec_filings, get_sec_filing, get_sec_filing_section]


_SYSTEM_PROMPT = ("You are a research assistant with access to SEC EDGAR filings. "
                  "Find the relevant company by ticker, list filings if needed, then read the most relevant "
                  "10-K/10-Q/8-K or a specific section (e.g. Item 1A Risk Factors, Item 7 MD&A) to answer the "
                  "question. Cite the filing type and date. Use only what the filings say.")


class SecFilingsSource(ToolAgentSource, AgentSource):
    name = "sec_filings"
    label = "SEC Filings"
    description = "Primary SEC EDGAR filings (10-K, 10-Q, 8-K) — risk factors, MD&A, financial statements."
    keywords = [
        "sec",
        "filing",
        "filings",
        "10-k",
        "10-q",
        "8-k",
        "risk factors",
        "md&a",
        "annual report",
        "quarterly report",
        "edgar"
    ]
    requires_env = []  # SEC_EDGAR_EMAIL has a default identity
    requires_modules = ["edgar"]  # edgartools provides the `edgar` package
    system_prompt = _SYSTEM_PROMPT
    max_iterations = 4

    @property
    def tools(self) -> list:
        return _load_tools()
