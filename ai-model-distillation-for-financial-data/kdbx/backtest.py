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
"""Vectorised backtesting engine using KDB-X as-of joins.

Executes a single parameterized q lambda that:
1. Filters signals by model_id (and optional universe/date range)
2. Uses ``aj`` to look up entry price at signal time
3. Uses ``aj`` to look up exit price 1 day later
4. Computes net returns with transaction costs
5. Aggregates into Sharpe, drawdown, total return, win rate

No user values are ever interpolated into the q string.
"""

from __future__ import annotations

import logging
from typing import Any

import pykx as kx

from kdbx.connection import pykx_connection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# q lambda — no user values embedded in the string
# ---------------------------------------------------------------------------

_BACKTEST_Q = """\
{[mid;cost]
  sigs: select from signals where model_id = mid, direction in `BUY`SELL;
  entry: aj[`sym`timestamp; sigs;
    select sym, timestamp, entry_price:close from market_ticks];
  exits: aj[`sym`timestamp;
    update timestamp: timestamp + 1D from entry;
    select sym, timestamp, exit_price:close from market_ticks];
  trades: update
    dir_mult: ?[direction = `BUY; 1f; -1f],
    gross_ret: (exit_price - entry_price) % entry_price
  from entry lj `signal_id xkey select signal_id, exit_price from exits;
  trades: update net_ret: (gross_ret * dir_mult) - cost % 10000
  from trades where not null entry_price, not null exit_price;
  rets: exec net_ret from trades;
  n: count rets;
  `sharpe`max_drawdown`total_return`win_rate`n_trades!(
    $[n > 1; (avg rets) % dev rets; 0f];
    $[n > 0; (min (prds 1 + rets) % maxs prds 1 + rets) - 1; 0f];
    $[n > 0; (prd 1 + rets) - 1; 0f];
    $[n > 0; (sum rets > 0) % n; 0f];
    n)
 }"""

_BACKTEST_UNIVERSE_Q = """\
{[mid;cost;syms]
  sigs: select from signals where model_id = mid, sym in syms, direction in `BUY`SELL;
  entry: aj[`sym`timestamp; sigs;
    select sym, timestamp, entry_price:close from market_ticks];
  exits: aj[`sym`timestamp;
    update timestamp: timestamp + 1D from entry;
    select sym, timestamp, exit_price:close from market_ticks];
  trades: update
    dir_mult: ?[direction = `BUY; 1f; -1f],
    gross_ret: (exit_price - entry_price) % entry_price
  from entry lj `signal_id xkey select signal_id, exit_price from exits;
  trades: update net_ret: (gross_ret * dir_mult) - cost % 10000
  from trades where not null entry_price, not null exit_price;
  rets: exec net_ret from trades;
  n: count rets;
  `sharpe`max_drawdown`total_return`win_rate`n_trades!(
    $[n > 1; (avg rets) % dev rets; 0f];
    $[n > 0; (min (prds 1 + rets) % maxs prds 1 + rets) - 1; 0f];
    $[n > 0; (prd 1 + rets) - 1; 0f];
    $[n > 0; (sum rets > 0) % n; 0f];
    n)
 }"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_backtest(
    model_id: str,
    universe: list[str] | None = None,
    cost_bps: float = 5.0,
) -> dict[str, float | int]:
    """Run a vectorised backtest for *model_id* signals.

    Parameters
    ----------
    model_id : str
        The ``model_id`` symbol stored in the ``signals`` table.
    universe : list[str] | None
        Optional list of ticker symbols to restrict the backtest to.
    cost_bps : float
        Round-trip transaction cost in basis points (default 5.0).

    Returns
    -------
    dict[str, float | int]
        Keys: ``sharpe``, ``max_drawdown``, ``total_return``,
        ``win_rate``, ``n_trades``.
    """
    with pykx_connection() as q:
        if universe:
            result = q(
                _BACKTEST_UNIVERSE_Q,
                kx.SymbolAtom(model_id),
                kx.FloatAtom(cost_bps),
                kx.SymbolVector(universe),
            )
        else:
            result = q(
                _BACKTEST_Q,
                kx.SymbolAtom(model_id),
                kx.FloatAtom(cost_bps),
            )

    # Convert q dictionary to Python dict (.py() avoids embedded q license)
    d = result.py()
    return {
        "sharpe": float(d["sharpe"]),
        "max_drawdown": float(d["max_drawdown"]),
        "total_return": float(d["total_return"]),
        "win_rate": float(d["win_rate"]),
        "n_trades": int(d["n_trades"]),
    }
