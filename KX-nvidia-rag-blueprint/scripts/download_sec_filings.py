#!/usr/bin/env python3
"""
Download SEC 10-K filings for companies.

Usage:
    python download_sec_filings.py                    # Download all default companies
    python download_sec_filings.py BA                 # Download only Boeing
    python download_sec_filings.py BA NVDA AAPL      # Download specific companies
    python download_sec_filings.py --list            # List available companies
"""

import argparse
import time
import requests
from pathlib import Path

# SEC EDGAR API requires a User-Agent header
HEADERS = {
    "User-Agent": "Demo Research demo@example.com",
    "Accept-Encoding": "gzip, deflate",
}

# Available companies with their CIK numbers (Central Index Key)
ALL_COMPANIES = {
    "AAPL": "0000320193",   # Apple
    "MSFT": "0000789019",   # Microsoft
    "NVDA": "0001045810",   # NVIDIA
    "GOOGL": "0001652044",  # Alphabet
    "AMZN": "0001018724",   # Amazon
    "BA": "0000012927",     # Boeing
    "TSLA": "0001318605",   # Tesla
    "META": "0001326801",   # Meta (Facebook)
    "JPM": "0000019617",    # JPMorgan Chase
    "V": "0001403161",      # Visa
    "JNJ": "0000200406",    # Johnson & Johnson
    "WMT": "0000104169",    # Walmart
    "PG": "0000080424",     # Procter & Gamble
    "XOM": "0000034088",    # Exxon Mobil
    "UNH": "0000731766",    # UnitedHealth
    "HD": "0000354950",     # Home Depot
    "DIS": "0001744489",    # Disney
    "INTC": "0000050863",   # Intel
    "AMD": "0000002488",    # AMD
    "CRM": "0001108524",    # Salesforce
}

# Default companies if none specified
DEFAULT_COMPANIES = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]

# Years to download (last 10 years)
YEARS = list(range(2015, 2025))

OUTPUT_DIR = Path("sec_filings")


def get_company_filings(cik: str, filing_type: str = "10-K") -> list:
    """Get list of filings for a company from SEC EDGAR."""
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        filings = []
        recent = data.get("filings", {}).get("recent", {})

        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])

        for i, form in enumerate(forms):
            if form == filing_type:
                year = int(dates[i][:4])
                if year in YEARS:
                    filings.append({
                        "form": form,
                        "date": dates[i],
                        "year": year,
                        "accession": accessions[i].replace("-", ""),
                        "primary_doc": primary_docs[i],
                    })

        return filings
    except Exception as e:
        print(f"Error fetching filings for CIK {cik}: {e}")
        return []


def download_filing(cik: str, ticker: str, filing: dict) -> str:
    """Download a single filing document."""
    accession = filing["accession"]
    primary_doc = filing["primary_doc"]
    year = filing["year"]

    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{primary_doc}"

    # Create output directory
    output_dir = OUTPUT_DIR / ticker
    output_dir.mkdir(parents=True, exist_ok=True)

    # Output filename (use .html for compatibility with ingestor)
    ext = Path(primary_doc).suffix or ".html"
    if ext == ".htm":
        ext = ".html"  # Normalize .htm to .html
    output_file = output_dir / f"{ticker}_10K_{year}{ext}"

    if output_file.exists():
        print(f"  Already exists: {output_file.name}")
        return str(output_file)

    try:
        resp = requests.get(url, headers=HEADERS, timeout=60)
        resp.raise_for_status()

        output_file.write_bytes(resp.content)
        print(f"  Downloaded: {output_file.name}")
        return str(output_file)
    except Exception as e:
        print(f"  Error downloading {url}: {e}")
        return None


def list_companies():
    """Print all available companies."""
    print("Available companies:")
    print("-" * 40)
    for ticker, cik in sorted(ALL_COMPANIES.items()):
        print(f"  {ticker:6} - CIK: {cik}")
    print("-" * 40)
    print(f"\nDefault: {', '.join(DEFAULT_COMPANIES)}")


def main():
    parser = argparse.ArgumentParser(
        description="Download SEC 10-K filings for companies.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python download_sec_filings.py                    # Download default companies
  python download_sec_filings.py BA                 # Download only Boeing
  python download_sec_filings.py BA NVDA AAPL      # Download specific companies
  python download_sec_filings.py --list            # List available companies
        """,
    )
    parser.add_argument(
        "companies",
        nargs="*",
        help="Company ticker symbols to download (e.g., BA NVDA AAPL)",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all available companies",
    )
    parser.add_argument(
        "--years",
        type=str,
        default=None,
        help="Year range (e.g., '2020-2024' or '2023')",
    )

    args = parser.parse_args()

    # Handle --list flag
    if args.list:
        list_companies()
        return []

    # Determine which companies to download
    if args.companies:
        # Validate tickers
        companies = {}
        for ticker in args.companies:
            ticker = ticker.upper()
            if ticker in ALL_COMPANIES:
                companies[ticker] = ALL_COMPANIES[ticker]
            else:
                print(f"Warning: Unknown ticker '{ticker}', skipping.")
                print(f"  Use --list to see available companies.")
        if not companies:
            print("Error: No valid companies specified.")
            return []
    else:
        companies = {t: ALL_COMPANIES[t] for t in DEFAULT_COMPANIES}

    # Handle year range
    years = YEARS
    if args.years:
        if "-" in args.years:
            start, end = args.years.split("-")
            years = list(range(int(start), int(end) + 1))
        else:
            years = [int(args.years)]

    print("=" * 60)
    print("SEC 10-K Filings Downloader")
    print(f"Companies: {', '.join(companies.keys())}")
    print(f"Years: {years[0]}" + (f" - {years[-1]}" if len(years) > 1 else ""))
    print("=" * 60)

    OUTPUT_DIR.mkdir(exist_ok=True)

    all_files = []

    for ticker, cik in companies.items():
        print(f"\n{ticker} (CIK: {cik})")
        print("-" * 40)

        # Remove leading zeros for API calls
        cik_clean = cik.lstrip("0")

        filings = get_company_filings(cik, "10-K")
        # Filter by requested years
        filings = [f for f in filings if f["year"] in years]
        print(f"Found {len(filings)} 10-K filings in date range")

        for filing in filings:
            filepath = download_filing(cik_clean, ticker, filing)
            if filepath:
                all_files.append(filepath)

            # Be nice to SEC servers
            time.sleep(0.5)

        time.sleep(1)  # Pause between companies

    print("\n" + "=" * 60)
    print(f"Downloaded {len(all_files)} files to {OUTPUT_DIR}/")
    print("=" * 60)

    # Print upload instructions
    if all_files:
        first_ticker = list(companies.keys())[0]
        print("\nTo upload to RAG, run:")
        print(f"  curl -X POST http://localhost:8082/documents \\")
        print(f"    -F 'documents=@{all_files[0]}' \\")
        print(f"    -F 'data={{\"collection_name\":\"sec_filings\"}}'")

    return all_files


if __name__ == "__main__":
    main()
