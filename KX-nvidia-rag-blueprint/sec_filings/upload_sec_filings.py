#!/usr/bin/env python3
"""
SEC Filings Uploader

Uploads downloaded SEC filings to the RAG ingestor for vectorization and storage.

Usage:
    python upload_sec_filings.py [--ingestor-url http://localhost:8082] [--collection sec_filings]
"""

import os
import sys
import time
import argparse
import requests
from pathlib import Path
from typing import Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed

# Default settings
DEFAULT_INGESTOR_URL = "http://localhost:8082"
DEFAULT_COLLECTION = "sec_filings"
UPLOAD_TIMEOUT = 300  # 5 minutes per file
POLL_INTERVAL = 5  # seconds between status checks
MAX_WAIT_TIME = 600  # 10 minutes max wait per file

# Symbols to process
SYMBOLS = [
    "AAPL",
    "GOOG",
    "GOOGL",
    "MSFT",
    "TSLA",
    "AMZN",
    "NVDA",
    "META",
    "RIVN",
]


def get_filing_files(base_dir: Path, symbols: Optional[List[str]] = None) -> List[Path]:
    """
    Get all filing files to upload.

    Args:
        base_dir: Base directory containing symbol folders
        symbols: Optional list of symbols to filter

    Returns:
        List of file paths
    """
    files = []
    target_symbols = symbols if symbols else SYMBOLS

    for symbol in target_symbols:
        symbol_dir = base_dir / symbol
        if symbol_dir.exists():
            for file in symbol_dir.glob("*.html"):
                files.append(file)

    # Sort by symbol and year
    files.sort(key=lambda x: (x.parent.name, x.name))
    return files


def upload_file(
    file_path: Path,
    ingestor_url: str,
    collection_name: str,
    blocking: bool = False
) -> dict:
    """
    Upload a single file to the ingestor.

    Args:
        file_path: Path to the file
        ingestor_url: Ingestor server URL
        collection_name: Target collection name
        blocking: Whether to wait for completion

    Returns:
        Response dict with status
    """
    url = f"{ingestor_url}/documents"

    try:
        with open(file_path, "rb") as f:
            files = {"documents": (file_path.name, f, "text/html")}
            data = {"data": f'{{"collection_name": "{collection_name}", "blocking": {str(blocking).lower()}}}'}

            response = requests.post(url, files=files, data=data, timeout=UPLOAD_TIMEOUT)
            response.raise_for_status()

            return {
                "status": "submitted",
                "file": str(file_path),
                "response": response.json()
            }

    except requests.exceptions.RequestException as e:
        return {
            "status": "error",
            "file": str(file_path),
            "error": str(e)
        }


def wait_for_task(ingestor_url: str, task_id: str, max_wait: int = MAX_WAIT_TIME) -> dict:
    """
    Wait for an ingestion task to complete.

    Args:
        ingestor_url: Ingestor server URL
        task_id: Task ID to monitor
        max_wait: Maximum wait time in seconds

    Returns:
        Task status dict
    """
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
                # Task completed and was cleaned up
                return {"status": "completed", "message": "Task completed"}
        except Exception:
            pass

        time.sleep(POLL_INTERVAL)

    return {"status": "timeout", "message": f"Task did not complete within {max_wait}s"}


def check_ingestor_health(ingestor_url: str) -> bool:
    """Check if ingestor is healthy."""
    try:
        response = requests.get(f"{ingestor_url}/health", timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Upload SEC filings to RAG ingestor"
    )
    parser.add_argument(
        "--ingestor-url",
        type=str,
        default=DEFAULT_INGESTOR_URL,
        help=f"Ingestor server URL (default: {DEFAULT_INGESTOR_URL})"
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=DEFAULT_COLLECTION,
        help=f"Target collection name (default: {DEFAULT_COLLECTION})"
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default=".",
        help="Directory containing symbol folders (default: current directory)"
    )
    parser.add_argument(
        "--symbols",
        type=str,
        nargs="+",
        default=None,
        help="Specific symbols to upload (default: all)"
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Wait for each upload to complete before proceeding"
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=60,
        help="Delay between uploads in seconds (default: 60)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files without uploading"
    )

    args = parser.parse_args()

    data_dir = Path(args.data_dir)

    print("=" * 60)
    print("SEC Filings Uploader")
    print("=" * 60)
    print(f"Ingestor URL: {args.ingestor_url}")
    print(f"Collection: {args.collection}")
    print(f"Data Directory: {data_dir.absolute()}")
    print()

    # Check ingestor health
    if not args.dry_run:
        print("Checking ingestor health...")
        if not check_ingestor_health(args.ingestor_url):
            print("ERROR: Ingestor is not healthy or not reachable")
            print(f"Please ensure ingestor is running at {args.ingestor_url}")
            sys.exit(1)
        print("Ingestor is healthy!")
        print()

    # Get files to upload
    files = get_filing_files(data_dir, args.symbols)

    if not files:
        print("No filing files found to upload.")
        print(f"Make sure the data directory contains symbol folders with .html files")
        sys.exit(0)

    print(f"Found {len(files)} files to upload:")
    for f in files:
        print(f"  - {f.parent.name}/{f.name}")
    print()

    if args.dry_run:
        print("Dry run - no files uploaded")
        return

    # Upload files
    uploaded = 0
    failed = 0

    for i, file_path in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}] Uploading {file_path.parent.name}/{file_path.name}...")

        result = upload_file(
            file_path,
            args.ingestor_url,
            args.collection,
            blocking=False
        )

        if result["status"] == "submitted":
            task_id = result["response"].get("task_id")
            print(f"  Submitted: task_id={task_id}")

            if args.wait and task_id:
                print(f"  Waiting for completion...")
                task_result = wait_for_task(args.ingestor_url, task_id)
                task_status = task_result.get("status", "unknown")
                print(f"  Task status: {task_status}")

                if task_status == "completed":
                    uploaded += 1
                else:
                    failed += 1
            else:
                uploaded += 1

            # Delay between uploads to avoid overwhelming the system
            if i < len(files):
                print(f"  Waiting {args.delay}s before next upload...")
                time.sleep(args.delay)

        else:
            print(f"  Error: {result.get('error', 'Unknown error')}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Upload complete!")
    print(f"  Submitted: {uploaded}")
    print(f"  Failed: {failed}")
    print("=" * 60)


if __name__ == "__main__":
    main()
