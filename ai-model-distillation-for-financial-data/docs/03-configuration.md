# Configuration Guide

Learn how to configure the AI Model Distillation for Financial Data developer example using this guide. It covers all available configuration options, their impacts, and recommended settings.

- [Configuration Guide](#configuration-guide)
  - [Prerequisites](#prerequisites)
    - [System Requirements](#system-requirements)
    - [Required API Keys and Access](#required-api-keys-and-access)
      - [NGC API Key](#ngc-api-key)
      - [NVIDIA API Key (for Remote Configurations)](#nvidia-api-key-for-remote-configurations)
      - [Hugging Face Token](#hugging-face-token)
  - [Before You Start](#before-you-start)
  - [Configuration File Location](#configuration-file-location)
  - [Environment Variables](#environment-variables)
    - [Required Environment Variables](#required-environment-variables)
    - [Optional Environment Variables](#optional-environment-variables)
    - [Environment Setup Examples](#environment-setup-examples)
  - [NeMo microservices Configuration](#nemo-microservices-configuration)
  - [Logging Configuration](#logging-configuration)
  - [MLflow Configuration](#mlflow-configuration)
    - [Enabling MLflow](#enabling-mlflow)
  - [Model Integration](#model-integration)
    - [Supported Models](#supported-models)
  - [Evaluation Settings](#evaluation-settings)
    - [Data Split Configuration](#data-split-configuration)
      - [Stratified Splitting Behavior](#stratified-splitting-behavior)
      - [Graceful Degradation](#graceful-degradation)
      - [Splitting Process Visualization](#splitting-process-visualization)
      - [Examples](#examples)
      - [Configuration Recommendations by Use Case](#configuration-recommendations-by-use-case)
    - [ICL (In-Context Learning) Configuration](#icl-in-context-learning-configuration)
      - [Example Selection Options](#example-selection-options)
      - [Similarity Configuration](#similarity-configuration)
      - [Embedding NIM Configuration](#embedding-nim-configuration)
  - [Fine-tuning Options](#fine-tuning-options)
    - [Training Configuration](#training-configuration)
    - [LoRA Configuration](#lora-configuration)
  - [Model Customization](#model-customization)
    - [Overview](#overview)
    - [Configuration Structure](#configuration-structure)
    - [Target Models](#target-models)
    - [Customization Parameters](#customization-parameters)
    - [Training Integration](#training-integration)
    - [Example Configurations](#example-configurations)
    - [Best Practices](#best-practices)
  - [Enrichment Configuration](#enrichment-configuration)
  - [Backtest Configuration](#backtest-configuration)
  - [Data Infrastructure](#data-infrastructure)
    - [Storage Services](#storage-services)
    - [Processing Configuration](#processing-configuration)
  - [Deployment Options](#deployment-options)
    - [Development Environment](#development-environment)
    - [Production Deployment Options](#production-deployment-options)
      - [Docker Compose (Simple Production)](#docker-compose-simple-production)
      - [Kubernetes with Helm (Enterprise Production)](#kubernetes-with-helm-enterprise-production)
    - [Resource Configuration](#resource-configuration)

## Prerequisites

### System Requirements

| Requirement Type | Details |
|-------------------------|---------|
| **Minimum GPU** | 2× (NVIDIA A100/H100/H200/B200 GPUs) |
| **Cluster** | Single-node NVIDIA GPU cluster on Linux with cluster-admin permissions |
| **Disk Space** | At least 200 GB free |
| **Software** | Python 3.12<br>Docker Engine<br>Docker Compose v2 |
| **Services** | KDB-X<br>Redis 7.2<br>FastAPI (API server)<br>Celery (task processing)<br>MLflow 2.22.0<br>Wandb 0.22.3 |
| **Resource** | **Minimum Memory**: 1 GB<br>**Storage**: Varies by log volume or model size<br>**Network**: Ports 8000 (API), 8082 (KDB-X), 6379 (Redis) |
| **Development** | Docker Compose for local development with hot reloading<br>Supports macOS (Darwin) and Linux<br>Optional: GPU support for model inference |
| **Production** | Kubernetes cluster (recommended)<br>Resources scale with workload<br>Persistent volume support for data storage |

### Required API Keys and Access

#### NGC API Key
You must [generate a personal API key](https://org.ngc.nvidia.com/setup/api-keys) with the `NGC catalog` and `Public API Endpoints` services selected. This enables:

- Complete deployment of NMP (NeMo Microservices Platform)
- Access NIM services
- Access models hosted in the NVIDIA API Catalog
- Download models on-premises

For detailed steps, see the official [NGC Private Registry User Guide](https://docs.nvidia.com/ngc/gpu-cloud/ngc-private-registry-user-guide/index.html#generating-personal-api-key).

#### NVIDIA API Key (for Remote Configurations)
Generate an API key at [build.nvidia.com](https://build.nvidia.com) for accessing:
- Remote model inference using NVIDIA Inference Microservice (NIM)

#### Hugging Face Token
Create a token at [Hugging Face Settings](https://huggingface.co/settings/tokens) with read access for model downloads and data uploading functionality.

## Before You Start

- Run the [Quickstart](./02-quickstart.md) to tour the functionality and default settings of the developer example.
- Run the [Notebooks](../notebooks/README.md) to understand how the developer example supports different use cases.

> **Important**
>
> Advanced configuration such as large-scale hyper-parameter sweeps, architecture search, or custom evaluation metrics must run directly in **NeMo microservices**. The configurations in this guide are only for the developer example itself.

> **Note**
> 
> For detailed NeMo microservices API documentation, refer to the [official documentation](https://docs.nvidia.com/nemo/microservices/latest/api/index.html).

## Configuration File Location

The developer example uses a YAML-based configuration system. The primary configuration file is located at:

```bash
config/config.yaml
```

## Environment Variables

The developer example relies on several environment variables for configuration. These can be set in a `.env` file in the project root or as system environment variables.

### Required Environment Variables

| Variable | Description | Usage | Example |
|----------|-------------|-------|---------|
| `NGC_API_KEY` | API key for NVIDIA Cloud Foundation | NGC login and container downloads only | `nvapi-...` |
| `NVIDIA_API_KEY` | API key for NVIDIA API Catalog | Remote NIM access, remote model inference | `nvapi-...` |
| `HF_TOKEN` | Hugging Face authentication token | Data uploading functionality, model access | `hf_...` |

### Optional Environment Variables

| Variable | Description | Default | Usage |
|----------|-------------|---------|-------|
| `KDBX_ENDPOINT` | KDB-X connection endpoint (`host:port`) | `"localhost:8082"` | Database connection |
| `KDBX_MODE` | KDB-X connection mode | `"ipc"` | `"ipc"` (remote) or `"embedded"` (localhost default) |
| `KDBX_USERNAME` | KDB-X authentication username | `""` | Optional; omit for unauthenticated connections |
| `KDBX_PASSWORD` | KDB-X authentication password | `""` | Required when `KDBX_USERNAME` is set |
| `EMB_API_KEY` | API key for remote embedding services | Uses `NVIDIA_API_KEY` | Override default API key for remote embeddings (supports any provider) |
| `REDIS_URL` | Redis connection URL | `"redis://localhost:6379/0"` | Task broker and results backend |

### Environment Setup Examples

**Development Setup:**
```bash
# Required for NGC login and container downloads
export NGC_API_KEY="your-ngc-api-key"

# Required for remote configurations
export NVIDIA_API_KEY="your-nvidia-api-key"
export HF_TOKEN="your-huggingface-token"

# Optional (defaults work for development)
export KDBX_ENDPOINT="localhost:8082"
export KDBX_MODE="embedded"  # allows localhost default when KDBX_ENDPOINT is unset
```

**Production Setup:**
```bash
# Required for NGC login and container downloads
export NGC_API_KEY="your-ngc-api-key"

# Required for remote configurations
export NVIDIA_API_KEY="your-nvidia-api-key"
export HF_TOKEN="your-huggingface-token"

# Production URLs
export KDBX_ENDPOINT="kdbx.production:8082"
export KDBX_USERNAME="admin"
export KDBX_PASSWORD="your-kdbx-password"
export REDIS_URL="redis://redis.production:6379/0"
```

**EKS / Kubernetes Deployment** (additional variables):
```bash
# Base64-encoded KDB-X license file (mounted into the KDB-X pod)
export KDB_LICENSE_B64="$(base64 -w0 < /path/to/kc.lic)"

# KDB.AI / KDB-X container registry token (image pull secret)
export KDBAI_REGISTRY_TOKEN="your-registry-token"
```

**For full functionality, at minimum configure:**
```bash
export NGC_API_KEY="your-ngc-api-key"
export NVIDIA_API_KEY="your-nvidia-api-key"
export HF_TOKEN="your-huggingface-token"
```


## NeMo microservices Configuration

The `nmp_config` section controls the NeMo Microservices Platform (NMP) integration:

```yaml
nmp_config:
  nemo_base_url: "http://nemo.test"
  nim_base_url: "http://nim.test"
  datastore_base_url: "http://data-store.test"
  nmp_namespace: "dfwbp"
```

| Option | Description | Default |
|--------|-------------|---------|
| `nemo_base_url` | Base URL for NeMo services | `http://nemo.test` |
| `nim_base_url` | Base URL for NIM services | `http://nim.test` |
| `datastore_base_url` | Base URL for datastore services | `http://data-store.test` |
| `nmp_namespace` | Namespace for NMP resources | "dfwbp" |

## Logging Configuration

The `logging_config` section controls the verbosity of log output across all services:

```yaml
logging_config:
  level: "INFO"  # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
```

| Option | Description | Default | Notes |
|--------|-------------|---------|-------|
| `level` | Log verbosity level | "INFO" | Controls detail level of application logs |

The `logging_config` section configures logging level. Available options:

- `CRITICAL`: Only critical errors
- `ERROR`: Error events 
- `WARNING`: Warning messages
- `INFO`: Informational messages (default)
- `DEBUG`: Detailed diagnostic information

## MLflow Configuration

The `mlflow_config` section controls MLflow integration for experiment tracking and model management. MLflow is controlled via the `COMPOSE_PROFILES` environment variable:

```yaml
mlflow_config:
  # enabled: automatically set based on COMPOSE_PROFILES environment variable
  tracking_uri: "http://0.0.0.0:5000"
  experiment_name_prefix: "data-flywheel"
  artifact_location: "./mlruns"
```

| Option | Description | Default | Notes |
|--------|-------------|---------|-------|
| `enabled` | Enable MLflow integration | Automatically set | Determined by checking if "mlflow" is in `COMPOSE_PROFILES` |
| `tracking_uri` | MLflow tracking server URI | "http://0.0.0.0:5000" | URL of the MLflow tracking server |
| `experiment_name_prefix` | Prefix for experiment names | "data-flywheel" | Used to organize experiments |
| `artifact_location` | Location for MLflow artifacts | "./mlruns" | Directory for storing model artifacts |

### Enabling MLflow

To enable MLflow, set the `COMPOSE_PROFILES` environment variable to include "mlflow":

```bash
export COMPOSE_PROFILES=mlflow
docker compose -f deploy/docker-compose.yaml up -d --build
```

Or run it directly:

```bash
COMPOSE_PROFILES=mlflow docker compose -f deploy/docker-compose.yaml up -d --build
```

> **Note:**
> - The MLflow service only starts when the "mlflow" profile is enabled via `COMPOSE_PROFILES`
> - The `enabled` field in the configuration is automatically set based on the presence of "mlflow" in `COMPOSE_PROFILES`
> - When enabled, MLflow will be available at `http://localhost:5000`

## Model Integration

The `nims` section configures which models to deploy and their settings:

**Default Behavior**: When a model is listed in the `nims` section, it will automatically run base evaluation by default.

**Customization Control**: Use the `customization_enabled` key to control whether the model can be fine-tuned. When enabled, the model will also run customization and evaluation on customized model using the settings defined in `customizer_configs`.

```yaml
nims:
  - model_name: "meta/llama-3.2-1b-instruct"
    model_type: "llm"
    context_length: 8192
    gpus: 1
    pvc_size: 25Gi
    tag: "1.8.3"
    customization_enabled: true
    customizer_configs:
      target: "meta/llama-3.2-1b-instruct@2.0"
      gpus: 1
      max_seq_length: 8192
```

| Option | Description | Required | Example |
|--------|-------------|----------|---------|
| `model_name` | Name of the model to deploy | Yes | "meta/llama-3.2-1b-instruct" |
| `model_type` | Type of NIM | No | "llm" |
| `context_length` | Maximum context length in tokens | Yes | 8192 |
| `gpus` | Number of GPUs to allocate | Yes | 1 |
| `pvc_size` | Persistent volume claim size | No | "25Gi" |
| `tag` | Model version tag | Yes | "1.8.3" |
| `customization_enabled` | Whether model can be fine-tuned | No | true |

> **📖 For detailed customization configuration options:** See [Model Customization](#model-customization)

> **Note:**
> All NIMs listed in your configuration will appear in the job response with a status of `"Pending"` as soon as a job starts, even if NIMs are executed one after another. This ensures users have a transparent view of all planned model evaluations for the job. Each NIM's status will update (e.g., to `Running`, `Completed`, or `Error`) as the job progresses.

### Supported Models

Currently supported models include:

Student models:

- Meta Llama 3.1 1B Instruct
- Meta Llama 3.2 3B Instruct
- Meta Llama 3.2 8B Instruct

Teacher models:

- Meta Llama 3.3 Nemotron Super 49b v1
- Meta Llama 3.3 70B Instruct

Note: Not all models may be enabled by default in the configuration. Enable them by uncommenting and configuring the appropriate sections in `config/config.yaml`.

## Evaluation Settings

The `data_split_config` and `icl_config` sections control evaluation processes:

### Data Split Configuration

The developer example uses **class-aware stratified splitting** powered by scikit-learn to ensure balanced representation of different tool types across your evaluation, training, and validation datasets.

```yaml
data_split_config:
  eval_size: 100
  val_ratio: 0.1
  min_total_records: 50
  random_seed: null
  limit: 10000
  parse_function_arguments: true
```

| Option | Description | Default | Notes |
|--------|-------------|---------|-------|
| `eval_size` | Number of examples for evaluation | 100 | Minimum size of evaluation set (stratified across tool types) |
| `val_ratio` | Ratio of data used for validation | 0.1 | Must be ≥ 0 and < 1 (10% of remaining data after eval, stratified) |
| `min_total_records` | Minimum required records | 50 | Total dataset size requirement |
| `random_seed` | Seed for reproducible splits | null | Set for reproducible results |
| `limit` | Limit for evaluator | 10000 | Set for evaluator config limit |
| `parse_function_arguments` | Parse function arguments to JSON | true | Data validation: converts string function arguments to JSON objects |

#### Stratified Splitting Behavior

It automatically analyzes your data to identify different classes (tool types) and ensures balanced representation across splits:

**1. Class Detection**: Records are classified by their tool usage using the `get_tool_name()` function.

**2. Splitting Strategy**:
- **Frequent classes**: Tool types with multiple records are split using stratified sampling
- **Rare classes**: Tool types with only one record are distributed fairly across splits

**3. Two-Stage Process**:
   - **Stage 1**: Creates evaluation set with stratified sampling from frequent classes
   - **Stage 2**: Splits remaining data into training and validation sets (also stratified when possible)

#### Graceful Degradation

When stratification isn't possible (e.g., insufficient samples per class), the system automatically falls back to random splitting while maintaining the specified split sizes.

#### Splitting Process Visualization

```mermaid
flowchart TD
    A["Input Records"] --> B["Class Detection<br>get_tool_name()"]
    B --> C{"Multiple Classes?"}
    C -->|Yes| D["Stratified Labels<br>Rare classes become 'others'"]
    C -->|No| E["Simple Labels"]
    D --> F["Stage 1: Eval Split<br>stratified sampling"]
    E --> F
    F --> G["Remaining Records"]
    G --> H["Stage 2: Train/Val Split<br>stratified when possible"]
    H --> I["Final Datasets<br>Eval + Train + Val"]
```

#### Examples

**Tool-Calling Dataset (60 records)**:
- `get_weather`: 30 records
- `schedule_meeting`: 20 records  
- `no_tool`: 10 records

**With `eval_size: 6, val_ratio: 0.2`**:
- **Eval**: 6 records (stratified: ~3 weather, ~2 meeting, ~1 no_tool)
- **Train**: 43 records (remaining after eval/val splits)
- **Val**: 11 records (20% of remaining 54 records)

**Single-Class Dataset Fallback**:
When all records use the same tool, stratification automatically falls back to random splitting while preserving split ratios.

#### Configuration Recommendations by Use Case

| Use Case | eval_size | val_ratio | min_total_records | random_seed | Notes |
|----------|-----------|-----------|-------------------|-------------|-------|
| **Development/Testing** | 20 | 0.1 | 50 | 42 | Small, reproducible |
| **Production (Balanced)** | 100 | 0.1 | 200 | null | Standard settings |
| **Production (Imbalanced)** | 50 | 0.15 | 500 | null | Larger validation set |
| **Tool-Heavy Workloads** | 200 | 0.2 | 1000 | null | More eval examples per tool |

> **Related Documentation**
> 
> - **API Usage**: See [Data Split Configuration](07-api-reference.md#data-split-configuration) for API integration
> - **Best Practices**: See [Tuning Guidelines](05-limitations-best-practices.md#tune-data_split_config-as-you-learn-workload-characteristics)
> - **Validation Process**: See [Dataset Validation](dataset-validation.md) for data quality requirements
> - **Implementation Details**: Check `src/lib/flywheel/util.py` for source code
>
> While these values are set in the configuration file, you can override them on a per-job basis by including a `data_split_config` object in the POST request to `/api/jobs`. This gives you the flexibility to use different split configurations for different jobs without modifying the configuration file.
>
> For example, you might want to:
> - Use a larger evaluation set for certain workloads
> - Adjust the validation ratio based on dataset size
> - Set a specific random seed for reproducible results
>
> You can override just the parameters you want to change - any parameters not specified in the POST request will automatically use their default values shown in the table above. For instance, you could override just the `eval_size` while keeping the default values for all other parameters.
>
> See the [Job Operations section](02-quickstart.md#job-operations) in the Quickstart Guide for a complete example.

### ICL (In-Context Learning) Configuration

The ICL configuration supports two example selection methods to optimize few-shot learning performance:

```yaml
icl_config:
  max_context_length: 32768
  reserved_tokens: 4096
  max_examples: 3
  min_examples: 1
  example_selection: "semantic_similarity"  # or "uniform_distribution"
  similarity_config:
    relevance_ratio: 0.7
    embedding_nim_config:
      deployment_type: "remote"
      url: "https://integrate.api.nvidia.com/v1/embeddings"
      model_name: "nvidia/llama-3.2-nv-embedqa-1b-v2"
```

| Option | Description | Default | Notes |
|--------|-------------|---------|-------|
| `max_context_length` | Maximum tokens in context | 32768 | Model dependent |
| `reserved_tokens` | Tokens reserved for system | 4096 | For prompts and metadata |
| `max_examples` | Maximum ICL examples | 3 | Upper limit per context |
| `min_examples` | Minimum ICL examples | 1 | Lower limit per context |
| `example_selection` | ICL selection method | "semantic_similarity" | See [Example Selection Options](#example-selection-options) |
| `similarity_config` | Similarity configuration | Required for semantic_similarity | Required for `semantic_similarity` selection |

#### Example Selection Options

The developer example supports two methods for selecting in-context learning examples:

**1. Uniform Distribution** (`uniform_distribution`)
- **Description**: Distributes examples evenly across different tool types
- **Use Case**: Provides balanced representation of all available tools
- **Behavior**: For tool-calling workloads, ensures each tool gets roughly equal representation in the ICL examples
- **Requirements**: No additional configuration needed

**2. Semantic Similarity** (`semantic_similarity`)
- **Description**: Selects examples based on semantic similarity using vector embeddings
- **Use Case**: Finds the most relevant examples for each evaluation query
- **Behavior**: Uses an embedding model to identify semantically similar examples from historical data stored in KDB-X
- **Requirements**: Requires `similarity_config` to be configured

#### Similarity Configuration

When using `semantic_similarity`, you must configure the `similarity_config` section:

```yaml
icl_config:
  example_selection: "semantic_similarity"
  similarity_config:
    relevance_ratio: 0.7
    embedding_nim_config:
      deployment_type: "remote"
      url: "https://integrate.api.nvidia.com/v1/embeddings"
      model_name: "nvidia/llama-3.2-nv-embedqa-1b-v2"
```

| Option | Description | Default | Notes |
|--------|-------------|---------|-------|
| `relevance_ratio` | Ratio of examples selected by pure relevance | 0.7 | Range: 0.0-1.0. Higher values prioritize relevance; lower values ensure tool diversity |
| `embedding_nim_config` | Embedding model configuration | Required | See [Embedding NIM Configuration](#embedding-nim-configuration) below |

#### Embedding NIM Configuration

When using `semantic_similarity`, you must configure an embedding model within the `similarity_config` section:


**Local Deployment** (`deployment_type: "local"`):
- Spins up a dedicated embedding NIM in your cluster
- Requires GPU resources and storage
- Provides isolated embedding generation

```yaml
icl_config:
  example_selection: "semantic_similarity"
  similarity_config:
    relevance_ratio: 0.7
    embedding_nim_config:
      deployment_type: "local"
      model_name: "nvidia/llama-3.2-nv-embedqa-1b-v2"
      context_length: 32768
      gpus: 1
      pvc_size: "25Gi"
      tag: "1.9.0"
```

**Remote Deployment** (`deployment_type: "remote"`):
- Uses an external embedding API endpoint
- Requires API key configuration (set `EMB_API_KEY` or defaults to `NVIDIA_API_KEY`)

```yaml
icl_config:
  example_selection: "semantic_similarity"
  similarity_config:
    relevance_ratio: 0.7
    embedding_nim_config:
      deployment_type: "remote"
      url: "https://integrate.api.nvidia.com/v1/embeddings"
      model_name: "nvidia/llama-3.2-nv-embedqa-1b-v2"
```

## Fine-tuning Options

The `training_config` and `lora_config` sections control model fine-tuning:

```yaml
training_config:
  training_type: "sft"
  finetuning_type: "lora"
  epochs: 2
  batch_size: 16
  learning_rate: 0.0001

lora_config:
  adapter_dim: 32
  adapter_dropout: 0.1
```

### Training Configuration

| Option | Description | Default | Notes |
|--------|-------------|---------|-------|
| `training_type` | Type of training | "sft" | Supervised Fine-Tuning |
| `finetuning_type` | Fine-tuning method | "lora" | Low-Rank Adaptation |
| `epochs` | Training epochs | 2 | Full passes through data |
| `batch_size` | Batch size | 16 | Samples per training step |
| `learning_rate` | Learning rate | 0.0001 | Training step size |

### LoRA Configuration

| Option | Description | Default | Notes |
|--------|-------------|---------|-------|
| `adapter_dim` | LoRA adapter dimension | 32 | Rank of adaptation |
| `adapter_dropout` | Dropout rate | 0.1 | Regularization parameter |

## Model Customization

The developer example supports model customization (fine-tuning) through the NeMo Customizer service. This feature enables Parameter-Efficient Fine-Tuning (PEFT) using LoRA (Low-Rank Adaptation) to efficiently customize base models on your specific datasets.

### Overview

Model customization works by:
1. **Target Selection**: Choosing a base model that supports customization
2. **Configuration Setup**: Creating a customization configuration with training parameters
3. **Training Execution**: Running the fine-tuning job with your dataset
4. **Model Deployment**: Using the customized model for inference

### Configuration Structure

To enable customization for a model, add the `customization_enabled` and `customizer_configs` fields to your NIM configuration:

```yaml
nims:
  - model_name: "meta/llama-3.2-1b-instruct"
    context_length: 8192
    gpus: 1
    pvc_size: 25Gi
    tag: "1.8.3"
    customization_enabled: true  # Enable customization
    customizer_configs:
      target: "meta/llama-3.2-1b-instruct@2.0"  # Target model for customization
      gpus: 1
      max_seq_length: 8192
      # Additional training options...
```

### Target Models

**Targets** represent models that can be customized using the Customizer service. These are typically created during the initial setup of your Customizer microservice or NMP cluster.

**To find available targets:**
- Check the targets API in your NMP cluster or follow the NMP documentation to create one
- Contact your NMP administrator for the list of available targets

### Customization Parameters

The `customizer_configs` section supports the following parameters:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `target` | Target model for customization | - |
| `gpus` | Number of GPUs for training | - |
| `max_seq_length` | Maximum sequence length | 4096 |
| `num_nodes` | Number of nodes for training | 1 |
| `tensor_parallel_size` | Tensor parallel size | 1 |
| `data_parallel_size` | Data parallel size | 1 |
| `use_sequence_parallel` | Enable sequence parallel | false |
| `micro_batch_size` | Micro batch size | 1 |
| `training_precision` | Training precision | "bf16-mixed" |

**Training Hyperparameters** (configured in global `training_config` and `lora_config`):

| Hyperparameter | Description | Recommended Value |
|----------------|-------------|-------------------|
| `batch_size` | Number of samples processed together before updating model parameters | 16 (recommended; use 32 only if you have validated stability and sufficient memory) |
| `learning_rate` | Step size for updating model parameters | 1e-3 to 1e-5 |
| `epochs` | Number of complete passes through the training dataset | Varies by dataset size (automatic early stopping after 10 epochs without improvement) |
| `adapter_dim` | Rank of the low-rank matrices (LoRA) | Start with 8, increase if needed |
| `adapter_dropout` | Probability of dropping neurons during training | 0.1 for smaller models (7B-13B) |

> **Note**
> 
> - Sample targets and configuration hyperparameters are already provided for `llama-3.2-1b-instruct` & `llama-3.1-8b-instruct`
> - Feel free to modify the hyperparameters/training_options for the LoRA customization like `max_seq_length`, `training_type` based on your available resources

### Training Integration

Customization uses the global `training_config` and `lora_config` settings:

```yaml
training_config:
  training_type: "sft"        # Used by customization
  finetuning_type: "lora"     # Used by customization
  epochs: 2                   # Used by customization
  batch_size: 16              # Used by customization
  learning_rate: 0.0001       # Used by customization

lora_config:
  adapter_dim: 32             # Used by customization
  adapter_alpha: 16           # Used by customization
  adapter_dropout: 0.1        # Used by customization
```

### Example Configurations

**Llama 3.2 1B Instruct (Default):**
```yaml
nims:
  - model_name: "meta/llama-3.2-1b-instruct"
    model_type: "llm"
    context_length: 8192
    gpus: 1
    pvc_size: 25Gi
    tag: "1.8.3"
    customization_enabled: true
    customizer_configs:
      target: "meta/llama-3.2-1b-instruct@2.0"
      gpus: 1
      max_seq_length: 8192
```

**Llama 3.1 8B Instruct:**
```yaml
nims:
  - model_name: "meta/llama-3.1-8b-instruct"
    context_length: 32768
    gpus: 1
    pvc_size: 25Gi
    tag: "1.8.3"
    customization_enabled: true
    customizer_configs:
      target: "meta/llama-3.1-8b-instruct@2.0"
      gpus: 1
      max_seq_length: 8192
      micro_batch_size: 1
      training_precision: "bf16-mixed"
```

### Best Practices

1. **Resource Allocation**: Ensure sufficient GPU resources for your target model size
2. **Sequence Length**: Set `max_seq_length` based on your dataset requirements
3. **Batch Size**: Use 16 (recommended), 32 only with validated stability and sufficient memory
4. **Learning Rate**: Use range 1e-3 to 1e-5 for optimal training
5. **LoRA Parameters**: 
   - Start with `adapter_dim=8`, increase if needed
   - Use `adapter_dropout=0.05` for smaller models (7B-13B)
7. **Target Verification**: Always verify target availability before starting customization

> **Reference**
> 
> For detailed information about NeMo Customizer concepts, hyperparameters, and advanced features, refer to the [official NeMo Microservices Customization documentation](https://docs.nvidia.com/nemo/microservices/latest/about/core-concepts/customization.html).

## Enrichment Configuration

The `enrichment_config` section controls market-data enrichment applied to training records during dataset creation:

```yaml
enrichment_config:
  sma_windows: [5, 20]
  rsi_period: 14
  volatility_window: 20
  pct_change_period: 1
```

| Option | Description | Default |
|--------|-------------|---------|
| `sma_windows` | Simple moving average window sizes | [5, 20] |
| `rsi_period` | RSI calculation period | 14 |
| `volatility_window` | Rolling volatility window | 20 |
| `pct_change_period` | Percent change lookback period | 1 |

Enrichment adds the following features to each record: SMA (for each window), RSI, rolling volatility, and percent change. The ticker symbol is extracted from each record using `kdbx/enrichment.py:extract_sym_from_record()`.

## Backtest Configuration

The `backtest_config` section controls the financial backtesting evaluation:

```yaml
backtest_config:
  cost_bps: 5.0
  min_signals: 10
```

| Option | Description | Default |
|--------|-------------|---------|
| `cost_bps` | Round-trip transaction cost in basis points | 5.0 |
| `min_signals` | Minimum number of signals required to run backtest | 10 |

The backtest uses a vectorised KDB-X as-of join (`aj`) to compute entry/exit prices from `market_ticks`, then calculates Sharpe ratio, max drawdown, total return, and win rate.

## Data Infrastructure

The developer example uses several services for data storage and processing:

### Storage Services

| Service | Purpose | Configuration Location |
|---------|---------|----------------------|
| KDB-X | Log storage, API data persistence, vector search, market data | `deploy/docker-compose.yaml` |
| Redis | Task queue (Celery broker) | `deploy/docker-compose.yaml` |

### Processing Configuration

| Component | Purpose | Configuration |
|-----------|---------|---------------|
| Celery Workers | Background processing | Configurable concurrency |
| API Server | REST endpoints | FastAPI configuration |

## Deployment Options

The developer example supports multiple deployment strategies for different environments and requirements.

### Development Environment

```bash
./scripts/run-dev.sh
```

Includes additional services for development:
- Flower (Celery monitoring)
- KDB-X Studio (database visualization)

### Production Deployment Options

#### Docker Compose (Simple Production)

```bash
./scripts/run.sh
```

**Best for:**
- Single-node deployments
- Smaller production environments
- Organizations without Kubernetes infrastructure
- Development/staging environments

**Includes core services:**
- API Server
- Celery Workers
- KDB-X, Redis

#### Kubernetes with Helm (Enterprise Production)

**Best for:**
- Multi-node clusters
- High availability requirements
- Enterprise production environments
- Advanced scaling and monitoring needs

For production-grade Kubernetes deployment, refer to the [Helm Installation Guide](11-helm-installation.md) which provides:
- Scalable, production-ready Kubernetes deployment via Helm charts
- Integration with NeMo microservices
- Post-installation setup and verification procedures
- Operations, scaling, and maintenance guidance

### Resource Configuration

| Resource | Configuration | Notes |
|----------|--------------|-------|
| Network Mode | `deploy/docker-compose.yaml` | Service networking |
| Volume Mounts | `deploy/docker-compose.yaml` | Persistent storage |
| Health Checks | `deploy/docker-compose.yaml` | Service monitoring |
| Environment | `.env` file or environment variables | API keys and URLs |
