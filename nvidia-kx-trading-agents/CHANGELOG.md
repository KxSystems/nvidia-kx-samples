# Change Log

Unreleased — AI Trading Agents (KX edition)
- Re-targeted the blueprint as **AI Trading Agents**: a multi-agent financial-research
  system over KDB-X market data and external market intelligence (derived from the
  NVIDIA AI-Q Research Assistant; see `NOTICE` and `docs/whats-different-from-aiq.md`)
- Added an **11-source agent registry** with per-query routing (planner tag → keyword →
  semantic similarity), a relevancy gate, failure-aware rerouting, and a reflection digest
- **KDB-X as one engine, three agents**: `kdb` (time-series SQL via MCP), `kdb_docs`
  (GPU vector search over documents), `kdb_pit` (point-in-time as-of joins)
- Added external source agents: `market_data`, `news_headlines`, `fundamentals`,
  `sec_filings` (SEC EDGAR), `macro_economic` (FRED), `web_search` (Firecrawl/Tavily),
  and `onetick` (OneTick Cloud)
- **Optional, enhance-when-present NIMs**: NeMo Retriever reranker (relevancy gate) and
  embedding (semantic routing/dedup + `kdb_docs`), a small summarization NIM, and
  NemoGuard content-safety input rail
- In-app **agent picker** with inline data selection, persisted via new endpoints:
  `GET /source_agents`, `GET/PUT /settings/kdb-docs`, `GET/PUT /settings/kdb-tables`
- **SEC filings ingestion** into per-ticker RAG collections via nv-ingest
  (`POST /sec/ingest`, `GET /sec/collections`)
- **KDB-X chat + historical-data loader** (`/kdb/chat`, `/kdb/load-historical`,
  `/kdb/jobs`, …) with an always-on SQL execution rail
- **Self-hosted vs. cloud NIMs in all deployment modes** — switchable via
  `INSTRUCT_BASE_URL`/`NEMOTRON_BASE_URL`; added an optional `nim-llm-nemotron` Helm
  subchart to self-host Nemotron in-chart
- **Standalone (no-RAG) support** — the `rag` agent is reachability-gated, so the
  blueprint runs as KDB-X + external agents + the two LLMs without the RAG blueprint
- Backend hardening: HPA/PDB, client-disconnect cancellation, context-truncation guard,
  KDB chat/agent scoped to KXTA-owned tables
- Documentation overhaul (README, architecture/sequence diagrams, REST API reference,
  configuration reference, troubleshooting, deployment guides)

Release v1.2.0
- Added support for Helm deployments
- Add support and documentation for evaluation
- Simplified the configuration and integration with RAG, removing nginx
- Adopted RAG 2.3.0
- Tested for compatability with RTX Pro 6000

Release v1.1.0 
- Tested for compatability with RAG 2.2.0 release and B200
- Adds support for NVIDIA Workbench

Release v1.0.0

Initial release of the NVIDIA AI-Q Research Assistant Blueprint featuring:
- Multi-modal PDF document upload and processing, compatible with the NVIDIA RAG 2.1 blueprint release
- Demo web application
- Deep research report writing including human-in-the-loop feedback
