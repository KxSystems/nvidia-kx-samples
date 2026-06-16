<!--
  SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->
# Model Inventory for NVIDIA RAG Blueprint

This document is the canonical reference for every model used by this fork of the
[NVIDIA RAG Blueprint](readme.md): what it does, the container image and tag it
ships with, and — for the models this fork upgraded — what it was changed *from*
and *why*.

It exists because the upstream [release notes](release-notes.md) only record the
LLM migration; the embedding, reranking, VLM, and VL-embedding upgrades made on
this fork were not documented anywhere as a before/after.

All versions below reflect `deploy/helm/nvidia-blueprint-rag/values.yaml` at the
time of writing. When you bump a model, update this table in the same change.

---

## Currency status (as of 2026-06-03)

Phase 2 (KDB-X GPU CAGRA) introduced no new NIM models.

Checked against NVIDIA's live catalog and the upstream
[NVIDIA-AI-Blueprints/rag](https://github.com/NVIDIA-AI-Blueprints/rag) `main`
config (the authoritative reference pin):

- **Text embedding, reranking, and VL embedding** — identical to upstream
  (`embed-1b-v2:1.13.0`, `rerank-1b-v2:1.10.0`, `embed-vl-1b-v2:1.12.0`). On the
  current v2 NeMo Retriever generation; **no action needed**.
- **VLM** (`nemotron-nano-12b-v2-vl:1.6.0`) — current Nemotron Nano 2 VL generation.
- **LLM** — pinned to **`1.15.5`** (the latest **1.x** patch) on 2026-05-29, for
  both LLMs (nemotron 49b here + the 70b instruct in AIRA) so they share one
  version and the TensorRT-LLM backend. This is a NIM **container patch**, not a
  model change (same `llama-3.3-nemotron-super-49b-v1.5`). We went past upstream's
  `1.14.0` (newest 1.x) but deliberately stayed on the **1.x line** rather than the
  newer `2.0.x` (see the NIM 1.x vs 2.0 section below). The `nim-llm` Helm subchart
  dependency in `Chart.yaml` remains `1.13.1` (chart ≠ image tag) — bump separately
  only if you re-run `helm dependency update` against a published newer chart.

Newer **alternative** models exist but are intentionally **not** adopted here:
- `llama-embed-nemotron-8b` — newer/larger (8B) text embedder, SOTA multilingual
  MTEB (Oct 2025). Not drop-in: heavier GPU footprint, verify output dims vs the
  2048 used here. Evaluate only if multilingual retrieval quality outweighs cost.
- `llama-nemotron-rerank-vl-1b-v2` — new *multimodal* reranker (a new capability,
  not a replacement for the text reranker above).

---

## Version timeline (previous → current)

Every NIM this fork ships, with the version it started from and what it runs today.
Tags are the container image tags in `values.yaml` / `deploy/EKS/`.

| NIM (role) | Previous (baseline) | **Current (in use)** | Backend / note |
|------------|---------------------|----------------------|----------------|
| **LLM** — generation, rewriter, reflection, summary | `llama-3.3-nemotron-super-49b-v1.5:1.13.1` → `1.14.0` | **`:1.15.5`** | NIM 1.x / TensorRT-LLM; FP8 single-GPU on g7e |
| **Text embedding** | `llama-3.2-nv-embedqa-1b-v2:1.9.0` | **`llama-nemotron-embed-1b-v2:1.13.0`** | renamed to `llama-nemotron-*`; 2048-dim |
| **Reranking** | `llama-3.2-nv-rerankqa-1b-v2:1.7.0` | **`llama-nemotron-rerank-1b-v2:1.10.0`** | renamed family |
| **VLM** — captioning + optional inference | `llama-3.1-nemotron-nano-vl-8b-v1` (8B) | **`nemotron-nano-12b-v2-vl:1.6.0`** | 8B → 12B; was `:1.5.0` |
| **VL embedding** (opt-in) | `llama-3.2-nemoretriever-1b-vlm-embed-v1` (nemo-microservices `1.7.0`) | **`llama-nemotron-embed-vl-1b-v2:1.12.0`** | registry moved to `nim/nvidia`; disabled by default |
| **nv-ingest: page-elements** (YOLOX) | `nemoretriever-page-elements-v2:1.5.0` | **`:1.6.0`** | "NIM for Object Detection" set |
| **nv-ingest: graphic-elements** (YOLOX) | `nemoretriever-graphic-elements-v1:1.5.0` | **`:1.6.0`** | versions together with the set |
| **nv-ingest: table-structure** (YOLOX) | `nemoretriever-table-structure-v1:1.5.0` | **`:1.6.0`** | versions together with the set |
| **nv-ingest: parse** | `nemoretriever-parse:1.2` | **`:1.2`** | unchanged |
| **nv-ingest: OCR** | `nemoretriever-ocr-v1:1.1.0` / `paddleocr:1.5.0` | **same** | unchanged |
| **nv-ingest** (pipeline) | `nv-ingest:25.9.0` | **`:25.9.0`** | bundle versioning (≠ standalone NIM tags) |
| **Guardrails** (off by default) | `llama-3.1-nemoguard-8b-*:1.10.1` | **same** | content-safety / topic-control / jailbreak |
| **AIRA instruct** (sister repo) | `meta/llama-3.3-70b-instruct:1.13.1`* / `2.0.5` | **`:1.15.5`** | *`1.13.1` was an invalid pin; moved to 1.x for parity |

## Roadmap — what's next, and what it would entail (work / risk)

These are **available but deliberately not adopted**. Two distinct kinds of "next":
a **runtime** jump (NIM 2.0 — same model weights, new serving stack) and genuine
**new models** (new weights/capabilities).

| Area | Next version | What it entails | Work | Risk |
|------|-------------|-----------------|------|------|
| **All LLM NIMs** | **NIM 2.0** (`...:2.0.5`) — *runtime*, same `v1.5`/70B weights | vLLM-only redesign; TensorRT-LLM removed; air-gap manifest caching; NVFP4 on Blackwell | Re-benchmark on vLLM, pin new profiles, add `VLLM_ATTENTION_BACKEND=FLASH_ATTN` on Blackwell, migration guide | **High** — FP8 TRT-LLM profiles gone; *documented 49B engine-init crash* needs `NIM_PASSTHROUGH_ARGS --disable-custom-all-reduce`; ahead of upstream (still 1.14.0). See [NIM 1.x vs 2.0](#nim-1x-vs-20--why-the-llm-nims-stay-on-1x-investigated-2026-05-29). |
| **Text embedding** | **`llama-embed-nemotron-8b`** — *new model* | newer, larger (8B) embedder; SOTA multilingual MTEB (Oct 2025) | Bigger GPU footprint; **full corpus re-embed/re-index** if output dims differ from 2048 | **Medium** — not drop-in; only worth it if multilingual retrieval quality outweighs cost + re-index |
| **Reranking** | **`llama-nemotron-rerank-vl-1b-v2`** — *new capability* | multimodal (image+text page) reranker | Wire a multimodal rerank path | **Low** — additive, not a replacement; only useful with visual-document retrieval |
| **nv-ingest extractors** | **`nemoretriever-page-elements-v3`** (`:1.7.0`) — *new model* | newer object-detection generation | Swap tag; re-validate extraction accuracy | **Medium** — detection behavior changes → must re-validate ingestion quality before rollout |
| **nv-ingest pipeline** | newer `nv-ingest` (> `25.9.0`) | bundled extractors move with the release | Bump bundle; re-test pipeline | **Low–Med** — only affects the bundled (onprem-gpu) lineage; coordinate with standalone NIM tags |
| **VLM** | future Nemotron-Nano-VL patch / next gen | newer captioning/VQA quality | Tag bump | **Low** — within the same 12B-v2-VL line |

> [!NOTE]
> "Nemotron v2" is ambiguous — clarify which is meant:
> 1. **NIM 2.0** (the `2.0.x` *container* tags) — the **same** `llama-3.3-nemotron-super-49b-v1.5` weights in a new vLLM runtime. This is what the roadmap row above and the [NIM 1.x vs 2.0](#nim-1x-vs-20--why-the-llm-nims-stay-on-1x-investigated-2026-05-29) section cover.
> 2. A future **Nemotron model v2** (genuinely new weights, not yet released for this 49B) — would be a real model upgrade (quality change, re-eval, possibly new prompt tuning), evaluated like the embed/rerank/page-elements new-model rows.

---

## NIM 1.x vs 2.0 — why the LLM NIMs stay on 1.x (investigated 2026-05-29)

Both LLM NIMs used here have a newer **`2.0.x`** container line on NGC
(`llama-3.3-nemotron-super-49b-v1.5` and `meta/llama-3.3-70b-instruct` both
publish `2.0.5` as `latest`, dated 2026-05-19). **`2.0.x` is NIM 2.0 — a
ground-up runtime redesign, not a routine version bump.** The *model weights are
identical* (`v1.5` / 70B unchanged); only the serving stack changes. We
deliberately stay on the **1.x** line for now. Rationale:

**What NIM 2.0 gains**
- vLLM-native backend (vLLM 0.18.0) exposed as first-class `vllm serve` — any
  vLLM arg can be passed straight through; full tuning control.
- Better **air-gapped** deploys: Model-Free NIM caches the runtime manifest
  locally, so relaunches need no network (relevant to the EKS airgap path).
- Transparent tool-calling/model behavior (no hidden enterprise shims); newer,
  signed, security-patched base.

**What NIM 2.0 costs**
- **TensorRT-LLM is removed** — 2.0 is "one container, one backend" = **vLLM
  only**. The FP8 TensorRT-LLM throughput profiles in
  [model-profiles.md](model-profiles.md) (`tensorrt_llm-*-fp8-tp...`) no longer
  exist; `NIM_MODEL_PROFILE` values from 1.x do not carry over and performance
  must be **re-benchmarked** on vLLM.
- **Documented deploy failure on the 49b model.** NVIDIA's NIM 2.0.x release
  notes list a known issue: *"Llama 3.3 Nemotron Super 49B v1.5 might fail to
  deploy on all GPUs and profiles, returning a `RuntimeError` during engine core
  initialization."* Still present at `2.0.2`. Workaround (env var on the NIM):
  ```
  NIM_PASSTHROUGH_ARGS="--disable-custom-all-reduce --compilation-config '{\"pass_config\": {\"fuse_allreduce_rms\": false}}'"
  ```
- Major-version migration (1.x → 2.0 migration guide); semantics changed.
- Upstream [NVIDIA-AI-Blueprints/rag](https://github.com/NVIDIA-AI-Blueprints/rag)
  `main` still pins the LLM at `1.14.0`, so `2.0.5` is ahead of the reference and
  less battle-tested in this blueprint.

**Latest tags per line** (so a future bump picks the right one):

| Model | Latest **1.x** (in use) | Latest **2.0.x** |
|-------|-------------------------|------------------|
| `llama-3.3-nemotron-super-49b-v1.5` | **`1.15.5`** ✅ | `2.0.5` |
| `meta/llama-3.3-70b-instruct` (AIRA) | **`1.15.5`** ✅ | `2.0.5` |

> [!NOTE]
> Both LLMs are pinned to **`1.15.5`** for parity (same version, same TRT-LLM
> backend, FP8 single-GPU profiles intact). The sister **AIRA** blueprint
> (`aiq-research-assistant`) was briefly on the instruct's `2.0.5` (after a broken
> `1.13.1` pin was corrected) but was moved back to `1.15.5` to drop the NIM 2.0
> requirements — `VLLM_ATTENTION_BACKEND=FLASH_ATTN` and the 70b OOM cap are no
> longer needed on 1.x. Revisit 2.0 only as a deliberate, benchmarked migration.

**Decision:** defer 2.0 adoption. Migrate deliberately later — add the
`NIM_PASSTHROUGH_ARGS` workaround, re-benchmark vLLM profiles, and cut both LLMs
over together — rather than as an in-place tag bump.

---

## Models upgraded on this fork

Four models were upgraded from the older descriptive `llama-3.x` / `nemoretriever`
identifiers to NVIDIA's unified **`llama-nemotron-*`** family (plus the matching
NIM chart and image-registry moves). The default generation LLM was migrated
upstream and is listed in the inherited section below.

| Role | Old model | New model | Image (tag) | Commit | Notes |
|------|-----------|-----------|-------------|--------|-------|
| **Text embedding** | `nvidia/llama-3.2-nv-embedqa-1b-v2` | `nvidia/llama-nemotron-embed-1b-v2` | `nvcr.io/nim/nvidia/llama-nemotron-embed-1b-v2:1.13.0` | `6a20369` (+ subchart rename `b0d08ae`) | Output stays **2048-dim** (`APP_EMBEDDINGS_DIMENSIONS: "2048"` unchanged). Helm subchart key renamed `nvidia-nim-llama-32-nv-embedqa-1b-v2` → `nvidia-nim-llama-nemotron-embed-1b-v2`. |
| **Reranking** | `nvidia/llama-3.2-nv-rerankqa-1b-v2` | `nvidia/llama-nemotron-rerank-1b-v2` | `nvcr.io/nim/nvidia/llama-nemotron-rerank-1b-v2:1.10.0` | `d11bf2d` | NIM chart **1.7.0 → 1.10.0**. Subchart key renamed to `nvidia-nim-llama-nemotron-rerank-1b-v2`. |
| **VLM** (captioning + VLM inference) | `nvidia/llama-3.1-nemotron-nano-vl-8b-v1` | `nvidia/nemotron-nano-12b-v2-vl` | `nvcr.io/nim/nvidia/nemotron-nano-12b-v2-vl:1.6.0` | `2330be2` | **8B → 12B**. Drives both nv-ingest image captioning (`APP_NVINGEST_CAPTIONMODELNAME`) and optional VLM response generation (`APP_VLM_MODELNAME`). |
| **Multimodal (VL) embedding** | `nvidia/llama-3.2-nemoretriever-1b-vlm-embed-v1` | `nvidia/llama-nemotron-embed-vl-1b-v2` | `nvcr.io/nim/nvidia/llama-nemotron-embed-vl-1b-v2:1.12.0` | `593fae5` | NIM chart **1.7.0 → 1.12.0**. Image registry moved `nvcr.io/nvidia/nemo-microservices/…` → `nvcr.io/nim/nvidia/…`; Helm repo moved `nvidia/nemo-microservices` → `nim/nvidia`. The old hosted-API identifier was **past EOL (deprecated 2026-04-24)**. Still **disabled by default** / opt-in via [vlm-embed](vlm-embed.md). |

> [!NOTE]
> The `llama-nemotron-*` rename is an NVIDIA rebrand of the same retrieval-model
> family — not a different architecture. These upgrades track the renames and the
> corresponding NIM chart/image version bumps so the deployment stays on
> supported, non-EOL models.

---

## Models inherited from upstream (not changed by this fork)

These models ship as configured by the upstream blueprint. They are listed here
for completeness so this file is a full inventory.

### Generation / language

| Role | Model | Image (tag) | Source |
|------|-------|-------------|--------|
| **LLM** — generation, query rewriter, filter-expression generator, reflection, summarization | `nvidia/llama-3.3-nemotron-super-49b-v1.5` | `nvcr.io/nim/nvidia/llama-3.3-nemotron-super-49b-v1.5:1.15.5` | Migrated **upstream** (see [release notes](release-notes.md)); ~1×H100 / 2×A100 to self-host. In the EKS/KDB-X overlays it is **cloud-hosted** via `https://integrate.api.nvidia.com`, not run on-cluster. |

### Guardrails (NeMo Guardrails — disabled by default)

| Role | Model | Image (tag) |
|------|-------|-------------|
| Content safety | `llama-3.1-nemoguard-8b-content-safety` | `nvcr.io/nim/nvidia/llama-3.1-nemoguard-8b-content-safety:1.10.1` |
| Topic control | `llama-3.1-nemoguard-8b-topic-control` | `nvcr.io/nim/nvidia/llama-3.1-nemoguard-8b-topic-control:1.10.1` |
| Jailbreak detection | `llama-3.1-nemoguard-8b-jailbreak-detect` | `nvcr.io/nim/nvidia/llama-3.1-nemoguard-8b-jailbreak-detect:1.10.1` |

### nv-ingest extraction pipeline

| Role | Model | Image (tag) |
|------|-------|-------------|
| PDF / document parse | `nvidia/nemoretriever-parse` | `nvcr.io/nim/nvidia/nemoretriever-parse:1.2` |
| OCR (NeMo Retriever) | `nemoretriever-ocr-v1` | `nvcr.io/nvidia/nemo-microservices/nemoretriever-ocr-v1:1.1.0` |
| OCR (PaddleOCR, alt) | `paddleocr` | `nvcr.io/nim/baidu/paddleocr:1.5.0` |
| Page elements (YOLOX) | `nemoretriever-page-elements-v2` | `nvcr.io/nim/nvidia/nemoretriever-page-elements-v2:1.6.0` |
| Graphic elements (YOLOX) | `nemoretriever-graphic-elements-v1` | `nvcr.io/nim/nvidia/nemoretriever-graphic-elements-v1:1.6.0` |
| Table structure (YOLOX) | `nemoretriever-table-structure-v1` | `nvcr.io/nim/nvidia/nemoretriever-table-structure-v1:1.6.0` |

---

## How to change a model

To swap the LLM or embedding model for your own deployment, see
[Change the LLM or Embedding Model](change-model.md). For hardware-specific NIM
profiles, see [Model Profiles](model-profiles.md). For the supported-model links
and minimum system requirements, see the [Support Matrix](support-matrix.md).

## Related documentation

- [Support Matrix](support-matrix.md)
- [Release Notes](release-notes.md)
- [Model Profiles for Hardware Configurations](model-profiles.md)
- [Change the LLM or Embedding Model](change-model.md)
- [Vision Language Model for Generation](vlm.md) · [VLM Embedding](vlm-embed.md)
