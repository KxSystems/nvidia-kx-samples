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

# AIQ-KX Blueprint Deployment Guide

A comprehensive guide for deploying the AI-Q Research Assistant with KDB-X (KX) financial data integration.

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Supported Platforms & Container Registries](#supported-platforms--container-registries)
5. [Deployment Options](#deployment-options)
6. [Docker Compose Deployment](#docker-compose-deployment)
   - [Setting Up Persistent Environment Variables](#setting-up-persistent-environment-variables)
7. [Quick Start (External KDB-X)](#quick-start-external-kdb-x)
8. [Full Deployment (Internal KDB-X)](#full-deployment-internal-kdb-x)
   - [Obtaining Required Credentials](#obtaining-required-credentials)
9. [Configuration Reference](#configuration-reference)
10. [Loading Historical Data](#loading-historical-data)
11. [Verification](#verification)
12. [Troubleshooting](#troubleshooting)
13. [Production Considerations](#production-considerations)
14. [Appendix](#appendix)
    - [Kubernetes Secrets Configuration](#kubernetes-secrets-configuration)

---

## Overview

### What is AIQ-KX?

AIQ-KX is an enhanced version of the AI-Q Research Assistant that integrates with KDB-X, a high-performance time-series database optimized for financial data. This blueprint enables:

- **Real-time financial data queries** - Access stock prices, trading volumes, and market data
- **Historical data analysis** - Query years of tick-by-tick financial data
- **Multi-source research** - Combine KDB-X data with RAG documents and web search
- **Natural language queries** - Ask questions in plain English, translated to q/SQL

### Key Features

| Feature | Description |
|---------|-------------|
| KDB-X MCP Integration | Query KDB-X databases using the Model Context Protocol |
| Intelligent Query Routing | Automatically routes queries to the best data source |
| Batch Data Loading | Load historical stock data with progress tracking |
| Agent Activity Monitoring | Real-time visibility into search operations with timing |
| Crash Recovery | Resume interrupted data loads from last checkpoint |

### Data Sources

The AIQ-KX blueprint supports three data sources that can be used individually or combined:

1. **KDB-X** - Time-series financial data (stocks, trades, quotes)
2. **RAG** - Document retrieval from uploaded collections
3. **Web Search** - Real-time web search via Tavily API

---

## Architecture

```
                                    +------------------+
                                    |   Frontend UI    |
                                    |   (React/Vite)   |
                                    +--------+---------+
                                             |
                                             v
+------------------+              +----------+----------+              +------------------+
|                  |              |                     |              |                  |
|  KDB-X MCP       +<-------------+   AIRA Backend     +------------->+   RAG Server     |
|  Server          |   MCP/HTTP   |   (FastAPI/NAT)    |   HTTP/REST  |   (NeMo)         |
|                  |              |                     |              |                  |
+------------------+              +----------+----------+              +------------------+
                                             |
                                             v
                                  +----------+----------+
                                  |                     |
                                  |   LLM Services      |
                                  |   (Instruct +       |
                                  |    Nemotron)        |
                                  |                     |
                                  +---------------------+
```

### Component Overview

| Component | Purpose | Default Port |
|-----------|---------|--------------|
| Frontend | React UI for research workflows | 3000 (NodePort 30080) |
| Backend | FastAPI service with LangGraph workflows | 3838 |
| Redis | Job tracking for data loader | 6379 |
| KDB-X MCP | Financial data queries via MCP | External |
| RAG Server | Document retrieval | 8081 |
| Instruct LLM | Report writing (Llama 3.3 70B) | 8000 |
| Nemotron LLM | Query planning (Nemotron 49B) | 8000 |

---

## Prerequisites

### Required

- **Kubernetes Cluster** - Any CNCF-conformant cluster (1.19+):
  - Cloud: EKS, GKE, AKS, DigitalOcean, Linode
  - Self-hosted: kubeadm, k3s, RKE2, OpenShift
  - Local: minikube, kind, k3d, Docker Desktop
- **Helm 3.x** - Package manager for Kubernetes
- **kubectl** - Kubernetes CLI configured for your cluster
- **NVIDIA API Key** - For hosted LLM services
- **Container Registry Access** - NVCR (default), Docker Hub, or any private registry

### Optional

- **Tavily API Key** - For web search fallback
- **KDB-X MCP Endpoint** - For financial data queries (default: KX public endpoint)
- **GPU Nodes** - Required only for self-hosted LLM NIMs

### Resource Requirements

| Deployment Type | CPU | Memory | GPU | Storage |
|-----------------|-----|--------|-----|---------|
| Hosted NIMs | 4 cores | 8GB | None | 10GB |
| Self-hosted NIMs | 16 cores | 64GB | 2x A100 | 100GB |

---

## Supported Platforms & Container Registries

This deployment is **cloud-agnostic** and works with any standard Kubernetes cluster and OCI-compliant container registry. No cloud-specific features are required.

### AIQ-KX Pre-built Images

AIQ-KX images are available from the **KX Portal Registry**:

```
portal.dl.kx.com/aiq-kx-backend:1.0.2
portal.dl.kx.com/aiq-kx-frontend:1.0.2
```

> **Registry Authentication:** Access to `portal.dl.kx.com` requires KX Portal credentials. Contact [KX Sales](https://kx.com/contact/) for access.

> **Note:** These images are different from the base NVCR images (`nvcr.io/nvidia/blueprint/aira-*`) which do NOT include KDB integration.

Development builds are also available on `dev.downloads.kx.com` for testing.

### Building Custom Images (Optional)

If you need to customize the images:

```bash
# Build KDB-enabled images
docker build -f deploy/Dockerfile -t your-registry/aiq-kx-backend:latest .
docker build -f frontend/Dockerfile -t your-registry/aiq-kx-frontend:latest ./frontend

# Push to your registry
docker push your-registry/aiq-kx-backend:latest
docker push your-registry/aiq-kx-frontend:latest
```

### Supported Kubernetes Distributions

| Distribution | Type | Notes |
|--------------|------|-------|
| Amazon EKS | Cloud | Managed |
| Google GKE | Cloud | Managed |
| Azure AKS | Cloud | Managed |
| DigitalOcean Kubernetes | Cloud | Managed |
| Vanilla Kubernetes (kubeadm) | Self-hosted | Standard installation |
| k3s / k3d | Self-hosted | Lightweight, ideal for edge |
| Rancher RKE / RKE2 | Enterprise | Full Rancher support |
| OpenShift | Enterprise | Use `oc` instead of `kubectl` |
| minikube | Local | Development and testing |
| kind | Local | CI/CD pipelines |
| Docker Desktop | Local | macOS/Windows development |

### Container Registry Options

Choose the registry that fits your infrastructure:

#### Option A: KX Portal (Recommended for AIQ-KX)

Pre-built AIQ-KX images with full KDB integration. Requires KX Portal credentials.

```bash
# AIQ-KX from KX Portal (default)
helm upgrade --install aiq-kx deploy/helm/aiq-aira \
  -n aiq --create-namespace \
  --set imagePullSecret.username="your-email@kx.com" \
  --set imagePullSecret.password="your-kx-portal-token" \
  --set ngcApiSecret.password="$NVIDIA_API_KEY"
```

#### Option B: NVIDIA NGC (Base Version Only)

> **Note:** NVCR images are the **base AI-Q Research Assistant** without KDB integration. For AIQ-KX with KDB support, use Option A (KX Portal).

Uses pre-built images from NVIDIA Container Registry. No image building required.

```bash
# Base version (no KDB) - uses default NVCR images
helm upgrade --install aiq deploy/helm/aiq-aira \
  -n aiq --create-namespace \
  --set ngcApiSecret.password="$NVIDIA_API_KEY"
```

#### Option C: Private Registry

Best for enterprise deployments with custom registry requirements.

```yaml
# values-docker-hub.yaml
image:
  repository: docker.io/youruser/aira-backend
  tag: "v1.2.0"

imagePullSecret:
  create: true
  registry: "docker.io"
  username: "your-dockerhub-username"
  password: ""  # Set via --set flag
```

```bash
helm upgrade --install aiq-kx deploy/helm/aiq-aira \
  -n aiq --create-namespace \
  -f deploy/helm/aiq-aira/examples/values-docker-hub.yaml \
  --set imagePullSecret.password="your-access-token" \
  --set ngcApiSecret.password="$NVIDIA_API_KEY"
```

#### Option C: Private Registry (Harbor, GitLab, Quay.io)

Best for enterprise deployments and air-gapped environments.

```yaml
# values-private-registry.yaml
image:
  repository: registry.company.com/aiq/aira-backend
  tag: "v1.2.0"

imagePullSecret:
  create: true
  registry: "registry.company.com"
  username: "deploy-user"
  password: ""  # Set via --set flag
```

**Harbor Example:**
```bash
helm upgrade --install aiq-kx deploy/helm/aiq-aira \
  -n aiq -f deploy/helm/aiq-aira/examples/values-private-registry.yaml \
  --set imagePullSecret.registry="harbor.mycompany.com" \
  --set imagePullSecret.username="robot\$aiq-reader" \
  --set imagePullSecret.password="robot-token" \
  --set ngcApiSecret.password="$NVIDIA_API_KEY"
```

**GitLab Container Registry Example:**
```bash
helm upgrade --install aiq-kx deploy/helm/aiq-aira \
  -n aiq -f deploy/helm/aiq-aira/examples/values-private-registry.yaml \
  --set imagePullSecret.registry="registry.gitlab.com" \
  --set imagePullSecret.username="deploy-token-user" \
  --set imagePullSecret.password="gldt-xxxxxxxxxxxx" \
  --set ngcApiSecret.password="$NVIDIA_API_KEY"
```

#### Option D: AWS ECR

Best for AWS-native deployments with IAM integration.

```bash
# Get ECR credentials
ECR_PASSWORD=$(aws ecr get-login-password --region us-east-1)

helm upgrade --install aiq-kx deploy/helm/aiq-aira \
  -n aiq -f deploy/helm/aiq-aira/aiq-values.yaml \
  --set imagePullSecret.password="$ECR_PASSWORD" \
  --set ngcApiSecret.password="$NVIDIA_API_KEY"
```

#### Option E: Google Artifact Registry

```bash
# Authenticate with GCP
gcloud auth configure-docker us-central1-docker.pkg.dev

helm upgrade --install aiq-kx deploy/helm/aiq-aira \
  -n aiq \
  --set image.repository="us-central1-docker.pkg.dev/project/repo/aira-backend" \
  --set ngcApiSecret.password="$NVIDIA_API_KEY"
```

### Creating Image Pull Secrets Manually

If not using Helm's `imagePullSecret.create`, create the secret manually:

```bash
kubectl -n aiq create secret docker-registry my-registry-secret \
  --docker-server=YOUR_REGISTRY \
  --docker-username=YOUR_USERNAME \
  --docker-password=YOUR_PASSWORD \
  --docker-email=YOUR_EMAIL
```

Then reference in your values file:

```yaml
imagePullSecrets:
  - name: my-registry-secret
```

### Example Values Files

Pre-configured examples are available in `deploy/helm/aiq-aira/examples/`:

| File | Description |
|------|-------------|
| `values.yaml` (default) | **KX Portal registry** (`portal.dl.kx.com`) |
| `values-generic-k8s.yaml` | Minimal config for any K8s cluster |
| `values-hybrid.yaml` | Hybrid cloud + on-prem deployment |
| `values-private-registry.yaml` | Enterprise private registry template |

---

## Deployment Options

AIQ-KX supports two deployment modes for KDB-X integration:

### Option 1: External KDB-X MCP Server (Recommended for Production)

Connect to your existing KDB-X MCP server:
- **Recommended for production** - Use your organization's KDB-X infrastructure
- Only requires the MCP endpoint URL
- Single Helm chart: `aiq-aira`
- Your MCP server manages security, scaling, and data governance

```yaml
# Simply point to your existing MCP server
backendEnvVars:
  KDB_ENABLED: "true"
  KDB_MCP_ENDPOINT: "https://your-mcp-server.internal:8000/mcp"
```

### Option 2: Internal KDB-X (Development & Testing Only)

Deploy a KDB-X database and MCP server within your cluster:
- **For testing and development only** - Quick setup for evaluation
- Requires KX Portal account with bearer token and license
- Two Helm charts: `aiq-aira` + `kdb-x-mcp-server`
- Sample data included for immediate testing

> **Important:** The MCP server deployed by this blueprint is intended for **testing and demonstration purposes only**. For production deployments, you should use your organization's existing KDB-X MCP server that includes:
> - Enterprise-grade security and authentication
> - Appropriate data governance policies
> - Production-scale performance tuning
> - Integration with your existing monitoring and alerting

### Comparison

| Aspect | External MCP (Production) | Internal MCP (Dev/Test) |
|--------|---------------------------|-------------------------|
| Use Case | Production workloads | Development & testing |
| KX Credentials | Your existing setup | Required (bearer + license) |
| Data Location | Your infrastructure | Your cluster |
| Security | Your policies | Basic |
| Helm Charts | 1 (aiq-aira) | 2 (aiq-aira + kdb-x-mcp-server) |
| Scalability | Your infrastructure | Limited |

### Option 3: Docker Compose (Development/Testing)

Deploy all services on a single server using Docker Compose:
- Ideal for development, testing, or single-server deployments
- Can reuse existing NVIDIA RAG blueprint NIMs
- No Kubernetes required

See [Docker Compose Deployment](#docker-compose-deployment) section below.

---

## Docker Compose Deployment

This section covers deploying AIQ-KX using Docker Compose on a single server.

### Docker Compose Prerequisites

- Docker Engine 24.0+ with Compose V2
- NVIDIA Container Toolkit (for GPU support)
- Existing NVIDIA RAG blueprint (optional, for NIM reuse)

### Runtime Installation vs Pre-built Images

The Docker Compose configurations use **runtime installation** by default:

- **KDB-X Database**: Uses `python:3.12-slim-bookworm` and installs KDB-X at startup
- **KDB-X MCP Server**: Uses `ghcr.io/astral-sh/uv:python3.12-bookworm` and clones from GitHub at startup

First startup takes 2-3 minutes for KDB-X and 1-2 minutes for MCP server. Credentials are passed via environment variables (`KDB_BEARER_TOKEN`, `KDB_LICENSE_B64`).

**Alternative: Build and Push Pre-built Images**

If you prefer faster startup times with pre-built images, use the provided build script which uses Docker BuildKit secrets to securely handle credentials (credentials are NOT stored in image layers):

```bash
# Set credentials as environment variables
export KDB_BEARER_TOKEN="your-bearer-token"
export KDB_B64_LICENSE="$(cat kc.lic | base64 | tr -d '\n')"

# Build KDB-X image using BuildKit secrets
cd deploy/helm/kdb-x-mcp-server
./scripts/build-kdbx-image.sh \
  --repository your-registry/kdbx \
  --tag latest \
  --push
```

The image is built securely - credentials cannot be extracted via `docker history`.

Then update the compose file to use your image:
```yaml
kdbx:
  image: your-registry/kdbx:latest
  command: ["/opt/kx/start.sh"]
  # Remove the entrypoint that installs at runtime
```

### Setting Up Persistent Environment Variables

**Important:** Environment variables must be set every time you SSH into the server. To make them persistent, add them to your shell profile.

#### Step 1: Create Environment File

Create a secure environment file for your credentials:

```bash
# Create directory for secrets
mkdir -p ~/.config/aiq-kx
chmod 700 ~/.config/aiq-kx

# Create environment file
cat > ~/.config/aiq-kx/env << 'EOF'
# NVIDIA API Key - for hosted LLM services
# Get from: https://build.nvidia.com/ → Account Settings → API Key
export NVIDIA_API_KEY="nvapi-xxxxxxxxxxxxxxxxxxxx"
export NGC_API_KEY="$NVIDIA_API_KEY"

# KX Portal Bearer Token - for KDB-X installer download
# Get from: https://portal.kx.com → Profile → Tokens → Generate new token
export KDB_BEARER_TOKEN="your-bearer-token-here"

# KDB-X License (base64 encoded)
# Get license from: https://kx.com/kdb-personal-edition/
# Encode with: cat kc.lic | base64 | tr -d '\n'
export KDB_LICENSE_B64="your-base64-encoded-license"

# Tavily API Key (optional) - for web search
# Get from: https://tavily.com/
export TAVILY_API_KEY="tvly-xxxxxxxxxxxxxxxxxxxx"
EOF

# Secure the file
chmod 600 ~/.config/aiq-kx/env
```

#### Step 2: Add to Shell Profile

Add automatic loading to your `.bashrc` or `.zshrc`:

```bash
# Add to ~/.bashrc (for bash) or ~/.zshrc (for zsh)
echo '
# Load AIQ-KX environment variables
if [ -f ~/.config/aiq-kx/env ]; then
    source ~/.config/aiq-kx/env
fi
' >> ~/.bashrc

# Apply immediately
source ~/.bashrc
```

#### Step 3: Verify Variables

```bash
# Verify all variables are set
echo "NVIDIA_API_KEY: ${NVIDIA_API_KEY:0:10}..."
echo "KDB_BEARER_TOKEN: ${KDB_BEARER_TOKEN:0:10}..."
echo "KDB_LICENSE_B64 length: ${#KDB_LICENSE_B64}"
```

### Deploy with Docker Compose

#### Option A: Reuse Existing RAG NIMs (Recommended)

If you already have the NVIDIA RAG blueprint running with NIMs:

```bash
# Clone the repository
git clone https://github.com/KxSystems/nvidia-kx-samples.git
cd nvidia-kx-samples/KX-AIQ-nvidia-rag-blueprint

# Verify the nvidia-rag network exists
docker network ls | grep nvidia-rag

# Deploy AIQ-KX (connects to existing NIMs)
docker compose -f deploy/compose/docker-compose-kx-reuse-nim.yaml up -d

# Watch startup logs
docker compose -f deploy/compose/docker-compose-kx-reuse-nim.yaml logs -f
```

#### Option B: Full Local Deployment

Deploy everything including LLM NIMs (requires GPUs):

```bash
# Deploy with self-hosted NIMs
docker compose -f deploy/compose/docker-compose-kx-local.yaml up -d
```

### Verify Docker Compose Deployment

```bash
# Check all containers are running
docker ps --format "table {{.Names}}\t{{.Status}}"

# Expected output:
# NAMES                 STATUS
# aiq-kx-frontend       Up X minutes
# aiq-kx-backend        Up X minutes
# kdb-mcp-server        Up X minutes (healthy)
# kdbx                  Up X minutes
# aiq-kx-redis          Up X minutes

# Test backend health
curl -s http://localhost:3838/aiqhealth

# Test KDB-X connection
docker exec kdbx /opt/kx/.kx/bin/q -c "tables[]"

# Access the UI
echo "Frontend available at: http://$(hostname):3000"
```

### Docker Compose Troubleshooting

#### Container Not Starting

```bash
# Check logs for specific container
docker logs kdbx --tail 100
docker logs kdb-mcp-server --tail 100

# Restart specific service
docker compose -f deploy/compose/docker-compose-kx-reuse-nim.yaml restart kdbx
```

#### Environment Variables Not Set

```bash
# Verify variables are loaded
env | grep -E "NVIDIA|KDB|NGC"

# If empty, source the env file
source ~/.config/aiq-kx/env
```

#### KDB-X Installer Fails

```bash
# Check bearer token is valid
echo "Token length: ${#KDB_BEARER_TOKEN}"

# Test download manually
curl -sI --oauth2-bearer "$KDB_BEARER_TOKEN" \
  https://portal.dl.kx.com/assets/raw/kdb-x/install_kdb/~latest~/install_kdb.sh
# Should return HTTP 200
```

---

## Quick Start (External KDB-X)

If you already have a KDB-X MCP server running, use this quick start:

```bash
# 1. Clone the repository
git clone https://github.com/KxSystems/nvidia-kx-samples.git
cd nvidia-kx-samples/KX-AIQ-nvidia-rag-blueprint

# 2. Set required environment variables
export NVIDIA_API_KEY="nvapi-xxx"
export TAVILY_API_KEY="tvly-xxx"  # Optional
export KDB_MCP_ENDPOINT="http://your-mcp-server:8000/mcp"  # Your MCP endpoint

# 3. Deploy with Helm (update KDB_MCP_ENDPOINT in aiq-values.yaml first)
helm upgrade --install aiq-kx deploy/helm/aiq-aira \
  -n aiq --create-namespace \
  -f deploy/helm/aiq-aira/aiq-values.yaml \
  --set ngcApiSecret.password=$NVIDIA_API_KEY \
  --set tavilyApiSecret.password=$TAVILY_API_KEY

# 4. Wait for pods to be ready
kubectl -n aiq rollout status deployment/aiq-kx-aira-backend

# 5. Access the UI
kubectl -n aiq port-forward svc/aiq-kx-aira-frontend 3000:3000
# Open http://localhost:3000
```

---

## Full Deployment (Internal KDB-X)

This section provides step-by-step instructions for deploying AIQ-KX with an internal KDB-X database and MCP server.

### Prerequisites for Internal Deployment

Before starting, you'll need:

1. **KX Portal Account** - Register at [portal.kx.com](https://portal.kx.com)
2. **Bearer Token** - Generate from KX Portal → Profile → Tokens
3. **KDB-X License** - Base64-encoded license file (`cat kc.lic | base64`)
4. **Container Registry** - Docker Hub, Harbor, or private registry access

### Obtaining Required Credentials

This section explains how to obtain all credentials needed for AIQ-KX deployment.

#### 1. NVIDIA API Key (Required)

Used for hosted LLM services (Llama 3.3 Instruct, Nemotron).

**How to obtain:**
1. Go to [build.nvidia.com](https://build.nvidia.com/)
2. Sign in or create an NVIDIA account
3. Navigate to any model (e.g., Llama 3.3 70B Instruct)
4. Click "Get API Key" or find it in your account settings
5. Copy the key (starts with `nvapi-`)

**Usage:**
```bash
export NVIDIA_API_KEY="nvapi-xxxxxxxxxxxxxxxxxxxx"
```

#### 2. Tavily API Key (Optional)

Used for web search fallback when RAG results are insufficient.

**How to obtain:**
1. Go to [tavily.com](https://tavily.com/)
2. Sign up for an account
3. Navigate to API Keys in your dashboard
4. Generate a new API key (starts with `tvly-`)

**Usage:**
```bash
export TAVILY_API_KEY="tvly-xxxxxxxxxxxxxxxxxxxx"
```

#### 3. KX Portal Bearer Token (Required for Internal KDB-X)

Used to download and install KDB-X at container startup.

**How to obtain:**
1. Go to [portal.kx.com](https://portal.kx.com)
2. Sign in or register for a KX account
3. Navigate to **Profile → Tokens**
4. Click **Generate new token**
5. Copy the OAuth bearer token

> **Important:** The bearer token is invalidated if you change your KX Portal password. Generate a new token after password changes.

**Usage:**
```yaml
# In your kdb-values.yaml
kdbx:
  build:
    bearerToken: "your-bearer-token-here"
```

#### 4. KDB-X License (Required for Internal KDB-X)

PyKX and KDB-X require a valid license to operate.

**How to obtain:**
1. Go to [kx.com/kdb-personal-edition](https://kx.com/kdb-personal-edition/) for personal use
2. Or contact KX sales for commercial licenses
3. Download the license file (`kc.lic` for personal, `k4.lic` for commercial)
4. Base64-encode the license:
   ```bash
   cat kc.lic | base64 | tr -d '\n'
   ```
5. Copy the single-line base64 output

**Usage:**
```yaml
# In your kdb-values.yaml
kdbx:
  build:
    licenseB64: "base64-encoded-license-here"
```

#### 5. Container Registry Credentials (Varies by Registry)

**Docker Hub:**
1. Go to [hub.docker.com](https://hub.docker.com) → Account Settings → Security
2. Generate an **Access Token** (recommended over password)
3. Use your Docker Hub username and access token

**Harbor:**
1. Navigate to your Harbor project
2. Create a **Robot Account** with pull permissions
3. Use the robot account name (e.g., `robot$project-name`) and token

**GitLab Container Registry:**
1. Navigate to your GitLab project → Settings → Access Tokens
2. Create a **Deploy Token** with `read_registry` scope
3. Use the deploy token username and password

**AWS ECR:**
```bash
# Get temporary credentials (valid 12 hours)
ECR_PASSWORD=$(aws ecr get-login-password --region us-east-1)
```

#### Credential Security Best Practices

1. **Never commit credentials** to version control
2. **Use environment variables** or `--set` flags for sensitive values
3. **Rotate tokens regularly**, especially bearer tokens
4. **Use secrets managers** in production (HashiCorp Vault, AWS Secrets Manager)
5. **Check `.gitignore`** covers your custom values files:
   ```
   my-values.yaml
   kdb-values.yaml
   *secret*.yaml
   ```

### Step 1: Prepare Environment

```bash
# Clone the repository
git clone https://github.com/KxSystems/nvidia-kx-samples.git
cd nvidia-kx-samples/KX-AIQ-nvidia-rag-blueprint

# Verify cluster access
kubectl cluster-info
kubectl get nodes

# Set environment variables
export NVIDIA_API_KEY="nvapi-xxx"
export TAVILY_API_KEY="tvly-xxx"  # Optional

# For ECR users
export AWS_PROFILE="your-profile"
export ECR_REGISTRY="123456789.dkr.ecr.us-east-1.amazonaws.com"
```

### Step 2: Create Namespace

```bash
kubectl create namespace aiq
```

### Step 3: Deploy KDB-X MCP Server

First, create a values file from the provided template:

```bash
# Copy the example template
cp deploy/helm/kdb-x-mcp-server/examples/internal-runtime-values.yaml kdb-values.yaml

# Edit the file and replace all REPLACE_WITH_* placeholders:
# - REPLACE_WITH_YOUR_REGISTRY → Your container registry (e.g., 123456789.dkr.ecr.us-east-1.amazonaws.com)
# - REPLACE_WITH_YOUR_BEARER_TOKEN → KX Portal OAuth token (https://portal.kx.com → Profile → Tokens)
# - REPLACE_WITH_YOUR_LICENSE_B64 → Base64-encoded license (cat kc.lic | base64)

# Example using sed (or edit manually):
sed -i '' \
  -e 's|REPLACE_WITH_YOUR_REGISTRY|123456789.dkr.ecr.us-east-1.amazonaws.com|g' \
  -e 's|REPLACE_WITH_YOUR_BEARER_TOKEN|your-actual-bearer-token|g' \
  -e 's|REPLACE_WITH_YOUR_LICENSE_B64|your-base64-encoded-license|g' \
  kdb-values.yaml
```

> **Important:** The `kdb-values.yaml` file contains sensitive credentials. It is automatically ignored by `.gitignore`. Never commit this file to version control.

Deploy the KDB-X MCP server:

```bash
# Get ECR password (for AWS users)
ECR_PASSWORD=$(aws ecr get-login-password --region us-east-1 --profile $AWS_PROFILE)

# Deploy KDB-X MCP server
helm upgrade --install kdb-mcp deploy/helm/kdb-x-mcp-server \
  -n aiq \
  -f kdb-values.yaml \
  --set imagePullSecret.password="$ECR_PASSWORD"

# Wait for pods to be ready (KDB-X takes ~2-3 minutes to install)
echo "Waiting for KDB-X to initialize..."
kubectl -n aiq rollout status deployment/kdb-mcp-kdb-x-mcp-server-kdbx --timeout=300s
kubectl -n aiq rollout status deployment/kdb-mcp-kdb-x-mcp-server --timeout=120s
```

Verify KDB-X deployment:

```bash
# Check pods
kubectl -n aiq get pods -l app.kubernetes.io/instance=kdb-mcp

# Expected output:
# NAME                                             READY   STATUS    AGE
# kdb-mcp-kdb-x-mcp-server-xxx                     1/1     Running   2m
# kdb-mcp-kdb-x-mcp-server-kdbx-xxx                1/1     Running   2m

# Check MCP server logs
kubectl -n aiq logs deployment/kdb-mcp-kdb-x-mcp-server --tail=20
```

### Step 4: Deploy AIQ-KX Backend and Frontend

The `aiq-values.yaml` should point to the internal KDB-X MCP server:

```yaml
# In deploy/helm/aiq-aira/aiq-values.yaml
backendEnvVars:
  # ... other settings ...

  # KDB-X Configuration - Internal MCP server
  KDB_ENABLED: "true"
  KDB_USE_NAT_CLIENT: "true"
  KDB_MCP_ENDPOINT: "http://kdb-mcp-kdb-x-mcp-server.aiq.svc.cluster.local:8000/mcp"
  KDB_TIMEOUT: "30"
```

Deploy the main application:

```bash
# Get ECR password if expired
ECR_PASSWORD=$(aws ecr get-login-password --region us-east-1 --profile $AWS_PROFILE)

# Deploy AIQ-KX
helm upgrade --install aiq-kx deploy/helm/aiq-aira \
  -n aiq \
  -f deploy/helm/aiq-aira/aiq-values.yaml \
  --set ngcApiSecret.password="$NVIDIA_API_KEY" \
  --set tavilyApiSecret.password="$TAVILY_API_KEY" \
  --set imagePullSecret.password="$ECR_PASSWORD"

# Wait for deployment
kubectl -n aiq rollout status deployment/aiq-kx-aira-backend
kubectl -n aiq rollout status deployment/aiq-kx-aira-frontend
```

### Step 5: Verify Full Deployment

```bash
# Check all pods
kubectl -n aiq get pods

# Expected output:
# NAME                                             READY   STATUS    AGE
# aiq-kx-aira-backend-xxx                          1/1     Running   1m
# aiq-kx-aira-frontend-xxx                         1/1     Running   1m
# aiq-kx-redis-xxx                                 1/1     Running   1m
# kdb-mcp-kdb-x-mcp-server-xxx                     1/1     Running   5m
# kdb-mcp-kdb-x-mcp-server-kdbx-xxx                1/1     Running   5m

# Check services
kubectl -n aiq get svc

# Test backend health
kubectl -n aiq exec deployment/aiq-kx-aira-backend -- curl -s http://localhost:3838/aiqhealth
# Expected: {"value":{"status":"OK"}}

# Test MCP connectivity from backend
kubectl -n aiq exec deployment/aiq-kx-aira-backend -- \
  curl -s http://kdb-mcp-kdb-x-mcp-server.aiq.svc.cluster.local:8000/mcp \
  -X POST -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "tools/list", "id": 1}'
# Should return a JSON response (even if error, confirms connectivity)
```

### Step 6: Access the Application

```bash
# Port-forward frontend and backend
kubectl -n aiq port-forward svc/aiq-kx-aira-frontend 3000:3000 &
kubectl -n aiq port-forward svc/aiq-kx-aira-backend 3838:3838 &

# Open http://localhost:3000
```

---

## Configuration Reference

### KDB-X Settings

| Setting | Values | Description |
|---------|--------|-------------|
| `KDB_ENABLED` | `true`/`false` | Enable KDB-X data source |
| `KDB_USE_NAT_CLIENT` | `true`/`false` | Use NAT MCP client (recommended) |
| `KDB_MCP_ENDPOINT` | URL | KDB-X MCP server endpoint |
| `KDB_MCP_INTERNAL` | `true`/`false` | **Important:** Set to `true` only when MCP server is deployed by this blueprint. Enables data loader (write operations). Default: `false` (read-only mode for external MCP servers). |
| `KDB_TIMEOUT` | seconds | Query timeout |
| `KDB_API_KEY` | string | API key for authenticated servers |

### LLM Settings

| Setting | Description |
|---------|-------------|
| `INSTRUCT_BASE_URL` | Instruct LLM endpoint |
| `INSTRUCT_MODEL_NAME` | Model identifier |
| `NEMOTRON_BASE_URL` | Nemotron reasoning model endpoint |
| `NEMOTRON_MODEL_NAME` | Model identifier |

### Full Configuration Example

```yaml
# complete-kx-values.yaml

replicaCount: 1

nim-llm:
  enabled: false  # Use hosted NIMs

redis:
  enabled: true

frontend:
  enabled: true
  replicaCount: 1
  service:
    type: NodePort
    port: 3000
    nodePort: 30080

backendEnvVars:
  # LLM Configuration
  INSTRUCT_MODEL_NAME: "meta/llama-3.3-70b-instruct"
  INSTRUCT_MODEL_TEMP: "0.0"
  INSTRUCT_MAX_TOKENS: "20000"
  INSTRUCT_BASE_URL: "https://integrate.api.nvidia.com/v1"

  NEMOTRON_MODEL_NAME: "nvidia/llama-3.3-nemotron-super-49b-v1.5"
  NEMOTRON_MODEL_TEMP: "0.5"
  NEMOTRON_MAX_TOKENS: "5000"
  NEMOTRON_BASE_URL: "https://integrate.api.nvidia.com/v1"

  # RAG Configuration
  RAG_SERVER_URL: "http://rag-server.rag.svc.cluster.local:8081"
  RAG_INGEST_URL: "http://ingestor-server.rag.svc.cluster.local:8082"

  # KDB-X Configuration
  KDB_ENABLED: "true"
  KDB_USE_NAT_CLIENT: "true"
  KDB_MCP_ENDPOINT: "https://kdbxmcp.kxailab.com/mcp"
  KDB_TIMEOUT: "30"

  # Guardrails
  AIRA_APPLY_GUARDRAIL: "false"
```

---

## Loading Historical Data

The AIQ-KX blueprint includes a data loader for populating KDB-X with historical stock data.

> **Warning: Testing & Development Only**
>
> The KDB Data Loader is designed for **testing and demonstration purposes only**. It is specifically configured to work with the deployment included in this repository and **should not be used in production environments**.
>
> **Why this matters:**
> - The MCP server's security checks are relaxed at runtime to allow INSERT operations
> - Loading data **clears all existing tables** before inserting new data
> - Data includes synthetic intraday trades/quotes generated from real daily OHLCV
> - For production systems, use proper ETL pipelines with appropriate data governance
>
> This feature enables quick testing of the AIQ-KX integration without requiring a pre-configured KDB-X database with financial data.

> **Note:** When deploying with internal KDB-X (`kdbx.enabled: true`), the database comes **pre-loaded with sample data** for immediate testing:
> - **Date Range**: 2023-2024
> - **Symbols**: AAPL, GOOG, MSFT, TSLA, AMZN, NVDA, META, RIVN, BYD, BA
> - **Data**: 50,000 trades, 50,000 quotes, 730 daily records
>
> Use the Data Loader below to add real historical data for your specific symbols and date ranges.

### Accessing the Data Loader

1. Open the application UI
2. Click the **Settings** icon (gear) in the top right
3. Navigate to **KDB Data Loader** tab

### Loading Stock Data

1. **Enter Stock Symbols** - Comma-separated list (e.g., `AAPL, GOOG, MSFT, NVDA`)
2. **Select Date Range** - Choose start and end dates
3. **Click "Load Data"** - Progress will display in real-time

### Progress Monitoring

The data loader shows:
- Current phase (Clearing, Fetching, Inserting)
- Per-symbol progress
- Row counts and timing
- Overall completion percentage

### Batch Insert Feature

Large datasets are automatically batched:
- Default batch size: 5000 rows
- Prevents memory issues
- Shows per-batch progress

### Crash Recovery

If the browser closes or connection drops:
1. Job state is saved in Redis
2. On reconnection, active jobs are detected
3. Progress resumes from last checkpoint

---

## Verification

### Test KDB-X Integration

1. **Select KDB-X Data Source**
   - In the UI, ensure "KDB-X" is selected as a data source

2. **Generate a Financial Query**
   - Topic: "NVIDIA stock performance analysis"
   - The system should generate KDB-specific queries

3. **Check Agent Activity**
   - Expand "Agent Activity" panel
   - Look for "KDB-X query" events with timing

### Test Report Generation

1. **Create a Research Topic**
   - Enter: "Compare AAPL and MSFT stock performance in 2024"

2. **Configure Sources**
   - Enable: KDB-X
   - Optional: Enable RAG or Web Search

3. **Generate Report**
   - Click "Generate Queries" then "Generate Report"
   - Monitor Agent Activity for KDB queries

### Verify API Endpoints

```bash
# Health check
curl http://localhost:3838/aiqhealth

# Check available collections
curl http://localhost:3838/default_collections

# API documentation
open http://localhost:3838/docs
```

---

## Troubleshooting

### Common Issues

#### Pod CrashLoopBackOff

```bash
# Check pod logs
kubectl -n aiq logs -f deployment/aiq-kx-aira-backend

# Common causes:
# - Invalid NVIDIA_API_KEY
# - Cannot reach LLM endpoints
# - Redis connection failure
```

#### KDB-X MCP Server Crashes

**Symptom:** `kdb-mcp-kdb-x-mcp-server` pod in CrashLoopBackOff

```bash
# Check MCP server logs
kubectl -n aiq logs deployment/kdb-mcp-kdb-x-mcp-server --tail=50

# Common causes and solutions:

# 1. License error: "license error: kc.lic"
#    - Verify license is correctly base64 encoded
#    - Check QLIC environment variable points to /opt/kx/lic
#    - Verify license file is mounted correctly

# 2. PyKX import failure
#    - Check that kdb-license-secret exists
kubectl -n aiq get secret kdb-license-secret -o yaml

# 3. Cannot connect to KDB-X database
#    - Ensure kdb-mcp-kdb-x-mcp-server-kdbx pod is running first
kubectl -n aiq get pods -l app.kubernetes.io/component=kdbx-database
```

#### KDB-X Database Init Failure

**Symptom:** `kdb-mcp-kdb-x-mcp-server-kdbx` pod stuck in `Init:Error` or `Init:CrashLoopBackOff`

```bash
# Check init container logs
kubectl -n aiq logs deployment/kdb-mcp-kdb-x-mcp-server-kdbx -c install-kdbx --tail=50

# Common causes:

# 1. Bearer token expired or disabled
#    Error: "disabled token due to recent account password change"
#    Solution: Generate a new bearer token from https://portal.kx.com

# 2. Invalid license
#    Solution: Ensure license is correctly base64 encoded:
#    cat kc.lic | base64

# 3. Network issues downloading KDB-X
#    Solution: Check pod can reach portal.dl.kx.com
```

#### KDB-X Queries Failing

```bash
# Check backend logs for MCP errors
kubectl -n aiq logs deployment/aiq-kx-aira-backend | grep -i kdb

# Verify KDB_ENABLED is true
kubectl -n aiq get deployment aiq-kx-aira-backend -o jsonpath='{.spec.template.spec.containers[0].env}' | jq '.[] | select(.name=="KDB_ENABLED")'

# Test MCP connectivity from backend
kubectl -n aiq exec deployment/aiq-kx-aira-backend -- \
  curl -s http://kdb-mcp-kdb-x-mcp-server.aiq.svc.cluster.local:8000/mcp \
  -X POST -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "tools/list", "id": 1}'
```

#### Frontend Cannot Reach Backend

**Symptom:** nginx error "host not found in upstream"

```bash
# Check frontend logs
kubectl -n aiq logs deployment/aiq-kx-aira-frontend --tail=20

# Verify INFERENCE_ORIGIN environment variable
kubectl -n aiq get deployment aiq-kx-aira-frontend -o jsonpath='{.spec.template.spec.containers[0].env}'

# The INFERENCE_ORIGIN should match the backend service name:
# http://aiq-kx-aira-backend.aiq.svc.cluster.local:3838

# If using custom release name, update accordingly
```

#### Image Pull Errors

```bash
# Check image pull secret
kubectl -n aiq get secret

# Verify secret contents
kubectl -n aiq get secret ecr-secret -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d

# For ECR, refresh credentials (expires every 12 hours)
ECR_PASSWORD=$(aws ecr get-login-password --region us-east-1 --profile your-profile)
kubectl -n aiq delete secret ecr-secret 2>/dev/null || true
kubectl -n aiq create secret docker-registry ecr-secret \
  --docker-server=123456789.dkr.ecr.us-east-1.amazonaws.com \
  --docker-username=AWS \
  --docker-password="$ECR_PASSWORD"
```

#### Orphaned Secrets Blocking Helm Install

**Symptom:** Helm error "Secret exists and cannot be imported into the current release"

```bash
# Delete orphaned secret
kubectl -n aiq delete secret <secret-name>

# Then retry helm install
```

### Debug Commands

```bash
# View all resources
kubectl -n aiq get all

# Describe pod for events
kubectl -n aiq describe pod <pod-name>

# Stream backend logs
kubectl -n aiq logs -f deployment/aiq-kx-aira-backend

# Interactive shell in backend
kubectl -n aiq exec -it deployment/aiq-kx-aira-backend -- /bin/bash

# Check Redis connectivity
kubectl -n aiq exec -it deployment/aiq-kx-aira-backend -- redis-cli -h aiq-kx-redis ping

# Check KDB-X database is running with sample data
kubectl -n aiq logs deployment/kdb-mcp-kdb-x-mcp-server-kdbx -c kdbx --tail=20
# Should show: "KDB-X initialized with sample data (2023-2024)"

# Force pod recreation after config changes
kubectl -n aiq delete pods -l app.kubernetes.io/instance=kdb-mcp
kubectl -n aiq delete pods -l app.kubernetes.io/instance=aiq-kx
```

### Helm Troubleshooting

```bash
# View Helm releases
helm list -n aiq

# Check release history
helm history aiq-kx -n aiq
helm history kdb-mcp -n aiq

# Rollback to previous version
helm rollback aiq-kx -n aiq
helm rollback kdb-mcp -n aiq

# Complete cleanup and fresh install
helm uninstall aiq-kx -n aiq
helm uninstall kdb-mcp -n aiq
kubectl -n aiq delete secrets --all
kubectl -n aiq delete pvc --all
```

---

## Production Considerations

### High Availability

For production deployments, increase replica counts:

```yaml
replicaCount: 3

frontend:
  replicaCount: 2

redis:
  # Consider using Redis Cluster or managed Redis
  enabled: true
```

### Resource Limits

Add resource constraints:

```yaml
resources:
  backend:
    requests:
      cpu: "1"
      memory: "2Gi"
    limits:
      cpu: "4"
      memory: "8Gi"
```

### Monitoring

Enable Phoenix tracing for observability:

```yaml
phoenix:
  enabled: true
```

Access Phoenix UI:

```bash
kubectl -n aiq port-forward svc/aiq-kx-phoenix 6006:6006
# Open http://localhost:6006
```

### Security

1. **Use Secrets Management** - Integrate with HashiCorp Vault or AWS Secrets Manager
2. **Enable TLS** - Configure ingress with TLS certificates
3. **Network Policies** - Restrict pod-to-pod communication
4. **RBAC** - Configure appropriate Kubernetes RBAC

### Backup and Recovery

1. **Redis Persistence** - Enable AOF/RDB persistence for job state
2. **Configuration Backup** - Store Helm values in version control
3. **Data Retention** - Configure KDB-X data retention policies

---

## Appendix

### Helm Commands Reference

```bash
# Install
helm upgrade --install aiq-kx deploy/helm/aiq-aira -n aiq -f values.yaml

# Upgrade
helm upgrade aiq-kx deploy/helm/aiq-aira -n aiq -f values.yaml

# Rollback
helm rollback aiq-kx -n aiq

# Uninstall
helm uninstall aiq-kx -n aiq

# View current values
helm get values aiq-kx -n aiq

# View all releases
helm list -n aiq
```

### Useful kubectl Commands

```bash
# Scale deployment
kubectl -n aiq scale deployment/aiq-kx-aira-backend --replicas=3

# Restart deployment
kubectl -n aiq rollout restart deployment/aiq-kx-aira-backend

# View logs with timestamps
kubectl -n aiq logs -f deployment/aiq-kx-aira-backend --timestamps

# Port-forward multiple services
kubectl -n aiq port-forward svc/aiq-kx-aira-backend 3838:3838 &
kubectl -n aiq port-forward svc/aiq-kx-aira-frontend 3000:3000 &
```

### Environment Variables Quick Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NVIDIA_API_KEY` | Yes | - | NVIDIA API access |
| `TAVILY_API_KEY` | No | - | Web search |
| `KDB_ENABLED` | No | `false` | Enable KDB-X |
| `KDB_MCP_ENDPOINT` | No | KX public | MCP server URL |
| `RAG_SERVER_URL` | No | Internal | RAG service |
| `REDIS_URL` | No | Internal | Redis for jobs |

### Kubernetes Secrets Configuration

AIQ-KX uses Kubernetes secrets to securely store sensitive credentials. This section explains how secrets are created, used, and managed.

#### Secret Architecture

| Secret Name | Key | Used By | Purpose |
|-------------|-----|---------|---------|
| `ngc-api` | `NVIDIA_API_KEY` | Backend | LLM API authentication (Instruct & Nemotron) |
| `tavily-secret` | `TAVILY_API_KEY` | Backend | Web search API (optional) |
| `kdb-secret` | `KDB_API_KEY` | Backend | Authenticated KDB-X MCP servers (optional) |
| `kdb-license-secret` | `KDB_LICENSE_B64` | KDB-X MCP Server | PyKX license (internal deployment) |
| `ngc-secret` | `.dockerconfigjson` | All Pods | Container registry pull credentials |

#### Creating Secrets via Helm

Secrets are automatically created when deploying with Helm if you provide values:

```bash
# Deploy with secrets
helm upgrade --install aiq-kx deploy/helm/aiq-aira \
  -n aiq --create-namespace \
  --set ngcApiSecret.password="nvapi-xxxxxxxxxxxx" \
  --set tavilyApiSecret.password="tvly-xxxxxxxxxxxx" \
  --set imagePullSecret.password="your-registry-password"
```

#### Creating Secrets Manually

If Helm doesn't create secrets (or you need to update them):

```bash
# Create NGC API secret (required)
kubectl -n aiq create secret generic ngc-api \
  --from-literal=NVIDIA_API_KEY="nvapi-xxxxxxxxxxxx" \
  --from-literal=NGC_API_KEY="nvapi-xxxxxxxxxxxx" \
  --from-literal=NGC_CLI_API_KEY="nvapi-xxxxxxxxxxxx" \
  --dry-run=client -o yaml | kubectl apply -f -

# Create Tavily secret (optional)
kubectl -n aiq create secret generic tavily-secret \
  --from-literal=TAVILY_API_KEY="tvly-xxxxxxxxxxxx" \
  --dry-run=client -o yaml | kubectl apply -f -

# Create KDB API secret (optional, for authenticated MCP servers)
kubectl -n aiq create secret generic kdb-secret \
  --from-literal=KDB_API_KEY="your-kdb-api-key" \
  --dry-run=client -o yaml | kubectl apply -f -
```

#### Updating Existing Secrets

To update a secret without deleting it:

```bash
# Method 1: Patch the secret
kubectl -n aiq patch secret ngc-api --type='json' -p='[
  {"op": "replace", "path": "/data/NVIDIA_API_KEY", "value": "'$(echo -n "nvapi-NEW-KEY-HERE" | base64)'"}
]'

# Method 2: Delete and recreate
kubectl -n aiq delete secret ngc-api
kubectl -n aiq create secret generic ngc-api \
  --from-literal=NVIDIA_API_KEY="nvapi-NEW-KEY-HERE"

# After updating secrets, restart the deployment to pick up changes
kubectl -n aiq rollout restart deployment/aiq-kx-aira-backend
```

#### Verifying Secrets

```bash
# List all secrets in namespace
kubectl -n aiq get secrets

# Check secret keys (without exposing values)
kubectl -n aiq get secret ngc-api -o jsonpath='{.data}' | jq -r 'keys[]'

# Verify secret is not empty (shows first 10 chars)
kubectl -n aiq get secret ngc-api -o jsonpath='{.data.NVIDIA_API_KEY}' | base64 -d | head -c 10; echo "..."

# Check if secret is mounted in pod
kubectl -n aiq exec deployment/aiq-kx-aira-backend -- env | grep -E "INSTRUCT_API_KEY|NEMOTRON_API_KEY"
```

#### Troubleshooting Secrets

**Problem: 401 Unauthorized errors when calling LLM**

This usually means the NVIDIA_API_KEY is empty or invalid:

```bash
# Check if the key is set
kubectl -n aiq get secret ngc-api -o jsonpath='{.data.NVIDIA_API_KEY}' | base64 -d | wc -c
# Should return > 0

# If empty, update the secret
kubectl -n aiq patch secret ngc-api --type='json' -p='[
  {"op": "replace", "path": "/data/NVIDIA_API_KEY", "value": "'$(echo -n "nvapi-YOUR-KEY" | base64)'"}
]'

# Restart the backend
kubectl -n aiq rollout restart deployment/aiq-kx-aira-backend
```

**Problem: Secrets not being picked up after update**

Kubernetes doesn't automatically reload secrets. Restart the deployment:

```bash
kubectl -n aiq rollout restart deployment/aiq-kx-aira-backend
kubectl -n aiq rollout status deployment/aiq-kx-aira-backend
```

**Problem: Secret exists but Helm fails with conflict**

This happens when a secret was created outside of Helm management:

```bash
# Option 1: Adopt the secret into Helm release
kubectl -n aiq annotate secret ngc-api \
  meta.helm.sh/release-name=aiq-kx \
  meta.helm.sh/release-namespace=aiq
kubectl -n aiq label secret ngc-api \
  app.kubernetes.io/managed-by=Helm

# Option 2: Delete and let Helm recreate
kubectl -n aiq delete secret ngc-api
helm upgrade --install aiq-kx deploy/helm/aiq-aira -n aiq \
  --set ngcApiSecret.password="nvapi-xxx"
```

#### Secrets in Docker Compose

For Docker Compose deployments, secrets are passed via environment variables:

```bash
# Set in your shell profile (~/.bashrc or ~/.zshrc)
export NVIDIA_API_KEY="nvapi-xxxxxxxxxxxx"
export TAVILY_API_KEY="tvly-xxxxxxxxxxxx"
export KDB_BEARER_TOKEN="your-bearer-token"
export KDB_LICENSE_B64="$(cat kc.lic | base64 | tr -d '\n')"

# Deploy (compose reads from environment)
docker compose -f deploy/compose/docker-compose-kx-reuse-nim.yaml up -d
```

Or use an environment file:

```bash
# Create .env file
cat > .env << 'EOF'
NVIDIA_API_KEY=nvapi-xxxxxxxxxxxx
NGC_API_KEY=nvapi-xxxxxxxxxxxx
TAVILY_API_KEY=tvly-xxxxxxxxxxxx
KDB_BEARER_TOKEN=your-bearer-token
KDB_LICENSE_B64=your-base64-license
EOF

# Deploy with env file
docker compose --env-file .env -f deploy/compose/docker-compose-kx-reuse-nim.yaml up -d
```

> **Security Note:** Never commit `.env` files to version control. The repository `.gitignore` already excludes `.env` files.

---

## Support

- **GitHub Issues**: [KxSystems/nvidia-kx-samples](https://github.com/KxSystems/nvidia-kx-samples/issues)
- **NVIDIA Developer Forums**: [forums.developer.nvidia.com](https://forums.developer.nvidia.com)
- **KX Documentation**: [code.kx.com](https://code.kx.com)
