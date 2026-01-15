#!/bin/bash
#
# SEC Filings Loader - Local Runner
#
# Downloads SEC 10-K filings and uploads them to the RAG ingestor.
#
# Usage:
#   ./run_loader.sh                    # Download and upload all
#   ./run_loader.sh --download-only    # Only download files
#   ./run_loader.sh --upload-only      # Only upload existing files
#   ./run_loader.sh --symbols AAPL,MSFT  # Specific symbols
#

set -e

# Configuration - modify these as needed
export SEC_LOADER_ENABLED=true
export SEC_LOADER_SYMBOLS="${SEC_LOADER_SYMBOLS:-AAPL,GOOG,MSFT,TSLA,AMZN,NVDA,META,RIVN}"
export SEC_LOADER_YEARS="${SEC_LOADER_YEARS:-5}"
export SEC_INGESTOR_URL="${SEC_INGESTOR_URL:-http://localhost:8082}"
export SEC_COLLECTION_NAME="${SEC_COLLECTION_NAME:-sec_filings}"
export SEC_UPLOAD_DELAY="${SEC_UPLOAD_DELAY:-60}"
export SEC_DATA_DIR="${SEC_DATA_DIR:-$(pwd)}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "============================================================"
echo "SEC Filings Loader"
echo "============================================================"
echo "Symbols: $SEC_LOADER_SYMBOLS"
echo "Years: $SEC_LOADER_YEARS"
echo "Ingestor URL: $SEC_INGESTOR_URL"
echo "Collection: $SEC_COLLECTION_NAME"
echo "Data Directory: $SEC_DATA_DIR"
echo ""

# Check if ingestor is accessible (unless download-only)
if [[ "$*" != *"--download-only"* ]]; then
    echo "Checking ingestor health..."
    if ! curl -sf "${SEC_INGESTOR_URL}/health" > /dev/null 2>&1; then
        echo "WARNING: Ingestor is not accessible at ${SEC_INGESTOR_URL}"
        echo "Make sure port-forward is running:"
        echo "  kubectl port-forward -n rag svc/ingestor-server 8082:8082"
        echo ""
        read -p "Continue anyway? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    else
        echo "Ingestor is healthy!"
    fi
fi

# Run the loader
python3 "${SCRIPT_DIR}/sec_filings_loader.py" --force "$@"
