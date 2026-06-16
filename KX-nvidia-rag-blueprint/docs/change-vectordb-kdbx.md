<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 KX Systems, Inc. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->
# KDB-X RAG Blueprint Deployment Guide

This guide explains how to deploy the [NVIDIA RAG Blueprint](readme.md) with
**KDB-X** as the vector database backend, covering both CPU HNSW and GPU CAGRA
(cuVS) deployment paths.

KDB-X is the community-edition successor to kdb+ for AI workloads, offering
high-performance HNSW vector search with an optional NVIDIA cuVS / CAGRA GPU
backend.

> 💡 **Deploying on Amazon EKS with GPU CAGRA?** For a complete, validated
> step-by-step runbook — cluster creation → driver-580 gate → image build →
> Helm install → smoke test → teardown, plus connecting to an external /
> standalone-EC2 KDB-X — see **[EKS + KDB-X cuVS (GPU CAGRA) setup](eks-kdbx-cuvs-setup.md)**.
> The guide below covers the conceptual configuration, env vars, and the
> Docker-Compose path.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Required Credentials](#required-credentials)
- [Build the Images](#build-the-images)
- [Docker Compose Deployment](#docker-compose-deployment)
- [Helm / Kubernetes Deployment](#helmkubernetes-deployment)
- [GPU vector search (cuVS / CAGRA)](#gpu-vector-search-cuvs--cagra--test-deploy)
- [Amazon EKS Deployment](#amazon-eks-deployment)
- [Environment Variables Reference](#environment-variables-reference)
- [Verify Your Deployment](#verify-your-deployment)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

- Docker 24+ with BuildKit enabled (`DOCKER_BUILDKIT=1`)
- A KX Portal account with a **KDB-X CE entitlement** — sign up at
  <https://portal.kx.com> (90-day free trial available)
- An NVIDIA NGC API key for NIM containers
- Helm 3.12+ (Kubernetes deployments only)
- `kubectl` pointing at your cluster (Kubernetes deployments only)

---

## Required Credentials

| Credential | How to obtain |
|---|---|
| KDB-X bearer token | KX Portal → *Software Downloads* → copy the bearer token shown |
| KDB-X license file (`kc.lic`) | KX Portal → *License Management* → download |
| NGC API key | <https://ngc.nvidia.com/setup/api-key> |

---

## How the `.rag.*` server functions are provisioned

`kdbx-init.q` must be **loaded by q at process startup**. It defines all
`.rag.*` functions, runs `.rag.rehydrate[]` to restore in-memory state from the
PVC, and (when cuVS is enabled) runs the GPU readiness canary — all before the
first connection is accepted.

```bash
# Canonical q startup command:
q /opt/kx/conf/kdbx-init.q -p 5000
```

The helm chart (test-only deploy) does this automatically via
`kdbx-entrypoint.sh`. For customer-managed KDB-X, add this command to your
q process launch configuration. `kdbx-init.q` ships with the helm chart at
`deploy/helm/nvidia-blueprint-rag/files/kdbx/kdbx-init.q`.

The adapter performs a one-time readiness check on its first operation
(`.rag.ping[]`) and raises `KdbxNotBootstrappedError` with instructions if the
server does not have `.rag.*` loaded.

## Build the Images

Three images make up a kdbx deployment:

1. **`kdbx-rag`** — the KDB-X server image (q + the `kx.ai` module; `kx.cuvs`
   is downloaded at pod start when armed).  The q scripts (`kdbx-init.q`,
   `healthcheck.q`, `readiness.q`) are BAKED into the image at
   `/opt/kx/conf/` so the bare container bootstraps `.rag.*` on its own; in
   the chart they are additionally ConfigMap-mounted over the same paths, so
   editing them + `helm upgrade` + pod restart still needs no image rebuild.
2. **`rag-server-kdbx`** — the KX-fork rag-server with the KdbxVDB Python
   adapter under `src/nvidia_rag/utils/vdb/kdbx/`.
3. **`ingestor-server-kdbx`** — same fork, ingestor side.

The release pipeline publishes the server images under the historical
`*-kdbai` names — from **2.4.0** those images contain the kdbx adapter too,
so the kdbx path uses them directly.  `*-kdbai:2.3.4` and older PRE-DATE the
adapter and will not work for kdbx.  Until 2.4.0 lands on the portal (or to
test unreleased code) build + push the images yourself as below.

### Build & push (current testing flow)

```bash
export KDB_BEARER_TOKEN="<paste bearer token from KX Portal>"
export KDB_B64_LICENSE="$(base64 -i /path/to/kc.lic)"   # macOS: base64 -i; Linux: base64 -w0
export REGISTRY="<your-registry>"   # e.g. 123456789012.dkr.ecr.us-west-2.amazonaws.com

# 1. KDB-X server image (needs the KX-portal secrets for the install_kdb.sh download)
docker build --platform linux/amd64 \
  --secret id=bearer_token,env=KDB_BEARER_TOKEN \
  --secret id=license_b64,env=KDB_B64_LICENSE \
  -t ${REGISTRY}/kdbx-rag:1.0.0 \
  -f deploy/helm/nvidia-blueprint-rag/files/kdbx/Dockerfile.kdbx \
  deploy/helm/nvidia-blueprint-rag/files/kdbx/
docker push ${REGISTRY}/kdbx-rag:1.0.0

# 2. rag-server with the kdbx adapter
docker build --platform linux/amd64 \
  -t ${REGISTRY}/rag-server-kdbx:2.4.0 \
  -f src/nvidia_rag/rag_server/Dockerfile .
docker push ${REGISTRY}/rag-server-kdbx:2.4.0

# 3. ingestor-server with the kdbx adapter
docker build --platform linux/amd64 \
  -t ${REGISTRY}/ingestor-server-kdbx:2.4.0 \
  -f src/nvidia_rag/ingestor_server/Dockerfile .
docker push ${REGISTRY}/ingestor-server-kdbx:2.4.0
```

Once the 2.4.0 release lands at `portal.dl.kx.com`, only step 1 (the kdbx-rag
server image) is needed and the helm install can use the EKS overlay's default
`image.repository` values (`portal.dl.kx.com/{rag,ingestor}-server-kdbai:2.4.0`).

### Smoke-test the kdbx image locally

The image starts q with `kdbx-init.q` loaded (via the entrypoint). Once the
process is ready, `.rag.ping[]` returns `` `pong ``.

```bash
# Run with kdbx-init.q from the repo (mounts it at the expected path):
docker run --rm -p 5000:5000 \
  -v $(pwd)/deploy/helm/nvidia-blueprint-rag/files/kdbx/kdbx-init.q:/opt/kx/conf/kdbx-init.q \
  ${REGISTRY}/kdbx-rag:1.0.0

# In a q client — .rag.ping[] should return `pong:
q
# In the q REPL:
#   q) h:hopen 5000
#   q) h".rag.ping[]"                              / `pong
```

---

## Docker Compose Deployment

> **Note:** A ready-made integration-test compose file is available at
> `tests/integration/docker-compose-kdbx.yml`.  For production use, wire
> KDB-X into your existing `docker-compose-rag-server.yaml` by adding the
> service block below.

Add the following service to `deploy/compose/docker-compose-rag-server.yaml`:

```yaml
kdbx:
  image: "<your-registry>/kdbx-rag:1.0.0"
  ports:
    - "5000:5000"
  environment:
    KDBX_LISTEN_PORT: "5000"
  healthcheck:
    test: ["CMD", "q", "healthcheck.q", "-p", "5000"]
    interval: 10s
    timeout: 10s
    retries: 10
    start_period: 30s
```

Set environment variables for the RAG / ingestor services:

```bash
export APP_VECTORSTORE_URL="http://kdbx:5000"
export APP_VECTORSTORE_NAME="kdbx"
export APP_VECTORSTORE_SEARCHTYPE="dense"
export NGC_API_KEY="<your-ngc-api-key>"
```

---

## Helm / Kubernetes Deployment

### 1. Create Kubernetes secrets

```bash
NS="your-namespace"

# Registry secret (if your registry requires auth)
kubectl create secret docker-registry kdbx-registry-secret \
  --docker-server=<your-registry> \
  --docker-username=<user> \
  --docker-password=<token> \
  -n $NS

# KDB-X license secret
kubectl create secret generic kdbx-license-secret \
  --from-literal=KDB_LICENSE_B64="$(base64 -i /path/to/kc.lic)" \
  -n $NS

# NGC API secret
kubectl create secret generic ngc-api \
  --from-literal=NGC_API_KEY="${NGC_API_KEY}" \
  -n $NS
```

### 2. Update Helm dependencies

```bash
helm dependency update deploy/helm/nvidia-blueprint-rag
```

### 3. Deploy

```bash
# Required overrides (rag-server + ingestor + kdbx all need explicit
# `image.repository` until the `*-kdbx` images land on portal.dl.kx.com).
helm upgrade --install rag deploy/helm/nvidia-blueprint-rag \
  -n $NS \
  --set kdbai.enabled=false \
  --set kdbx.enabled=true \
  --set image.repository=<your-registry>/rag-server-kdbx \
  --set "ingestor-server.image.repository=<your-registry>/ingestor-server-kdbx" \
  --set kdbx.image.repository=<your-registry>/kdbx-rag \
  --set kdbx.licenseSecret.create=true \
  --set-string kdbx.licenseSecret.licenseB64="$(base64 -i /path/to/kc.lic)" \
  --set imagePullSecret.password="${NGC_API_KEY}" \
  --set ngcApiSecret.password="${NGC_API_KEY}"
```

Key values to override (see `deploy/helm/nvidia-blueprint-rag/values.yaml`,
section `kdbx:`):

| Value | Default | Description |
|---|---|---|
| `kdbx.enabled` | `false` | Must be `true` to deploy KDB-X |
| `kdbx.image.repository` | `""` | Your registry URI for the KDB-X image |
| `kdbx.image.tag` | `1.0.0` | Image tag |
| `kdbx.indexType` | `hnsw` | Vector index type (`hnsw` for CPU, `cagra` for GPU) |
| `kdbx.useCuvs` | `false` | Enable NVIDIA cuVS GPU index (CAGRA). See GPU section below |
| `kdbx.gpu.count` | `1` | GPUs to request (`nvidia.com/gpu`) when `useCuvs=true` |
| `kdbx.gpu.nodeSelector` | `{}` | Pin the GPU node/arch when `useCuvs=true` |
| `kdbx.gpu.tolerations` | `[]` | Tolerations for GPU node taints |
| `kdbx.hnsw.metric` | `L2` | Distance metric (`L2` or `CS`) |
| `kdbx.hnsw.m` | `32` | HNSW M parameter |
| `kdbx.hnsw.efConstruction` | `64` | HNSW efConstruction |
| `kdbx.hnsw.efSearch` | `64` | HNSW efSearch |
| `kdbx.cagra.graphDegree` | `32` | CAGRA graph degree |
| `kdbx.cagra.intermediateGraphDegree` | `32` | CAGRA intermediate graph degree |
| `kdbx.cagra.itopkSize` | `128` | CAGRA internal top-k (must be >= search k) |
| `kdbx.cagra.gpuid` | `0` | GPU device index for CAGRA |
| `kdbx.cagra.skipPersistedRead` | `false` | Kill-switch for `.cagra` blob read on pod restart |
| `kdbx.cagra.cuvsStamp` | `""` | Custom stamp string for `_cagrastamp` sidecar |
| `kdbx.cuvsStartupSeconds` | `600` | Liveness probe initial delay (seconds) for cuVS install at startup |
| `kdbx.licenseSecret.bearerToken` | `""` | KX portal bearer token for cuVS module download (test-only) |
| `kdbx.persistence.size` | `50Gi` | PVC size |
| `kdbx.resources.limits.memory` | `16Gi` | Memory limit |

---

## GPU vector search (cuVS / CAGRA) — test deploy

> **Production note.** KX ships KDB-X and the cuVS module as **separate**
> artifacts — cuVS is not baked into KDB-X. In production, KDB-X is
> **customer-managed**: installed properly on accessible infra with cuVS set up
> by the customer, and the blueprint simply connects to its endpoint. The kdbx
> pod in this repo is **test-only scaffolding**, so rather than maintain a GPU
> image, `files/kdbx/kdbx-entrypoint.sh` installs the cuVS module + CUDA libs at
> **pod startup** (only when `useCuvs=true`). This keeps the same image for CPU
> and GPU; the cost is a slow first start (it downloads ~GBs of CUDA every cold
> start — there is no caching, by design, for a rarely-restarted test pod).

**Node requirements** (the entrypoint installs CUDA, but the *driver* comes from
the node): NVIDIA host driver **≥ 580**, Ampere or newer GPU, x86-64, and the
[NVIDIA device plugin](https://github.com/NVIDIA/k8s-device-plugin) installed so
`nvidia.com/gpu` is schedulable. Validated on g5.2xlarge (A10G, driver
580.159.03, cuVS 25.10).

**Extra credential.** Runtime cuVS download needs a KX-portal OAuth token. Add
it to the license secret under `KDB_BEARER_TOKEN` (test deploys only — never
ship a runtime portal token in a production artifact):

```bash
kubectl create secret generic kdbx-license-secret \
  --from-literal=KDB_LICENSE_B64="$(base64 -i /path/to/kc.lic)" \
  --from-literal=KDB_BEARER_TOKEN="<kx-portal-oauth-token>" \
  -n $NS
```

**Deploy with GPU enabled.** Layer the committed cuVS overlay on top of the base
values — it sets BOTH halves required for CAGRA (see the warning below):

```bash
helm upgrade --install rag deploy/helm/nvidia-blueprint-rag -n $NS \
  -f deploy/EKS/rag-values-kdbx.yaml \
  -f deploy/EKS/rag-values-kdbx-cuvs.yaml \
  --set kdbx.image.repository=<your-ecr>/kdbx-rag \
  --set image.repository=<your-ecr>/nvidia-rag-server-kdbx --set image.tag=<tag> \
  --set "ingestor-server.image.repository=<your-ecr>/ingestor-server-kdbx" \
  --set "ingestor-server.image.tag=<tag>" \
  --set kdbx.imagePullSecret.name="" \
  --set-string kdbx.licenseSecret.bearerToken="<kx-portal-oauth-token>" \
  --set 'kdbx.gpu.nodeSelector.node\.kubernetes\.io/instance-type=g5.2xlarge' \
  --set-file imagePullSecret.password=<ngc-key-file> \
  --set-file ngcApiSecret.password=<ngc-key-file>
```

> ⚠️ **`useCuvs=true` alone does NOT give you CAGRA collections.** Enabling cuVS
> needs BOTH halves, which is exactly why the `rag-values-kdbx-cuvs.yaml` overlay
> exists:
> 1. **Server armed** — `kdbx.useCuvs=true` requests `nvidia.com/gpu`, applies
>    `kdbx.gpu.nodeSelector`/`tolerations`, and sets `KDBX_USE_CUVS=1` so the
>    entrypoint installs the cuVS module; `kdbx-init.q` (loaded at q startup)
>    then loads `kx.cuvs`.
> 2. **Client requesting it** — the rag-server/ingestor adapter chooses the index
>    type from `APP_VECTORSTORE_ENABLEGPUINDEX` / `APP_VECTORSTORE_ENABLEGPUSEARCH`
>    (the overlay sets both `True`, on rag-server AND ingestor). Without these the
>    adapter requests **HNSW** and new collections are built HNSW *even on a GPU
>    pod*.
>
> With both set, new collections are built CAGRA and degrade gracefully to HNSW
> if cuVS fails to load; existing HNSW collections are served as-is. Images must
> be built from current source — the `portal.dl.kx.com/...:2.3.x` tags in the
> base overlay header are pre-Phase-3 placeholders, not runnable as-is.

> **Arch coupling.** A persisted `.cagra` index blob is tied to the GPU arch it
> was built on. Because the pod uses `strategy: Recreate` on an RWO PVC, pin a
> single arch via `kdbx.gpu.nodeSelector` so a restarted pod reattaches to the
> same GPU family.

To watch the install + launch on first start:

```bash
kubectl logs -n $NS deploy/kdbx -f | grep kdbx-entrypoint
# [kdbx-entrypoint] downloading cuVS module (l64-cuvs.zip)
# [kdbx-entrypoint] running install_deps.sh (pulls CUDA 13.1 + cuVS 25.10 — slow)
# [kdbx-entrypoint] launching q on port 5000 ... (KDBX_USE_CUVS=1)
# then in kdbx-init.q output: [kdbx-init] cuvs.enabled = 1
```

### GPU safety guards (WS-SAFETY)

A persisted CAGRA index (`.cagra` blob) is opaque GPU state coupled to the GPU
arch + cuVS version, and a fatal read of an incompatible/half-written blob can
hard-fault q (uncatchable → a crashloop). WS-SAFETY hardens this in **two
layers**, which matters because production KDB-X is customer-managed (see the
note at the top): the **server-side logic** lives in `kdbx-init.q` and is active
wherever that script is loaded (local test pod *or* a remote KDB-X wired for
this blueprint, since the adapter already requires its `.rag.*` functions); the
**Kubernetes wiring** is applied only by this repo's chart (the test pod) — a
remote KDB-X supplies the equivalent through its own process supervision.

Server-side logic in `kdbx-init.q` (local **and** remote; gated on `cuvs.enabled`):

- **Build marker.** A build writes a `<cname>_cagrabuilding` sidecar and clears
  it after persist; if the process dies mid-build, the next start sees the
  marker and rebuilds from the (intact) vector table instead of reading a
  half-written blob.
- **Env stamp.** Each `.cagra` gets a `<cname>_cagrastamp` recording the GPU
  arch/driver (+ optional `KDBX_CUVS_STAMP`). On reload a mismatch → rebuild, so
  storage reattached to a different GPU arch never reads an incompatible blob.
- **Kill-switch.** `KDBX_CAGRA_SKIP_PERSISTED_READ=1` never reads a persisted
  blob and always rebuilds — the escape hatch if a blob ever fatally faults.
- **Canary function** `.rag.cuvs.canary[]` — a tiny CAGRA search that throws if
  the GPU context is wedged (wire it to whatever health-checks the host uses).

Kubernetes wiring applied by this chart when `useCuvs=true` (**test pod only**):

- **Build-startup grace.** `kdbx.cuvsStartupSeconds` (default `600`) sets the
  liveness `initialDelaySeconds` so the at-startup cuVS install and the first
  CAGRA build (both block q's single thread) don't trip a liveness kill.
- **Readiness canary.** Readiness runs `.rag.cuvs.canary` via `readiness.q`; a
  wedged GPU pulls the pod from service **without** a liveness kill (which would
  churn the RWO PVC). Liveness stays the cheap `.rag.ping`.
- Surfaces the kill-switch + stamp tag as `kdbx.cagra.skipPersistedRead` /
  `kdbx.cagra.cuvsStamp`.

---

## Amazon EKS Deployment

An EKS-specific values overlay is provided at `deploy/EKS/rag-values-kdbx.yaml`.
It pre-configures EBS gp3 storage, disables KDB.AI, and sets cloud-hosted LLM
endpoints.

### 1. Create the cluster

```bash
# ~20 min.  Spec: 9 × g5.2xlarge GPU nodes + 3 × t3.xlarge system nodes
# (t3.medium's 4 GiB is too small — rag-server and ingestor each request 8 GiB)
# (matches the resource budget for nv-ingest + the embed/rerank NIMs).
AWS_PROFILE=<your-profile> eksctl create cluster -f deploy/EKS/rag-dev-cluster.yaml
```

### 2. Push images to ECR (or your registry)

Build per "Build the Images" above with `REGISTRY=<your-account>.dkr.ecr.<region>.amazonaws.com`.
Tag both server images as `2.4.0` to match the overlay defaults (or pass `--set image.tag=...`).

### 3. helm install

```bash
NS=rag
kubectl create namespace $NS --dry-run=client -o yaml | kubectl apply -f -

# A single helm install — no kubectl set env / manual secret / manual SC.
# The chart creates the rag-storage SC, the license secret, and all
# pull-secret wiring on its own.
helm install rag deploy/helm/nvidia-blueprint-rag \
  -n $NS \
  -f deploy/EKS/rag-values-kdbx.yaml \
  --set image.repository=${REGISTRY}/rag-server-kdbx \
  --set "ingestor-server.image.repository=${REGISTRY}/ingestor-server-kdbx" \
  --set kdbx.image.repository=${REGISTRY}/kdbx-rag \
  --set kdbx.licenseSecret.create=true \
  --set-string kdbx.licenseSecret.licenseB64="$(base64 -i /path/to/kc.lic)" \
  --set imagePullSecret.password="${NGC_API_KEY}" \
  --set ngcApiSecret.password="${NGC_API_KEY}" \
  --timeout 30m
```

If you don't need to pull rag-server from `portal.dl.kx.com` (i.e., all three
images live in your own registry), also pass `--set kdbai.imagePullSecret.name=""`
so the deployments don't reference a non-existent pull secret.

### 3b. Optional: GPU CAGRA deploy

Layer the GPU CAGRA overlay on top of the base kdbx overlay. The
`rag-values-kdbx-cuvs.yaml` file already sets
`APP_VECTORSTORE_ENABLEGPUINDEX=True` and `APP_VECTORSTORE_ENABLEGPUSEARCH=True`
on both rag-server and ingestor:

```bash
# Layer the GPU CAGRA overlay on top of the base kdbx overlay:
helm upgrade --install nvidia-rag . \
  -f deploy/EKS/rag-values-kdbx.yaml \
  -f deploy/EKS/rag-values-kdbx-cuvs.yaml
```

> **Note:** Both `APP_VECTORSTORE_ENABLEGPUINDEX` and
> `APP_VECTORSTORE_ENABLEGPUSEARCH` must be `True` on rag-server AND ingestor.
> Without them the adapter sends HNSW requests even on a GPU pod with
> `KDBX_USE_CUVS=1`. The cuvs overlay handles this automatically.

### 3c. Optional: Blackwell g7e EKS (self-hosted LLM)

For Blackwell (g7e) EKS deployment of the LLM, see
`deploy/EKS/g7e-llm-nodegroup.yaml` and
`deploy/EKS/rag-values-llm-selfhost-g7e.yaml` — eksctl requires an explicit
AL2023-NVIDIA AMI pin and a CUDA 803 compat-libcuda fix is needed for the NIM
pod.

### 4. Port-forward + smoke test

```bash
# Wait for pods (~3 min once images are cached; ~10 min first-pull).
kubectl rollout status -n $NS deploy/rag-server --timeout=15m
kubectl rollout status -n $NS deploy/ingestor-server --timeout=15m

# Frontend on http://localhost:8090
kubectl port-forward -n $NS svc/rag-frontend 8090:3000 &
# API for scripted smoke
kubectl port-forward -n $NS svc/rag-server 8081:8081 &
kubectl port-forward -n $NS svc/ingestor-server 8082:8082 &
```

### 5. Tear down

```bash
AWS_PROFILE=<your-profile> eksctl delete cluster --name rag-dev --region us-west-2
```

---

## Known limitations (vs the KDB.AI backend)

- **Metadata filtering is rejected, not supported.** The rag-server emits
  filter expressions in Milvus-string / Elasticsearch-list form, which the
  kdbx adapter does not yet translate. Rather than silently returning
  UNFILTERED (i.e. wrong) results, any non-empty `filter_expr` raises
  `UnsupportedFeatureError`. This only bites when
  `ENABLE_FILTER_GENERATOR=True` (default `False`); the q-side filter path
  and the `kdbx_filters.translate_filter` building block already exist for
  when support lands.
- **Hybrid (dense+sparse) search is not supported** — use
  `APP_VECTORSTORE_SEARCHTYPE=dense`.

## Security

**q IPC is unauthenticated and code-execution-equivalent.** Any client that
can open a TCP connection to the KDB-X port can evaluate arbitrary q —
including `system"..."` shell commands. There is no `-u`/`.z.pw` auth in this
deployment (the probes and adapter rely on plain IPC). Treat network reach to
the kdb+ port as equivalent to shell access on that host. Plan accordingly:

- **In-cluster (chart-managed test pod):** the chart ships a `NetworkPolicy`
  (`kdbx.networkPolicy.enabled`, default **true**) restricting ingress on the
  kdbx port to the rag-server and ingestor-server pods only. Enforcement
  requires a CNI that implements NetworkPolicy — on EKS the stock AWS VPC CNI
  only enforces with its network-policy agent enabled (`enableNetworkPolicy:
  "true"`); Calico/Cilium enforce natively. With a non-enforcing CNI the
  object is accepted but inert.
- **External / BYO KDB-X (the production model):** keep the endpoint on
  private subnets with security groups that allow the KDB-X port only from
  the cluster's node/pod security group. q IPC is **unencrypted** by default —
  for production add TLS (q's built-in TLS or stunnel) or a private link, and
  consider `.z.pw`/`-u` authentication on the customer-managed process.
- The KDB-X **license file is baked into the image layers** by
  `install_kdb.sh` at build time — never push the kdbx image to a public
  registry.

## Environment Variables Reference

### Client-side (set on rag-server and ingestor pods)

| Variable | Default | Description |
|---|---|---|
| `APP_VECTORSTORE_URL` | `http://kdbx:5000` | KDB-X IPC endpoint |
| `APP_VECTORSTORE_NAME` | `kdbx` | Selects the KDB-X adapter |
| `APP_VECTORSTORE_SEARCHTYPE` | `dense` | Vector search mode |
| `APP_VECTORSTORE_ENABLEGPUINDEX` | `False` | Must be `True` on BOTH rag-server and ingestor for CAGRA. If `False`, adapter sends HNSW requests even when `KDBX_USE_CUVS=1`. |
| `APP_VECTORSTORE_ENABLEGPUSEARCH` | `False` | Must be `True` on BOTH rag-server and ingestor for CAGRA. If `False`, adapter sends HNSW requests even when `KDBX_USE_CUVS=1`. |

### Server-side (set on the kdbx pod / Docker Compose service)

| Variable | Default | Description |
|---|---|---|
| `KDBX_LISTEN_PORT` | `5000` | kdb+ process listen port. `KDBX_PORT` is intentionally not used because Kubernetes auto-injects `KDBX_PORT=tcp://<clusterIP>:5000` from a Service of the same name, which would collide with this variable. |
| `KDBX_USE_CUVS` | `0` | Enable GPU CAGRA via kx.cuvs (`1`=enabled) |
| `KDBX_INDEX_TYPE` | *(empty)* | Pod-default index for NEW collections when the client doesn't specify one: `cagra` (requires cuVS) or anything else → `hnsw`. The chart wires this from `kdbx.indexType`. |
| `KDBX_DATA_DIR` | `/opt/kx/data` | Persistence root for collection tables, sidecars and `.cagra` blobs (the chart mounts the PVC here) |
| `KDBX_METRIC` | `L2` | Pod-default distance metric for NEW collections: `L2` (Euclidean), `CS` (cosine) or `IP` (inner product). A per-collection metric requested at create time takes precedence; the chosen metric is stamped per-collection and survives restarts (WS-METRIC). |
| `KDBX_HNSW_M` | `32` | HNSW graph connectivity parameter |
| `KDBX_HNSW_EF_CONSTRUCTION` | `64` | HNSW build-time search width |
| `KDBX_HNSW_EF_SEARCH` | `64` | HNSW query-time search width |
| `KDBX_CAGRA_GRAPH_DEGREE` | `32` | CAGRA graph degree |
| `KDBX_CAGRA_INTERMEDIATE_GRAPH_DEGREE` | `32` | CAGRA intermediate graph degree |
| `KDBX_CAGRA_ITOPK_SIZE` | `128` | CAGRA internal top-k (must be >= search k) |
| `KDBX_CAGRA_BUILD_ALGO` | `nn_descent` | CAGRA build algorithm |
| `KDBX_CAGRA_NN_DESCENT_NITER` | `20` | NN-descent iterations for the CAGRA build |
| `KDBX_CAGRA_MAX_ITERATIONS` | `0` | CAGRA search max iterations (0 = cuVS default) |
| `KDBX_CAGRA_MIN_ITERATIONS` | `0` | CAGRA search min iterations (0 = cuVS default) |
| `KDBX_CAGRA_GPUID` | `0` | GPU device index for CAGRA |
| `KDBX_CAGRA_SKIP_PERSISTED_READ` | `0` | Kill-switch: `1` = skip `.cagra` blob read, rebuild from vectors (use after a CUDA fault) |
| `KDBX_CUVS_STAMP` | *(empty)* | Optional custom identifier written to `_cagrastamp` sidecar |

---

## Verify Your Deployment

### Ping KDB-X directly

```bash
# From inside the cluster / container:
q
# In the q REPL:
#   q) h:hopen 5000
#   q) h".rag.ping[]"
# Expected: `pong
```

### Via RAG server health endpoint

```bash
curl http://localhost:8081/health
# Expected JSON: {"status": "healthy"}
```

### Run integration tests

```bash
KDBX_HOST=localhost:5000 pytest tests/integration/test_kdbx_vdb.py -v
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `pykx.QError: 'conn` on startup | KDB-X not ready | Wait for healthcheck; increase `start_period` |
| `KdbxQError: 'length` on insert | Vector dimension mismatch | Set `dimension=` to match your embedding model |
| `KdbxQError: 'nyi` | GPU code path called without cuVS | Set `KDBX_USE_CUVS=1` on the kdbx pod and ensure `APP_VECTORSTORE_ENABLEGPUINDEX=True` + `APP_VECTORSTORE_ENABLEGPUSEARCH=True` on both rag-server and ingestor; CPU HNSW works without any of these |
| Pod stuck in `Init` | License secret missing | Create `kdbx-license-secret` (see above) |
| `wsfull` error | KDB-X OOM | Increase `kdbx.resources.limits.memory` |
| `LicenseException: A valid q license must be in a known location (e.g. \`$QLIC\`) to run q code via 'pykx.q'` on the rag-server or ingestor pod | You set `kdbx.pykxUnlicensed=false` but PyKX rejected the mounted `kc.lic` (KDB-X CE licenses aren't currently accepted by PyKX 3.1.x's bundled q) | Either accept the default (`kdbx.pykxUnlicensed=true`, IPC-only) or get a PyKX-compatible kc.lic and keep `false`. |
| `ImagePullBackOff` on rag-server / ingestor pulling `*-kdbx:*` | The `*-kdbx`-suffixed images haven't been published to portal.dl.kx.com yet | Build + push your own (see "Build the Images") and override with `--set image.repository=...` `--set ingestor-server.image.repository=...` on `helm install`. |

---

## GPU Acceleration (cuVS) — quick reference

GPU CAGRA support is fully shipped and validated end-to-end on EKS (A10G and
Blackwell g7e). See
**[GPU vector search (cuVS / CAGRA)](#gpu-vector-search-cuvs--cagra--test-deploy)**
above for the authoritative deploy steps — use the committed
`deploy/EKS/rag-values-kdbx-cuvs.yaml` overlay.

Key facts:

- The cuVS module is **NOT bundled in the image** — KX ships it separately; the
  kdbx entrypoint installs it at pod startup when `KDBX_USE_CUVS=1`.
- `kdbx.useCuvs=true` only **arms the server**. New collections are built CAGRA
  only when the **client** also requests the GPU index
  (`APP_VECTORSTORE_ENABLEGPUINDEX/SEARCH=True` on rag-server **and** ingestor) —
  the overlay sets both. With useCuvs on but the client env off, collections are
  HNSW even on a GPU pod.
- `kdbx-init.q` is loaded at q startup (not pushed by the adapter); it loads
  `kx.cuvs` when `KDBX_USE_CUVS=1` is set. Images must be built from current
  source — pre-Phase-3 images do not include the startup-load change.
