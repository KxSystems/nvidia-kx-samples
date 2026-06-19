# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Vendored into the KXTA source-agents layer from the KX "alpha-agents-strategy-miner" project
# (faithful copy; imports rewritten and heavy imports made lazy -- no logic changes).
"""LangChain tools for retrieving SEC EDGAR filings via edgartools."""

from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv
from edgar import Company, set_identity
from langchain_core.tools import tool
from pydantic import BaseModel, Field

load_dotenv()

# SEC requires a user-agent identity for EDGAR access
set_identity(os.getenv("SEC_EDGAR_EMAIL", "alphaagent@example.com"))

# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------


class ListFilingsInput(BaseModel):
    """Input for listing SEC filings metadata."""

    ticker: str = Field(description="Stock ticker symbol, e.g. 'AAPL'")
    filing_type: Optional[str] = Field(
        default=None,
        description="SEC filing type to filter by, e.g. '10-K', '10-Q', '8-K'. None returns all types.",
    )
    date_from: Optional[str] = Field(
        default=None,
        description="Start date (inclusive) in YYYY-MM-DD format.",
    )
    date_to: Optional[str] = Field(
        default=None,
        description="End date (inclusive) in YYYY-MM-DD format.",
    )
    limit: int = Field(
        default=10,
        description="Maximum number of filings to return.",
    )


class GetFilingInput(BaseModel):
    """Input for retrieving the full text of an SEC filing."""

    ticker: str = Field(description="Stock ticker symbol, e.g. 'AAPL'")
    filing_type: str = Field(description="SEC filing type, e.g. '10-K', '10-Q', '8-K'.")
    date_from: Optional[str] = Field(
        default=None,
        description="Start date (inclusive) in YYYY-MM-DD format.",
    )
    date_to: Optional[str] = Field(
        default=None,
        description="End date (inclusive) in YYYY-MM-DD format.",
    )
    max_chars: int = Field(
        default=50_000,
        description="Maximum characters to return (truncates long filings).",
    )


class GetFilingSectionInput(BaseModel):
    """Input for retrieving a specific section from a 10-K or 10-Q filing."""

    ticker: str = Field(description="Stock ticker symbol, e.g. 'AAPL'")
    filing_type: str = Field(description="SEC filing type that supports sections, e.g. '10-K' or '10-Q'.")
    section: str = Field(description=("Section identifier, e.g. 'Item 1', 'Item 1A', 'Item 7'. "
                                      "Common 10-K sections: Item 1 (Business), Item 1A (Risk Factors), "
                                      "Item 7 (MD&A), Item 8 (Financial Statements)."), )
    date_from: Optional[str] = Field(
        default=None,
        description="Start date (inclusive) in YYYY-MM-DD format.",
    )
    date_to: Optional[str] = Field(
        default=None,
        description="End date (inclusive) in YYYY-MM-DD format.",
    )
    max_chars: int = Field(
        default=50_000,
        description="Maximum characters to return (truncates long sections).",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_date_filter(date_from: Optional[str], date_to: Optional[str]) -> Optional[str]:
    """Build edgartools date filter string from optional bounds.

    Returns a string like "2023-01-01:2023-12-31", "2023-01-01:", ":2023-12-31",
    or None if both bounds are absent.
    """
    if date_from and date_to:
        return f"{date_from}:{date_to}"
    if date_from:
        return f"{date_from}:"
    if date_to:
        return f":{date_to}"
    return None


def _get_filings(
    ticker: str,
    filing_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """Fetch a Filings collection, optionally filtered by type and date."""
    company = Company(ticker)
    filings = company.get_filings(form=filing_type) if filing_type else company.get_filings()
    date_filter = _build_date_filter(date_from, date_to)
    if date_filter:
        filings = filings.filter(filing_date=date_filter)
    return filings


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool(args_schema=ListFilingsInput)
def list_sec_filings(
    ticker: str,
    filing_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 10,
) -> str:
    """List available SEC filings for a company. Returns a table of filing metadata
    (date, form type, accession number) without the filing text itself."""
    try:
        filings = _get_filings(ticker, filing_type, date_from, date_to)
        df = filings.head(limit).to_pandas()
        if df.empty:
            return f"No filings found for {ticker} with the given filters."
        return df.to_string(index=False)
    except Exception as e:
        return f"Error listing filings for {ticker}: {e}"


@tool(args_schema=GetFilingInput)
def get_sec_filing(
    ticker: str,
    filing_type: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    max_chars: int = 50_000,
) -> str:
    """Retrieve the full clean text of the most recent SEC filing matching the
    given company and filing type. Useful for reading complete 10-K, 10-Q, or 8-K
    documents."""
    try:
        filings = _get_filings(ticker, filing_type, date_from, date_to)
        filing = filings[0]
        text = filing.text()
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n... [truncated at {max_chars} chars]"
        return text
    except Exception as e:
        return f"Error retrieving {filing_type} for {ticker}: {e}"


@tool(args_schema=GetFilingSectionInput)
def get_sec_filing_section(
    ticker: str,
    filing_type: str,
    section: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    max_chars: int = 50_000,
) -> str:
    """Retrieve a specific section from the most recent 10-K or 10-Q filing.
    For example, use section='Item 1A' to get Risk Factors, or 'Item 7' for MD&A."""
    try:
        filings = _get_filings(ticker, filing_type, date_from, date_to)
        filing = filings[0]
        obj = filing.obj()
        section_text = str(obj[section])
        if len(section_text) > max_chars:
            section_text = (section_text[:max_chars] + f"\n\n... [truncated at {max_chars} chars]")
        return section_text
    except KeyError:
        return (f"Section '{section}' not found. "
                f"Available sections: {list(obj.items) if 'obj' in dir() else 'unknown'}")
    except Exception as e:
        return f"Error retrieving section '{section}' from {filing_type} for {ticker}: {e}"
