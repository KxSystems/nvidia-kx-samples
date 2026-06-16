<h1>NVIDIA RAG Blueprint — KX fork</h1>

> **This fork supports KDB.AI and KDB-X as vector databases.** The upstream NVIDIA RAG Blueprint supports Milvus, Elasticsearch, and KDB.AI as vector stores. This fork (`kxdev/.../kx-nvidia-rag`) specializes the Helm chart for KX vector databases — Milvus and Elasticsearch chart deps and overlays have been removed. Python implementations under `src/nvidia_rag/utils/vdb/{milvus,elasticsearch}/` remain in the codebase (unused at deploy time). The Helm chart deploys either a KDB.AI-backed stack or a KDB-X-backed stack (connecting to a customer-managed bare kdb+ endpoint via IPC).
>
> Also adds: NeMo Guardrails Helm support (orchestrator + content-safety + topic-control NIMs) — not available in upstream's Helm chart, only their docker-compose. See `docs/nemo-guardrails.md`.

Retrieval-Augmented Generation (RAG) combines the reasoning power of large language models (LLMs)
with real-time retrieval from trusted data sources.
It grounds AI responses in enterprise knowledge,
reducing hallucinations and ensuring accuracy, compliance, and freshness.



## Overview

The NVIDIA RAG Blueprint is a reference solution and foundational starting point
for building Retrieval-Augmented Generation (RAG) pipelines with NVIDIA NIM microservices.
It enables enterprises to deliver natural language question answering grounded in their own data,
while meeting governance, latency, and scalability requirements.
Designed to be decomposable and configurable, the blueprint integrates GPU-accelerated components with NeMo Retriever models, Multimodal and Vision Language Models, and guardrailing services,
to provide an enterprise-ready framework.
With a pre-built reference UI, open-source code, and multiple deployment options — including local docker (with and without NVIDIA Hosted endpoints) and Kubernetes —
it serves as a flexible starting point that developers can adapt and extend to their specific needs.



## Key Features

<details>
    <summary>Data Ingestion</summary>
    <ul>
        <li>Multimodal content extraction - Documents with with text, tables, charts, infographics, and audio. For the full list of supported file types, see [NeMo Retriever Extraction Overview](https://docs.nvidia.com/nemo/retriever/latest/extraction/overview/).</li>
        <li>Custom metadata support</li>
    </ul>
</details>
<details>
    <summary>Search and Retrieval</summary>
    <ul>
        <li>Multi-collection searchability</li>
        <li>Hybrid search with dense and sparse search</li>
        <li>Reranking to further improve accuracy</li>
        <li>GPU-accelerated Index creation and search</li>
        <li>KDB.AI vector database with cuVS / CAGRA GPU acceleration; KDB-X (bare kdb+ BYO endpoint) also supports GPU CAGRA via kx.cuvs (set <code>KDBX_USE_CUVS=1</code>)</li>
    </ul>
</details>
<details>
    <summary>Query Processing</summary>
    <ul>
        <li>Query decomposition</li>
        <li>Dynamic filter expression creation</li>
    </ul>
</details>
<details>
    <summary>Generation and Enrichment</summary>
    <ul>
        <li>Opt-in for Multimodal and Vision Language Model Support in the answer generation pipeline.</li>
        <li>Document summarization</li>
        <li>Improve accuracy with optional reflection</li>
        <li>Optional programmable guardrails for content safety</li>
    </ul>
</details>
<details>
    <summary>Evaluation</summary>
    <ul>
        <li>Evaluation scripts (RAGAS framework)</li>
    </ul>
</details>
<details>
    <summary>User Experience</summary>
    <ul>
        <li>Sample user interface</li>
        <li>Multi-turn conversations</li>
        <li>Multi-session support</li>
    </ul>
</details>
<details>
    <summary>Deployment and Operations</summary>
    <ul>
        <li>Docker Compose for local development</li>
        <li>Kubernetes/Helm for production deployments</li>
        <li>Amazon EKS with cloud-hosted NVIDIA AI endpoints</li>
        <li>Telemetry and observability</li>
        <li>Decomposable and customizable</li>
        <li>NIM Operator support</li>
        <li>Python library mode support</li>
        <li>OpenAI-compatible APIs</li>
    </ul>
</details>



## Software Components

The RAG blueprint is built from the following complementary categories of software:


- **NVIDIA NIM microservices** – Deliver the core AI functionality. Large-scale inference (e.g.for example, Nemotron LLM models for response generation), retrieval and reranking models, and specialized extractors for text, tables, charts, and graphics. Optional NIMs extend these capabilities with OCR, content safety, topic control, and multimodal embeddings.

- **The integration and orchestration layer** – Acts as the glue that binds the system into a complete solution.

This modular design ensures efficient query processing, accurate retrieval of information, and easy customization.


### NVIDIA NIM Microservices


- Response Generation (Inference)

    - [NVIDIA NIM llama-3.3-nemotron-super-49b-v1.5](https://build.nvidia.com/nvidia/llama-3_3-nemotron-super-49b-v1_5)

- Retriever and Extraction Models

    - [NVIDIA NIM llama-nemotron-embed-1b-v2](https://build.nvidia.com/nvidia/llama-nemotron-embed-1b-v2)
    - [NVIDIA NIM llama-nemotron-rerank-1b-v2](https://build.nvidia.com/nvidia/llama-nemotron-rerank-1b-v2)
    - [NeMo Retriever Page Elements NIM](https://build.nvidia.com/nvidia/nemoretriever-page-elements-v2)
    - [NeMo Retriever Table Structure NIM](https://build.nvidia.com/nvidia/nemoretriever-table-structure-v1)
    - [NeMo Retriever Graphic Elements NIM](https://build.nvidia.com/nvidia/nemoretriever-graphic-elements-v1)
    - [PaddleOCR NIM](https://build.nvidia.com/baidu/paddleocr)

- Optional NIMs

    - [Llama 3.1 NemoGuard 8B Content Safety NIM](https://build.nvidia.com/nvidia/llama-3_1-nemoguard-8b-content-safety)
    - [Llama 3.1 NemoGuard 8B Topic Control NIM](https://build.nvidia.com/nvidia/llama-3_1-nemoguard-8b-topic-control)
    - [Nemotron-Nano-12b-v2-VL NIM](https://build.nvidia.com/nvidia/nemotron-nano-12b-v2-vl)
    - [NeMo Retriever Parse NIM](https://build.nvidia.com/nvidia/nemoretriever-parse)
    - [NeMo Retriever OCR NIM](https://build.nvidia.com/nvidia/nemoretriever-ocr) (Early Access)
    - [llama-nemotron-embed-vl-1b-v2](https://build.nvidia.com/nvidia/llama-nemotron-embed-vl-1b-v2)


 ### Integration and orchestration layer

- **RAG Orchestrator Server** – Coordinates interactions between the user, retrievers, vector database, and inference models, ensuring multi-turn and context-aware query handling. This is [LangChain](https://www.langchain.com/)-based.

- **Vector Database** – Stores and searches embeddings at scale with high-performance indexing and retrieval.
    - **KDB-X** (**default & recommended**) – **Default vector database for this fork** (CAGRA / cuVS GPU by default). Connects to a customer-managed bare kdb+ endpoint via IPC — point the adapter at it with `APP_VECTORSTORE_URL` (e.g. `http://my-kdbx-host:5000`); the host:port is parsed from that URL. (`KDBX_LISTEN_PORT` is the **server-side** kdb+ listen port, not a client connection setting.) The KDB-X process loads its `.rag.*` server definitions from `kdbx-init.q` at **q startup** (the in-cluster test pod does this automatically via its entrypoint; a customer-managed KDB-X loads it itself — the adapter no longer pushes them on connect). Supports CPU HNSW and GPU CAGRA (via kx.cuvs). See [docs/change-vectordb-kdbx.md](docs/change-vectordb-kdbx.md) for configuration and all `KDBX_*` env vars, and the step-by-step [EKS + KDB-X cuVS (GPU CAGRA) setup runbook](docs/eks-kdbx-cuvs-setup.md) for a full from-scratch EKS deployment.
    - [KDB.AI CuVS](https://kdb.ai/) _(supported alternative)_ – High-performance vector store built on kdb+, with GPU acceleration via NVIDIA cuVS. Select it by layering the KDB.AI overlay (`-f deploy/EKS/rag-values-kdbai.yaml`) — it ships public images and works out of the box.
    - Upstream NVIDIA RAG Blueprint also supports Milvus and Elasticsearch; that support has been removed from this Helm chart (Python implementations remain in the codebase for reference).

- **NeMo Retriever Extraction** – A high-performance ingestion microservice for parsing multimodal content. For more information about the ingestion pipeline, see [NeMo Retriever Extraction Overview](https://docs.nvidia.com/nemo/retriever/latest/extraction/overview/)

- **RAG User Interface (rag-frontend)** – A lightweight user interface that demonstrates end-to-end query, retrieval, and response workflows for developers and end users. For more information, refer to [RAG UI](docs/user-interface.md).




## Technical Diagram

The following image represents the architecture and workflow.

  <p align="center">
  <img src="./docs/assets/arch_diagram.png" width="750">
  </p>


## Workflow

The following is a step-by-step explanation of the workflow from the end-user perspective:

1. **Data Ingestion & Extraction Pipeline** – Multimodal enterprise documents (text, images, tables, charts, infographics, and audio) are ingested.

2. **User Query** – The user interacts with the system through the UI or APIs, submitting a question. An optional NeMo Guardrails module can filter or reshape the query for safety and compliance before it enters the retrieval pipeline.

3. **Query Processing** – The query is processed by the Query Processing service, which may also leverage reflection (an optional LLM step) to improve query understanding or reformulation for better retrieval results.

4. **Retrieval from Enterprise Data** – The processed query is converted into embeddings using NeMo Retriever Embedding and matched against enterprise data stored in a cuVS accelerated Vector Database (CuVS) and associated object store(minIO). Relevant results are identified based on similarity.

5. **Reranking for Precision** – An optional NeMo Retriever Reranker reorders the retrieved passages, ensuring the most relevant chunks are selected to ground the response.

6. **Response Generation** – The selected context is passed into the LLM inference service (e.g., Llama Nemotron models). An optional reflection step can further validate or refine the answer against the retrieved context. Guardrails may also be applied to enforce safety before delivery.

7. **User Response** – The generated, grounded response is sent back to the user interface, often with citations to retrieved documents for transparency.



## Minimum System Requirements

### Hardware Requirements

The blueprint offers two primary modes of deployment. By default, it deploys the referenced NIM microservices locally. Each method lists its minimum required hardware. This will change if the deployment turns on optional configuration settings.

**Docker**
- 2x RTX PRO 6000
- 2x H100
- 3x B200
- 3x A100 SXM

**Kubernetes**
- 8x RTX PRO 6000
- 8x H100-80GB
- 9x B200
- 9x A100-80GB SXM
- 4x H100 (with [Multi-Instance GPU](docs/mig-deployment.md) / [DRA with NIM Operator](docs/deploy-nim-operator.md))

> [!TIP]
> The blueprint allows for use of [NVIDIA cloud-hosted endpoints](#llm-hosting-options), in which case the GPU requirements are significantly reduced — only GPUs for the ingestion NIMs and vector database are needed.

For detailed per-component requirements, see [Minimum System Requirements](docs/support-matrix.md).

### OS Requirements

- Ubuntu 22.04 OS

### Deployment Options

- Docker
- Kubernetes



## Get Started With NVIDIA RAG Blueprint

**KDB-X is the default and recommended vector database for this fork** (GPU CAGRA
via NVIDIA cuVS). For a cloud deployment, follow the step-by-step
[EKS + KDB-X cuVS runbook](docs/eks-kdbx-cuvs-setup.md); for local evaluation or a
self-hosted Kubernetes cluster, see the [KDB-X deployment guide](docs/change-vectordb-kdbx.md)
(covers Docker Compose **and** Helm). KDB.AI with NVIDIA cuVS remains supported as
an alternative (public images, 90-day trial license) — see
[Alternative Vector Databases](#alternative-vector-databases).

### Deployment Options

The first three rows (KDB-X) are the recommended paths; the KDB.AI rows remain supported as an alternative.

| Deployment | Vector Database | LLM | Documentation |
|------------|-----------------|-----|---------------|
| **Amazon EKS — step-by-step (Recommended)** | **KDB-X** cuVS / GPU CAGRA (A10G) | NVIDIA Cloud Endpoints | [Runbook](docs/eks-kdbx-cuvs-setup.md) |
| **Kubernetes/Helm (Recommended)** | **KDB-X** (BYO kdb+ endpoint) | Self-hosted NIM | [Guide](docs/change-vectordb-kdbx.md) |
| **Docker Compose** — local eval | **KDB-X** | Self-hosted NIM or NVIDIA Cloud | [Guide](docs/change-vectordb-kdbx.md#docker-compose-deployment) |
| Docker Compose | KDB.AI with cuVS _(alternative)_ | Self-hosted NIM | [Guide](docs/deploy-docker-self-hosted.md) |
| Docker Compose | KDB.AI with cuVS _(alternative)_ | NVIDIA Cloud Endpoints | [Guide](docs/deploy-docker-nvidia-hosted.md) |
| Kubernetes/Helm | KDB.AI with cuVS _(alternative)_ | Self-hosted NIM | [Guide](docs/deploy-helm.md) |
| Kubernetes with NIM Operator | KDB.AI with cuVS _(alternative)_ | Self-hosted NIM | [Guide](docs/deploy-nim-operator.md) |

> **Sizing — dev vs. production.** The EKS runbook uses a **dev / evaluation**
> GPU sizing (9× g5.2xlarge / A10G + the NGC-hosted LLM) so you can exercise the
> full pipeline cheaply. For **preprod/production**, self-host the LLM and size the
> GPU fleet per [Minimum System Requirements](#minimum-system-requirements)
> (Kubernetes: 8× H100-80GB, 8× RTX PRO 6000 Blackwell, 9× A100-80GB SXM, or 9× B200).

### LLM Hosting Options

The RAG Blueprint supports two options for LLM inference. Choose based on your infrastructure and requirements:

<details>
<summary><b>Option 1: Cloud-Hosted (NVIDIA API Endpoints)</b> – No local GPU required for LLM</summary>

Use NVIDIA's cloud-hosted API endpoints for LLM inference. This is ideal when you want to minimize local GPU requirements or get started quickly.

**Requirements:**
- NVIDIA NGC API key ([get one free](https://ngc.nvidia.com/))
- Internet connectivity to `integrate.api.nvidia.com`

**Configuration:**
```bash
# Set your NGC API key
export NGC_API_KEY="nvapi-your-key-here"
export NVIDIA_API_KEY="${NGC_API_KEY}"

# Configure LLM endpoint (in your .env or values file)
APP_LLM_SERVERURL="https://integrate.api.nvidia.com/v1"
APP_LLM_MODELNAME="nvidia/llama-3.3-nemotron-super-49b-v1.5"
```

**Pros:** No GPU required for LLM, faster setup, always up-to-date models
**Cons:** Requires internet, API usage costs, data leaves your infrastructure

</details>

<details>
<summary><b>Option 2: Self-Hosted (Local NIM Containers)</b> – Full control, air-gapped capable</summary>

Deploy the LLM as a local NIM container for complete control over your infrastructure. This is ideal for air-gapped environments, data privacy requirements, or high-throughput production workloads.

**Requirements:**
- **GPU (for full self-hosted stack):** One of the following configurations:
  - 2x H100
  - 3x B200
  - 3x A100 SXM
  - 2x RTX PRO 6000
  - See [Minimum System Requirements](docs/support-matrix.md) for full details
- **LLM-specific requirements:** Refer to the [NVIDIA NIM LLM Support Matrix](https://docs.nvidia.com/nim/large-language-models/latest/supported-models.html#llama-3-3-nemotron-super-49b-v1-5)
- **Storage:** ~50GB for model weights (cached in `~/.cache/nim`)
- NVIDIA NGC API key (for downloading NIM containers)
- nvidia-container-toolkit installed

**Configuration:**
```bash
# Set your NGC API key
export NGC_API_KEY="nvapi-your-key-here"

# Configure LLM endpoint (points to local container)
APP_LLM_SERVERURL="http://nemollm-inference:8000/v1"
APP_LLM_MODELNAME="nvidia/llama-3.3-nemotron-super-49b-v1.5"

# GPU assignment for LLM (example: GPUs 0 and 1)
LLM_MS_GPU_ID=0,1
```

**Pros:** Data stays local, no per-query costs, works air-gapped, predictable latency
**Cons:** Significant GPU investment, model management overhead

</details>

> [!TIP]
> **Not sure which to choose?** Start with cloud-hosted endpoints to evaluate the blueprint, then migrate to self-hosted when you need production-grade privacy, throughput, or cost optimization.

### Alternative Vector Databases

**KDB-X with cuVS (CAGRA) is the default** — see the [KDB-X configuration guide](docs/change-vectordb-kdbx.md) (all `KDBX_*` env vars) and the step-by-step [EKS + KDB-X cuVS setup runbook](docs/eks-kdbx-cuvs-setup.md). Note a bare KDB-X install needs prep (build the kdbx images, supply a license/bearer, GPU node). To use a different vector database, see:
- [KDB.AI](docs/change-vectordb-kdbai.md) – GPU cuVS vector store with **public images** (works out of the box). Select it with `-f deploy/EKS/rag-values-kdbai.yaml`.
- [Elasticsearch](docs/change-vectordb.md) – Hybrid search with BM25 and vector similarity

Refer to the [full documentation](docs/readme.md) to learn about the following:

- Minimum Requirements
- Deployment Options
- Configuration Settings
- Common Customizations
- Available Notebooks
- Troubleshooting
- Additional Resources

### Utility Scripts

The [scripts/](scripts/) directory contains utilities for testing and interacting with the RAG system:

- **SEC Filings Downloader** – Download 10-K filings from SEC EDGAR for testing with real financial documents
- **Batch Ingestion CLI** – Bulk upload datasets with progress tracking
- **Retriever API CLI** – Query the RAG server from the command line

See [scripts/README.md](scripts/README.md) for usage details.

## Blog Posts

- [NVIDIA NeMo Retriever Delivers Accurate Multimodal PDF Data Extraction 15x Faster](https://developer.nvidia.com/blog/nvidia-nemo-retriever-delivers-accurate-multimodal-pdf-data-extraction-15x-faster/)
- [Finding the Best Chunking Strategy for Accurate AI Responses](https://developer.nvidia.com/blog/finding-the-best-chunking-strategy-for-accurate-ai-responses/)


## Inviting the community to contribute

We're posting these examples on GitHub to support the NVIDIA LLM community and facilitate feedback.
We invite contributions!
To open a GitHub issue or pull request, see the [contributing guidelines](./CONTRIBUTING.md).


## License

This NVIDIA AI BLUEPRINT is licensed under the [Apache License, Version 2.0.](./LICENSE) This project will download and install additional third-party open source software projects and containers. Review [the license terms of these open source projects](./LICENSE-3rd-party.txt) before use.

Use of the models in this blueprint is governed by the [NVIDIA AI Foundation Models Community License](https://docs.nvidia.com/ai-foundation-models-community-license.pdf).

### KX / KDB.AI License

This fork uses a KX vector database — **KDB-X by default**, or KDB.AI — both of which require a valid KX license. Use of KDB.AI specifically requires:

- **KDB.AI License**: A valid license from [KX](https://kx.com). Free trial licenses are available for evaluation (valid for 90 days).
- **KDB.AI Terms of Service**: Use of KDB.AI is governed by the [KX Terms of Service](https://kx.com/terms-of-service/).
- **KDB.AI Documentation**: [KDB.AI Server Setup Guide](https://code.kx.com/kdbai/latest/gettingstarted/kdb-ai-server-setup.html)

To obtain a KDB.AI license, visit [kx.com](https://kx.com) and sign up for access.

KDB-X users bring their own kdb+ license from KX. The open-source adapter has no separate license requirement.


## Terms of Use
This blueprint is governed by the [NVIDIA Agreements | Enterprise Software | NVIDIA Software License Agreement](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/) and the [NVIDIA Agreements | Enterprise Software | Product Specific Terms for AI Product](https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-ai-products/). The models are governed by the [NVIDIA Agreements | Enterprise Software | NVIDIA Community Model License](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-community-models-license/) and the [NVIDIA RAG dataset](./data/multimodal/) which is governed by the [NVIDIA Asset License Agreement](https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/data/LICENSE.DATA).
The following models that are built with Llama are governed by the Llama 3.2 Community License Agreement: nvidia/llama-nemotron-embed-1b-v2 and nvidia/llama-nemotron-rerank-1b-v2 and llama-nemotron-embed-vl-1b-v2.

### KX / KDB.AI Terms

Use of KDB.AI as the vector database is subject to:
- [KX Terms of Service](https://kx.com/terms-of-service/)
- [KX Privacy Policy](https://kx.com/privacy-policy/)
- [KDB.AI License Agreement](https://code.kx.com/kdbai/latest/gettingstarted/kdb-ai-server-setup.html) (provided upon registration)

## Additional Information

The [Llama 3.1 Community License Agreement](https://www.llama.com/llama3_1/license/) for the nemotron-nano-12b-v2-vl, llama-3.1-nemoguard-8b-content-safety and llama-3.1-nemoguard-8b-topic-control models. The [Llama 3.2 Community License Agreement](https://www.llama.com/llama3_2/license/) for the nvidia/llama-nemotron-embed-1b-v2, nvidia/llama-nemotron-rerank-1b-v2 and llama-nemotron-embed-vl-1b-v2 models. The [Llama 3.3 Community License Agreement](https://github.com/meta-llama/llama-models/blob/main/models/llama3_3/LICENSE) for the llama-3.3-nemotron-super-49b-v1.5 models. Built with Llama. Apache 2.0 for NVIDIA Ingest and for the nemoretriever-page-elements-v2, nemoretriever-table-structure-v1, nemoretriever-graphic-elements-v1, paddleocr and nemoretriever-ocr-v1 models.

