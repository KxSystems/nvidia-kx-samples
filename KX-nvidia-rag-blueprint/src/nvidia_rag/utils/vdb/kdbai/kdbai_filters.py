# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

"""
Filter expression utilities for KDB.AI.

Why This Module Exists:
-----------------------
The RAG Blueprint supports multiple vector databases (Milvus, Elasticsearch, KDB.AI),
each with its own native filter format:

    Milvus (string expressions - used as the common interface):
        "source == 'file.pdf'"
        "count > 10 and status == 'active'"

    Elasticsearch (Query DSL - JSON):
        {"bool": {"must": [{"term": {"source": "file.pdf"}}]}}
        {"range": {"count": {"gt": 10}}}

    KDB.AI (tuple-based lists):
        [("=", "source", "file.pdf")]
        [(">", "count", 10), ("=", "status", "active")]

The RAG Blueprint uses Milvus-style string expressions as the common filter interface
throughout the codebase (API endpoints, LLM filter generation, frontend). Each vector
database implementation then translates to its native format:

    - milvus_vdb.py  -> Uses filters directly (native format)
    - elastic_vdb.py -> Translates to Elasticsearch Query DSL
    - kdbai_vdb.py   -> Uses this module to translate to KDB.AI tuples

This approach maintains a single filter interface while supporting multiple backends.

KDB.AI Filter Format Reference:
-------------------------------
    Single condition: [("=", "column", value)]
    Multiple conditions (AND): [("<=", "num", 250), ("in", "sym", ["AA", "ABC"])]
    Operators: "=", "<>", "<", "<=", ">", ">=", "in", "like"
    Note: Use "=" for equality, not "=="
"""

import logging
import re
from typing import Any, List, Optional, Union

logger = logging.getLogger(__name__)


def milvus_to_kdbai_filter(
    filter_expr: str,
) -> Optional[List[Union[str, Any]]]:
    """
    Convert Milvus-style filter expression to KDB.AI filter format.

    Args:
        filter_expr: Milvus-style filter expression string

    Returns:
        KDB.AI filter list or None if empty/invalid

    Examples:
        >>> milvus_to_kdbai_filter("source == 'file.pdf'")
        [("=", "source", "file.pdf")]

        >>> milvus_to_kdbai_filter("source['source_name'] == 'file.pdf'")
        [("=", "source", "file.pdf")]

        >>> milvus_to_kdbai_filter("count > 10")
        [(">", "count", 10)]
    """
    if not filter_expr or not filter_expr.strip():
        return None

    filter_expr = filter_expr.strip()
    conditions = []

    # Split by 'and' or '&&' for multiple conditions
    parts = re.split(r"\s+and\s+|\s*&&\s*", filter_expr, flags=re.IGNORECASE)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        condition = _parse_single_condition(part)
        if condition:
            conditions.append(condition)

    if not conditions:
        return None

    return conditions


def _convert_operator(op: str) -> str:
    """Convert Milvus operator to KDB.AI operator."""
    operator_map = {
        "==": "=",
        "!=": "<>",
        ">": ">",
        "<": "<",
        ">=": ">=",
        "<=": "<=",
    }
    return operator_map.get(op, op)


def _parse_single_condition(expr: str) -> Optional[tuple]:
    """
    Parse a single filter condition.

    Args:
        expr: Single condition expression

    Returns:
        KDB.AI filter condition tuple (operator, field, value)
    """
    expr = expr.strip()

    # Pattern for nested field access: source['source_name'] == 'value'
    nested_pattern = r"(\w+)\[(['\"])(\w+)\2\]\s*(==|!=|>|<|>=|<=)\s*(['\"])([^'\"]+)\5"
    match = re.match(nested_pattern, expr)
    if match:
        # For KDB.AI, we simplify nested access to just the field name
        # since metadata is stored as JSON string
        field = match.group(1)  # Use parent field name
        operator = _convert_operator(match.group(4))
        value = match.group(6)
        return (operator, field, value)

    # Pattern for simple equality: field == 'value' or field == "value"
    equality_pattern = r"(\w+)\s*(==|!=)\s*(['\"])([^'\"]+)\3"
    match = re.match(equality_pattern, expr)
    if match:
        field = match.group(1)
        operator = _convert_operator(match.group(2))
        value = match.group(4)
        return (operator, field, value)

    # Pattern for numeric comparison: field > 10, field <= 100.5
    numeric_pattern = r"(\w+)\s*(>|<|>=|<=|==|!=)\s*(-?\d+\.?\d*)"
    match = re.match(numeric_pattern, expr)
    if match:
        field = match.group(1)
        operator = _convert_operator(match.group(2))
        value_str = match.group(3)
        # Convert to appropriate numeric type
        value = float(value_str) if "." in value_str else int(value_str)
        return (operator, field, value)

    # Pattern for 'in' operator: field in ['a', 'b', 'c']
    in_pattern = r"(\w+)\s+in\s+\[([^\]]+)\]"
    match = re.match(in_pattern, expr, re.IGNORECASE)
    if match:
        field = match.group(1)
        values_str = match.group(2)
        # Parse the values list
        values = _parse_list_values(values_str)
        if values:
            return ("in", field, values)

    # Pattern for 'like' operator: field like '%pattern%'
    like_pattern = r"(\w+)\s+like\s+(['\"])([^'\"]+)\2"
    match = re.match(like_pattern, expr, re.IGNORECASE)
    if match:
        field = match.group(1)
        pattern = match.group(3)
        # KDB.AI uses 'like' with wildcards
        return ("like", field, pattern)

    logger.warning(f"Could not parse filter expression: {expr}")
    return None


def _parse_list_values(values_str: str) -> List[Any]:
    """
    Parse a comma-separated list of values.

    Args:
        values_str: String like "'a', 'b', 'c'" or "1, 2, 3"

    Returns:
        List of parsed values
    """
    values = []
    # Match quoted strings or numbers
    pattern = r"(['\"])([^'\"]+)\1|(-?\d+\.?\d*)"

    for match in re.finditer(pattern, values_str):
        if match.group(2):  # Quoted string
            values.append(match.group(2))
        elif match.group(3):  # Number
            num_str = match.group(3)
            values.append(float(num_str) if "." in num_str else int(num_str))

    return values


def build_source_filter(source_name: str) -> List[tuple]:
    """
    Build a filter for matching documents by source name.

    Args:
        source_name: The source filename to match

    Returns:
        KDB.AI filter for source matching
    """
    return [("like", "source", f"*{source_name}*")]


def build_metadata_filter(metadata: dict) -> Optional[List[tuple]]:
    """
    Build a filter from metadata key-value pairs.

    Args:
        metadata: Dictionary of field-value pairs

    Returns:
        KDB.AI filter list or None if empty
    """
    if not metadata:
        return None

    conditions = []
    for field, value in metadata.items():
        if isinstance(value, str):
            conditions.append(("=", field, value))
        elif isinstance(value, (int, float)):
            conditions.append(("=", field, value))
        elif isinstance(value, list):
            conditions.append(("in", field, value))

    return conditions if conditions else None
