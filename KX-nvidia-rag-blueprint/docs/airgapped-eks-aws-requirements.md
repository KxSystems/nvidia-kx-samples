<!--
  SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->
# Airgapped EKS — AWS Provisioning Requirements (NVIDIA RAG Blueprint + KDB-X)

> Meeting brief for AWS/IT. Generated 2026-06-01 from the repo configs
> (`deploy/helm/nvidia-blueprint-rag/`, `deploy/EKS/`) — file:line references ground
> every number. Scope = the enabled **KDB-X + self-hosted-LLM-on-g7e** path.

## 1. Executive summary

We are deploying the NVIDIA RAG Blueprint (KX fork, chart `nvidia-blueprint-rag` v2.3.4) onto an **eksctl-managed EKS 1.30 cluster named `rag-dev` in `us-west-2`** (`rag-dev-cluster.yaml:5-7`), running entirely in **private subnets with no internet egress**. The vector store is **self-hosted KDB-X** (HNSW CPU default; GPU CAGRA available via `rag-values-kdbx-cuvs.yaml` overlay — `rag-values-kdbx.yaml:116-117`); the **49B LLM is self-hosted** on a g7e Blackwell node as FP8 single-GPU (`rag-values-llm-selfhost-g7e.yaml:34-44`); embed/rerank/VLM/nv-ingest extraction NIMs run on a g5/g6 pool. Because there is no egress, **every container image, every Helm chart, and every model weight must be pre-staged inside the VPC**, and every AWS API call (ECR, STS, EC2, ELB, EKS) must traverse a private VPC endpoint. The airgap ask has three pillars: (a) a full **private VPC endpoint set** (incl. the S3 *gateway* endpoint that ECR pulls silently depend on); (b) a **private ECR mirror of ~26 images (incl. co-deployed AIRA) plus pre-staged NIM model-weight caches** (the classic airgap killer — NIM 1.x fetches weights from NGC at boot); and (c) **GPU compute + a g7e vCPU service-quota increase** (often 0 by default, longest lead item). Two images (the KDB-X DB image and the `*-kdbx` RAG/ingestor images) **must be built on a connected staging host** because they pull from `portal.dl.kx.com` at build time — that can never run inside the airgap. The **AIRA sister blueprint is co-deployed** (decided), but its 70B instruct is **descoped** — AIRA reuses the shared self-hosted **49B** as its LLM, so there is **one** self-hosted LLM total (1 g7e GPU). AIRA's own app images are folded into §1b.8 and §5.

## 1a. Decide first: image & model delivery posture (A vs B)

NVIDIA supports **two** ways to get images + model weights into the cluster, and which one you pick changes most of §2. **Decide this in the meeting before anything else** — it hinges on a single question: *is the environment truly zero-egress, or is an allowlisted forward proxy permitted?*

> The detailed asks in §2 below assume **Posture A** (full mirror). Under Posture B, §C (ECR mirror + weight pre-staging) collapses to "forward proxy + allowlist"; the AWS-API VPC endpoints in §A (STS/EC2/ELB/EBS) stay MUST either way (they're EKS/EBS internals, not image pulls).

### Posture A — Full ECR mirror + pre-staged weights (true zero-egress airgap)
Mirror every image to private ECR, pre-stage every NIM model-weight cache on PVCs, vendor the Helm charts. No runtime egress at all.

| Pros | Cons |
|---|---|
| **True zero-egress** — meets strict airgap/compliance mandates; nothing leaves the VPC | **Largest upfront effort** — ~22 images + the harder model-weight pre-staging |
| **Deterministic / reproducible** — pinned digests; immune to upstream tag deletion, NGC outages, Docker Hub rate limits | **Ongoing maintenance** — every version bump (and we bump often) = re-mirror + re-stage |
| **Fast in-region pulls** (ECR); no external dependency at scale-up/restart | **Two images must be *built*** on a connected host (`kdbx-rag`, `*-kdbx`) regardless |
| **Auditable** — exact, fixed inventory of what's inside the boundary | **Weight pre-staging is the big lift** (NGC two-phase offline workflow) + ECR/EBS storage cost + a staging/bastion host |

### Posture B — Allowlist NVIDIA (+ HF + KX) egress via forward proxy
Permit outbound HTTPS from the cluster (or a forward proxy) to a fixed domain set. Images pull from `nvcr.io` directly; NIMs download weights from NGC/HF on first boot (then cached on PVC). No mirroring of NVIDIA assets.

**Domains to allowlist** (per NVIDIA NIM docs):
- `nvcr.io`, `authn.nvidia.com` — registry + auth
- `api.ngc.nvidia.com`, `xfiles.ngc.nvidia.com` — NGC API + model-file downloads
- `huggingface.co`, `cas-bridge.xethub.hf.co` — some NIMs pull tokenizers/weights from HF
- `portal.dl.kx.com` — KDB-X / KX build + binary downloads
- `docker.io`, `quay.io`, `registry.k8s.io` — infra/platform images (unless those are mirrored)

| Pros | Cons |
|---|---|
| **Dramatically less work** — no mirror, no weight pre-staging, no staging host for NVIDIA images | **Not a true airgap** — requires permitting external egress; may violate the mandate outright (*the deciding factor*) |
| **NIMs "just work"** — auto-select profiles, download weights on boot; NVIDIA's happy path | **Domain/SNI allowlist required** — nvcr.io/NGC/HF are CDN-fronted (CloudFront/Cloudflare/Xet), so IP/CIDR rules don't work → needs a forward proxy with SNI/DNS filtering |
| **Trivial version bumps** — change the tag, it pulls | **Trust surface widens to HuggingFace + Cloudflare CDNs**, not just NVIDIA |
| **Less storage/ops** — no ECR mirror to maintain (weights still cached on PVC after first pull) | **Runtime dependency** on NVIDIA/HF uptime + NGC rate limits at deploy/scale/restart |
| Matches NVIDIA's documented proxy deployment | **TLS-proxy plumbing** — custom CA into NIMs (`NIM_SDK_USE_NATIVE_TLS=1`, `SSL_CERT_FILE`) + `ulimit nofile=1048576` (NIM opens many FDs through a proxy); + allowlist drift maintenance |

### Hybrid (often the sweet spot)
The *hard* part of Posture A is the **weights**; the *easy* part is the images. So: **mirror images to ECR (Posture A) but allowlist only the NGC/HF weight-download endpoints** (`api.ngc.nvidia.com`, `xfiles.ngc.nvidia.com`, `authn.nvidia.com`, `huggingface.co`, `cas-bridge.xethub.hf.co`). NIMs download weights once on first boot (cached on PVC), removing the biggest pre-staging pain while keeping the image supply local and your own KX images in ECR.

### Decision criterion
- **Hard zero-egress mandate (classified / strict compliance)** → **Posture A**, no choice.
- **A controlled forward proxy with domain allowlisting is permitted** → **Posture B** or **Hybrid** — saves enormous effort.
- This maps to open question #10. Either way you keep ECR (for the self-built KX images) and the AWS-API VPC endpoints.

## 1b. External dependency inventory (what crosses the boundary)

Every external thing this deployment reaches for, with its **disposition**: **MIRROR** (copy into ECR/internal), **VENDOR** (copy Helm charts in, one-time), **BUILD** (produce on a connected host — cannot be copied as-is), **PRE-STAGE/ALLOWLIST** (model weights — Posture A pre-stages, Posture B/Hybrid allowlists), or **VPC-ENDPOINT** (AWS APIs via PrivateLink, neither mirrored nor allowlisted). Full image tag list is in §5.

### 1. Container image registries → MIRROR to ECR
| External source | Provides | Auth | Disposition |
|---|---|---|---|
| `nvcr.io/nim/nvidia/*` | LLM, embed, rerank, VLM, page/graphic/table, parse NIMs | NGC `$oauthtoken` (gated) | **MIRROR** |
| `nvcr.io/nim/baidu/paddleocr` | OCR (alt) | NGC (gated) | **MIRROR** |
| `nvcr.io/nvidia/nemo-microservices/*` | nv-ingest + bundled extractors; guardrails | NGC (gated) | **MIRROR** |
| `nvcr.io/nvidia/blueprint/rag-frontend` | UI | NGC | **MIRROR** |
| `portal.dl.kx.com/*` | `kdbai-db-cuvs` (KDB.AI path only), KX-published images | KX OAuth | **MIRROR** (KDB.AI path) |
| `docker.io` | `minio/minio`, `redis`, `python:3.12-slim-bookworm` | Docker Hub (rate-limited — authenticate) | **MIRROR** |
| `quay.io`, `registry.k8s.io` | observability + self-managed platform images | anon | **MIRROR** (only if those features on) |

### 2. Self-managed platform/GPU images → MIRROR to ECR
| Source | Provides | Disposition |
|---|---|---|
| `nvcr.io` / `registry.k8s.io` | **NVIDIA device plugin + DCGM** (or full GPU Operator incl. its **driver image**) | **MIRROR** (mandatory for GPU scheduling) |
| `registry.k8s.io` / public ECR | cluster-autoscaler / Karpenter (if used, min-0 pools) | **MIRROR** (if used) |
| public ECR / quay.io | AWS Load Balancer Controller (if ALB) | **MIRROR** (if ALB) |
| AWS regional ECR (`602401143452.dkr.ecr.us-west-2…`) | EKS **managed** addons: vpc-cni, coredns, kube-proxy, aws-ebs-csi-driver | **VPC-ENDPOINT** — EKS pulls these via the ECR+S3 endpoints; you just **pin versions** (not `latest`) |

### 3. Helm chart repositories → VENDOR (copy charts in, one-time on connected box)
| Repo | Charts |
|---|---|
| `helm.ngc.nvidia.com/nim` (+ `/nvidia`) | `nim-llm`, embed, rerank |
| `helm.ngc.nvidia.com/nvidia/nemo-microservices` | `nv-ingest` |
| `prometheus-community.github.io/helm-charts` | `kube-prometheus-stack` (if observability on) |
| `open-telemetry.github.io/opentelemetry-helm-charts` | `opentelemetry-collector` (if on) |
| `zipkin.io/zipkin-helm` | `zipkin` (if on) |

Already vendored as `charts/*.tgz` matching `Chart.lock` → transfer the dir intact and `helm install` (do **not** run `helm dependency update` in the airgap). Charts pin images — mirroring charts does **not** mirror their images (§1–2 above).

### 4. Model weights & runtime fetch → PRE-STAGE (Posture A) **or ALLOWLIST (Posture B/Hybrid)**
*This is the "allowlist for the LLM weights" set.* NIM 1.x downloads weights/engines on first boot.
| Endpoint | Provides |
|---|---|
| `authn.nvidia.com` | NGC auth token |
| `api.ngc.nvidia.com` | NGC API / model manifest |
| `xfiles.ngc.nvidia.com` | NIM model weights + engine files |
| `huggingface.co` | tokenizers / some model weights |
| `cas-bridge.xethub.hf.co` | HuggingFace Xet CDN (weight blobs) |

> CDN-fronted → allowlist by **domain/SNI** via a forward proxy, not by IP/CIDR. Posture A avoids these entirely by pre-staging the cache onto PVCs.

**Posture A pre-stage procedure — official, NIM LLM 1.15.x** ([NVIDIA air-gap guide](https://docs.nvidia.com/nim/large-language-models/1.15.0/deploy-air-gap.html)):
1. **Connected phase** — on the staging host, run the NIM image's `download-to-cache` (or `create-model-store`) with `NGC_API_KEY` set, pinning the exact profile:
   ```bash
   export LOCAL_NIM_CACHE=~/.cache/nim
   export NIM_MODEL_PROFILE=<profile-hash from `list-model-profiles`>   # verified values below
   download-to-cache -p $NIM_MODEL_PROFILE
   # or: create-model-store --profile $NIM_MODEL_PROFILE --model-store /model-repo
   ```

   **FIELD-VERIFIED profile IDs** (live `list-model-profiles` on a g7e RTX PRO
   6000 Blackwell, NIM `llama-3.3-nemotron-super-49b-v1.5:1.15.5`, 2026-06-11 —
   profile hashes are per-NIM-image, so re-verify after a NIM tag bump):

   | Profile | ID to pass to `--profile` / `NIM_MODEL_PROFILE` |
   |---|---|
   | **FP8 TP1 throughput** (auto-selected, validated serving) | `1cafe40d906fd2c1f82cdcb56d141212826ad4521124276ee77611e776f1f04a` |
   | NVFP4 TP1 throughput (faster: ~1.32× FP8 on this GPU) | `73ea7038053e5e103fd92da955a590dad96cdbe1b1aa957049b714f747e014d7` |

   Full FP8 profile name for reference:
   `tensorrt_llm-rtx6000_blackwell_sv-fp8-tp1-pp1-throughput-pytorch-2bb5:10de-603587f8…-1-true`.

   > ⚠️ **Do not confuse profile IDs with NGC cache refs.** The cache directory
   > contains snapshot tags like
   > `trtllmapi-pt-runtime-params-rtx6000-blackwell-svx1-throughput-fp8-…` and
   > `fp8-rmctserfba-tool-calling` — those are the *artifact bundles a profile
   > resolves to* (runtime-params + checkpoint), not profile names; passing one
   > to `--profile` fails. The second hash embedded in a profile *name* is its
   > `nim_workspace_hash_v1`, also not an ID.

   > **No compile step exists for this model**: the selected profile runs
   > TRT-LLM's PyTorch backend (`Detected ModelOpt fp8 checkpoint` → runtime
   > optimization), and `list-model-profiles` explicitly reports "Compilable to
   > TRT-LLM using just-in-time compilation: \<None\>". The airgapped first boot
   > therefore needs no toolchain and no internet — checkpoint load + runtime
   > opt only (the ~12 min connected-phase boot cost is mostly the ~50 GB
   > download; warm-cache boots are a couple of minutes).
2. **Transfer** the cache into the airgap (→ the LLM's EBS PVC, mounted at `/opt/nim/.cache`).
3. **Airgapped run phase** — mount the cache, **pin the same `NIM_MODEL_PROFILE` hash, and DO NOT set `NGC_API_KEY`** (with it set, NIM may attempt NGC; without it + a cached profile, NIM serves purely from cache, zero registry access).

> **Two config implications for our overlay** (`rag-values-llm-selfhost-g7e.yaml`), under Posture A:
> - `NIM_MODEL_PROFILE: ""` (auto) **must be replaced with the pinned profile hash** — auto-select queries NGC and hangs offline.
> - Drop the NGC API key from the runtime LLM pod (`model.ngcAPISecret`) — pre-staged cache needs no key; setting it can trigger a phone-home.

### 5. Build-time only → consumed on the connected staging host (never needed inside the airgap)
| Source | For |
|---|---|
| `portal.dl.kx.com` | `install_kdb.sh` + q binary, baked into `kdbx-rag` at build (`Dockerfile.kdbx:43-48`) |
| `docker.io` `python:3.12-slim-bookworm` | build base image |
| `pypi.org` / `files.pythonhosted.org` | pip deps when building `rag-server-kdbx` / `ingestor-server-kdbx` from source |
| `deb.debian.org` / `security.debian.org` | apt packages in base-image build |

Output of this phase = the `kdbx-rag`, `rag-server-kdbx`, `ingestor-server-kdbx` images pushed to ECR. Inside the airgap, none of these sources are contacted.

### 5a. ⚠️ Runtime conda install of `librosa` (audio ingest) — nv-ingest (FIELD-CONFIRMED)
A live test showed nv-ingest, **at boot**, logging `Checking if librosa is installed... Installing librosa using conda...` and pulling **`librosa`** (the audio-analysis library) + its deps (`aom`, `audioread`, `brotli`, `contourpy`, …) from **`conda-forge`** on **`conda.anaconda.org`**. This is a **runtime** install (not build-time), it's **not in NVIDIA's documented endpoint lists**, and it **breaks offline**.

**Confirmed scope:**
- **Endpoint:** `conda.anaconda.org` (channel **`conda-forge`**) — `repo.anaconda.com` / `pypi.org` were **not** observed.
- **Licensing: not an issue** — `conda-forge` is community-licensed (free); the Anaconda paid-license ToS (`anaconda`/`main` channels) does **not** apply here. *(Confirm it stays on conda-forge.)*
- **Tied to audio ingestion, and the exact toggle is known.** The boot-time install is gated by **`nv-ingest.envVars.INSTALL_AUDIO_EXTRACTION_DEPS`**, hardcoded **`"true"`** in the chart (`values.yaml:1114`). Yet the audio model (**Riva ASR `riva-nim`) is NOT deployed by default** (`APP_NVINGEST_SEGMENTAUDIO: "False"`, `values.yaml:340`; enabling audio requires adding `nv-ingest.riva-nim.deployed: true` per [audio_ingestion.md](audio_ingestion.md)). So the chart installs `librosa` **for a feature that isn't even on** — pointless egress.

**Mitigations (best first):**
1. **Set `INSTALL_AUDIO_EXTRACTION_DEPS: "false"`** in `nv-ingest.envVars` (one line in the EKS overlay). Since `riva-nim` isn't deployed, you lose **nothing** and the `conda.anaconda.org` boot fetch disappears. **This is the fix unless audio is in scope.**

   > **Audio extraction in airgap**: Set `INSTALL_AUDIO_EXTRACTION_DEPS=false` on the nv-ingest pod to prevent it from attempting to contact `conda.anaconda.org` for `librosa`. In airgap, this contact will hang. Add to your values overlay:
   > ```yaml
   > nv-ingest:
   >   envVars:
   >     INSTALL_AUDIO_EXTRACTION_DEPS: "false"
   > ```
2. **If audio *is* needed:** keep it `"true"`, **pre-bake `librosa` + deps into the nv-ingest image** (connected staging host → zero runtime install), **and** deploy `riva-nim` (`nvcr.io/nim/nvidia/riva-asr` + ASR model weights, **+1 GPU H100/B200**).
3. Alternatively **mirror the conda-forge subset** (`librosa` + transitive deps) internally and point `.condarc` at it, or (Posture B/Hybrid) **allowlist `conda.anaconda.org`**.

> Arguably a **bug** — a production service image shouldn't `conda install` at runtime. Worth raising with NVIDIA / the nv-ingest maintainers, and pinning an `nv-ingest` build that bakes `librosa` in (or gates it behind the audio feature).

### 6. AWS service APIs → VPC endpoints (neither mirrored nor allowlisted)
ECR, S3, STS, EC2, ELB, EKS, EBS, (logs/ssm) — provisioned as PrivateLink endpoints, see §2A. Not an image/weight dependency.

### 7. Easy-to-miss external touches → confirm disabled/internal
| Item | Action |
|---|---|
| **NIM telemetry / usage phone-home** | Disable (NIM telemetry opt-out env) — otherwise pods attempt egress and log errors |
| **KDB-X licensing** | Offline `kc.lic` / `KDB_LICENSE_B64`, `PYKX_UNLICENSED=1` — **no license server call**; confirm no online check at start |
| **NVIDIA AI Enterprise / NGC entitlement** | Pre-staged caches need no runtime entitlement check; confirm for the chosen NIM versions |
| **Time (NTP)** | Provide an internal NTP source — TLS/STS fail with clock skew |

### 8. AIRA sister blueprint (co-deployed — incremental dependencies)
AIRA (`aiq-research-assistant`) is deployed and mirrored in the **same pass**. Its **70B instruct LLM is descoped** — AIRA **reuses the shared self-hosted 49B** (`nim-llm`) as its instruct/report-writing LLM, so it adds **no extra LLM and no extra GPU**. It also reuses rag2's retrieval NIMs as a service (no extra embed/rerank/VLM). Only its **app images** are incremental.
| External source | Provides | Disposition |
|---|---|---|
| `portal.dl.kx.com/aiq-kx-backend:1.0.2` | AIRA backend service | **MIRROR** |
| `portal.dl.kx.com/aiq-kx-frontend:1.0.2` | AIRA frontend | **MIRROR** |
| `docker.io/arizephoenix/phoenix:latest` | tracing UI (pin the tag — `latest` won't resolve offline) | **MIRROR** |
| `docker.io/redis:8.2.1` | AIRA job tracking | **MIRROR** (shared image with rag2) |
| `kdb-x-mcp-server` (`your-registry/...`, python base, `build-kdbx-image.sh`) | KDB-X MCP server | **BUILD** on connected host → ECR |
| Helm: `aiq-aira` chart + `nim-llm` subchart (`helm.ngc.nvidia.com/nim` `1.13.1`) | AIRA chart | **VENDOR** |

> AIRA's instruct LLM is repointed to the shared `nim-llm:8000` (the 49B) in AIRA's own values — so there is **one** self-hosted LLM, **one** g7e GPU, and **no new weights/endpoints** from AIRA. (Trade-off: report-writing runs on the 49B reasoning model rather than a dedicated 70B instruct — an accepted scope call.)

## 2. Ask AWS/IT to provision

### A. Networking & VPC endpoints
| Item | Pri | Detail |
|---|---|---|
| Private subnets only, ≥2 AZs, no IGW/NAT | **MUST** | Cluster `rag-dev`, `us-west-2`. Tag `kubernetes.io/cluster/rag-dev=shared`, `kubernetes.io/role/internal-elb=1`. VPC-CNI assigns a real VPC IP per pod (~9 GPU + 1 g7e + 3 system nodes, many NIM pods) — size CIDRs generously. |
| **S3 gateway endpoint** `com.amazonaws.us-west-2.s3` | **MUST** | Free, route-table attached. **Required for ECR pulls** (layer blobs live in S3); without it every `docker pull` fails with opaque ImagePullBackOff. |
| ECR interface endpoints `ecr.api` + `ecr.dkr` | **MUST** | Both needed: `ecr.api` for auth/`get-login-password` (`rag-values-kdbx.yaml:20`), `ecr.dkr` for the data path. |
| STS interface endpoint `com.amazonaws.us-west-2.sts` (regional) | **MUST** | IRSA enabled (`rag-dev-cluster.yaml:9-10`); EBS CSI controller assumes role via STS. Global `sts.amazonaws.com` is NOT served by the regional endpoint — must use regional. Without it, IRSA hangs and PVCs stay Pending. |
| EC2 interface endpoint `com.amazonaws.us-west-2.ec2` | **MUST** | VPC-CNI (ENI/IP attach) and EBS CSI (volume attach) call EC2 APIs. |
| EKS control-plane private endpoint | **MUST** | Set endpoint access Private (or Private + CIDR allowlist). Cluster SG must allow node→443. |
| `elasticloadbalancing` interface endpoint | **MUST** | For the AWS LB Controller / in-tree provisioning of the internal NLB/ALB. |
| Internal-scheme NLB/ALB + private Route53 record | **MUST** | Chart ships **no** internal LB/Ingress: rag-server is ClusterIP:8081 (`values.yaml:45-47`), ingestor ClusterIP:8082 (`values.yaml:255-257`), frontend **NodePort:3000** (`values.yaml:394-396`). Add `scheme: internal` LB + private hosted-zone A/alias (e.g. `rag.internal.<domain>`). |
| Enable Private DNS on every interface endpoint | **MUST** | Needs VPC `enableDnsSupport` + `enableDnsHostnames`; otherwise pods resolve public AWS hostnames and time out. |
| Endpoint security group: 443 inbound from node + cluster SGs | **MUST** | Cover gpu-pool, gpu-llm-g7e, and cpu-system node SGs. |
| CloudWatch Logs endpoint `com.amazonaws.us-west-2.logs` | SHOULD | If control-plane logging / CloudWatch agent enabled. |
| SSM endpoints `ssm` / `ssmmessages` / `ec2messages` | SHOULD | Break-glass node shell via Session Manager (no SSH bastion in airgap). |
| `autoscaling` endpoint | SHOULD | If Cluster Autoscaler used (all node groups `minSize: 0`). |
| Private NTP source; confirm no `0.0.0.0/0` egress route | NICE | Accurate time needed for TLS/STS; confirm airgap is actually enforced. |

### B. EKS, compute, GPU & quotas
| Item | Pri | Detail |
|---|---|---|
| **Raise G-series On-Demand vCPU quota for g7e** | **MUST** | Service Quotas code **L-DB2E81BA** (`us-west-2`). g7e.24xlarge = 96 vCPU; need ≥96 for desired 1, ≥192 for max 2. g7e is new (GA 2026-01, us-west-2 since 2026-02); quota frequently 0 — **longest lead item, request first** (`g7e-llm-nodegroup.yaml:18-20`). |
| LLM GPU node group `gpu-llm-g7e` | **MUST** | 1× **g7e.24xlarge** (4× RTX PRO 6000 Blackwell, 96GB), AL2023 GPU AMI, 200Gi gp3 root, desired 1 / min 0 / max 2, taint `dedicated=llm:NoSchedule`, label `node-type=gpu-llm`. **Hosts the one self-hosted LLM: rag2 49B (1 GPU, FP8 TP1); 3 headroom** (AIRA reuses the same 49B). A single g7e GPU covers it (`g7e-llm-nodegroup.yaml:39-57`, `rag-values-llm-selfhost-g7e.yaml:40-44`). |
| General GPU node group `gpu-pool` | **MUST** | g5/g6 family (dev pins **g5.2xlarge**, 1 GPU/node), AL2, 100Gi gp3 root, desired 9 / min 0 / max 12. Hosts embed/rerank/VLM/nv-ingest extraction (8 GPUs), +2 if Guardrails on (`rag-dev-cluster.yaml:13-29`). KDB-X GPU (cuVS) is NOT in this pool — it schedules to its own node via `kdbx.gpu.nodeSelector` in `rag-values-kdbx-cuvs.yaml`. |
| CPU/system node group `cpu-system` | **MUST** | 3× **t3.xlarge** (16 GiB RAM), 50Gi gp3, desired 3 / max 4, label `node-type=system`. Hosts rag-server, ingestor, MinIO, coredns, CSI controllers (`rag-dev-cluster.yaml:31-39`). Note: t3.medium (4 GiB) is too small — rag-server and ingestor each request 8 GiB. |
| GPU driver delivery path for airgap | **MUST** | Blackwell sm_120 needs driver ≥570/580 (`g7e-llm-nodegroup.yaml:21-23`). Prefer (a) EKS accelerated AL2023 AMI with driver baked in (no runtime pull); else (b) GPU Operator with its **driver image mirrored to ECR**. Verify the AMI's bundled driver ≥570/580 before deploy. |
| NVIDIA device plugin reaches g7e nodes | **MUST** | Device-plugin (+ DCGM) images mirrored to ECR; the DaemonSet **must tolerate `dedicated=llm:NoSchedule`** or `nvidia.com/gpu` is never advertised and the LLM pod stays Pending. GPU Operator tolerates all taints by default (`g7e-llm-nodegroup.yaml:24-29`). |
| EBS gp3 for model caches | SHOULD | aws-ebs-csi-driver addon + `rag-storage` SC; LLM cache 120Gi RWO (`rag-values-llm-selfhost-g7e.yaml:58-62`). |
| Cluster Autoscaler / Karpenter for min-0 pools | NICE | Scale-from-zero needs autoscaler awareness of GPU labels/taints; its image must be mirrored. |

### C. ECR & image mirroring
| Item | Pri | Detail |
|---|---|---|
| Private ECR registry + one repo per image (~22) | **MUST** | See BoM §5 for the full tag list. The 8 vendored Helm subchart `.tgz` are already committed in `charts/` matching `Chart.lock` — but vendoring charts does **not** vendor images. |
| Connected staging/bastion host (Docker + skopeo/crane + helm v4) | **MUST** | Temporary egress to nvcr.io, portal.dl.kx.com, docker.io, quay.io, registry.k8s.io + the 4 helm repos; push to ECR. Pull-tag-push each image (`skopeo copy --all`). |
| NGC API key / catalog entitlement for gated pulls | **MUST** | All `nvcr.io/nim/*` + `nvcr.io/nvidia/nemo-microservices/*` are gated; auth `$oauthtoken` + NGC_API_KEY. Confirm entitlement covers 49B, embed/rerank, VLM, 4 extraction NIMs, paddleocr, parse. |
| **Build KDB-X DB image** `kdbx-rag:1.0.0` on staging | **MUST** | `Dockerfile.kdbx:43-48` curls `install_kdb.sh` + q binary from `portal.dl.kx.com` via OAuth bearer at **build time**, bakes in b64 license; base `python:3.12-slim-bookworm` (`Dockerfile.kdbx:25`). Cannot run in airgap — build once, push to ECR. |
| **Build `rag-server-kdbx` / `ingestor-server-kdbx` 2.3.4** on staging | **MUST** | Overlay points at `portal.dl.kx.com/rag-server-kdbx:2.3.4` / `ingestor-server-kdbx:2.3.4` but **warns these may not be published** — published KX images are `-kdbai` variants lacking the KDB-X adapter (`rag-values-kdbx.yaml:55-72,200-201`). Confirm with KX; else build from `src/nvidia_rag/{rag,ingestor}_server/Dockerfile`. |
| **Pre-stage NIM model-weight caches on PVCs** | **MUST** | NIMs download weights from NGC at first boot → crashloop in airgap. Only the 49B has a cache PVC (120Gi, `rag-values-llm-selfhost-g7e.yaml:54-62`); embed/rerank/VLM/extraction NIMs default `persistence.enabled=false`. Pre-populate caches in staging or use NGC offline bundle. **Larger lift than the images.** |
| Mirror Docker Hub infra: `minio/minio:RELEASE.2025-09-07T16-13-09Z`, `redis:8.2.1` | **MUST** | `rag-values-kdbx.yaml:144-146`, nv-ingest bundled redis. Subject to Docker Hub rate limits — authenticate or use a pull-through cache. |
| Repoint image registries + pull secrets to ECR | SHOULD | Chart hardcodes `nvcr.io`/`portal.dl.kx.com`. Override per parent **and** per-subchart image blocks (a single global override misses the NIM subcharts). Switch pull secrets to ECR auth (IRSA or `get-login-password`). |
| Observability image set (kube-prometheus-stack 76.3.0, otel 0.130.2, zipkin 0.4.0) | SHOULD | All default `enabled:false` and disabled in the kdbx overlay (`otelEnabled:false`). If turned on, `helm template` the subcharts to enumerate ~10 extra images (quay.io/docker.io/registry.k8s.io). |
| Guardrails images if enabled | NICE | `guardrails:25.09` + 3× `nemoguard-8b-*:1.10.1` (`model-inventory.md:142-144`); +1 GPU each. Default off. |

### D. IAM / OIDC
| Item | Pri | Detail |
|---|---|---|
| Cluster OIDC provider (IRSA) | **MUST** | `iam.withOIDC: true` (`rag-dev-cluster.yaml:9-10`); reachable only via STS endpoint. Decide eksctl vs IT pre-creates OIDC. |
| ECR read policy on both GPU + system node roles | **MUST** | Nodes pull all images from private ECR. |
| EBS CSI IRSA role | **MUST** | `wellKnownPolicies.ebsCSIController: true` (`rag-dev-cluster.yaml:50-51`): CreateVolume/AttachVolume. |
| ECR pull auth model | SHOULD | Confirm node IAM role vs IRSA for pull; affects how pull secrets are wired vs chart's hardcoded `nvcr.io`/KX secrets. |

### E. Storage
| Item | Pri | Detail |
|---|---|---|
| aws-ebs-csi-driver as managed addon, **pinned version** (not `latest`) | **MUST** | `version: latest` (`rag-dev-cluster.yaml:48-49`) stalls in airgap (must resolve from public ECR). Pin explicit version; mirror `ebs-csi-controller` + `ebs-csi-node` images. |
| gp3 StorageClass `rag-storage` | **MUST** | Chart creates it (`rag-values-kdbx.yaml:84-93`): `ebs.csi.aws.com`, gp3, `WaitForFirstConsumer`, `reclaimPolicy: Delete`, `isDefault: false`. Confirm whether cluster has a default SC. |
| Total EBS capacity / gp3 quota | **MUST** | App PVCs (all RWO): KDB-X 50Gi, MinIO 50Gi, ingestor 50Gi, nv-ingest redis (~8Gi), LLM cache 120Gi = ~280Gi. Node roots: g5×9@100=900Gi, t3×3@50=150Gi, g7e×1@200=200Gi. **~1.5 TiB total provisioned gp3.** Confirm the "gp3 storage, in TiB" Service Quota with headroom. |
| Per-NIM model-cache PVCs (embed/rerank/VLM/extraction) | SHOULD | All default `persistence.enabled=false` → emptyDir, re-stage on restart. Either enable ~50Gi PVCs each on `rag-storage`, or confirm node roots absorb staged models + pre-pulled images. The file `deploy/EKS/rag-values-nim-cache.yaml` provisions separate PVCs for caching NIM model weights, avoiding re-download on pod restart. Layer it in your helm install command: `helm install ... -f deploy/EKS/rag-values-nim-cache.yaml`. |
| EBS snapshot / backup policy + VolumeSnapshotClass | SHOULD | `reclaimPolicy: Delete` destroys KDB-X/MinIO data on PVC delete. Decide AWS Backup / DLM. |
| EBS KMS encryption | NICE | SC sets no `encrypted`/`kmsKeyId`; if CMK required, add to SC params + grant EBS CSI IRSA `kms:CreateGrant/Decrypt`. |

### F. Secrets & licensing
| Item | Pri | Detail |
|---|---|---|
| `kdbx-license-secret` (KDB_LICENSE_B64) | **MUST** | Mounted at `/opt/kx-license`; `PYKX_UNLICENSED=1` (IPC-only mode proven) (`rag-values-kdbx.yaml:23-25,119-124`). Must work offline with no online license check at container start. |
| `kdbx-license-secret` (KDB_BEARER_TOKEN) | SHOULD | Required when using the test-deploy entrypoint with `KDBX_USE_CUVS=1`. Used by `kdbx-entrypoint.sh` to download the cuVS module from `portal.dl.kx.com` at pod startup. Not needed in production (customer manages KDB-X). |
| `kdbx-registry-secret` (ECR docker-registry) | **MUST** | `--docker-username=AWS --docker-password=$(aws ecr get-login-password)` (`rag-values-kdbx.yaml:16-21,108-110`). |
| `ngc-api` secret (NGC_API_KEY) | **MUST** | Used by the self-hosted NIM model block (`rag-values-llm-selfhost-g7e.yaml:53`). |
| MinIO credentials | MUST | Currently `minioadmin/minioadmin` (`rag-values-kdbx.yaml:148-149`) — rotate for production. |
| Secrets Manager + External Secrets endpoint | SHOULD | If secrets sourced from Secrets Manager, add a `secretsmanager` interface endpoint. |

## 3. Airgap gotchas (deduped)

- **eksctl picks non-GPU AL2023 AMI for g7e**: eksctl does not recognise g7e as a GPU instance type and provisions a standard AL2023 AMI (no driver). You must pin the AL2023-NVIDIA AMI explicitly in the nodegroup config. See `deploy/EKS/g7e-llm-nodegroup.yaml` for the required `ami:` and `overrideBootstrapCommand` fields.
- **NIM model weights are the real airgap killer, not the images.** NIM 1.x (pinned `1.15.5`) is *not* Model-Free — first boot reaches NGC for the runtime manifest/engines and crashloops offline. Only the 49B has a cache PVC; embed/rerank/VLM/extraction NIMs ship `persistence.enabled=false`. Pre-stage all caches on PVCs. (NIM 2.0 fixes this but is deliberately not adopted — it drops TensorRT-LLM and has a documented 49B deploy failure, `model-inventory.md:49-101`.)
- **nv-ingest runtime-installs `librosa` via conda (field-confirmed).** At boot it pulls `librosa` + deps from **conda-forge** (`conda.anaconda.org`) — undocumented egress that breaks offline (conda-forge is free, no license issue). Gated by **`INSTALL_AUDIO_EXTRACTION_DEPS`**, hardcoded `"true"` in the chart even though the audio model (`riva-nim`) is off by default. **Fix: set `INSTALL_AUDIO_EXTRACTION_DEPS: "false"`** (zero loss unless audio is used). See §1b.5a.
- **The S3 *gateway* endpoint is mandatory for ECR.** ECR layer blobs live in S3; without it, pulls fail with opaque ImagePullBackOff even though the ECR interface endpoints exist.
- **STS + EC2 endpoints gate EBS CSI / IRSA.** Missing STS → IRSA token exchange hangs → CreateVolume/AttachVolume hang → PVCs stuck Pending. Use the *regional* STS endpoint, not global.
- **Two images cannot be mirrored — they must be built on a connected host.** `Dockerfile.kdbx:43-48` pulls q from `portal.dl.kx.com` at build time; and `*-kdbx:2.3.4` RAG/ingestor images likely aren't published (only `-kdbai` exist). Build both in staging, push to ECR.
- **GPU driver must already be on the node.** Blackwell sm_120 needs driver ≥570/580; in airgap you cannot pull a driver at runtime. Use an accelerated AMI with the driver baked in, or mirror the GPU Operator driver image — and verify the version.
- **CUDA error 803 on g7e LLM NIM**: caused by compat-libcuda shadow (host driver 580.159.03 vs NIM bundled 580.95.05). The fix is already applied in `rag-values-llm-selfhost-g7e.yaml` (emptyDir mount over `/usr/local/cuda-13.0/compat`).
- **Device plugin must tolerate the LLM taint.** `dedicated=llm:NoSchedule` means a standalone device plugin without the toleration never advertises `nvidia.com/gpu` on g7e → LLM stays Pending with no obvious error.
- **The overlays default LLM endpoints to `https://integrate.api.nvidia.com`** (`rag-values-kdbx.yaml:182-193`) — unreachable in airgap. The g7e self-host overlay (layered last) flips them to `nim-llm:8000` (`rag-values-llm-selfhost-g7e.yaml:78-86`); it is **mandatory**, not optional.
- **`NIM_MODEL_PROFILE` is empty** (`rag-values-llm-selfhost-g7e.yaml:47-49`) → auto-select queries NGC and hangs offline. Pin the `tensorrt_llm-rtx6000_blackwell_sv-fp8-tp1` profile, verified via `list-model-profiles` on tag 1.15.5.
- **Pin addon + tag versions exactly.** `version: latest` on EKS addons (`rag-dev-cluster.yaml:43,45,47,49`) requires public resolution. NIM tags must match the cache exactly (1.15.5) or the cache is ignored.
- **Image registry overrides are split** across parent values and each NIM subchart's own image block — a single global override won't catch them all.
- **`helm dependency update` must NOT run in the airgap.** Deps are already vendored in `charts/*.tgz` matching `Chart.lock`; transfer the dir intact and `helm install` directly. (Note `Chart.lock` currently shows untracked in git — confirm it's committed/transferred.)
- **Don't mirror what's disabled:** `kdbai-db-cuvs:1.8.2` (KDB.AI path only), milvus/etcd/pulsar/kafka inside nv-ingest (`milvusDeployed:false`), VLM/VL-embed/parse/ocr, and guardrails are all off by default. Confirm feature scope before mirroring.
- **Docker Hub rate limits** can throttle the mirror job (minio, redis, python base) — authenticate to docker.io.
- **WaitForFirstConsumer + RWO EBS is AZ-pinned.** Recreate-strategy stateful pods (KDB-X, ingestor, MinIO) can't reschedule across AZs; consider single-AZ stateful node groups.
- **NodePort frontend has no stable internal DNS** and won't survive node scaling (min 0) without the explicitly-added internal LB.

## 4. Open questions / decisions for the meeting

1. **Feature scope:** Are observability (kube-prometheus-stack/otel/zipkin, ~10 images), Guardrails (+4 images, +1–3 GPUs), and VLM features (VLM, VL-embed, nemoretriever-parse) in scope? All default off.
2. Do `portal.dl.kx.com/rag-server-kdbx:2.3.4` and `ingestor-server-kdbx:2.3.4` actually exist, or must we build from source? (Determines 2 vs 4 images needing a build pipeline.)
3. **NIM weight airgap strategy:** pre-staged PVC snapshot, NGC offline pre-download bundle, or an internal model registry? Does 120Gi cover the 49B FP8 weights + built TRT-LLM engine?
4. ECR account/region/prefix — same account as EKS? IRSA or node role for pull auth? (We'll pre-write the `<acct>.dkr.ecr.us-west-2.amazonaws.com` overrides before the meeting once known.)
5. EKS control-plane endpoint Private-only or Private+CIDR? How do admins run `kubectl`/`eksctl`/`helm install` from inside the airgap — bastion/SSM in-VPC, or jump host on the corporate network?
6. Internal LB: NLB (L4, simpler) or ALB (L7, needs LB Controller image + IRSA)? Which private hosted zone / internal domain, and who owns Route53?
7. GPU driver ownership: accelerated AMI (verify driver ≥570/580 in this account/region) vs GPU Operator? Cluster Autoscaler/Karpenter in scope given min-0 pools?
8. g5/g6 instance choice for the small-NIM pool — keep g5.2xlarge (A10G 24GB) or move to g6/g6e (L4/L40S) for the 12B VLM? (Changes total G-series vCPU ask.)
9. Storage: should per-NIM caches move to PVCs (~50Gi each) or are node roots sized to absorb them? Backup/DR (snapshots) and CMK encryption required? Single-AZ vs multi-AZ stateful groups?
10. Secrets delivery: sealed secrets vs Secrets Manager + External Secrets (adds a `secretsmanager` endpoint)? Is the corporate firewall truly zero-egress or is there an allowlisted forward proxy (could downgrade some MUST endpoints)?
11. ~~Will the AIRA sister blueprint be co-deployed?~~ **RESOLVED — YES, but the 70B is descoped.** AIRA is co-deployed and **reuses the shared 49B** as its instruct LLM (no separate 70B). Incremental deps = app images only (`aiq-kx-backend`/`aiq-kx-frontend`, phoenix, `kdb-x-mcp-server`, the `aiq-aira` chart) — see §1b.8/§5. Net effect: **no extra LLM, no extra GPU, no new weights**; ~4 extra ECR repos. *(Action: in AIRA's own values, set `nim-llm.enabled: false` and repoint its instruct endpoint to `nim-llm:8000`.)*
12. **nv-ingest runtime-installs `librosa` for audio (field-confirmed — RESOLVED toggle):** gated by `INSTALL_AUDIO_EXTRACTION_DEPS` (hardcoded `"true"` at `values.yaml:1114`) while the Riva audio model is off by default. **Is audio ingestion in scope?** If **no** (default) → set `INSTALL_AUDIO_EXTRACTION_DEPS: "false"` in the overlay → conda egress gone, zero loss. If **yes** → keep it on, pre-bake `librosa` into the image + deploy `riva-nim` (+1 GPU). (See §1b.5a.)

## 5. Rough bill of materials

**Node groups**
| Group | Instance | Count (desired/min/max) | GPUs | Role |
|---|---|---|---|---|
| gpu-llm-g7e | g7e.24xlarge (4× RTX PRO 6000 Blackwell 96GB) | 1 / 0 / 2 | 1 used (FP8 TP1), 3 headroom | rag2 49B LLM (AIRA reuses it) |
| gpu-pool | g5.2xlarge (A10G 24GB) | 9 / 0 / 12 | 1/node | embed, rerank, VLM, nv-ingest extraction (KDB-X GPU uses its own node via `kdbx.gpu.nodeSelector` — not in this pool) |
| cpu-system | t3.xlarge (16 GiB) | 3 / 0 / 4 | 0 | rag-server, ingestor, MinIO, system |

**EBS:** App PVCs ~280Gi (KDB-X 50 + MinIO 50 + ingestor 50 + redis ~8 + LLM cache 120) + node roots ~1,250Gi (g5×9@100 + t3×3@50 + g7e×1@200) = **~1.5 TiB provisioned gp3** (add ~50Gi/NIM if per-NIM caches move to PVCs).

**ECR repos (~26 for the enabled KDB-X + self-host-LLM path + co-deployed AIRA):**
- LLM: `llama-3.3-nemotron-super-49b-v1.5:1.15.5`
- Retrieval NIMs: `llama-nemotron-embed-1b-v2:1.13.0`, `llama-nemotron-rerank-1b-v2:1.10.0`
- nv-ingest extraction: `nemoretriever-parse:1.2`, `paddleocr:1.5.0`, `nemoretriever-page-elements-v2:1.6.0`, `nemoretriever-graphic-elements-v1:1.6.0`, `nemoretriever-table-structure-v1:1.6.0`
- nv-ingest: `nv-ingest:25.9.0`
- KX (BUILT in staging): `kdbx-rag:1.0.0`, `rag-server-kdbx:2.3.4`, `ingestor-server-kdbx:2.3.4`
- Frontend: `rag-frontend:2.3.0`
- Infra: `minio/minio:RELEASE.2025-09-07T16-13-09Z`, `redis:8.2.1`, `python:3.12-slim-bookworm` (build base)
- Platform: ebs-csi-controller, ebs-csi-node, NVIDIA device-plugin, DCGM exporter, (+ GPU Operator driver image if not AMI-baked), (+ autoscaler if used)
- **AIRA (co-deployed, 70B descoped):** `aiq-kx-backend:1.0.2`, `aiq-kx-frontend:1.0.2`, `arizephoenix/phoenix` (pin tag), `kdb-x-mcp-server` (BUILT in staging). **No 70B NIM** — AIRA reuses the shared 49B; no extra GPU or weights.
- *Optional / off by default (not counted):* VLM `nemotron-nano-12b-v2-vl:1.6.0`, VL-embed `embed-vl-1b-v2:1.12.0`, `nemoretriever-ocr-v1:1.1.0`, guardrails (`guardrails:25.09` + 3× `nemoguard-8b-*:1.10.1`), observability (~10), `kdbai-db-cuvs:1.8.2` (KDB.AI path only).

**VPC endpoints (8 MUST + up to 5 SHOULD):**
- MUST: S3 gateway, ecr.api, ecr.dkr, sts, ec2, elasticloadbalancing, EKS control-plane private endpoint, (Private DNS on all interface endpoints).
- SHOULD/NICE: logs, ssm, ssmmessages, ec2messages, autoscaling (+ secretsmanager if Secrets Manager used).
