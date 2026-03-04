# KDB-X Integration Design — NVIDIA AI Model Distillation Blueprint

> Approved design for replacing Elasticsearch and MongoDB with KDB-X.
> Phased approach: Phase 1 (data layer swap), Phase 2 (financial enhancements).

---

## Overview

Replace Elasticsearch and MongoDB with KDB-X as the unified data platform for the
NVIDIA AI Model Distillation Blueprint. Redis stays as Celery broker only.

**Approach:** Adapter pattern. Create a `kdbx/` package that implements the exact
interfaces the existing code already calls. Callers (Celery tasks, API endpoints,
job service) are minimally changed or untouched.

**Client library:** PyKX (KDB-X Python, formerly pykx) is the sole Python interface
to KDB-X. All table operations, queries, updates, deletes, and vector search go
through PyKX. There is no `kdbai_client` dependency — that is for KDB.AI cloud,
which is a separate product.

**Reference:** https://code.kx.com/kdb-x/learn/kdb-x-python-overview.html

---

## Phase 1: Data Layer Swap

### 1. What Changes vs What Stays

**Modified files (6):**

| File | Change |
|---|---|
| `src/api/db.py` | Rewrite `init_db()` / `get_db()` / `close_db()` to delegate to `kdbx/` |
| `src/api/db_manager.py` | Rewrite `TaskDBManager` internals, keep all method signatures |
| `src/api/job_service.py` | No code changes — works via pymongo-compat shim from `get_db()` |
| `src/lib/integration/es_client.py` | Rewrite internals to delegate to `kdbx/es_adapter.py` |
| `src/scripts/load_test_data.py` | Rewrite data loading to use KDB-X |
| `src/lib/flywheel/icl_selection.py` | Imports stay the same (calls `es_client` functions) |

**New files (5):**

| File | Purpose |
|---|---|
| `kdbx/__init__.py` | Package init |
| `kdbx/connection.py` | KDB-X connection management via PyKX |
| `kdbx/schema.py` | All table definitions via q commands + `create_all_tables()` |
| `kdbx/es_adapter.py` | Drop-in replacement for ES functions (logs + vector search) |
| `kdbx/compat.py` | `KDBXDatabase` + `KDBXCollection` pymongo-compatible shim |

**Untouched files (everything else):**

- `src/api/endpoints.py` — API routes
- `src/api/models.py` — Pydantic models (including `bson.ObjectId`)
- `src/api/schemas.py` — API schemas
- `src/tasks/tasks.py` — Celery task chain
- `src/lib/flywheel/*.py` — flywheel logic
- `src/lib/nemo/*.py` — NeMo integrations
- `src/lib/integration/dataset_creator.py` — dataset ops
- `src/lib/integration/data_validator.py` — validation
- `src/lib/integration/record_exporter.py` — calls es_client functions (unchanged interface)
- `src/lib/integration/mlflow_client.py` — MLflow tracking
- `src/config.py` — only addition: `KDBX_ENDPOINT` env var

---

### 2. KDB-X Connection Management (`kdbx/connection.py`)

Single connection type: **PyKX** only.

PyKX supports two modes:
- **Embedded mode** (licensed): `import pykx as kx; kx.q('...')` — q runs in-process
- **IPC mode**: `kx.SyncQConnection(host, port)` — connects to remote KDB-X process

For Docker deployment (KDB-X in a container), we use **IPC mode** with context managers
as recommended by PyKX documentation.

```python
import pykx as kx

# Context manager factory (recommended by PyKX docs)
def pykx_connection() -> ContextManager[kx.SyncQConnection]:
    """Returns a context manager for a PyKX connection to KDB-X."""
    host, port = parse_endpoint(os.getenv("KDBX_ENDPOINT", "localhost:8082"))
    return kx.SyncQConnection(host, port)

# Usage:
with pykx_connection() as q:
    result = q('select from flywheel_runs where workload_id = wid', wid)
```

For embedded mode (testing, or licensed local dev), PyKX can run q in-process:
```python
import pykx as kx
kx.q('select from flywheel_runs')  # No connection needed
```

**Exported functions:**
```
pykx_connection() -> ContextManager[kx.SyncQConnection]  # IPC context manager
get_kdbx_mode()   -> str                                  # "ipc" or "embedded"
```

Retry logic: 30 attempts, 1s apart (matches existing ES retry pattern).
Applied in `init_db()` — tries to connect and run a health check query.

---

### 3. KDB-X Schema (`kdbx/schema.py`)

Tables are created via q commands through PyKX. No `kdbai_client` — pure q DDL.

#### 3.1 Table Creation Pattern

```python
with pykx_connection() as q:
    # Create table if it doesn't exist
    q('''
      if[not `flywheel_runs in tables[];
        flywheel_runs:([]
          _id:`symbol$();
          workload_id:`symbol$();
          client_id:`symbol$();
          status:`symbol$();
          started_at:`timestamp$();
          finished_at:`timestamp$();
          num_records:`long$();
          datasets:();           / general list — stores JSON strings
          error:()               / general list — nullable strings
        )]
    ''')
```

String columns that can be null use general list type `()`. Columns with a fixed
set of values (like `_id`, `workload_id`, `status`) use `symbol` for fast equality
lookups. Timestamps use `timestamp` (nanosecond precision, native to kdb+).

#### 3.2 MongoDB Replacement Tables

**`flywheel_runs`** — replaces MongoDB `flywheel_runs` collection

| Column | q Type | Notes |
|---|---|---|
| `_id` | `symbol` | ObjectId-format string, primary key |
| `workload_id` | `symbol` | Fast equality lookup |
| `client_id` | `symbol` | |
| `status` | `symbol` | Enum value: PENDING, RUNNING, COMPLETED, FAILED, CANCELLED |
| `started_at` | `timestamp` | |
| `finished_at` | `timestamp` | Nullable (0Np) |
| `num_records` | `long` | Nullable (0N) |
| `datasets` | general | JSON-encoded string |
| `error` | general | Nullable string |

**`nims`** — replaces MongoDB `nims` collection

| Column | q Type | Notes |
|---|---|---|
| `_id` | `symbol` | ObjectId-format string |
| `flywheel_run_id` | `symbol` | FK to `flywheel_runs._id` |
| `model_name` | `symbol` | |
| `status` | `symbol` | NIMRunStatus enum value |
| `deployment_status` | general | Nullable string |
| `started_at` | `timestamp` | Nullable (0Np) |
| `finished_at` | `timestamp` | Nullable (0Np) |
| `runtime_seconds` | `float` | |
| `error` | general | Nullable string |

**`evaluations`** — replaces MongoDB `evaluations` collection

| Column | q Type | Notes |
|---|---|---|
| `_id` | `symbol` | ObjectId-format string |
| `nim_id` | `symbol` | FK to `nims._id` |
| `eval_type` | `symbol` | "base-eval" or "customized-eval" |
| `scores` | general | JSON-encoded dict |
| `started_at` | `timestamp` | |
| `finished_at` | `timestamp` | Nullable (0Np) |
| `runtime_seconds` | `float` | |
| `progress` | `float` | 0-100 |
| `nmp_uri` | general | Nullable string |
| `mlflow_uri` | general | Nullable string |
| `error` | general | Nullable string |

**`customizations`** — replaces MongoDB `customizations` collection

| Column | q Type | Notes |
|---|---|---|
| `_id` | `symbol` | ObjectId-format string |
| `nim_id` | `symbol` | FK to `nims._id` |
| `workload_id` | `symbol` | |
| `base_model` | `symbol` | |
| `customized_model` | general | Nullable string |
| `started_at` | `timestamp` | |
| `finished_at` | `timestamp` | Nullable (0Np) |
| `runtime_seconds` | `float` | |
| `progress` | `float` | 0-100 |
| `epochs_completed` | `long` | Nullable (0N) |
| `steps_completed` | `long` | Nullable (0N) |
| `nmp_uri` | general | Nullable string |
| `error` | general | Nullable string |

**`llm_judge_runs`** — replaces MongoDB `llm_judge_runs` collection

| Column | q Type | Notes |
|---|---|---|
| `_id` | `symbol` | ObjectId-format string |
| `flywheel_run_id` | `symbol` | FK to `flywheel_runs._id` |
| `model_name` | `symbol` | |
| `deployment_type` | `symbol` | |
| `deployment_status` | general | Nullable string |
| `error` | general | Nullable string |

#### 3.3 Elasticsearch Replacement Tables

**`flywheel_logs`** — replaces ES `flywheel` index

| Column | q Type | Notes |
|---|---|---|
| `doc_id` | `symbol` | UUID string, primary key |
| `workload_id` | `symbol` | Queryable filter |
| `client_id` | `symbol` | Queryable filter |
| `timestamp` | `timestamp` | Sort key |
| `request` | general | JSON-encoded request object |
| `response` | general | JSON-encoded response object |

**`flywheel_embeddings`** — replaces ES `flywheel_embeddings_index_*` dynamic indexes

| Column | q Type | Notes |
|---|---|---|
| `doc_id` | `symbol` | Unique ID per row |
| `index_name` | `symbol` | Replaces per-workflow ES index names. Filter + delete key. |
| `embedding` | `real list` | 2048-dim dense vector (real = 32-bit float) |
| `tool_name` | `symbol` | Function/tool name |
| `query_text` | general | User query text (variable length) |
| `record_id` | `symbol` | References workload_id |
| `timestamp` | `timestamp` | |
| `record` | general | JSON-encoded full source record |

The embeddings column stores vectors as `real` lists (32-bit float, matching the
embedding model's output precision).

#### 3.4 Vector Search — HNSW via KDB-X AI Module

KDB-X has a built-in AI module (`.ai.hnsw.*`) for HNSW vector search. Unlike
kdbai_client which integrates indexes into table operations, KDB-X HNSW is a
**standalone in-memory index** managed separately from tables.

**How it works:**

```q
\l ai.q                                          / Load AI module
vecs: select embedding from flywheel_embeddings   / Extract vectors
hnsw: .ai.hnsw.put[();();vecs;`CS;32;1%log 32;64] / Build HNSW index

/ Search: returns (distances; indices)
.ai.hnsw.search[vecs;hnsw;queryVec;50;`CS;64]

/ Filtered search: restrict to specific row IDs
.ai.hnsw.filterSearch[vecs;hnsw;queryVec;50;`CS;64;allowedIds]
```

**HNSW parameters:**
- `M=32` — connectivity (higher = better recall, more memory)
- `ef=64` — construction quality
- `efs=64` — search quality (higher = better recall, slower)
- `metric=CS` — cosine similarity (matches ES config)

**Integration strategy for `es_adapter.py`:**

The HNSW index must be rebuilt when new embeddings are inserted (per-workflow).
Since each workflow creates a temporary set of embeddings (tagged by `index_name`),
the flow is:

1. `index_embeddings()` — insert rows into `flywheel_embeddings` table, then build
   HNSW index from the vectors with matching `index_name`
2. `search_similar_embeddings()` — use `.ai.hnsw.filterSearch` with the pre-built
   index. Filter by `index_name` at the q level to get allowed row IDs, then pass
   those IDs to filterSearch.
3. `delete_embeddings()` — delete rows from table, discard the HNSW object

**Per-workflow index lifecycle:**
```python
# In es_adapter.py — managed as module-level dict
_hnsw_indexes: dict[str, tuple] = {}  # index_name -> (vectors, hnsw_object)

def index_embeddings(q, binned_data, workload_id, client_id) -> str:
    index_name = f"flywheel_embeddings_index_{workload_id}_{client_id}_{ts}"
    # 1. Insert rows into flywheel_embeddings table
    # 2. Extract vectors for this index_name
    # 3. Build HNSW: .ai.hnsw.put[();();vecs;`CS;32;1%log 32;64]
    # 4. Store in _hnsw_indexes[index_name]
    return index_name

def search_similar_embeddings(q, query_embedding, index_name, k) -> list:
    vecs, hnsw = _hnsw_indexes[index_name]
    # .ai.hnsw.search[vecs;hnsw;queryVec;k;`CS;64]
    # Map indices back to table rows for tool_name + record
    ...

def delete_embeddings(q, index_name):
    # Delete rows from table
    # Remove from _hnsw_indexes
    del _hnsw_indexes[index_name]
```

**Note:** The HNSW index lives in the Python process memory (or the KDB-X process
if built via IPC). Since each Celery worker handles one workflow at a time
(serial `parent_queue`), there's no concurrency issue with the module-level dict.

#### 3.5 `create_all_tables()`

Called once on startup via `init_db()`. For each table:
1. Check if table exists: `q('tables[]')` and check membership
2. If not found, create with q DDL
3. Load AI module: `q('\\l ai.q')` (needed for vector search)

`drop_existing` parameter for test fixtures — drops and recreates all tables.

---

### 4. ES Adapter (`kdbx/es_adapter.py`)

Drop-in replacements for the 6 functions exported by `es_client.py`:

**`get_es_client()` -> KDB-X connection wrapper**
- Returns an object that the existing callers can pass around
- Internally creates a PyKX connection via `pykx_connection()`
- Retry logic: 30 attempts, 1s sleep (matches current behavior)
- Auto-creates tables on first connection via `create_all_tables()`
- Loads KDB-X AI module (`.ai:use`kx.ai`) for native HNSW vector search

**`ensure_embeddings_index(client, index_name)` -> no-op**
- The `flywheel_embeddings` table is created at startup
- HNSW index is built per-workflow when embeddings are inserted

**`index_embeddings_to_es(client, binned_data, workload_id, client_id)` -> `index_embeddings()`**
- Generates `index_name = f"flywheel_embeddings_index_{workload_id}_{client_id}_{ts}"`
- Flattens `binned_data` dict into rows
- Inserts into `flywheel_embeddings` table via q insert
- Extracts the embedding vectors and builds HNSW index via `.ai.hnsw.put`
- Caches the HNSW object + vectors in module-level dict
- Returns `index_name` string (same return type as current)

**`search_similar_embeddings(client, query_embedding, index_name, max_candidates)` -> HNSW search**
- Retrieves cached HNSW object + vectors for `index_name`
- Calls `.ai.hnsw.search[vecs;hnsw;queryVec;k;`CS;64]` via PyKX
- Maps result indices back to table rows to get `tool_name` and `record`
- Returns `list[tuple[float, str, dict]]` — `(score, tool_name, record)` — same format

**`delete_embeddings_index(client, index_name)` -> delete rows + discard HNSW**
- Deletes rows via parameterized q: `{[nm] delete from `flywheel_embeddings where index_name = nm}`
- Removes HNSW object from module-level cache

**`close_es_client()` -> cleanup**
- Clears HNSW cache
- No persistent connection to close (context managers handle this)

---

### 5. Pymongo-Compatible Shim (`kdbx/compat.py`)

Supports the exact query patterns used by `job_service.py` and `TaskDBManager.__init__`.
All operations go through PyKX q queries.

**`KDBXCollection`** — mimics `pymongo.collection.Collection`

Supported operations (covers 100% of actual usage in codebase):

```python
# Read
find_one(filter: dict) -> dict | None
    # {"_id": val}              -> q: select from tbl where _id = val
    # {"field": val}            -> q: select from tbl where field = val
    # {"_id": val, "error": None} -> q: select from tbl where _id = val, null error

find(filter: dict) -> list[dict]
    # {"field": val}            -> q: select from tbl where field = val
    # {"field": {"$in": [list]}} -> q: select from tbl where field in list
    # Compound filters combine with ,

# Write
insert_one(doc: dict) -> InsertOneResult-like (with .inserted_id)
    # Converts dict to q table row, inserts via q insert

# Update
update_one(filter: dict, update: dict) -> None
    # filter: {"_id": val} or {"_id": val, "field": None}
    # update: {"$set": {field: value, ...}}
    # -> q: update col1:val1, col2:val2 from `tbl where _id = val, null field

update_many(filter: dict, update: dict) -> None
    # Same patterns, applies to all matches

# Delete
delete_one(filter: dict) -> None
delete_many(filter: dict) -> None
    # -> q: delete from `tbl where field = val

# Index (no-op)
create_index(field: str) -> None
```

**Null handling:** MongoDB's `{"error": None}` filter becomes q's `null error`
predicate. This is native to q and works correctly for general list columns.

Any unsupported pattern raises `NotImplementedError` with a descriptive message.

**`KDBXDatabase`** — mimics `pymongo.database.Database`

Attribute access returns `KDBXCollection` instances:
- `db.flywheel_runs` -> `KDBXCollection("flywheel_runs")`
- `db.nims` -> `KDBXCollection("nims")`
- `db.evaluations` -> `KDBXCollection("evaluations")`
- `db.customizations` -> `KDBXCollection("customizations")`
- `db.llm_judge_runs` -> `KDBXCollection("llm_judge_runs")`

**Implementation detail:** Each `KDBXCollection` uses `pykx_connection()` context
managers for each operation. All q queries use parameterized expressions — no
f-string interpolation of user data.

**PyKX Pythonic API alternative:** For reads, we can also use PyKX's Pythonic query API:
```python
table = kx.q('flywheel_runs')
result = table.select(where=kx.Column('_id') == oid)
```
This avoids raw q strings for simple queries. We use raw q only for operations
the Pythonic API can't express (compound null filters, updates).

---

### 6. `TaskDBManager` Rewrite (`src/api/db_manager.py`)

Same class, same 30+ methods, same signatures. Internal changes:

**Insert operations** (`create_nim_run`, `insert_evaluation`, `insert_customization`, `create_llm_judge_run`):
- Call `model.to_mongo()` to get dict (unchanged)
- Convert to q-compatible types (ObjectId -> str, datetime -> timestamp, dict -> JSON str)
- Insert via q: `{[row] `tablename insert row}`

**Update operations** (`update_flywheel_run_status`, `mark_nim_error`, etc.):
- Conditional updates use q `update ... from ... where` with null checks:
  ```q
  {[oid;newStatus]
    update status:newStatus from `flywheel_runs
    where _id = oid, null error}
  ```
- All done via parameterized PyKX calls

**Query operations** (`find_nim_run`, `get_flywheel_run`, `find_running_flywheel_runs`):
- Via q select with `.pd()` conversion:
  ```python
  with pykx_connection() as q:
      result = q('{[oid] select from flywheel_runs where _id = oid}', oid)
      df = result.pd()
      return df.iloc[0].to_dict() if len(df) > 0 else None
  ```
- `$in` queries map to q `in`: `where status in \`RUNNING\`PENDING`

**Delete operations** (`delete_job_records`):
- Cascade delete via q: delete from each table where FK matches
- All parameterized

**ObjectId handling:**
- `bson.ObjectId` stays as dependency (via pymongo)
- `ObjectId()` generates IDs, stored as `str(ObjectId())` -> q symbol
- `ObjectId(string)` used for validation (existing behavior)
- Comparison: symbol equality in q queries

---

### 7. Docker & Dependencies

#### 7.1 Docker Compose Changes

Remove services:
- `elasticsearch` (image: `elasticsearch:8.12.2`, ports 9200/9300)
- `mongodb` (image: `mongo:7.0`, port 27017)

Add service:
```yaml
kdbx:
  image: kxsys/kdbx:latest
  container_name: kdbx
  ports:
    - "8082:8082"    # qIPC
    - "8081:8081"    # REST
  volumes:
    - kdbx_data:/data
    - ./kdbx_config:/config
  environment:
    KDBX_LICENSE_FILE: /config/kc.lic
  restart: unless-stopped
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8081/health"]
    interval: 10s
    timeout: 5s
    retries: 5
```

Update `api` and `worker` services:
- `depends_on`: `kdbx` (was: `elasticsearch`, `mongodb`)
- Remove: `ELASTICSEARCH_URL`, `MONGODB_URL`, `MONGODB_DB`, `ES_COLLECTION_NAME`
- Add: `KDBX_ENDPOINT=http://kdbx:8082`

Redis service: **unchanged**.

#### 7.2 pyproject.toml Changes

```diff
 dependencies = [
-    "elasticsearch==8.17.2",
+    "pykx>=2.5.0",
     "pymongo>=4.12.0",          # KEEP — used for bson.ObjectId only
     # ... everything else unchanged
 ]
```

No `kdbai-client` — KDB-X is accessed entirely through PyKX.

#### 7.3 Environment Variables

| Remove | Add | Default |
|---|---|---|
| `ELASTICSEARCH_URL` | `KDBX_ENDPOINT` | `localhost:8082` |
| `MONGODB_URL` | `KDBX_MODE` | `ipc` (or `embedded` for local dev) |
| `MONGODB_DB` | | |
| `ES_COLLECTION_NAME` | | (hardcoded in schema) |
| `ES_EMBEDDINGS_INDEX_NAME` | | (hardcoded in schema) |

Keep unchanged: `REDIS_URL`, `NVIDIA_API_KEY`, all NeMo env vars.

---

### 8. Testing

**Unit tests** — no changes. They mock at the `TaskDBManager` and `es_client`
function boundaries. Since signatures are unchanged, mocks keep working.

**Integration tests** — update fixtures:
- Replace ES container fixture with KDB-X container
- Replace MongoDB container fixture with same KDB-X container
- Fixture calls `create_all_tables(drop_existing=True)` before each test
- Connection env vars point to test KDB-X instance
- PyKX embedded mode can be used for faster test execution (no Docker needed)

**CI pipeline** — update `.github/workflows/ci.yaml`:
- Remove ES and MongoDB health checks
- Add KDB-X health check
- Update Docker Compose file reference

---

### 9. q Injection Prevention

All user-controlled values going into q expressions MUST be parameterized.
Never use f-strings with user data in q queries.

**Pattern:**
```python
# BAD — q injection risk
q(f'delete from `flywheel_logs where workload_id=`$"{user_input}"')

# GOOD — parameterized via PyKX
q('{[wid] delete from `flywheel_logs where workload_id = wid}', kx.SymbolAtom(user_input))
```

This applies to all operations in `compat.py`, `es_adapter.py`, and `db_manager.py`.

---

### 10. Migration / Rollback

Phase 1 is a clean swap — no data migration needed since this is a developer example
(not a production system with existing data). The original code is preserved on the
branch before the PR.

If rollback is needed: revert the branch. No data to migrate back.

---

## Phase 2: Financial Enhancements (Future)

Phase 2 extends the blueprint from pure classification to financial signal generation
with market-aware evaluation. This section captures the design intent so the knowledge
is preserved.

### 2.1 New Use Case: Trading Signal Generation

The original blueprint classifies financial news into 13 categories. Phase 2 extends
this to generate BUY/SELL/HOLD trading signals enriched with market context.

This is a **new capability** layered on top of the existing classification pipeline,
not a replacement.

### 2.2 New KDB-X Tables (Structured — Time-Series)

These leverage kdb+'s native time-series strengths. Created via q DDL through PyKX.

**`market_ticks`** — OHLCV + trade data at tick resolution

| Column | q Type |
|---|---|
| `sym` | `symbol` |
| `timestamp` | `timestamp` |
| `open`, `high`, `low`, `close` | `float` |
| `volume` | `long` |
| `vwap` | `float` |
| `trade_count` | `long` |
| `source` | `symbol` |

**`order_book`** — bid/ask depth snapshots

| Column | q Type |
|---|---|
| `sym` | `symbol` |
| `timestamp` | `timestamp` |
| `bid_price`, `ask_price` | `float` |
| `bid_size`, `ask_size` | `long` |
| `mid`, `spread` | `float` |

**`signals`** — NIM-generated trading signals + outcomes

| Column | q Type |
|---|---|
| `signal_id` | `symbol` |
| `timestamp` | `timestamp` |
| `sym` | `symbol` |
| `direction` | `symbol` (BUY/SELL/HOLD) |
| `confidence` | `float` |
| `model_id` | `symbol` |
| `source_doc_id` | `symbol` |
| `rationale` | general |
| `realized_pnl` | `float` |
| `realized_at` | `timestamp` |

**`backtest_results`** — evaluation runs with financial metrics

| Column | q Type |
|---|---|
| `run_id` | `symbol` |
| `timestamp` | `timestamp` |
| `model_id` | `symbol` |
| `universe` | general (JSON list of syms) |
| `start_date`, `end_date` | `timestamp` |
| `sharpe` | `float` |
| `max_drawdown` | `float` |
| `total_return` | `float` |
| `avg_fill_slippage` | `float` |
| `win_rate` | `float` |
| `f1_score` | `float` |
| `params` | general (JSON) |

### 2.3 Co-Temporal Training Data Enrichment

The core value-add of Phase 2. When generating teacher-student distillation pairs:

1. For each financial document, query `market_ticks` at the document's event timestamp
2. Extract market microstructure features: VWAP, 1h return, spread, volume, high/low
3. Inject these features into the teacher prompt alongside the document text
4. Teacher (70B) generates signal + rationale informed by both text AND market state
5. Store enriched pair in `training_pairs` table with market context columns

The temporal alignment uses kdb+'s `aj` (as-of join) — native, vectorized, nanosecond
precision. This is where KDB-X shines vs the original ES/Mongo stack.

```q
/ As-of join: for each document timestamp, get the most recent market state
aj[`sym`timestamp;
   select sym, timestamp from documents;
   select sym, timestamp, close, vwap, volume from market_ticks]
```

**New table: `training_pairs`**

| Column | q Type |
|---|---|
| `pair_id` | `symbol` |
| `timestamp` | `timestamp` (event time, NOT generation time) |
| `sym` | `symbol` |
| `doc_id` | `symbol` (FK to flywheel_logs) |
| `teacher_prompt` | general |
| `teacher_response` | general |
| `teacher_model` | `symbol` |
| `market_close`, `market_vwap`, `market_spread` | `float` |
| `market_volume` | `long` |
| `price_return_1h`, `price_return_1d` | `float` |
| `ground_truth_signal` | `symbol` (BUY/SELL/HOLD) |
| `outcome_return` | `float` |
| `dataset_split` | `symbol` (train/val/test) |

### 2.4 Financial-Grade Evaluation (PyKX Backtesting)

Replace F1-only evaluation with combined NLP + financial metrics:

1. **NeMo Evaluator** — still runs for F1, accuracy, etc. (kept from Phase 1)
2. **PyKX backtest** — new: as-of join signals onto `market_ticks` to compute:
   - Sharpe ratio (annualized)
   - Max drawdown (cumulative return based)
   - Total return (net of transaction costs)
   - Win rate
   - Average fill slippage

The backtest runs entirely in q via PyKX — vectorized, no Python loops over ticks.

```q
/ Backtest: join signals to prices, compute returns
entries: aj[`sym`timestamp; signals; select sym, timestamp, entry:close from market_ticks];
exits: aj[`sym`timestamp;
          update timestamp: timestamp + 1D from entries;
          select sym, timestamp, exit:close from market_ticks];
bt: update ret: (exit % entry - 1) * ?[direction=`BUY;1;-1] from exits;
select sharpe: avg[ret] % dev[ret] * sqrt 252,
       max_dd: max maxs[sums ret] - sums ret,
       total_ret: sum ret,
       win_rate: avg ret > 0
from bt
```

### 2.5 Hybrid Search Upgrade

Phase 1 does pure dense cosine k-NN via `.ai.hnsw` (matching current ES behavior).
Phase 2 can add BM25 text search using KDB-X's built-in capabilities, combining
vector similarity with keyword matching.

### 2.6 MCP Tool Exposure

Expose KDB-X capabilities as MCP tools so NIM agents can call them during inference:

- `query_market_data(sym, time_from, time_to)` — pull tick data
- `get_temporal_context(sym, event_timestamp, window_minutes)` — market state snapshot
- `run_backtest(model_id, universe, start_date, end_date)` — backtest signals
- `hybrid_search(query_text, query_embedding, filters)` — combined search
- `stream_signals(signals)` — persist NIM-generated signals for live consumption

These would live in `kdbx/mcp_tools.py` and register with the KDB-X MCP server.

### 2.7 NIM Outputs Table

Store raw NIM inference outputs with response embeddings for similarity search
over model outputs:

**`nim_outputs`**

| Column | q Type |
|---|---|
| `output_id` | `symbol` |
| `timestamp` | `timestamp` |
| `model_id` | `symbol` |
| `doc_id` | `symbol` |
| `prompt` | general |
| `response` | general |
| `latency_ms` | `float` |
| `token_count` | `long` |
| `embedding` | `real list` (HNSW indexed via `.ai.hnsw`) |

### 2.8 Phase 2 Depends On

- Phase 1 complete and tested
- Market data source identified (exchange feed, vendor API, or synthetic)
- Decision on whether to keep or replace the 13-category classification task
  alongside the new signal generation task
- KDB-X license that supports the additional table/data volume

---

## File Structure After Both Phases

```
kdbx/
├── __init__.py
├── connection.py              # PyKX connection management (IPC + embedded)
├── schema.py                  # All table definitions via q DDL
├── es_adapter.py              # Replaces Elasticsearch (logs + HNSW vector search)
├── compat.py                  # pymongo-compatible shim (KDBXDatabase, KDBXCollection)
├── training_data_generator.py # [Phase 2] Co-temporal enrichment via aj
├── backtest.py                # [Phase 2] PyKX financial evaluation
└── mcp_tools.py               # [Phase 2] MCP tool registry
```
