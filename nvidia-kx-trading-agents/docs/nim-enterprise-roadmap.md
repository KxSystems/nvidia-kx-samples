# NIM / NVIDIA AI Enterprise Roadmap

Source: multi-agent + NVIDIA-stack audit (2026-06-10). Context: the blueprint's NVIDIA
coupling is deep for NAT / NIM serving / Nemotron, thin elsewhere. Every item below is
an incremental swap on a stack that already speaks NIM through NAT — low integration risk.

## Done (from the same audit)

- ✅ **Multi-agent maturity fixes** — failure-aware rerouting (`routing.FALLBACK_CHAINS`),
  cross-agent findings digest (`configurable.findings_digest`), supervisor mode on by
  default. The claim "multi-agent trading research system built on NVIDIA NIM and NeMo
  Agent Toolkit" is now defensible.
- ✅ **Single-Nemotron deployment profile** — `no_think_prefix()` injects reasoning-off on
  instruct-role paths; one NIM (49B) serves planner + writer + agents. Benchmarked:
  2m14s vs >9.7min with thinking on. Flip `INSTRUCT_MODEL_NAME` to the Nemotron model;
  no other config needed.
- ✅ **Relevancy fail-open fixed** — judge failures now pass results through flagged
  (`judge_error: true`) instead of silently disabling the gate.

## Roadmap (priority order)

### 1. ✅ DONE — Reranker NIM for relevancy gating (2026-06-11)
`check_relevancy` prefers a reranker NIM via `RERANKER_NIM_URL` (`/v1/ranking`,
chunked answers, best-chunk wins, threshold 0.0 — measured margins: relevant ≈ +10
logits, off-topic ≈ −15 to −21). Falls back to the LLM judge when unset/unavailable
(enhance-when-present). On rag-dev it reuses the RAG blueprint's own
`nemoretriever-ranking-ms` (llama-nemotron-rerank-1b-v2) — zero new GPU. Verified
live in-cluster: relevant → yes (+14.3), irrelevant → no (−21.97).

### 2. ✅ DONE — Guardrails: SQL execution rail + NemoGuard input rail (2026-06-11)
`sql_guard.validate_sql()` (always on, stdlib, literal-aware) validates KDB-chat
generated SQL before MCP execution — SELECT-only, single statement, deny-list
(DROP/DELETE/INSERT/…), length cap; blocked SQL never executes and the user sees why.
`guardrails.check_content_safety()` adds a NemoGuard 8B content-safety input rail
(`KXTA_APPLY_GUARDRAIL=nemoguard`, `NEMOGUARD_MODEL_NAME`) on the Q&A question and the
research topic; enhance-when-present. Verified live: weapons topic → flagged "Guns and
Illegal Weapons, Criminal Planning/Confessions"; finance topic → safe; `DROP TABLE` →
blocked; `'drop table'` inside a string literal → allowed.

### 3. ✅ DONE — Small summarization NIM (2026-06-11)
`get_summarization_llm()` routes the six agents' compression calls (the chattiest LLM
path) to a dedicated small NIM via `SUMMARIZATION_MODEL_NAME` (e.g. meta/llama-3.1-8b-
instruct), no_think-wrapped on Nemotron; unset → blueprint LLM. Verified live in-cluster.

### 4. ✅ DONE — Embedding NIM for semantic routing + dedup (2026-06-11)
`embeddings.py`: semantic source routing (cosine of query vs source descriptions) when
keyword routing finds only the RAG floor, and semantic query dedup in deepen/supervisor
rounds; Jaccard/keyword fallback when `EMBEDDING_NIM_URL` unset. On rag-dev it reuses
`nemoretriever-embedding-ms` (llama-nemotron-embed-1b-v2, 2048-dim) — zero new GPU.
Threshold 0.70 calibrated live (paraphrase ~0.76, related ~0.60, unrelated ~0.16).
Verified: tick-volatility query routed to `onetick`; paraphrase deduped.

### 5. ✅ DONE — SEC filings via nv-ingest into per-ticker RAG collections (2026-06-11)
`POST /sec/ingest {ticker}` fetches the latest 10-K/10-Q (edgartools, HTML) and uploads
through the RAG ingestor (nv-ingest parses tables) into a `sec_<ticker>` collection;
`GET /sec/collections` lists them. The Documents (RAG) agent then retrieves the parsed
filing. Collection dim = 2048 (matches the embedder). Verified live: NVDA 10-Q →
**sec_nvda, 157 entities**. (Caveat: the inline sec_filings agent still uses flat
edgartools text; this endpoint is the table-preserving path.)

### 6. ✅ DONE — Backend HPA/PDB + NIM Operator guidance (2026-06-11)
Values-gated `HorizontalPodAutoscaler` + `PodDisruptionBudget` for the backend
(`autoscaling.enabled` / `podDisruptionBudget.enabled`, off by default; render-verified).
NIM deployments themselves are best managed by the **NVIDIA NIM Operator** (HPA on NIM
metrics) rather than the hand-tuned nim-llm subchart — recommended for production.

## ✅ DONE — Token-context guard (2026-06-11)
The agent content-truncation guard now derives its budget from `NIM_MAX_MODEL_LEN`
(default 32768, ×0.75) instead of the dead hardcoded 150k that could never fire against
a 32k-context NIM.

## Positioning note (updated 2026-06-11)

The audit's "thin NVIDIA claims" are now largely resolved: the blueprint directly uses
NeMo Retriever **reranking** (item 1) and **embedding** (item 4) NIMs, **nv-ingest**
extraction (item 5), and **NemoGuard** safety (item 2) — in addition to NAT + NIM LLM
serving and the Nemotron coupling. On rag-dev these reuse the companion RAG cluster's
NIMs at zero new GPU cost. Still external (consumed, not owned by this repo): the RAG
retrieval server itself and KDB-X's cuVS/CAGRA vector index.

Defensible claim today: **"a multi-agent trading-research system built on NVIDIA NAT,
NIM LLMs, and NeMo Retriever (reranking, embedding, extraction) with NemoGuard safety."**
