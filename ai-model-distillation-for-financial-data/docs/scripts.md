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

# Scripts Directory

Efficiently manage and maintain the developer example application using the following scripts. These utilities help automate cleanup, manage resources, and streamline your workflow.

## Prerequisites

- Docker and Docker Compose must be installed.
- The `uv` package manager must be installed.
- Scripts assume you are running in the project root directory unless otherwise specified.
- Note: Volume cleanup scripts automatically manage service lifecycle - manual shutdown is not required.

---

## Scripts

### `deploy-nmp.sh`

Deployment script for NVIDIA NeMo microservices (NMP) setup. This is a comprehensive deployment script with specialized configuration for enterprise environments.

- Contains advanced deployment logic and enterprise-specific configurations.
- Requires specific NMP credentials and environment setup.
- See internal deployment documentation for usage details.

### `deploy-short.sh`

All-in-one NeMo Microservices Platform setup script for minikube environments.

- Installs required tools (yq, huggingface-cli, minikube, helm, kubectl).
- Starts minikube with GPU support and ingress addon.
- Creates Kubernetes secrets for NGC and NVIDIA API keys.
- Installs Volcano scheduler and the NeMo Microservices Helm chart.
- Configures DNS resolution (`/etc/hosts`) for `nemo.test`, `nim.test`, `data-store.test`.
- Waits up to 30 minutes for all pods to reach ready state.
- Requires `NGC_API_KEY` and `NVIDIA_API_KEY` environment variables.

### `setup-storage.sh`

Configures Docker and Minikube to use a specified storage device with NVIDIA runtime support.

- Formats the device with ext4, mounts it, and adds an fstab entry.
- Moves Docker data root and Minikube home to the mounted volume.
- Configures the NVIDIA container runtime as Docker's default runtime.
- Usage: `./scripts/setup-storage.sh -d /dev/nvme0n1` (mount point auto-derived) or `./scripts/setup-storage.sh -d /dev/sda2 -m /mnt/data`.

### `demo-values.yaml`

Example Helm values file for NeMo Microservices when deploying with minikube for tutorials.

- Pre-configures data-store, customizer targets (Llama 3.2 1B/3B, Llama 3.1 8B), evaluator, and ingress.
- Used with `deploy-short.sh` or manual `helm install` commands.

### `generate_openapi.py`

Python script to generate the OpenAPI specification for the API.

- Imports the FastAPI app and writes the OpenAPI schema to `openapi.json` (or a user-specified path).
- Validates the output path for safety.
- Can be run as `python scripts/generate_openapi.py [output_path.json]`.

### `run.sh`

- Stops any running containers, then starts the main application stack using Docker Compose.
- Builds images as needed.
- Runs KDB-X in detached mode without attaching logs, to reduce log noise.

### `run-dev.sh`

- Stops any running containers, then starts the application stack with both the main and development Docker Compose files.
- Builds images as needed.
- Runs KDB-X in detached mode (no logs attached).
- Ensures Flower monitoring UI is available.

### `stop.sh`

- Stops all running containers for both the main and development Docker Compose files.

### Volume Cleanup Scripts

- `clear_kdbx_volume.sh`, `clear_redis_volume.sh`, `clear_mlflow_volume.sh`—Each script:
  - Stops the relevant service container (KDB-X, Redis, or MLflow).
  - Removes the associated Docker volume to clear all stored data.
  - Restarts the service container to ensure the service is running with a fresh, empty volume.
  - Prints status messages for each step.
- `clear_all_volumes.sh`—A convenience script to clear all persistent data volumes used by the application. It sequentially calls the volume cleanup scripts above (KDB-X, Redis, and MLflow) and restarts all services.

### `check_requirements.sh`

A script to ensure your `requirements.txt` is in sync with your `pyproject.toml`:

- Uses `uv` to generate a temporary list of installed packages.
- Compares this list to `requirements.txt`.
- If out of sync, prints a diff and instructions to update.
- Exits with an error if not up to date, otherwise confirms success.

### `quick-test.sh`

A minimal script to quickly verify that the API is running and responsive:

- Sends a POST request to `http://localhost:8001/jobs` with a test payload.
- Useful for smoke-testing the local API after startup.

---

## Helm Scripts (`scripts/helm/`)

Utility scripts for managing the Helm-deployed stack. All scripts accept an optional `NAMESPACE` environment variable (defaults to `nv-nvidia-blueprint-data-flywheel`).

### `forward-ports.sh`

Port-forwards Kubernetes services to local ports.

- Usage: `./scripts/helm/forward-ports.sh <service_name> <local_port> [...]`
- Example: `./scripts/helm/forward-ports.sh df-api-service 8000 df-mlflow-service 5000`
- Run with `--help` for full usage details.

### Helm Data Cleanup Scripts

- `clear-kdbx-data.sh`, `clear-redis-data.sh`, `clear-mlflow-data.sh` — each clears data for the named service within the Kubernetes deployment.
- `clear-all-data.sh` — convenience script that sequentially clears KDB-X, Redis, and MLflow data.

See [Helm Installation Guide — Data Clearing](11-helm-installation.md#data-clearing) for details.
