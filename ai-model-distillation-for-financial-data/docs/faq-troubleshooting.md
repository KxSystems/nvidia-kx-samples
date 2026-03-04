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

# FAQ & Troubleshooting

Quick solutions to common issues when working with the Data Flywheel Blueprint.

## Common Issues

### NeMo Microservices: ImagePullBackOff or Pod Errors

**Symptom:** `kubectl logs` shows errors or pods are in `ImagePullBackOff` state.

**Solution:** Check your NGC API key configuration:

```bash
# Verify the secret exists
kubectl get secret ngc-api-secret -n nemo-platform

# If incorrect or missing, delete and recreate it
kubectl delete secret ngc-api-secret -n nemo-platform
kubectl create secret generic ngc-api-secret \
  --from-literal=NGC_CLI_API_KEY=your_actual_ngc_api_key \
  -n nemo-platform

# Restart the affected pods
kubectl rollout restart deployment -n nemo-platform
```

> Get your NGC API key from https://ngc.nvidia.com/setup/api-key

### Reinstall NeMo Microservices from Scratch

**When to use:** Fresh start needed, persistent configuration issues, or upgrade.

```bash
# Delete the entire minikube cluster
minikube delete

# Start fresh (refer to installation docs for full setup)
minikube start --cpus=8 --memory=16384 --disk-size=100g
# ... continue with helm installation steps
```

### Data Flywheel Server Issues

**Symptom:** API not responding, containers unhealthy, or services not starting.

**Solution:** Clean restart using Docker Compose:

```bash
# Stop and remove all containers, networks, and volumes
docker compose down -v

# Optional: Clean up dangling resources
docker system prune -f

# Restart services
./scripts/run.sh
```

For selective cleanup:
```bash
# Clear specific volumes
./scripts/clear_kdbx_volume.sh   # KDB-X data
./scripts/clear_redis_volume.sh  # Redis data
./scripts/clear_mlflow_volume.sh # MLflow experiments
```

## Handy Commands

### Kubernetes (kubectl)

```bash
# Check pod status in NeMo platform
kubectl get pods -n nemo-platform

# View logs for a specific pod
kubectl logs <pod-name> -n nemo-platform

# Follow logs in real-time
kubectl logs -f <pod-name> -n nemo-platform

# Describe pod (includes events and errors)
kubectl describe pod <pod-name> -n nemo-platform

# Get all resources in namespace
kubectl get all -n nemo-platform

# Check persistent volume claims
kubectl get pvc -n nemo-platform

# Port forward to access service locally
kubectl port-forward svc/<service-name> 8080:80 -n nemo-platform

# Delete and recreate a deployment
kubectl rollout restart deployment <deployment-name> -n nemo-platform

# Check cluster nodes
kubectl get nodes
```

### Docker & Docker Compose

```bash
# View running containers
docker ps

# View all containers (including stopped)
docker ps -a

# Check container logs
docker logs <container-name>

# Follow container logs in real-time
docker logs -f <container-name>

# Execute command inside container
docker exec -it <container-name> bash

# Check container resource usage
docker stats

# View compose services status
docker compose ps

# Restart specific service
docker compose restart <service-name>

# View service logs
docker compose logs <service-name>

# Stop services without removing volumes
docker compose stop

# Start stopped services
docker compose start

# Rebuild and restart services
docker compose up -d --build

# Check disk usage
docker system df

# Clean up unused resources
docker system prune -a --volumes
```

## Health Check Commands

### Verify Data Flywheel Stack

```bash
# Check all services are running
docker compose ps

# Verify API is responding
curl http://localhost:8000/health

# Check KDB-X
python -c "import pykx as kx; conn=kx.SyncQConnection('localhost',8082); print(conn('1+1').py())"

# Check Redis
docker exec -it redis redis-cli ping
```

### Verify NeMo Microservices

```bash
# Check all pods are running
kubectl get pods -n nemo-platform --watch

# Verify services are ready
kubectl get svc -n nemo-platform

# Check customizer status
kubectl logs -l app=nemo-customizer -n nemo-platform --tail=50

# Check evaluator status
kubectl logs -l app=nemo-evaluator -n nemo-platform --tail=50
```

## Getting More Help

- **Documentation:** See [Complete Documentation Guide](./readme.md)
- **Issues:** [GitHub Issues](https://github.com/KxSystems/nvidia-kx-samples/issues)
- **Security:** Report vulnerabilities via [SECURITY.md](../SECURITY.md)

