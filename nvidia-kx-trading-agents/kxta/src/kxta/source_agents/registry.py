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
"""Registry of available research sources, plus the built-in RAG and KDB adapters."""

from __future__ import annotations

import logging
import os
import socket
import time
from urllib.parse import urlparse

import aiohttp
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from kxta.kdb_tools_nat import KDB_ENABLED
from kxta.kdb_tools_nat import KDB_KEYWORDS
from kxta.kdb_tools_nat import _mcp_available
from kxta.kdb_tools_nat import search_kdb_nat_with_fallback
from kxta.source_agents.base import SourceAgent
from kxta.source_agents.base import SourceResult
from kxta.source_agents.fundamentals import FundamentalsSource
from kxta.source_agents.macro_economic import MacroEconomicSource
from kxta.source_agents.market_data import MarketDataSource
from kxta.source_agents.news_headlines import NewsHeadlinesSource
from kxta.source_agents.onetick import OneTickSource
from kxta.source_agents.sec_filings import SecFilingsSource
from kxta.source_agents.web_search import WebSearchSource
from kxta.tools import search_rag

logger = logging.getLogger(__name__)


def _kdb_available() -> bool:
    """True when the MCP package is importable (mcp package from NAT 1.3.0+).

    Whether KDB is *switched on* for a request is gated separately in enabled_sources
    (via use_kdb / KDB_ENABLED)."""
    return bool(_mcp_available)


_rag_probe_cache = {"ts": 0.0, "ok": None}


def _rag_reachable(ttl: float = 30.0) -> bool:
    """Fast, cached TCP reachability probe of RAG_SERVER_URL.

    Returns True only if a RAG server is actually deployed/reachable, so the UI can
    show RAG as 'not deployed' instead of falsely advertising it as available.
    Cached for `ttl` seconds to avoid probing on every /source_agents hit.
    """
    import time as _t
    now = _t.monotonic()
    if _rag_probe_cache["ok"] is not None and (now - _rag_probe_cache["ts"]) < ttl:
        return _rag_probe_cache["ok"]
    url = os.getenv("RAG_SERVER_URL", "")
    ok = False
    if url:
        try:
            parsed = urlparse(url if "://" in url else "http://" + url)
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if host:
                with socket.create_connection((host, port), timeout=1.0):
                    ok = True
        except Exception:
            ok = False
    _rag_probe_cache.update(ts=now, ok=ok)
    return ok


class RagSource:
    name = "rag"
    label = "Documents (RAG)"
    description = "Unstructured document retrieval from the selected RAG collection."
    keywords: list[str] = []  # RAG is the default floor; routing always allows it
    unavailable_reason = "RAG not deployed (RAG_SERVER_URL unreachable)"

    def is_available(self) -> bool:
        # RAG is only 'available' when a RAG server is actually reachable.
        return _rag_reachable()

    async def run(self, query: str, config: RunnableConfig, writer: StreamWriter) -> SourceResult:
        rag_url = config["configurable"].get("rag_url")
        collection = config["configurable"].get("collection")
        start = time.time()
        try:
            async with aiohttp.ClientSession() as session:
                answer, citation, doc_count = await search_rag(session, rag_url, query, writer, collection)
            return SourceResult(source="rag",
                                content=answer or "",
                                citation=citation or "",
                                record_count=doc_count,
                                duration_seconds=time.time() - start)
        except Exception as e:
            logger.error(f"RAG source failed: {e}")
            return SourceResult(source="rag", content="", citation="", duration_seconds=time.time() - start)


class KdbSource:
    name = "kdb"
    label = "Financial Data (KDB+)"
    description = "Quantitative financial / time-series queries against KDB+ (prices, volumes, indicators)."
    keywords = list(KDB_KEYWORDS)

    def is_available(self) -> bool:
        return _kdb_available()

    async def run(self, query: str, config: RunnableConfig, writer: StreamWriter) -> SourceResult:
        start = time.time()
        try:
            answer, citation, record_count = await search_kdb_nat_with_fallback(query, writer, None)
            return SourceResult(source="kdb",
                                content=answer or "",
                                citation=citation or "",
                                record_count=record_count,
                                duration_seconds=time.time() - start)
        except Exception as e:
            logger.error(f"KDB source failed: {e}")
            return SourceResult(source="kdb", content="", citation="", duration_seconds=time.time() - start)


class KdbDocsSource:
    """Unstructured retrieval from documents stored as vectors in KDB-X (roadmap #1).

    Complements RagSource: where RAG hits the blueprint's RAG server, this searches
    filings/documents embedded directly in KDB-X via in-engine vector search — the
    same engine that holds the structured market data. Available only when a KDB-X
    vector table is configured (KDB_DB_HOST + a selected collection)."""

    name = "kdb_docs"
    label = "Documents (KDB-X)"
    description = ("Semantic search over filings/documents stored as vectors in KDB-X "
                   "(qualitative context: risk factors, MD&A, disclosures).")
    keywords = [
        "filing", "filings", "10-k", "10-q", "risk factor", "risk factors", "md&a",
        "disclosure", "disclosed", "management discussion", "annual report", "prospectus",
        "qualitative", "what does the filing", "according to the filing"
    ]

    def is_available(self) -> bool:
        from kxta.kdb_docs_settings import get_selected_collection
        from kxta.kdb_vector import embedding_configured
        return (bool(os.getenv("KDB_DB_HOST", "").strip())
                and bool(get_selected_collection())
                and embedding_configured())

    @property
    def unavailable_reason(self) -> str:
        if not os.getenv("KDB_DB_HOST", "").strip():
            return "KDB-X not configured (KDB_DB_HOST not set)"
        from kxta.kdb_docs_settings import get_selected_collection
        if not get_selected_collection():
            return ("no KDB-X document collection selected — choose one in "
                    "Settings → KDB-X Document Search")
        from kxta.kdb_vector import embedding_configured
        if not embedding_configured():
            return ("no embedding endpoint configured — set EMBEDDING_NIM_URL "
                    "(or NVIDIA_API_KEY for the hosted embedder)")
        return ""

    async def run(self, query: str, config: RunnableConfig, writer: StreamWriter) -> SourceResult:
        from kxta.kdb_vector import kdb_vector_search
        from kxta.kdb_docs_settings import get_selected_collection
        start = time.time()
        # Emit a progress event so this agent gets a visible lane in the report's
        # activity feed (the orchestrator only emits the *_answer completion event).
        writer({"kdb_docs_progress": f"Vector-searching KDB-X filings for: {query[:80]}"})
        try:
            table = config["configurable"].get("kdb_vector_table") or get_selected_collection()
            res = await kdb_vector_search(query, n=6, table=table)
            rows = res.get("rows") or []
            if res.get("isError") or not rows:
                return SourceResult(source="kdb_docs", content="", citation="",
                                    duration_seconds=time.time() - start)
            content = "\n\n".join(f"[{i + 1}] {r['text']}" for i, r in enumerate(rows))
            # One clean citation line (the report renders citations as a numbered list,
            # so keep it to a single line — no per-chunk cosine noise).
            citation = f"KDB-X semantic (vector) search over indexed filings — {len(rows)} relevant passages retrieved."
            return SourceResult(source="kdb_docs", content=content, citation=citation,
                                record_count=len(rows), duration_seconds=time.time() - start)
        except Exception as e:
            logger.error(f"KDB docs source failed: {e}")
            return SourceResult(source="kdb_docs", content="", citation="",
                                duration_seconds=time.time() - start)


# Cheap TTL-cached check that kdb_pit's tick tables are actually populated.
# is_available() is called frequently (/source_agents, enabled_sources), so we
# probe KDB-X at most once per _PIT_PROBE_TTL seconds and cache the verdict.
_PIT_PROBE = {"ts": 0.0, "ok": False}
_PIT_PROBE_TTL = 30.0


def _pit_tick_data_present() -> bool:
    """True when both trade and quote exist with rows > 0 (TTL-cached)."""
    now = time.monotonic()
    if (now - _PIT_PROBE["ts"]) < _PIT_PROBE_TTL:
        return _PIT_PROBE["ok"]
    ok = False
    try:
        from kxta.kdb_direct_write import _table_counts_sync
        counts = _table_counts_sync(["trade", "quote"])
        ok = bool((counts.get("trade") or 0) > 0 and (counts.get("quote") or 0) > 0)
    except Exception:  # noqa: BLE001  (KDB-X unreachable -> treat as not ready)
        ok = False
    _PIT_PROBE["ts"] = now
    _PIT_PROBE["ok"] = ok
    return ok


class KdbPitSource:
    """Point-in-time market microstructure via KDB-X as-of joins (roadmap #4).

    Joins each trade to the quote PREVAILING at its timestamp (`aj[`sym`time;trade;quote]`)
    — no lookahead bias. Surfaces execution-vs-quote / spread context that plain SQL can't
    express. Available only when both trade and quote tick tables exist with rows > 0."""

    name = "kdb_pit"
    label = "Point-in-Time Market (KDB-X aj)"
    description = ("Point-in-time trade/quote analysis via KDB-X as-of joins: each trade matched "
                   "to the prevailing quote (bid/ask/spread) with no lookahead bias.")
    keywords = [
        "trade", "quote", "bid", "ask", "spread", "prevailing", "point-in-time", "point in time",
        "as-of", "as of", "microstructure", "execution", "slippage", "at the time", "nbbo", "tick"
    ]

    def is_available(self) -> bool:
        if not os.getenv("KDB_DB_HOST", "").strip():
            return False
        return _pit_tick_data_present()

    @property
    def unavailable_reason(self) -> str:
        if not os.getenv("KDB_DB_HOST", "").strip():
            return "KDB-X not configured (KDB_DB_HOST not set)"
        return "no trade/quote tick data loaded — load it via KDB-X → Load Data"

    async def run(self, query: str, config: RunnableConfig, writer: StreamWriter) -> SourceResult:
        import re as _re

        from kxta.kdb_direct_write import kdb_asof_join
        start = time.time()
        writer({"kdb_pit_progress": "Point-in-time as-of join: matching trades to prevailing quotes..."})
        try:
            res = await kdb_asof_join("trade", "quote", ("sym", "time"), n=2000)
            rows = res.get("rows") or []
            if res.get("isError") or not rows:
                return SourceResult(source="kdb_pit", content="", citation="",
                                    duration_seconds=time.time() - start)
            present = {str(r.get("sym")) for r in rows}
            wanted = {t for t in _re.findall(r"[A-Z]{1,5}", query or "") if t in present}
            sel = [r for r in rows if (not wanted) or str(r.get("sym")) in wanted]
            by_sym: dict[str, list] = {}
            for r in sel:
                by_sym.setdefault(str(r.get("sym")), []).append(r)
            lines = []
            for sym, rs in by_sym.items():
                spreads = [float(r["ask"]) - float(r["bid"]) for r in rs
                           if r.get("ask") is not None and r.get("bid") is not None]
                avg_spread = (sum(spreads) / len(spreads)) if spreads else 0.0
                ex = rs[-1]
                lines.append(
                    f"{sym}: {len(rs)} trades matched to the prevailing quote (point-in-time, no "
                    f"lookahead via KDB-X aj). Avg quoted spread {avg_spread:.3f}. "
                    f"Example trade price {ex.get('price')} vs prevailing bid "
                    f"{float(ex.get('bid', 0)):.2f} / ask {float(ex.get('ask', 0)):.2f}.")
            content = "\n".join(lines)
            citation = (f"KDB-X point-in-time as-of join (trade vs prevailing quote) — "
                        f"{len(sel)} trades matched to the prevailing quote, no lookahead.")
            return SourceResult(source="kdb_pit", content=content, citation=citation,
                                record_count=len(sel), duration_seconds=time.time() - start)
        except Exception as e:
            logger.error(f"KDB point-in-time source failed: {e}")
            return SourceResult(source="kdb_pit", content="", citation="",
                                duration_seconds=time.time() - start)


class SourceRegistry:
    """Holds all known sources; resolves which are enabled for a given request config."""

    def __init__(self, sources: list[SourceAgent] | None = None):
        self._sources: list[SourceAgent] = sources if sources is not None else [
            RagSource(),
            KdbSource(),
            KdbDocsSource(),
            KdbPitSource(),
            OneTickSource(),
            WebSearchSource(),
            MarketDataSource(),
            NewsHeadlinesSource(),
            FundamentalsSource(),
            SecFilingsSource(),
            MacroEconomicSource(),
        ]

    def all_sources(self) -> list[SourceAgent]:
        return list(self._sources)

    def _state_of(self, source) -> dict:
        """Compute availability state for a source (handles AgentSource-style + simple sources)."""
        import importlib.util
        import os

        requires_modules = getattr(source, "requires_modules", []) or []
        requires_env = getattr(source, "requires_env", []) or []

        missing_module = next((m for m in requires_modules if importlib.util.find_spec(m) is None), None)
        if missing_module:
            return {"state": "unavailable", "missing_key": None, "reason": f"module '{missing_module}' not installed"}

        missing_key = next((e for e in requires_env if not os.getenv(e)), None)
        if missing_key:
            return {
                "state": "needs_key",
                "missing_key": missing_key,
                "reason": f"environment variable {missing_key} not set"
            }

        # Sources without requires_* (rag/kdb) fall back to is_available().
        if not requires_modules and not requires_env:
            ok = source.is_available()
            reason = "" if ok else getattr(source, "unavailable_reason", "source reports unavailable")
            return {"state": "available" if ok else "unavailable", "missing_key": None, "reason": reason}

        return {"state": "available", "missing_key": None, "reason": ""}

    def describe_sources(self) -> list[dict]:
        """List every source with UI-facing availability metadata."""
        out = []
        for s in self._sources:
            entry = {"name": s.name, "label": getattr(s, "label", s.name), "description": getattr(s, "description", "")}
            entry.update(self._state_of(s))
            out.append(entry)

        # Synthetic entry for the legacy Tavily web-search fallback (the search_web flag).
        # It is not a registry routing source, but it should appear in the UI with honest
        # key availability instead of always looking 'available'.
        tavily_ok = bool(os.getenv("TAVILY_API_KEY"))
        out.append({
            "name": "web",
            "label": "Web Search (Tavily)",
            "description": "Quick web-search fallback via Tavily.",
            "state": "available" if tavily_ok else "needs_key",
            "missing_key": None if tavily_ok else "TAVILY_API_KEY",
            "reason": "" if tavily_ok else "environment variable TAVILY_API_KEY not set",
        })
        return out

    def _is_selected(self, source, configurable: dict) -> bool:
        """Whether a source is switched on for this request (ignores collection presence).

        Used by the planner description, which runs in Stage 1 before a collection is
        bound — so unlike enabled_sources it must not gate RAG on a collection.
        """
        if source.name == "rag":
            return bool(configurable.get("use_rag", True))
        if source.name == "kdb":
            use_kdb = configurable.get("use_kdb", None)
            return (use_kdb is True) or (use_kdb is None and KDB_ENABLED)
        return bool(configurable.get(f"use_{source.name}", False))

    def describe_for_planner(self, configurable: dict) -> str:
        """Build the 'Available Data Sources' prompt section for the query planner.

        Lists every source that is BOTH selected for this request AND currently usable
        (module present, key present, service reachable), each tagged with its canonical
        `source` id so the planner can reference it when routing queries. Sources the user
        toggled on but can't actually run (missing key / unreachable) are intentionally
        omitted — the planner should not plan around a source that will fail.
        """
        # Per-source one-line "best for" hint shown to the planner, including what the
        # source can actually return (lookback/coverage limits) so the planner doesn't
        # write queries the source can't answer (e.g. "5 years of fundamentals" when
        # only the latest statements are served). Falls back to the source's own
        # description when a name isn't mapped here.
        hints = {
            "rag":
                "Qualitative analysis, background, research findings, expert commentary from the document "
                "collection. Returns only what has been ingested into the selected collection.",
            "kdb":
                "Quantitative time-series: intraday/historical prices, volumes, trades, computed indicators. "
                "Returns only tickers/date-ranges loaded into the database.",
            "kdb_docs":
                "Qualitative document search — filings, risk factors, MD&A, disclosures — via in-engine GPU "
                "vector search over the selected KDB-X collection (same corpus as `rag`, faster direct "
                "retrieval). One topic per query.",
            "kdb_pit":
                "Point-in-time / as-of joins over KDB-X tick data: align trades to the prevailing quote, "
                "spreads and execution context at a timestamp. Returns as-of-joined rows; needs tick tables "
                "loaded.",
            "market_data":
                "Live and historical quotes, OHLCV, technical indicators. Returns current quote plus recent "
                "history; one ticker per query.",
            "fundamentals":
                "Company financial statements: income statement, balance sheet, cash flow, valuation ratios. "
                "Returns the latest annual + recent quarterly figures and current ratios — not multi-year "
                "history; one ticker per query.",
            "sec_filings":
                "Regulatory filings (10-K/10-Q/8-K): risk factors, MD&A, segment and disclosure detail. "
                "Returns the most recent filings; one ticker per query.",
            "macro_economic":
                "Macro indicators: GDP, CPI/inflation, interest rates, unemployment, money supply (FRED), "
                "latest prints plus historical series.",
            "news_headlines":
                "Recent company/market news headlines and sentiment, roughly the last few weeks; one ticker "
                "or topic per query.",
            "onetick":
                "Tick-data history from OneTick Cloud: daily bars, period returns, volatility, volume "
                "statistics. Returns computed stats over a date window; one or more tickers per query.",
            "web_search":
                "Deep web research and page extraction for current events not in the documents.",
            "web":
                "Quick web-search fallback for current events and recent developments (Tavily).",
        }

        lines: list[str] = []
        ids: list[str] = []
        for s in self._sources:
            if not self._is_selected(s, configurable):
                continue
            if self._state_of(s).get("state") != "available":
                continue
            label = getattr(s, "label", s.name)
            hint = hints.get(s.name) or getattr(s, "description", "")
            lines.append(f"- `{s.name}` — **{label}**: {hint}")
            ids.append(s.name)

        # Synthetic Tavily fallback (the use_web flag), not a registry routing source.
        if configurable.get("use_web", False) and os.getenv("TAVILY_API_KEY"):
            lines.append(f"- `web` — **Web Search (Tavily)**: {hints['web']}")
            ids.append("web")

        if not lines:
            # Nothing selectable/usable — give the planner a neutral instruction rather than
            # advertising sources that will fail.
            return ("# Available Data Sources\n"
                    "No specialized data source is currently available; write general, "
                    "self-contained research queries, and set \"source\" to \"auto\".")

        # Constrain the planner to only the enabled + usable ids, so it never tags a query
        # with a source that cannot run.
        id_list = ", ".join(f"`{i}`" for i in ids)
        section = ("# Available Data Sources\n"
                   "The research agent can draw on the following sources. Each is identified by a "
                   "`source` id:\n" + "\n".join(lines))

        # Mechanical routing rules: (what the query needs, source ids in preference order).
        # Rendered only for ids that are enabled, so the reasoning model applies them as a
        # lookup instead of deliberating between near-miss sources on every query.
        routing_rules = [
            ("news sentiment, headlines, press coverage", ["news_headlines"]),
            ("financial statements, ratios, earnings, valuation", ["fundamentals"]),
            ("prices, volumes, returns, technical indicators", ["kdb", "market_data"]),
            ("point-in-time / as-of: trade vs prevailing quote, spread at a timestamp", ["kdb_pit"]),
            ("tick-data history, period returns/volatility stats", ["onetick", "kdb", "market_data"]),
            ("filings content, risk factors, MD&A, disclosures", ["kdb_docs", "sec_filings"]),
            ("macro prints: rates, CPI, GDP, unemployment", ["macro_economic"]),
            ("qualitative background from ingested documents", ["rag"]),
            ("current events / anything not covered above", ["web_search", "web"]),
        ]
        rule_lines = []
        for need, candidates in routing_rules:
            picks = [c for c in candidates if c in ids]
            if picks:
                arrow = f"`{picks[0]}`" + (f" (else `{picks[1]}`)" if len(picks) > 1 else "")
                rule_lines.append(f"- {need} → {arrow}")

        section += ("\n\n## Source-Routing Guidance\n"
                    "Apply these routing rules mechanically — match the query's need to a rule and take "
                    "that source; do NOT deliberate between sources:\n" + "\n".join(rule_lines) +
                    f"\n\nValid `source` ids are exactly this set: {id_list}. If no rule matches, set "
                    "\"source\" to \"auto\". Do not use any source id outside this set.")
        return section

    def enabled_sources(self, configurable: dict) -> list[SourceAgent]:
        """Sources that are available AND switched on for this request.

        Mirrors today's flags: use_rag (+ a non-empty collection) and use_kdb.
        use_kdb=None means legacy auto-detect: allowed when KDB_ENABLED env is set.
        """
        out: list[SourceAgent] = []
        use_rag = configurable.get("use_rag", True)
        use_kdb = configurable.get("use_kdb", None)
        collection = (configurable.get("collection") or "").strip()

        for s in self._sources:
            if s.name == "rag":
                if use_rag and collection and s.is_available():
                    out.append(s)
            elif s.name == "kdb":
                kdb_on = (use_kdb is True) or (use_kdb is None and KDB_ENABLED)
                if kdb_on and s.is_available():
                    out.append(s)
            else:
                if configurable.get(f"use_{s.name}", False) and s.is_available():
                    out.append(s)
        return out


_default_registry = SourceRegistry()


def get_registry() -> SourceRegistry:
    return _default_registry
