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

This document provides a comprehensive reference for all configurable values in the AI-Q Research Assistant.

## Table of Contents

- [Environment Variables](#environment-variables)
  - [Core Service Configuration](#core-service-configuration)
  - [LLM Configuration](#llm-configuration)
  - [KDB+ MCP Configuration](#kdb-mcp-configuration)
  - [RAG Configuration](#rag-configuration)
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
| `AIRA_APPLY_GUARDRAIL` | `false` | Enable/disable relevancy guardrails |
| `AIRA_HOSTED_NIMS` | `false` | Use hosted NIMs vs local deployment |

### LLM Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `INSTRUCT_BASE_URL` | `http://aira-instruct-llm:8000/v1` | Instruct LLM endpoint |
| `INSTRUCT_MODEL_NAME` | `meta-llama/llama-3.3-70b-instruct` | Instruct model name |
| `INSTRUCT_MODEL_TEMP` | `0.0` | Instruct model temperature |
| `INSTRUCT_MAX_TOKENS` | `20000` | Max tokens for instruct model |
| `INSTRUCT_API_KEY` | `not-needed` | API key for instruct LLM (local) |
| `NEMOTRON_BASE_URL` | `http://nim-llm-ms:8000/v1` | Nemotron reasoning model endpoint |
| `NEMOTRON_MODEL_NAME` | `nvidia/llama-3.3-nemotron-super-49b-v1.5` | Nemotron model name |
| `NEMOTRON_MODEL_TEMP` | `0.5` | Nemotron model temperature |
| `NEMOTRON_MAX_TOKENS` | `5000` | Max tokens for Nemotron model |
| `NEMOTRON_API_KEY` | From secret | API key for Nemotron LLM |

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
| `RAG_INGEST_URL` | `http://ingestor-server:8082/v1` | RAG ingestor endpoint |
| `RAG_API_KEY` | Optional | API key for RAG service |

### Evaluation Module

These variables are used by the evaluation framework in `aira/src/aiq_aira/eval/`:

| Variable | Default | Description |
|----------|---------|-------------|
| `NVIDIA_API_BASE_URL` | `https://integrate.api.nvidia.com/v1` | NVIDIA API base URL |
| `NV_OAUTH_URL` | `https://prod.api.nvidia.com/oauth/api/v1/ssa/default/token` | NVIDIA OAuth token endpoint |
| `NV_AZURE_API_BASE` | `https://prod.api.nvidia.com/llm/v1/azure` | Azure LLM Gateway endpoint |
| `NV_CLIENT_ID` | Required for eval | NVIDIA client ID for LLM Gateway |
| `NV_CLIENT_SECRET` | Required for eval | NVIDIA client secret for LLM Gateway |

---

## Helm Chart Configuration

The Helm chart is located at `deploy/helm/aiq-aira/`.

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
  repository: 123456789.dkr.ecr.us-east-1.amazonaws.com/aira-backend
  tag: latest
  pullPolicy: Always

frontend:
  image:
    repository: 123456789.dkr.ecr.us-east-1.amazonaws.com/aira-frontend
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
  AIRA_APPLY_GUARDRAIL: "false"
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
helm upgrade --install aiq-aira deploy/helm/aiq-aira \
  -n aiq --create-namespace \
  --set ngcApiSecret.password=$NVIDIA_API_KEY \
  --set tavilyApiSecret.password=$TAVILY_API_KEY

# Install with custom values file (e.g., ECR images)
helm upgrade --install aiq-aira deploy/helm/aiq-aira \
  -n aiq --create-namespace \
  -f deploy/helm/aiq-aira/aiq-values.yaml \
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
| `AIRA_BACKEND_IMAGE` | `nvcr.io/nvidia/blueprint/aira-backend:v1.2.0` | Backend image |
| `AIRA_FRONTEND_IMAGE` | `nvcr.io/nvidia/blueprint/aira-frontend:v1.2.0` | Frontend image |
| `AIRA_LOAD_FILES_IMAGE` | `nvcr.io/nvidia/blueprint/aira-load-files:v1.2.0` | File loader image |

### Usage Examples

```bash
# Use default NVCR images
docker compose -f deploy/compose/docker-compose.yaml --profile aira up -d

# Use custom images
export AIRA_BACKEND_IMAGE=123456789.dkr.ecr.us-east-1.amazonaws.com/aira-backend:latest
export AIRA_FRONTEND_IMAGE=123456789.dkr.ecr.us-east-1.amazonaws.com/aira-frontend:latest
docker compose -f deploy/compose/docker-compose.yaml --profile aira up -d

# With all environment variables
export NVIDIA_API_KEY=nvapi-xxx
export NGC_API_KEY=$NVIDIA_API_KEY
export TAVILY_API_KEY=your-tavily-key
export USERID=$(id -u)
docker compose -f deploy/compose/docker-compose.yaml \
  --profile aira-instruct-llm --profile aira up -d
```

### Other Docker Compose Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_DIRECTORY` | `./` | NIM model cache directory |
| `USERID` | Required | User ID for container permissions |
| `AIRA_LLM_MS_GPU_ID` | `2,3` | GPU IDs for LLM NIM |
| `RAG_SERVER_URL` | `http://rag-server:8081/v1` | RAG server URL |
| `RAG_INGEST_URL` | `http://ingestor-server:8082/v1` | RAG ingestor URL |
| `INFERENCE_ORIGIN` | `http://aira-backend:3838` | Backend URL for frontend |

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
    base_url: ${INSTRUCT_LLM_BASE_URL:-http://aira-instruct-llm:8000/v1}
  nemotron:
    base_url: ${NEMOTRON_LLM_BASE_URL:-http://nim-llm-ms:8000/v1}

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
helm upgrade --install aiq-aira deploy/helm/aiq-aira \
  -n aiq --create-namespace \
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
