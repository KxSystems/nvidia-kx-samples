# AI Model Distillation for Financial Data

## Introduction

The AI Model Distillation for Financial Data developer example provides a workflow for creating, evaluating, and deploying high-performance, domain-specific models in financial services. Built with NVIDIA Nemotron, NVIDIA NeMo, and NVIDIA NIM, it enables continuous distillation, fine-tuning, and evaluation on real financial data, maintaining accuracy while reducing compute costs.

![The AI Model Distillation for Financial Data ](./img/findistil_diagram.png)

This notebook demonstrates how to use a data flywheel to distill knowledge from a large teacher model into smaller, more efficient student models for financial news classification. Key steps include generating high-quality labels using a teacher model, processing the data, fine-tuning smaller candidate models, and evaluating their performance to match teacher-level accuracy.

## How it Works

We provide a reusable recipe to experiment and train these distilled models using the [NVIDIA Data Flywheel Blueprint](https://developer.nvidia.com/blog/build-efficient-ai-agents-through-model-distillation-with-nvidias-data-flywheel-blueprint/). At the heart of the blueprint is the flywheel orchestrator, a unified control plane that abstracts the complexity of interacting directly with NVIDIA NeMo microservices. Acting as the brain of the flywheel system, the orchestrator API coordinates the data flywheel job by leveraging a suite of modular [NeMo microservices](https://docs.nvidia.com/nemo/microservices/latest/index.html): 
- NVIDIA NeMo Customizer to handle lightweight LoRA-based fine-tuning
- NVIDIA NeMo Evaluator to automate evaluations across runs
- NeMo Datastore to manage structured datasets and artifacts
- NeMo Deployment Manager to spin up and serve candidate distilled models dynamically for inference

Each microservice is packaged as a Docker container for consistent deployment across different environments. This workflow is orchestrated through Kubernetes integration. It ensures dynamic orchestration of NIM microservices for experimentation and production workloads.

All direct communication with the NeMo Microservices platform (model deployment, evaluation, customization, etc.) is handled by the orchestrator's backend services. This means you do not need to interact with NeMo APIs or infrastructure directly—the orchestrator manages the full workflow for you.

## Notebooks

- [AI Model Distillation for Financial Data](./ai-model-distillation-financial-data.ipynb): Use a teacher model to label financial news headlines and fine-tune smaller models to achieve comparable accuracy for event classification.
- [KDB-X Financial Analytics Demo](./kdbx-financial-analytics-demo.ipynb): Explore KDB-X's financial analytics capabilities — time-series aggregation, trading signal generation, as-of joins, vectorised backtesting, and market data enrichment for training records.

## Prerequisites

### Hardware Requirement

To complete this tutorial, you'll need a system with at least two A100/H100/H200/B200 (80GB) NVIDIA GPUs, which will be used as follows:

- **Fine-tuning:** At least one GPU is required for fine-tuning a model (e.g. `meta/llama-3.2-1b-instruct`, `meta/llama-3.2-3b-instruct` or `meta/llama-3.1-8b-instruct`).
- **Inference:** At least one GPU is required for deploying the corresponding NIM for evaluation.

### Software Requirement

You will deploy the [NVIDIA NeMo Microservices](https://docs.nvidia.com/nemo/microservices/latest/about/index.html) as part of this developer example.

First, please ensure your platform meets the [Requirements](https://docs.nvidia.com/nemo/microservices/latest/get-started/platform-prereq.html#requirements) before proceeding. The notebook uses a script to automate the remaining setup, including the minikube cluster and NeMo microservices deployment.


### Get the AI Model Distillation for Financial Data developer example

1. Clone the blueprint repository:

   ```sh
   git clone git@github.com:NVIDIA-AI-Blueprints/ai-model-distillation-for-financial-data.git

   cd ai-model-distillation-for-financial-data
   ```

2. Install dependencies using [uv](https://docs.astral.sh/uv/getting-started/installation/):

   ```sh
   uv sync --dev
   ```

### Access the Tutorial

1. Launch Jupyter Lab to begin working with the provided tutorial.

   ```bash
   uv run --with jupyter jupyter lab --ip=0.0.0.0
   ```

2. Navigate to the [notebook](#notebooks).
