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
"""Core data shapes for pluggable research data sources.

A SourceResult is the uniform unit every source produces. merge_source_results
combines N of them into the (content, citation) pair the report pipeline expects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from typing import Protocol
from typing import runtime_checkable

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

_EMPTY_RE = re.compile(
    r'\b(no data|no results|not found|no relevant|no information|unable to|error)\b',
    re.IGNORECASE,
)


@dataclass
class SourceResult:
    """Result from a single data source with metadata."""
    source: str  # 'kdb', 'rag', 'web', 'market_data', ...
    content: str
    citation: str
    is_relevant: bool = True
    record_count: Optional[int] = None
    duration_seconds: float = 0.0

    def is_empty(self) -> bool:
        """True when the result has no meaningful content."""
        if not self.content:
            return True
        return bool(_EMPTY_RE.search(self.content)) and len(self.content) < 200


@runtime_checkable
class SourceAgent(Protocol):
    """A pluggable research data source."""
    name: str
    label: str
    description: str
    keywords: list[str]

    def is_available(self) -> bool:
        ...

    async def run(self, query: str, config: RunnableConfig, writer: StreamWriter) -> SourceResult:
        ...


_SOURCE_LABELS = {
    "kdb": "Financial Data (KDB+)",
    "rag": "Document Analysis (RAG)",
    "web": "Web Search",
    "market_data": "Market Data",
    "news_headlines": "News Headlines",
    "fundamentals": "Company Fundamentals",
    "sec_filings": "SEC Filings",
    "macro_economic": "Macroeconomic Data (FRED)",
}


def _label_for(source: str) -> str:
    return _SOURCE_LABELS.get(source, source.replace("_", " ").title())


def merge_source_results(results: list[SourceResult], query: str) -> tuple[str, str]:
    """Merge N SourceResults into (content, citation).

    - A single relevant result is returned bare (no attribution header), matching
      the legacy single-source behavior.
    - 2+ relevant, non-empty results are concatenated with a per-source attribution header.
    - If none are relevant, fall back to the first result that has any content.
    - If nothing has content, return a neutral 'no information' message.
    """
    # `query` is reserved for future relevancy-ranking; unused at this stage.
    relevant = [r for r in results if r.is_relevant and not r.is_empty()]

    if len(relevant) == 1:
        r = relevant[0]
        return r.content, r.citation

    if relevant:
        content_parts = []
        citation_parts = []
        for r in relevant:
            content_parts.append(f"**{_label_for(r.source)}:**\n{r.content}")
            if r.citation:
                citation_parts.append(f"[{_label_for(r.source)} Source]\n{r.citation}")
        return "\n\n".join(content_parts), "\n\n".join(citation_parts)

    for r in results:
        if r.content:
            return r.content, (r.citation or "")

    return "No relevant information found from available sources.", ""
