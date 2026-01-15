# SEC Filings Loader

Downloads SEC 10-K annual reports and indexes them into the NVIDIA RAG system for semantic search.

## Supported Symbols

| Symbol | Company |
|--------|---------|
| AAPL | Apple Inc. |
| GOOG | Alphabet Inc. (Google) |
| MSFT | Microsoft Corporation |
| TSLA | Tesla, Inc. |
| AMZN | Amazon.com, Inc. |
| NVDA | NVIDIA Corporation |
| META | Meta Platforms, Inc. |
| RIVN | Rivian Automotive, Inc. |

**Note:** BYD files with Chinese CSRC (not SEC), and SPY is an ETF that doesn't file 10-K forms.

## Quick Start

### 1. Local Usage (with port-forward)

```bash
# Start port-forward to ingestor
kubectl port-forward -n rag svc/ingestor-server 8082:8082 &

# Run the loader
./run_loader.sh

# Or with specific options
./run_loader.sh --download-only          # Only download, don't upload
./run_loader.sh --upload-only             # Upload existing files
SEC_LOADER_SYMBOLS=AAPL,MSFT ./run_loader.sh  # Specific symbols
```

### 2. Python Direct Usage

```bash
# Install dependencies
pip install requests

# Download and index all filings
python sec_filings_loader.py --force

# Download only
python sec_filings_loader.py --force --download-only

# Upload existing files only
python sec_filings_loader.py --force --upload-only

# Custom options
python sec_filings_loader.py --force \
  --symbols AAPL,MSFT,NVDA \
  --years 3 \
  --ingestor-url http://localhost:8082 \
  --collection sec_filings
```

### 3. Kubernetes Job (Automatic)

Deploy the SEC loader job after KDB.AI installation:

```bash
# Apply the job manifests
kubectl apply -f deploy/sec-loader-job.yaml -n rag

# Monitor the job
kubectl logs -f job/sec-loader -n rag

# Check job status
kubectl get jobs -n rag
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SEC_LOADER_ENABLED` | `false` | Enable/disable the loader |
| `SEC_LOADER_SYMBOLS` | `AAPL,GOOG,MSFT,TSLA,AMZN,NVDA,META,RIVN` | Comma-separated symbols |
| `SEC_LOADER_YEARS` | `5` | Number of years of filings |
| `SEC_INGESTOR_URL` | `http://ingestor-server:8082` | Ingestor server URL |
| `SEC_COLLECTION_NAME` | `sec_filings` | Vector store collection |
| `SEC_UPLOAD_DELAY` | `60` | Seconds between uploads |
| `SEC_DATA_DIR` | `/tmp/sec_filings` | Directory for downloads |

### Helm Integration

Add to your Helm values file to enable automatic loading after KDB.AI deployment:

```yaml
secLoader:
  enabled: true
  symbols:
    - AAPL
    - GOOG
    - MSFT
    - TSLA
    - AMZN
    - NVDA
    - META
    - RIVN
  years: 5
  collectionName: sec_filings
```

## File Structure

```
sec_filings/
├── AAPL/
│   ├── AAPL_10K_2024.html
│   ├── AAPL_10K_2023.html
│   └── ...
├── MSFT/
│   └── ...
├── sec_filings_loader.py    # Main loader script
├── run_loader.sh            # Shell wrapper
├── deploy/
│   ├── sec-loader-job.yaml  # Kubernetes manifests
│   └── values-sec-loader.yaml
└── README.md
```

## How It Works

1. **Download Phase**: Fetches 10-K filings from SEC EDGAR API
   - Uses CIK (Central Index Key) to identify companies
   - Downloads the primary HTML document for each filing
   - Saves to local filesystem organized by symbol

2. **Index Phase**: Uploads filings to RAG ingestor
   - Waits for ingestor to be healthy
   - Uploads each file sequentially with configurable delay
   - Monitors task completion before proceeding

## SEC EDGAR Rate Limits

The SEC limits API requests to 10 per second. This script uses a 150ms delay between requests to stay well under the limit.

## Troubleshooting

### Ingestor not accessible
```bash
# Check if ingestor pod is running
kubectl get pods -n rag | grep ingestor

# Start port-forward
kubectl port-forward -n rag svc/ingestor-server 8082:8082
```

### Collection doesn't exist
The ingestor will create the collection automatically if it doesn't exist.

### Upload fails
Check ingestor logs:
```bash
kubectl logs -n rag deploy/ingestor-server --tail=100
```
