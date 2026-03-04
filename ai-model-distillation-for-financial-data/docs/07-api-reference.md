# API Reference and Integration Guide

Learn how to integrate with the developer example REST API to programmatically manage flywheel jobs, monitor progress, and retrieve results.

## Base URL and Authentication

The API is served on port 8000 with the `/api` prefix:

```
Base URL: http://your-host:8000/api
```

**Authentication**: Currently, no authentication is required for the API endpoints. In production deployments, ensure proper network security and access controls.

## Core Endpoints

### Create Flywheel Job
> **`POST`** `/api/jobs` - *Start a new NIM workflow job*

Creates a new flywheel job that runs the complete NIM workflow including data extraction, evaluation, and model customization.

<details>
<summary><strong>Request Details</strong></summary>

**Request Body:**
```json
{
  "workload_id": "customer-service-v1",
  "client_id": "production-app",
  "data_split_config": {
    "eval_size": 20,
    "val_ratio": 0.1,
    "min_total_records": 50,
    "limit": null
  }
}
```

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workload_id` | `string` | Yes | Identifier for the workload type in your logged data |
| `client_id` | `string` | Yes | Identifier for the client application generating the data |
| `data_split_config` | `object` | No | Configuration for dataset splitting |

</details>

**Success Response:**
```json
{
  "id": "507f1f77bcf86cd799439011",
  "status": "queued",
  "message": "NIM workflow started"
}
```

> **Note:** There is currently a known inconsistency where the POST endpoint returns `"queued"` but the job is actually stored with `"pending"` status. Subsequent GET requests will show the actual stored status.

**Example cURL:**
```bash
curl -X POST "http://localhost:8000/api/jobs" \
  -H "Content-Type: application/json" \
  -d '{
    "workload_id": "customer-service-v1",
    "client_id": "production-app"
  }'
```

---

### List All Jobs
> **`GET`** `/api/jobs` - *Retrieve all flywheel jobs*

Retrieves a list of all flywheel jobs with their current status and basic information.

**Success Response:**
```json
{
  "jobs": [
    {
      "id": "507f1f77bcf86cd799439011",
      "workload_id": "customer-service-v1", 
      "client_id": "production-app",
      "status": "pending",
      "started_at": "2024-01-15T10:30:00Z",
      "finished_at": null,
      "datasets": [
        {
          "name": "base-eval-dataset",
          "num_records": 150,
          "nmp_uri": "https://nmp.host/v1/datasets/dataset-123"
        }
      ],
      "error": null
    }
  ]
}
```

**Example cURL:**
```bash
curl "http://localhost:8000/api/jobs"
```

---

### Get Job Details  
> **`GET`** `/api/jobs/{job_id}` - *Get comprehensive job information*

Retrieves detailed information about a specific job, including all workflow stages, evaluations, and results.

<details>
<summary><strong>Complete Response Structure</strong></summary>

```json
{
  "id": "507f1f77bcf86cd799439011",
  "workload_id": "customer-service-v1",
  "client_id": "production-app", 
  "status": "completed",
  "started_at": "2024-01-15T10:30:00Z",
  "finished_at": "2024-01-15T12:45:00Z",
  "num_records": 1000,
  "enrichment_stats": {
    "num_enriched": 150,
    "total_records": 1000,
    "fields_added": ["market_close", "market_vwap", "market_high", "market_low", "market_volume", "market_bid", "market_ask", "market_spread", "market_mid"]
  },
  "datasets": [
    {
      "name": "base-eval-dataset",
      "num_records": 150,
      "nmp_uri": "https://nmp.host/v1/datasets/dataset-123"
    }
  ],
  "nims": [
    {
      "model_name": "meta/llama-3.2-1b-instruct",
      "status": "completed",
      "deployment_status": "ready",
      "runtime_seconds": 450.5,
      "evaluations": [
        {
          "eval_type": "base-eval",
          "scores": {"f1_score": 0.85},
          "started_at": "2024-01-15T11:00:00Z",
          "finished_at": "2024-01-15T11:30:00Z",
          "runtime_seconds": 1800.0,
          "progress": 100.0,
          "nmp_uri": "https://nmp.host/v1/evaluation/jobs/eval-123",
          "mlflow_uri": "http://localhost:5000/#/experiments/123",
          "error": null
        },
        {
          "eval_type": "backtest-eval",
          "scores": {
            "sharpe": 0.187,
            "max_drawdown": -0.029,
            "total_return": 0.045,
            "win_rate": 0.438,
            "n_trades": 16
          },
          "started_at": "2024-01-15T12:30:00Z",
          "finished_at": "2024-01-15T12:30:05Z",
          "runtime_seconds": 5.0,
          "progress": 100.0,
          "nmp_uri": null,
          "mlflow_uri": null,
          "error": null
        }
      ],
      "customizations": [
        {
          "started_at": "2024-01-15T11:30:00Z",
          "finished_at": "2024-01-15T12:00:00Z",
          "runtime_seconds": 1800.0,
          "progress": 100.0,  
          "epochs_completed": 2,
          "steps_completed": 100,
          "nmp_uri": "https://nmp.host/v1/customization/jobs/custom-123",
          "customized_model": "customized-llama-3.2-1b-instruct",
          "error": null
        }
      ],
      "error": null
    }
  ],
  "error": null
}
```

</details>

**Example cURL:**
```bash
curl "http://localhost:8000/api/jobs/507f1f77bcf86cd799439011"
```

---

### Cancel Job
> **`POST`** `/api/jobs/{job_id}/cancel` - *Stop a running job*

Cancels a running job, stopping all active tasks and marking the job as cancelled.

**Success Response:**
```json
{
  "id": "507f1f77bcf86cd799439011",
  "message": "Job cancellation initiated successfully."
}
```

**Example cURL:**
```bash
curl -X POST "http://localhost:8000/api/jobs/507f1f77bcf86cd799439011/cancel"
```

> **Note:** Only jobs that haven't finished can be cancelled. Completed, failed, or already cancelled jobs cannot be cancelled.

---

### Delete Job
> **`DELETE`** `/api/jobs/{job_id}` - *Remove job and cleanup resources*

Deletes a job and all its associated resources from the database. Running jobs must be cancelled first.

**Success Response:**
```json
{
  "id": "507f1f77bcf86cd799439011",
  "message": "Job deletion started. Resources will be cleaned up in the background."
}
```

**Example cURL:**
```bash
curl -X DELETE "http://localhost:8000/api/jobs/507f1f77bcf86cd799439011"
```

## Data Explorer Endpoints

### Get Schema
> **`GET`** `/api/data/schema` - *List all KDB-X tables and their columns*

Returns the schema for every KDB-X table, including column names.

**Success Response:**
```json
{
  "tables": {
    "flywheel_runs": ["_id", "client_id", "datasets", "enrichment_stats", "error", "finished_at", "num_records", "started_at", "status", "workload_id"],
    "flywheel_logs": ["client_id", "doc_id", "request", "response", "timestamp", "workload_id"],
    "evaluations": ["_id", "error", "eval_type", "finished_at", "job_id", "mlflow_uri", "nim_id", "nmp_uri", "progress", "runtime_seconds", "scores", "started_at"]
  }
}
```

**Example cURL:**
```bash
curl "http://localhost:8000/api/data/schema"
```

---

### Get Table Row Count
> **`GET`** `/api/data/{table}/count` - *Count rows in a KDB-X table*

Returns the row count for a table. Supports optional column equality filters as query parameters.

**Path Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `table` | `string` | Yes | Table name (must match a known KDB-X table) |

**Query Parameters:** Any valid column name for the table can be passed as a filter (e.g., `?workload_id=customer-service-v1`).

**Success Response:**
```json
{
  "table": "flywheel_logs",
  "count": 500
}
```

**Example cURL:**
```bash
# Count all rows
curl "http://localhost:8000/api/data/flywheel_logs/count"

# Count with filter
curl "http://localhost:8000/api/data/evaluations/count?eval_type=base-eval"
```

---

### Query Table Data
> **`GET`** `/api/data/{table}` - *Query rows from a KDB-X table*

Returns rows from a KDB-X table with optional column equality filters and a configurable row limit.

**Path Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `table` | `string` | Yes | Table name (must match a known KDB-X table) |

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `limit` | `int` | No | Maximum rows to return (1-1000, default 50) |

Additional query parameters matching valid column names act as equality filters.

**Success Response:**
```json
{
  "table": "flywheel_logs",
  "count": 50,
  "rows": [
    {
      "doc_id": "abc123",
      "workload_id": "customer-service-v1",
      "client_id": "production-app",
      "timestamp": "2024-01-15T10:30:00",
      "request": {"messages": [{"role": "user", "content": "..."}]},
      "response": {"choices": [{"message": {"role": "assistant", "content": "..."}}]}
    }
  ]
}
```

**Example cURL:**
```bash
# Get first 50 rows (default)
curl "http://localhost:8000/api/data/flywheel_logs"

# Get 100 rows filtered by workload
curl "http://localhost:8000/api/data/flywheel_logs?limit=100&workload_id=customer-service-v1"
```

---

## Financial Analytics Endpoints

### Run Backtest
> **`POST`** `/api/backtest` - *Run a vectorised backtest for a model's trading signals*

Executes a vectorised backtest for the given model's trading signals using KDB-X as-of joins against the `market_ticks` table. Returns performance metrics including Sharpe ratio, max drawdown, and win rate.

<details>
<summary><strong>Request Details</strong></summary>

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `model_id` | `string` | Yes | Identifier for the model whose signals to backtest |
| `universe` | `list[string]` | No | Ticker symbols to include (repeated query param for multiple values) |
| `cost_bps` | `float` | No | Transaction cost in basis points (default from config) |

</details>

**Success Response:**
```json
{
  "model_id": "test-model",
  "cost_bps": 5.0,
  "universe": ["NVDA", "AAPL"],
  "sharpe": 0.187,
  "max_drawdown": -0.029,
  "total_return": 0.045,
  "win_rate": 0.438,
  "n_trades": 16
}
```

**Example cURL:**
```bash
curl -X POST "http://localhost:8000/api/backtest?model_id=test-model&universe=NVDA&universe=AAPL"
```

> **Note:** If no signals exist for the given `model_id`, the endpoint returns a 500 error.

---

### Market Status
> **`GET`** `/api/market-status` - *Check row counts for financial market tables*

Returns row counts for all 4 financial market tables (`market_ticks`, `order_book`, `signals`, `backtest_results`). Tables that do not exist yet return a row count of 0 with an error message.

**Success Response:**
```json
{
  "market_ticks": {"row_count": 100},
  "order_book": {"row_count": 0},
  "signals": {"row_count": 40},
  "backtest_results": {"row_count": 0}
}
```

If a table has not been created yet:
```json
{
  "market_ticks": {"row_count": 0, "error": "table not found"}
}
```

**Example cURL:**
```bash
curl "http://localhost:8000/api/market-status"
```

---

## Job Status Values

| Status | Description |
|--------|-------------|
| `pending` | Job is queued and waiting to start |
| `running` | Job is actively executing workflow stages |
| `completed` | Job finished successfully |
| `cancelled` | Job was manually cancelled |
| `failed` | Job encountered an error and stopped |

## Data Split Configuration

The optional `data_split_config` allows you to control how logged data is processed for evaluation:

```json
{
  "eval_size": 20,
  "val_ratio": 0.1,
  "min_total_records": 50,
  "limit": null,
  "random_seed": 42,
  "parse_function_arguments": true,
  "stratify_enabled": true,
  "min_samples_per_class": 2,
  "rare_class_threshold": 1
}
```

**Parameters:**
- `eval_size` (int): Size of evaluation set (default: 20)
- `val_ratio` (float): Validation ratio (0.0-1.0, default: 0.1)
- `min_total_records` (int): Minimum total records required to proceed (default: 50)
- `limit` (int | null): Maximum records to use for evaluation (default: null — no limit)
- `random_seed` (int): Seed for reproducible splits (optional)
- `parse_function_arguments` (bool): Parse function arguments to JSON (default: true)
- `stratify_enabled` (bool): Enable stratified splitting to maintain class balance (default: true)
- `min_samples_per_class` (int): Minimum samples required per class for stratification (default: 2)
- `rare_class_threshold` (int): Group classes with <= this many samples as "others" (default: 1)

## Python Integration Example

```python
import requests
import time

class DataFlywheelClient:
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = f"{base_url}/api"
    
    def create_job(self, workload_id, client_id, data_split_config=None):
        """Create a new flywheel job."""
        payload = {
            "workload_id": workload_id,
            "client_id": client_id
        }
        if data_split_config:
            payload["data_split_config"] = data_split_config
            
        response = requests.post(f"{self.base_url}/jobs", json=payload)
        response.raise_for_status()
        return response.json()
    
    def get_job_status(self, job_id):
        """Get current job status."""
        response = requests.get(f"{self.base_url}/jobs/{job_id}")
        response.raise_for_status()
        return response.json()
    
    def wait_for_completion(self, job_id, timeout=3600):
        """Wait for job to complete with polling."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            status = self.get_job_status(job_id)
            job_status = status["status"]
            
            if job_status in ["completed", "failed", "cancelled"]:
                return status
                
            time.sleep(30)  # Poll every 30 seconds
        raise TimeoutError(f"Job {job_id} did not complete within {timeout} seconds")

# Usage example
client = DataFlywheelClient()

# Create job with custom configuration
data_config = {
    "eval_size": 30,
    "val_ratio": 0.15,
    "min_total_records": 100,
    "limit": 500
}

job = client.create_job(
    workload_id="customer-service-v1",
    client_id="production-app",
    data_split_config=data_config
)
job_id = job['id']
print(f"Created job: {job_id}")

# Monitor progress  
result = client.wait_for_completion(job_id)
print(f"Job completed with status: {result['status']}")
```

## Error Handling

### HTTP Status Codes

- `200` - Success
- `400` - Bad Request (invalid parameters, business rule violations)
- `404` - Job not found
- `422` - Validation Error (invalid request body structure or data types)
- `500` - Internal server error

### Error Response Format

```json
{
  "detail": "Job not found"
}
```

For validation errors (422), the response includes detailed validation information:

```json
{
  "detail": [
    {
      "loc": ["body", "workload_id"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

### Common Error Scenarios

**Job Not Found (404):**
```bash
# Invalid job ID
curl "http://localhost:8000/api/jobs/invalid-id"
```

**Validation Error (422):**
```bash
# Missing required field
curl -X POST "http://localhost:8000/api/jobs" \
  -H "Content-Type: application/json" \
  -d '{"workload_id": "test"}'  # Missing client_id
```

**Cannot Cancel Completed Job (400):**
```json
{
  "detail": "Cannot cancel a job that has already finished."
}
```

## Rate Limiting and Best Practices

1. **Polling Frequency**: When monitoring job status, poll every 30-60 seconds to avoid overwhelming the API
2. **Timeout Handling**: Flywheel jobs can take 1-3 hours depending on data size and model complexity
3. **Error Retry**: Implement exponential backoff for transient errors
4. **Resource Cleanup**: Always delete completed jobs when no longer needed to free up storage

## Integration Patterns

### Webhook Alternative

Since the API doesn't support webhooks, implement polling with exponential backoff:

```python
import time
import random

def poll_with_backoff(client, job_id, max_retries=10):
    """Poll job status with exponential backoff."""
    for attempt in range(max_retries):
        try:
            status = client.get_job_status(job_id)
            if status["status"] in ["completed", "failed", "cancelled"]:
                return status
        except requests.RequestException:
            # Exponential backoff with jitter
            delay = (2 ** attempt) + random.uniform(0, 1)
            time.sleep(min(delay, 300))  # Cap at 5 minutes
    
    raise Exception("Max polling attempts exceeded")
```

### Batch Job Management

```python
def manage_multiple_jobs(client, job_configs):
    """Create and manage multiple flywheel jobs."""
    jobs = []
    
    # Create all jobs
    for config in job_configs:
        job = client.create_job(**config)
        jobs.append(job["id"])
    
    # Monitor all jobs
    completed = []
    while len(completed) < len(jobs):
        for job_id in jobs:
            if job_id not in completed:
                status = client.get_job_status(job_id)
                if status["status"] in ["completed", "failed", "cancelled"]:
                    completed.append(job_id)
                    print(f"Job {job_id} finished: {status['status']}")
        
        time.sleep(60)  # Check every minute
    
    return completed
```

This API reference provides the foundation for integrating any application with the developer example. For advanced workflow configuration, see the [Configuration Guide](./03-configuration.md). 