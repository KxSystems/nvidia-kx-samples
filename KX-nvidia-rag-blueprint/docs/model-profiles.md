<!--
  SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->
# Model Profiles for NVIDIA RAG Blueprint

Use the following documentation to learn about model profiles available for [NVIDIA RAG Blueprint](readme.md).

This section provides the recommended model profiles for different hardware configurations. 
You should use these profiles for all deployment methods (Docker Compose, Helm Chart, RAG python library, and NIM Operator).


## Profile Selection Guidelines

- **TensorRT-LLM profiles** (`tensorrt_llm-*`) are recommended for best performance
- For multi-GPU setups, ensure proper GPU allocation by setting `LLM_MS_GPU_ID` environment variable in docker setup.
- Always verify available profiles using the `list-model-profiles` command before deployment



## List Available Profiles

To see all available profiles for your specific hardware configuration, run the following code.

```bash
USERID=$(id -u) docker run --rm --gpus all \
  -v ~/.cache/model-cache:/opt/nim/.cache \
  nvcr.io/nim/nvidia/llama-3.3-nemotron-super-49b-v1.5:1.15.5 \
  list-model-profiles
```

## Hardware-Specific Profiles

The following profiles are optimized for different common GPU configurations:

### 1xH100 NVL
```bash
NIM_MODEL_PROFILE=tensorrt_llm-h100_nvl-fp8-tp1-pp1-throughput-2321:10de-d347471b749e4e6b6e5956bb0f600b6646461c214cadadf6614baf305054a743-1
```

### 1xH100 SXM
```bash
NIM_MODEL_PROFILE=tensorrt_llm-h100-fp8-tp1-pp1-throughput-2330:10de-a5381c1be0b8ee66ad41e7dc7b4e6d2cffaa7a4e37ca05f57898817560b0bd2b-1
```

### 2xA100 SXM
```bash
NIM_MODEL_PROFILE=vllm-bf16-tp2-pp1-32c3b968468aefcfb3ea1db5a16e3dc9d64395f02ef68a06175e8bbdb0038601
```

### 1xRTX PRO 6000
```bash
# Verified via list-model-profiles on a live RTX PRO 6000 Blackwell (NIM 1.15.5, 2026-06-16).
# Equivalent profile ID: 1cafe40d906fd2c1f82cdcb56d141212826ad4521124276ee77611e776f1f04a
NIM_MODEL_PROFILE=tensorrt_llm-rtx6000_blackwell_sv-fp8-tp1-pp1-throughput-pytorch-2bb5:10de-603587f8c487b7440b2a14a89044654ad141f072432604570c5cc8eef48f8bf4-1-true
```

> **KDB-X GPU CAGRA on g7e nodes:** For KDB-X GPU CAGRA deployments on g7e nodes,
> combine this RTX PRO 6000 Blackwell profile for the LLM with the KDB-X CAGRA
> overlay (`deploy/EKS/rag-values-kdbx-cuvs.yaml`). Model selection is
> backend-agnostic — the same NIM models serve regardless of which vector database
> backend is used.

### 2xB200
```bash
NIM_MODEL_PROFILE=tensorrt_llm-b200-fp8-tp2-pp1-throughput-2901:10de-d2ff2bbf26fdabe28afaf754ca8e5615ed337e19d873da15627c209849f51072-2
```



## GPU Memory & Precision (llama-3.3-nemotron-super-49b-v1.5)

The 49B LLM's footprint — and therefore how many GPUs you need — is driven by
the weight **precision**:

| Precision | Weights (~) | 1× RTX PRO 6000 Blackwell (96 GB) | 1× B200 (180 GB) | 2× 80–96 GB |
|-----------|-------------|-----------------------------------|------------------|-------------|
| **bf16**  | ~98 GB | ❌ doesn't fit → needs **TP2** | ✅ fits (TP1) | ✅ TP2 |
| **FP8**   | ~49 GB | ✅ **fits → TP1 (single GPU)** | ✅ fits, large headroom | ✅ TP2 for throughput |
| **NVFP4** *(Blackwell-only)* | ~25 GB | ✅ fits easily | ✅ fits | — |

**bf16 → FP8 lets you collapse a 2-GPU (TP2) deployment to a single GPU (TP1).**
bf16 (~98 GB) does not fit on a 96 GB card, which is why it requires two; FP8
(~49 GB) leaves ~47 GB free on the same card for KV cache — enough for a 32K
context (`NIM_MAX_MODEL_LEN: 32768`) at reasonable concurrency. NVIDIA publishes
an official **calibrated FP8 checkpoint** (`Llama-3_3-Nemotron-Super-49B-v1_5-FP8`),
so the accuracy delta vs bf16 is effectively negligible for grounded RAG.
Benefits of moving bf16→FP8 on Blackwell: frees one GPU, higher tensor-core
throughput, and no cross-GPU tensor-parallel communication overhead.

## Backend & Profiles: NIM 1.x vs 2.0

The profiles above are **NIM 1.x** (the line this blueprint pins; see
[model-inventory.md](model-inventory.md)). Backend support differs by major
version:

- **1.x** — multi-backend. `tensorrt_llm-*` profiles (FP8) for best throughput on
  H100/Blackwell; a `vllm-bf16-tp2` profile for A100. **Blackwell (B200 +
  RTX PRO 6000) fully supported.**
- **2.0** — **vLLM only**; TensorRT-LLM removed, so the `tensorrt_llm-*` profile
  strings above **no longer exist**. The same GPUs still work (including Blackwell
  + TP2), but via vLLM (FP8 or, best on Blackwell, **NVFP4**). On Blackwell, 2.0
  additionally requires `VLLM_ATTENTION_BACKEND=FLASH_ATTN`, and the 49B model
  needs the engine-init workaround `NIM_PASSTHROUGH_ARGS="--disable-custom-all-reduce
  ..."` (the `--disable-custom-all-reduce` part matters specifically for
  multi-GPU / tensor-parallel setups). Re-benchmark before cutting over — on
  Blackwell, vLLM (esp. NVFP4) is competitive with or faster than the old
  TRT-LLM FP8 path.

> [!NOTE]
> GPUs verified for this model: `h100`, `h100_nvl`, `a100`, `b200`,
> `rtx6000_blackwell_sv`. Lower-TP profiles need more memory per device, so some
> GPUs only offer higher-TP (TP4/TP8) profiles. Always confirm with
> `list-model-profiles` against the exact image tag you deploy.



## Related Topics

- [NVIDIA RAG Blueprint Documentation](readme.md)
- [Best Practices for Common Settings](accuracy_perf.md).
- [Deploy with Docker (Self-Hosted Models)](deploy-docker-self-hosted.md)
- [Deploy with Docker (NVIDIA-Hosted Models)](deploy-docker-nvidia-hosted.md)
- [Deploy with Helm](deploy-helm.md)
- [Deploy with Helm and MIG Support](mig-deployment.md)
- [Deploy with NIM Operator](deploy-nim-operator.md)
