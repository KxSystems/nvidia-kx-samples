# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Vendored into the KXTA source-agents layer from the KX "alpha-agents-strategy-miner" project
# (faithful copy; imports rewritten and heavy imports made lazy -- no logic changes).
"""LangChain tools for retrieving Federal Reserve Economic Data (FRED) via fredapi."""

from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv
from langchain_core.tools import tool
from pydantic import BaseModel, Field

load_dotenv()
_FRED_API_KEY = os.getenv("FRED_API_KEY")


def _get_fred():
    """Return a Fred client, or raise if the API key is missing."""
    from fredapi import Fred

    if not _FRED_API_KEY:
        raise RuntimeError("FRED_API_KEY environment variable is not set. "
                           "Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html")
    return Fred(api_key=_FRED_API_KEY)


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------


class SearchSeriesInput(BaseModel):
    """Input for searching FRED series by keyword."""

    query: str = Field(description="Search term, e.g. 'unemployment rate', 'GDP', 'consumer price index'.")
    limit: int = Field(
        default=10,
        description="Maximum number of results to return.",
    )


class GetSeriesInput(BaseModel):
    """Input for retrieving FRED time series observations."""

    series_id: str = Field(description=("FRED series identifier, e.g. 'UNRATE' (unemployment rate), "
                                        "'GDP' (gross domestic product), 'CPIAUCSL' (CPI)."), )
    observation_start: Optional[str] = Field(
        default=None,
        description="Start date in YYYY-MM-DD format.",
    )
    observation_end: Optional[str] = Field(
        default=None,
        description="End date in YYYY-MM-DD format.",
    )
    frequency: Optional[str] = Field(
        default=None,
        description=("Frequency to aggregate to: 'd' (daily), 'w' (weekly), "
                     "'m' (monthly), 'q' (quarterly), 'a' (annual). "
                     "Must be equal to or lower than the series native frequency."),
    )
    units: Optional[str] = Field(
        default=None,
        description=("Data transformation: 'lin' (levels, default), 'chg' (change), "
                     "'pch' (percent change), 'pc1' (percent change from year ago), "
                     "'log' (natural log)."),
    )


class GetSeriesInfoInput(BaseModel):
    """Input for retrieving metadata about a FRED series."""

    series_id: str = Field(description="FRED series identifier, e.g. 'UNRATE', 'GDP', 'CPIAUCSL'.")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

_SEARCH_COLUMNS = ["title", "frequency_short", "units_short", "seasonal_adjustment_short"]


@tool(args_schema=SearchSeriesInput)
def search_fred_series(query: str, limit: int = 10) -> str:
    """Search the FRED database for economic data series by keyword. Returns a
    table of matching series with their IDs, titles, frequency, and units.
    Use this to discover the right series_id before fetching data."""
    try:
        fred = _get_fred()
        results = fred.search(query)
        if results.empty:
            return f"No FRED series found for '{query}'."
        cols = [c for c in _SEARCH_COLUMNS if c in results.columns]
        subset = results[cols].head(limit)
        return subset.to_string()
    except Exception as e:
        return f"Error searching FRED for '{query}': {e}"


@tool(args_schema=GetSeriesInput)
def get_fred_series(
    series_id: str,
    observation_start: Optional[str] = None,
    observation_end: Optional[str] = None,
    frequency: Optional[str] = None,
    units: Optional[str] = None,
) -> str:
    """Retrieve time series observations for a FRED economic data series. Returns
    dated values, e.g. monthly unemployment rates or quarterly GDP figures.
    Use search_fred_series first if you don't know the series_id."""
    try:
        fred = _get_fred()
        kwargs = {}
        if observation_start:
            kwargs["observation_start"] = observation_start
        if observation_end:
            kwargs["observation_end"] = observation_end
        if frequency:
            kwargs["frequency"] = frequency
        if units:
            kwargs["units"] = units
        data = fred.get_series(series_id, **kwargs)
        if data.empty:
            return f"No observations found for series '{series_id}' with the given filters."
        return data.to_string()
    except Exception as e:
        return f"Error retrieving FRED series '{series_id}': {e}"


@tool(args_schema=GetSeriesInfoInput)
def get_fred_series_info(series_id: str) -> str:
    """Get metadata about a FRED series including its title, frequency, units,
    seasonal adjustment, and description notes."""
    try:
        fred = _get_fred()
        info = fred.get_series_info(series_id)
        lines = [f"{key}: {value}" for key, value in info.items() if value]
        return "\n".join(lines)
    except Exception as e:
        return f"Error retrieving info for FRED series '{series_id}': {e}"
