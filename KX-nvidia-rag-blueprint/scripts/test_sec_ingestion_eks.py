#!/usr/bin/env python3
"""
SEC Filings Ingestion Test for EKS with CAGRA Index

This script:
1. Creates a collection for SEC filings
2. Ingests all SEC filings using batch ingestion
3. Tracks and reports metrics:
   - Rows per batch (KDBAI_INSERT_BATCH_SIZE)
   - Number of batches
   - Overall row count in KDB.AI

Prerequisites:
- Port-forward to EKS services:
  kubectl port-forward svc/ingestor-server 8082:8082 -n rag &
  kubectl port-forward svc/kdbai 8084:8082 -n rag &

Usage:
  python scripts/test_sec_ingestion_eks.py
  python scripts/test_sec_ingestion_eks.py --ingestor-host localhost --ingestor-port 8082
  python scripts/test_sec_ingestion_eks.py --kdbai-host localhost --kdbai-port 8084
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Try to import kdbai_client for metrics
try:
    import kdbai_client as kdbai
    KDBAI_AVAILABLE = True
except ImportError:
    KDBAI_AVAILABLE = False
    print("Warning: kdbai_client not installed. Install with: pip install kdbai-client")

import requests


# Configuration defaults
DEFAULT_COLLECTION_NAME = "sec_filings_cagra_test"
DEFAULT_INGESTOR_HOST = "localhost"
DEFAULT_INGESTOR_PORT = 8082
DEFAULT_KDBAI_HOST = "localhost"
DEFAULT_KDBAI_PORT = 8084  # Port-forwarded from 8082 on EKS
DEFAULT_UPLOAD_BATCH_SIZE = 10  # Files per upload batch
DEFAULT_KDBAI_INSERT_BATCH_SIZE = 200  # Rows per KDB.AI insert batch (env: KDBAI_INSERT_BATCH_SIZE)

# SEC filings directory
SEC_FILINGS_DIR = Path(__file__).parent / "sec_filings"


class MetricsTracker:
    """Track ingestion metrics."""

    def __init__(self):
        self.start_time = None
        self.end_time = None
        self.total_files = 0
        self.total_file_batches = 0
        self.files_per_batch = []
        self.total_rows = 0
        self.kdbai_insert_batch_size = DEFAULT_KDBAI_INSERT_BATCH_SIZE
        self.collection_name = None
        self.errors = []

    def start(self):
        self.start_time = datetime.now()

    def stop(self):
        self.end_time = datetime.now()

    @property
    def duration_seconds(self):
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0

    @property
    def estimated_kdbai_batches(self):
        """Estimate number of KDB.AI insert batches based on rows and batch size."""
        if self.total_rows > 0 and self.kdbai_insert_batch_size > 0:
            import math
            return math.ceil(self.total_rows / self.kdbai_insert_batch_size)
        return 0

    def report(self):
        """Generate a formatted metrics report."""
        report = []
        report.append("\n" + "=" * 70)
        report.append("SEC FILINGS INGESTION TEST - METRICS REPORT")
        report.append("=" * 70)
        report.append(f"Collection Name: {self.collection_name}")
        report.append(f"Index Type: CAGRA (GPU-accelerated)")
        report.append("")
        report.append("--- FILE INGESTION METRICS ---")
        report.append(f"Total Files Ingested: {self.total_files}")
        report.append(f"File Upload Batches: {self.total_file_batches}")
        report.append(f"Files per Upload Batch: {DEFAULT_UPLOAD_BATCH_SIZE}")
        report.append("")
        report.append("--- KDB.AI VECTOR STORE METRICS ---")
        report.append(f"Total Rows (chunks) in KDB.AI: {self.total_rows:,}")
        report.append(f"KDB.AI Insert Batch Size: {self.kdbai_insert_batch_size}")
        report.append(f"Estimated KDB.AI Insert Batches: {self.estimated_kdbai_batches}")
        report.append(f"Rows per KDB.AI Batch: {self.kdbai_insert_batch_size}")
        report.append("")
        report.append("--- PERFORMANCE ---")
        report.append(f"Total Duration: {self.duration_seconds:.1f} seconds")
        if self.total_rows > 0 and self.duration_seconds > 0:
            report.append(f"Throughput: {self.total_rows / self.duration_seconds:.1f} rows/second")
        report.append("")
        if self.errors:
            report.append("--- ERRORS ---")
            for err in self.errors:
                report.append(f"  - {err}")
            report.append("")
        report.append("=" * 70)
        return "\n".join(report)


def check_service_health(host: str, port: int, service_name: str) -> bool:
    """Check if a service is reachable."""
    try:
        url = f"http://{host}:{port}/health"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            print(f"[OK] {service_name} is healthy at {host}:{port}")
            return True
    except Exception as e:
        pass

    # Try alternate health endpoints
    try:
        url = f"http://{host}:{port}/v1/health"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            print(f"[OK] {service_name} is healthy at {host}:{port}")
            return True
    except Exception:
        pass

    print(f"[WARN] {service_name} not reachable at {host}:{port}")
    return False


def create_collection(host: str, port: int, collection_name: str) -> bool:
    """Create a collection for SEC filings."""
    url = f"http://{host}:{port}/v1/collection"
    payload = {
        "collection_name": collection_name,
        "embedding_dimension": 2048,
        "metadata_schema": []
    }

    try:
        print(f"Creating collection '{collection_name}'...")
        resp = requests.post(url, json=payload, timeout=60)
        if resp.status_code == 200 or resp.status_code == 201:
            print(f"[OK] Collection '{collection_name}' created successfully")
            return True
        elif resp.status_code == 409 or "already exists" in resp.text.lower():
            print(f"[OK] Collection '{collection_name}' already exists")
            return True
        else:
            print(f"[ERROR] Failed to create collection: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        print(f"[ERROR] Failed to create collection: {e}")
        return False


def delete_collection(host: str, port: int, collection_name: str) -> bool:
    """Delete a collection."""
    url = f"http://{host}:{port}/v1/collections"

    try:
        print(f"Deleting collection '{collection_name}'...")
        resp = requests.delete(url, json=[collection_name], timeout=60)
        if resp.status_code == 200:
            print(f"[OK] Collection '{collection_name}' deleted")
            return True
        else:
            print(f"[WARN] Delete collection response: {resp.status_code}")
            return False
    except Exception as e:
        print(f"[WARN] Could not delete collection: {e}")
        return False


def get_row_count_from_kdbai(host: str, port: int, collection_name: str) -> int:
    """Query KDB.AI to get the total row count for a collection."""
    if not KDBAI_AVAILABLE:
        print("[WARN] kdbai_client not available, cannot query row count")
        return 0

    try:
        session = kdbai.Session(endpoint=f"http://{host}:{port}")
        db = session.database("default")

        # Try to find the table
        tables = db.tables
        print(f"[DEBUG] Available tables in KDB.AI: {tables}")

        # The table name might be the collection name or with a prefix
        table_name = collection_name
        if table_name not in tables:
            # Try variations
            for t in tables:
                if collection_name.lower() in t.lower():
                    table_name = t
                    break

        if table_name in tables:
            table = db.table(table_name)
            row_count = len(table)
            print(f"[OK] Table '{table_name}' has {row_count:,} rows")
            return row_count
        else:
            print(f"[WARN] Table '{collection_name}' not found in KDB.AI")
            return 0

    except Exception as e:
        print(f"[ERROR] Failed to query KDB.AI: {e}")
        return 0


def run_batch_ingestion(
    folder: Path,
    collection_name: str,
    ingestor_host: str,
    ingestor_port: int,
    upload_batch_size: int
) -> tuple[int, int]:
    """Run the batch_ingestion.py script and return (total_files, total_batches)."""

    script_path = Path(__file__).parent / "batch_ingestion.py"

    cmd = [
        sys.executable,
        str(script_path),
        "--folder", str(folder),
        "--collection-name", collection_name,
        "--ingestor-host", ingestor_host,
        "--ingestor-port", str(ingestor_port),
        "--upload-batch-size", str(upload_batch_size),
        "--allowed-exts", ".html",
        "-v"
    ]

    print(f"\n[INFO] Running batch ingestion...")
    print(f"[INFO] Command: {' '.join(cmd)}")
    print("-" * 60)

    # Run and capture output
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    total_files = 0
    total_batches = 0

    for line in process.stdout:
        print(line, end="")
        # Parse output to extract metrics
        if "Discovered" in line and "files" in line:
            parts = line.split()
            for i, p in enumerate(parts):
                if p == "Discovered":
                    try:
                        total_files = int(parts[i + 1])
                    except (IndexError, ValueError):
                        pass
                if "batch(es)" in p or "batch" in p:
                    try:
                        total_batches = int(parts[i - 1])
                    except (IndexError, ValueError):
                        pass

    process.wait()
    print("-" * 60)

    if process.returncode != 0:
        print(f"[WARN] Batch ingestion exited with code {process.returncode}")

    return total_files, total_batches


def main():
    parser = argparse.ArgumentParser(
        description="Test SEC filings ingestion on EKS with CAGRA index",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Prerequisites:
  Set up port-forwarding to EKS before running:

  kubectl port-forward svc/ingestor-server 8082:8082 -n rag &
  kubectl port-forward svc/kdbai 8084:8082 -n rag &

Examples:
  python scripts/test_sec_ingestion_eks.py
  python scripts/test_sec_ingestion_eks.py --collection-name my_test
  python scripts/test_sec_ingestion_eks.py --clean  # Delete collection first
        """
    )

    parser.add_argument(
        "--collection-name",
        default=DEFAULT_COLLECTION_NAME,
        help=f"Collection name (default: {DEFAULT_COLLECTION_NAME})"
    )
    parser.add_argument(
        "--ingestor-host",
        default=DEFAULT_INGESTOR_HOST,
        help=f"Ingestor server host (default: {DEFAULT_INGESTOR_HOST})"
    )
    parser.add_argument(
        "--ingestor-port",
        type=int,
        default=DEFAULT_INGESTOR_PORT,
        help=f"Ingestor server port (default: {DEFAULT_INGESTOR_PORT})"
    )
    parser.add_argument(
        "--kdbai-host",
        default=DEFAULT_KDBAI_HOST,
        help=f"KDB.AI host (default: {DEFAULT_KDBAI_HOST})"
    )
    parser.add_argument(
        "--kdbai-port",
        type=int,
        default=DEFAULT_KDBAI_PORT,
        help=f"KDB.AI port (default: {DEFAULT_KDBAI_PORT})"
    )
    parser.add_argument(
        "--upload-batch-size",
        type=int,
        default=DEFAULT_UPLOAD_BATCH_SIZE,
        help=f"Files per upload batch (default: {DEFAULT_UPLOAD_BATCH_SIZE})"
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete existing collection before starting"
    )
    parser.add_argument(
        "--skip-ingestion",
        action="store_true",
        help="Skip ingestion, only query metrics"
    )

    args = parser.parse_args()

    # Initialize metrics tracker
    metrics = MetricsTracker()
    metrics.collection_name = args.collection_name
    metrics.kdbai_insert_batch_size = int(os.getenv("KDBAI_INSERT_BATCH_SIZE", DEFAULT_KDBAI_INSERT_BATCH_SIZE))

    print("=" * 70)
    print("SEC FILINGS INGESTION TEST - EKS with CAGRA Index")
    print("=" * 70)
    print(f"Collection: {args.collection_name}")
    print(f"Ingestor: {args.ingestor_host}:{args.ingestor_port}")
    print(f"KDB.AI: {args.kdbai_host}:{args.kdbai_port}")
    print(f"KDBAI_INSERT_BATCH_SIZE: {metrics.kdbai_insert_batch_size}")
    print("=" * 70)

    # Check if SEC filings exist
    if not SEC_FILINGS_DIR.exists():
        print(f"[ERROR] SEC filings directory not found: {SEC_FILINGS_DIR}")
        print("Run: python scripts/download_sec_filings.py")
        return 1

    html_files = list(SEC_FILINGS_DIR.rglob("*.html"))
    print(f"\n[INFO] Found {len(html_files)} SEC filing files in {SEC_FILINGS_DIR}")

    if not args.skip_ingestion:
        # Check service health
        print("\n--- Checking Service Health ---")
        ingestor_ok = check_service_health(args.ingestor_host, args.ingestor_port, "Ingestor Server")

        if not ingestor_ok:
            print("\n[ERROR] Ingestor server not reachable.")
            print("Please set up port-forwarding:")
            print("  kubectl port-forward svc/ingestor-server 8082:8082 -n rag &")
            return 1

        # Clean if requested
        if args.clean:
            print("\n--- Cleaning Up ---")
            delete_collection(args.ingestor_host, args.ingestor_port, args.collection_name)
            time.sleep(2)

        # Create collection
        print("\n--- Creating Collection ---")
        if not create_collection(args.ingestor_host, args.ingestor_port, args.collection_name):
            metrics.errors.append("Failed to create collection")
            return 1

        # Run ingestion
        print("\n--- Running Ingestion ---")
        metrics.start()

        total_files, total_batches = run_batch_ingestion(
            folder=SEC_FILINGS_DIR,
            collection_name=args.collection_name,
            ingestor_host=args.ingestor_host,
            ingestor_port=args.ingestor_port,
            upload_batch_size=args.upload_batch_size
        )

        metrics.stop()
        metrics.total_files = total_files
        metrics.total_file_batches = total_batches

    # Query KDB.AI for row count
    print("\n--- Querying KDB.AI Metrics ---")
    kdbai_ok = check_service_health(args.kdbai_host, args.kdbai_port, "KDB.AI")

    if kdbai_ok or KDBAI_AVAILABLE:
        metrics.total_rows = get_row_count_from_kdbai(
            args.kdbai_host,
            args.kdbai_port,
            args.collection_name
        )
    else:
        print("[WARN] Cannot query KDB.AI for row count")
        print("Please set up port-forwarding:")
        print("  kubectl port-forward svc/kdbai 8084:8082 -n rag &")

    # Print final report
    print(metrics.report())

    # Save metrics to JSON
    metrics_file = Path(__file__).parent / f"ingestion_metrics_{args.collection_name}.json"
    metrics_data = {
        "collection_name": metrics.collection_name,
        "index_type": "cagra",
        "total_files": metrics.total_files,
        "total_file_batches": metrics.total_file_batches,
        "files_per_batch": args.upload_batch_size,
        "total_rows": metrics.total_rows,
        "kdbai_insert_batch_size": metrics.kdbai_insert_batch_size,
        "estimated_kdbai_batches": metrics.estimated_kdbai_batches,
        "duration_seconds": metrics.duration_seconds,
        "timestamp": datetime.now().isoformat(),
        "errors": metrics.errors
    }

    with open(metrics_file, "w") as f:
        json.dump(metrics_data, f, indent=2)
    print(f"\n[INFO] Metrics saved to: {metrics_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
