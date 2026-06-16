# SPDX-FileCopyrightText: Copyright (c) 2026 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Translate Python filter AST -> q functional-select where-clauses.

Output shape: list of triples [op, column, value]. Multiple triples are ANDed.
"""
from __future__ import annotations

from typing import Any

OP_MAP = {
    "==": "=", "eq": "=",
    "!=": "<>", "ne": "<>",
    ">":  ">",  "gt": ">",
    "<":  "<",  "lt": "<",
    ">=": ">=", "gte": ">=",
    "<=": "<=", "lte": "<=",
    "in": "in",
}


def translate_filter(f: dict[str, Any] | None) -> list[list[Any]]:
    """Return list of q where-clause triples. Empty list = no filter."""
    if not f:
        return []
    op = f.get("op")
    if op in ("and", "AND"):
        out: list[list[Any]] = []
        for arg in f["args"]:
            out.extend(translate_filter(arg))
        return out
    if op in ("or", "OR"):
        raise NotImplementedError(
            "OR filter not supported in Phase 1 (q functional-select where ANDs implicitly). "
            "Use server-side computed columns to express disjunction."
        )
    if op not in OP_MAP:
        raise ValueError(f"Unsupported filter op: {op!r}")
    key = f["key"]
    value = f["value"]
    # For `=` and `<>`, wrap scalar value in a 1-element list (q convention: enlist)
    if OP_MAP[op] in ("=", "<>") and not isinstance(value, list):
        value = [value]
    return [[OP_MAP[op], key, value]]
