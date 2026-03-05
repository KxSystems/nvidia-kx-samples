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
"""Batch signal writer for the KDB-X ``signals`` table.

Inserts model trading signals using PyKX IPC (unlicensed mode),
following the same typed-vector pattern as ``kdbx.market_tables``.
"""

from __future__ import annotations

import logging
from typing import Any

import pykx as kx

from kdbx.connection import pykx_connection

logger = logging.getLogger(__name__)

_INSERT_SIGNALS_Q = (
    "{[sid;ts;s;dir;conf;mid;rat]"
    " n: count sid;"
    " `signals insert flip"
    " `signal_id`timestamp`sym`direction`confidence`model_id`rationale`realized_pnl`realized_at"
    "!(sid;ts;s;dir;conf;mid;rat;n#0n;n#0Np)}"
)


def write_signals_batch(signals: list[dict[str, Any]]) -> int:
    """Insert a batch of signal dicts into the ``signals`` table.

    Parameters
    ----------
    signals : list[dict]
        Each dict must contain: ``signal_id``, ``timestamp``, ``sym``,
        ``direction``, ``confidence``, ``model_id``, ``rationale``.
        ``realized_pnl`` and ``realized_at`` are filled with nulls server-side.

    Returns
    -------
    int
        Number of signals inserted.
    """
    if not signals:
        return 0

    signal_ids = [s["signal_id"] for s in signals]
    timestamps = [s["timestamp"] for s in signals]
    syms = [s["sym"] for s in signals]
    directions = [s["direction"] for s in signals]
    confidences = [s["confidence"] for s in signals]
    model_ids = [s["model_id"] for s in signals]
    rationales = [s["rationale"] for s in signals]

    with pykx_connection() as q:
        q(
            _INSERT_SIGNALS_Q,
            kx.SymbolVector(signal_ids),
            kx.TimestampVector(timestamps),
            kx.SymbolVector(syms),
            kx.SymbolVector(directions),
            kx.toq(confidences),
            kx.SymbolVector(model_ids),
            kx.toq(rationales),
        )

    logger.info("Inserted %d signals into signals table", len(signals))
    return len(signals)
