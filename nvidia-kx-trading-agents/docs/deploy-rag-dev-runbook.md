# Runbook — Deploy the Trading Agents Blueprint into an existing RAG cluster

This documents the deployment used for live testing: running KXTA **inside an
existing NVIDIA RAG cluster** (`rag-dev`, us-west-2, account `590780615264`) so
that **all nine source agents are available in one place** — including
Documents (RAG) via the in-cluster `rag-server`, and KDB-X via the cluster's
existing `kdbx` database.

Result: `rag`, `kdb`, `web_search`, `market_data`, `news_headlines`,
`fundamentals`, `sec_filings`, `macro_economic`, `web` — all `available`.

---

## 0. Multi-cluster safety (important)

`kubectl`'s **current-context is a single global setting** in `~/.kube/config`.
If two sessions share the same kubeconfig, `kubectl config use-context` /
`aws eks update-kubeconfig` in one **silently repoints the other**.

**Rule: never switch the global context. Pass it per command.**

```bash
RAGCTX="arn:aws:eks:us-west-2:590780615264:cluster/rag-dev"
export AWS_PROFILE=terraform-sa AWS_REGION=us-west-2

kubectl --context "$RAGCTX" ...
helm   --kube-context "$RAGCTX" ...
```

(Or isolate fully with a dedicated `KUBECONFIG` per session.)

---

## 1. Prerequisites (already present in `rag-dev`)

- RAG blueprint in namespace `rag`: `rag-server:8081`, `ingestor-server:8082`,
  NeMo Retriever embedding/ranking, nv-ingest, MinIO, Redis.
- A KDB-X database: service `kdbx.rag.svc.cluster.local:5000`.
- ECR images (account `590780615264`, us-west-2):
  `kxta-backend:test-yf17`, `kdbx-mcp-server:latest`.
- A PyKX license (base64) — kept locally in the gitignored
  `deploy/helm/kdb-x-mcp-server/kdb-values.yaml` (`kdbLicense.licenseB64`).
- API keys for the keyed agents (Alpha Vantage, FRED, Firecrawl, Tavily) and an
  NGC API key for the hosted LLM. **Never commit these.**

---

## 2. Create the KXTA namespace

```bash
kubectl --context "$RAGCTX" create namespace kxta
```

---

## 3. Deploy the KDB-X MCP server (connect to the EXISTING kdbx)

The MCP server is what KXTA talks to (`KDB_MCP_ENDPOINT`); it connects to the
KDB-X DB. We reuse the cluster's `kdbx` rather than deploying a second one:
`kdbx.enabled: false` + `database.host` pointed at the existing service.

`/tmp/kdb-mcp-ragdev.yaml`:

```yaml
mode: "internal"
image:
  repository: 590780615264.dkr.ecr.us-west-2.amazonaws.com/kdbx-mcp-server
  tag: "latest"
imagePullSecret: { create: false }   # ECR via node IAM
kdbx:
  enabled: false                      # reuse the existing kdbx
database:
  host: "kdbx.rag.svc.cluster.local"  # cross-namespace is fine
  port: 5000
kdbLicense:
  create: true                        # PyKX needs a license to run, even vs a remote DB
  type: "personal"
  licenseB64: "<from kdb-values.yaml>"
mcp: { transport: "streamable-http", host: "0.0.0.0", port: 8000 }
service: { type: ClusterIP, port: 8000 }
```

```bash
helm --kube-context "$RAGCTX" upgrade --install kdb-mcp \
  deploy/helm/kdb-x-mcp-server -n kxta -f /tmp/kdb-mcp-ragdev.yaml
```

The chart publishes the endpoint:
`http://kdb-mcp-kdb-x-mcp-server.kxta.svc.cluster.local:8000/mcp`.

### 3a. Load the SQL interface into the existing kdbx  ← the key step

The MCP server requires KDB-X's **SQL interface** (`.s.init[]`). A bare KDB-X
process does not load it, so the MCP fails its startup check and crashloops:

```
KDB-X connectivity: SUCCESS ... version 5.0.x
KDB-X SQL interface check: FAILED — run .s.init[] in your KDB-X Session
```

Load it **into the running q process** by opening a client handle to it and
evaluating `.s.init[]` server-side. This is **non-destructive** — it loads the
SQL namespace; existing tables/data are untouched.

```bash
KDBX=$(kubectl --context "$RAGCTX" get pods -n rag -o name | grep '^pod/kdbx' | head -1 | cut -d/ -f2)

cat > /tmp/init.q <<'QEOF'
h:hopen 5000                                   / handle to the local serving q
h".s.init[]"                                   / load SQL interface server-side
-1 "remote .s.init[] loaded";
-1 "remote tables: ",", " sv string h"tables[]";
exit 0
QEOF

kubectl --context "$RAGCTX" cp /tmp/init.q rag/$KDBX:/tmp/init.q
kubectl --context "$RAGCTX" exec -n rag $KDBX -- \
  sh -c 'QHOME=/opt/kx/.kx QLIC=/opt/kx/.kx /opt/kx/.kx/bin/q /tmp/init.q -q < /dev/null'

# then restart the MCP so it re-checks and stays up:
kubectl --context "$RAGCTX" rollout restart deploy/kdb-mcp-kdb-x-mcp-server -n kxta
```

> Caveat: `.s.init[]` lives in the q process memory, so it must be re-run if the
> kdbx pod restarts. For a permanent fix, bake it into the kdbx image's startup
> (see the prebuilt-mode startup the blueprint adds in
> `deploy/helm/kdb-x-mcp-server/templates/kdbx-deployment.yaml`).

---

## 4. Deploy KXTA wired to the in-cluster RAG + this MCP

Take the deploy values and point RAG + KDB at the in-cluster services:

```yaml
# (in backendEnvVars)
RAG_SERVER_URL: "http://rag-server.rag.svc.cluster.local:8081"
RAG_INGEST_URL: "http://ingestor-server.rag.svc.cluster.local:8082"
KDB_ENABLED: "true"
KDB_MCP_ENDPOINT: "http://kdb-mcp-kdb-x-mcp-server.kxta.svc.cluster.local:8000/mcp"
KDB_MCP_INTERNAL: "true"   # enables the historical-data loader UI
# + ALPHAVANTAGE_API_KEY / FRED_API_KEY / FIRECRAWL_API_KEY, NGC + Tavily secrets,
#   NGC-hosted INSTRUCT_/NEMOTRON_ model + base_url, image tag test-yf17
```

```bash
helm --kube-context "$RAGCTX" upgrade --install kxta \
  deploy/helm/kxta -n kxta -f /tmp/kxta-ragdev.yaml
```

---

## 5. Verify + access

```bash
kubectl --context "$RAGCTX" port-forward -n kxta deploy/kxta-backend 3838:3838 &

curl -s localhost:3838/source_agents   # all 9 -> available (rag now reachable)
curl -s localhost:3838/kdb/status      # connected: true (MCP -> your kdbx)
```

Frontend: the local Vite dev server (`localhost:3000`) proxies `/api` →
`localhost:3838`, so it now drives the rag-dev backend. The Settings → Data tab
(KDB historical-data loader) is enabled by `KDB_MCP_INTERNAL=true`.

> RAG is now **reachable** (so it shows `available`). Actual document retrieval
> depends on collections being ingested into `rag-server` — select an existing
> collection, or ingest documents, for RAG results to come back.

---

## 5a. Historical-data loader — writes go DIRECT to KDB-X (not the MCP)

The KDB-X MCP is a **read-only query gateway** (`kdbx_run_sql_query` parses SQL and
rejects raw q), so the data loader cannot create/insert through it — it silently
no-op'd. The loader writes **directly to KDB-X over q-IPC** instead
(`kxta/src/kxta/kdb_direct_write.py`, a dependency-free IPC client). Point it
at the KDB-X DB:

```yaml
KDB_DB_HOST: "kdbx.rag.svc.cluster.local"   # the KDB-X the MCP queries
KDB_DB_PORT: "5000"
```

Safety: the loader only ever touches its own tables
(`daily/trade/quote/fundamentals/news/recommendations`) — it `set`s the typed
schema (create-or-clear) and never enumerates `tables[]`, so co-located RAG
collections (`multimodal_data`, etc.) are never read or written. KDB-X here is
the **unified store**: RAG vectors (managed by `rag-server-kdbx`, GPU CAGRA) +
tick tables (loaded by KXTA) in one instance.

## 5b. Productionize the loader (follow-ups)

- ✅ **DONE — PyKX rewrite**: `kdb_direct_write.py` now uses `pykx.SyncQConnection`
  (unlicensed — IPC clients need no license) instead of the hand-rolled protocol
  impl, and all f-string-built q inserts were replaced with **typed writes**
  (`kdb_insert`: typed q column vectors + server-side `flip`/`insert` — no q code
  built from data, no escaping/injection surface). `pykx` ships in the image
  (`PYKX_UNLICENSED=true`) and as the `kdb-loader` extra.

Remaining:
- **Bake `.s.init[]`** into the KDB-X image startup so the SQL interface survives
  restarts (done for the chart's prebuilt mode; the `kdbx-rag` image predates it).
- **Persistence for tick tables** — `daily/trade/quote` are in-memory and lost on
  pod restart; save down to the PVC or a dedicated HDB.

## 5d. Sharing KDB-X with the RAG blueprint — table isolation

When KXTA's KDB-X is the same process the RAG blueprint uses (the rag-dev setup),
both systems' tables live in one root namespace, so the KDB chat would otherwise
see RAG's tables (`sec_*`, `*_meta`, `smoke*`, `test*`) jumbled with KXTA's tick
tables. Three isolation options, in order of strength:

1. **q namespaces** (`.kxta.daily`): real isolation but breaks the SQL layer —
   `.s.init[]` and the MCP's `kdbx_run_sql_query` only see root-namespace tables,
   and rag-server writes to root. Fights the stack; not recommended.
2. **Presentation-layer scoping** ✅ **DONE**: the KDB chat/agent restrict schema
   discovery to an allowlist (`KDB_VISIBLE_TABLES`, default = `KXTA_OWNED_TABLES`:
   daily/trade/quote/fundamentals/news/recommendations). RAG tables stay reachable
   via the **Documents (RAG)** agent. SQL stays intact; no second process. This is
   the right fix when co-located.
3. **Dedicated KXTA KDB-X process/port** — true physical isolation (two processes,
   two `tables[]`), the production-hardening option. Give KXTA its own KDB-X pod
   (no GPU needed for tick tables; GPU only for RAG vectors) and point
   `KDB_DB_HOST`/`KDB_MCP_ENDPOINT` at it. Preferred for production; option 2
   covers the shared-cluster case meanwhile.

(KDB-X has no built-in "logical database" partition — these three are the real
choices. Not covered by the kdbx skill; this reflects the project's design call.)
- Optional: **bulk Parquet/Arrow ingestion** (`.pq`) for very large loads.

## 5c. Pause / Resume (scale nodes to 0 overnight)

The rag-dev cluster has two managed nodegroups: `gpu-pool` (g5.2xlarge — the
costly RAG NIMs) and `cpu-system` (t3.xlarge — KXTA + control workloads).

**Pause (stop compute spend, keep the control plane + PVCs):**
```bash
export AWS_PROFILE=terraform-sa AWS_REGION=us-west-2
for ng in gpu-pool cpu-system; do
  eksctl scale nodegroup --cluster rag-dev --name "$ng" --region us-west-2 \
    --nodes 0 --nodes-min 0
done
```

**Resume (next day):** scale back up (`--nodes <N> --nodes-min <N>`), wait for
nodes Ready, then because KDB-X in-memory state is lost on the kdbx pod cycle:
1. **Re-run `.s.init[]`** into kdbx (step 3a) — the MCP needs it.
2. **Re-load tick data** via the loader (the `daily/trade/quote` tables are
   in-memory; not saved to the PVC).  RAG collections on the `kdbx-data` PVC
   survive if the RAG image saves them down.
3. Restart the port-forward(s); the local Vite frontend then drives rag-dev again.

> Scaling nodes to 0 stops the **entire rag-dev cluster** (RAG stack included),
> not just KXTA. The EKS control plane + PVCs persist (small cost).

## 6. Teardown of the throwaway cluster

The earlier standalone `kxta-test` cluster is no longer needed:

```bash
eksctl delete cluster kxta-test --region us-west-2 --profile terraform-sa
```
