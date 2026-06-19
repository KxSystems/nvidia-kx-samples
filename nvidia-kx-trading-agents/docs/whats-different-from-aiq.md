# What's Different — AI Trading Agents vs. NVIDIA AI-Q Research Assistant

This blueprint is a modified derivative of the **NVIDIA AI-Q Research Assistant**
blueprint (Apache-2.0, see [`NOTICE`](../NOTICE)). It keeps AI-Q's three-stage
research workflow (plan → research → synthesize/reflect) and re-targets it for
**financial research and trading decision support**, adding a multi-source agent
layer over real-time and historical market data.

## Summary

| Capability | AI-Q (upstream) | Trading Agents Blueprint |
|---|---|---|
| Data sources | RAG documents + web search (+ KDB in the KX edition) | Pluggable **11-source registry**: KDB-X (time-series / documents / point-in-time), OneTick, market data, news/sentiment, SEC filings, fundamentals, macro, web, RAG |
| Per-query routing | Single retrieval path | Source-aware planning + **routing** (planner tag → keyword → semantic) to the best-fit source agent, with **reroute on relevancy miss** |
| Relevancy gate | LLM-as-judge | NeMo Retriever **reranker NIM** when present, else LLM judge |
| Execution | Sequential-ish retrieval | Sources and queries run **in parallel** |
| Market data | — | **KDB-X** — one engine for tick data **and** document vectors (via MCP + GPU vector search) |
| Optional NIMs | — | **Enhance-when-present**: reranker, embedding (routing/dedup), summarization, NemoGuard content-safety |
| Domain framing | General deep research | **Trading insights & decision support** |
| Activity view | Linear progress | **Convergent fan-in** agent-activity tree |

## What this blueprint adds

1. **KDB-X as a first-class source — one engine, three agents.** The same KDB-X
   instance holds tick data *and* RAG document vectors and backs three agents:
   - `kdb` — time-series SQL over prices/volumes via the **MCP** server
   - `kdb_docs` — **GPU vector search** (cuVS/CAGRA) over documents/filings ingested into KDB-X
   - `kdb_pit` — **point-in-time as-of joins** matching each trade to the prevailing quote

2. **A pluggable N-source agent registry**
   (`kxta/src/kxta/source_agents/`) that generalizes AI-Q's fixed RAG/KDB
   retrieval branch into an arbitrary set of data-source agents, each gated by
   availability (module / API key / service reachability) and surfaced via the
   `GET /source_agents` endpoint.

3. **External data-source agents** (adapted from KX internal projects —
   see [`NOTICE`](../NOTICE)):
   - `market_data` — live/historical quotes, OHLCV, technical indicators
   - `news_headlines` — recent news headlines and sentiment
   - `fundamentals` — income statement, balance sheet, cash flow, valuation
   - `web_search` — deep web research and article extraction (Firecrawl, Tavily fallback)
   - `sec_filings` — 10-K/10-Q/8-K risk factors, MD&A (SEC EDGAR)
   - `macro_economic` — GDP, CPI, rates, unemployment (FRED)
   - `onetick` — OneTick Cloud tick history (OAuth2)

   With the three KDB-X agents and the upstream `rag` agent, the registry exposes
   **11 source agents** in total (plus a synthetic `web` fallback).

4. **Source-aware planning + routing** — the Nemotron planner is told which
   sources are enabled and available and tags each query with the best-fit
   source; the router honors that tag, falling back to keyword then **semantic
   similarity** (embedding NIM) for `auto`. On a relevancy miss the orchestrator
   **reroutes** to up to two fallback sources, and finally a web search.

5. **Relevancy gate + reflection** — results are scored by a **NeMo Retriever
   reranker NIM** when configured (else an LLM judge); a supervisor digests the
   findings and re-queries to fill gaps before the report is written.

6. **Enhance-when-present NIMs** — optional reranker, embedding (routing/dedup),
   summarization, and NemoGuard content-safety microservices activate
   automatically when configured and fall back gracefully when absent.

7. **Parallel execution** — queries fan out concurrently, and the sources
   chosen for each query run concurrently, then converge into a
   synthesis-and-reflection loop that produces a citation-backed report.

8. **Trading-oriented UI** — a convergent (fan-in) **Agent Activity** view that
   shows each source agent's live steps branching into synthesis → final report,
   plus an in-app **agent picker** with inline data selection (RAG collection,
   KDB-X document collection, KDB-X tables).

## What stays the same (and why)

This is a **soft fork** of the KX `kx-nvidia-aiq` base, kept syncable with it.
The additions are deliberately **isolated** — the `source_agents/` package plus
thin hooks in `nodes.py`, `schema.py`, and `prompts.py` — so upstream fixes
(deployment, KDB-X, core workflow) can still be merged in. The core AI-Q
package name (`kxta`), API endpoints, and three-stage workflow are
unchanged to keep that merge path clean.

## Where to look

| Area | Path |
|---|---|
| Source registry + routing | `kxta/src/kxta/source_agents/` |
| Source-aware planning | `kxta/src/kxta/nodes.py` (`generate_query`), `prompts.py` |
| Per-query routing | `kxta/src/kxta/source_agents/routing.py`, `search_utils.py` |
| Availability endpoint | `GET /source_agents` |
| Data-selection settings | `GET/PUT /settings/kdb-docs`, `GET/PUT /settings/kdb-tables` |
| KDB-X document agent | `kxta/src/kxta/kdb_vector.py`, [`docs/kdb-docs-agent.md`](kdb-docs-agent.md) |
| Activity UI + agent picker | `frontend/src/components/report/AgentActivity.tsx`, `frontend/src/components/sources/SourceSelector.tsx` |
