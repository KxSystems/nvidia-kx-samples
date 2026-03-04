#!/usr/bin/env bash
set -euo pipefail

# === Debug Settings ===
trap 'echo "Error on line $LINENO: Command failed with exit code $?" >&2' ERR

# === Utility Functions ===
log() { echo -e "\033[1;32m[INFO]\033[0m $*"; }
warn() { echo -e "\033[1;33m[WARN]\033[0m $*"; }
err() { echo -e "\033[1;31m[ERROR]\033[0m $*" >&2; }
die() { err "$*"; exit 1; }

# Check if running as root
is_root() {
  [[ $EUID -eq 0 ]] || [[ $(id -u) -eq 0 ]]
}

# Run a command with sudo if not root
maybe_sudo() {
  if is_root; then
    "$@"
  else
    sudo "$@"
  fi
}

# === Install Required Tools ===
install_tools() {
  log "Installing required tools..."
  
  # Install snap if not available
  if ! command -v snap >/dev/null 2>&1; then
    log "Installing snapd..."
    maybe_sudo apt update
    maybe_sudo apt install -y snapd
  fi
  
  # Install yq
  if ! command -v yq >/dev/null 2>&1; then
    log "Installing yq..."
    maybe_sudo snap install yq
  fi
  
  # Install huggingface-cli
  if ! command -v huggingface-cli >/dev/null 2>&1; then
    log "Installing huggingface-cli..."
    if ! command -v pip >/dev/null 2>&1; then
      maybe_sudo apt update
      maybe_sudo apt install -y python3-pip
    fi
    pip install --upgrade pip
    pip install -U "huggingface_hub[cli]"
    export PATH="$HOME/.local/bin:$PATH"
  fi
  
  # Set up apps directory
  export APP_PATH=$HOME/apps
  mkdir -p "$APP_PATH"
  export PATH="$APP_PATH:$PATH"
  
  # Install minikube
  if ! command -v minikube >/dev/null 2>&1 && ! [[ -f "$APP_PATH/minikube" ]]; then
    log "Installing minikube..."
    cd "$APP_PATH"
    wget -q https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64 -O minikube
    chmod +x minikube
  fi
  
  # Install helm
  if ! command -v helm >/dev/null 2>&1 && ! [[ -f "$APP_PATH/helm" ]]; then
    log "Installing helm..."
    cd "$APP_PATH"
    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 -o get_helm.sh
    chmod +x get_helm.sh
    USE_SUDO=false HELM_INSTALL_DIR="$APP_PATH" ./get_helm.sh
  fi
  
  # Install kubectl
  if ! command -v kubectl >/dev/null 2>&1 && ! [[ -f "$APP_PATH/kubectl" ]]; then
    log "Installing kubectl..."
    cd "$APP_PATH"
    curl -fsSL -o kubectl "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
    chmod +x kubectl
  fi
  
  # Update PATH for current session
  export PATH="$APP_PATH:$HOME/.local/bin:$PATH"
  
  # Update bashrc if not already done
  if ! grep -q "$APP_PATH" ~/.bashrc 2>/dev/null; then
    log "Updating ~/.bashrc with PATH settings..."
    cat <<EOF >> ~/.bashrc

# Added by NeMo setup script
export PATH=\$PATH:$APP_PATH
export PATH=\$PATH:\$HOME/.local/bin

# Tab completion in bash
if command -v kubectl >/dev/null 2>&1; then
    source <(kubectl completion bash)
fi
if command -v helm >/dev/null 2>&1; then
    source <(helm completion bash)
fi

# Use k instead of kubectl and make sure completion works
alias k="kubectl"
if command -v kubectl >/dev/null 2>&1; then
    complete -o default -F __start_kubectl k
fi
EOF
  fi
  
  log "Tools installation completed."
}

# === Prerequisites Check ===
check_prerequisites() {
  log "Checking prerequisites..."
  
  # Check that NGC_API_KEY is set
  if [[ -z "${NGC_API_KEY:-}" ]]; then
    die "NGC_API_KEY environment variable is not set. Please set it before running this script."
  fi
  
  # Check that NVIDIA_API_KEY is set
  if [[ -z "${NVIDIA_API_KEY:-}" ]]; then
    die "NVIDIA_API_KEY environment variable is not set. Please set it before running this script."
  fi
  
  # Check for docker
  if ! command -v docker >/dev/null 2>&1; then
    die "Docker is not installed. Please install Docker first."
  fi
  
  # Verify all tools are now available
  local missing_commands=()
  for cmd in minikube kubectl helm huggingface-cli; do
    if ! command -v "$cmd" >/dev/null 2>&1 && ! [[ -f "$APP_PATH/$cmd" ]]; then
      missing_commands+=("$cmd")
    fi
  done
  
  if [[ ${#missing_commands[@]} -gt 0 ]]; then
    die "Missing required commands after installation: ${missing_commands[*]}"
  fi
  
  log "Prerequisites check completed successfully."
}

# === Start Minikube ===
start_minikube() {
  log "Checking Minikube status..."
  
  # Check if minikube is already running
  if minikube status &>/dev/null; then
    warn "Minikube is already running. Deleting existing cluster for clean setup..."
    minikube delete
  fi

  log "Starting Minikube with GPU support..."
  
  # Add --force flag if running as root
  local extra_args=""
  if is_root; then
    extra_args="--force"
    log "Running as root, adding --force flag to minikube command"
  fi
  
  minikube start \
    --driver docker \
    --container-runtime docker \
    --cpus no-limit \
    --memory no-limit \
    --gpus all \
    $extra_args

  log "Enabling ingress addon..."
  minikube addons enable ingress
  
  log "Waiting for ingress controller to be ready..."
  # Wait for ingress-nginx-controller deployment to be available
  kubectl wait --namespace ingress-nginx \
    --for=condition=ready pod \
    --selector=app.kubernetes.io/component=controller \
    --timeout=300s || warn "Ingress controller pods may still be initializing"
  
  # Wait for the webhook service to be ready
  log "Waiting for ingress admission webhook to be ready..."
  local max_wait=120
  local elapsed=0
  while ! kubectl get validatingwebhookconfigurations ingress-nginx-admission &>/dev/null; do
    if (( elapsed >= max_wait )); then
      warn "Webhook configuration not found after ${max_wait}s, continuing anyway..."
      break
    fi
    sleep 5
    elapsed=$((elapsed + 5))
    log "Still waiting for ingress webhook configuration... (${elapsed}s/${max_wait}s)"
  done
  
  # Additional wait for webhook service endpoint to be ready
  sleep 10
  
  log "Labeling node for GPU availability..."
  kubectl label node minikube feature.node.kubernetes.io/pci-10de.present=true --overwrite
  
  log "Minikube setup completed successfully."
}

# === Install NeMo Microservices Platform ===
setup_kubernetes_secrets() {
  log "Setting up NGC secrets in Kubernetes..."
  
  # Create NGC image pull secret
  kubectl create secret docker-registry nvcrimagepullsecret \
    --docker-server=nvcr.io \
    --docker-username='$oauthtoken' \
    --docker-password="$NGC_API_KEY" \
    --dry-run=client -o yaml | kubectl apply -f -

  # Create NGC API secret
  kubectl create secret generic ngc-api \
    --from-literal=NGC_API_KEY="$NGC_API_KEY" \
    --dry-run=client -o yaml | kubectl apply -f -
  
  # Create NVIDIA API secret
  kubectl create secret generic nvidia-api \
    --from-literal=NVIDIA_API_KEY="$NVIDIA_API_KEY" \
    --dry-run=client -o yaml | kubectl apply -f -
  
  log "Kubernetes secrets created successfully."
}

install_nemo_platform() {
  log "Adding NeMo Microservices Helm repository..."
  
  helm repo add nmp https://helm.ngc.nvidia.com/nvidia/nemo-microservices \
    --username='$oauthtoken' \
    --password="$NGC_API_KEY"
  
  helm repo update
  
  log "Installing Volcano scheduler..."
  kubectl apply -f https://raw.githubusercontent.com/volcano-sh/volcano/v1.9.0/installer/volcano-development.yaml
  
  log "Installing NeMo Microservices Helm Chart..."
  
  # Try installing with webhook validation, if it fails, retry with annotation to skip validation
  if ! helm --namespace default install \
    nemo nmp/nemo-microservices-helm-chart \
    --set guardrails.guardrails.nvcfAPIKeySecretName="nvidia-api" 2>/dev/null; then
    
    warn "Initial installation failed, retrying with webhook validation bypass..."
    
    # Delete any partial installation
    helm uninstall nemo --namespace default 2>/dev/null || true
    
    # Retry with annotation to skip ingress validation
    helm --namespace default install \
      nemo nmp/nemo-microservices-helm-chart \
      --set guardrails.guardrails.nvcfAPIKeySecretName="nvidia-api" \
      --set ingress.annotations."nginx\.ingress\.kubernetes\.io/enable-admission-webhook"="false"
  fi
  
  log "NeMo Microservices platform installation initiated."
}

# === Wait for Pods ===
wait_for_pods() {
  log "Waiting for pods to be ready (up to 30 minutes)..."
  log "During this time, pods may be in pending or restarting state - this is normal."
  
  local old_err_trap=$(trap -p ERR)
  trap 'echo "Interrupted by user. Exiting."; exit 1;' SIGINT
  
  local start_time=$(date +%s)
  local end_time=$((start_time + 1800))  # 30 minutes

  while true; do
    local current_time=$(date +%s)
    if (( current_time >= end_time )); then
      warn "Timeout waiting for pods after 30 minutes. Some pods may still be initializing."
      warn "You can continue monitoring with: kubectl get pods"
      break
    fi

    # Get pod statuses
    local pod_statuses
    if ! pod_statuses=$(kubectl get pods --no-headers 2>/dev/null); then
        warn "Failed to get pod statuses. Retrying..."
        sleep 10
        continue
    fi

    # Check for image pull errors
    local image_pull_errors
    image_pull_errors=$(echo "$pod_statuses" | grep -E "ImagePullBackOff|ErrImagePull" || true)
    if [[ -n "$image_pull_errors" ]]; then
      err "Detected ImagePull errors:"
      echo "$image_pull_errors" >&2
      warn "You may want to check NGC credentials or network connectivity."
      warn "Run 'kubectl events' for more details."
    fi

    # Count ready pods (Running or Completed)
    local total_pods running_pods
    total_pods=$(echo "$pod_statuses" | wc -l)
    running_pods=$(echo "$pod_statuses" | grep -E "Running|Completed" | wc -l || echo 0)
    
    log "Pod status: $running_pods/$total_pods pods ready"
    
    # Check if all pods are ready or in acceptable states
    if ! echo "$pod_statuses" | grep -v -E "Running|Completed" | grep -qE "Pending|ContainerCreating|Init:"; then
      log "All pods are in ready state."
      break
    fi

    sleep 15
  done
  
  # Restore trap
  eval "$old_err_trap"
  trap - SIGINT
  
  # Final pod status check
  log "Final pod status:"
  kubectl get pods
  
  log "Pod initialization completed."
}

# === Configure DNS ===
configure_dns() {
  log "Configuring DNS resolution..."
  
  # Display ingress resources
  log "Current ingress resources:"
  kubectl get ingress || warn "No ingress resources found yet"
  
  # Get minikube IP
  local nemo_host
  nemo_host=$(minikube ip)
  log "Minikube IP: $nemo_host"
  
  # Backup /etc/hosts
  log "Creating backup of /etc/hosts..."
  maybe_sudo cp /etc/hosts "/etc/hosts.bak.$(date +%Y%m%d%H%M%S)"
  
  # Remove existing entries if they exist
  maybe_sudo sed -i.tmp '/nemo\.test\|nim\.test\|data-store\.test/d' /etc/hosts
  
  # Add new entries
  log "Adding host entries to /etc/hosts..."
  {
    echo "# Added by NeMo Microservices setup script"
    echo "$nemo_host nemo.test"
    echo "$nemo_host nim.test" 
    echo "$nemo_host data-store.test"
  } | maybe_sudo tee -a /etc/hosts > /dev/null
  
  log "DNS configuration completed."
  log "You can now access services at:"
  log "  - NeMo Platform: http://nemo.test"
  log "  - NIM Services: http://nim.test"
  log "  - Data Store: http://data-store.test"
}

# === Verification ===
verify_installation() {
  log "Verifying installation..."
  
  # Wait a bit for ingress to be ready
  sleep 10
  
  # Check ingress status
  if kubectl get ingress >/dev/null 2>&1; then
    log "✓ Ingress resources created"
    kubectl get ingress
  else
    warn "⚠ No ingress resources found"
  fi
  
  # Check key services
  local key_services=("data-store" "guardrails")
  for service in "${key_services[@]}"; do
    if kubectl get svc | grep -q "$service"; then
      log "✓ Service $service found"
    else
      warn "⚠ Service $service not found"
    fi
  done
  
  log "Installation verification completed."
}

# === Cleanup Function ===
show_cleanup_instructions() {
  cat << EOF

=== SETUP COMPLETE ===

Your NeMo Microservices platform is now installed and running on minikube.

Access URLs:
  - NeMo Platform: http://nemo.test
  - NIM Services: http://nim.test  
  - Data Store: http://data-store.test

To monitor pod status:
  kubectl get pods

To view logs for troubleshooting:
  kubectl logs <pod-name>

To clean up when you're done:
  minikube delete
  sudo cp /etc/hosts.bak.* /etc/hosts  # Restore hosts file

For tutorials and next steps, visit:
https://docs.nvidia.com/nemo/microservices/latest/get-started/tutorials/

EOF
}

# === Main Function ===
main() {
  log "Starting NVIDIA NeMo Microservices Platform setup..."
  log "This script follows the official NVIDIA documentation setup process."
  
  install_tools
  check_prerequisites
  start_minikube
  setup_kubernetes_secrets
  install_nemo_platform
  wait_for_pods
  configure_dns
  verify_installation
  show_cleanup_instructions
  
  log "🎉 NeMo Microservices Platform setup completed successfully!"
}

# Run main function
main "$@"