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

# AIQ-AIRA Helm Chart Examples (AIQ-KX with KDB Integration)

This directory contains example Helm values files for deploying AIQ-KX (the KDB-enabled version of AI-Q Research Assistant).

## Important: Image Hosting

**AIQ-KX images are NOT on NVIDIA NGC (NVCR).** The KDB-enabled images are available from:
1. **KX Portal Registry** (recommended): `portal.dl.kx.com/aiq-kx-backend:1.0.2` and `portal.dl.kx.com/aiq-kx-frontend:1.0.2`
2. Self-hosted: Build from this repository and push to your registry

The default NVCR images (`nvcr.io/nvidia/blueprint/aira-*`) do NOT include KDB integration.

## Available Examples

| File | Use Case | Registry | Kubernetes |
|------|----------|----------|------------|
| `values-generic-k8s.yaml` | On-premise / Self-hosted | Your registry | Any K8s |
| `values-docker-hub.yaml` | Docker Hub images | Docker Hub | Any K8s |
| `values-private-registry.yaml` | Enterprise registries | Harbor, GitLab, etc. | Any K8s |

## Pre-built Images

AIQ-KX images are available on the KX portal registry:

```
portal.dl.kx.com/aiq-kx-backend:1.0.2
portal.dl.kx.com/aiq-kx-frontend:1.0.2
```

### Building Your Own Images (Optional)

If you want to build custom images:

```bash
# Build backend
docker build -f deploy/Dockerfile -t your-registry/aiq-kx-backend:latest .

# Build frontend
docker build -f frontend/Dockerfile -t your-registry/aiq-kx-frontend:latest ./frontend

# Push to your registry
docker push your-registry/aiq-kx-backend:latest
docker push your-registry/aiq-kx-frontend:latest
```

## Quick Start

### Option 1: Generic Kubernetes (Recommended)

Works on any Kubernetes cluster (kubeadm, k3s, minikube, etc.) using pre-built images from the KX portal registry:

```bash
# Deploy directly - no edits needed
helm upgrade --install aiq-kx ../. -n aiq --create-namespace \
  -f values-generic-k8s.yaml \
  --set ngcApiSecret.password="$NVIDIA_API_KEY"
```

### Option 2: Docker Hub

For images hosted on Docker Hub:

```bash
# 1. Copy and edit the template
cp values-docker-hub.yaml my-values.yaml
# Edit my-values.yaml: replace REPLACE_WITH_YOUR_USERNAME

# 2. Deploy
helm upgrade --install aiq-kx ../. -n aiq --create-namespace \
  -f my-values.yaml \
  --set imagePullSecret.password="your-dockerhub-access-token" \
  --set ngcApiSecret.password="$NVIDIA_API_KEY"
```

### Option 3: Private Registry (Harbor, GitLab, etc.)

For enterprise private registries:

```bash
# 1. Copy and edit the template
cp values-private-registry.yaml my-values.yaml
# Edit my-values.yaml: replace REPLACE_WITH_REGISTRY and REPLACE_WITH_USERNAME

# 2. Deploy
helm upgrade --install aiq-kx ../. -n aiq --create-namespace \
  -f my-values.yaml \
  --set imagePullSecret.password="your-registry-token" \
  --set ngcApiSecret.password="$NVIDIA_API_KEY"
```

## Supported Kubernetes Distributions

These examples work on any CNCF-conformant Kubernetes cluster:

| Distribution | Type | Tested |
|--------------|------|--------|
| Amazon EKS | Cloud | Yes |
| Google GKE | Cloud | Yes |
| Azure AKS | Cloud | Yes |
| DigitalOcean | Cloud | Yes |
| Vanilla Kubernetes (kubeadm) | Self-hosted | Yes |
| k3s / k3d | Lightweight | Yes |
| Rancher RKE / RKE2 | Enterprise | Yes |
| OpenShift | Enterprise | Yes |
| minikube | Local | Yes |
| kind | Local | Yes |
| Docker Desktop | Local | Yes |

## Supported Container Registries

| Registry | Example Host | Auth Method |
|----------|--------------|-------------|
| KX Portal | `portal.dl.kx.com` | KX Portal Token |
| Docker Hub | `docker.io` | Access Token |
| Harbor | `harbor.company.com` | Robot Account |
| GitLab Registry | `registry.gitlab.com` | Deploy Token |
| Quay.io | `quay.io` | Robot Account |
| AWS ECR | `123456789.dkr.ecr.region.amazonaws.com` | IAM/Token |
| Google Artifact Registry | `region-docker.pkg.dev` | Service Account |
| Azure ACR | `myregistry.azurecr.io` | Service Principal |
| JFrog Artifactory | `company.jfrog.io` | API Key |

## Customization

Each example file is a starting point. Common customizations:

```yaml
# Enable KDB-X financial data integration
backendEnvVars:
  KDB_ENABLED: "true"
  KDB_MCP_ENDPOINT: "http://your-kdb-mcp-server:8000/mcp"

# Use LoadBalancer instead of NodePort (cloud deployments)
frontend:
  service:
    type: LoadBalancer
    port: 3000

# Increase resources for production
resources:
  limits:
    cpu: "4"
    memory: "8Gi"
  requests:
    cpu: "1"
    memory: "2Gi"

# Enable self-hosted LLM NIMs (requires GPU nodes)
nim-llm:
  enabled: true
```

## Security Notes

- **Never commit credentials** to version control
- Use `--set` flags for sensitive values (passwords, tokens)
- Consider using Kubernetes Secrets or external secret managers for production
- The `my-values.yaml` pattern keeps credentials out of git
