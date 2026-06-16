<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 KX Systems, Inc. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->
# EKS + KDB-X cuVS (GPU CAGRA) RAG — Step-by-Step Setup

End-to-end runbook to stand up the NVIDIA RAG Blueprint on **Amazon EKS** with
**KDB-X** as the vector database and **GPU-accelerated CAGRA** search via NVIDIA
**cuVS**. Every step has the exact commands. Validated on `g5.2xlarge` (A10G).

This is the GPU/CAGRA path. For the CPU/HNSW path, skip the cuVS-specific steps
(noted inline) and omit the `rag-values-kdbx-cuvs.yaml` overlay.

> **🧪 This is a dev / evaluation sizing — not preprod/prod.** It provisions
> **9× g5.2xlarge (A10G)** and uses the **NGC-hosted LLM** (no in-cluster LLM GPU),
> which is the cheapest way to exercise the full KDB-X RAG pipeline end-to-end. For
> **preprod/production**, self-host the LLM and size the GPU fleet per the
> [Minimum System Requirements](../README.md#minimum-system-requirements) —
> Kubernetes: **8× H100-80GB**, **8× RTX PRO 6000 (Blackwell)**, **9× A100-80GB SXM**,
> or **9× B200**. The "[self-host the LLM on Blackwell (g7e)](#optional-self-host-the-llm-on-blackwell-g7e-instead-of-the-ngc-endpoint)"
> option in §7 (validated on RTX PRO 6000 Blackwell) is the starting point for a
> production topology.

> **⏱️ Before you begin — clear these gates first.**
> The per-step commands below are reliable, but a few things must be in place
> **before** `eksctl create cluster` or you'll stall partway. Sort these first:
>
> 1. **GPU instance quota.** This cluster needs **9× g5.2xlarge** (= 72 G-instance
>    vCPUs). New AWS accounts default to a **0** quota for *"Running On-Demand G and
>    VT instances"* — `eksctl` will fail to bring up `gpu-pool` until you request an
>    increase in **Service Quotas** (console → Service Quotas → EC2 → that quota).
>    Approval can take hours to a couple of days, so file it first. Also confirm g5
>    is offered in your Region/AZs.
> 2. **Cost.** 9× g5.2xlarge + 3× t3.xlarge is roughly **$250–300/day** on-demand
>    (verify current pricing for your Region). **Scale the GPU pool to 0 when idle**
>    (see §10) — that's the single biggest cost lever.
> 3. **NGC access to the gated NIMs.** Your NGC API key must belong to an org that
>    can pull the gated NeMo/Nemotron NIMs, and you must have accepted the model
>    licenses on <https://build.nvidia.com>. Otherwise the NIM subcharts fail with
>    `403` / `ImagePullBackOff` during §7.
> 4. **KX license + bearer token.** Building the KDB-X server image (§5a) needs a
>    KDB-X license (`kc.lic`) **and** a KX-Portal bearer token (the latter only for
>    cuVS). Get both from the KX Portal before you start (see §1).
> 5. **You will build & push 3 images** (§5). The release pipeline publishes the
>    two server images as `portal.dl.kx.com/{rag,ingestor}-server-kdbai:2.4.0+`
>    (kdbx adapter included) — use those to skip §5b — but the `kdbx-rag` server
>    image is always build-your-own. Budget ~30–45 min (longer on Apple Silicon).
>
> If all five are ready, the rest is copy-paste.

---

## 0. Architecture at a glance

```
                ┌──────────────── EKS cluster (rag-dev) ────────────────┐
  user ──HTTP──▶│ rag-server ──┐                                        │
                │ ingestor ────┼─IPC(:5000)─▶ kdbx pod (q + kx.cuvs)    │
                │ frontend     │              └─ CAGRA index on GPU      │
                │ nv-ingest, embed/rerank NIMs (GPU)                     │
                │ minio, redis                                          │
                └────────────────────────────────────────────────────────┘
   LLM is NGC-hosted (integrate.api.nvidia.com) — NOT run in-cluster.
```

Three images you build + push:
| Image | Built from | Notes |
|---|---|---|
| `kdbx-rag` | `deploy/helm/nvidia-blueprint-rag/files/kdbx/Dockerfile.kdbx` | KDB-X server (q + `kx.ai`/`kx.cuvs`). Needs KX-portal secrets at build. |
| `rag-server-kdbx` | `src/nvidia_rag/rag_server/Dockerfile` | RAG API + KDB-X adapter. |
| `ingestor-server-kdbx` | `src/nvidia_rag/ingestor_server/Dockerfile` | Ingestion + KDB-X adapter. |

### How the KDB-X server is provisioned — `kdbx-init.q`

`deploy/helm/nvidia-blueprint-rag/files/kdbx/kdbx-init.q` is the q script that
defines **all the `.rag.*` server functions** the rag-server/ingestor adapters
call (create collection, insert, search, rehydrate, the GPU readiness canary, …)
and, when `KDBX_USE_CUVS=1`, **loads `kx.cuvs`** for GPU CAGRA.

You don't run it or copy it manually — **the Helm chart mounts it automatically**:

- The chart templates `kdbx-init.q` (plus `kdbx-entrypoint.sh`, `readiness.q`,
  `healthcheck.q`) into a **ConfigMap** (`kdbx-init`) mounted at
  `/opt/kx/conf/` in the kdbx pod.
- `kdbx-entrypoint.sh` installs cuVS (when armed) and then launches q **with
  `kdbx-init.q` loaded at startup** — so `.rag.*` (and `kx.cuvs`) are ready
  *before* the first connection is accepted. The adapter no longer pushes it.
- Because it's a ConfigMap, **editing `kdbx-init.q` then `helm upgrade` +
  restarting the kdbx pod** is all it takes to change server-side behavior — no
  image rebuild. (The image rebuild in step 5 is only for the *Python adapter*
  in the wheel.)

Startup log lines to expect: `[kdbx-init] kx.cuvs loaded` → `cuvs.enabled = 1` →
`ready on port 5000` (see step 8).

### ⚠️ Test vs. production: the in-cluster kdbx pod is TEST-ONLY

The `kdbx` pod this chart deploys (and its self-installing cuVS entrypoint) is
**scaffolding for testing**. In **production, KDB-X is customer-managed** —
installed and operated separately (its own license, its own GPU host, often a
**multi-process** deployment), and the blueprint simply **connects to it**. The
rag-server/ingestor adapter dials any KDB-X endpoint over IPC; it does not care
whether the chart created it.

**To connect to an existing/external KDB-X instead of deploying the pod:**

1. **Prepare the external KDB-X** (done by whoever runs KDB-X, not this chart):
   - Reachable over IPC at a `host:port`.
   - **Load `kdbx-init.q` at q startup** in every process that serves the
     adapter — it defines the `.rag.*` functions the adapter calls, and the
     adapter **does not push them** (it fails fast with "KDB-X server … does not
     have `.rag.*` loaded" if they're missing). Ship them
     `deploy/helm/nvidia-blueprint-rag/files/kdbx/kdbx-init.q` and have them run
     `q kdbx-init.q -p <port>` (plus `KDBX_USE_CUVS=1` + the cuVS module on a GPU
     host with driver ≥580 if they want GPU CAGRA).
   - Provide its own KDB-X license; cuVS install is on their host (the chart's
     bearer-token / license flags do **not** apply).

2. **Point the blueprint at it** (replaces the `kdbx.*` image/secret flags in §7):
   ```bash
   helm upgrade --install rag deploy/helm/nvidia-blueprint-rag -n $NS \
     -f deploy/EKS/rag-values-kdbx.yaml \
     -f deploy/EKS/rag-values-kdbx-cuvs.yaml \      # keep ONLY for GPU CAGRA — sets the client GPU-index flags
     --set kdbx.enabled=false \                     # don't deploy the in-cluster pod
     --set envVars.APP_VECTORSTORE_URL=http://<kdbx-host>:<port> \
     --set "ingestor-server.envVars.APP_VECTORSTORE_URL=http://<kdbx-host>:<port>" \
     --set image.repository=$REGISTRY/rag-server-kdbx --set image.tag=$TAG \
     --set "ingestor-server.image.repository=$REGISTRY/ingestor-server-kdbx" \
     --set "ingestor-server.image.tag=$TAG" \
     --set kdbai.imagePullSecret.name="" \
     --set-file imagePullSecret.password=/tmp/rag-secrets/ngc.key \
     --set-file ngcApiSecret.password=/tmp/rag-secrets/ngc.key
   ```
   The `http://` is only parsed for host+port (the adapter connects via IPC, not
   HTTP). Drop the `kdbx.image.*`, `kdbx.licenseSecret.*`, and bearer-token flags
   — they're for the in-cluster pod only. GPU CAGRA still needs the client flags
   from `rag-values-kdbx-cuvs.yaml` **and** `kx.cuvs` loaded on the external host.

3. **Multi-process / sharded KDB-X:** the adapter connects to a **single**
   endpoint, so front a multi-process deployment with a gateway (or the process
   that owns the `.rag.*` collections) and point `APP_VECTORSTORE_URL` there.
   Every process that the adapter (or that gateway) routes `.rag.*` calls to must
   have `kdbx-init.q` loaded.

#### KDB-X on a standalone EC2 (not in the cluster)

The adapter reaches KDB-X over plain **q IPC (TCP)**, so it's pure VPC networking:

- **Same VPC** — easiest: run the EC2 in the **same VPC as the EKS cluster**
  (the eksctl-default VPC CIDR is `192.168.0.0/16`). Different VPC → VPC-peer,
  Transit Gateway, or VPN so the pod subnets can route to the EC2.
- **Security group** — on the EC2, allow inbound **TCP on the KDB-X port** (e.g.
  `5000`) from the EKS **node/pod security group** (preferred) or the cluster VPC
  CIDR. (Find the node SG: `aws eks describe-cluster --name $CLUSTER --query
  cluster.resourcesVpcConfig.securityGroupIds`, or the nodegroup's SG.)
- **Endpoint** — use the EC2's **private** IP or private DNS, never public:
  `--set envVars.APP_VECTORSTORE_URL=http://10.0.x.x:5000` (and the same for
  `ingestor-server.envVars.APP_VECTORSTORE_URL`).
- **Security** — q IPC is **unencrypted** by default. Keep it on private subnets
  and tight SGs; for production add TLS (q's TLS / stunnel) or a private link.
- **The EC2 itself** provides: q + KDB-X license + `kdbx-init.q` loaded at
  startup; for GPU CAGRA, a GPU instance (g5/g7e) with **driver ≥580** + the
  `kx.cuvs` module. Quick reachability check from inside the cluster:
  `kubectl run -it --rm netcheck --image=busybox -- nc -zv <ec2-private-ip> 5000`.

> With `kdbx.enabled=false`, skip §4's local driver probe and the §8 `deploy/kdbx`
> log watch — those are for the in-cluster pod. Verify connectivity instead with
> the reachability check above + the §9 smoke test against your external endpoint.

---

## 1. Prerequisites

**Tools** (local machine):
- `awscli` v2, `eksctl` ≥ 0.221, `kubectl`, `helm` ≥ 3.12
- Docker 24+ with BuildKit (`DOCKER_BUILDKIT=1`), able to build `linux/amd64`

**Accounts / credentials:**
| Credential | How to get it |
|---|---|
| AWS profile with EKS/EC2/ECR/IAM rights | `aws configure --profile <profile>` |
| NGC API key | <https://ngc.nvidia.com/setup/api-key> (`nvapi-...`) |
| KDB-X license (`kc.lic`) | KX Portal → License Management |
| KDB-X bearer token | KX Portal → Software Downloads (OAuth token) — **only needed for cuVS** (the entrypoint downloads the cuVS module at pod start) |

**Set shared env vars** (used throughout):
```bash
export AWS_PROFILE=<your-profile>            # e.g. terraform-sa
export REGION=us-west-2
export CLUSTER=rag-dev
export REGISTRY=<acct>.dkr.ecr.${REGION}.amazonaws.com   # e.g. 123456789012.dkr.ecr.us-west-2.amazonaws.com
export TAG=2.4.0                             # image tag you will build/deploy (any tag works; 2.4.0 matches the overlay defaults & Chart appVersion)
export NS=rag
export NGC_API_KEY=nvapi-...                 # used by the ECR/NGC login + helm secrets
```

> 💡 **Apple Silicon:** the image builds in §5 target `linux/amd64`. On an ARM Mac
> they run under emulation and are slow (~10–15 min each). On an x86_64 Linux
> host they're much faster.

> ⚠️ **Stale AWS env-credential pitfall.** If your shell has `AWS_ACCESS_KEY_ID`/
> `AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN` exported (e.g. expired SSO/STS
> session creds), they **override** `AWS_PROFILE` and silently break `kubectl`
> (the kubeconfig exec uses `AWS_PROFILE`) with `You must be logged in to the
> server`. Either `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN`,
> or prefix commands with `env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u
> AWS_SESSION_TOKEN`.

---

## 2. Create the EKS cluster

The cluster config is committed at `deploy/EKS/rag-dev-cluster.yaml`: 9× `g5.2xlarge`
GPU nodes (`gpu-pool`, labeled `node-type=gpu`) + 3× `t3.xlarge` system nodes,
OIDC, and the EBS CSI addon.

```bash
eksctl create cluster -f deploy/EKS/rag-dev-cluster.yaml      # ~20 min
```

> ⚠️ **Region/name are hard-coded in the YAML.** `rag-dev-cluster.yaml` pins
> `metadata.region: us-west-2` and `metadata.name: rag-dev`. These do **not** read
> the `$REGION`/`$CLUSTER` env vars — if you set those to anything else, edit the
> YAML to match (and confirm g5.2xlarge is available in your Region's AZs).

> 🔑 **GPU AMI / driver gate (critical for cuVS).** `gpu-pool` uses
> `amiFamily: AmazonLinux2023`. eksctl auto-selects the **AL2023-NVIDIA** AMI for
> g5 (amiType `AL2023_x86_64_NVIDIA`), which ships **driver 580.159.03 / CUDA 13**.
> cuVS 25.10 installs **CUDA 13.1**, which has a hard **R580 driver floor** — a
> CUDA-version requirement that applies to **A10G too**, not just Blackwell. The
> old `AmazonLinux2` GPU AMI ships driver **570** and cuVS will fail to initialize.

Point `kubectl` at the cluster (also fixes a stale kubeconfig if the cluster was
recreated and its API endpoint changed):
```bash
aws eks update-kubeconfig --name $CLUSTER --region $REGION --profile $AWS_PROFILE
kubectl get nodes -L node.kubernetes.io/instance-type,node-type
```

If `kubectl` returns `the server has asked for the client to provide credentials`,
confirm your IAM principal has an **access entry**:
```bash
aws eks list-access-entries --cluster-name $CLUSTER --region $REGION
# If missing, add cluster-admin for your principal:
aws eks create-access-entry --cluster-name $CLUSTER --region $REGION \
  --principal-arn $(aws sts get-caller-identity --query Arn --output text)
aws eks associate-access-policy --cluster-name $CLUSTER --region $REGION \
  --principal-arn $(aws sts get-caller-identity --query Arn --output text) \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy \
  --access-scope type=cluster
```

---

## 3. Verify the NVIDIA device plugin

eksctl **auto-installs** the NVIDIA device plugin when it creates a GPU nodegroup
on the EKS accelerated AMI — you'll see `the Nvidia Kubernetes device plugin was
automatically installed` in the §2 output. So there's nothing to install; just
verify every GPU node advertises a GPU:
```bash
kubectl get nodes -o custom-columns='NODE:.metadata.name,GPU:.status.allocatable.nvidia\.com/gpu'
# each gpu-pool node -> 1 ; cpu-system nodes -> <none>
```
The plugin's pods on the non-GPU `cpu-system` nodes show `CrashLoopBackOff` — the
DaemonSet has no GPU nodeSelector. Harmless; GPU nodes are unaffected.

> Only if GPUs are **not** advertised (e.g. you used a non-accelerated AMI),
> install it manually:
> ```bash
> kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.17.1/deployments/static/nvidia-device-plugin.yml
> ```

---

## 4. Verify the GPU driver is ≥ 580 (cuVS gate)

Do this **before** deploying cuVS — a 570 driver wastes a ~10-min cuVS install
that then fails.
```bash
cat > /tmp/nvsmi-probe.yaml <<'EOF'
apiVersion: v1
kind: Pod
metadata: { name: nvsmi-probe }
spec:
  restartPolicy: Never
  nodeSelector: { node-type: gpu }
  containers:
  - name: nvsmi
    image: nvcr.io/nvidia/cuda:12.6.2-base-ubuntu24.04
    command: ["nvidia-smi","--query-gpu=name,driver_version","--format=csv"]
    resources: { limits: { nvidia.com/gpu: 1 } }
EOF
kubectl apply -f /tmp/nvsmi-probe.yaml
kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/nvsmi-probe --timeout=180s
kubectl logs nvsmi-probe          # expect: NVIDIA A10G, 580.159.03
kubectl delete pod nvsmi-probe
```
If the driver is `< 580`, recreate the GPU nodegroup on the AL2023-NVIDIA AMI:
```bash
eksctl delete nodegroup --cluster $CLUSTER --name gpu-pool --region $REGION --wait
eksctl create nodegroup -f deploy/EKS/rag-dev-cluster.yaml --include=gpu-pool
```

---

## 5. Build & push the three images

Log in to ECR (and NGC for the build base image):
```bash
aws ecr get-login-password --region $REGION --profile $AWS_PROFILE \
  | docker login --username AWS --password-stdin $REGISTRY
echo "$NGC_API_KEY" | docker login nvcr.io --username '$oauthtoken' --password-stdin
```

Create the ECR repos once (skip any that exist):
```bash
for r in kdbx-rag rag-server-kdbx ingestor-server-kdbx; do
  aws ecr create-repository --repository-name $r --region $REGION --profile $AWS_PROFILE 2>/dev/null || true
done
```

**5a. KDB-X server image** (needs KX-portal secrets to download q at build):
```bash
export KDB_BEARER_TOKEN="<kx-portal-bearer-token>"
export KDB_B64_LICENSE="$(base64 -i /path/to/kc.lic)"   # Linux: base64 -w0
docker build --platform linux/amd64 \
  --secret id=bearer_token,env=KDB_BEARER_TOKEN \
  --secret id=license_b64,env=KDB_B64_LICENSE \
  -t $REGISTRY/kdbx-rag:1.0.0 \
  -f deploy/helm/nvidia-blueprint-rag/files/kdbx/Dockerfile.kdbx \
  deploy/helm/nvidia-blueprint-rag/files/kdbx/
docker push $REGISTRY/kdbx-rag:1.0.0
```

**5b. rag-server + ingestor** (clean multi-stage builds — they compile the
`nvidia_rag` wheel from `./src`, so each image is self-contained):
```bash
docker build --platform linux/amd64 -t $REGISTRY/rag-server-kdbx:$TAG \
  -f src/nvidia_rag/rag_server/Dockerfile .
docker push $REGISTRY/rag-server-kdbx:$TAG

docker build --platform linux/amd64 -t $REGISTRY/ingestor-server-kdbx:$TAG \
  -f src/nvidia_rag/ingestor_server/Dockerfile .
docker push $REGISTRY/ingestor-server-kdbx:$TAG
```
> Always build these from current source — the adapter's server-readiness check
> and the startup-load provisioning live in the wheel.

---

## 6. Namespace, secrets, and Helm dependencies

```bash
kubectl create namespace $NS --dry-run=client -o yaml | kubectl apply -f -

# Pull the chart's subcharts (NIMs, nv-ingest, etc.) from NGC:
helm dependency update deploy/helm/nvidia-blueprint-rag
```

Secrets are created by the chart from `--set`/`--set-file` flags in the install
below (no manual `kubectl create secret` needed):
- `imagePullSecret` / `ngcApiSecret` ← your NGC API key
- `kdbx-license-secret` ← base64 `kc.lic` (+ bearer token for cuVS)

Stash them in files (avoids leaking secrets in shell history / argv):
```bash
umask 077; mkdir -p /tmp/rag-secrets
printf '%s' "$NGC_API_KEY"        > /tmp/rag-secrets/ngc.key
base64 -i /path/to/kc.lic         > /tmp/rag-secrets/license.b64   # Linux: base64 -w0
printf '%s' "$KDB_BEARER_TOKEN"   > /tmp/rag-secrets/bearer.token  # cuVS only
```

---

## 7. Deploy with Helm (GPU CAGRA)

The base overlay `rag-values-kdbx.yaml` configures KDB-X + EBS gp3 storage + the
NGC-hosted LLM. The `rag-values-kdbx-cuvs.yaml` overlay arms cuVS on the server
**and** sets the client GPU-index flags (both halves are required for CAGRA).

```bash
helm upgrade --install rag deploy/helm/nvidia-blueprint-rag -n $NS \
  -f deploy/EKS/rag-values-kdbx.yaml \
  -f deploy/EKS/rag-values-kdbx-cuvs.yaml \
  --set image.repository=$REGISTRY/rag-server-kdbx \
  --set image.tag=$TAG \
  --set "ingestor-server.image.repository=$REGISTRY/ingestor-server-kdbx" \
  --set "ingestor-server.image.tag=$TAG" \
  --set kdbx.image.repository=$REGISTRY/kdbx-rag \
  --set kdbx.image.tag=1.0.0 \
  --set kdbx.imagePullSecret.name="" \
  --set kdbai.imagePullSecret.name="" \
  --set kdbx.licenseSecret.create=true \
  --set-file kdbx.licenseSecret.licenseB64=/tmp/rag-secrets/license.b64 \
  --set-file kdbx.licenseSecret.bearerToken=/tmp/rag-secrets/bearer.token \
  --set-file imagePullSecret.password=/tmp/rag-secrets/ngc.key \
  --set-file ngcApiSecret.password=/tmp/rag-secrets/ngc.key \
  --timeout 30m
```

What the cuVS overlay sets (don't omit either half):
- **Server armed:** `kdbx.useCuvs=true` → `KDBX_USE_CUVS=1` (entrypoint installs the
  cuVS module at pod start) + `kdbx.gpu.nodeSelector: node-type=gpu` + 1 GPU.
- **Client requests GPU index:** `APP_VECTORSTORE_ENABLEGPUINDEX/ENABLEGPUSEARCH=True`
  on **both** rag-server and ingestor. Without these, collections build HNSW even
  on a GPU pod.

> 🔑 **nodeSelector must match your nodes.** The overlay pins
> `kdbx.gpu.nodeSelector: node-type=gpu`, matching the `node-type=gpu` label on
> `gpu-pool`. If your GPU nodes use a different label, override it (e.g.
> `--set 'kdbx.gpu.nodeSelector.node\.kubernetes\.io/instance-type=g5.2xlarge'`).

For **CPU/HNSW only**: drop the `-f rag-values-kdbx-cuvs.yaml` line and the two
`--set-file kdbx.licenseSecret.bearerToken` / `kdbx.*` GPU flags.

> 💾 **Optional but recommended — persist NIM model weights.** By default the
> embed / rerank / extraction NIMs run with `persistence.enabled=false`, so they
> **re-download their weights from NGC on every pod restart** (slow, and a hard
> failure in an air-gapped/egress-restricted cluster). Layer the NIM-cache overlay
> to back each NIM with an EBS PVC on `rag-storage`:
>
> ```bash
> helm upgrade --install rag deploy/helm/nvidia-blueprint-rag -n $NS \
>   -f deploy/EKS/rag-values-kdbx.yaml \
>   -f deploy/EKS/rag-values-kdbx-cuvs.yaml \
>   -f deploy/EKS/rag-values-nim-cache.yaml \   # <-- persist NIM weight caches
>   ... (same --set flags as above)
> ```

### Optional: self-host the LLM on Blackwell (g7e) instead of the NGC endpoint

By default this runbook uses the **NGC-hosted LLM** (`integrate.api.nvidia.com`) —
the right choice for dev and the A10G pool (no LLM GPU needed). To instead run the
LLM **in-cluster** on an **NVIDIA RTX PRO 6000 Blackwell (g7e)** node (49B, FP8, 1 GPU):

1. **Add a g7e nodegroup** (separate from the A10G `gpu-pool`, tainted so only the
   LLM lands on it). eksctl 0.221 misdetects g7e and would pick a *driverless* AMI,
   so `deploy/EKS/g7e-llm-nodegroup.yaml` pins the AL2023-NVIDIA AMI explicitly —
   fill its 4 placeholders, then create it:
   ```bash
   aws ssm get-parameter --region $REGION \
     --name /aws/service/eks/optimized-ami/1.30/amazon-linux-2023/x86_64/nvidia/recommended/image_id \
     --query Parameter.Value --output text                       # AMI id
   aws eks describe-cluster --name $CLUSTER --region $REGION \
     --query '{e:cluster.endpoint,ca:cluster.certificateAuthority.data,cidr:cluster.kubernetesNetworkConfig.serviceIpv4Cidr}'
   # edit the placeholders in deploy/EKS/g7e-llm-nodegroup.yaml, then:
   eksctl create nodegroup -f deploy/EKS/g7e-llm-nodegroup.yaml
   ```
2. **Layer the self-host overlay** onto the §7 helm install (LAST, so it wins):
   ```bash
   helm upgrade --install rag ... \
     -f deploy/EKS/rag-values-kdbx.yaml \
     -f deploy/EKS/rag-values-kdbx-cuvs.yaml \
     -f deploy/EKS/rag-values-llm-selfhost-g7e.yaml \   # flips LLM cloud -> in-cluster
     ...<same image/secret --set flags as §7>...
   ```
   The overlay pins the LLM to the g7e pool, repoints every LLM consumer to
   `nim-llm:8000`, persists the model cache, and bakes in two Blackwell-specific
   fixes: **(a)** it leaves `NIM_MODEL_PROFILE` **unset** (an empty string breaks
   NIM 1.15.x profile auto-select), and **(b)** it shadows the NIM's bundled CUDA-13
   forward-compat libcuda (`/usr/local/cuda-13.0/compat/lib.real`) with an emptyDir
   to dodge **CUDA error 803** — the host driver (580.159.03) is newer than the
   compat lib, so without this the 49B won't initialize CUDA on Blackwell.
3. **First start is slow** — NIM downloads the 49B weights and builds the TensorRT
   engine into the persisted cache: `kubectl logs -n $NS deploy/nim-llm -f` →
   `CUDA driver initialized successfully` → serving on `:8000`.

> Validated 2026-06-02 (FP8 TP1 on g7e RTX PRO 6000 Blackwell, 96 GB). g7e nodegroup
> details (AMI pin, taint, NodeConfig) are in `deploy/EKS/g7e-llm-nodegroup.yaml`.
> To revert to cloud-hosted, just drop the `-f rag-values-llm-selfhost-g7e.yaml` line.

---

## 8. Watch the rollout

```bash
# The kdbx pod installs cuVS (CUDA 13.1, ~GBs) at startup before q launches:
kubectl logs -n $NS deploy/kdbx -f | grep -E 'kdbx-entrypoint|kdbx-init'
# Expect:
#   [kdbx-entrypoint] running install_deps.sh (pulls CUDA 13.1 + cuVS 25.10 — slow)
#   [kdbx-init] kx.cuvs loaded
#   [kdbx-init] cuvs.enabled = 1
#   [kdbx-init] ready on port 5000

kubectl rollout status -n $NS deploy/rag-server     --timeout=15m
kubectl rollout status -n $NS deploy/ingestor-server --timeout=15m
kubectl get pods -n $NS
```

> ℹ️ A log line `cuVS canary build INCONCLUSIVE (... GPU likely fine; real builds
> unaffected)` is **expected and harmless** on A10G — the startup self-test builds
> a tiny synthetic index that can flakily fail on Ampere; real collection builds
> are unaffected and the pod stays Ready.

---

## 9. Smoke test (ingest → search)

```bash
kubectl port-forward -n $NS svc/rag-server      8081:8081 &
kubectl port-forward -n $NS svc/ingestor-server 8082:8082 &
kubectl port-forward -n $NS svc/rag-frontend    8090:3000 &   # UI at http://localhost:8090

# 1) Create a CAGRA collection (2048-dim matches llama-nemotron-embed-1b-v2):
curl -s -X POST http://localhost:8082/collection -H 'Content-Type: application/json' \
  -d '{"collection_name":"smoke","embedding_dimension":2048}'

# 2) Ingest a document (blocking):
curl -s -X POST http://localhost:8082/documents \
  -F 'documents=@/path/to/yourdoc.pdf' \
  -F 'data={"collection_name":"smoke","blocking":true,"split_options":{"chunk_size":512,"chunk_overlap":100}}'

# 3) Search:
curl -s -X POST http://localhost:8081/search -H 'Content-Type: application/json' \
  -d '{"query":"your question","collection_names":["smoke"],"top_k":5}'

# 4) (optional) confirm the collection is CAGRA, not HNSW:
kubectl exec -n $NS deploy/kdbx -- bash -lc \
  'echo "h:hopen\`:localhost:5000; -1 string h\".rag.idxType\`smoke\"; exit 0" | $QHOME/bin/q -q'
# -> "cagra"
```
A collection with **< 33 rows** uses an exact-scan fallback (no GPU build) until it
crosses the minimum CAGRA build size; that's expected. To actually exercise the
**GPU CAGRA build**, ingest enough to exceed ~33 chunks (a few pages, or a smaller
`chunk_size`), then confirm the index was built and persisted to the PVC:
```bash
kubectl exec -n $NS deploy/kdbx -- sh -c 'ls /opt/kx/data | grep smoke'
# expect: smoke.cagra  smoke.kdb  smoke_cagrastamp  smoke_meta  smoke_schema ...
```
The kdbx log shows a benign `Intermediate graph degree ... reducing it to N` for
small collections — the build still succeeds (the `.cagra` file appears).

---

## 10. Cost control & teardown

**Scale GPU nodes to 0** (stops the g5 cost; keeps the cluster + PVCs):
```bash
aws eks update-nodegroup-config --cluster-name $CLUSTER --nodegroup-name gpu-pool \
  --scaling-config minSize=0,maxSize=12,desiredSize=0 --region $REGION
# Scale back up later: ...desiredSize=9
```

**Clean reinstall** (fresh app, keep the cluster):
```bash
helm uninstall rag -n $NS
kubectl delete pvc --all -n $NS        # optional: wipe KDB-X + MinIO data
helm upgrade --install rag ...         # (re-run step 7)
```

**Full teardown:**
```bash
eksctl delete cluster --name $CLUSTER --region $REGION --wait

# eksctl does NOT reclaim dynamically-provisioned PVC volumes — delete the
# orphaned EBS volumes (status=available) so they don't keep costing:
for v in $(aws ec2 describe-volumes --region $REGION \
    --filters Name=status,Values=available \
              Name=tag:kubernetes.io/created-for/pvc/namespace,Values=$NS \
    --query 'Volumes[].VolumeId' --output text); do
  aws ec2 delete-volume --region $REGION --volume-id "$v"
done
```
> Tip: before a **full** teardown, `helm uninstall rag -n $NS && kubectl delete
> pvc --all -n $NS` first — that lets the EBS CSI driver delete the volumes
> gracefully (reclaimPolicy Delete), avoiding the orphan sweep above.

---

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `kubectl`: *the server has asked for the client to provide credentials* | Stale exported `AWS_*` env creds shadow `AWS_PROFILE`; or no access entry | `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN`; add an access entry (step 2) |
| `kubectl`: `dial tcp: ... no such host` | Stale kubeconfig (cluster recreated → new API endpoint) | `aws eks update-kubeconfig --name $CLUSTER --region $REGION` |
| Device plugin advertises 0 GPUs | Plugin not installed / node has no driver | Step 3; verify driver with step 4 |
| kdbx logs: `kx.cuvs load FAILED` / CUDA init error | GPU driver `< 580` (AL2 GPU AMI ships 570) | Recreate `gpu-pool` on AL2023-NVIDIA AMI (step 4) |
| Collections build **HNSW** on a GPU pod | Missing client GPU flags | Ensure `APP_VECTORSTORE_ENABLEGPUINDEX/SEARCH=True` on rag-server **and** ingestor (the cuVS overlay sets both) |
| kdbx pod `Pending` | nodeSelector doesn't match GPU node labels | Match `kdbx.gpu.nodeSelector` to your nodes (default `node-type=gpu`) |
| Adapter: *KDB-X server ... does not have `.rag.*` loaded* | rag-server/ingestor image is **not** built from current source | Rebuild from `src/.../Dockerfile` (step 5b) |
| `cuVS canary build INCONCLUSIVE ... : rank` | Flaky synthetic startup self-test on Ampere | **Expected/harmless** — real builds unaffected, pod stays Ready |
| `ImagePullBackOff` on `kdbx-rag` / `*-kdbx` | Node IAM lacks ECR pull, or wrong repo | Managed nodegroups get `AmazonEC2ContainerRegistryReadOnly`; verify `--set *.image.repository` paths |
| `ImagePullBackOff` after adding a registry secret to the ServiceAccount | k8s only applies SA `imagePullSecrets` when the pod spec defines NONE — this chart sets `ngc-secret` explicitly, so SA-level secrets are silently ignored | Add the secret at the Deployment/pod-spec level (`kubectl patch deploy ... imagePullSecrets/-`) or via chart values, not the SA |
| kdbx `Pending` with `volume node affinity conflict` after scale-down/up | kdbx's EBS PVC is pinned to ONE AZ; GPU NIMs re-scheduled first and filled every GPU node in that AZ | Evict one constraint-free GPU pod from a node in the PV's AZ (it reschedules elsewhere; kdbx takes the slot). Long-term: pin kdbx to the PV's AZ via nodeSelector, or use a per-AZ nodegroup |
| `LicenseException ... q license` on rag-server/ingestor | `kdbx.pykxUnlicensed=false` but PyKX rejected the CE `kc.lic` | Keep the default `kdbx.pykxUnlicensed=true` (IPC-only mode) |

---

## Reference: file map

| File | Purpose |
|---|---|
| `deploy/EKS/rag-dev-cluster.yaml` | eksctl cluster config (AL2023 GPU pool + system pool) |
| `deploy/EKS/rag-values-kdbx.yaml` | Base Helm overlay (KDB-X, EBS storage, NGC LLM) |
| `deploy/EKS/rag-values-kdbx-cuvs.yaml` | GPU CAGRA overlay (arms cuVS + client GPU flags) |
| `deploy/helm/nvidia-blueprint-rag/files/kdbx/Dockerfile.kdbx` | KDB-X server image |
| `deploy/helm/nvidia-blueprint-rag/files/kdbx/kdbx-init.q` | `.rag.*` server functions, loaded at q startup (ConfigMap) |
| `src/nvidia_rag/{rag,ingestor}_server/Dockerfile` | rag-server / ingestor images |

For the conceptual guide and Docker-Compose path, see
[`docs/change-vectordb-kdbx.md`](change-vectordb-kdbx.md).
