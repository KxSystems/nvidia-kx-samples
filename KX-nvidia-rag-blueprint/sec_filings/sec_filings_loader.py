#!/usr/bin/env python3
"""
SEC Filings Loader

Downloads SEC 10-K filings and indexes them into the RAG system.
Can be run standalone or as part of a Kubernetes Job after KDB.AI installation.

Environment Variables:
    SEC_LOADER_ENABLED: Set to "true" to enable loading (default: false)
    SEC_LOADER_SYMBOLS: Comma-separated list of symbols (default: built-in list)
    SEC_LOADER_YEARS: Number of years to download (default: 5)
    SEC_INGESTOR_URL: Ingestor server URL (default: http://ingestor-server:8082)
    SEC_COLLECTION_NAME: Collection name (default: sec_filings)
    SEC_UPLOAD_DELAY: Delay between uploads in seconds (default: 60)
    SEC_DATA_DIR: Directory to store downloaded files (default: /tmp/sec_filings)

Usage:
    # Standalone
    python sec_filings_loader.py

    # With environment variables
    SEC_LOADER_ENABLED=true SEC_LOADER_SYMBOLS=AAPL,MSFT python sec_filings_loader.py

    # Download only
    python sec_filings_loader.py --download-only

    # Upload only (from existing files)
    python sec_filings_loader.py --upload-only
"""

import os
import re
import sys
import time
import argparse
import requests
from datetime import datetime
from typing import Optional, List
from pathlib import Path

# =============================================================================
# Configuration from Environment
# =============================================================================

def get_env_bool(key: str, default: bool = False) -> bool:
    """Get boolean from environment variable."""
    val = os.environ.get(key, str(default)).lower()
    return val in ("true", "1", "yes", "on")

def get_env_list(key: str, default: List[str]) -> List[str]:
    """Get list from comma-separated environment variable."""
    val = os.environ.get(key, "")
    if val:
        return [s.strip() for s in val.split(",") if s.strip()]
    return default

def get_env_int(key: str, default: int) -> int:
    """Get integer from environment variable."""
    try:
        return int(os.environ.get(key, default))
    except ValueError:
        return default

# Default configuration
DEFAULT_SYMBOLS = [
    "AAPL",   # Apple Inc.
    "GOOG",   # Alphabet Inc. (Google)
    "MSFT",   # Microsoft Corporation
    "TSLA",   # Tesla, Inc.
    "AMZN",   # Amazon.com, Inc.
    "NVDA",   # NVIDIA Corporation
    "META",   # Meta Platforms, Inc.
    "RIVN",   # Rivian Automotive, Inc.
]

# Load configuration from environment
CONFIG = {
    "enabled": get_env_bool("SEC_LOADER_ENABLED", False),
    "symbols": get_env_list("SEC_LOADER_SYMBOLS", DEFAULT_SYMBOLS),
    "years": get_env_int("SEC_LOADER_YEARS", 5),
    "ingestor_url": os.environ.get("SEC_INGESTOR_URL", "http://ingestor-server:8082"),
    "collection_name": os.environ.get("SEC_COLLECTION_NAME", "sec_filings"),
    "upload_delay": get_env_int("SEC_UPLOAD_DELAY", 60),
    "data_dir": os.environ.get("SEC_DATA_DIR", "/tmp/sec_filings"),
}

# =============================================================================
# SEC EDGAR API
# =============================================================================

SEC_USER_AGENT = "SEC-Filings-Loader/1.0 (nvidia-rag@example.com)"
SEC_API_BASE_URL = "https://data.sec.gov"  # For JSON API calls
SEC_ARCHIVE_BASE_URL = "https://www.sec.gov"  # For document downloads
SEC_REQUEST_DELAY = 0.15  # 150ms between SEC requests

# CIK (Central Index Key) mapping
CIK_MAP = {
    "AAPL": "0000320193",
    "GOOG": "0001652044",
    "GOOGL": "0001652044",
    "MSFT": "0000789019",
    "TSLA": "0001318605",
    "AMZN": "0001018724",
    "NVDA": "0001045810",
    "META": "0001326801",
    "RIVN": "0001874178",
}


def get_sec_headers() -> dict:
    """Get headers for SEC requests."""
    return {"User-Agent": SEC_USER_AGENT, "Accept": "application/json"}


def get_company_cik(ticker: str) -> Optional[str]:
    """Get CIK for a company ticker."""
    if ticker.upper() in CIK_MAP:
        return CIK_MAP[ticker.upper()]

    try:
        url = f"{SEC_API_BASE_URL}/submissions/CIK{ticker.upper()}.json"
        response = requests.get(url, headers=get_sec_headers(), timeout=30)
        if response.status_code == 200:
            return response.json().get("cik", "").zfill(10)
    except Exception as e:
        print(f"  Warning: Could not find CIK for {ticker}: {e}")
    return None


def get_company_filings(cik: str, form_type: str = "10-K", years: int = 5) -> list:
    """Get list of 10-K filings for a company."""
    filings = []
    current_year = datetime.now().year
    min_year = current_year - years

    try:
        url = f"{SEC_API_BASE_URL}/submissions/CIK{cik}.json"
        response = requests.get(url, headers=get_sec_headers(), timeout=30)
        response.raise_for_status()
        data = response.json()

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accession_numbers = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        primary_docs = recent.get("primaryDocument", [])

        for i, form in enumerate(forms):
            if form == form_type:
                filing_date = filing_dates[i]
                filing_year = int(filing_date[:4])

                if filing_year >= min_year:
                    filings.append({
                        "form": form,
                        "accession_number": accession_numbers[i],
                        "filing_date": filing_date,
                        "primary_document": primary_docs[i],
                        "fiscal_year": filing_year,
                    })
    except Exception as e:
        print(f"  Error fetching filings: {e}")

    return filings


def download_filing(cik: str, accession_number: str, primary_document: str) -> Optional[str]:
    """Download a specific SEC filing document.

    Uses www.sec.gov for document downloads (data.sec.gov requires authentication).
    """
    accession_no_dashes = accession_number.replace("-", "")
    cik_stripped = cik.lstrip("0")

    # Primary URL pattern using www.sec.gov
    url = f"{SEC_ARCHIVE_BASE_URL}/Archives/edgar/data/{cik_stripped}/{accession_no_dashes}/{primary_document}"

    try:
        response = requests.get(url, headers=get_sec_headers(), timeout=60)
        if response.status_code == 200:
            return response.text
    except Exception as e:
        print(f"  Error downloading primary document: {e}")

    # Fallback: try alternative document names
    # Some filings use different naming patterns
    alt_names = [
        primary_document,
        primary_document.replace(".htm", ".html"),
        f"{cik_stripped.lower()}-10k.htm",
        f"{cik_stripped.lower()}_10k.htm",
    ]

    for alt_name in alt_names:
        try:
            alt_url = f"{SEC_ARCHIVE_BASE_URL}/Archives/edgar/data/{cik_stripped}/{accession_no_dashes}/{alt_name}"
            response = requests.get(alt_url, headers=get_sec_headers(), timeout=60)
            if response.status_code == 200:
                return response.text
        except Exception:
            continue

    print(f"  Failed to download filing: {accession_number}")
    return None


# =============================================================================
# Download Logic
# =============================================================================

def download_filings_for_symbol(ticker: str, output_dir: Path, years: int = 5) -> List[Path]:
    """Download all 10-K filings for a symbol. Returns list of downloaded file paths."""
    print(f"\n{'='*60}")
    print(f"Downloading {ticker} filings")
    print(f"{'='*60}")

    downloaded_files = []

    cik = get_company_cik(ticker)
    if not cik:
        print(f"  Skipping {ticker}: CIK not found")
        return downloaded_files

    print(f"  CIK: {cik}")
    time.sleep(SEC_REQUEST_DELAY)

    filings = get_company_filings(cik, "10-K", years)
    print(f"  Found {len(filings)} 10-K filings in last {years} years")

    if not filings:
        return downloaded_files

    ticker_dir = output_dir / ticker
    ticker_dir.mkdir(parents=True, exist_ok=True)

    for filing in filings:
        fiscal_year = filing["fiscal_year"]
        output_filename = f"{ticker}_10K_{fiscal_year}.html"
        output_path = ticker_dir / output_filename

        if output_path.exists():
            print(f"  Skipping {output_filename} (already exists)")
            downloaded_files.append(output_path)
            continue

        print(f"  Downloading {output_filename}...")
        time.sleep(SEC_REQUEST_DELAY)

        content = download_filing(cik, filing["accession_number"], filing["primary_document"])

        if content:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"    Saved: {output_path}")
            downloaded_files.append(output_path)
        else:
            print(f"    Failed to download")

        time.sleep(SEC_REQUEST_DELAY)

    return downloaded_files


def download_all_filings(symbols: List[str], output_dir: Path, years: int) -> List[Path]:
    """Download filings for all symbols. Returns list of all downloaded files."""
    all_files = []
    for symbol in symbols:
        files = download_filings_for_symbol(symbol, output_dir, years)
        all_files.extend(files)
    return all_files


# =============================================================================
# Upload/Index Logic
# =============================================================================

def check_ingestor_health(ingestor_url: str, max_retries: int = 30, retry_delay: int = 10) -> bool:
    """Check if ingestor is healthy, with retries."""
    print(f"Checking ingestor health at {ingestor_url}...")

    for attempt in range(max_retries):
        try:
            response = requests.get(f"{ingestor_url}/health", timeout=10)
            if response.status_code == 200:
                print("Ingestor is healthy!")
                return True
        except Exception as e:
            pass

        if attempt < max_retries - 1:
            print(f"  Attempt {attempt + 1}/{max_retries} failed, retrying in {retry_delay}s...")
            time.sleep(retry_delay)

    print("ERROR: Ingestor is not healthy after all retries")
    return False


def upload_file_to_ingestor(
    file_path: Path,
    ingestor_url: str,
    collection_name: str
) -> dict:
    """Upload a single file to the ingestor."""
    url = f"{ingestor_url}/documents"

    try:
        with open(file_path, "rb") as f:
            files = {"documents": (file_path.name, f, "text/html")}
            data = {"data": f'{{"collection_name": "{collection_name}", "blocking": false}}'}

            response = requests.post(url, files=files, data=data, timeout=300)
            response.raise_for_status()

            return {"status": "submitted", "response": response.json()}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def wait_for_task(ingestor_url: str, task_id: str, max_wait: int = 600) -> dict:
    """Wait for an ingestion task to complete."""
    start_time = time.time()
    url = f"{ingestor_url}/task/{task_id}"

    while time.time() - start_time < max_wait:
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                data = response.json()
                status = data.get("status", "unknown")
                if status in ("completed", "failed"):
                    return data
            elif response.status_code == 404:
                return {"status": "completed"}
        except Exception:
            pass
        time.sleep(5)

    return {"status": "timeout"}


def upload_all_filings(
    files: List[Path],
    ingestor_url: str,
    collection_name: str,
    upload_delay: int = 60
) -> tuple:
    """Upload all files to the ingestor. Returns (success_count, fail_count)."""
    if not files:
        print("No files to upload")
        return 0, 0

    success = 0
    failed = 0

    for i, file_path in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}] Uploading {file_path.parent.name}/{file_path.name}...")

        result = upload_file_to_ingestor(file_path, ingestor_url, collection_name)

        if result["status"] == "submitted":
            task_id = result["response"].get("task_id")
            print(f"  Submitted: task_id={task_id}")
            print(f"  Waiting for completion...")

            task_result = wait_for_task(ingestor_url, task_id)
            task_status = task_result.get("status", "unknown")
            print(f"  Task status: {task_status}")

            if task_status == "completed":
                success += 1
            else:
                failed += 1
        else:
            print(f"  Error: {result.get('error', 'Unknown error')}")
            failed += 1

        # Delay between uploads
        if i < len(files):
            print(f"  Waiting {upload_delay}s before next upload...")
            time.sleep(upload_delay)

    return success, failed


# =============================================================================
# Main Entry Point
# =============================================================================

def run_loader(
    symbols: List[str],
    years: int,
    data_dir: Path,
    ingestor_url: str,
    collection_name: str,
    upload_delay: int,
    download_only: bool = False,
    upload_only: bool = False
) -> bool:
    """Run the complete SEC filings loader pipeline."""
    print("=" * 60)
    print("SEC Filings Loader")
    print("=" * 60)
    print(f"Symbols: {', '.join(symbols)}")
    print(f"Years: {years}")
    print(f"Data Directory: {data_dir}")
    print(f"Ingestor URL: {ingestor_url}")
    print(f"Collection: {collection_name}")
    print()

    data_dir.mkdir(parents=True, exist_ok=True)

    # Download phase
    if not upload_only:
        print("\n" + "=" * 60)
        print("PHASE 1: Downloading SEC Filings")
        print("=" * 60)

        files = download_all_filings(symbols, data_dir, years)
        print(f"\nDownloaded {len(files)} files total")

        if download_only:
            print("\nDownload-only mode - skipping upload")
            return True
    else:
        # Collect existing files for upload
        files = []
        for symbol in symbols:
            symbol_dir = data_dir / symbol
            if symbol_dir.exists():
                files.extend(symbol_dir.glob("*.html"))
        files.sort(key=lambda x: (x.parent.name, x.name))
        print(f"Found {len(files)} existing files to upload")

    # Upload phase
    if files:
        print("\n" + "=" * 60)
        print("PHASE 2: Indexing into RAG System")
        print("=" * 60)

        if not check_ingestor_health(ingestor_url):
            return False

        success, failed = upload_all_filings(files, ingestor_url, collection_name, upload_delay)

        print("\n" + "=" * 60)
        print("SEC Filings Loader Complete!")
        print(f"  Successfully indexed: {success}")
        print(f"  Failed: {failed}")
        print("=" * 60)

        return failed == 0

    return True


def main():
    parser = argparse.ArgumentParser(description="SEC Filings Loader")
    parser.add_argument("--download-only", action="store_true", help="Only download, don't upload")
    parser.add_argument("--upload-only", action="store_true", help="Only upload existing files")
    parser.add_argument("--force", action="store_true", help="Run even if SEC_LOADER_ENABLED is false")
    parser.add_argument("--symbols", type=str, help="Comma-separated list of symbols")
    parser.add_argument("--years", type=int, help="Number of years to download")
    parser.add_argument("--ingestor-url", type=str, help="Ingestor server URL")
    parser.add_argument("--collection", type=str, help="Collection name")
    parser.add_argument("--data-dir", type=str, help="Data directory")

    args = parser.parse_args()

    # Check if enabled
    if not CONFIG["enabled"] and not args.force:
        print("SEC Loader is disabled. Set SEC_LOADER_ENABLED=true or use --force")
        sys.exit(0)

    # Override config with CLI args
    symbols = args.symbols.split(",") if args.symbols else CONFIG["symbols"]
    years = args.years if args.years else CONFIG["years"]
    ingestor_url = args.ingestor_url if args.ingestor_url else CONFIG["ingestor_url"]
    collection_name = args.collection if args.collection else CONFIG["collection_name"]
    data_dir = Path(args.data_dir) if args.data_dir else Path(CONFIG["data_dir"])

    success = run_loader(
        symbols=symbols,
        years=years,
        data_dir=data_dir,
        ingestor_url=ingestor_url,
        collection_name=collection_name,
        upload_delay=CONFIG["upload_delay"],
        download_only=args.download_only,
        upload_only=args.upload_only
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
