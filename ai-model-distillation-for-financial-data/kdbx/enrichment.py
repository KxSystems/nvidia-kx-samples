# SPDX-FileCopyrightText: Copyright (c) 2026 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Co-temporal training pair enrichment via KDB-X as-of joins.

Enriches training records with point-in-time market context (price,
volume, order book) using ``aj`` — the same record gets the most
recent market snapshot at or before the event timestamp.

No user values are ever interpolated into the q string.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import pandas as pd
import pykx as kx

from kdbx.connection import pykx_connection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# q lambdas
# ---------------------------------------------------------------------------

_ENRICH_Q = """\
{[s;ts]
  snap: aj[`sym`timestamp;
    ([] sym: enlist s; timestamp: enlist ts);
    select sym, timestamp, close, vwap, high, low, volume from market_ticks];
  book: aj[`sym`timestamp;
    ([] sym: enlist s; timestamp: enlist ts);
    select sym, timestamp, bid_price, ask_price, spread, mid from order_book];
  first snap lj `sym`timestamp xkey book
 }"""

_ENRICH_BATCH_Q = """\
{[s;ts]
  lookup: ([] sym: s; timestamp: ts);
  snap: aj[`sym`timestamp; lookup;
    select sym, timestamp, close, vwap, high, low, volume from market_ticks];
  book: aj[`sym`timestamp; lookup;
    select sym, timestamp, bid_price, ask_price, spread, mid from order_book];
  snap lj `sym`timestamp xkey book
 }"""


# ---------------------------------------------------------------------------
# Field mapping: q column name -> enriched record key
# ---------------------------------------------------------------------------

_FIELD_MAP: dict[str, str] = {
    "close": "market_close",
    "vwap": "market_vwap",
    "high": "market_high",
    "low": "market_low",
    "volume": "market_volume",
    "bid_price": "market_bid",
    "ask_price": "market_ask",
    "spread": "market_spread",
    "mid": "market_mid",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def enrich_training_pair(
    record: dict[str, Any],
    sym: str,
    event_timestamp: str,
) -> dict[str, Any]:
    """Enrich a single training record with point-in-time market context.

    Parameters
    ----------
    record : dict
        The original training record to enrich.
    sym : str
        Ticker symbol (e.g. ``"AAPL"``).
    event_timestamp : str
        ISO-8601 timestamp string for the event.

    Returns
    -------
    dict
        Original record keys plus ``market_close``, ``market_vwap``,
        ``market_high``, ``market_low``, ``market_volume``,
        ``market_bid``, ``market_ask``, ``market_spread``, ``market_mid``.
    """
    ts = pd.Timestamp(event_timestamp).to_pydatetime()

    with pykx_connection() as q:
        row = q(
            _ENRICH_Q,
            kx.SymbolAtom(sym),
            kx.TimestampAtom(ts),
        )

    enriched = dict(record)
    try:
        raw = row.py() if hasattr(row, "py") else {}
        # `first` on a table returns a q dictionary → .py() gives a Python dict
        # If it somehow returns a table, .py() gives a dict of lists
        row_dict = raw if isinstance(raw, dict) else {}
    except Exception:
        row_dict = {}

    for q_col, rec_key in _FIELD_MAP.items():
        val = row_dict.get(q_col)
        enriched[rec_key] = float(val) if val is not None else None

    return enriched


def enrich_training_pairs_batch(
    records: list[dict[str, Any]],
    sym_field: str = "sym",
    timestamp_field: str = "timestamp",
) -> list[dict[str, Any]]:
    """Enrich multiple training records in a single ``aj`` call.

    Parameters
    ----------
    records : list[dict]
        Training records to enrich.
    sym_field : str
        Key in each record holding the ticker symbol.
    timestamp_field : str
        Key in each record holding the event timestamp string.

    Returns
    -------
    list[dict]
        Enriched records with market context fields appended.
    """
    if not records:
        return []

    syms = [r[sym_field] for r in records]
    timestamps = [
        pd.Timestamp(r[timestamp_field]).to_pydatetime() for r in records
    ]

    with pykx_connection() as q:
        result = q(
            _ENRICH_BATCH_Q,
            kx.SymbolVector(syms),
            kx.TimestampVector(timestamps),
        )

    try:
        result_df = result.pd() if hasattr(result, "pd") else pd.DataFrame()
    except Exception:
        result_df = pd.DataFrame()

    enriched: list[dict[str, Any]] = []
    for i, rec in enumerate(records):
        out = dict(rec)
        if i < len(result_df):
            row = result_df.iloc[i]
            for q_col, rec_key in _FIELD_MAP.items():
                val = row.get(q_col)
                out[rec_key] = float(val) if val is not None else None
        enriched.append(out)

    return enriched


def extract_sym_from_record(
    record: dict[str, Any],
    config: Any,
) -> str | None:
    """Extract ticker symbol from a training record.

    Strategies:
      - "field": read directly from record[config.sym_field]
      - "regex": extract first uppercase ticker match from request text
    """
    if config.sym_extraction == "field":
        return record.get(config.sym_field)

    if config.sym_extraction == "regex":
        request = record.get("request", "")
        text = request.get("content", "") if isinstance(request, dict) else str(request)
        match = re.search(config.sym_regex, text)
        if match:
            return match.group(1)

    return config.default_sym
