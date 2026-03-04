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
"""Pymongo-compatible shim for KDB-X.

Provides :class:`KDBXCollection` and :class:`KDBXDatabase` that translate
pymongo query patterns to parameterised q queries executed via PyKX.

This module covers 100 % of the query patterns used in ``db_manager.py``
and ``job_service.py``, including:

* ``find_one`` / ``find`` with equality, compound, null-condition,
  ``$in``, and projection filters
* ``insert_one`` returning :class:`InsertOneResult`
* ``update_one`` / ``update_many`` with ``$set``
* ``delete_one`` / ``delete_many`` with equality and ``$in``
* ``create_index`` (no-op)

All user-supplied values are **parameterised** — they are never
interpolated into q strings — to prevent q injection.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

import pandas as pd
import pykx as kx
from bson import ObjectId

from kdbx.connection import pykx_connection
from kdbx.schema import ALL_COLUMNS, TABLE_NAMES, VALID_COLUMNS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column classification — drives type conversion on insert and read
# ---------------------------------------------------------------------------

#: Columns stored as q symbols (fast equality lookups).
SYMBOL_COLUMNS: frozenset[str] = frozenset(
    {
        "_id",
        "workload_id",
        "client_id",
        "status",
        "flywheel_run_id",
        "nim_id",
        "model_name",
        "eval_type",
        "doc_id",
        "index_name",
        "tool_name",
        "record_id",
        "base_model",
        "deployment_type",
        "deployment_status",
        "customized_model",
    }
)

#: Columns whose Python ``dict``/``list`` values are serialised to JSON
#: strings on write and deserialised back on read.
JSON_COLUMNS: frozenset[str] = frozenset(
    {
        "scores",
        "datasets",
        "enrichment_stats",
        "request",
        "response",
        "record",
    }
)

#: Columns stored as q timestamps — needed for typed null on insert.
TIMESTAMP_COLUMNS: frozenset[str] = frozenset(
    {"started_at", "finished_at", "timestamp"}
)

#: Columns stored as q longs.
LONG_COLUMNS: frozenset[str] = frozenset(
    {"num_records", "epochs_completed", "steps_completed"}
)

#: Columns stored as q floats.
FLOAT_COLUMNS: frozenset[str] = frozenset(
    {"runtime_seconds", "progress"}
)

#: Columns that hold ``bson.ObjectId`` hex strings — converted back on read.
OBJECTID_COLUMNS: frozenset[str] = frozenset(
    {"_id", "flywheel_run_id", "nim_id"}
)

# ---------------------------------------------------------------------------
# Identifier validation — prevents column/table name injection
# ---------------------------------------------------------------------------

_VALID_TABLE_NAMES = frozenset(TABLE_NAMES)
_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _validate_table(name: str) -> None:
    """Raise ``ValueError`` if *name* is not a known table."""
    if name not in _VALID_TABLE_NAMES:
        raise ValueError(f"Unknown table: {name!r}")


def _validate_column(col: str, table: str | None = None) -> None:
    """Raise ``ValueError`` if *col* is not a valid column identifier."""
    if not _IDENT_RE.match(col):
        raise ValueError(f"Invalid column name: {col!r}")
    allowed = VALID_COLUMNS.get(table, ALL_COLUMNS) if table else ALL_COLUMNS
    if col not in allowed:
        raise ValueError(f"Unknown column {col!r} for table {table!r}")


# ---------------------------------------------------------------------------
# InsertOneResult
# ---------------------------------------------------------------------------


@dataclass
class InsertOneResult:
    """Minimal stand-in for ``pymongo.results.InsertOneResult``."""

    inserted_id: Any


# ---------------------------------------------------------------------------
# Internal helpers — value conversion
# ---------------------------------------------------------------------------


def _python_to_q(column: str, value: Any) -> Any:
    """Convert a Python value to the appropriate PyKX atom type.

    Parameters
    ----------
    column:
        The column name — used to decide symbol vs general treatment.
    value:
        The Python value to convert.

    Returns
    -------
    A PyKX atom ready to be passed as a q parameter.  **Always** returns
    a ``kx.K`` subclass so that mixed-column insert lists serialise
    correctly as q general lists over IPC.
    """
    if value is None:
        if column in SYMBOL_COLUMNS:
            return kx.SymbolAtom("")
        if column in TIMESTAMP_COLUMNS:
            return kx.TimestampAtom(pd.NaT)
        if column in LONG_COLUMNS:
            return kx.LongAtom(0)
        if column in FLOAT_COLUMNS:
            return kx.FloatAtom(float("nan"))
        return kx.CharVector("")
    if isinstance(value, ObjectId):
        return kx.SymbolAtom(str(value))
    if isinstance(value, Enum):
        return kx.SymbolAtom(str(value.value))
    if isinstance(value, datetime):
        return kx.TimestampAtom(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return kx.LongAtom(value)
    if isinstance(value, float):
        return kx.FloatAtom(value)
    if isinstance(value, (dict, list)):
        return kx.CharVector(json.dumps(value))
    if isinstance(value, str):
        if column in SYMBOL_COLUMNS:
            return kx.SymbolAtom(value)
        return kx.CharVector(value)
    # Fallback — attempt kx conversion
    return kx.toq(value)


def _col_ref(col: str, table: str) -> str:
    """Return a q-safe column reference.

    In q, ``_`` is a built-in operator so ``_id`` is parsed as ``_ id``.
    For columns starting with ``_``, use ``(table`$"col")`` syntax.
    """
    if col.startswith("_"):
        return f'({table}`$"{col}")'
    return col


def _build_where_clause(
    filter_dict: dict[str, Any],
    table: str,
) -> tuple[str, list[Any]]:
    """Translate a pymongo-style filter dict into a q where-clause fragment.

    Returns ``(where_fragment, params)`` where *where_fragment* is the text
    after ``where`` (e.g. ``"_id = w0, null error"``) and *params* is the
    list of PyKX-typed values in positional order matching the ``wN``
    placeholders.

    Supports:
    * equality:  ``{"col": value}``
    * null test: ``{"col": None}``
    * ``$in``:   ``{"col": {"$in": [v1, v2, …]}}``
    """
    clauses: list[str] = []
    params: list[Any] = []
    pidx = 0  # running parameter index

    for col, val in filter_dict.items():
        _validate_column(col, table)
        ref = _col_ref(col, table)
        if val is None:
            # Null condition — no parameter needed.
            # q's ``null`` keyword only works on typed columns (symbol,
            # timestamp, long, float).  For general-list / char-vector
            # columns we must use ``0=count each col`` instead.
            _TYPED_COLUMNS = SYMBOL_COLUMNS | TIMESTAMP_COLUMNS | LONG_COLUMNS | FLOAT_COLUMNS
            if col in _TYPED_COLUMNS:
                clauses.append(f"null {ref}")
            else:
                clauses.append(f"0=count each {ref}")
        elif isinstance(val, dict) and "$in" in val:
            # $in operator — pass the list as a single parameter
            items = val["$in"]
            converted = [_python_to_q(col, v) for v in items]
            pname = f"w{pidx}"
            pidx += 1
            clauses.append(f"{ref} in {pname}")
            params.append(converted)
        else:
            # Equality
            pname = f"w{pidx}"
            pidx += 1
            clauses.append(f"{ref} = {pname}")
            params.append(_python_to_q(col, val))

    return ", ".join(clauses), params


def _build_param_header(params: list[Any]) -> str:
    """Build a q function parameter header like ``[w0;w1;w2]``.

    If *params* is empty, returns an empty string (no function wrapper).
    """
    if not params:
        return ""
    names = ";".join(f"w{i}" for i in range(len(params)))
    return f"[{names}]"


def _projection_columns(
    projection: dict[str, int] | None,
    table: str | None = None,
) -> str | None:
    """Extract column names from a pymongo projection dict.

    Returns a comma-separated string of column names, or ``None`` if no
    projection is given (meaning "select all columns").
    """
    if not projection:
        return None
    cols = []
    for col, flag in projection.items():
        if flag:
            _validate_column(col, table)
            cols.append(col)
    return " ".join(cols) if cols else None


# ---------------------------------------------------------------------------
# Read-side helpers
# ---------------------------------------------------------------------------


def _result_to_dicts(result: Any, table: str) -> list[dict[str, Any]]:
    """Convert a q query result (via PyKX) to a list of Python dicts.

    * Uses ``result.pd()`` to obtain a :class:`~pandas.DataFrame`.
    * Replaces ``NaN`` / ``NaT`` with ``None``.
    * Deserialises JSON columns from string back to ``dict`` / ``list``.
    """
    try:
        df = result.pd()
    except AttributeError:
        # The result is already a DataFrame (e.g. in tests with mocks)
        df = result

    if df is None or df.empty:
        return []

    records = df.to_dict("records")

    # Post-process each row: NaN/NaT -> None, deserialise JSON columns,
    # and restore ObjectId instances for id columns.
    for row in records:
        for key, val in row.items():
            # Replace NaN / NaT / empty numpy arrays with None
            if val is pd.NaT:
                row[key] = None
            elif isinstance(val, float) and pd.isna(val):
                row[key] = None
            elif hasattr(val, "__len__") and hasattr(val, "dtype") and len(val) == 0:
                # Empty numpy arrays from null general-list columns
                row[key] = None
            # Empty bytes (b"") / empty strings ("") from null symbols
            # or empty char vectors in q — map them back to None for
            # symbol columns where "" means "no value".
            elif (isinstance(val, bytes) and val == b"") or (key in SYMBOL_COLUMNS and isinstance(val, str) and val == ""):
                row[key] = None
            # Convert pandas Timestamp to Python datetime — mirrors pymongo
            # which returns datetime objects.  Downstream code (db_manager)
            # performs arithmetic on these values.
            elif isinstance(val, pd.Timestamp):
                row[key] = val.to_pydatetime()
            # Restore ObjectId for id columns
            elif key in OBJECTID_COLUMNS and isinstance(val, str) and len(val) == 24:
                try:
                    row[key] = ObjectId(val)
                except Exception:
                    pass
            # Deserialise JSON columns (PyKX may return bytes or str)
            if key in JSON_COLUMNS and isinstance(val, (str, bytes)):
                text = val.decode() if isinstance(val, bytes) else val
                try:
                    row[key] = json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    pass  # leave as-is if not valid JSON

    return records


# ---------------------------------------------------------------------------
# KDBXCollection
# ---------------------------------------------------------------------------


class KDBXCollection:
    """Pymongo-compatible collection backed by a KDB-X table.

    Each method builds a parameterised q expression and executes it via
    :func:`kdbx.connection.pykx_connection`.
    """

    def __init__(self, table: str) -> None:
        _validate_table(table)
        self._table = table

    def __repr__(self) -> str:  # pragma: no cover
        return f"KDBXCollection({self._table!r})"

    # -----------------------------------------------------------------
    # find_one
    # -----------------------------------------------------------------

    def find_one(
        self,
        filter_dict: dict[str, Any] | None = None,
        projection: dict[str, int] | None = None,
    ) -> dict[str, Any] | None:
        """Return the first matching document, or ``None``.

        Parameters
        ----------
        filter_dict:
            Pymongo-style filter (equality, null, ``$in``).
            Pass ``None`` or ``{}`` to match all rows.
        projection:
            Optional ``{col: 1}`` dict to select specific columns.
        """
        filter_dict = filter_dict or {}
        proj = _projection_columns(projection, self._table)
        select_cols = proj if proj else ""

        if not filter_dict:
            q_expr = f"select[1] {select_cols} from {self._table}"
            params: list[Any] = []
        else:
            where_frag, params = _build_where_clause(filter_dict, self._table)
            header = _build_param_header(params)
            q_expr = f"{{{header} select[1] {select_cols} from {self._table} where {where_frag}}}"

        logger.debug("find_one q=%s params=%s", q_expr, params)

        with pykx_connection() as q:
            result = q(q_expr, *params)

        rows = _result_to_dicts(result, self._table)
        return rows[0] if rows else None

    # -----------------------------------------------------------------
    # find
    # -----------------------------------------------------------------

    def find(
        self,
        filter_dict: dict[str, Any] | None = None,
        projection: dict[str, int] | None = None,
        limit: int | None = 10_000,
    ) -> list[dict[str, Any]]:
        """Return matching documents as a list of dicts.

        Parameters
        ----------
        filter_dict:
            Pymongo-style filter (equality, null, ``$in``).
            Pass ``None`` or ``{}`` to match all rows.
        projection:
            Optional ``{col: 1}`` dict to select specific columns.
        limit:
            Maximum number of rows to return.  Defaults to ``10_000``.
            Pass ``None`` to remove the limit (full table scan).
        """
        filter_dict = filter_dict or {}
        proj = _projection_columns(projection, self._table)
        select_cols = proj if proj else ""
        sel = f"select[{limit}]" if limit is not None else "select"

        if not filter_dict:
            q_expr = f"{sel} {select_cols} from {self._table}"
            params: list[Any] = []
        else:
            where_frag, params = _build_where_clause(filter_dict, self._table)
            header = _build_param_header(params)
            q_expr = f"{{{header} {sel} {select_cols} from {self._table} where {where_frag}}}"

        logger.debug("find q=%s params=%s", q_expr, params)

        with pykx_connection() as q:
            result = q(q_expr, *params)

        return _result_to_dicts(result, self._table)

    # -----------------------------------------------------------------
    # insert_one
    # -----------------------------------------------------------------

    def insert_one(self, doc: dict[str, Any]) -> InsertOneResult:
        """Insert a single document (row) and return :class:`InsertOneResult`.

        * ``ObjectId`` values are converted to ``kx.SymbolAtom(str(oid))``.
        * ``datetime`` values are converted to ``kx.TimestampAtom``.
        * ``dict`` / ``list`` values in JSON columns are serialised.
        * ``int`` -> ``kx.LongAtom``, ``float`` -> ``kx.FloatAtom``.
        """
        inserted_id = doc.get("_id")

        columns: list[str] = []
        params: list[Any] = []

        valid = VALID_COLUMNS.get(self._table)
        for col, val in doc.items():
            if valid and col not in valid:
                logger.debug("insert_one: skipping unknown column %r", col)
                continue
            _validate_column(col, self._table)
            columns.append(col)
            params.append(_python_to_q(col, val))

        # PyKX IPC limits queries to 8 parameters.  Pass column names
        # and values as two arguments to stay within the limit regardless
        # of column count.
        q_expr = f"{{[n;v] `{self._table} insert n!v}}"

        logger.debug("insert_one q=%s cols=%s", q_expr, columns)

        col_names = kx.SymbolVector(columns)

        with pykx_connection() as q:
            q(q_expr, col_names, params)

        return InsertOneResult(inserted_id=inserted_id)

    # -----------------------------------------------------------------
    # update_one / update_many
    # -----------------------------------------------------------------

    def _update(
        self,
        filter_dict: dict[str, Any],
        update_doc: dict[str, Any],
        limit_one: bool = False,
    ) -> None:
        """Shared implementation for update_one and update_many."""
        if "$set" not in update_doc:
            raise ValueError("Only $set updates are supported")

        set_fields = update_doc["$set"]
        where_frag, where_params = _build_where_clause(filter_dict, self._table)

        # Build the set-clause: "col1:sN, col2:sN+1, ..."
        set_clauses: list[str] = []
        set_params: list[Any] = []
        sidx = len(where_params)  # start numbering after where params

        for col, val in set_fields.items():
            _validate_column(col, self._table)
            pname = f"w{sidx}"
            sidx += 1
            qval = _python_to_q(col, val)
            # In q, ``update col:val from t where ...`` interprets list
            # values (e.g. CharVector) as per-row values.  Wrapping with
            # ``enlist`` ensures a list value is treated as a single cell.
            if isinstance(qval, (kx.CharVector, kx.List)):
                set_clauses.append(f"{col}:enlist {pname}")
            else:
                set_clauses.append(f"{col}:{pname}")
            set_params.append(qval)

        all_params = where_params + set_params
        header = _build_param_header(all_params)
        set_frag = ", ".join(set_clauses)

        if limit_one:
            # Limit to first matching row via its index.
            # ``first exec i from table where ...`` returns 0N on no match,
            # and ``i = 0N`` matches nothing, so this is safe.
            q_expr = (
                f"{{{header} update {set_frag} from `{self._table}"
                f" where i = first exec i from {self._table} where {where_frag}}}"
            )
        else:
            q_expr = (
                f"{{{header} update {set_frag} from `{self._table} where {where_frag}}}"
            )

        logger.debug("update q=%s params=%s", q_expr, all_params)

        with pykx_connection() as q:
            q(q_expr, *all_params)

    def update_one(
        self,
        filter_dict: dict[str, Any],
        update_doc: dict[str, Any],
    ) -> None:
        """Update the first matching document only."""
        self._update(filter_dict, update_doc, limit_one=True)

    def update_many(
        self,
        filter_dict: dict[str, Any],
        update_doc: dict[str, Any],
    ) -> None:
        """Update all matching documents."""
        self._update(filter_dict, update_doc)

    # -----------------------------------------------------------------
    # delete_one / delete_many
    # -----------------------------------------------------------------

    def _delete(
        self,
        filter_dict: dict[str, Any],
        limit_one: bool = False,
    ) -> None:
        """Shared implementation for delete_one and delete_many."""
        where_frag, params = _build_where_clause(filter_dict, self._table)
        header = _build_param_header(params)

        if limit_one:
            q_expr = (
                f"{{{header} delete from `{self._table}"
                f" where i = first exec i from {self._table} where {where_frag}}}"
            )
        else:
            q_expr = f"{{{header} delete from `{self._table} where {where_frag}}}"

        logger.debug("delete q=%s params=%s", q_expr, params)

        with pykx_connection() as q:
            q(q_expr, *params)

    def delete_one(self, filter_dict: dict[str, Any]) -> None:
        """Delete the first matching document only."""
        self._delete(filter_dict, limit_one=True)

    def delete_many(self, filter_dict: dict[str, Any]) -> None:
        """Delete all matching documents."""
        self._delete(filter_dict)

    # -----------------------------------------------------------------
    # create_index (no-op)
    # -----------------------------------------------------------------

    def create_index(self, field: str, **kwargs: Any) -> None:
        """No-op — KDB-X uses attributes (sorted/unique) set in the schema."""
        logger.debug("create_index(%s) is a no-op on KDB-X", field)


# ---------------------------------------------------------------------------
# KDBXDatabase
# ---------------------------------------------------------------------------


class KDBXDatabase:
    """Pymongo-compatible database object.

    Attribute access returns :class:`KDBXCollection` instances::

        db = KDBXDatabase()
        db.flywheel_runs   # -> KDBXCollection("flywheel_runs")
        db.nims            # -> KDBXCollection("nims")

    Collections are cached — the same attribute always returns the same
    instance.
    """

    def __init__(self) -> None:
        self._collections: dict[str, KDBXCollection] = {}

    def __getattr__(self, name: str) -> KDBXCollection:
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in _VALID_TABLE_NAMES:
            raise AttributeError(f"Unknown table: {name!r}")
        if name not in self._collections:
            self._collections[name] = KDBXCollection(name)
        return self._collections[name]
