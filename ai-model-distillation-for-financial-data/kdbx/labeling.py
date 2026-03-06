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
"""Market-return-based training data labeling via KDB-X as-of joins.

Computes next-day return labels (BUY/SELL/HOLD) by joining training record
timestamps against ``market_ticks`` to get entry and exit prices.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import pykx as kx

from kdbx.connection import pykx_connection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# q lambda — batch return lookup via aj
# ---------------------------------------------------------------------------

_RETURN_LABELS_Q = """\
{[syms;timestamps]
  lookup: ([] sym: syms; timestamp: timestamps);
  entry: aj[`sym`timestamp; lookup;
    select sym, timestamp, entry_price:close from market_ticks];
  exit_lookup: update timestamp: timestamp + 1D from lookup;
  exits: aj[`sym`timestamp; exit_lookup;
    select sym, timestamp, exit_price:close from market_ticks];
  update exit_price: exits`exit_price from entry
 }"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_return_labels_batch(
    syms: list[str],
    timestamps: list[str | Any],
    threshold_bps: float,
) -> list[dict[str, Any]]:
    """Compute next-day return labels for a batch of (sym, timestamp) pairs.

    Parameters
    ----------
    syms : list[str]
        Ticker symbols.
    timestamps : list
        ISO-8601 timestamp strings or datetime-like objects.
    threshold_bps : float
        Threshold in basis points.  return > +threshold → BUY,
        < -threshold → SELL, else HOLD.

    Returns
    -------
    list[dict]
        One dict per input with keys ``entry_price``, ``exit_price``,
        ``return_pct``, ``direction``.  ``direction`` is None when
        market data is missing.
    """
    if not syms:
        return []

    ts_dt = [pd.Timestamp(t).to_pydatetime() for t in timestamps]
    threshold_pct = threshold_bps / 100.0  # bps → percent

    with pykx_connection() as q:
        result = q(
            _RETURN_LABELS_Q,
            kx.SymbolVector(syms),
            kx.TimestampVector(ts_dt),
        )

    try:
        df = result.pd() if hasattr(result, "pd") else pd.DataFrame()
    except Exception:
        df = pd.DataFrame()

    labels: list[dict[str, Any]] = []
    for i in range(len(syms)):
        if i < len(df):
            row = df.iloc[i]
            entry = row.get("entry_price")
            exit_ = row.get("exit_price")
        else:
            entry = None
            exit_ = None

        if entry is None or exit_ is None or pd.isna(entry) or pd.isna(exit_):
            labels.append({
                "entry_price": None,
                "exit_price": None,
                "return_pct": None,
                "direction": None,
            })
            continue

        entry_f = float(entry)
        exit_f = float(exit_)
        ret_pct = ((exit_f - entry_f) / entry_f) * 100.0

        if ret_pct > threshold_pct:
            direction = "BUY"
        elif ret_pct < -threshold_pct:
            direction = "SELL"
        else:
            direction = "HOLD"

        labels.append({
            "entry_price": entry_f,
            "exit_price": exit_f,
            "return_pct": round(ret_pct, 4),
            "direction": direction,
        })

    return labels


def generate_template_rationale(
    direction: str,
    sym: str,
    return_pct: float,
    entry_price: float,
    exit_price: float,
) -> str:
    """Generate a template rationale string for a labeled record.

    Returns
    -------
    str
        e.g. ``"BUY — AAPL next-day return +1.50% ($185.50 → $188.28)"``
    """
    sign = "+" if return_pct >= 0 else ""
    return (
        f"{direction} \u2014 {sym} next-day return "
        f"{sign}{return_pct:.2f}% (${entry_price:.2f} \u2192 ${exit_price:.2f})"
    )
