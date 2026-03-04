# KDB-X Architecture — Data Flywheel Blueprint

## Overview

The Data Flywheel Blueprint replaces MongoDB and Elasticsearch with a single KDB-X instance, reducing infrastructure complexity while maintaining the same application API.

## Architecture Diagram

```
                         ┌──────────────────────────────────────────┐
                         │          EKS Cluster (rag-dev)           │
                         │    ns: nv-nvidia-blueprint-data-flywheel │
┌───────────┐            │                                          │
│  Client   │───NLB──────┤►  df-api (FastAPI :8000)                 │
└───────────┘            │     │  ├── REST endpoints                │
                         │     │  ├── imports kdbx.compat           │
                         │     │  └── imports kdbx.es_adapter       │
                         │     │                                    │
                         │     ├──► df-celery-worker (x50 conc.)   │
                         │     │     └── async task execution       │
                         │     │                                    │
                         │     ├──► df-celery-parent-worker         │
                         │     │     └── task orchestration         │
                         │     │                                    │
                         │     ▼                                    │
                         │  ┌─────────────────────────────┐         │
                         │  │       KDB-X (:8082)         │         │
                         │  │  ┌────────────────────────┐ │         │
                         │  │  │ 7+4 Tables (q engine)  │ │         │
                         │  │  │ ┌──────────────────┐   │ │         │
                         │  │  │ │ flywheel_runs    │   │ │         │
                         │  │  │ │ nims             │   │ │         │
                         │  │  │ │ evaluations      │   │ │         │
                         │  │  │ │ customizations   │   │ │         │
                         │  │  │ │ llm_judge_runs   │   │ │         │
                         │  │  │ │ flywheel_logs    │   │ │         │
                         │  │  │ │ flywheel_embeds  │←──┤ │ vector  │
                         │  │  │ │ market_ticks     │   │ │         │
                         │  │  │ │ order_book       │   │ │         │
                         │  │  │ │ signals          │   │ │         │
                         │  │  │ │ backtest_results │   │ │         │
                         │  │  │ └──────────────────┘   │ │ search  │
                         │  │  └────────────────────────┘ │         │
                         │  │  PVC: 50Gi (kdbai-storage)  │         │
                         │  └─────────────────────────────┘         │
                         │                                          │
                         │  ┌──────────┐  ┌──────────────────┐      │
                         │  │ Redis    │  │ MLflow (:5000)   │      │
                         │  │ (:6379)  │  │ experiment       │      │
                         │  │ Celery   │  │ tracking         │      │
                         │  │ broker   │  └──────────────────┘      │
                         │  └──────────┘                            │
                         │                                          │
                         │  ┌──────────────────────────────┐        │
                         │  │  NeMo Microservices          │        │
                         │  │  ├── Customizer              │        │
                         │  │  ├── Evaluator               │        │
                         │  │  ├── Deployment Mgmt         │        │
                         │  │  ├── Data Store              │        │
                         │  │  ├── NIM Operator            │        │
                         │  │  └── Guardrails              │        │
                         │  └──────────────────────────────┘        │
                         │                                          │
                         │  Remote LLM Judge ──────────────►        │
                         │  NVIDIA API (llama-3.3-70b-instruct)     │
                         └──────────────────────────────────────────┘
```

## Before vs After

| Component | Before (MongoDB + ES) | After (KDB-X) |
|-----------|----------------------|----------------|
| **Document DB** | MongoDB | KDB-X q tables via `kdbx.compat` pymongo shim |
| **Vector Search** | Elasticsearch `dense_vector` | KDB-X native HNSW via `.ai.hnsw` module (`kdbx.es_adapter`) |
| **Connection** | `pymongo.MongoClient` + `elasticsearch.Elasticsearch` | `pykx.SyncQConnection` (single IPC) |
| **Data Services** | 3 (MongoDB, Elasticsearch, Redis) | 2 (KDB-X, Redis) |
| **PVCs** | 2 (MongoDB + Elasticsearch) | 1 (KDB-X, 50Gi) |
| **Memory Footprint** | ~6Gi (Mongo 2Gi + ES 4Gi) | ~4Gi (KDB-X) |

## Python Adapter Layers

### `kdbx/compat.py` — PyMongo Compatibility Shim

`KDBXCollection` and `KDBXDatabase` classes implement the pymongo API surface:
- `find()`, `find_one()` — translates to `select from table where ...`
- `insert_one()`, `insert_many()` — keyed insert via `` `tbl insert `col1`col2!(v0;v1) ``
- `update_one()`, `update_many()` — parameterized q update
- `delete_one()`, `delete_many()` — parameterized q delete
- `count_documents()` — `count` aggregation

All queries use parameterized q (no string interpolation) for safety.

### `kdbx/es_adapter.py` — Elasticsearch Replacement

Replaces Elasticsearch for vector search:
- Stores embeddings in the `flywheel_embeddings` KDB-X table
- Builds native HNSW indexes server-side via `.ai.hnsw.put` (M=32, ef=64, cosine similarity)
- Searches via `.ai.hnsw.search` — returns (distances, indices) for top-k nearest neighbours
- HNSW indexes stored as KDB-X server globals (`.hnsw.idx`, `.hnsw.vecs`) — persist across IPC connections
- On startup, `_rebuild_hnsw_from_table()` reconstructs indexes from persisted `flywheel_embeddings` rows

### `kdbx/enrichment.py` — Market Data Enrichment

Extracts ticker symbols from flywheel log records and enriches them with financial features:
- `extract_sym_from_record(record)` — parses ticker from request messages
- Features: SMA (configurable windows), RSI, rolling volatility, percent change
- Used during `create_datasets` to add market context to training pairs

### `kdbx/backtest.py` — Vectorised Backtesting Engine

Runs financial backtests using KDB-X as-of joins (`aj`):
- Joins signals to `market_ticks` by `sym` and `timestamp` for entry prices
- Shifts timestamp +1 day for exit prices
- Computes net returns with configurable transaction costs
- Returns: Sharpe ratio, max drawdown, total return, win rate, n_trades
- All queries are parameterized (no string interpolation)

### `kdbx/market_tables.py` — Market Table DDL

Defines 4 financial market tables: `market_ticks`, `order_book`, `signals`, `backtest_results`. Includes a Parquet loader for bulk-inserting market data.

### `kdbx/connection.py` — Connection Management

`pykx_connection()` context manager using `kx.SyncQConnection`:
```python
with pykx_connection() as conn:
    result = conn("select from flywheel_runs")
```

### `kdbx/schema.py` — Table DDL

7 core tables + 4 market tables (11 total) created using `flip` syntax to handle `_id` columns (q's `_` operator conflicts with `([] _id:...)` dictionary syntax). Core table DDL lives here; market table DDL is in `kdbx/market_tables.py`.
```q
`flywheel_runs set flip (`$"_id"),...
```

## KDB-X Deployment

KDB-X runs as a single pod using `python:3.12-slim-bookworm` with runtime installation:

1. Container starts from `python:3.12-slim-bookworm`
2. Downloads KDB-X installer from `portal.dl.kx.com` (authenticated via bearer token)
3. Installs KDB-X with base64-encoded license
4. Starts q process on port 8082
5. Tables are created on first connection by the application

Data is persisted to a 50Gi EBS volume (`kdbai-storage` StorageClass, gp3).

## Network Topology

| Service | Type | Port | Access |
|---------|------|------|--------|
| df-api-service | LoadBalancer (NLB) | 8000 | External |
| df-kdbx-service | ClusterIP | 8082 | Internal only |
| df-redis-service | ClusterIP | 6379 | Internal only |
| df-mlflow-service | ClusterIP | 5000 | Internal (port-forward) |
| df-flower-service | ClusterIP | 5555 | Internal (port-forward) |

## Key Design Decisions

1. **Native HNSW vector search**: KDB-X AI module (`.ai:use`kx.ai`) provides native HNSW indexing and search. Indexes are built server-side with `.ai.hnsw.put[(); (); vecs; `CS; 32; 1%log 32; 64]` and searched with `.ai.hnsw.search[vecs; hnsw; query; k; `CS; 64]`. Works on Community Edition.

2. **PyMongo shim over direct q**: Minimizes changes to existing application code. `src/` imports `kdbx.compat` instead of `pymongo` with the same API shapes.

3. **Symbol atoms for q**: Always use `kx.SymbolAtom()` for symbol-typed columns — raw Python strings become char vectors in q, not symbols.

4. **Keyed inserts**: Uses `` `tbl insert `col1`col2!(v0;v1) `` for column-order-independent, safer inserts.

5. **Single service**: One KDB-X instance handles both document storage (replacing MongoDB) and vector search (replacing Elasticsearch), reducing operational complexity.

6. **Remote LLM Judge**: Uses NVIDIA API (`meta/llama-3.3-70b-instruct`) instead of local 4-GPU NIM — the cluster has single-GPU nodes (g5.2xlarge), insufficient for a 70B model.

## Phase 3 — Enrichment + Backtest Pipeline

Phase 3 integrates financial analytics into the flywheel DAG:

1. **Market-data enrichment** in `create_datasets` — adds SMA, RSI, volatility, percent-change features to training records
2. **Backtest assessment** — new Celery task (`run_backtest_assessment`) wired after customization eval, producing `backtest-eval` evaluations with Sharpe/drawdown/return metrics
3. **New API endpoints** — `POST /api/backtest` (ad-hoc) and `GET /api/market-status` (table stats)
4. **`enrichment_stats`** — persisted on `flywheel_runs`, surfaced in job detail responses

The `flywheel_runs` table now includes an `enrichment_stats` column (general list, JSON-serialized) tracking records enriched, features added, and enrichment time.
