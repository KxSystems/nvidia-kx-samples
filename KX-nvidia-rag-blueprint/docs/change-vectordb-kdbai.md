<!--
  SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->
# KDB.AI RAG Blueprint Deployment Guide

This guide provides step-by-step instructions for deploying the [NVIDIA RAG Blueprint](readme.md) with [KDB.AI](https://kdb.ai) as the vector database.

[KDB.AI](https://kdb.ai) is a high-performance vector database built on kdb+ technology, offering vector similarity search with enterprise-grade reliability and real-time analytics capabilities.

## Key Features

- **High-Performance Vector Search** - Built on kdb+ technology for fast similarity search
- **GPU Acceleration** - Optional NVIDIA cuVS integration for GPU-accelerated indexing (CAGRA)
- **Full RAG Pipeline Support** - NV-Ingest document ingestion, LangChain retrieval, metadata management
- **Multiple Index Types** - HNSW, Flat, IVF, IVFPQ for different scale and accuracy requirements
- **Enterprise Ready** - Production-grade reliability with persistent storage

> [!TIP]
> To navigate this page more easily, click the outline button at the top of the page. (<img src="assets/outline-button.png">)

## Table of Contents

**Getting Started**
- [Quick Start](#quick-start-docker-compose) - Get running in 5 minutes
- [Prerequisites](#prerequisites-and-important-considerations-before-you-start) - Requirements and system info
- [Required Credentials](#required-credentials) - NGC API key, KDB.AI license, registry access

**Deployment**
- [Docker Compose](#docker-compose-deployment) - Local and development deployment
- [8-GPU Docker Compose](#8-gpu-docker-compose-deployment) - Full stack on 8-GPU server
- [Helm/Kubernetes](#helmkubernetes-deployment) - Production Kubernetes deployment
- [Amazon EKS](#amazon-eks-deployment) - AWS cloud deployment

**Configuration & Tuning**
- [Environment Variables](#environment-variables-reference) - All configuration options
- [Performance Tuning](#index-types-and-performance-tuning) - Index selection and optimization

**Operations**
- [Verify Deployment](#verify-your-deployment) - Testing your setup
- [Troubleshooting](#troubleshooting) - Common issues and fixes
- [NGC Authentication Issues](#ngc-authentication-issues) - NIM pod failures
- [Debugging](#debugging) - Logs and diagnostics
- [Lessons Learned](#lessons-learned-from-deployment) - Real-world deployment insights
- [Known Issues](#known-issues-and-solutions) - Issues with solutions

**Advanced**
- [GPU Acceleration](#gpu-accelerated-kdbai-with-cuvs) - NVIDIA cuVS support

---

## Quick Start (Docker Compose)

For users who want to get started quickly, here's the minimal setup:

```bash
# 1. Get your KDB.AI license from https://kx.com (required - 90-day free trial available)

# 2. Set required environment variables
export KDBAI_REGISTRY_EMAIL="your-email@example.com"
export KDBAI_REGISTRY_TOKEN="your-bearer-token-from-kx-email"
export KDB_LICENSE_B64="your-base64-license-from-kx-email"
export APP_VECTORSTORE_NAME="kdbai"
export APP_VECTORSTORE_URL="http://kdbai:8082"

# 3. Create data directory with proper permissions
mkdir -p deploy/compose/volumes/kdbai && chmod 0777 deploy/compose/volumes/kdbai

# 4. Start KDB.AI
cd deploy/compose
docker compose -f vectordb.yaml --profile kdbai up -d

# 5. Verify it's running
curl http://localhost:8083/api/v2/ready

# 6. Restart RAG services to use KDB.AI
docker compose -f docker-compose-rag-server.yaml up -d
docker compose -f docker-compose-ingestor-server.yaml up -d
```

For detailed instructions, Helm deployment, or troubleshooting, continue reading below.

---

## Prerequisites and Important Considerations Before You Start

Review these requirements before deploying KDB.AI with the RAG Blueprint.

### Required

- **KDB.AI License** - You need a KDB.AI license from KX. Visit [kx.com](https://kx.com) to request a license (90-day free trial available).

- **Docker Registry Access** - You must authenticate with the KX Docker registry to pull the KDB.AI image. Credentials are provided in your KX welcome email.

### System Requirements

- **Operating System** - Linux kernel 4.18.0 or later
- **CPU** - Intel/AMD CPUs with AVX2 or ARM aarch64 with NEON
- **Memory** - Minimum 4GB RAM recommended (more for larger datasets)
- **Storage** - Persistent storage for vector data (SSD recommended)

### Index Types

KDB.AI supports multiple index types for different use cases:

| Index Type | Description | Best For |
|------------|-------------|----------|
| `hnsw` | Hierarchical Navigable Small World | Most use cases (recommended) |
| `flat` | Exact brute-force search | Small datasets (<10K vectors) |
| `ivf` | Inverted File Index | Large datasets (>100K vectors) |
| `ivfpq` | IVF with Product Quantization | Very large datasets, memory constrained |
| `cagra` | GPU-accelerated (cuVS) | High-throughput with NVIDIA GPU |

### Search Modes

- **Dense Search** - Default vector similarity search using L2 (Euclidean) distance
- **Cosine Similarity** - Use `CS` metric for normalized embeddings


## Required Credentials

This section lists all credentials required to deploy the KDB.AI RAG Blueprint and instructions on how to obtain them.

### Credentials Summary

| Credential | Required For | How to Obtain |
|------------|--------------|---------------|
| `NGC_API_KEY` | NVIDIA container registry, NIM services | [NVIDIA NGC Portal](#nvidia-ngc-api-key) |
| `KDB_LICENSE_B64` | KDB.AI server license | [KX Portal](#kdbai-license-from-kx) |
| `KDBAI_REGISTRY_EMAIL` | KDB.AI Docker registry | [KX Welcome Email](#kdbai-docker-registry-credentials) |
| `KDBAI_REGISTRY_TOKEN` | KDB.AI Docker registry | [KX Welcome Email](#kdbai-docker-registry-credentials) |

### NVIDIA NGC API Key

The NGC API key is required to:
- Pull NVIDIA container images from `nvcr.io` (via `ngc-secret`)
- Authenticate NIM services to download models (via `ngc-api` secret)
- Access cloud-hosted NVIDIA AI endpoints

**How to obtain:**

1. Go to [NVIDIA NGC](https://ngc.nvidia.com/)
2. Sign in or create a free account
3. Click your username in the top-right corner → **Setup**
4. Under **Personal Keys**, click **Generate Personal Key**
5. Copy the key (starts with `nvapi-...`)

**Set the environment variable:**

```bash
export NGC_API_KEY="nvapi-your-key-here"
```

> [!IMPORTANT]
> Never commit your NGC API key to version control. Use environment variables or secrets management.

> [!NOTE]
> For Kubernetes deployments, this single key is used to create **two separate secrets**:
> - `ngc-secret`: Docker registry credentials for pulling images from nvcr.io
> - `ngc-api`: Environment variables for NIM pods to authenticate and download models

### KDB.AI License from KX

The KDB.AI license is required to run the KDB.AI vector database server.

**How to obtain:**

1. Visit [https://kx.com](https://kx.com)
2. Click **Get Started** or **Try KDB.AI**
3. Fill out the registration form
4. You will receive a welcome email within 24-48 hours containing:
   - Your **KDB.AI license** (Base64-encoded string)
   - Your **Bearer token** for Docker registry authentication

**Set the environment variable:**

```bash
# The license string from your KX welcome email (Base64-encoded)
export KDB_LICENSE_B64="your-base64-license-string"
```

> [!NOTE]
> KDB.AI licenses are valid for **90 days**. Contact KX for renewal before expiration.

> [!WARNING]
> **KDB.AI vs KDB/X licenses are different!** Make sure you request a **KDB.AI** license specifically, not a KDB/X or kdb+ license. These are separate products with incompatible licenses. When decoded, a valid KDB.AI license shows readable license text. If you see binary garbage when running `echo "$KDB_LICENSE_B64" | base64 -d`, you may have the wrong license type.

### KDB.AI Docker Registry Credentials

These credentials are required to pull the KDB.AI Docker image from the KX private registry.

**Provided in your KX welcome email:**
- **Email**: The email address you used to register
- **Bearer Token**: Authentication token for the Docker registry

**Set the environment variables:**

```bash
export KDBAI_REGISTRY_EMAIL="your-email@example.com"
export KDBAI_REGISTRY_TOKEN="your-bearer-token-from-kx-email"
```

**Manual Docker login (if needed):**

```bash
echo "${KDBAI_REGISTRY_TOKEN}" | docker login portal.dl.kx.com -u "${KDBAI_REGISTRY_EMAIL}" --password-stdin
```

### Optional: KDB.AI API Key

For **self-hosted** KDB.AI deployments (Docker Compose or Kubernetes), no API key is required. Leave it empty:

```bash
export KDBAI_API_KEY=""
```

For **KDB.AI Cloud** deployments, you would need an API key from your KDB.AI Cloud dashboard.

### Security Best Practices

1. **Never hardcode credentials** in configuration files that are committed to version control
2. **Use environment variables** or secrets management systems (Kubernetes Secrets, HashiCorp Vault, AWS Secrets Manager)
3. **Rotate credentials** regularly and before they expire
4. **Use `.local` files** for local development:
   ```bash
   cp deploy/compose/.env.kdbai deploy/compose/.env.kdbai.local
   # Edit .env.kdbai.local with your credentials
   # .local files are gitignored
   ```

### Production Considerations

For production deployments:

| Component | Default | Production Recommendation |
|-----------|---------|---------------------------|
| MinIO Password | `minioadmin` | Change to a strong password |
| KDB.AI API Key | Empty (self-hosted) | Consider enabling authentication |
| NGC API Key | Required | Use Kubernetes Secrets |
| KDB License | Required | Store in Kubernetes Secrets |

**Required Kubernetes Secrets for Production:**

```bash
# All four secrets must be created before deployment

# 1. NGC Docker Registry (for pulling NVIDIA images)
kubectl create secret docker-registry ngc-secret \
  --docker-server=nvcr.io \
  --docker-username='$oauthtoken' \
  --docker-password="${NGC_API_KEY}" \
  -n <your-namespace>

# 2. NGC API (for NIM model authentication)
kubectl create secret generic ngc-api \
  --from-literal=NGC_API_KEY="${NGC_API_KEY}" \
  --from-literal=NGC_CLI_API_KEY="${NGC_API_KEY}" \
  --from-literal=NVIDIA_API_KEY="${NGC_API_KEY}" \
  -n <your-namespace>

# 3. KDB.AI Docker Registry
kubectl create secret docker-registry kdbai-registry-secret \
  --docker-server=portal.dl.kx.com \
  --docker-username="${KDBAI_REGISTRY_EMAIL}" \
  --docker-password="${KDBAI_REGISTRY_TOKEN}" \
  -n <your-namespace>

# 4. KDB.AI License
kubectl create secret generic kdbai-license-secret \
  --from-literal=KDB_LICENSE_B64="${KDB_LICENSE_B64}" \
  -n <your-namespace>
```


## Docker Compose Deployment

Follow these steps to deploy KDB.AI using Docker Compose.

### Step 1: Prepare the Data Directory

```bash
mkdir -p deploy/compose/volumes/kdbai
chmod 0777 deploy/compose/volumes/kdbai
```

### Step 2: Set Required Environment Variables

Set the Docker registry credentials and license from your KX welcome email:

```bash
# KX Docker Registry Authentication (REQUIRED)
export KDBAI_REGISTRY_EMAIL="your-email@example.com"
export KDBAI_REGISTRY_TOKEN="your-bearer-token"

# KDB.AI License (REQUIRED)
export KDB_LICENSE_B64="your-kdb-license-b64-string"

# KDB.AI Server Configuration
export KDBAI_THREADS=8  # Number of threads (Standard Edition limited to 24 cores)

# Vector Store Configuration
export APP_VECTORSTORE_NAME="kdbai"
export APP_VECTORSTORE_URL="http://kdbai:8082"
export APP_VECTORSTORE_SEARCHTYPE="dense"

# Optional: Index type
export KDBAI_INDEX_TYPE="hnsw"
export KDBAI_DATABASE="default"
```

Alternatively, use the provided environment file:

```bash
# Copy and customize the environment file
cp deploy/compose/.env.kdbai deploy/compose/.env.kdbai.local
# Edit .env.kdbai.local with your credentials and license
source deploy/compose/.env.kdbai.local
```

### Step 3: Start the KDB.AI Container

```bash
docker compose -f deploy/compose/vectordb.yaml --profile kdbai up -d
```

This will:
1. First run the `kdbai-registry-login` service to authenticate with the KX Docker registry
2. Pull the KDB.AI image from `portal.dl.kx.com/kdbai-db`
3. Start the KDB.AI server with:
   - Port 8083: REST API endpoint (mapped from internal 8081)
   - Port 8084: Client endpoint (mapped from internal 8082)

### Step 4: Verify KDB.AI is Running

```bash
# Check container status
docker ps | grep kdbai

# Check readiness endpoint
curl http://localhost:8083/api/v2/ready
```

### Step 5: Relaunch the RAG and Ingestion Services

```bash
docker compose -f deploy/compose/docker-compose-ingestor-server.yaml up -d
docker compose -f deploy/compose/docker-compose-rag-server.yaml up -d
```

### Step 6: Update the RAG UI Configuration

Access the RAG UI at `http://<host-ip>:8090`. In the UI, navigate to: Settings > Endpoint Configuration > Vector Database Endpoint → set to `http://kdbai:8082`.


## 8-GPU Docker Compose Deployment

This section covers deploying the full RAG stack on a server with 8 NVIDIA GPUs using a pre-configured deployment script. This is ideal for on-premises or dedicated GPU servers where you want to run all components locally with maximum performance.

> [!NOTE]
> **Development/Testing Only**: This deployment configuration is intended for development, testing, and proof-of-concept purposes. For production deployments, consider proper scaling strategies including:
> - High availability (HA) configurations with multiple replicas
> - Load balancing across multiple nodes
> - Kubernetes-based orchestration for auto-scaling
> - Proper resource limits and monitoring
> - Backup and disaster recovery procedures

### Prerequisites

1. **8 NVIDIA GPUs** - The deployment script is configured for 8x GPUs (tested on RTX PRO 6000 Blackwell with 96GB each, but works with other configurations)
2. **Docker with GPU support** - nvidia-container-toolkit installed
3. **Required credentials** (see [Required Credentials](#required-credentials)):
   - NGC API Key
   - KDB.AI license (base64 encoded)
   - KX Docker registry credentials

### GPU Assignment

The deployment automatically assigns GPUs to different services:

| GPU | Service | Memory Usage |
|-----|---------|--------------|
| 0, 1 | LLM (49B model with tensor parallelism) | ~98GB combined |
| 2 | Embedding + Reranker (shared) | ~8GB |
| 3 | Page Elements NIM | ~8GB |
| 4 | Graphic Elements NIM | ~8GB |
| 5 | Table Structure NIM + PaddleOCR (shared) | ~12GB |
| 6 | KDB.AI (vector database) | ~16GB |
| 7 | VLM (multimodal, optional) | ~16GB |

### Step 1: Navigate to Compose Directory

```bash
cd deploy/compose
```

### Step 2: Create Local Environment File

Copy the template and add your credentials:

```bash
cp .env.kdbai-8gpu .env.kdbai-8gpu.local
```

### Step 3: Edit Credentials

Edit `.env.kdbai-8gpu.local` with your actual credentials:

```bash
# Required - get from https://ngc.nvidia.com
export NGC_API_KEY="nvapi-your-actual-key"

# Required - from KX welcome email
export KDBAI_REGISTRY_EMAIL="your-email@example.com"
export KDBAI_REGISTRY_TOKEN="your-bearer-token-from-kx"

# Required - base64-encoded license from KX
export KDB_LICENSE_B64="your-base64-encoded-license"
```

> [!IMPORTANT]
> Never commit `.env.kdbai-8gpu.local` to version control. It's already in `.gitignore`.

### Step 4: Start the Stack

```bash
chmod +x deploy-kdbai-8gpu.sh
./deploy-kdbai-8gpu.sh up
```

The script will:
1. Validate all required environment variables
2. Create necessary directories with proper permissions
3. Log in to NGC and KX Docker registries
4. Start all services with correct GPU assignments

### Step 5: Monitor Startup

Services will take 5-15 minutes to initialize as they download model files.

```bash
# Watch container status
./deploy-kdbai-8gpu.sh ps

# View logs
./deploy-kdbai-8gpu.sh logs

# Check GPU utilization
./deploy-kdbai-8gpu.sh gpu
```

### Step 6: Access the Services

Once all containers are running:

| Service | URL |
|---------|-----|
| Frontend (RAG UI) | http://localhost:8090 |
| RAG Server API | http://localhost:8081 |
| Ingestor Server API | http://localhost:8082 |
| KDB.AI | http://localhost:8084 |

### Deployment Script Commands

The `deploy-kdbai-8gpu.sh` script supports these commands:

```bash
./deploy-kdbai-8gpu.sh up      # Start all services
./deploy-kdbai-8gpu.sh down    # Stop all services
./deploy-kdbai-8gpu.sh ps      # Show container status
./deploy-kdbai-8gpu.sh logs    # View logs (follow mode)
./deploy-kdbai-8gpu.sh gpu     # Show GPU status (nvidia-smi)
```

### Customizing GPU Assignments

To modify GPU assignments, edit `.env.kdbai-8gpu.local`:

```bash
# Example: Use GPU 4 for embedding instead of GPU 2
export EMBEDDING_MS_GPU_ID=4
export RANKING_MS_GPU_ID=4
```

Available GPU assignment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_GPU_COUNT` | 2 | Number of GPUs for LLM (tensor parallelism) |
| `EMBEDDING_MS_GPU_ID` | 2 | GPU for embedding model |
| `RANKING_MS_GPU_ID` | 2 | GPU for reranking model |
| `YOLOX_MS_GPU_ID` | 3 | GPU for page elements detection |
| `YOLOX_GRAPHICS_MS_GPU_ID` | 4 | GPU for graphic elements detection |
| `YOLOX_TABLE_MS_GPU_ID` | 5 | GPU for table structure detection |
| `OCR_MS_GPU_ID` | 5 | GPU for PaddleOCR |
| `KDBAI_GPU_DEVICE_ID` | 6 | GPU for KDB.AI (if using cuVS) |
| `VLM_MS_GPU_ID` | 7 | GPU for vision-language model |

### Troubleshooting 8-GPU Deployment

**Container fails to start with GPU error:**
```bash
# Check GPU availability
nvidia-smi

# Verify nvidia-container-toolkit is installed
docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
```

**Model download takes too long:**
- First startup downloads ~50GB+ of models
- Subsequent starts use cached models from `~/.cache/nim`
- Ensure sufficient disk space and network bandwidth

**Out of memory errors:**
- Check GPU memory with `nvidia-smi`
- Reduce `LLM_GPU_COUNT` if using smaller GPUs
- Consider using cloud LLM endpoints instead of self-hosted

**Permission denied on volumes:**
```bash
# Fix KDB.AI volume permissions
sudo chown -R 65534:65534 volumes/kdbai
chmod -R 777 volumes/kdbai
```


## Helm/Kubernetes Deployment

Follow these steps to deploy KDB.AI using Helm on Kubernetes.

The Helm chart includes templates for deploying KDB.AI as part of the RAG Blueprint stack. You can use the pre-configured values file, customize the configuration, or connect to an external KDB.AI instance.

### Option A: Use the Pre-configured Values File (Recommended)

Use the provided [`values-kdbai.yaml`](../deploy/helm/nvidia-blueprint-rag/values-kdbai.yaml) overlay file:

#### Step 1: Create Required Secrets

Before deploying, create all required Kubernetes secrets:

```bash
# Set your credentials as environment variables first
export NGC_API_KEY="nvapi-your-key-here"
export KDBAI_REGISTRY_EMAIL="your-email@example.com"
export KDBAI_REGISTRY_TOKEN="your-bearer-token-from-kx-email"
export KDB_LICENSE_B64="your-base64-encoded-license"

# 1. NGC Docker Registry Secret (for NVIDIA container images)
kubectl create secret docker-registry ngc-secret \
  --docker-server=nvcr.io \
  --docker-username='$oauthtoken' \
  --docker-password="${NGC_API_KEY}" \
  -n <your-namespace>

# 2. NGC API Secret (for NIM model downloads)
kubectl create secret generic ngc-api \
  --from-literal=NGC_API_KEY="${NGC_API_KEY}" \
  --from-literal=NGC_CLI_API_KEY="${NGC_API_KEY}" \
  --from-literal=NVIDIA_API_KEY="${NGC_API_KEY}" \
  -n <your-namespace>

# 3. KDB.AI Docker registry secret
kubectl create secret docker-registry kdbai-registry-secret \
  --docker-server=portal.dl.kx.com \
  --docker-username="${KDBAI_REGISTRY_EMAIL}" \
  --docker-password="${KDBAI_REGISTRY_TOKEN}" \
  -n <your-namespace>

# 4. KDB.AI license secret
kubectl create secret generic kdbai-license-secret \
  --from-literal=KDB_LICENSE_B64="${KDB_LICENSE_B64}" \
  -n <your-namespace>
```

> [!IMPORTANT]
> All four secrets are required. Missing `ngc-secret` or `ngc-api` will cause NIM pods to fail with image pull or authentication errors.

#### Step 2: Deploy with the Values File

From the repository root directory:

```bash
cd <repo-root>

# Create namespace if it doesn't exist
kubectl create namespace rag --dry-run=client -o yaml | kubectl apply -f -

# Install or upgrade using the KDB.AI values overlay
helm upgrade --install rag deploy/helm/nvidia-blueprint-rag \
  --namespace rag \
  -f deploy/helm/nvidia-blueprint-rag/values-kdbai.yaml \
  --dependency-update \
  --timeout 20m
```

> [!IMPORTANT]
> Always specify the `--namespace` flag. Without it, Helm deploys to the `default` namespace which is not recommended for production workloads.

The `values-kdbai.yaml` file configures:
- KDB.AI enabled with HNSW index
- Milvus disabled
- RAG server and ingestor server pointing to KDB.AI endpoint

### Option B: Manual Configuration

If you need to customize the configuration, modify your values file directly. Configure KDB.AI as the vector database in [`values.yaml`](../deploy/helm/nvidia-blueprint-rag/values.yaml):

```yaml
# Enable KDB.AI
kdbai:
  enabled: true
  fullnameOverride: kdbai

  # Image pull secret for KX Docker registry
  imagePullSecret:
    name: "kdbai-registry-secret"
    create: false  # Set to true if providing credentials below
    # email: "your-email@example.com"
    # token: "your-bearer-token"

  # License secret
  licenseSecret:
    name: "kdbai-license-secret"
    create: false  # Set to true if providing license below
    # licenseB64: "your-base64-license"

  # Server configuration
  config:
    threads: 8
    dataDir: "/tmp/kx/data/vdb"

  # Resources
  resources:
    limits:
      memory: "16Gi"
      cpu: "8"
    requests:
      memory: "4Gi"
      cpu: "2"

  # Persistence
  persistence:
    enabled: true
    size: 50Gi

# Update RAG server to use KDB.AI
envVars:
  APP_VECTORSTORE_URL: "http://kdbai:8082"
  APP_VECTORSTORE_NAME: "kdbai"
  KDBAI_DATABASE: "default"
  KDBAI_INDEX_TYPE: "hnsw"
  KDBAI_API_KEY: ""

# Update ingestor server to use KDB.AI
ingestor-server:
  envVars:
    APP_VECTORSTORE_URL: "http://kdbai:8082"
    APP_VECTORSTORE_NAME: "kdbai"
    KDBAI_DATABASE: "default"
    KDBAI_INDEX_TYPE: "hnsw"
    KDBAI_API_KEY: ""

# Disable Milvus since we're using KDB.AI
nv-ingest:
  enabled: true
  milvusDeployed: false
  milvus:
    enabled: false
```

Then deploy:

```bash
# Update Helm dependencies
helm dependency update deploy/helm/nvidia-blueprint-rag

# Install or upgrade the release
helm upgrade --install rag deploy/helm/nvidia-blueprint-rag \
  -n <your-namespace> \
  -f <your-values-file>
```

#### Step 3: Verify KDB.AI is Running

```bash
# Check pod status
kubectl get pods -n <your-namespace> | grep kdbai

# Check KDB.AI logs
kubectl logs -n <your-namespace> deployment/kdbai

# Test the REST API endpoint
kubectl port-forward svc/kdbai 8081:8081 -n <your-namespace>
curl http://localhost:8081/api/v2/ready
```

### Option C: Use External KDB.AI Instance

If you prefer to deploy KDB.AI separately or use an external instance:

1. Keep `kdbai.enabled: false` in values.yaml

2. Configure the vector store environment variables to point to your external KDB.AI:

   ```yaml
   envVars:
     APP_VECTORSTORE_URL: "http://<kdbai-host>:8082"
     APP_VECTORSTORE_NAME: "kdbai"
     KDBAI_DATABASE: "default"
     KDBAI_INDEX_TYPE: "hnsw"
     KDBAI_API_KEY: "<your-api-key-if-required>"

   ingestor-server:
     envVars:
       APP_VECTORSTORE_URL: "http://<kdbai-host>:8082"
       APP_VECTORSTORE_NAME: "kdbai"
       KDBAI_DATABASE: "default"
       KDBAI_INDEX_TYPE: "hnsw"
       KDBAI_API_KEY: "<your-api-key-if-required>"
   ```

3. Disable Milvus deployment:

   ```yaml
   nv-ingest:
     enabled: true
     milvusDeployed: false
     milvus:
       enabled: false
   ```

4. Apply the changes as described in [Change a Deployment](deploy-helm.md#change-a-deployment).


## Environment Variables Reference

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `KDBAI_REGISTRY_EMAIL` | Your KX signup email for Docker registry auth | - | Yes |
| `KDBAI_REGISTRY_TOKEN` | Bearer token from KX welcome email | - | Yes |
| `KDB_LICENSE_B64` | Base64-encoded KDB.AI license | - | Yes |
| `KDBAI_THREADS` | Number of threads for KDB.AI | `8` | No |
| `KDBAI_DATABASE` | Database name | `default` | No |
| `KDBAI_INDEX_TYPE` | Index type (`flat`, `hnsw`, `ivf`, `ivfpq`) | `hnsw` | No |
| `KDBAI_INSERT_BATCH_SIZE` | Batch size for document ingestion | `200` | No |
| `KDBAI_DEBUG` | Enable verbose debug logging for KDB.AI operations | `false` | No |
| `APP_VECTORSTORE_URL` | KDB.AI client endpoint | - | Yes |
| `APP_VECTORSTORE_NAME` | Must be `kdbai` | - | Yes |
| `APP_VECTORSTORE_SEARCHTYPE` | Search type (`dense` or `hybrid`) | `dense` | No |


## Verify Your Deployment

After completing the setup, verify that KDB.AI is running correctly:

### Check Container Status

```bash
docker ps | grep kdbai
docker logs kdbai-server
```

### Test REST API

```bash
curl http://localhost:8083/api/v2/ready
```

### Test Python Client Connectivity

```python
import kdbai_client as kdbai

# Connect to self-hosted KDB.AI Server
session = kdbai.Session(endpoint='http://localhost:8084')

# Get database
db = session.database('default')

# List tables
print(db.tables)
```

### Verify Through RAG Server

Check the RAG server logs to confirm KDB.AI connection:

```bash
docker logs rag-server 2>&1 | grep -i kdbai
```

### Kubernetes/Helm Verification

For Helm deployments, use the following commands:

```bash
# Check pod status
kubectl get pods -n <your-namespace> | grep kdbai

# Check KDB.AI logs
kubectl logs -n <your-namespace> deployment/kdbai

# Port-forward to test REST API locally
kubectl port-forward svc/kdbai 8081:8081 -n <your-namespace>
curl http://localhost:8081/api/v2/ready

# Port-forward client endpoint for Python SDK testing
kubectl port-forward svc/kdbai 8082:8082 -n <your-namespace>

# Verify RAG server can connect to KDB.AI
kubectl logs -n <your-namespace> deployment/rag-server | grep -i kdbai
```


## Index Types and Performance Tuning

Choose the appropriate index type based on your use case:

| Index Type | Best For | Trade-offs |
|------------|----------|------------|
| `flat` | Small datasets (<10K vectors), exact results | Slow for large datasets |
| `hnsw` | Most use cases, balanced performance | Good accuracy/speed trade-off |
| `ivf` | Large datasets (>100K vectors) | Requires training, approximate results |
| `ivfpq` | Very large datasets, memory constrained | Lower accuracy, high compression |

To change the index type, update the `KDBAI_INDEX_TYPE` environment variable and recreate your collections.


## Troubleshooting

### License Errors

If you see license-related errors:

1. **Verify KDB_LICENSE_B64 is set** - The license must be base64-encoded.
   ```bash
   echo $KDB_LICENSE_B64
   ```

2. **Verify you have the correct license type** - KDB.AI and KDB/X are different products with incompatible licenses.
   ```bash
   # A valid KDB.AI license decodes to readable text
   echo "$KDB_LICENSE_B64" | base64 -d | head -3

   # If you see binary garbage, you have the wrong license type
   # Request a KDB.AI license specifically from https://kx.com
   ```

3. **Check license expiration** - Licenses are valid for 90 days.

4. **Review container logs**:
   ```bash
   docker logs kdbai-server
   ```

### Connection Errors

If you encounter connection errors:

1. **Verify container is running**:
   ```bash
   docker ps | grep kdbai
   ```

2. **Check port accessibility**:
   ```bash
   curl http://localhost:8083/api/v2/ready
   ```

3. **Verify endpoint configuration** - RAG server should connect to port 8082 (client port).

### Docker Registry Authentication

If you can't pull the KDB.AI image:

1. **Re-authenticate with the registry**:
   ```bash
   docker logout portal.dl.kx.com
   docker login portal.dl.kx.com -u <email> -p <bearer-token>
   ```

2. **Verify credentials** - Ensure you're using the email and bearer token from your KX welcome email.

### Document Upload Issues

If documents fail to upload:

1. **Check collection exists** - Ensure the collection was created successfully.

2. **Verify embedding dimensions** - Confirm your embedding model dimensions match the collection configuration (default: 2048).

3. **Review server logs**:
   ```bash
   docker logs ingestor-server 2>&1 | tail -100
   ```

### Kubernetes/Helm Troubleshooting

For Helm deployments, check these common issues:

1. **Image pull errors** - Verify your registry secret is correctly configured:
   ```bash
   kubectl get secret kdbai-registry-secret -n <your-namespace> -o yaml
   kubectl describe pod -n <your-namespace> -l app=kdbai
   ```

2. **License errors** - Check the license secret:
   ```bash
   kubectl get secret kdbai-license-secret -n <your-namespace> -o yaml
   # Verify the license is correctly base64-encoded
   kubectl get secret kdbai-license-secret -n <your-namespace> -o jsonpath='{.data.KDB_LICENSE_B64}' | base64 -d
   ```

3. **Pod not starting** - Check events and logs:
   ```bash
   kubectl describe pod -n <your-namespace> -l app=kdbai
   kubectl logs -n <your-namespace> -l app=kdbai --previous
   ```

4. **Service connectivity** - Verify the service is accessible:
   ```bash
   kubectl get svc kdbai -n <your-namespace>
   kubectl run curl-test --image=curlimages/curl -it --rm -- curl http://kdbai:8081/api/v2/ready
   ```

### NGC Authentication Issues

These issues affect NVIDIA NIM pods (embedding, reranking, nemoretriever):

#### NIM Pods in ImagePullBackOff (401 Unauthorized)

**Symptoms:**
```
Warning  Failed  Failed to pull image "nvcr.io/nim/nvidia/...": 401 Unauthorized
```

**Cause:** The `ngc-secret` is missing or has invalid credentials.

**Solution:**
```bash
# Delete and recreate the NGC docker registry secret
kubectl delete secret ngc-secret -n <your-namespace>
kubectl create secret docker-registry ngc-secret \
  --docker-server=nvcr.io \
  --docker-username='$oauthtoken' \
  --docker-password="${NGC_API_KEY}" \
  -n <your-namespace>

# Restart affected pods
kubectl delete pods -n <your-namespace> -l app.kubernetes.io/name=nemoretriever-page-elements-v2
```

#### NIM Pods in CrashLoopBackOff (Authentication Error)

**Symptoms:**
```
ERROR: Error downloading manifest: Authentication Error
ManifestDownloadError: Error downloading manifest: Authentication Error
```

**Cause:** The `ngc-api` secret is missing or has empty values. NIMs need this to download models from NGC.

**Solution:**
```bash
# Delete and recreate the NGC API secret
kubectl delete secret ngc-api -n <your-namespace>
kubectl create secret generic ngc-api \
  --from-literal=NGC_API_KEY="${NGC_API_KEY}" \
  --from-literal=NGC_CLI_API_KEY="${NGC_API_KEY}" \
  --from-literal=NVIDIA_API_KEY="${NGC_API_KEY}" \
  -n <your-namespace>

# Restart affected pods
kubectl delete pods -n <your-namespace> -l app.kubernetes.io/name=nvidia-nim-llama-32-nv-embedqa-1b-v2
kubectl delete pods -n <your-namespace> -l app.kubernetes.io/name=nvidia-nim-llama-32-nv-rerankqa-1b-v2
```

#### Verify NGC Secrets Are Configured Correctly

```bash
# Check ngc-secret has a password (not just "$oauthtoken:")
kubectl get secret ngc-secret -n <your-namespace> -o jsonpath='{.data.\.dockerconfigjson}' | \
  base64 -d | jq -r '.auths["nvcr.io"].auth' | base64 -d

# Check ngc-api has a non-empty NGC_API_KEY
kubectl get secret ngc-api -n <your-namespace> -o jsonpath='{.data.NGC_API_KEY}' | base64 -d
```

#### RAG Queries Hang Indefinitely (No Response)

**Symptoms:** Queries submitted through the frontend show "loading" forever with no response or error.

**Cause:** The RAG server is configured to use cloud-hosted LLM endpoints but the `NVIDIA_API_KEY` environment variable is empty, causing authentication to fail silently.

**Diagnosis:**
```bash
# Check if NVIDIA_API_KEY is set in the rag-server pod
kubectl exec deployment/rag-server -n <your-namespace> -- env | grep NVIDIA_API_KEY
# If output shows "NVIDIA_API_KEY=" (empty), this is the problem
```

**Solution:**
```bash
# Mount the ngc-api secret to the application pods
kubectl set env deployment/rag-server -n <your-namespace> --from=secret/ngc-api
kubectl set env deployment/ingestor-server -n <your-namespace> --from=secret/ngc-api

# Wait for pods to restart
kubectl rollout status deployment/rag-server -n <your-namespace>

# Verify the key is now set
kubectl exec deployment/rag-server -n <your-namespace> -- env | grep NVIDIA_API_KEY
# Should show: NVIDIA_API_KEY=nvapi-...
```


## Debugging

If you encounter issues, use these commands to check logs:

### Check Service Logs

```bash
# Docker Compose
docker logs kdbai-server
docker logs rag-server 2>&1 | grep -i kdbai
docker logs ingestor-server 2>&1 | grep -i kdbai

# Kubernetes
kubectl logs deployment/kdbai -n <namespace>
kubectl logs deployment/rag-server -n <namespace> | grep -i kdbai
```

### Enable Debug Logging

For more detailed logs, enable debug mode:

```bash
export KDBAI_DEBUG=true
```

Then restart the RAG server.


## Lessons Learned from Deployment

This section captures important lessons learned from real-world deployments to help avoid common pitfalls.

### NVIDIA API Key Configuration for Cloud LLM Endpoints

**Issue:** When using cloud-hosted NVIDIA AI endpoints (e.g., `integrate.api.nvidia.com`), the `NVIDIA_API_KEY` must be explicitly set in the rag-server pod. Helm-created secrets may have empty values.

**Symptoms:**
- Queries hang indefinitely in the frontend
- No error messages in logs
- File uploads work, but LLM responses never return

**Root Cause:** The `ngc-api` secret created during Helm install may have empty values if the `NGC_API_KEY` environment variable wasn't set at install time.

**Solution:**
```bash
# 1. Verify the secret has the actual API key
kubectl get secret ngc-api -n rag -o jsonpath='{.data.NVIDIA_API_KEY}' | base64 -d
# If empty, recreate the secret:

# 2. Delete and recreate with actual values
kubectl delete secret ngc-api -n rag
kubectl create secret generic ngc-api -n rag \
  --from-literal=NGC_API_KEY="nvapi-your-actual-key" \
  --from-literal=NGC_CLI_API_KEY="nvapi-your-actual-key" \
  --from-literal=NVIDIA_API_KEY="nvapi-your-actual-key"

# 3. Mount the secret to rag-server
kubectl set env deployment/rag-server -n rag --from=secret/ngc-api

# 4. Verify the key is set
kubectl exec deployment/rag-server -n rag -- env | grep NVIDIA_API_KEY
```

---

### GPU/cuVS Features Disabled by Default

**Current State:** GPU acceleration (cuVS/CAGRA) is preserved for future work but **disabled by default** in the EKS values file.

The following settings should be `"False"` for standard deployments:
```yaml
envVars:
  APP_VECTORSTORE_ENABLEGPUINDEX: "False"
  APP_VECTORSTORE_ENABLEGPUSEARCH: "False"

kdbai:
  gpu:
    enabled: false
```

**Why:** The cuVS integration requires:
- Special KDB.AI cuVS image from a separate registry
- GPU nodes with NVIDIA drivers
- Additional registry secrets

For production deployments, use the standard KDB.AI image with HNSW index, which provides excellent performance without GPU requirements.

---

### KDB.AI-Enabled RAG Images

KDB.AI-enabled RAG images are available from the KX registry and use the same credentials as the KDB.AI database image:

- `portal.dl.kx.com/rag-server-kdbai:2.3.4`
- `portal.dl.kx.com/ingestor-server-kdbai:2.3.4`

**To build custom images:**
```bash
export REGISTRY=<your-registry>
export TAG=2.3.4

# Build and push rag-server
docker buildx build --platform linux/amd64 \
  -t ${REGISTRY}/rag-server-kdbai:${TAG} \
  -f src/nvidia_rag/rag_server/Dockerfile --push .

# Build and push ingestor-server
docker buildx build --platform linux/amd64 \
  -t ${REGISTRY}/ingestor-server-kdbai:${TAG} \
  -f src/nvidia_rag/ingestor_server/Dockerfile --push .
```

---

### Health Probe Timeouts

**Issue:** Pods may enter `CrashLoopBackOff` if health probes timeout before the application can respond.

**Symptoms:**
- Pod shows multiple restarts
- Logs show "Checking service health..." followed by SIGTERM
- Events show "Liveness probe failed: context deadline exceeded"

**Cause:** Default health probe timeouts (5s) may be too short when connecting to KDB.AI, especially during initial startup.

**Solution:** Increase probe timeouts if needed:
```bash
kubectl patch deployment rag-server -n rag --type='json' -p='[
  {"op": "replace", "path": "/spec/template/spec/containers/0/livenessProbe/initialDelaySeconds", "value": 60},
  {"op": "replace", "path": "/spec/template/spec/containers/0/livenessProbe/timeoutSeconds", "value": 30},
  {"op": "replace", "path": "/spec/template/spec/containers/0/readinessProbe/initialDelaySeconds", "value": 30},
  {"op": "replace", "path": "/spec/template/spec/containers/0/readinessProbe/timeoutSeconds", "value": 30}
]'
```

---

### PVC Conflicts During Configuration Changes

**Issue:** Switching between GPU and non-GPU KDB.AI configurations may cause PVC attachment conflicts.

**Symptoms:**
- New KDB.AI pod stuck in `Init:0/1`
- Events show: "Multi-Attach error for volume"

**Cause:** The old pod is still using the PersistentVolumeClaim when the new configuration tries to create a replacement pod.

**Solution:**
```bash
# Option 1: Rollback to previous configuration
kubectl rollout undo deployment/kdbai -n rag

# Option 2: Force transition (causes brief downtime)
kubectl delete pod -l app=kdbai -n rag --grace-period=0 --force
# Wait for new pod to attach to the PVC
```

---

## Known Issues and Solutions

### Search Returns No Results

**Symptoms:** Documents uploaded successfully but search returns empty results.

**Solutions:**
1. Delete the collection from the RAG UI
2. Recreate the collection
3. Re-upload your documents

This can happen if the collection was created before KDB.AI was fully ready.

---

### Helm Deployment - Duplicate Environment Variable Error

**Error:**
```
failed to create resource: duplicate entries for key [name="INGEST_LOG_LEVEL"]
```

**Solution:** Add this to your values file:

```yaml
nv-ingest:
  logLevel: WARNING
  envVars:
    INGEST_LOG_LEVEL: null
```

---

### Helm Release Secret Too Large

**Error:**
```
Secret "sh.helm.release.v1.rag.v1" is invalid: data: Too long: must have at most 1048576 bytes
```

**Solution:** Move backup folders outside the chart directory:

```bash
mv deploy/helm/nvidia-blueprint-rag/*-backup ../
```


## Amazon EKS Deployment

For Amazon EKS deployments, a pre-configured values file is available that combines KDB.AI with cloud-hosted NVIDIA AI endpoints.

> [!NOTE]
> **Development/Testing Configuration**: The provided EKS values file is configured for development and testing purposes with single replicas. For production deployments, you should:
> - Increase replica counts for high availability
> - Configure Horizontal Pod Autoscaling (HPA)
> - Set appropriate resource requests and limits
> - Enable persistent storage with proper backup strategies
> - Configure monitoring, alerting, and logging
> - Review and harden security configurations

### Prerequisites

1. An EKS cluster with GPU nodes and the AWS EBS CSI driver installed
2. `kubectl` configured to access your EKS cluster
3. KDB.AI license and registry credentials from KX
4. NVIDIA NGC API key for container images and NIM services

### Step 1: Set Environment Variables

Set all required credentials as environment variables (these will be used in subsequent commands):

```bash
# NVIDIA NGC API Key (required)
export NGC_API_KEY="nvapi-your-key-here"

# KDB.AI credentials from KX welcome email (required)
export KDBAI_REGISTRY_EMAIL="your-email@example.com"
export KDBAI_REGISTRY_TOKEN="your-bearer-token-from-kx-email"
export KDB_LICENSE_B64="your-base64-encoded-license"

# Optional: If using AWS CLI profiles
export AWS_PROFILE="your-aws-profile"
```

### Step 2: Create Kubernetes Namespace

```bash
kubectl create namespace rag --dry-run=client -o yaml | kubectl apply -f -
```

### Step 3: Create All Required Secrets

Create **all four** secrets before deploying. Missing secrets will cause pod failures.

```bash
# 1. NGC Docker Registry Secret (for pulling NVIDIA container images)
kubectl create secret docker-registry ngc-secret \
  --docker-server=nvcr.io \
  --docker-username='$oauthtoken' \
  --docker-password="${NGC_API_KEY}" \
  -n rag

# 2. NGC API Secret (for NIM model downloads and API authentication)
kubectl create secret generic ngc-api \
  --from-literal=NGC_API_KEY="${NGC_API_KEY}" \
  --from-literal=NGC_CLI_API_KEY="${NGC_API_KEY}" \
  --from-literal=NVIDIA_API_KEY="${NGC_API_KEY}" \
  -n rag

# 3. KDB.AI Docker Registry Secret (for pulling KDB.AI image)
kubectl create secret docker-registry kdbai-registry-secret \
  --docker-server=portal.dl.kx.com \
  --docker-username="${KDBAI_REGISTRY_EMAIL}" \
  --docker-password="${KDBAI_REGISTRY_TOKEN}" \
  -n rag

# 4. KDB.AI License Secret
kubectl create secret generic kdbai-license-secret \
  --from-literal=KDB_LICENSE_B64="${KDB_LICENSE_B64}" \
  -n rag
```

> [!IMPORTANT]
> The `ngc-secret` and `ngc-api` secrets are critical. Without them:
> - NIM pods will fail with `ImagePullBackOff` (401 Unauthorized)
> - Embedding/Reranking NIMs will crash with `Authentication Error` when downloading models

### Step 4: Verify Secrets

Confirm all secrets are created:

```bash
kubectl get secrets -n rag | grep -E "(ngc|kdbai)"
```

Expected output:
```
kdbai-license-secret     Opaque                                1      ...
kdbai-registry-secret    kubernetes.io/dockerconfigjson        1      ...
ngc-api                  Opaque                                3      ...
ngc-secret               kubernetes.io/dockerconfigjson        1      ...
```

### Step 5: Update Helm Dependencies

```bash
helm dependency update deploy/helm/nvidia-blueprint-rag
```

### Step 6: Deploy the Helm Chart

From the repository root directory:

```bash
helm upgrade --install rag deploy/helm/nvidia-blueprint-rag \
  --namespace rag \
  -f deploy/helm/nvidia-blueprint-rag/values-kdbai.yaml \
  -f deploy/EKS/rag-values-kdbai.yaml \
  --timeout 30m
```

> [!NOTE]
> The deployment may take 10-20 minutes as NIM containers download model files on first startup.

### Step 7: Monitor Deployment Progress

Watch pods until all reach `Running` status with `1/1` ready:

```bash
kubectl get pods -n rag -w
```

Expected pods when healthy:
```
NAME                                                         READY   STATUS
ingestor-server-...                                          1/1     Running
kdbai-...                                                    1/1     Running
rag-frontend-...                                             1/1     Running
rag-minio-...                                                1/1     Running
rag-nemoretriever-graphic-elements-v1-...                    1/1     Running
rag-nemoretriever-page-elements-v2-...                       1/1     Running
rag-nemoretriever-table-structure-v1-...                     1/1     Running
rag-nv-ingest-...                                            1/1     Running
rag-nvidia-nim-llama-32-nv-embedqa-1b-v2-...                 1/1     Running
rag-nvidia-nim-llama-32-nv-rerankqa-1b-v2-...                1/1     Running
rag-redis-master-0                                           1/1     Running
rag-redis-replicas-0                                         1/1     Running
rag-server-...                                               1/1     Running
```

### Step 8: Mount API Key to Application Pods

The RAG server and ingestor server need access to the NGC API key for cloud-hosted LLM endpoints. Mount the secret to these deployments:

```bash
kubectl set env deployment/rag-server -n rag --from=secret/ngc-api
kubectl set env deployment/ingestor-server -n rag --from=secret/ngc-api
```

Wait for pods to restart:

```bash
kubectl rollout status deployment/rag-server -n rag
kubectl rollout status deployment/ingestor-server -n rag
```

Verify the API key is set:

```bash
kubectl exec deployment/rag-server -n rag -- env | grep NVIDIA_API_KEY
# Should show: NVIDIA_API_KEY=nvapi-...
```

> [!IMPORTANT]
> Without this step, queries will hang indefinitely because the RAG server cannot authenticate with the cloud LLM endpoint.

### Step 9: Verify Services

```bash
# Check RAG server health
kubectl exec -n rag deployment/rag-server -- \
  python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8081/health').read().decode())"

# Check KDB.AI connection in logs
kubectl logs -n rag deployment/rag-server | grep -i kdbai
```

### Step 10: Access the Frontend

Port-forward to access the UI locally:

```bash
kubectl port-forward svc/rag-frontend 8090:3000 -n rag
```

Then open **http://localhost:8090** in your browser.

### EKS Values File Overview

The [`deploy/EKS/rag-values-kdbai.yaml`](../deploy/EKS/rag-values-kdbai.yaml) file configures:

| Component | Configuration |
|-----------|---------------|
| **KDB.AI** | Enabled with HNSW index, 16Gi memory limit |
| **MinIO** | Standalone deployment (`rag-minio:9000`) for object storage |
| **LLM** | Cloud-hosted via `integrate.api.nvidia.com` |
| **Milvus** | Disabled (`milvusDeployed: false`) |
| **Vector Store** | Points to `http://kdbai:8082` |

This configuration uses cloud-hosted NVIDIA AI endpoints for LLM inference, reducing GPU requirements on your EKS cluster while using KDB.AI for vector storage.

### Volume Scheduling for Dynamic Node Scaling

The EKS values file includes a StorageClass with `WaitForFirstConsumer` binding mode to prevent volume scheduling issues when EKS nodes scale up/down. This ensures the persistent volume is created on the same node where the KDB.AI pod is scheduled:

```yaml
storageClass:
  create: true
  name: "kdbai-storage"
  volumeBindingMode: WaitForFirstConsumer
  reclaimPolicy: Delete
  allowVolumeExpansion: true
  provisioner: "ebs.csi.aws.com"
  parameters:
    type: gp3
```

Without this configuration, you may encounter volume affinity errors when nodes are replaced during cluster scaling operations.

> [!NOTE]
> MinIO is deployed as a standalone service for object storage. It is required for storing multimodal content such as images extracted from documents during ingestion.


## GPU-Accelerated KDB.AI with cuVS

KDB.AI supports GPU-accelerated vector indexing and search using NVIDIA cuVS when deployed with a cuVS-enabled Docker image. When GPU mode is enabled, the blueprint automatically uses the **CAGRA** (CUDA Approximate Graph-based Nearest Neighbor) index from NVIDIA cuVS for fast GPU-accelerated vector search.

### GPU Index Type: CAGRA

When `APP_VECTORSTORE_ENABLEGPUINDEX=True` is set:
- CPU index types (`hnsw`, `flat`) are automatically mapped to `cagra` (cuVS GPU index)
- CAGRA provides GPU-accelerated approximate nearest neighbor search
- The index is built and searched on the GPU for optimal performance

| CPU Index Type | GPU Equivalent |
|----------------|----------------|
| `hnsw` | `cagra` (GPU-accelerated) |
| `flat` | `cagra` (GPU-accelerated) |

### Prerequisites for GPU Deployment

1. **NVIDIA GPU** - A CUDA-capable GPU (compute capability 7.0+)
2. **nvidia-container-toolkit** - Docker GPU support installed
3. **cuVS Docker Image** - Access to the KDB.AI cuVS image from KX

### Docker Compose GPU Deployment

```bash
# Set GPU environment variables
export APP_VECTORSTORE_ENABLEGPUINDEX=True
export APP_VECTORSTORE_ENABLEGPUSEARCH=True
export KDBAI_GPU_IMAGE="ext-dev-registry.kxi-dev.kx.com/kdbai-db:1.8.1-rc.2-cuvs"

# Login to cuVS registry (uses same KX credentials as standard registry)
docker login ext-dev-registry.kxi-dev.kx.com -u $KDBAI_REGISTRY_EMAIL -p $KDBAI_REGISTRY_TOKEN

# Start GPU-enabled KDB.AI
docker compose -f deploy/compose/vectordb.yaml --profile kdbai-gpu up -d
```

### Kubernetes/Helm GPU Deployment

Update your values file to enable GPU:

```yaml
kdbai:
  enabled: true
  gpu:
    enabled: true
    deviceId: "0"
  gpuImage:
    registry: ext-dev-registry.kxi-dev.kx.com
    repository: kdbai-db
    tag: "1.8.1-rc.2-cuvs"
  gpuImagePullSecret:
    name: "kdbai-cuvs-registry-secret"  # Create this secret for cuVS registry

envVars:
  APP_VECTORSTORE_ENABLEGPUINDEX: "True"
  APP_VECTORSTORE_ENABLEGPUSEARCH: "True"
```

Create the cuVS registry secret (uses same KX credentials as standard KDB.AI registry):

```bash
kubectl create secret docker-registry kdbai-cuvs-registry-secret \
  --docker-server=ext-dev-registry.kxi-dev.kx.com \
  --docker-username=<your-kx-email> \
  --docker-password=<bearer-token-from-kx> \
  -n <your-namespace>
```

Then deploy:

```bash
helm upgrade --install nvidia-rag deploy/helm/nvidia-blueprint-rag \
  -n <your-namespace> \
  -f deploy/helm/nvidia-blueprint-rag/values-kdbai.yaml
```

### GPU Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `APP_VECTORSTORE_ENABLEGPUINDEX` | Enable GPU-accelerated indexing (uses CAGRA) | `False` |
| `APP_VECTORSTORE_ENABLEGPUSEARCH` | Enable GPU-accelerated search | `False` |
| `KDBAI_GPU_DEVICE_ID` | GPU device ID to use | `0` |
| `KDBAI_GPU_IMAGE` | cuVS-enabled Docker image | (see values file) |

> [!NOTE]
> When GPU indexing is enabled, the blueprint automatically uses the `cagra` index type from NVIDIA cuVS for GPU-accelerated vector search. CPU index types (`hnsw`, `flat`) are mapped to `cagra` automatically.


## Related Topics

### NVIDIA RAG Blueprint
- [NVIDIA RAG Blueprint Overview](readme.md) - Main documentation
- [Deploy with Docker Compose](deploy-docker-compose.md) - Docker deployment guide
- [Deploy with Helm](deploy-helm.md) - Kubernetes deployment guide
- [Best Practices for Common Settings](accuracy_perf.md) - Performance optimization
- [RAG Pipeline Debugging Guide](debugging.md) - General debugging tips
- [Troubleshoot](troubleshooting.md) - Common issues

### KDB.AI Resources
- [KDB.AI Documentation](https://code.kx.com/kdbai/) - Official KDB.AI documentation
- [KDB.AI Python Client Reference](https://code.kx.com/kdbai/reference/python-client.html) - Python SDK reference
- [KDB.AI Filter Documentation](https://code.kx.com/kdbai/use/filter.html) - Filter syntax guide
- [KDB.AI Index Types](https://code.kx.com/kdbai/latest/use/supported-indexes.html) - Index options and configuration
- [KDB.AI Server Setup](https://docs.kx.com/1.7/KDB_AI/Get_Started/kdb-ai-server-setup.htm) - Server installation guide
- [KX Website](https://kx.com) - Request licenses and learn more about KX products

### GPU Acceleration
- [NVIDIA cuVS Documentation](https://docs.nvidia.com/cuvs/) - GPU-accelerated vector search
- [NV-Ingest Documentation](https://github.com/NVIDIA/nv-ingest) - Document ingestion pipeline
