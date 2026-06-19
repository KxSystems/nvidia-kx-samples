# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
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
"""SQL execution rail for LLM-generated queries (NIM roadmap item 2, piece 1).

The KDB chat path has an LLM generate SQL that is then executed against the
KDB-X MCP server. This module is an ALWAYS-ON, pure-stdlib gate that sits
immediately before execution: read-only single SELECT statements pass,
everything else is rejected with a human-readable reason. It needs no NIM, no
network, and no third-party packages — it can never be a point of failure.

Checks (in order):
1. Length cap (env SQL_GUARD_MAX_LEN, default 4000 chars).
2. String literals are masked first so keywords inside quotes
   (e.g. WHERE name = 'drop table') never trigger the deny-list.
3. Single statement only — an unquoted semicolon followed by more content
   is rejected.
4. Must start with SELECT (after stripping code fences and SQL comments).
5. Deny-list of write/DDL/escape keywords anywhere outside string literals.
"""

from __future__ import annotations

import os
import re

# User-facing prefix used by callers when a query is rejected. Kept here so the
# route and the client agree on the exact wording.
SQL_GUARD_BLOCK_MESSAGE = "Generated SQL was blocked by the execution guard"

_DEFAULT_MAX_LEN = 4000

# Write / DDL / escape-hatch keywords that have no place in a read-only
# analytics query. Scanned with word boundaries on string-masked text.
_DENY_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "CREATE",
    "ALTER",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
    "EXEC",
    "ATTACH",
    "PRAGMA",
    "MERGE",
    "REPLACE",
)

_DENY_RE = re.compile(r"\b(" + "|".join(_DENY_KEYWORDS) + r")\b", re.IGNORECASE)
_INTO_OUTFILE_RE = re.compile(r"\bINTO\s+OUTFILE\b", re.IGNORECASE)

# Single-quoted SQL string literal, with '' as the escaped quote.
_STRING_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")

# ```sql ... ``` (or bare ```) fences around the whole query.
_FENCED_RE = re.compile(r"^\s*```[a-zA-Z]*\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)
_LEADING_FENCE_RE = re.compile(r"^\s*```[a-zA-Z]*\s*\n?")

_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_code_fences(sql: str) -> str:
    """Unwrap ```sql ... ``` fences the LLM may have left around the query."""
    match = _FENCED_RE.match(sql)
    if match:
        return match.group(1)
    # Tolerate an opening fence without a closing one.
    return _LEADING_FENCE_RE.sub("", sql, count=1)


def _mask_string_literals(sql: str) -> str:
    """Replace the contents of single-quoted literals with spaces.

    Keeps offsets stable and leaves the surrounding quotes in place so the
    structural checks (semicolons, deny-list keywords) only ever see SQL
    syntax, never user data.
    """
    return _STRING_LITERAL_RE.sub(lambda m: "'" + " " * (len(m.group(0)) - 2) + "'", sql)


def _strip_comments(sql: str) -> str:
    sql = _BLOCK_COMMENT_RE.sub(" ", sql)
    return _LINE_COMMENT_RE.sub(" ", sql)


def validate_sql(sql: str) -> tuple[bool, str]:
    """Validate LLM-generated SQL before execution.

    Returns (ok, reason). ``reason`` is "ok" when the query passes, otherwise a
    short user-facing explanation of why it was rejected.
    """
    if not sql or not sql.strip():
        return False, "empty SQL statement"

    max_len = int(os.getenv("SQL_GUARD_MAX_LEN", str(_DEFAULT_MAX_LEN)))
    if len(sql) > max_len:
        return False, f"statement exceeds the {max_len} character limit"

    sql = _strip_code_fences(sql).strip()
    if not sql:
        return False, "empty SQL statement"

    masked = _mask_string_literals(sql)
    # After masking, every complete literal is exactly '<spaces>'. Any quote
    # left once those are removed is an unterminated string — too ambiguous to
    # scan safely.
    if "'" in _STRING_LITERAL_RE.sub("", masked):
        return False, "unterminated string literal"

    structural = _strip_comments(masked)
    if not structural.strip():
        return False, "empty SQL statement"

    # Single statement only: a semicolon may appear at most as a trailer.
    semi_idx = structural.find(";")
    if semi_idx != -1 and structural[semi_idx + 1:].strip():
        return False, "multiple SQL statements are not allowed"

    if not re.match(r"^\s*SELECT\b", structural, re.IGNORECASE):
        return False, "only SELECT statements are allowed"

    deny_match = _DENY_RE.search(structural)
    if deny_match:
        return False, f"forbidden keyword '{deny_match.group(1).upper()}'"

    if _INTO_OUTFILE_RE.search(structural):
        return False, "forbidden keyword 'INTO OUTFILE'"

    return True, "ok"
