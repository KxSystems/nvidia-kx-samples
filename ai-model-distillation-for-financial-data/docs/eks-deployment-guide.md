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

# EKS Deployment Guide

Deploy the Data Flywheel Blueprint on Amazon EKS with GPU-enabled nodes for NIM inference, fine-tuning, and evaluation.

> **Prerequisites:** AWS CLI configured, `eksctl` installed, `kubectl` installed, `helm` 3.8+ installed, Docker installed.
> **Estimated time:** ~45 minutes (cluster creation ~20 min, GPU operator ~5 min, app deployment ~15 min).

## Architecture Overview

```text
EKS Cluster: $EKS_CLUSTER_NAME ($AWS_REGION, k8s 1.31)
+-- system node group (2x m5.2xlarge)
|   +-- Data Flywheel API, Celery workers, MLflow, Flower
|   +-- KDB-X (persistent storage)
|   +-- Redis (Celery broker)
|   +-- NeMo microservices (Customizer, Evaluator, Data Store, etc.)
+-- gpu node group (2x p4d.24xlarge -- 8x A100 each)
    +-- NIM inference deployments (Llama 3.2 1B, etc.)
    +-- NeMo Customizer training jobs
    +-- LLM Judge (Llama 3.3 70B -- remote or local)
```

## Step 0: Configure Environment

All infrastructure parameters are stored in `deploy/.env`. Copy the example and fill in your values:

```bash
cp deploy/.env.example deploy/.env
```

Key EKS settings in `.env`:

```bash
# AWS
AWS_PROFILE=terraform-sa
AWS_REGION=us-west-2
AWS_ACCOUNT_ID=<your-account-id>    # auto-detected if empty

# EKS
EKS_CLUSTER_NAME=data-flywheel-dev

# VPC (leave empty to let eksctl create a new VPC)
VPC_ID=
SUBNET_PUBLIC_2A=
SUBNET_PUBLIC_2B=
SUBNET_PRIVATE_2A=
SUBNET_PRIVATE_2B=

# ECR
ECR_REPO_NAME=data-flywheel-server
IMAGE_TAG=0.5.1
```

Load the env into your shell:

```bash
set -a; source deploy/.env; set +a
```

## Step 1: Create the EKS Cluster

Generate the eksctl config from the template, then create the cluster:

```bash
# Generate eksctl-cluster.yaml from template (substitutes .env values)
envsubst < deploy/eksctl-cluster.yaml.tpl > deploy/eksctl-cluster.yaml

# Create the cluster (~15-20 minutes)
eksctl create cluster -f deploy/eksctl-cluster.yaml
```

If `VPC_ID` is empty in `.env`, eksctl creates a new VPC. Otherwise it uses the existing VPC and subnets.

Verify when done:

```bash
kubectl get nodes -o wide
# Expected: 2 system nodes + 2 gpu nodes
```

## Step 2: Install NVIDIA GPU Operator

The GPU operator installs drivers, device plugin, and container toolkit on GPU nodes.

```bash
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia
helm repo update

helm install gpu-operator nvidia/gpu-operator \
  --namespace gpu-operator --create-namespace \
  --set driver.enabled=true
```

Verify GPU detection (takes 2-3 minutes for DaemonSet rollout):

```bash
# Check operator pods
kubectl get pods -n gpu-operator

# Verify GPUs are detected on nodes
kubectl get nodes -o json | jq '.items[] | select(.status.capacity["nvidia.com/gpu"] != null) | {name: .metadata.name, gpus: .status.capacity["nvidia.com/gpu"]}'
```

## Step 3: Create StorageClasses

The Helm chart requires two StorageClasses: `kdbx-storage` (cluster default) and `kdbx-storage-1f` (single-AZ for NeMo Customizer training PVCs). The `kdbx-storage` class is marked as the cluster default because NeMo Bitnami PostgreSQL sub-charts create PVCs without specifying a StorageClass.

The manifest is at `deploy/storage-classes.yaml`. `deploy-eks.sh` auto-applies it if missing, but you can apply it manually:

```bash
kubectl apply -f deploy/storage-classes.yaml
```

Verify:

```bash
kubectl get storageclass
# kdbx-storage (default)   ebs.csi.aws.com   ...
# kdbx-storage-1f          ebs.csi.aws.com   ...
```

## Step 4: Install Volcano Scheduler

NeMo Customizer requires Volcano for training job scheduling. `deploy-eks.sh` auto-installs it if missing, but you can install it manually:

```bash
kubectl apply -f https://raw.githubusercontent.com/volcano-sh/volcano/v1.9.0/installer/volcano-development.yaml
```

Verify:

```bash
kubectl get namespaces | grep volcano
# Expected: volcano-monitoring, volcano-system
```

## Step 5: Install ingress-nginx Controller

NeMo microservices expose an Ingress resource that routes API paths (`/v1/namespaces`, `/v1/customization`, `/v1/evaluation`, `/v1/deployment`, etc.) to the correct backend services. An ingress-nginx controller is required to service this Ingress. `deploy-eks.sh` auto-installs it if missing, but you can install it manually:

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update
helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx --create-namespace \
  --set controller.service.type=ClusterIP \
  --set controller.watchIngressWithoutClass=true
```

Verify:

```bash
kubectl get pods -n ingress-nginx
# Expected: ingress-nginx-controller-* Running
kubectl get ingress -n nv-nvidia-blueprint-data-flywheel
# Expected: nemo-microservices-helm-chart with ADDRESS populated
```

## Step 6: Build and Push Docker Image

Build the Data Flywheel server image for `linux/amd64` (EKS runs on amd64 nodes):

```bash
# Derive the ECR registry URL from .env values
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# Build
docker build --platform linux/amd64 \
  -f deploy/Dockerfile \
  -t "${ECR_REGISTRY}/${ECR_REPO_NAME}:${IMAGE_TAG}" .
```

Authenticate to ECR and push:

```bash
aws ecr get-login-password --region "${AWS_REGION}" --profile "${AWS_PROFILE}" \
  | docker login --username AWS --password-stdin "${ECR_REGISTRY}"

docker push "${ECR_REGISTRY}/${ECR_REPO_NAME}:${IMAGE_TAG}"
```

> **Note:** If the ECR repository doesn't exist yet, create it:
> ```bash
> aws ecr create-repository --repository-name "${ECR_REPO_NAME}" \
>   --region "${AWS_REGION}" --profile "${AWS_PROFILE}"
> ```

## Step 7: Configure Secrets

Ensure `deploy/.env` has all required API keys (see `deploy/.env.example`):

```bash
# Required
NVIDIA_API_KEY=nvapi-xxxxx
NGC_API_KEY=nvapi-xxxxx          # Usually same as NVIDIA_API_KEY
HF_TOKEN=hf_xxxxx
KDB_LICENSE_B64=<base64-encoded>

# Optional
LLM_JUDGE_API_KEY=               # Defaults to NVIDIA_API_KEY
EMB_API_KEY=                     # Defaults to NVIDIA_API_KEY
KDBX_USERNAME=
KDBX_PASSWORD=
```

> **KDB License:** Encode your `kc.lic` file: `base64 -i kc.lic | tr -d '\n'`

## Step 8: Deploy with deploy-eks.sh

The deployment script reads all parameters from `deploy/.env`, handles namespace creation, Helm dependency build, secret injection (via temp file), and `helm upgrade --install`.

```bash
./deploy/deploy-eks.sh
```

The script will:
1. Run pre-flight checks (kubectl context, GPU operator)
2. Auto-create StorageClasses if missing (`deploy/storage-classes.yaml`)
3. Auto-install Volcano scheduler if missing
4. Auto-install ingress-nginx controller if missing (cluster-internal, for NeMo service routing)
5. Create the namespace `nv-nvidia-blueprint-data-flywheel`
6. Build Helm dependencies
7. Deploy via `helm upgrade --install` with `deploy/eks-values.yaml`
8. Inject ECR image via `--set` (from `AWS_ACCOUNT_ID`, `AWS_REGION`, `ECR_REPO_NAME`, `IMAGE_TAG`)
9. Wait for pods to be ready
10. Print the NLB endpoint URL

## Step 9: Verify Deployment

### Check pod status

```bash
kubectl get pods -n nv-nvidia-blueprint-data-flywheel
```

Expected pods (all `Running`):
- `df-api-deployment-*` -- FastAPI server
- `df-celery-worker-deployment-*` -- Task workers
- `df-celery-parent-worker-deployment-*` -- Orchestrator
- `df-kdbx-deployment-*` -- KDB-X database
- `df-redis-deployment-*` -- Redis broker
- `df-mlflow-deployment-*` -- Experiment tracking
- `data-flywheel-customizer-*` -- NeMo Customizer
- `data-flywheel-evaluator-*` -- NeMo Evaluator
- `data-flywheel-data-store-*` -- NeMo Data Store

### Test API endpoint

```bash
# Get NLB hostname
API_LB=$(kubectl get svc df-api-service -n nv-nvidia-blueprint-data-flywheel \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

# Test the API (NLB may take 2-3 minutes to provision)
curl -s http://${API_LB}:8000/api/jobs | jq .
# Expected: {"jobs": []}
```

### Verify GPU access

```bash
# Run nvidia-smi on a GPU node
kubectl run gpu-test --rm -it --restart=Never \
  --image=nvidia/cuda:12.4.0-base-ubuntu22.04 \
  --overrides='{"spec":{"tolerations":[{"key":"nvidia.com/gpu","operator":"Exists","effect":"NoSchedule"}],"nodeSelector":{"role":"gpu"}}}' \
  -- nvidia-smi
```

### Port-forward internal services

```bash
# MLflow UI
kubectl port-forward svc/df-mlflow-service 5000:5000 -n nv-nvidia-blueprint-data-flywheel

# KDB-X
kubectl port-forward svc/df-kdbx-service 8082:8082 -n nv-nvidia-blueprint-data-flywheel

# Flower (if non-production profile)
kubectl port-forward svc/df-flower-service 5555:5555 -n nv-nvidia-blueprint-data-flywheel
```

## Step 10: Load Market Data & Run Financial Pipeline

The financial features (market enrichment, backtesting) require market data in KDB-X. This step loads sample data and runs a full pipeline job.

### Load test data

Port-forward KDB-X and run the data loaders:

```bash
# Port-forward KDB-X
kubectl port-forward svc/df-kdbx-service 8082:8082 -n nv-nvidia-blueprint-data-flywheel &

# Load FinGPT sentiment dataset
PYTHONPATH=. python src/scripts/load_test_data.py --file fingpt_sentiment_1k.jsonl --workload-id news_sentiment --client-id fingpt-1k

# Load market data (OHLCV + order book)
PYTHONPATH=. python -c "
from kdbx.market_tables import create_market_tables, load_parquet_data
create_market_tables()
load_parquet_data('data/sample_market_data.parquet')
"
```

### Submit a job

```bash
API_LB=$(kubectl get svc df-api-service -n nv-nvidia-blueprint-data-flywheel \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

curl -X POST "http://${API_LB}:8000/api/jobs" \
  -H "Content-Type: application/json" \
  -d '{"workload_id": "news_sentiment", "client_id": "fingpt-1k"}'
```

### Expected pipeline stages

1. **initialize_workflow** — Creates flywheel run record
2. **create_datasets** — Enriches records with market context via KDB-X `aj`, splits into eval (20) and train
3. **wait_for_llm_as_judge** — Deploys or connects to the LLM judge model
4. **spin_up_nim** — Deploys Llama 3.2 1B via NIM (~3 min)
5. **run_base_eval** — Evaluates base model (F1 score)
6. **generate_signals (base)** — Calls the NIM to generate trading signals from eval records
7. **run_backtest_assessment (base)** — Vectorised backtest via KDB-X `aj` (Sharpe, drawdown, win rate)
8. **start_customization → run_customization_eval** — LoRA fine-tuning via NeMo Customizer (~6 min), then evaluates fine-tuned model
9. **generate_signals (customized)** — Generates trading signals using the fine-tuned model
10. **run_backtest_assessment (customized)** — Backtests the customized model's signals
11. **shutdown_deployment** — Removes NIM deployment
12. **finalize** — Marks run as complete

Total runtime: ~10-15 minutes.

## Teardown

### Remove the Helm release

```bash
./deploy/teardown-eks.sh
```

### Delete the EKS cluster

```bash
# Remove GPU operator first
helm uninstall gpu-operator -n gpu-operator

# Delete ingress-nginx
helm uninstall ingress-nginx -n ingress-nginx

# Delete Volcano
kubectl delete -f https://raw.githubusercontent.com/volcano-sh/volcano/v1.9.0/installer/volcano-development.yaml

# Delete the cluster (removes all node groups, VPC resources, IAM roles)
eksctl delete cluster --name "${EKS_CLUSTER_NAME}" --region "${AWS_REGION}"
```

## EKS-Specific Configuration

The `deploy/eks-values.yaml` overrides the defaults for EKS:

| Setting | Value | Purpose |
|---------|-------|---------|
| `kdbx.persistence.storageClass` | `kdbx-storage` | gp3 EBS for KDB-X data |
| `kdbx.persistence.size` | `50Gi` | Production-sized KDB-X storage |
| `kdbx.service.type` | `ClusterIP` | Internal-only KDB-X access |
| `redis.service.type` | `ClusterIP` | Internal-only Redis access |
| `foundationalFlywheelServer.image` | `$ECR_IMAGE` (from `.env`) | Custom image with KDB-X support |
| `api.service.type` | `LoadBalancer` (NLB) | Internet-facing API endpoint |
| `llm_judge_config.deployment_type` | `remote` | Uses NVIDIA API Catalog (saves GPU) |
| `customizer.storageClassName` | `kdbx-storage` | EBS for model checkpoints |
| `customizer.training.pvc.storageClass` | `kdbx-storage-1f` | Single-AZ EBS for training |
| `nmp_config.nemo_base_url` | `http://ingress-nginx-controller.ingress-nginx:80` | Reverse proxy routing to NeMo sub-services |
| `enrichment_config.enabled` | `true` | Enrich training records with market context via KDB-X `aj` |
| `enrichment_config.sym_extraction` | `regex` | Extract tickers from text using regex |
| `backtest_config.enabled` | `true` | Run vectorised backtesting via KDB-X as-of joins |
| `backtest_config.cost_bps` | `5.0` | Round-trip transaction cost in basis points |

## Environment Variables Reference

All EKS deployment parameters (set in `deploy/.env`):

| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_PROFILE` | `terraform-sa` | AWS CLI profile |
| `AWS_REGION` | `us-west-2` | AWS region for the cluster |
| `AWS_ACCOUNT_ID` | auto-detected | AWS account ID (for ECR URL) |
| `EKS_CLUSTER_NAME` | `data-flywheel-dev` | EKS cluster name |
| `VPC_ID` | (empty = new VPC) | Existing VPC ID |
| `SUBNET_PUBLIC_2A` | (empty) | Public subnet in AZ a |
| `SUBNET_PUBLIC_2B` | (empty) | Public subnet in AZ b |
| `SUBNET_PRIVATE_2A` | (empty) | Private subnet in AZ a |
| `SUBNET_PRIVATE_2B` | (empty) | Private subnet in AZ b |
| `ECR_REPO_NAME` | `data-flywheel-server` | ECR repository name |
| `IMAGE_TAG` | `0.5.1` | Docker image tag |

## Cost Estimates

| Resource | Instance | Count | On-Demand $/hr |
|----------|----------|-------|-----------------|
| System nodes | m5.2xlarge | 2 | ~$0.77/node |
| GPU nodes | p4d.24xlarge | 2 | ~$32.77/node |
| EBS (gp3) | -- | ~600 GB total | ~$0.08/GB-month |
| NAT Gateway | -- | 1 | ~$0.045/hr |
| NLB | -- | 1 | ~$0.023/hr |

**Total:** ~$67/hr (~$1,600/day). Use spot instances for GPU nodes or scale to 0 when idle to reduce costs.

> **Tip:** Set `gpu` node group `minSize: 0` in `deploy/eksctl-cluster.yaml.tpl` and scale down when not training:
> ```bash
> eksctl scale nodegroup --cluster "${EKS_CLUSTER_NAME}" --name gpu --nodes 0 --nodes-min 0
> ```

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Pods stuck `Pending` | No GPU nodes / PVC not binding | `kubectl describe pod <name>` -- check events |
| `StorageClass not found` | Missing StorageClass | Run Step 3 |
| `nvidia.com/gpu: 0` on nodes | GPU operator not ready | Wait for `gpu-operator` DaemonSets, check logs |
| NLB hostname empty | NLB still provisioning | Wait 2-3 min, then `kubectl get svc df-api-service` |
| Image pull error | ECR auth expired | Re-run `aws ecr get-login-password` |
| Celery workers CrashLoop | KDB-X or Redis not ready | Check those pods first; workers retry on connect |
| Customizer training hangs | Volcano not installed | Run Step 4 |
| `Failed to resolve 'ingress-nginx-controller.ingress-nginx'` | ingress-nginx not installed | Run Step 5 |
| Job stuck `pending` after fresh deploy | Parent worker init failed (KDB-X not ready at startup) | `kubectl rollout restart deployment df-celery-parent-worker-deployment -n nv-nvidia-blueprint-data-flywheel` |
| Training pod `Pending` (PVC wrong AZ) | `kdbx-storage-1f` PVC bound to AZ without GPU nodes | Delete the PVC, add `allowedTopologies` to StorageClass restricting to the GPU node AZ |
| `Enrichment failed: valid q license` | `kx.toq(DataFrame_with_Categorical)` needs PyKX licensed mode | Fixed: enrichment uses `kx.SymbolVector` + `kx.TimestampVector` (no license needed) |
| New worker pod `Pending` (Insufficient CPU) | Rolling update can't fit 2 workers simultaneously | Delete the old worker pod manually: `kubectl delete pod <old-worker>` |

For more detailed troubleshooting, see [Helm Installation Guide](11-helm-installation.md#troubleshooting) and [FAQ](faq-troubleshooting.md).
