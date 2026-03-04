# Data Logging for AI Apps

Instrumenting your AI application to log interactions is a critical step in implementing the developer example. This guide explains how to enable data logging for any AI app, providing a general approach and best practices.

## General Approach and Requirements

### Supported Logging Backend

- **KDB-X** — unified data platform for log storage, vector search, and financial analytics

### Environment Variables

To enable data logging, set the following environment variables:

```sh
KDBX_ENDPOINT=localhost:8082
```

### Data Schema

Log entries should include:

```json
{
  "request": { ... },
  "response": { ... },
  "timestamp": "...",
  "client_id": "...",
  "workload_id": "..."
}
```

## Implementing Data Logging in Any App

### Direct KDB-X Integration (Recommended)

The developer example uses a PyKX-based KDB-X integration for logging. Here's a practical example:

```python
import os
import time
import uuid
from openai import OpenAI

# Environment configuration
KDBX_ENDPOINT = os.getenv("KDBX_ENDPOINT", "localhost:8082")

# Initialize clients
openai_client = OpenAI()

CLIENT_ID = "my_demo_app"

# Example agent nodes (each with its own workload_id)
WORKLOADS = {
    "simple_chat": "agent.chat",
    "tool_router": "agent.tool_router",
}

def log_chat(workload_id: str, messages: list[dict]):
    # 1) call the LLM
    response = openai_client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=messages,
        temperature=0.3,
    )

    # 2) build the document
    doc = {
        "timestamp": int(time.time()),
        "workload_id": workload_id,
        "client_id": CLIENT_ID,
        "request": {
            "model": response.model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 1024,
        },
        "response": response.model_dump(),  # OpenAI python-sdk v1 returns a pydantic model
    }

    # 3) write to KDB-X via the pymongo-compatible shim
    from src.api.db import get_db
    db = get_db()
    db.flywheel_logs.insert_one(doc)

# --- Example usage -----------------------------------------------------------
messages_chat = [{"role": "user", "content": "Hello!"}]
log_chat(WORKLOADS["simple_chat"], messages_chat)

messages_tool = [
    {"role": "user", "content": "Who won the 2024 Super Bowl?"},
    {
        "role": "system",
        "content": "You are a router that decides whether to call the Wikipedia tool or answer directly.",
    },
]
log_chat(WORKLOADS["tool_router"], messages_tool)
```

### Integration Steps

1. Configure the `KDBX_ENDPOINT` environment variable pointing to your KDB-X instance.
2. For each LLM interaction, capture both request and response data.
3. Structure the data according to the required schema with `workload_id` and `client_id`.
4. Insert the log entry into the `flywheel_logs` KDB-X table.

## Configuration

To enable data logging to KDB-X, configure the following environment variable:

```sh
KDBX_ENDPOINT=localhost:8082
```

### Data Schema

The log entries stored in KDB-X contain the following structure:

```json
{
  "request": {
    "model": "model_name",
    "messages": [{"role": "user", "content": "..."}],
    "temperature": 0.2,
    "max_tokens": 1024,
    "tools": []
  },
  "response": {
    "id": "run_id",
    "object": "chat.completion",
    "model": "model_name",
    "usage": {"prompt_tokens": 50, "completion_tokens": 120, "total_tokens": 170}
  },
  "timestamp": 1715854074,
  "client_id": "your_app",
  "workload_id": "session_id"
}
```

### Implementation Architecture

The developer example system includes several components for data management:

1. **KDB-X Compatibility Shim**: PyMongo-compatible interface (`kdbx/compat.py`)
2. **Record Exporter**: Retrieves logged data for processing (`src/lib/integration/record_exporter.py`)
3. **Data Validation**: Ensures data quality before processing (`src/lib/integration/data_validator.py`)

### Code Implementation Examples

#### KDB-X Client Implementation

The system uses a KDB-X connection with PyKX:

```python
# From src/api/db.py (simplified for readability)
import pykx as kx
from kdbx.compat import KDBXDatabase

def get_db() -> KDBXDatabase:
    """Get the KDB-X database instance."""
    return KDBXDatabase(host, port)
```

The `KDBXDatabase` provides a pymongo-compatible API — `find()`, `insert_one()`, `update_one()` — that translates to parameterized q queries under the hood.

#### Data Loading for Testing

For development and testing, you can load sample data via the API or the example notebook at [`notebooks/ai-model-distillation-financial-data.ipynb`](../notebooks/ai-model-distillation-financial-data.ipynb).

```python
# Example: load data via the KDB-X pymongo-compatible shim
from src.api.db_manager import get_db

db = get_db()

with open("data/aiva-test.jsonl") as f:
    test_data = [json.loads(line) for line in f]

for doc in test_data:
    doc["workload_id"] = "my-workload"
    doc["client_id"] = "my-client"
    db.flywheel_logs.insert_one(doc)
```

### Dependencies

- `pykx>=2.5.0`

## Best Practices

- Use consistent `workload_id` values for accurate workload identification.
- Make sure you include error handling in logging routines.
- Be mindful of privacy and personally identifiable information (PII)—consider redacting or anonymizing as needed.
- Log only what's necessary for model improvement and debugging.
- Use the `KDBX_ENDPOINT` environment variable to configure your connection.

## Data Validation

The system includes built-in data validation to ensure quality:

- **OpenAI Format Validation**: Ensures proper request/response structure
- **Workload Type Detection**: Automatically identifies workload types
- **Deduplication**: Removes duplicate entries based on user queries
- **Quality Filters**: Applies workload-specific quality checks

## Integration with developer example

Once data is logged to KDB-X, the developer example can:

1. **Export Records**: Use `RecordExporter` to retrieve data for processing
2. **Validate Data**: Apply quality filters and format validation
3. **Create Datasets**: Generate training and evaluation datasets
4. **Run Evaluations**: Compare model performance across different configurations

## Additional Resources

- [Instrumenting an application (README)](../README.md#2instrumenting-an-application)
- [PyKX Documentation](https://code.kx.com/pykx/)
- [Data Validation Guide](dataset-validation.md)
- Source code examples:
  - `kdbx/compat.py` - KDB-X pymongo-compatible shim
  - `src/lib/integration/record_exporter.py` - Data retrieval
  - `notebooks/ai-model-distillation-financial-data.ipynb` - Example data loading notebook
