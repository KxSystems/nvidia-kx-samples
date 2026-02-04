# KDB.AI Vector Database Integration

This document describes the KDB.AI vector database integration for NVIDIA RAG Blueprint, including implementation details, GPU acceleration support, issues encountered, and their solutions.

## Overview

KDB.AI is a vector database from KX Systems that supports similarity search with various index types (HNSW, Flat, IVF, IVFPQ). This integration enables KDB.AI as an alternative to Milvus and Elasticsearch for storing and retrieving document embeddings.

### Key Features

- **CPU and GPU Index Support**: Use HNSW/Flat indexes on CPU or CAGRA (cuVS) on GPU
- **NV-Ingest Pipeline Integration**: Full support for document ingestion workflows
- **LangChain Compatibility**: Works with LangChain retrieval chains
- **Metadata Schema Management**: Store and retrieve collection metadata schemas
- **Filter Expression Translation**: Automatic Milvus-to-KDB.AI filter conversion

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `APP_VECTORSTORE_NAME` | Set to `kdbai` to use KDB.AI | - |
| `APP_VECTORSTORE_URL` | KDB.AI endpoint URL | `http://kdbai:8082` |
| `KDBAI_API_KEY` | API key for KDB.AI Cloud (optional for local server) | - |
| `KDBAI_DATABASE` | Database name in KDB.AI | `default` |
| `KDBAI_INDEX_TYPE` | Index type: `hnsw`, `flat`, `cagra`, `ivf`, `ivfpq` | `hnsw` |
| `KDBAI_DEBUG` | Enable verbose debug logging | `false` |
| `APP_VECTORSTORE_ENABLEGPUINDEX` | Enable GPU-accelerated indexing (cuVS) | `False` |
| `APP_VECTORSTORE_ENABLEGPUSEARCH` | Enable GPU-accelerated search (cuVS) | `False` |
| `KDBAI_INSERT_BATCH_SIZE` | Batch size for inserting records | `200` |
| `KDBAI_CAGRA_SINGLE_BATCH` | Use single batch insert for CAGRA (workaround) | `true` |
| `KDBAI_THREADS` | Number of threads for KDB.AI server | `8` |

### KX Docker Registry Authentication

KDB.AI requires authentication to pull images from KX's Docker registry:

| Variable | Description |
|----------|-------------|
| `KDBAI_REGISTRY_EMAIL` | Your KX signup email |
| `KDBAI_REGISTRY_TOKEN` | Bearer token from KX welcome email |
| `KDB_LICENSE_B64` | Base64-encoded KDB.AI license string |

## GPU Acceleration (cuVS)

KDB.AI supports GPU-accelerated vector indexing and search via NVIDIA cuVS (CUDA Vector Search).

### How It Works

When GPU indexing is enabled with a compatible index type (`hnsw` or `flat`), the integration automatically maps to the `cagra` index type (CUDA Approximate Graph-based Nearest Neighbor).

```
GPU Enabled + hnsw → cagra (GPU-accelerated)
GPU Enabled + flat → cagra (GPU-accelerated)
GPU Enabled + ivf  → ivf (remains CPU, not GPU-compatible)
GPU Disabled + any → original type (CPU)
```

### Configuration

```bash
# Enable GPU acceleration
export APP_VECTORSTORE_ENABLEGPUINDEX=True
export APP_VECTORSTORE_ENABLEGPUSEARCH=True

# Use the kdbai-gpu Docker Compose profile
docker compose -f vectordb.yaml --profile kdbai-gpu up -d
```

### Limitations

- **CAGRA Max Results**: cuVS cagra index has a hard limit of 64 results per query (`itopk_size` default)
- **CAGRA Extend Bug**: There's a known issue with `cuvsCagraExtend()` that can crash when extending an existing index. The workaround (`KDBAI_CAGRA_SINGLE_BATCH=true`) inserts all records in a single batch to avoid calling extend.

## Docker Compose Deployment

### CPU Mode (Standard)

```yaml
# In vectordb.yaml - kdbai profile
kdbai:
  container_name: kdbai
  image: portal.dl.kx.com/kdbai-db
  ports:
    - "8083:8081"  # REST API
    - "8084:8082"  # Client endpoint
  environment:
    KDB_LICENSE_B64: ${KDB_LICENSE_B64}
    VDB_DIR: "/tmp/kx/data/vdb"
    THREADS: ${KDBAI_THREADS:-8}
  volumes:
    - kdbai-data:/tmp/kx/data/vdb
  profiles: ["kdbai"]
```

### GPU Mode (cuVS)

```yaml
# In vectordb.yaml - kdbai-gpu profile
kdbai-gpu:
  container_name: kdbai-server-gpu
  # cuVS image from KX portal
  image: ${KDBAI_GPU_IMAGE:-portal.dl.kx.com/kdbai-db-cuvs:1.8.2}
  ports:
    - "8083:8081"
    - "8084:8082"
  environment:
    KDB_LICENSE_B64: ${KDB_LICENSE_B64}
    VDB_DIR: "/tmp/kx/data/vdb"
    THREADS: ${KDBAI_THREADS:-8}
    CUDA_VISIBLE_DEVICES: ${KDBAI_GPU_DEVICE_ID:-0}
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            capabilities: ["gpu"]
            device_ids: ['${KDBAI_GPU_DEVICE_ID:-0}']
  profiles: ["kdbai-gpu"]
```

### Deployment Commands

```bash
# CPU Mode
docker compose -f vectordb.yaml --profile kdbai up -d

# GPU Mode (cuVS)
export APP_VECTORSTORE_ENABLEGPUINDEX=True
export APP_VECTORSTORE_ENABLEGPUSEARCH=True
docker compose -f vectordb.yaml --profile kdbai-gpu up -d

# Full RAG Stack with KDB.AI
./deploy-kdbai-8gpu.sh up
```

### Registry Authentication

Before first run, authenticate with KX Docker registry:

```bash
# KDB.AI images (CPU and cuVS GPU) - portal.dl.kx.com
echo "$KDBAI_REGISTRY_TOKEN" | docker login portal.dl.kx.com -u "$KDBAI_REGISTRY_EMAIL" --password-stdin
```

## Helm Deployment (Kubernetes/EKS)

### Prerequisites: NGC Helm Repository Authentication

```bash
helm repo add nemo-microservices https://helm.ngc.nvidia.com/nvidia/nemo-microservices \
  --username '$oauthtoken' \
  --password '<YOUR_NGC_API_KEY>'
helm repo update
```

### Deploy

```bash
helm upgrade --install rag deploy/helm/nvidia-blueprint-rag \
  --namespace rag \
  -f deploy/helm/nvidia-blueprint-rag/values-kdbai.yaml \
  --dependency-update \
  --timeout 20m
```

## Architecture

### Files Structure

```
src/nvidia_rag/utils/vdb/kdbai/
├── __init__.py
├── kdbai_vdb.py      # Main KdbaiVDB class implementation
├── kdbai_filters.py  # Filter expression translation utilities
└── README.md         # This documentation
```

### Key Components

1. **KdbaiVDB** (`kdbai_vdb.py`): Main class implementing the `VDBRag` interface
   - Collection management (create, delete, list)
   - Document management (insert, delete, query)
   - Metadata schema storage
   - Vector similarity search
   - GPU/cuVS support

2. **Filter Utilities** (`kdbai_filters.py`): Translates Milvus-style filter expressions to KDB.AI format

### NV-Ingest Client VDB Interface

The `KdbaiVDB` class implements the NV-Ingest client VDB interface for seamless integration with the ingestion pipeline:

| Method | Description |
|--------|-------------|
| `_check_index_exists(table_name)` | Check if table exists in KDB.AI |
| `create_index()` | Create table with vector index if not exists |
| `write_to_index(records)` | Write records in batches to KDB.AI |
| `run(records)` | Full ingestion: create index + write records |
| `reindex(records)` | Drop table and re-ingest all records |
| `retrieval(queries)` | Retrieve documents (use `retrieval_langchain` instead) |

### Retrieval Operations

| Method | Description |
|--------|-------------|
| `get_langchain_vectorstore(collection_name)` | Get LangChain KDBAI VectorStore |
| `retrieval_langchain(query, collection_name, ...)` | Direct table search (bypasses LangChain) |

## Issues and Solutions

### Issue 1: kdbai-client Import Error

**Error:**
```
ImportError: kdbai_client is required for KDB.AI support
```

**Solution:** Added `kdbai-client` to project dependencies.

---

### Issue 2: Metadata DataFrame Type Error

**Error:**
```
TypeError: string indices must be integers, not 'str'
```

**Solution:** Read CSV file using `pandas_file_reader()` before passing to KdbaiVDB.

---

### Issue 3: Search Vectors Format

**Error:**
```
AttributeError: 'list' object has no attribute 'items'
```

**Solution:** Bypassed LangChain's KDBAI VectorStore and call `table.search()` directly:

```python
# Correct format for kdbai_client
matches = table.search(
    vectors={"vectorIndex": [query_embedding]},  # Dict with index name as key
    n=top_k,
)
```

---

### Issue 4: Index Not Found Error

**Error:**
```
KDBAIException: Neither Sparse nor Dense Index : Index not found
```

**Solution:** Standardized index name to `vectorIndex` and ensured consistent naming between table creation and search.

---

### Issue 5: Filter Expression Format

**Error:**
```
KDBAIException: Unsupported filter function: ==
```

**Solution:** KDB.AI uses tuples with `=` operator:

```python
# Correct KDB.AI filter format
[("=", "column", "value")]  # Not ["==", "column", "value"]
```

---

### Issue 6: CAGRA Extend Crash

**Error:**
```
cuvsCagraExtend() crashes when extending existing GPU index
```

**Solution:** Set `KDBAI_CAGRA_SINGLE_BATCH=true` to insert all records in one batch, avoiding the extend operation. When KDB.AI/cuVS fixes this issue, set to `false` for better memory efficiency.

---

### Issue 7: Helm Duplicate Environment Variable

**Error:**
```
duplicate entries for key [name="INGEST_LOG_LEVEL"]
```

**Solution:** Set `INGEST_LOG_LEVEL: null` in Helm values to override subchart default.

---

### Issue 8: Helm Release Secret Too Large

**Error:**
```
Secret "sh.helm.release.v1.rag.v1" is invalid: data: Too long
```

**Solution:** Move backup folders outside the chart directory before deploying.

## KDB.AI API Reference

### Filter Format

```python
# Equality
[("=", "column", "value")]

# Inequality
[("<>", "column", "value")]

# Comparison
[("<", "column", 100), (">=", "column", 10)]

# In list
[("in", "column", ["val1", "val2"])]

# Like pattern
[("like", "column", "*pattern*")]
```

### Search Format

```python
table.search(
    vectors={"vectorIndex": [embedding_vector]},
    n=10,
    filter=[("=", "field", "value")],
)
```

### Table Creation (CPU - HNSW)

```python
indexes = [{
    "name": "vectorIndex",
    "type": "hnsw",
    "column": "vector",
    "params": {
        "dims": 2048,
        "metric": "L2",
        "M": 8,
        "efConstruction": 8,
    },
}]
```

### Table Creation (GPU - CAGRA)

```python
indexes = [{
    "name": "vectorIndex",
    "type": "cagra",
    "column": "vector",
    "params": {
        "metric": "L2",  # Only metric required for cagra
    },
}]
```

## Testing

After deployment, verify the integration:

1. **Create a collection** with metadata schema via the UI
2. **Upload and ingest** a document
3. **Chat** with the document to verify retrieval works
4. **Check logs** for any errors:
   ```bash
   kubectl logs deployment/rag-server -n rag --tail=100
   kubectl logs deployment/ingestor-server -n rag --tail=100
   ```

### Unit Tests

```bash
# Run KDB.AI VDB tests
pytest tests/unit/test_utils/test_vdb/test_kdbai_vdb.py -v
```

## Debugging Tips

Enable debug logging with `KDBAI_DEBUG=true` and check for these log messages:

| Log Message | Description |
|-------------|-------------|
| `Connected to KDB.AI at ...` | Connection successful |
| `GPU indexing enabled: mapping 'hnsw' -> 'cagra'` | GPU mode active |
| `Built index config (GPU cuVS): ...` | GPU index configuration |
| `KDB.AI search returned: ...` | Search results |
| `Got X records from search` | Documents retrieved |
| `KDB.AI retrieval: X docs in Y.Zs` | Search performance |
| `cuVS cagra index limits results to 64` | CAGRA result limit warning |

## References

- [KDB.AI Documentation](https://code.kx.com/kdbai/)
- [KDB.AI Python Client](https://code.kx.com/kdbai/reference/python-client.html)
- [KDB.AI Filter Documentation](https://code.kx.com/kdbai/use/filter.html)
- [KDB.AI Index Types](https://code.kx.com/kdbai/latest/use/supported-indexes.html)
- [KDB.AI cuVS Integration](https://docs.kx.com/kdbai-db/use/vector-indexes.html)
- [NVIDIA cuVS](https://github.com/rapidsai/cuvs)
