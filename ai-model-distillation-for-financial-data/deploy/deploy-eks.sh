#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART_DIR="${SCRIPT_DIR}/helm/data-flywheel"
EKS_VALUES="${SCRIPT_DIR}/eks-values.yaml"
ENV_FILE="${SCRIPT_DIR}/.env"
RELEASE_NAME="data-flywheel"
NAMESPACE="nv-nvidia-blueprint-data-flywheel"
TIMEOUT="10m"

# AWS / EKS defaults — override via .env or environment
export AWS_PROFILE="${AWS_PROFILE:-default}"
export AWS_REGION="${AWS_REGION:-us-west-2}"
export AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")}"
export EKS_CLUSTER_NAME="${EKS_CLUSTER_NAME:-data-flywheel-dev}"
export ECR_REPO_NAME="${ECR_REPO_NAME:-data-flywheel-server}"
export IMAGE_TAG="${IMAGE_TAG:-0.5.1}"
export ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
export ECR_IMAGE="${ECR_REGISTRY}/${ECR_REPO_NAME}:${IMAGE_TAG}"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# --- Load .env file ---
if [[ -f "${ENV_FILE}" ]]; then
    info "Loading secrets from ${ENV_FILE}"
    set -a
    # shellcheck source=/dev/null
    source "${ENV_FILE}"
    set +a
else
    warn "No .env file found at ${ENV_FILE} — expecting env vars to be set"
fi

# NGC_API_KEY defaults to NVIDIA_API_KEY if not set
: "${NGC_API_KEY:=${NVIDIA_API_KEY:-}}"

# --- Pre-flight checks ---
info "Running pre-flight checks (AWS_PROFILE=${AWS_PROFILE})..."

command -v kubectl >/dev/null 2>&1 || error "kubectl not found"
command -v helm    >/dev/null 2>&1 || error "helm not found"

# Verify kubectl context
CONTEXT=$(kubectl config current-context 2>/dev/null) || error "No kubectl context set"
info "Using kubectl context: ${CONTEXT}"

# Check for NVIDIA GPU operator / device plugin
if kubectl get pods -n gpu-operator -l app=nvidia-device-plugin-daemonset --no-headers 2>/dev/null | grep -q Running; then
    info "NVIDIA GPU operator found"
elif kubectl get daemonset -n kube-system nvidia-device-plugin-daemonset >/dev/null 2>&1; then
    info "NVIDIA device plugin found"
else
    warn "NVIDIA device plugin not detected — GPU workloads may not schedule"
fi

# Ensure StorageClasses exist (kdbx-storage is the cluster default)
if kubectl get storageclass kdbx-storage >/dev/null 2>&1; then
    info "StorageClass 'kdbx-storage' found"
else
    info "Creating StorageClasses from ${SCRIPT_DIR}/storage-classes.yaml..."
    kubectl apply -f "${SCRIPT_DIR}/storage-classes.yaml"
fi

# Ensure Volcano scheduler is installed (required by NeMo Customizer)
if kubectl get namespace volcano-system >/dev/null 2>&1; then
    info "Volcano scheduler found"
else
    info "Installing Volcano scheduler..."
    kubectl apply -f https://raw.githubusercontent.com/volcano-sh/volcano/v1.9.0/installer/volcano-development.yaml
fi

# Ensure ingress-nginx controller is installed (required by NeMo microservices routing)
if kubectl get deployment ingress-nginx-controller -n ingress-nginx >/dev/null 2>&1; then
    info "ingress-nginx controller found"
else
    info "Installing ingress-nginx controller (cluster-internal)..."
    helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx 2>/dev/null || true
    helm repo update ingress-nginx
    helm install ingress-nginx ingress-nginx/ingress-nginx \
        --namespace ingress-nginx --create-namespace \
        --set controller.service.type=ClusterIP \
        --set controller.watchIngressWithoutClass=true
    info "Waiting for ingress-nginx controller to be ready..."
    kubectl wait --for=condition=ready pod \
        -l app.kubernetes.io/name=ingress-nginx \
        -n ingress-nginx --timeout=120s
fi

# Ensure ingress-nginx pods are actually running (may need restart after scale-up)
NGINX_READY=$(kubectl get pods -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l)
if [[ "${NGINX_READY}" -eq 0 ]]; then
    info "ingress-nginx pods not running, restarting..."
    kubectl rollout restart deployment ingress-nginx-controller -n ingress-nginx
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=ingress-nginx -n ingress-nginx --timeout=120s
fi

# Required environment variables
: "${NVIDIA_API_KEY:?Set NVIDIA_API_KEY in .env or environment}"
: "${NGC_API_KEY:?Set NGC_API_KEY in .env or environment (defaults to NVIDIA_API_KEY)}"
: "${KDB_LICENSE_B64:?Set KDB_LICENSE_B64 in .env or environment}"

info "All pre-flight checks passed"

# --- Create namespace ---
info "Ensuring namespace '${NAMESPACE}' exists..."
kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

# --- Helm dependency build ---
info "Building Helm dependencies..."
helm dependency build "${CHART_DIR}"

# --- Build secrets values file (avoids leaking secrets via --set in process table) ---
SECRETS_FILE=$(mktemp)
chmod 600 "${SECRETS_FILE}"
trap 'rm -f "${SECRETS_FILE}"' EXIT

cat > "${SECRETS_FILE}" <<EOF
secrets:
  ngcApiKey: "${NGC_API_KEY}"
  nvidiaApiKey: "${NVIDIA_API_KEY}"
  kdbLicenseB64: "${KDB_LICENSE_B64}"
  kdbBearerToken: "${KDBAI_REGISTRY_TOKEN:-}"
  hfToken: "${HF_TOKEN:-}"
  llmJudgeApiKey: "${LLM_JUDGE_API_KEY:-}"
  embApiKey: "${EMB_API_KEY:-}"
  kdbxUsername: "${KDBX_USERNAME:-}"
  kdbxPassword: "${KDBX_PASSWORD:-}"
EOF

# --- Helm install/upgrade ---
# Note: --wait is omitted because the WaitForFirstConsumer PVC
# (core-job-storage) never binds until a training job runs, causing
# a false timeout.  Pod readiness is verified separately below.
info "Deploying ${RELEASE_NAME} to ${NAMESPACE}..."
helm upgrade --install "${RELEASE_NAME}" "${CHART_DIR}" \
    --namespace "${NAMESPACE}" \
    -f "${EKS_VALUES}" \
    -f "${SECRETS_FILE}" \
    --set "foundationalFlywheelServer.image.repository=${ECR_REGISTRY}/${ECR_REPO_NAME}" \
    --set "foundationalFlywheelServer.image.tag=${IMAGE_TAG}" \
    --timeout "${TIMEOUT}"

# --- Wait for pods ---
info "Waiting for pods to be ready (timeout ${TIMEOUT})..."
kubectl wait --for=condition=Ready pod \
    -l "app in (df-api-deployment,df-celery-worker-deployment,df-celery-parent-worker-deployment,df-kdbx-deployment,df-redis-deployment,df-mlflow-deployment)" \
    -n "${NAMESPACE}" \
    --timeout="${TIMEOUT}" 2>/dev/null || {
    warn "Some pods may not be ready yet. Current status:"
    kubectl get pods -n "${NAMESPACE}"
}

# --- Print endpoints ---
echo ""
info "=== Deployment Complete ==="
echo ""

# API endpoint (NLB)
API_LB=$(kubectl get svc df-api-service -n "${NAMESPACE}" \
    -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)
if [[ -n "${API_LB}" ]]; then
    info "API endpoint: http://${API_LB}:8000"
else
    warn "NLB hostname not yet available — check: kubectl get svc df-api-service -n ${NAMESPACE}"
fi

echo ""
info "Port-forward commands for internal services:"
echo "  MLflow:  kubectl port-forward svc/df-mlflow-service  5000:5000 -n ${NAMESPACE}"
echo "  Flower:  kubectl port-forward svc/df-flower-service  5555:5555 -n ${NAMESPACE}"
echo "  KDB-X:   kubectl port-forward svc/df-kdbx-service    8082:8082 -n ${NAMESPACE}"
echo "  Redis:   kubectl port-forward svc/df-redis-service    6379:6379 -n ${NAMESPACE}"
echo ""
info "Check pod status: kubectl get pods -n ${NAMESPACE}"
