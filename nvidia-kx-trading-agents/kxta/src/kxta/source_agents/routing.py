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
"""Per-query source selection.

Heuristic-first: a source is chosen when any of its keywords appear in the query.
RAG (the source whose keywords list is empty) is always kept as the default floor,
so a query never resolves to zero sources. The llm parameter is reserved for an
LLM tiebreak in a later plan; the foundation does not call it.
"""

from __future__ import annotations

import logging

from kxta.source_agents.base import SourceAgent

logger = logging.getLogger(__name__)


def _matches(query_lower: str, source: SourceAgent) -> bool:
    return any(kw in query_lower for kw in getattr(source, "keywords", []))


# Failure-aware rerouting: when a source returns nothing usable for a query, the
# next-best sources to try, in preference order. Only registry sources belong here
# (the legacy Tavily fallback is handled separately by process_single_query).
FALLBACK_CHAINS: dict[str, list[str]] = {
    "kdb": ["onetick", "market_data", "web_search"],
    "onetick": ["kdb", "market_data", "web_search"],
    "market_data": ["kdb", "onetick", "web_search"],
    "fundamentals": ["market_data", "sec_filings", "web_search"],
    "news_headlines": ["web_search"],
    "sec_filings": ["web_search"],
    "macro_economic": ["web_search"],
    "web_search": [],
    "rag": [],
}


def fallback_sources(failed: list[str], enabled: list[SourceAgent], tried: set[str]) -> list[SourceAgent]:
    """Next-best sources to re-dispatch a query to after `failed` produced nothing usable.

    Walks each failed source's preference chain, keeping order, skipping anything
    already tried (or not enabled). Returns deduplicated SourceAgents.
    """
    by_name = {s.name: s for s in enabled}
    picked: list[SourceAgent] = []
    for name in failed:
        for candidate in FALLBACK_CHAINS.get(name, []):
            if candidate in tried or candidate not in by_name:
                continue
            if by_name[candidate] not in picked:
                picked.append(by_name[candidate])
    return picked


def select_sources(query: str, enabled: list[SourceAgent], llm=None, preferred: str | None = None) -> list[SourceAgent]:
    """Return the subset of `enabled` sources that should run for `query`.

    - When the planner tagged a query with a `preferred` source that is enabled, honor it
      (LLM-chosen routing) plus the RAG floor — the planner decided, so trust it.
    - Otherwise fall back to keyword routing:
        - Keyword match selects specialized sources.
        - Sources with no keywords (RAG) are always kept as the floor.
        - If nothing matched and no floor source exists, fall back to all enabled.

    `preferred` of "auto"/""/None, or a value not in `enabled`, defers to keyword routing.
    """
    if not enabled:
        return []

    floor = [s for s in enabled if not getattr(s, "keywords", [])]

    # LLM-chosen routing: honor a valid planner tag.
    pref = (preferred or "").strip().lower()
    if pref and pref != "auto":
        picked = next((s for s in enabled if s.name == pref), None)
        if picked is not None:
            chosen = [picked]
            for s in floor:
                if s not in chosen:
                    chosen.append(s)
            logger.info(f"select_sources (planner='{pref}') -> {[s.name for s in chosen]} for: {query[:50]}...")
            return chosen
        logger.info(f"select_sources: planner source '{pref}' not enabled; falling back to keywords")

    # Keyword routing fallback.
    query_lower = query.lower()
    matched = [s for s in enabled if _matches(query_lower, s)]

    chosen = list(matched)
    for s in floor:
        if s not in chosen:
            chosen.append(s)

    if not chosen:
        # safety net: every enabled source is specialized (no floor) and none matched
        chosen = list(enabled)

    logger.info(f"select_sources -> {[s.name for s in chosen]} for: {query[:50]}...")
    return chosen
