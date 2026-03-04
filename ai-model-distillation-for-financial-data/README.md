# AI Model Distillation for Financial Data Developer Example

A production-ready developer example demonstrating how to distill large language models into smaller, cost-efficient models for financial workloads using the [NVIDIA Data Flywheel Blueprint](https://developer.nvidia.com/blog/build-efficient-ai-agents-through-model-distillation-with-nvidias-data-flywheel-blueprint/).

Built on NVIDIA NeMo Microservices (25.12.0) and KDB-X, this example shows how to automatically fine-tune and evaluate student models for **financial news classification**, achieving teacher-model accuracy while reducing inference costs by up to 98%.

**The purpose of this Developer Example is two-fold:**

1. To provide a working reference implementation demonstrating how to use the Data Flywheel Blueprint for financial services use cases.
1. To educate the community on practical model distillation techniques: what works, what doesn't, and how to apply these methods to your own domain.

You can get started quickly and achieve similar results using your own infrastructure by following the [Quickstart guide](./docs/02-quickstart.md).


- [Financial Use Case: News Event Classification](#financial-use-case-news-event-classification)
- [What is a Data Flywheel?](#what-is-a-data-flywheel)
- [How to Use This Developer Example](#how-to-use-this-developer-example)
- [Real-World Results: Financial News Classification](#real-world-results-financial-news-classification)
- [Data Used](#data-used)
- [Why KDB-X?](#why-kdb-x)
- [Technical Details](#technical-details)
- [Next Steps](#next-steps)
- [Contributing](#contributing)
- [License](#license)
- [Disclaimer](#disclaimer)


## Financial Use Case: News Event Classification

Demonstrates model distillation on financial news headlines classification (13 event categories: market movements, earnings, regulatory changes, etc.).

**The Workflow:**
- Teacher: Generate labeled data using Llama 3.3 Nemotron Super 49B (or Llama 3.3 70B).
- Enrich: Augment training records with point-in-time market data (OHLCV, bid/ask) via KDB-X as-of joins — see [How Market Data Enriches Student Model Training](./docs/08-workflow-orchestration.md#how-market-data-enriches-student-model-training).
- Distill: Transfer knowledge to smaller models (Llama 3.2 1B/3B, Llama 3.1 8B).
- Evaluate: Use F1-score metrics to measure classification accuracy.
- Backtest: Validate that distilled models produce profitable trading signals.
- Deploy: Serve cost-efficient models matching teacher performance.

## What is a Data Flywheel?

> **Note:** Built on the [NVIDIA Data Flywheel Blueprint](https://developer.nvidia.com/blog/build-efficient-ai-agents-through-model-distillation-with-nvidias-data-flywheel-blueprint/). Code adapted for financial services with F1-score evaluation and financial backtesting.

A data flywheel uses production data (LLM logs, feedback, labels) to reduce latency and cost of GenAI systems:

```mermaid
flowchart TD
  app[Your App] --prompts/responses/feedback--> logs[Log service]
  logs --Create Datasets--> orch["Orchestrator"]
  orch --> exp1["Exp #1"]
  orch --> exp2["Exp #2"]
  orch --> expN["Exp #N"]
  exp1 --> results
  exp2 --> results
  expN --> results
```

Production traffic flows to a centralized logging service. From there, evaluation and fine-tuning datasets are created for offline experiments. Key decisions include model selection, dataset curation, fine-tuning techniques, and evaluation metrics.

### Where the NeMo Microservices Come In

NeMo Microservices provides programmatic control of datasets, fine-tuning, evaluation, and inference. Automates experiment exploration with sensible defaults, surfacing promising candidates for further analysis.

```mermaid
flowchart TD

app["Your application"] --Prompt/completion logs--> kdbx["KDB-X"]
kdbx --Datasets--> datasets["NeMo Datastore"]
datasets --"Fine-tuning datasets"--> customizer["NeMo Customizer"]
datasets --"Eval datasets"--> evaluator["NeMo Evaluator"]

subgraph NIMs["Loop across ALL NIMs"]
  customizer --"Customized model"--> NIM
  evaluator --> NIM
  NIM --> evaluator
end

evaluator --> results["Flywheel Results"]
kdbx --"Market ticks"--> backtest["Financial Backtest"]
backtest --> results
```

Automated process using NeMo microservices:

1. Ingest: Pull data from KDB-X log store and de-duplicate by task.
2. Curate: Create eval/fine-tuning datasets using stratified splitting for balanced representation.
3. Store: Manage datasets in NeMo Datastore.
4. Train: Launch fine-tuning jobs (NeMo Customizer using LoRA).
5. Score: Run F1-score evaluations (NeMo Evaluator).
6. Backtest: Validate trading signal quality via financial backtesting (Sharpe ratio, max drawdown, win rate).

## How to Use This Developer Example

This implementation uses an effective approach: routing production traffic to fine-tuning, using teacher model responses as ground truth, with no manual labeling required. This works well for classification tasks, structured outputs, and domain-specific workflows with consistent patterns, but may not suit open-ended creative generation or highly regulated outputs requiring human review.

**To get started:** Follow the [Quickstart Guide](./docs/02-quickstart.md) to deploy with the provided financial news dataset and see the workflow in action.

**To adapt for your use case:** Learn how to instrument your application and prepare your data by reading the [Data Logging Guide](./docs/data-logging.md). This covers the required log schema, application instrumentation examples, and data preparation steps.

### Real-World Results: Financial News Classification

Results from financial news headlines dataset with 13 event categories:

| Dataset Size | Model | Base F1-Score | Customized F1-Score |
|--------------|-------|---------------|---------------------|
| 5K samples | Llama 3.2 1B | 0.36 | 0.85 |
| 10K samples | Llama 3.2 1B | 0.34 | 0.89 |
| 25K samples | Llama 3.2 1B | 0.32 | 0.95 |
| 25K samples | Llama 3.2 3B | 0.72 | 0.95 |

**Key Findings:**
- Fine-tuned 1B models achieve 0.95+ F1-score, matching 70B teacher model performance
- Approximately 98% inference cost reduction by replacing 70B with fine-tuned 1B models
- Performance improves with more training data (flywheel effect)
- Beyond NLP accuracy, the system validates whether distilled models produce profitable trading signals — see [Financial Backtesting](./docs/financial-backtesting.md)
- Similar cost reductions observed in NVIDIA internal testing (HR chatbot: 98.6% reduction, Qwen-2.5-32b replacing Llama-3.1-70b: 50%+ reduction)

> Techniques demonstrated here apply to other financial workloads: document analysis, compliance checking, trade analysis, customer support.

## Data Used

The blueprint ships with **synthetic seed data** for pipeline validation. No real financial data is included in the repository.

### Included Seed Data

| KDB-X Table | Records | Description |
|-------------|---------|-------------|
| `flywheel_logs` | 200 | Financial Q&A pairs (e.g. "What are the key factors in ESG investing?") with templated LLM responses. Used as training/evaluation input for the distillation pipeline. |
| `market_ticks` | 100 | Synthetic OHLCV price bars for equities (AAPL, MSFT, etc.) — open, high, low, close, volume, VWAP, trade count. Source marked as `"synthetic"`. |
| `signals` | 40 | Synthetic BUY/SELL trading signals with confidence scores and zero realized PnL. Used to validate the backtesting pipeline. |

### How Real Data Flows In

In production, the blueprint is designed to be populated from three sources:

1. **Production LLM traffic** — Your application logs user queries and model responses to `flywheel_logs` via the `POST /api/jobs` endpoint. These become training data for distillation.
2. **Market data feeds** — Real OHLCV ticks ingested into `market_ticks` from providers (e.g. Alpaca, Polygon, Bloomberg). Used for training pair enrichment via asof joins.
3. **Model-generated signals** — BUY/SELL predictions from deployed models tracked in `signals`, enabling financial backtesting (Sharpe ratio, max drawdown, win rate) to validate whether distilled models produce profitable outputs.

The synthetic data lets you run the full pipeline end-to-end (data prep, NIM deployment, base evaluation, LoRA fine-tuning, customized evaluation, backtesting) without any external data dependencies.

## Why KDB-X?

This blueprint uses [KDB-X](https://kx.com/products/kdbx/) as its unified data platform, replacing what would traditionally require three separate systems (document store, vector database, analytics engine).

| Capability | Traditional Stack | This Blueprint |
|-----------|------------------|----------------|
| Log/metadata storage | MongoDB | KDB-X |
| Vector search | Elasticsearch | KDB-X native HNSW |
| Time-series analytics | Separate service | KDB-X (built-in) |
| Financial backtesting | Custom code + pandas | KDB-X q analytics |

**Key benefits:**

- **Single engine** — One database for document storage, vector search (native HNSW via `.ai` module), and time-series analytics. Fewer services to deploy, monitor, and scale.
- **Financial-grade performance** — KDB-X is the industry standard in capital markets. Columnar, in-memory processing handles tick-level data and vector operations in microseconds.
- **Native backtesting** — Sharpe ratio, max drawdown, PnL curves computed server-side in q. No data movement between systems.
- **Market data enrichment** — Training pairs enriched with real-time market context using asof joins (`aj`), a capability unique to time-series databases.
- **Free for commercial use** — KDB-X Community Edition includes the full AI module (HNSW, time-series similarity, anomaly detection) with no license cost.

For the full value analysis, see [KDB-X Value Proposition](./docs/kdbx-value-proposition.md).

## Technical Details

This developer example demonstrates NeMo Microservices capabilities on financial classification tasks, providing a foundation for production-ready model distillation. The system orchestrates multi-stage workflows including dataset creation, model deployment, F1-score evaluation, LoRA fine-tuning, financial backtesting, and automated resource management.

For complete technical architecture, software components, workflow details, and design philosophy, see the [Architecture Overview](./docs/01-architecture.md).

### Architecture

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   FastAPI     │    │  Celery      │    │  Celery      │
│   API Server  │───▶│  Worker      │    │  Parent      │
│   :8000       │    │  (default)   │    │  Worker      │
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │                   │                   │
       ▼                   ▼                   ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   KDB-X      │    │  Redis       │    │  MLflow      │
│   :8082      │    │  :6379       │    │  :5000       │
│  (data +     │    │  (broker)    │    │  (tracking)  │
│   vectors)   │    │              │    │              │
└──────────────┘    └──────────────┘    └──────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
       ┌──────────┐ ┌──────────┐ ┌──────────┐
       │  NeMo    │ │  NeMo    │ │  NeMo    │
       │Customizer│ │Evaluator │ │   NIM    │
       └──────────┘ └──────────┘ └──────────┘
```

### API Endpoints

All endpoints are prefixed with `/api`:

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/jobs` | Start a flywheel distillation run |
| GET | `/api/jobs` | List all jobs |
| GET | `/api/jobs/{id}` | Get job details and results |
| DELETE | `/api/jobs/{id}` | Delete a completed job |
| POST | `/api/jobs/{id}/cancel` | Cancel a running job |
| GET | `/api/data/schema` | Get KDB-X table schemas |
| GET | `/api/data/{table}` | Query table data with filters |
| GET | `/api/data/{table}/count` | Count rows with optional filters |
| POST | `/api/backtest` | Run financial backtesting |
| GET | `/api/market-status` | Get market data status |

### Minimum System Requirements

| Requirement Type | Details |
|-------------------------|---------|
| Minimum GPU | **Self-hosted LLM Judge**: 6x NVIDIA H100 or A100 GPUs<br>**Remote LLM Judge**: 2x NVIDIA H100 or A100 GPUs |
| Cluster | Single-node NVIDIA GPU cluster on Linux with cluster-admin permissions |
| Disk Space | At least 200 GB free |
| Software | Python >= 3.10<br>Docker Engine<br>Docker Compose v2<br>[KDB-X Community Edition license](https://kx.com/kdb-personal-edition-download/) (free, required) |
| Services | KDB-X (data platform + vector search)<br>Redis 7.2 (Celery broker)<br>FastAPI (API server)<br>Celery (task processing) |
| Resource | **Minimum Memory**: 1GB<br>**Storage**: Varies by log volume/model size<br>**Network**: Ports 8000 (API), 8082 (KDB-X), 6379 (Redis) |
| Development | Docker Compose for local dev with hot reloading<br>Supports macOS (Darwin) and Linux<br>Optional: GPU support for model inference |
| Production | Kubernetes cluster (EKS recommended)<br>[`deploy-eks.sh`](deploy/deploy-eks.sh) for one-command EKS deployment<br>Persistent volume support for data storage |

### KDB-X Tables

The system uses 7 core tables managed via the `kdbx/schema.py` module:

| Table | Purpose |
|-------|---------|
| `flywheel_runs` | Job metadata, status, and results |
| `nims` | NIM deployment state per job |
| `evaluations` | Evaluation scores (base and customized) |
| `customizations` | LoRA fine-tuning job state |
| `llm_judge_runs` | LLM-as-judge deployment tracking |
| `flywheel_logs` | Production LLM request/response logs (training data) |
| `flywheel_embeddings` | Vector embeddings with native HNSW index |

Additional analytics tables: `market_ticks`, `signals`, `backtest_results`, `order_book`.

### Security and Compliance for Financial Services

When deploying this example in financial services production environments, consider:

- **Data Privacy**: The reference implementation logs raw production traffic. For financial data, implement PII redaction and data governance controls before production use.
- **Model Validation**: F1-scores measure statistical similarity, not business correctness. Always validate model outputs against compliance requirements.
- **Audit Trails**: All experiments are logged in MLflow. Implement additional audit logging for regulatory compliance.
- **Access Control**: Secure API endpoints, KDB-X, and MLflow with appropriate authentication and authorization.

### Task Serialization Safeguard

**Why only one Flywheel run at a time?**  When the Flywheel kicks off a run it may need to spin up **multiple NIMs and customization jobs, each of which can claim one or more GPUs**.  The reference implementation does not yet discover the number of free GPUs in the cluster, so it uses a simple guardrail: **all invocations of `run_nim_workflow_dag` are serialized**.

* The task is bound to a dedicated Celery queue (`parent_queue`). In the `docker-compose.yaml` there is a worker dedicated to this queue whose concurrency is set to `1`. There is a second worker bound to the default `celery` queue which can handle running other tasks (e.g. evals) in parallel.
* Inside the task we wait for the full DAG to complete via `async_result.get(...)` before returning.
* The call to create a job (i.e. `POST /api/jobs`) will not block, however. It will return immediately with a Job ID.

This ensures that only **one** Flywheel experiment can allocate GPUs at any given time, preventing accidental overallocation that would lead to failed NIM deployments or customizations.

**Roadmap** – Automatic GPU introspection and smarter scheduling are planned for a future version of the Blueprint so multiple Flywheel runs can execute in parallel when resources permit.

## Next Steps

### Getting Started
1. Follow the [Quickstart Guide](./docs/02-quickstart.md) to run the financial news classification example
2. Review the [Architecture Overview](./docs/01-architecture.md) to understand the system design
3. Check the [Audience Guide](./docs/04-audience-guide.md) for role-specific guidance

### Documentation & Resources
- **Complete Documentation**: [Documentation Guide](./docs/readme.md) for role-based navigation and comprehensive documentation index
- **Configuration**: [Configuration Guide](./docs/03-configuration.md) for environment variables, model integration, and evaluation settings
- **Integration**: [Data Logging for AI Apps](./docs/data-logging.md) for instrumenting your application
- **Evaluation**: [Evaluation Types and Metrics](./docs/06-evaluation-types-and-metrics.md) and [Financial Backtesting](./docs/financial-backtesting.md)
- **Market Data Enrichment**: [How Market Data Enriches Student Model Training](./docs/08-workflow-orchestration.md#how-market-data-enriches-student-model-training) — how KDB-X as-of joins add financial context to training data
- **Limitations**: [Limitations & Best Practices](./docs/05-limitations-best-practices.md) before promoting any model
- **Workflows**: [Task Orchestration](./docs/08-workflow-orchestration.md) for debugging and customization
- **API**: [API Reference](./docs/07-api-reference.md) for programmatic access
- **KDB-X**: [KDB-X Architecture](./docs/KDB-X-Architecture.md) and [Value Proposition](./docs/kdbx-value-proposition.md)
- **NeMo**: [NeMo Platform Integration](./docs/09-nemo-platform-integration.md) for advanced features
- **Production**: [Production Deployment Guide](./docs/10-production-deployment.md) and [Helm Installation](./docs/11-helm-installation.md)
- **Model Extraction**: [LoRA Model Extraction](./docs/12-lora-model-extraction.md) for downloading fine-tuned models
- **Troubleshooting**: [FAQ & Troubleshooting](./docs/faq-troubleshooting.md) for common issues and solutions

### External Resources
- [Build Efficient Financial Data Workflows with AI Model Distillation](https://developer.nvidia.com/blog/build-efficient-financial-data-workflows-with-ai-model-distillation)
- [Enhance Your AI Agent with Data Flywheels Using NVIDIA NeMo Microservices](https://developer.nvidia.com/blog/enhance-your-ai-agent-with-data-flywheels-using-nvidia-nemo-microservices/)
- [Nvidia Releases NeMo Microservices To Streamline AI Agent Development](https://www.forbes.com/sites/janakirammsv/2025/04/25/nvidia-releases-nemo-microservices-to-streamline-ai-agent-development/)
- [Overview of NeMo Microservices](https://docs.nvidia.com/nemo/microservices/latest/about/index.html)
- [Enterprises Onboard AI Teammates Faster With NVIDIA NeMo Tools](https://blogs.nvidia.com/blog/nemo-enterprises-ai-teammates-employee-productivity/)
- [DLI Course: The Art of Compressing LLMs](https://learn.nvidia.com/courses/course-detail?course_id=course-v1:DLI+S-FX-24+V1)
- [KDB-X Documentation](https://kx.com/products/kdbx/)

## Available Customizations

The following are some of the customizations you can make after completing the [Quickstart Guide](./docs/02-quickstart.md):

| Category | Description | Available Options |
|----------|-------------|------------------|
| [Environment Variables](docs/03-configuration.md#environment-variables) | Configure system using environment variables | **Required**: NVIDIA_API_KEY, KDB_LICENSE_B64, KDBAI_REGISTRY_TOKEN<br>**Optional**: KDBX_ENDPOINT, REDIS_URL, HF_TOKEN, KDBX_USERNAME, KDBX_PASSWORD<br>**Configuration**: Via .env file or system environment |
| [Model Integration](docs/03-configuration.md#model-integration) | Configure and deploy LLM models | **Supported**: Llama 3.2 1B/3B, Llama 3.1 8B<br>**Context Length**: Up to 32768 tokens<br>**Hardware**: Configurable GPU and PVC settings |
| [Evaluation Settings](docs/03-configuration.md#evaluation-settings) | Configure data splitting and evaluation | **Data Split**: eval_size, val_ratio, min_total_records<br>**Reproducibility**: Optional random seed<br>**Stratification**: Class-aware splitting via scikit-learn |
| [Fine-tuning Options](docs/03-configuration.md#fine-tuning-options) | Customize model training | **Method**: LoRA with configurable parameters<br>**Parameters**: epochs, batch size, learning rate<br>**LoRA Config**: adapter dimension, dropout |
| [Backtest Config](docs/03-configuration.md#backtest-configuration) | Financial signal validation | **Metrics**: Sharpe ratio, max drawdown, win rate<br>**Parameters**: cost_bps, min_signals |
| [Data Infrastructure](docs/03-configuration.md#data-infrastructure) | Configure data storage and processing | **Storage**: KDB-X for logs, metadata, and vector search<br>**Queue**: Redis for task processing<br>**Processing**: Celery workers with configurable concurrency |
| [Deployment Options](docs/03-configuration.md#deployment-options) | Infrastructure configuration | **Development**: Docker Compose with hot reloading<br>**Production**: Kubernetes via [Helm charts](docs/11-helm-installation.md) or [`deploy-eks.sh`](deploy/deploy-eks.sh) for AWS EKS |

Refer to the [Configuration Guide](./docs/03-configuration.md) for more information.

## Contributing

1. Install development dependencies:

   ```sh
   uv sync --dev
   ```

   This command installs all dependencies needed to build the container and run the tests.

2. Start required services:

   ```sh
   ./scripts/run.sh
   ```

   This starts KDB-X, Redis, and MLflow via Docker Compose.

3. Run the tests:

   - For unit tests (requires KDB-X from docker compose):

     ```sh
     uv run pytest
     ```

   - For integration tests (with mocked NeMo microservices components):

     ```sh
     uv run pytest -m integration
     ```

4. Clean up after development:

   - Stop all services:

     ```sh
     ./scripts/stop.sh
     ```

   - (Optional) Clear all database volumes:

     ```sh
     ./scripts/clear_all_volumes.sh
     ```

If you modify the API, regenerate the openapi.json with the following command:

```sh
uv run python scripts/generate_openapi.py
```

## License

This NVIDIA AI BLUEPRINT is licensed under the [Apache License, Version 2.0](./LICENSE). This project will download and install additional third-party open source software projects and containers. Review the [license terms of these open source projects](./LICENSE-3rd-party.txt) before use.

The software and materials are governed by the [NVIDIA Software License Agreement](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/) and the [Product-Specific Terms for NVIDIA AI Products](https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-ai-products/), except that models are governed by the AI Foundation Models Community License Agreement (found at [NVIDIA Community Model License](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-community-models-license/)) and the NVIDIA dataset is governed by the [NVIDIA Asset License Agreement](./LICENSE-dataset).

### Additional Information

For Meta/llama-3.1-70b-instruct model the [Llama 3.1 Community License Agreement](https://www.llama.com/llama3_1/license/), for Llama-3.2-1B-Instruct and Llama-3.2-3B-Instruct the [Llama 3.2 Community License Agreement](https://www.llama.com/llama3_2/license/), and for Llama 3.3-70B-Instruct and Llama-3.3-Nemotron-Super-49B-v1 the [Llama 3.3 Community License Agreement](https://www.llama.com/llama3_3/license/). Built with Llama.



## Disclaimer

The AI Model Distillation for Financial Data developer example and Data Flywheel Blueprint are shared as reference and is provided "as is". The security in the production environment is the responsibility of the end users deploying it. When deploying in a production environment, please have security experts review any potential risks and threats; define the trust boundaries, implement logging and monitoring capabilities, secure the communication channels, integrate AuthN & AuthZ with appropriate controls.
