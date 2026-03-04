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
ENV_FILE="${SCRIPT_DIR}/.env"

# Load .env if present
if [[ -f "${ENV_FILE}" ]]; then
    set -a; source "${ENV_FILE}"; set +a
fi

RELEASE_NAME="data-flywheel"
NAMESPACE="nv-nvidia-blueprint-data-flywheel"

export AWS_PROFILE="${AWS_PROFILE:-default}"
export AWS_REGION="${AWS_REGION:-us-west-2}"
export EKS_CLUSTER_NAME="${EKS_CLUSTER_NAME:-data-flywheel-dev}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }

# --- Helm uninstall ---
info "Uninstalling Helm release '${RELEASE_NAME}'..."
if helm status "${RELEASE_NAME}" -n "${NAMESPACE}" >/dev/null 2>&1; then
    helm uninstall "${RELEASE_NAME}" -n "${NAMESPACE}" --wait
    info "Helm release uninstalled"
else
    warn "Release '${RELEASE_NAME}' not found in namespace '${NAMESPACE}'"
fi

# --- PVC cleanup ---
PVCS=$(kubectl get pvc -n "${NAMESPACE}" -o name 2>/dev/null || true)
if [[ -n "${PVCS}" ]]; then
    info "Deleting PVCs in ${NAMESPACE}..."
    kubectl delete pvc --all -n "${NAMESPACE}"
    info "PVCs deleted"
else
    info "No PVCs found"
fi

# --- Namespace deletion (optional) ---
echo ""
read -rp "Delete namespace '${NAMESPACE}'? [y/N] " REPLY
if [[ "${REPLY}" =~ ^[Yy]$ ]]; then
    info "Deleting namespace '${NAMESPACE}'..."
    kubectl delete namespace "${NAMESPACE}"
    info "Namespace deleted"
else
    info "Namespace kept"
fi

echo ""
info "Teardown complete"
