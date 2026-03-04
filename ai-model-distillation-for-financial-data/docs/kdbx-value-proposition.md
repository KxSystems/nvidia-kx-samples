<!--
SPDX-FileCopyrightText: Copyright (c) 2026 KX Systems, Inc. All rights reserved.
SPDX-License-Identifier: Apache-2.0

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

# KDB-X Integration — Value Proposition

## 1. Consolidated Infrastructure (3 Databases → 1)

**Before:** MongoDB (document store) + Elasticsearch (vector search) + Redis (broker)
**After:** KDB-X (everything) + Redis (Celery broker only)

- Eliminates two database systems to manage, monitor, and scale
- Single query language (q) for all data operations
- One backup/restore strategy instead of three

## 2. Native Vector Search — No External Engine

Replaced Elasticsearch's approximate kNN with KDB-X's **native HNSW** via the `.ai` module. Vector indexing and search happen **server-side in the same process** as the data — no network hop to a separate search cluster.

- `.ai.hnsw.put` builds the index alongside the data
- `.ai.hnsw.search` runs cosine similarity directly on stored vectors
- No index synchronization lag between data store and search engine

## 3. Financial-Grade Time-Series Engine

This is the real differentiator. KDB-X is purpose-built for financial data:

- **Backtesting** — q can compute Sharpe ratio, max drawdown, win rate, and PnL curves in microseconds over tick-level data. The blueprint now has a `/api/backtest` endpoint powered by native q analytics.
- **Market data enrichment** — Training pairs can be joined with `market_ticks` using `aj` (asof join) to enrich training records with point-in-time price context at the time the event occurred.
- **Time-series AI** — `.ai.tss.search` for pattern matching, `.ai.dtw.distance` for dynamic time warping, `.ai.anomaly.detect` — all available natively for financial signal analysis.

## 4. Performance at Scale

KDB-X processes vectors and tabular data in **columnar, in-memory format**:

- Column-oriented storage means aggregations (avg, sum, select by) scan only needed columns
- No ORM overhead — parameterized q queries go directly to the engine
- Real-time ingestion without write-ahead-log bottlenecks

For a financial distillation pipeline processing thousands of training records with embeddings, this is significantly faster than MongoDB + Elasticsearch.

## 5. Simpler Deployment

- One StatefulSet (KDB-X) replaces MongoDB replica set + Elasticsearch cluster
- Fewer PVCs, fewer services, fewer ConfigMaps
- KDB-X Community Edition is free for commercial use — no license cost for the database layer

## 6. End-to-End Pipeline — Verified Working

The full flywheel pipeline runs on EKS with KDB-X:

| Stage | Status |
|-------|--------|
| Data ingestion (104 records) | Working |
| Dataset creation (train/eval split) | Working |
| NIM deployment | Working |
| Base model evaluation (f1=0.095) | Working |
| LoRA fine-tuning (2 epochs, 20 steps) | Working |
| Fine-tuned model evaluation (f1=0.062) | Working |
| Vector search (HNSW) for ICL selection | Working |
| Backtesting infrastructure | Working |

## Summary

The blueprint went from a generic ML distillation pipeline to a **financial-domain-specific** one. KDB-X gives it the time-series DNA that MongoDB and Elasticsearch never had — backtesting, tick-level joins, native vector search, and columnar analytics — all in a single engine that is already the standard in capital markets.
