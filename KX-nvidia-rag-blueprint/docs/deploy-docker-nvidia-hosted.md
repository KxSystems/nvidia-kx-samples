<!--
  SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->
# Deploy NVIDIA RAG Blueprint with Docker (NVIDIA-Hosted Models)

Use this documentation to deploy the [NVIDIA RAG Blueprint](readme.md) with Docker Compose for a single node deployment, and using NVIDIA-hosted models for testing and experimenting.
For other deployment options, refer to [Deployment Options](readme.md#deployment-options-for-rag-blueprint).

> [!TIP]
> If you want to run the RAG Blueprint with [NVIDIA AI Workbench](https://docs.nvidia.com/ai-workbench/user-guide/latest/overview/introduction.html), use [Quickstart for NVIDIA AI Workbench](../deploy/workbench/README.md).

> [!NOTE]
> When using NVIDIA-hosted endpoints, you might encounter rate limiting with larger file ingestions (>10 files). For details, see [Troubleshoot](troubleshooting.md).



## Prerequisites

1. [Get an API Key](api-key.md).

2. Install Docker Engine. For more information, see [Ubuntu](https://docs.docker.com/engine/install/ubuntu/).

3. Install Docker Compose. For more information, see [install the Compose plugin](https://docs.docker.com/compose/install/linux/).

   a. Ensure the Docker Compose plugin version is 2.29.1 or later.

   b. After you get the Docker Compose plugin installed, run `docker compose version` to confirm.

4. To pull images required by the blueprint from NGC, you must first authenticate Docker with nvcr.io. Use the NGC API Key you created in the first step.

   ```bash
   export NGC_API_KEY="nvapi-..."
   echo "${NGC_API_KEY}" | docker login nvcr.io -u '$oauthtoken' --password-stdin
   ```

5. Some containers are enabled with GPU acceleration, such as KDB.AI with cuVS. To configure Docker for GPU-accelerated containers, [install](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) the NVIDIA Container Toolkit.

6. **(KDB.AI - Default Vector Database)** Obtain a KDB.AI license and Docker registry credentials from [KX](https://kx.com). A 90-day free trial is available. Set the following environment variables:

   ```bash
   export KDBAI_REGISTRY_EMAIL="your-email@example.com"
   export KDBAI_REGISTRY_TOKEN="your-bearer-token-from-kx-email"
   export KDB_LICENSE_B64="your-base64-license-from-kx-email"
   ```

   Then authenticate with the KX Docker registry:

   ```bash
   echo "${KDBAI_REGISTRY_TOKEN}" | docker login portal.dl.kx.com -u "${KDBAI_REGISTRY_EMAIL}" --password-stdin
   ```

> [!NOTE]
> This deployment uses **KDB.AI with NVIDIA cuVS** for GPU-accelerated vector search using the CAGRA index. This provides optimal performance for production workloads.


## Clone the Repository

Clone the NVIDIA RAG Blueprint repository and navigate to the project directory. All subsequent commands assume you are running from the repository root directory.


## Deployment Architecture

This deployment uses **NVIDIA-hosted cloud endpoints** for LLM, Embedding, Reranking, and Document Extraction NIMs, reducing local GPU requirements. Only KDB.AI runs locally with GPU acceleration.

### Docker Compose Files

| File | Components | Source |
|------|------------|--------|
| `vectordb.yaml` | KDB.AI with cuVS (GPU-accelerated vector database) | `portal.dl.kx.com` |
| `docker-compose-ingestor-server.yaml` | Ingestor Server, NV-Ingest, Redis, MinIO | `nvcr.io` |
| `docker-compose-rag-server.yaml` | RAG Server, Frontend UI | `nvcr.io` |

### Deployment Order

Services must be started in this order due to dependencies:

```
1. Vector DB (vectordb.yaml)  → KDB.AI with cuVS
         ↓
2. Ingestor (ingestor)        → Document processing (uses cloud NIMs)
         ↓
3. RAG Server (rag-server)    → Query processing (uses cloud NIMs)
```

Since NIMs are cloud-hosted, you don't need to deploy them locally. The Ingestor and RAG Server connect to NVIDIA's cloud endpoints for embedding, reranking, and LLM inference.


## Start services using NVIDIA-hosted models

Use the following procedure to start all containers needed for this blueprint.

1. Open `deploy/compose/.env` and uncomment the section `Endpoints for using cloud NIMs`. Then set the environment variables by running the following code.

   ```bash
   source deploy/compose/.env
   ```


2. Prepare the KDB.AI data directory and start the vector database containers.

   ```bash
   # Create data directory with proper permissions
   mkdir -p deploy/compose/volumes/kdbai && chmod 0777 deploy/compose/volumes/kdbai

   # Start KDB.AI with GPU acceleration (cuVS/CAGRA)
   docker compose -f deploy/compose/vectordb.yaml --profile kdbai up -d
   ```

   Wait for KDB.AI to be ready:

   ```bash
   curl http://localhost:8083/api/v2/ready
   ```


3. Start the ingestion containers from the repo root. This pulls the prebuilt containers from NGC and deploys it on your system.

   ```bash
   docker compose -f deploy/compose/docker-compose-ingestor-server.yaml up -d
   ```

   You can check the status of the ingestor-server by running the following code.

   ```bash
   curl -X 'GET' 'http://localhost:8082/v1/health?check_dependencies=true' -H 'accept: application/json'
   ```

    You should see output similar to the following.

    ```bash
    {
        "message": "Service is up.",
        "databases": [
            ...
        ],
        "object_storage": [
            ...
        ],
        "nim": [
            {
                "service": "Embeddings",
                "status": "healthy",
                "message": "Using NVIDIA API Catalog",
                ...
            },
            {
                "service": "Summary LLM",
                "status": "healthy",
                "message": "Using NVIDIA API Catalog",
                ...
            },
            {
                "service": "Caption Model",
                "status": "healthy",
                "message": "Using NVIDIA API Catalog",
                ...
            }
        ],
        "processing": [
            {
                "service": "NV-Ingest",
                "status": "healthy",
                ...
            }
        ],
        "task_management": [
            {
                "service": "Redis",
                "status": "healthy",
                ...
            }
        ]
    }
    ```


4. Start the rag containers from the repo root. This pulls the prebuilt containers from NGC and deploys it on your system.

   ```bash
   docker compose -f deploy/compose/docker-compose-rag-server.yaml up -d
   ```

   You can check the status of the rag-server and its dependencies by issuing this curl command
   ```bash
   curl -X 'GET' 'http://localhost:8081/v1/health?check_dependencies=true' -H 'accept: application/json'
   ```

    You should see output similar to the following.

    ```bash
    {
        "message": "Service is up.",
        "databases": [
            ...
        ],
        "object_storage": [
            ...
        ],
        "nim": [
            {
                "service": "LLM",
                "status": "healthy",
                "message": "Using NVIDIA API Catalog",
                ...
            },
            {
                "service": "Embeddings",
                "status": "healthy",
                "message": "Using NVIDIA API Catalog",
                ...
            },
            {
                "service": "Ranking",
                "status": "healthy",
                "message": "Using NVIDIA API Catalog",
                ...
            }
        ]
    }
    ```


5. Check the status of the deployment by running the following code.

   ```bash
   docker ps --format "table {{.ID}}\t{{.Names}}\t{{.Status}}"
   ```

    You should see output similar to the following. Confirm all the following containers are running.

   ```output
   NAMES                                   STATUS
   compose-nv-ingest-ms-runtime-1          Up 5 minutes (healthy)
   ingestor-server                         Up 5 minutes
   compose-redis-1                         Up 5 minutes
   rag-frontend                            Up 9 minutes
   rag-server                              Up 9 minutes
   kdbai-server                            Up 36 minutes
   compose-minio-1                         Up 35 minutes (healthy)
   ```


## Experiment with the Web User Interface

After the RAG Blueprint is deployed, you can use the RAG UI to start experimenting with it.

1. Open a web browser and access the RAG UI. You can start experimenting by uploading docs and asking questions. For details, see [User Interface for NVIDIA RAG Blueprint](user-interface.md).



## Experiment with the Ingestion API Usage Notebook

After the RAG Blueprint is deployed, you can use the Ingestion API Usage notebook to start experimenting with it. For details, refer to [Experiment with the Ingestion API Usage Notebook](notebooks.md#experiment-with-the-ingestion-api-usage-notebook).



## Shut down services

1. To stop all running services.
    ```bash
    docker compose -f deploy/compose/docker-compose-ingestor-server.yaml down
    docker compose -f deploy/compose/docker-compose-rag-server.yaml down
    docker compose -f deploy/compose/vectordb.yaml --profile kdbai down
    ```


## Advanced Deployment Considerations

After the first time you deploy the RAG Blueprint successfully, you can consider the following advanced deployment options:

- For information about advanced settings, see [Best Practices for Common Settings](accuracy_perf.md).

- To turn on recommended configurations for accuracy optimization, run the following code:

   ```bash
   source deploy/compose/accuracy_profile.env
   ```

- To turn on recommended configurations for performance optimization, run the following code:

   ```bash
   source deploy/compose/perf_profile.env
   ```

- By default, GPU-accelerated **KDB.AI with cuVS** is deployed using the CAGRA index for optimal vector search performance. You can choose the GPU ID to allocate by setting:

   ```bash
   export VECTORSTORE_GPU_DEVICE_ID=0
   ```

- To disable GPU acceleration and use CPU-only KDB.AI with HNSW index:

   ```bash
   export APP_VECTORSTORE_ENABLEGPUINDEX=False
   export APP_VECTORSTORE_ENABLEGPUSEARCH=False
   export KDBAI_INDEX_TYPE="hnsw"
   ```

- If you have a requirement to build the NVIDIA Ingest runtime container from source, you can do it by following instructions [here](https://github.com/NVIDIA/nv-ingest).



## Related Topics

- [NVIDIA RAG Blueprint Documentation](readme.md)
- [KDB.AI Deployment Guide](change-vectordb-kdbai.md) - Full KDB.AI configuration and troubleshooting
- [Best Practices for Common Settings](accuracy_perf.md)
- [RAG Pipeline Debugging Guide](debugging.md)
- [Troubleshoot](troubleshooting.md)
- [Notebooks](notebooks.md)
