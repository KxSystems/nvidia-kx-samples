# NVIDIA & KX Samples

This repository contains samples that highlight the combination of KX and NVIDIA technologies. The focus is on combining insights from both structured and unstructured data through use-cases like advanced Retrieval-Augmented Generation (RAG).

## Samples

| Sample | Description |
|--------|-------------|
| [KX-nvidia-rag-blueprint](KX-nvidia-rag-blueprint) | **NVIDIA RAG Blueprint with KDB.AI** - Enterprise-ready RAG solution combining NVIDIA NIM microservices with KDB.AI vector database. Features multimodal document ingestion, GPU-accelerated search, React frontend, and multiple deployment options (Docker Compose, Kubernetes, EKS). |
| [KX-AIQ-nvidia-rag-blueprint](KX-AIQ-nvidia-rag-blueprint) | **AI-Q Research Assistant with KDB-X** - Deep research assistant that creates detailed reports using on-premise data and web search. Includes KDB-X financial data integration for real-time and historical time-series analysis. Pre-built Docker images available on KX Portal. |
| [NVIDIA_accelerated_RAG](NVIDIA_accelerated_RAG) | **Accelerated RAG Notebook** - Jupyter notebook demonstrating KDB.AI with NVIDIA NeMo Retriever, RAPIDS cuVS, and NIM LLMs. Shows ingestion and querying of vector embeddings with GPU acceleration. |
| [ai-model-distillation-for-financial-data](ai-model-distillation-for-financial-data) | **AI Model Distillation for Financial Data** - Production-ready developer example demonstrating how to distill large language models into smaller, cost-efficient models for financial workloads using the NVIDIA Data Flywheel Blueprint. Built on NVIDIA NeMo Microservices and KDB-X, it shows how to fine-tune and evaluate student models for financial news classification, achieving teacher-model accuracy while reducing inference costs by up to 98%. |


## NVIDIA AI Software Stack

The samples in this repository leverage the following NVIDIA technologies:

### NVIDIA NIM

**NVIDIA NIM (NVIDIA Inference Microservices)** optimizes and manages AI inference workloads on NVIDIA GPUs. It provides tools and APIs for deploying, managing, and optimizing AI models with high performance, scalable deployment, and enterprise-grade security. Used across all samples for serving LLMs (Llama 3.x family), embedding models, reranking models, and vision-language models.

### NeMo Microservices Platform

**NVIDIA NeMo Microservices** is a platform for building, customizing, and deploying enterprise AI applications. The platform includes several key components used across the samples:

- **NeMo Retriever** — GPU-accelerated retrieval models enabling efficient and accurate information retrieval from large datasets. Includes embedding models (NV-EmbedQA), reranking models, document parsing NIMs (Page Elements, Table Structure, Graphic Elements, OCR), and multimodal embeddings. Used in the [RAG Blueprint](KX-nvidia-rag-blueprint), [AIQ Research Assistant](KX-AIQ-nvidia-rag-blueprint), and [Accelerated RAG](NVIDIA_accelerated_RAG) samples.
- **NeMo Customizer** — Fine-tuning service supporting LoRA (Low-Rank Adaptation), P-tuning, and multi-GPU/multi-node training. Used in the [Accelerated RAG](NVIDIA_accelerated_RAG) and [AI Model Distillation](ai-model-distillation-for-financial-data) samples.
- **NeMo Evaluator** — Model evaluation service for measuring metrics like F1-score across base and customized models. Used in the [AI Model Distillation](ai-model-distillation-for-financial-data) sample.
- **NeMo Datastore** — Dataset management and versioning service. Used in the [AI Model Distillation](ai-model-distillation-for-financial-data) sample.
- **NeMo Guardrails** — Content safety and topic control using NemoGuard NIMs. Used in the [RAG Blueprint](KX-nvidia-rag-blueprint) sample for input/output guardrails.

### NVIDIA RAPIDS, cuVS, RAFT

**NVIDIA RAPIDS** is an open-source framework that accelerates data science and ML workflows using GPUs. Built on CUDA, it provides libraries (cuDF, cuML, cuGraph) for data ingestion, processing, ML, and visualization with a Python API compatible with Pandas, NumPy, and scikit-learn. Used in the [Accelerated RAG](NVIDIA_accelerated_RAG) sample.

**cuVS (CUDA Vector Search)** provides GPU-accelerated vector similarity search algorithms, enabling high-performance nearest neighbor search. Embedded in KDB.AI for GPU-accelerated vector indexing across the RAG samples.

**RAFT (Reusable Accelerated Functions and Tools)** contains CUDA-accelerated algorithms and primitives for ML and information retrieval, forming building blocks for high-performance applications.

### Technology Matrix

| Technology | [RAG Blueprint](KX-nvidia-rag-blueprint) | [AIQ Research Assistant](KX-AIQ-nvidia-rag-blueprint) | [Accelerated RAG](NVIDIA_accelerated_RAG) | [Model Distillation](ai-model-distillation-for-financial-data) |
|------------|:---:|:---:|:---:|:---:|
| NIM | ✓ | ✓ | ✓ | ✓ |
| NeMo Retriever | ✓ | ✓ | ✓ | |
| NeMo Customizer | | | ✓ | ✓ |
| NeMo Evaluator | | | | ✓ |
| NeMo Guardrails | ✓ | | | |
| RAPIDS / cuVS | ✓ | ✓ | ✓ | |

## Setup

Each sample has its own setup instructions in its respective directory:

- [KX-nvidia-rag-blueprint Setup](KX-nvidia-rag-blueprint/docs/change-vectordb-kdbai.md)
- [KX-AIQ-nvidia-rag-blueprint Setup](KX-AIQ-nvidia-rag-blueprint/README.md#aiq-kx-quick-start)
- [NVIDIA_accelerated_RAG Setup](NVIDIA_accelerated_RAG/README.md#setup)
- [AI Model Distillation for Financial Data Setup](ai-model-distillation-for-financial-data/docs/02-quickstart.md)

## Dataset Disclaimer

In this repository, we may make available to you certain datasets for use with the Software. You are not obliged to use such datasets (with the Software or otherwise), but any such use is at your own risk. Any datasets that we may make available to you are provided "as is" and without any warranty, including as to their accuracy or completeness. We accept no liability for any use you may make of such datasets.

## License

See [LICENSE](LICENSE) for details.
