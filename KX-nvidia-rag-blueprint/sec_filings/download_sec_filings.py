#!/usr/bin/env python3
"""
SEC Filings Downloader

Downloads 10-K annual reports from SEC EDGAR for specified companies.
Saves filings as HTML files organized by ticker symbol.

Usage:
    python download_sec_filings.py [--years 5] [--output-dir ./data]
"""

import os
import re
import time
import argparse
import requests
from datetime import datetime
from typing import Optional
from pathlib import Path

# SEC EDGAR API requires a User-Agent header with contact info
USER_AGENT = "SEC-Filings-Downloader/1.0 (contact@example.com)"
SEC_BASE_URL = "https://data.sec.gov"
EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

# Rate limiting: SEC allows max 10 requests per second
REQUEST_DELAY = 0.15  # 150ms between requests

# Symbols to download - includes various company types
SYMBOLS = [
    "AAPL",   # Apple Inc.
    "GOOG",   # Alphabet Inc. (Google) - Class C
    "GOOGL",  # Alphabet Inc. - Class A (may have same filings)
    "MSFT",   # Microsoft Corporation
    "TSLA",   # Tesla, Inc.
    "AMZN",   # Amazon.com, Inc.
    "NVDA",   # NVIDIA Corporation
    "META",   # Meta Platforms, Inc. (formerly Facebook)
    "RIVN",   # Rivian Automotive, Inc.
    # Note: BYD is Chinese, files with CSRC not SEC
    # Note: SPY is an ETF, doesn't file 10-K (files N-CSR instead)
]

# CIK (Central Index Key) mapping for companies
# These are the official SEC identifiers
CIK_MAP = {
    "AAPL": "0000320193",
    "GOOG": "0001652044",
    "GOOGL": "0001652044",  # Same company as GOOG
    "MSFT": "0000789019",
    "TSLA": "0001318605",
    "AMZN": "0000001018",
    "NVDA": "0001045810",
    "META": "0001326801",
    "RIVN": "0001874178",
}


def get_headers() -> dict:
    """Get headers for SEC requests."""
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }


def get_company_cik(ticker: str) -> Optional[str]:
    """
    Get CIK for a company ticker.
    First checks local map, then queries SEC.
    """
    # Check local map first
    if ticker.upper() in CIK_MAP:
        return CIK_MAP[ticker.upper()]

    # Query SEC for CIK
    try:
        url = f"{SEC_BASE_URL}/submissions/CIK{ticker.upper()}.json"
        response = requests.get(url, headers=get_headers(), timeout=30)
        if response.status_code == 200:
            data = response.json()
            cik = data.get("cik", "").zfill(10)
            return cik
    except Exception as e:
        print(f"  Warning: Could not find CIK for {ticker}: {e}")

    return None


def get_company_filings(cik: str, form_type: str = "10-K", years: int = 5) -> list:
    """
    Get list of filings for a company.

    Args:
        cik: Company CIK (10-digit padded)
        form_type: Type of filing (10-K, 10-Q, etc.)
        years: Number of years to look back

    Returns:
        List of filing metadata dicts
    """
    filings = []
    current_year = datetime.now().year
    min_year = current_year - years

    try:
        # Get company submissions
        url = f"{SEC_BASE_URL}/submissions/CIK{cik}.json"
        response = requests.get(url, headers=get_headers(), timeout=30)
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
    """
    Download a specific filing document.

    Args:
        cik: Company CIK
        accession_number: Filing accession number
        primary_document: Primary document filename

    Returns:
        HTML content of the filing or None
    """
    # Format accession number for URL (remove dashes)
    accession_no_dashes = accession_number.replace("-", "")

    # Build document URL
    url = f"{SEC_BASE_URL}/Archives/edgar/data/{cik}/{accession_no_dashes}/{primary_document}"

    try:
        response = requests.get(url, headers=get_headers(), timeout=60)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"  Error downloading {url}: {e}")
        return None


def sanitize_filename(name: str) -> str:
    """Sanitize a string for use as filename."""
    return re.sub(r'[^\w\-_.]', '_', name)


def download_filings_for_symbol(
    ticker: str,
    output_dir: Path,
    form_type: str = "10-K",
    years: int = 5
) -> int:
    """
    Download all filings for a symbol.

    Args:
        ticker: Stock ticker symbol
        output_dir: Base output directory
        form_type: Type of filing to download
        years: Number of years to look back

    Returns:
        Number of filings downloaded
    """
    print(f"\n{'='*60}")
    print(f"Processing {ticker}")
    print(f"{'='*60}")

    # Get CIK
    cik = get_company_cik(ticker)
    if not cik:
        print(f"  Skipping {ticker}: CIK not found")
        return 0

    print(f"  CIK: {cik}")
    time.sleep(REQUEST_DELAY)

    # Get filings list
    filings = get_company_filings(cik, form_type, years)
    print(f"  Found {len(filings)} {form_type} filings in last {years} years")

    if not filings:
        return 0

    # Create output directory for this ticker
    ticker_dir = output_dir / ticker
    ticker_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0

    for filing in filings:
        accession = filing["accession_number"]
        primary_doc = filing["primary_document"]
        filing_date = filing["filing_date"]
        fiscal_year = filing["fiscal_year"]

        # Determine output filename
        # Use fiscal year from filing date for naming
        output_filename = f"{ticker}_{form_type.replace('-', '')}_{fiscal_year}.html"
        output_path = ticker_dir / output_filename

        # Skip if already downloaded
        if output_path.exists():
            print(f"  Skipping {output_filename} (already exists)")
            continue

        print(f"  Downloading {output_filename} (filed {filing_date})...")
        time.sleep(REQUEST_DELAY)

        content = download_filing(cik.lstrip("0"), accession, primary_doc)

        if content:
            # Save the filing
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"    Saved to {output_path}")
            downloaded += 1
        else:
            print(f"    Failed to download")

        time.sleep(REQUEST_DELAY)

    return downloaded


def main():
    parser = argparse.ArgumentParser(
        description="Download SEC 10-K filings for specified companies"
    )
    parser.add_argument(
        "--years",
        type=int,
        default=5,
        help="Number of years of filings to download (default: 5)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=".",
        help="Output directory for downloaded filings (default: current directory)"
    )
    parser.add_argument(
        "--form",
        type=str,
        default="10-K",
        help="Form type to download (default: 10-K)"
    )
    parser.add_argument(
        "--symbols",
        type=str,
        nargs="+",
        default=None,
        help="Specific symbols to download (default: all configured symbols)"
    )

    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    symbols = args.symbols if args.symbols else SYMBOLS

    print("=" * 60)
    print("SEC Filings Downloader")
    print("=" * 60)
    print(f"Form Type: {args.form}")
    print(f"Years: {args.years}")
    print(f"Output Directory: {output_dir.absolute()}")
    print(f"Symbols: {', '.join(symbols)}")
    print()

    # Special notes for unsupported symbols
    unsupported = []
    if "BYD" in [s.upper() for s in symbols]:
        print("Note: BYD is a Chinese company and files with CSRC, not SEC.")
        print("      BYD ADRs (BYDDY/BYDDF) have limited SEC filings.")
        unsupported.append("BYD")

    if "SPY" in [s.upper() for s in symbols]:
        print("Note: SPY is an ETF and files N-CSR instead of 10-K.")
        print("      Use --form N-CSR to download ETF annual reports.")
        unsupported.append("SPY")

    total_downloaded = 0

    for symbol in symbols:
        if symbol.upper() in unsupported:
            print(f"\nSkipping {symbol} (unsupported)")
            continue

        count = download_filings_for_symbol(
            symbol,
            output_dir,
            args.form,
            args.years
        )
        total_downloaded += count

    print("\n" + "=" * 60)
    print(f"Download complete! Total filings downloaded: {total_downloaded}")
    print("=" * 60)


if __name__ == "__main__":
    main()
