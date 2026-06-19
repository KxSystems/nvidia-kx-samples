<!--
SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
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

# Configuration Reference

This document provides a comprehensive reference for all configurable values in the AI Trader Agents.

## Table of Contents

- [Environment Variables](#environment-variables)
  - [Core Service Configuration](#core-service-configuration)
  - [LLM Configuration](#llm-configuration)
  - [Self-hosted vs. cloud NIMs (and air-gap)](#self-hosted-vs-cloud-nims-and-air-gap)
  - [Standalone (no RAG)](#standalone-no-rag)
  - [KDB+ MCP Configuration](#kdb-mcp-configuration)
  - [RAG Configuration](#rag-configuration)
  - [NIM Enhancements (enhance-when-present)](#nim-enhancements-enhance-when-present)
  - [OneTick Cloud (source agent)](#onetick-cloud-source-agent)
  - [Source Agent Data Providers](#source-agent-data-providers)
  - [KDB-X Document & Table Selection](#kdb-x-document--table-selection)
  - [Evaluation Module](#evaluation-module)
- [Helm Chart Configuration](#helm-chart-configuration)
  - [Image Configuration](#image-configuration)
  - [Backend Environment Variables](#backend-environment-variables)
  - [Frontend Configuration](#frontend-configuration)
- [Docker Compose Configuration](#docker-compose-configuration)

---

## Environment Variables

### Core Service Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `NVIDIA_API_KEY` | Required | NVIDIA API key for hosted NIMs |
| `NGC_API_KEY` | Required | NGC registry access (usually same as NVIDIA_API_KEY) |
| `TAVILY_API_KEY` | Optional | Tavily API key for web search fallback |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection URL for job tracking |
| `KXTA_APPLY_GUARDRAIL` | `false` | Enable/disable relevancy guardrails |
| `KXTA_HOSTED_NIMS` | `false` | Use hosted NIMs vs local deployment |

### LLM Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `INSTRUCT_BASE_URL` | `http://kxta-instruct-llm:8000/v1` | Instruct LLM endpoint |
| `INSTRUCT_MODEL_NAME` | `meta-llama/llama-3.3-70b-instruct` | Instruct model name |
| `INSTRUCT_MODEL_TEMP` | `0.0` | Instruct model temperature |
| `INSTRUCT_MAX_TOKENS` | `20000` | Max tokens for instruct model |
| `INSTRUCT_API_KEY` | `not-needed` | API key for instruct LLM (local) |
| `NEMOTRON_BASE_URL` | `http://nim-llm-ms:8000/v1` | Nemotron reasoning model endpoint |
| `NEMOTRON_MODEL_NAME` | `nvidia/llama-3.3-nemotron-super-49b-v1.5` | Nemotron model name |
| `NEMOTRON_MODEL_TEMP` | `0.5` | Nemotron model temperature |
| `NEMOTRON_MAX_TOKENS` | `5000` | Max tokens for Nemotron model |
| `NEMOTRON_API_KEY` | From secret | API key for Nemotron LLM |

### Self-hosted vs. cloud NIMs (and air-gap)

The blueprint runs the NVIDIA models either **self-hosted** (local NIM containers
you operate) or against **NVIDIA-hosted cloud endpoints** — chosen entirely by the
`*_BASE_URL` variables. There is no code change; point them at a local service or
at the cloud. This applies to **all three deployment modes** (Docker Compose, Helm/EKS,
local `nat serve`).

| Model | Self-hosted (default) | Cloud |
|-------|------------------------|-------|
| Instruct (Llama 3.3 70B) | `INSTRUCT_BASE_URL=http://instruct-llm:8000/v1` | `INSTRUCT_BASE_URL=https://integrate.api.nvidia.com/v1` + `INSTRUCT_API_KEY=$NVIDIA_API_KEY` |
| Nemotron (49B) | `NEMOTRON_BASE_URL=http://nim-llm…:8000/v1` | `NEMOTRON_BASE_URL=https://integrate.api.nvidia.com/v1` + `NEMOTRON_API_KEY=$NVIDIA_API_KEY` |
| Reranker (optional) | `RERANKER_NIM_URL=http://nemoretriever-ranking-ms.<rag-ns>.svc.cluster.local:8000` | hosted ranking NIM URL |
| Embedding (optional) | `EMBEDDING_NIM_URL=http://nemoretriever-embedding-ms.<rag-ns>.svc.cluster.local:8000` | hosted embedding NIM URL |

How each mode self-hosts the two **required** LLMs:

- **Docker Compose:** `--profile kxta-instruct-llm` runs a local Instruct NIM;
  Nemotron comes from the RAG blueprint's `nim-llm-ms`. `docker-compose-kx-local.yaml`
  runs a **dedicated local Nemotron** container. To use cloud instead, set the
  `*_BASE_URL` to `https://integrate.api.nvidia.com/v1` (or run with
  `configs/hosted-config.yml`).
- **Helm / EKS:** the bundled **`nim-llm` subchart (`enabled: true`)** self-hosts
  Instruct. Nemotron defaults to the co-deployed RAG blueprint's `nim-llm`. To
  self-host Nemotron in-chart instead (e.g. standalone / air-gap), enable the
  **`nim-llm-nemotron`** subchart and point `backendEnvVars.NEMOTRON_BASE_URL` at
  `http://nemotron-llm:8000/v1` (budget a second GPU). To use cloud, override the
  `backendEnvVars.*_BASE_URL` to the hosted endpoint and disable the subcharts.
- **Local dev:** `configs/config.yml` defaults to local URLs; `configs/hosted-config.yml`
  points both at the cloud.

> **Air-gap:** there is no cloud option — both `*_BASE_URL` must point at local
> NIMs. Pre-stage each NIM's model cache on a connected machine
> (`download-to-cache -p <profile>`), transfer it, and serve from the local cache
> with `NGC_API_KEY` **unset**. For Helm, enable `nim-llm` + `nim-llm-nemotron`
> (and reuse the RAG cluster's reranker/embedding NIMs). For self-hosting the
> Nemotron NIM specifically on RTX PRO 6000 Blackwell, see the air-gap runbook.

### Standalone (no RAG)

The NVIDIA RAG blueprint is **optional**. AI Trader Agents boots and serves without
it: the `rag` agent is gated on a TCP reachability probe of `RAG_SERVER_URL`, so when
RAG is absent it simply reports *"RAG not deployed"* and drops out of routing — nothing
crashes. A standalone deployment is therefore **KDB-X + the external
market-intelligence agents + the two LLMs**.

**Still works without RAG:** `kdb`, `kdb_pit`, `market_data`, `news_headlines`,
`fundamentals`, `sec_filings` (queries SEC EDGAR directly), `macro_economic`,
`web_search`, `onetick`. When no enabled source returns a relevant answer the
orchestrator falls back to web search.

**The one hard requirement is the two LLMs** (reasoning + writing), which RAG normally
co-hosts. Supply them yourself — cloud (`*_BASE_URL → https://integrate.api.nvidia.com/v1`)
or self-hosted (`nim-llm` + `nim-llm-nemotron` subcharts). See
[Self-hosted vs. cloud NIMs](#self-hosted-vs-cloud-nims-and-air-gap).

**What you lose without RAG:**
- the `rag` document-retrieval agent;
- document **ingestion** via the RAG ingestor — the upload/collection UI, the demo
  collections, `POST /sec/ingest`, and loading *new* documents for `kdb_docs`
  (querying an already-populated KDB-X vector table still works if an embedding
  endpoint is configured);
- the reranker/embedding NIMs usually borrowed from the RAG cluster — relevancy
  falls back to the LLM judge, and semantic routing/dedup falls back to keyword/Jaccard
  (both optional; can also be pointed at cloud or self-hosted).

**Deploy standalone:**
- **Docker Compose** — bring up only the `kxta` (and `kdb`) profiles, skip the RAG
  stack, and set `INSTRUCT_BASE_URL`/`NEMOTRON_BASE_URL` to cloud or local NIMs:
  ```bash
  docker compose -f deploy/compose/docker-compose.yaml --profile kxta --profile kdb up -d
  ```
- **Helm / EKS** — leave `RAG_SERVER_URL`/`RAG_INGEST_URL` unset/unreachable (the `rag`
  agent auto-hides) and self-host both LLMs:
  ```bash
  helm upgrade --install kxta deploy/helm/kxta -n kxta \
    --set nim-llm.enabled=true \
    --set nim-llm-nemotron.enabled=true \
    --set backendEnvVars.NEMOTRON_BASE_URL=http://nemotron-llm:8000/v1 \
    --set backendEnvVars.RAG_SERVER_URL="" --set backendEnvVars.RAG_INGEST_URL=""
  ```
  (or point `INSTRUCT_BASE_URL`/`NEMOTRON_BASE_URL` at cloud and disable the subcharts).

### KDB+ MCP Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `KDB_ENABLED` | `false` | Enable KDB+ data source |
| `KDB_USE_NAT_CLIENT` | `true` | Use NAT's native MCP client (requires NAT 1.3.0+) |
| `KDB_MCP_ENDPOINT` | `https://kdbxmcp.kxailab.com/mcp` | KDB+ MCP server endpoint |
| `KDB_TIMEOUT` | `30` | KDB+ query timeout in seconds |
| `KDB_API_KEY` | Optional | API key for authenticated KDB+ MCP servers |

### RAG Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RAG_SERVER_URL` | `http://rag-server:8081/v1` | RAG server endpoint |
| `RAG_INGEST_URL` | `http://ingestor-server:8082/v1` | RAG ingestor endpoint (also used by `/sec/ingest`) |
| `RAG_API_KEY` | Optional | API key for RAG service |

### NIM Enhancements (enhance-when-present)

Each NIM below is an **upgrade slot**: when its env is unset (or the NIM is
unreachable) the blueprint transparently falls back to its prior behavior, so
hosted, on-prem, and air-gapped deployments all work. On a cluster that already
runs the NVIDIA RAG blueprint, the reranker/embedding/ingest NIMs can be reused
at zero additional GPU cost.

| Variable | Default | Description |
|----------|---------|-------------|
| `RERANKER_NIM_URL` | Optional | NeMo Retriever reranker NIM (`/v1/ranking`) for relevancy gating; falls back to the LLM-as-judge |
| `RERANKER_NIM_MODEL` | `nvidia/llama-nemotron-rerank-1b-v2` | Reranker model id |
| `RERANKER_RELEVANCY_THRESHOLD` | `0.0` | Min logit for a result to count as relevant |
| `EMBEDDING_NIM_URL` | Optional | Embedding NIM (`/v1/embeddings`) for semantic source-routing + query dedup; falls back to keyword routing / Jaccard |
| `EMBEDDING_NIM_MODEL` | `nvidia/llama-nemotron-embed-1b-v2` | Embedding model id (2048-dim) |
| `SEMANTIC_DEDUP_THRESHOLD` | `0.70` | Cosine similarity above which two queries are duplicates |
| `SUMMARIZATION_MODEL_NAME` | Optional | Dedicated small NIM for source-agent summarization (chattiest path); unset → blueprint LLM |
| `SUMMARIZATION_BASE_URL` | `INSTRUCT_BASE_URL` | Endpoint for the summarization NIM |
| `NEMOGUARD_MODEL_NAME` | Optional | NemoGuard content-safety model (with `KXTA_APPLY_GUARDRAIL=nemoguard`) |
| `NEMOGUARD_BASE_URL` | `INSTRUCT_BASE_URL` | NemoGuard endpoint |
| `SQL_GUARD_MAX_LEN` | `4000` | Max length of KDB-chat generated SQL (execution rail; always on) |
| `NIM_MAX_MODEL_LEN` | `32768` | Served context window; drives agent content-truncation budget |

`KXTA_APPLY_GUARDRAIL` accepts: `false` (off), `true` (LLM relevancy gate),
`nemoguard` (NemoGuard content-safety input rail on Q&A questions + research topics).

### OneTick Cloud (source agent)

| Variable | Default | Description |
|----------|---------|-------------|
| `ONETICK_CLIENT_ID` | Optional | OneTick Cloud OAuth2 client id (enables the OneTick agent) |
| `ONETICK_CLIENT_SECRET` | Optional | OneTick Cloud OAuth2 secret |
| `ONETICK_HTTP_ADDRESS` | `https://rest.cloud.onetick.com:443` | OneTick REST endpoint |
| `ONETICK_TOKEN_URL` | OMD realm token URL | OAuth2 token endpoint |

### Source Agent Data Providers

Each external data-source agent is enabled by the presence of its credential.
When unset, the agent reports `needs_key` / `unavailable` in `GET /source_agents`
and is skipped during routing. (Yahoo-backed `fundamentals` needs no key.)

| Variable | Default | Enables agent | Description |
|----------|---------|---------------|-------------|
| `ALPHAVANTAGE_API_KEY` | Optional | `market_data`, `news_headlines` | Alpha Vantage prices/volumes + news headlines; optional fallback for fundamentals |
| `FRED_API_KEY` | Optional | `macro_economic` | FRED macroeconomic series (free key from fred.stlouisfed.org) |
| `SEC_EDGAR_EMAIL` | `kxta@example.com` | `sec_filings` | SEC EDGAR identity sent as the HTTP User-Agent (not a secret) |
| `FIRECRAWL_API_KEY` | Optional | `web_search` | Firecrawl web research (also needs the `firecrawl-mcp` Node package); falls back to Tavily |
| `TAVILY_API_KEY` | Optional | `web_search` | Tavily web search (fallback web provider) |
| _(none — Yahoo Finance)_ | — | `fundamentals` | Company fundamentals via Yahoo; no key required |

### KDB-X Document & Table Selection

The `kdb_docs` (vector search) and `kdb` (time-series) agents read their data
selection from **Redis** (set inline in the UI agent picker, or via
`PUT /settings/kdb-docs` / `PUT /settings/kdb-tables`). The env vars below provide
the **fallback/default** when no Redis selection is present. `kdb_docs` also
requires an embedding endpoint (`KDB_VECTOR_EMBED_URL`, else `EMBEDDING_NIM_URL`,
else the hosted endpoint with `NVIDIA_API_KEY`). See [docs/kdb-docs-agent.md](kdb-docs-agent.md).

| Variable | Default | Description |
|----------|---------|-------------|
| `KDB_DB_HOST` | Optional | Direct KDB-X host:port for `kdb_docs` / `kdb_pit` (these agents are gated on it) |
| `KDB_MCP_INTERNAL` | `false` | Set `true` only when using the blueprint's bundled MCP (enables the data loader) |
| `KDB_VECTOR_TABLE` | `kxta_sec_nvda` | Default `kdb_docs` collection when none selected in Redis |
| `KDB_VECTOR_EMBED_URL` | falls back to `EMBEDDING_NIM_URL` / hosted | Embedding endpoint for `kdb_docs` query vectors |
| `KDB_VECTOR_EMBED_MODEL` | `nvidia/nv-embedqa-e5-v5` | Embedding model id for `kdb_docs` |
| `KDB_VECTOR_INDEX` / `KDB_VECTOR_METRIC` | Optional | Override the vector index name / distance metric |
| `KDB_VISIBLE_TABLES` | Optional | Comma-separated allowlist of KDB-X tables visible to `kdb` (narrowed further by the table picker) |

### Evaluation Module

These variables are used by the evaluation framework in `kxta/src/kxta/eval/`:

| Variable | Default | Description |
|----------|---------|-------------|
| `NVIDIA_API_BASE_URL` | `https://integrate.api.nvidia.com/v1` | NVIDIA API base URL |
| `NV_OAUTH_URL` | `https://prod.api.nvidia.com/oauth/api/v1/ssa/default/token` | NVIDIA OAuth token endpoint |
| `NV_AZURE_API_BASE` | `https://prod.api.nvidia.com/llm/v1/azure` | Azure LLM Gateway endpoint |
| `NV_CLIENT_ID` | Required for eval | NVIDIA client ID for LLM Gateway |
| `NV_CLIENT_SECRET` | Required for eval | NVIDIA client secret for LLM Gateway |

---

## Helm Chart Configuration

The Helm chart is located at `deploy/helm/kxta/`.

### Image Configuration

Default values in `values.yaml` use NVCR (public registry):

```yaml
# Backend image
image:
  repository: nvcr.io/nvidia/blueprint/aira-backend
  tag: v1.2.0
  pullPolicy: Always

# Frontend image
frontend:
  image:
    repository: nvcr.io/nvidia/blueprint/aira-frontend
    tag: v1.2.0
    pullPolicy: Always
```

#### Using a Private Registry (e.g., ECR)

Override in your values file (e.g., `aiq-values.yaml`):

```yaml
imagePullSecret:
  name: "ecr-secret"
  registry: "123456789.dkr.ecr.us-east-1.amazonaws.com"
  username: "AWS"
  password: ""  # Set via --set or IAM roles
  create: true

image:
  repository: 123456789.dkr.ecr.us-east-1.amazonaws.com/kxta-backend
  tag: latest
  pullPolicy: Always

frontend:
  image:
    repository: 123456789.dkr.ecr.us-east-1.amazonaws.com/kxta-frontend
    tag: latest
    pullPolicy: Always
```

### Backend Environment Variables

Configure via `backendEnvVars` in values:

```yaml
backendEnvVars:
  INSTRUCT_MODEL_NAME: "meta-llama/llama-3.3-70b-instruct"
  INSTRUCT_MODEL_TEMP: "0.0"
  NEMOTRON_MAX_TOKENS: "5000"
  INSTRUCT_MAX_TOKENS: "20000"
  INSTRUCT_BASE_URL: "http://instruct-llm:8000"
  INSTRUCT_API_KEY: "not-needed"
  NEMOTRON_MODEL_NAME: "nvidia/llama-3.3-nemotron-super-49b-v1.5"
  NEMOTRON_MODEL_TEMP: "0.5"
  NEMOTRON_BASE_URL: "http://nim-llm.rag.svc.cluster.local:8000"
  KXTA_APPLY_GUARDRAIL: "false"
  RAG_SERVER_URL: "http://rag-server.rag.svc.cluster.local:8081"
  RAG_INGEST_URL: "http://ingestor-server.rag.svc.cluster.local:8082"
  KDB_ENABLED: "false"
  KDB_USE_NAT_CLIENT: "true"
  KDB_MCP_ENDPOINT: "https://kdbxmcp.kxailab.com/mcp"
  KDB_TIMEOUT: "30"
```

### Frontend Configuration

```yaml
frontend:
  enabled: true
  service:
    type: NodePort
    port: 3000
    targetPort: 3000
    nodePort: 30080
  replicaCount: 1
```

### Secrets Configuration

```yaml
# NGC/NVIDIA API Secret
ngcApiSecret:
  name: "ngc-api"
  password: ""  # Set via --set
  create: true

# Tavily API Secret
tavilyApiSecret:
  name: "tavily-secret"
  password: ""  # Set via --set
  create: true

# KDB+ API Secret (optional)
kdbApiSecret:
  name: "kdb-secret"
  password: ""
  create: false  # Enable if using authenticated KDB+ MCP
```

### Redis Configuration

```yaml
redis:
  enabled: true
  image:
    repository: redis
    tag: 7-alpine
    pullPolicy: IfNotPresent
```

### Installation Example

```bash
# Install with NVCR images (default)
helm upgrade --install kxta deploy/helm/kxta \
  -n kxta --create-namespace \
  --set ngcApiSecret.password=$NVIDIA_API_KEY \
  --set tavilyApiSecret.password=$TAVILY_API_KEY

# Install with custom values file (e.g., ECR images)
helm upgrade --install kxta deploy/helm/kxta \
  -n kxta --create-namespace \
  -f deploy/helm/kxta/aiq-values.yaml \
  --set ngcApiSecret.password=$NVIDIA_API_KEY \
  --set tavilyApiSecret.password=$TAVILY_API_KEY
```

---

## Docker Compose Configuration

Docker Compose files support image overrides via environment variables.

### Environment Variables for Images

| Variable | Default | Description |
|----------|---------|-------------|
| `INSTRUCT_LLM_IMAGE` | `nvcr.io/nim/meta/llama-3.3-70b-instruct:1.13.1` | Instruct LLM NIM image |
| `KXTA_BACKEND_IMAGE` | `nvcr.io/nvidia/blueprint/aira-backend:v1.2.0` | Backend image |
| `KXTA_FRONTEND_IMAGE` | `nvcr.io/nvidia/blueprint/aira-frontend:v1.2.0` | Frontend image |
| `KXTA_LOAD_FILES_IMAGE` | `nvcr.io/nvidia/blueprint/aira-load-files:v1.2.0` | File loader image |

### Usage Examples

```bash
# Use default NVCR images
docker compose -f deploy/compose/docker-compose.yaml --profile kxta up -d

# Use custom images
export KXTA_BACKEND_IMAGE=123456789.dkr.ecr.us-east-1.amazonaws.com/kxta-backend:latest
export KXTA_FRONTEND_IMAGE=123456789.dkr.ecr.us-east-1.amazonaws.com/kxta-frontend:latest
docker compose -f deploy/compose/docker-compose.yaml --profile kxta up -d

# With all environment variables
export NVIDIA_API_KEY=nvapi-xxx
export NGC_API_KEY=$NVIDIA_API_KEY
export TAVILY_API_KEY=your-tavily-key
export USERID=$(id -u)
docker compose -f deploy/compose/docker-compose.yaml \
  --profile kxta-instruct-llm --profile kxta up -d
```

### Other Docker Compose Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_DIRECTORY` | `./` | NIM model cache directory |
| `USERID` | Required | User ID for container permissions |
| `KXTA_LLM_MS_GPU_ID` | `2,3` | GPU IDs for LLM NIM |
| `RAG_SERVER_URL` | `http://rag-server:8081/v1` | RAG server URL |
| `RAG_INGEST_URL` | `http://ingestor-server:8082/v1` | RAG ingestor URL |
| `INFERENCE_ORIGIN` | `http://kxta-backend:3838` | Backend URL for frontend |

---

## Configuration Files

### configs/config.yml

The main configuration file supports environment variable substitution:

```yaml
kdb:
  mcp:
    endpoint: ${KDB_MCP_ENDPOINT:-https://kdbxmcp.kxailab.com/mcp}
    enabled: ${KDB_ENABLED:-false}
    timeout: ${KDB_TIMEOUT:-30}

llms:
  instruct:
    base_url: ${INSTRUCT_BASE_URL:-http://kxta-instruct-llm:8000/v1}
  nemotron:
    base_url: ${NEMOTRON_BASE_URL:-http://nim-llm-ms:8000/v1}

rag:
  url: ${RAG_SERVER_URL:-http://rag-server:8081/v1}
```

### configs/hosted-config.yml

Use this config when using NVIDIA hosted NIMs:

```yaml
llms:
  instruct:
    base_url: https://integrate.api.nvidia.com/v1
  nemotron:
    base_url: https://integrate.api.nvidia.com/v1
```

---

## Quick Reference

### Minimal Production Setup

```bash
# Required environment variables
export NVIDIA_API_KEY=nvapi-xxx
export TAVILY_API_KEY=tvly-xxx  # Optional, for web search

# Helm install
helm upgrade --install kxta deploy/helm/kxta \
  -n kxta --create-namespace \
  --set ngcApiSecret.password=$NVIDIA_API_KEY \
  --set tavilyApiSecret.password=$TAVILY_API_KEY \
  --set backendEnvVars.KDB_ENABLED=true  # Enable KDB+ if needed
```

### Development Setup

```bash
# Local development with hot reload
cd frontend && npm run dev  # Frontend on :5173
uv run nat serve --config_file configs/config.yml --host 0.0.0.0 --port 3838  # Backend
```
