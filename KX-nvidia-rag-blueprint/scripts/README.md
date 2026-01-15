# Scripts

Utility scripts for the NVIDIA RAG Blueprint.

> **Prerequisites:** Deploy and start services following the [Quickstart guide](../docs/deploy-docker-self-hosted.md). Ensure RAG server (8081) and Ingestor server (8082) are running.

## Installation

```bash
pip install -r scripts/requirements.txt
```

---

## SEC Filings Downloader

Download SEC 10-K filings from EDGAR for testing RAG with real financial documents.

### Usage

```bash
# Download default companies (AAPL, MSFT, NVDA, GOOGL, AMZN)
python scripts/download_sec_filings.py

# Download specific companies
python scripts/download_sec_filings.py BA                 # Boeing only
python scripts/download_sec_filings.py BA NVDA AAPL      # Multiple companies

# Filter by year range
python scripts/download_sec_filings.py BA --years 2020-2024
python scripts/download_sec_filings.py NVDA --years 2023

# List all available companies
python scripts/download_sec_filings.py --list
```

### Available Companies

| Ticker | Company | Ticker | Company |
|--------|---------|--------|---------|
| AAPL | Apple | BA | Boeing |
| MSFT | Microsoft | TSLA | Tesla |
| NVDA | NVIDIA | META | Meta |
| GOOGL | Alphabet | JPM | JPMorgan Chase |
| AMZN | Amazon | V | Visa |
| JNJ | Johnson & Johnson | WMT | Walmart |
| PG | Procter & Gamble | XOM | Exxon Mobil |
| UNH | UnitedHealth | HD | Home Depot |
| DIS | Disney | INTC | Intel |
| AMD | AMD | CRM | Salesforce |

### Output Structure

```
sec_filings/
├── BA/
│   ├── BA_10K_2024.html
│   ├── BA_10K_2023.html
│   └── ...
└── NVDA/
    └── ...
```

### Uploading to RAG

**Step 1: Create the collection**

```bash
curl -X POST http://localhost:8082/collection \
  -H "Content-Type: application/json" \
  -d '{"collection_name": "sec_filings"}'
```

**Step 2: Upload documents**

```bash
# Single file
curl -X POST http://localhost:8082/documents \
  -F 'documents=@sec_filings/BA/BA_10K_2024.html' \
  -F 'data={"collection_name":"sec_filings"}'

# All files for a company
for f in sec_filings/BA/*.html; do
  curl -X POST http://localhost:8082/documents \
    -F "documents=@$f" \
    -F 'data={"collection_name":"sec_filings"}'
done
```

**Or use the batch ingestion script (recommended):**

```bash
python scripts/batch_ingestion.py \
  --folder sec_filings/BA/ \
  --collection-name sec_filings \
  --create_collection \
  -v
```

### Adding New Companies

Find the CIK at [SEC EDGAR](https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany) and add to `ALL_COMPANIES` in the script:

```python
"TICKER": "0001234567",  # Company Name
```

---

## Batch Ingestion CLI

Bulk upload datasets to the ingestor server with progress tracking and automatic retries.

### Usage

```bash
python scripts/batch_ingestion.py \
  --folder data/multimodal/ \
  --collection-name my_collection \
  --upload-batch-size 100 \
  -v
```

### Collection Management

```bash
# Create collection before uploading
python scripts/batch_ingestion.py \
  --folder data/ \
  --collection-name my_collection \
  --create_collection

# Delete collection after run
python scripts/batch_ingestion.py \
  --folder data/ \
  --collection-name my_collection \
  --delete_collection

# Create and delete (temporary runs)
python scripts/batch_ingestion.py \
  --folder data/ \
  --collection-name my_collection \
  --create_collection --delete_collection
```

### Features

- **Idempotent:** Skips already ingested files
- **Progress tracking:** Shows batch progress (e.g., "Uploading batch 2/43")
- **Task polling:** Waits for each batch to complete before proceeding

---

## Retriever API CLI

Query the RAG server from the command line.

### Generate (default)

```bash
python scripts/retriever_api_usage.py "What is RAG?"
```

### Search

```bash
python scripts/retriever_api_usage.py --mode search "Tell me about RAG"
```

### Specify Collection

```bash
# Generate
python scripts/retriever_api_usage.py \
  --payload-json '{"collection_names":["sec_filings"]}' \
  "What was Boeing's revenue in 2023?"

# Search
python scripts/retriever_api_usage.py \
  --mode search \
  --payload-json '{"collection_names":["sec_filings"]}' \
  "Boeing financial performance"
```

### Custom Payload

```bash
# JSON string
python scripts/retriever_api_usage.py \
  --payload-json '{"messages":[{"role":"user","content":"Your query"}]}'

# From file
python scripts/retriever_api_usage.py --payload-file scripts/payloads/search.json
```

### Options

```bash
# Save output to file
python scripts/retriever_api_usage.py --output-json result.json "my query"

# Different host
python scripts/retriever_api_usage.py --host http://my-host:8081 "my query"
```

---

## API Reference

### Create Collection

```bash
curl -X POST http://localhost:8082/collection \
  -H "Content-Type: application/json" \
  -d '{"collection_name": "my_collection"}'
```

### Upload Documents

```bash
curl -X POST http://localhost:8082/documents \
  -F 'documents=@path/to/file.pdf' \
  -F 'data={"collection_name":"my_collection"}'
```

### List Collections

```bash
curl http://localhost:8082/collections
```

### Delete Collection

```bash
curl -X DELETE "http://localhost:8082/collections?collection_names=my_collection"
```

### Generate Response

```bash
curl -X POST http://localhost:8081/generate \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What is RAG?"}],
    "collection_names": ["my_collection"]
  }'
```
