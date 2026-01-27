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

# KDB-X MCP Server Helm Chart

A Helm chart for deploying the [KDB-X MCP Server](https://github.com/KxSystems/kdb-x-mcp-server) - a Model Context Protocol server that enables natural language querying of KDB+/KDB-X databases.

## Overview

This chart supports two deployment modes:

1. **Internal Mode (default)**: Deploys the KDB-X MCP Server as a Kubernetes service
2. **External Mode**: Configures the chart to use an external MCP server endpoint

## Prerequisites

- Kubernetes 1.19+
- Helm 3.0+
- For internal mode with KDB-X database:
  - KX Portal account (https://portal.kx.com)
  - KDB-X license (personal or commercial)
  - Bearer token for KX downloads
- For external mode: External MCP server endpoint URL

## Getting KDB-X Credentials

Before deploying in internal mode with KDB-X database, you'll need:

### Bearer Token
1. Go to https://portal.kx.com
2. Log in or create an account
3. Navigate to your profile/tokens
4. Generate an OAuth bearer token

### License
1. Request a KDB-X license from https://kx.com
2. Save the license file (kc.lic for personal, k4.lic for commercial)
3. Base64 encode: `cat kc.lic | base64`

## Installation

### Quick Start with Example Templates

The chart includes ready-to-use example templates in `examples/`:

| Template | Description |
|----------|-------------|
| `examples/internal-runtime-values.yaml` | **Recommended** - Deploy MCP server + KDB-X database (installs at runtime) |
| `examples/external-values.yaml` | Connect to an existing external MCP server |

```bash
# 1. Copy the appropriate template
cp examples/internal-runtime-values.yaml my-values.yaml

# 2. Edit my-values.yaml and replace all REPLACE_WITH_* placeholders

# 3. Deploy
helm upgrade --install kdb-mcp . -n aiq -f my-values.yaml
```

> **Security:** Your `my-values.yaml` contains credentials. It is automatically ignored by `.gitignore`. Never commit credentials to version control.

### External Mode (Using existing MCP Server)

```bash
helm install kdb-mcp ./kdb-x-mcp-server \
  --namespace aiq \
  -f examples/external-values.yaml \
  --set external.endpoint=https://your-mcp-server/mcp
```

### Internal Mode with KDB-X Database (Runtime Installation)

This mode installs KDB-X at container startup - no pre-built image required.

**Step 1: Create your values file**
```bash
cp examples/internal-runtime-values.yaml my-values.yaml
# Edit my-values.yaml and set:
#   - REPLACE_WITH_YOUR_REGISTRY
#   - REPLACE_WITH_YOUR_BEARER_TOKEN
#   - REPLACE_WITH_YOUR_LICENSE_B64
```

**Step 2: Deploy**
```bash
# For ECR users:
ECR_PASSWORD=$(aws ecr get-login-password --region us-east-1)
helm upgrade --install kdb-mcp ./kdb-x-mcp-server \
  --namespace aiq \
  -f my-values.yaml \
  --set imagePullSecret.password="$ECR_PASSWORD"

# For other registries:
helm upgrade --install kdb-mcp ./kdb-x-mcp-server \
  --namespace aiq \
  -f my-values.yaml
```

### Non-AWS Registry Examples

This chart works with any OCI-compliant container registry. No cloud-specific tools required.

**Docker Hub:**
```bash
helm upgrade --install kdb-mcp ./kdb-x-mcp-server \
  --namespace aiq \
  -f my-values.yaml \
  --set image.repository="docker.io/youruser/kdb-x-mcp-server" \
  --set imagePullSecret.create=true \
  --set imagePullSecret.registry="docker.io" \
  --set imagePullSecret.username="youruser" \
  --set imagePullSecret.password="your-access-token"
```

**Harbor / GitLab / Quay.io:**
```bash
helm upgrade --install kdb-mcp ./kdb-x-mcp-server \
  --namespace aiq \
  -f my-values.yaml \
  --set image.repository="registry.company.com/kdb/mcp-server" \
  --set imagePullSecret.create=true \
  --set imagePullSecret.registry="registry.company.com" \
  --set imagePullSecret.username="deploy-user" \
  --set imagePullSecret.password="deploy-token"
```

**Generic Kubernetes (k3s, minikube, kubeadm):**
```bash
# Uses default settings, works on any K8s cluster
helm upgrade --install kdb-mcp ./kdb-x-mcp-server \
  --namespace aiq \
  -f my-values.yaml
```

> **Note:** No AWS CLI, `gcloud`, or cloud-specific tools are required for non-cloud deployments.

### Internal Mode with Prebuilt KDB-X Image (Faster Startup)

For faster container startup, build the KDB-X image once:

```bash
# Set credentials
export KDB_BEARER_TOKEN="your-kx-bearer-token"
export KDB_B64_LICENSE="your-base64-license"

# Build and push KDB-X image
./scripts/build-kdbx-image.sh \
  --repository your-registry/kdb-x \
  --tag 1.3.0 \
  --push
```

Then deploy:

```yaml
# internal-prebuilt-values.yaml
mode: "internal"

image:
  repository: your-registry/kdb-x-mcp-server
  tag: "0.1.0"

kdbx:
  enabled: true
  installMode: "prebuilt"
  build:
    repository: "your-registry/kdb-x"
    tag: "1.3.0"
  imagePullSecret:
    create: true
    registry: "your-registry"
    username: "your-username"
    password: "your-password"

kdbLicense:
  create: true
  licenseB64: "your-base64-license"
```

### Internal Mode (MCP Server Only - External KDB)

```bash
helm install kdb-mcp ./kdb-x-mcp-server \
  --namespace aiq \
  --set mode=internal \
  --set image.repository=your-registry/kdb-x-mcp-server \
  --set image.tag=0.1.0 \
  --set database.host=your-kdb-host \
  --set database.port=5000
```

## Configuration

### Global Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `mode` | Deployment mode: `internal` or `external` | `internal` |

### External Mode Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `external.endpoint` | External MCP server URL | `""` |
| `external.apiKey` | API key for authenticated servers | `""` |
| `external.timeout` | Connection timeout in seconds | `30` |

### Internal Mode - MCP Server Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `mcp.serverName` | MCP server identifier | `KDBX_MCP_Server` |
| `mcp.logLevel` | Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL) | `INFO` |
| `mcp.transport` | Transport protocol | `streamable-http` |
| `mcp.host` | Bind address | `0.0.0.0` |
| `mcp.port` | Server port | `8000` |

### Internal Mode - Database Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `database.host` | KDB+/KDB-X hostname | `localhost` |
| `database.port` | KDB+/KDB-X port | `5000` |
| `database.username` | Database username | `""` |
| `database.password` | Database password | `""` |
| `database.tls` | Enable TLS | `false` |
| `database.timeout` | Connection timeout | `1` |
| `database.retry` | Retry attempts | `2` |
| `database.metric` | Vector similarity metric (CS, L2, IP) | `CS` |
| `database.k` | Vector search result count | `5` |

### Internal Mode - KDB-X Database Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `kdbx.enabled` | Deploy KDB-X database alongside MCP server | `false` |
| `kdbx.installMode` | Installation mode: `runtime` or `prebuilt` | `runtime` |
| `kdbx.build.bearerToken` | KX Portal OAuth bearer token (for runtime mode) | `""` |
| `kdbx.build.licenseB64` | Base64-encoded KDB-X license (for runtime mode) | `""` |
| `kdbx.build.repository` | Docker repository for prebuilt image | `""` |
| `kdbx.build.tag` | Tag for prebuilt image | `1.3.0` |
| `kdbx.imagePullSecret.create` | Create image pull secret for prebuilt image | `false` |
| `kdbx.service.port` | KDB-X service port | `5000` |
| `kdbx.resources.limits.cpu` | CPU limit for KDB-X | `2000m` |
| `kdbx.resources.limits.memory` | Memory limit for KDB-X | `4Gi` |

### Internal Mode - KDB License Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `kdbLicense.create` | Create KDB license secret | `false` |
| `kdbLicense.type` | License type: `personal` (kc.lic) or `commercial` (k4.lic) | `personal` |
| `kdbLicense.licenseB64` | Base64-encoded license content | `""` |
| `kdbLicense.existingSecret` | Use existing secret instead | `""` |

### Internal Mode - TLS Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `tls.enabled` | Enable TLS for KDB connection | `false` |
| `tls.caCertFile` | Path to CA certificate | `/etc/kdb-tls/ca.crt` |
| `tls.verifyServer` | Verify server certificate | `true` |

### Image Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `image.repository` | Image repository | `your-registry/kdb-x-mcp-server` |
| `image.tag` | Image tag | `0.1.0` |
| `image.pullPolicy` | Image pull policy | `Always` |

### Service Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `service.type` | Kubernetes service type | `ClusterIP` |
| `service.port` | Service port | `8000` |

### Resources

| Parameter | Description | Default |
|-----------|-------------|---------|
| `resources.limits.cpu` | CPU limit | `500m` |
| `resources.limits.memory` | Memory limit | `512Mi` |
| `resources.requests.cpu` | CPU request | `100m` |
| `resources.requests.memory` | Memory request | `128Mi` |

## Integrating with AIRA Backend

After installing this chart, configure your AIRA backend to use the KDB MCP server:

### Using ConfigMap (recommended)

The chart creates a ConfigMap with the MCP endpoint configuration. Reference it in your AIRA deployment:

```yaml
# In your aiq-aira values.yaml
backendEnvVars:
  KDB_ENABLED: "true"
  KDB_USE_NAT_CLIENT: "true"
  # For internal mode:
  KDB_MCP_ENDPOINT: "http://kdb-mcp-kdb-x-mcp-server.aiq.svc.cluster.local:8000/mcp"
  # For external mode:
  # KDB_MCP_ENDPOINT: "https://kdbxmcp.kxailab.com/mcp"
  KDB_TIMEOUT: "30"
```

### Using Environment Variables from ConfigMap

```yaml
envFrom:
  - configMapRef:
      name: kdb-mcp-kdb-x-mcp-server-config
```

## Building the Docker Image

The chart includes a Dockerfile for building the KDB-X MCP Server image:

```bash
cd deploy/helm/kdb-x-mcp-server

# Build for linux/amd64 (for Kubernetes)
docker build --platform linux/amd64 -t your-registry/kdb-x-mcp-server:0.1.0 .

# Push to your registry
docker push your-registry/kdb-x-mcp-server:0.1.0
```

## MCP Tools Available

The KDB-X MCP Server provides these tools:

- **sql_execute**: Execute SQL queries against KDB+/KDB-X databases
- **similarity_search**: Vector similarity search (KDB-X only)
- **hybrid_search**: Combined vector and SQL search (KDB-X only)

## Troubleshooting

### Check pod status
```bash
kubectl get pods -n aiq -l app.kubernetes.io/name=kdb-x-mcp-server
```

### View MCP Server logs
```bash
kubectl logs -n aiq -l app.kubernetes.io/name=kdb-x-mcp-server
```

### View KDB-X Database logs
```bash
kubectl logs -n aiq -l app.kubernetes.io/component=kdbx-database
```

### View KDB-X init container logs (runtime mode)
```bash
kubectl logs -n aiq <pod-name> -c install-kdbx
```

### Test MCP connectivity
```bash
kubectl port-forward -n aiq svc/kdb-mcp-kdb-x-mcp-server 8000:8000
curl http://localhost:8000/health
```

### Test KDB-X connectivity
```bash
kubectl port-forward -n aiq svc/kdb-mcp-kdb-x-mcp-server-kdbx 5000:5000
```

### Common Issues

**License Error ("no license loaded")**
- Ensure `kdbLicense.create: true`
- Verify the base64-encoded license is correct: `echo "your-license-b64" | base64 -d`
- Check the license type matches your license file (personal vs commercial)

**Init Container Fails (Runtime Mode)**
- Verify bearer token is valid (from https://portal.kx.com)
- Check network connectivity to portal.dl.kx.com
- Review init container logs

**Image Pull Errors**
- For prebuilt mode, configure `kdbx.imagePullSecret`
- Ensure registry credentials are correct

**Connection Refused to KDB-X**
- Verify KDB-X pod is running: `kubectl get pods -l app.kubernetes.io/component=kdbx-database`
- Check service exists: `kubectl get svc | grep kdbx`
- Ensure database.host is empty (auto-configured) when kdbx.enabled=true

## License

This chart is provided under the Apache 2.0 License.

The KDB-X MCP Server source code is available at: https://github.com/KxSystems/kdb-x-mcp-server
