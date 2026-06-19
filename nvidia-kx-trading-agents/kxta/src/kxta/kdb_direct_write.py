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
"""Direct q-IPC write path for the KDB data loader, built on PyKX.

The KDB-X MCP server is a READ-ONLY query gateway (its `kdbx_run_sql_query` tool
parses SQL and rejects raw q), so it cannot create/insert tables. Bulk loading
therefore writes DIRECTLY to KDB-X over kdb+ IPC via PyKX, which runs UNLICENSED
for IPC client use (no license needed on this side). The target DB address comes
from KDB_DB_HOST / KDB_DB_PORT (the MCP endpoint is the read path and cannot
carry writes).

Two write surfaces:
- `kdb_exec` / `kdb_exec_batch`: run q expressions server-side (schema `set`s,
  counts) — the expression executes on the KDB-X process, not locally.
- `kdb_insert`: TYPED bulk insert — rows are converted to typed q column vectors
  client-side (dates, times, symbols, floats, longs, char vectors) and inserted
  via `flip` server-side. No q code is built from row values, so there is no
  string-escaping or injection surface for data-driven content.

Safety: destructive operations in the loader are restricted to KXTA-owned tables
(see KXTA_OWNED_TABLES) so the loader can co-locate in a KDB-X that also holds
other data (e.g. RAG collections) without ever touching it.
"""

import asyncio
import logging
import os

# PyKX must see this before its first import anywhere in the process: this module
# is an IPC client only, which unlicensed mode fully supports.
os.environ.setdefault("PYKX_UNLICENSED", "true")

logger = logging.getLogger(__name__)

# The only tables the loader is allowed to create/clear/insert. Never enumerate
# tables[] or touch anything outside this set, so RAG collections etc. are safe.
KXTA_OWNED_TABLES = frozenset({"daily", "trade", "quote", "fundamentals", "news", "recommendations"})

# Column order and q type kind per KXTA-owned table. Must match the empty typed
# schemas the loader `set`s (see clear_kdb_tables / create_public_data_tables in
# routes/kdb_data.py): `insert` aligns columns positionally.
TABLE_SCHEMAS = {
    "daily": {
        "date": "date",
        "sym": "symbol",
        "open": "float",
        "high": "float",
        "low": "float",
        "close": "float",
        "volume": "long"
    },
    "trade": {
        "date": "date", "time": "time", "sym": "symbol", "price": "float", "size": "long"
    },
    "quote": {
        "date": "date",
        "time": "time",
        "sym": "symbol",
        "bid": "float",
        "ask": "float",
        "bsize": "long",
        "asize": "long"
    },
    "fundamentals": {
        "date": "date",
        "sym": "symbol",
        "name": "string",
        "sector": "string",
        "industry": "string",
        "market_cap": "float",
        "pe_ratio": "float",
        "forward_pe": "float",
        "peg_ratio": "float",
        "price_to_book": "float",
        "eps": "float",
        "dividend_yield": "float",
        "beta": "float",
        "fifty_two_week_high": "float",
        "fifty_two_week_low": "float",
        "avg_volume": "long",
        "shares_outstanding": "long"
    },
    "news": {
        "date": "date",
        "time": "time",
        "sym": "symbol",
        "title": "string",
        "summary": "string",
        "publisher": "string",
        "link": "string",
        "news_type": "string"
    },
    "recommendations": {
        "date": "date",
        "sym": "symbol",
        "firm": "string",
        "to_grade": "string",
        "from_grade": "string",
        "action": "string"
    },
}

_NULL_LONG = -9223372036854775808  # q null long (0Nj)


class KdbWriteError(Exception):
    """Raised on a q error, a connection failure, or missing KDB_DB_HOST config."""


def _db_host_port() -> tuple[str, int]:
    return os.getenv("KDB_DB_HOST", "").strip(), int(os.getenv("KDB_DB_PORT", "5000") or "5000")


def assert_kxta_owned(table: str) -> None:
    """Guard: refuse destructive ops on any table the loader doesn't own."""
    if table not in KXTA_OWNED_TABLES:
        raise KdbWriteError(f"refusing destructive op on non-KXTA table '{table}'")


def _pykx():
    """Import PyKX lazily: it is a heavy optional dependency (extra: kdb-loader)."""
    try:
        import pykx
        return pykx
    except ImportError as e:
        raise KdbWriteError("PyKX is not installed — the KDB data loader needs it for direct writes "
                            "(pip install 'kxta[kdb-loader]').") from e


def _connect():
    kx = _pykx()
    host, port = _db_host_port()
    if not host:
        raise KdbWriteError("KDB_DB_HOST is not configured — the data loader needs the KDB-X DB address for "
                            "direct writes (the read-only MCP endpoint cannot carry writes).")
    try:
        return kx.SyncQConnection(host=host, port=port, timeout=15.0)
    except KdbWriteError:
        raise
    except Exception as e:
        raise KdbWriteError(f"KDB-X IPC connection to {host}:{port} failed: {e}") from e


def _parse_q_date(value: str):
    """q-format date string 'YYYY.MM.DD' -> numpy datetime64[D]."""
    import numpy as np
    return np.datetime64(str(value).replace(".", "-"), "D")


def _parse_q_time_ms(value: str) -> int:
    """q-format time string 'HH:MM:SS(.mmm)' -> milliseconds since midnight."""
    hh, mm, rest = str(value).split(":")
    ss, _, frac = rest.partition(".")
    ms = int(frac.ljust(3, "0")[:3]) if frac else 0
    return ((int(hh) * 60 + int(mm)) * 60 + int(ss)) * 1000 + ms


def _column(kind: str, values: list):
    """Convert one column of Python row values into a typed q vector (or char-vector list)."""
    import numpy as np
    kx = _pykx()
    if kind == "date":
        return kx.DateVector(np.array([_parse_q_date(v) for v in values], dtype="datetime64[D]"))
    if kind == "time":
        return kx.TimeVector(np.array([_parse_q_time_ms(v) for v in values], dtype="timedelta64[ms]"))
    if kind == "symbol":
        return kx.SymbolVector([str(v) for v in values])
    if kind == "float":
        return kx.FloatVector(
            np.array([float(v) if v is not None and v == v else float("nan") for v in values], dtype=np.float64))
    if kind == "long":
        return kx.LongVector(np.array([int(v) if v is not None else _NULL_LONG for v in values], dtype=np.int64))
    if kind == "string":
        # bytes -> q char vector; a list of them -> general list column (matches `()` schemas)
        return [("" if v is None else str(v)).encode("utf-8") for v in values]
    raise KdbWriteError(f"unknown column kind '{kind}'")


def _exec_sync(queries: list[str]) -> None:
    with _connect() as q:
        for expr in queries:
            try:
                q(expr)
            except Exception as e:
                raise KdbWriteError(str(e)) from e


def _insert_sync(table: str, rows: list[dict]) -> None:
    schema = TABLE_SCHEMAS[table]
    columns = {name: _column(kind, [row[name] for row in rows]) for name, kind in schema.items()}
    with _connect() as q:
        try:
            # Typed column dict -> table server-side; no q code built from row values.
            q("{[t;d] t insert flip d}", table, columns)
        except Exception as e:
            raise KdbWriteError(str(e)) from e


async def kdb_exec(query: str) -> dict:
    """Run one q expression on KDB-X via PyKX IPC (off-thread).

    Returns a dict shaped like the old MCP result so call-sites keep working:
    {"ok": bool, "isError": bool, "error": str | None}.
    """
    try:
        await asyncio.to_thread(_exec_sync, [query])
        return {"ok": True, "isError": False, "error": None}
    except Exception as e:
        logger.warning(f"kdb_exec failed: {e}")
        return {"ok": False, "isError": True, "error": str(e)}


def _query_sql_sync(sql: str) -> list[dict]:
    """Run a SELECT through KDB-X's SQL engine over IPC and return rows as dicts.

    Sends `.s.e "<sql>"` as a single q expression to the LICENSED KDB-X process —
    the unlicensed PyKX client only deserializes the response, the server does the
    (licensed) q execution. This is the query counterpart to the loader's write
    path, and it sidesteps the MCP server's own embedded-PyKX licensing.
    """
    kx = _pykx()
    # Escape backslashes then double-quotes so the SQL embeds safely in a q char
    # vector: .s.e "SELECT ... WHERE \"sym\" = 'NVDA'"
    escaped = sql.replace("\\", "\\\\").replace('"', '\\"')
    q_expr = f'.s.e "{escaped}"'
    with _connect() as q:
        res = q(q_expr)
        try:
            df = res.pd()
        except Exception:
            return []
        # Round-trip through pandas' JSON writer so dates/Timestamps become ISO
        # strings and numpy scalars become plain numbers — the SSE layer json-dumps
        # these, and raw Timestamps aren't JSON-serializable.
        import json as _json
        return _json.loads(df.to_json(orient="records", date_format="iso"))


async def kdb_query_sql(sql: str) -> dict:
    """Execute a read-only SELECT against KDB-X over IPC (off-thread).

    Returns {"ok", "isError", "error", "rows": list[dict]}. Used by the KDB chat
    so query execution runs on the licensed KDB-X server, not the MCP server's
    (separately-licensed) embedded PyKX.
    """
    try:
        rows = await asyncio.to_thread(_query_sql_sync, sql)
        return {"ok": True, "isError": False, "error": None, "rows": rows}
    except Exception as e:
        logger.warning(f"kdb_query_sql failed: {e}")
        return {"ok": False, "isError": True, "error": str(e), "rows": []}


_QTYPE = {
    "s": "symbol", "f": "float", "e": "real", "j": "long", "i": "int", "h": "short",
    "t": "time", "p": "timestamp", "d": "date", "z": "datetime", "n": "timespan",
    "b": "boolean", "g": "guid", "x": "byte", "c": "char", "C": "string", " ": "list",
}


def _describe_tables_sync(tables: list[str]) -> str:
    """Build an accurate per-table schema string over IPC (licensed KDB-X), so the
    chat's SQL generation sees real columns+types instead of the MCP's
    expired-license discovery. Skips the per-column vector bloat of RAG tables."""
    lines = []
    with _connect() as q:
        existing = {str(t) for t in q("tables[]").py()}
        for t in tables:
            if t not in existing:
                continue
            cols = [str(c) for c in q(f"cols `{t}").py()]
            cnt = int(q(f"count {t}").py())
            tch = q(f"(meta {t})`t").py()
            tch = tch.decode() if isinstance(tch, (bytes, bytearray)) else "".join(map(str, tch))
            typed = ", ".join(f'"{c}" ({_QTYPE.get(ty, ty)})' for c, ty in zip(cols, tch))
            line = f'Table "{t}": {cnt} rows; columns: {typed}'
            if "sym" in cols:
                syms = [str(s) for s in q(f"20 sublist distinct {t}`sym").py()]
                if syms:
                    line += f'; "sym" values: {", ".join(syms)}'
            lines.append(line)
    return "\n".join(lines)


async def kdb_describe_tables(tables: list[str]) -> str:
    """Async wrapper: accurate IPC schema for the given tables (empty string on failure)."""
    try:
        return await asyncio.to_thread(_describe_tables_sync, list(tables))
    except Exception as e:
        logger.warning(f"kdb_describe_tables failed: {e}")
        return ""


_IDENT_RE = __import__("re").compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _ident(name: str, kind: str) -> str:
    """Allow only plain identifiers for table/column names embedded in q code."""
    if not _IDENT_RE.match(name or ""):
        raise KdbWriteError(f"invalid {kind} name: {name!r}")
    return name


def _asof_join_sync(left: str, right: str, keys: list[str], n: int) -> list[dict]:
    """Run `aj[key; left; right]` server-side. The last key is the time column;
    `aj` keeps the left row's time and attaches the most-recent-prior right row
    per the leading keys — i.e. only data known AS OF the left timestamp."""
    import json as _json
    keysym = "".join("`" + k for k in keys)  # ("sym","time") -> `sym`time
    with _connect() as q:
        df = q(f"{int(n)} sublist aj[{keysym}; {left}; {right}]").pd()
        return _json.loads(df.to_json(orient="records", date_format="iso"))


async def kdb_asof_join(left_table: str, right_table: str,
                        keys: tuple[str, ...] = ("sym", "time"), n: int = 200) -> dict:
    """Point-in-time as-of join over KDB-X via IPC (roadmap #4).

    `keys` are the join columns with the TIME column last (e.g. ("sym","time")).
    Each left row is matched to the right row prevailing at its timestamp — no
    lookahead bias. Returns {"ok","isError","error","rows": list[dict]}.
    """
    left = _ident(left_table, "table")
    right = _ident(right_table, "table")
    keys = tuple(_ident(k, "column") for k in keys)
    if len(keys) < 1:
        return {"ok": False, "isError": True, "error": "need at least a time key", "rows": []}
    try:
        rows = await asyncio.to_thread(_asof_join_sync, left, right, list(keys), n)
        return {"ok": True, "isError": False, "error": None, "rows": rows}
    except Exception as e:
        logger.warning(f"kdb_asof_join failed: {e}")
        return {"ok": False, "isError": True, "error": str(e), "rows": []}


def _table_counts_sync(tables: list[str]) -> dict:
    kx = _pykx()
    with _connect() as q:
        # q idiom (vetted against the q skill): existence via tables[], vectorized
        # count over the resolved tables; return ONLY existing tables -> {sym: count}.
        expr = "{[req] ex:req where req in tables[]; ex!count each value each ex}"
        res = q(expr, kx.SymbolVector([str(t) for t in tables])).py()
    counts = {str(k): int(v) for k, v in (res or {}).items()}
    # Missing tables -> None (not present in `counts`); existing -> int row count.
    return {str(t): counts.get(str(t)) for t in tables}


async def kdb_table_counts(tables: list[str]) -> dict:
    """Row count per table: int when the table exists, None when it doesn't.

    Best-effort — returns all-None on any IPC failure rather than raising.
    """
    if not tables:
        return {}
    try:
        return await asyncio.to_thread(_table_counts_sync, list(tables))
    except Exception as e:  # noqa: BLE001
        logger.warning("kdb_table_counts failed: %s", e)
        return {str(t): None for t in tables}


async def kdb_exec_batch(queries: list[str]) -> dict:
    """Run several q expressions over a single IPC connection. All-or-error."""
    try:
        await asyncio.to_thread(_exec_sync, list(queries))
        return {"ok": True, "isError": False, "error": None}
    except Exception as e:
        logger.warning(f"kdb_exec_batch failed: {e}")
        return {"ok": False, "isError": True, "error": str(e)}


async def kdb_insert(table: str, rows: list[dict]) -> dict:
    """Typed bulk insert of row dicts into an KXTA-owned table (off-thread).

    Rows must carry the keys in TABLE_SCHEMAS[table]; dates/times may be the
    loader's q-format strings ('YYYY.MM.DD', 'HH:MM:SS.mmm'). Returns
    {"ok", "isError", "error", "rows": <inserted count>}.
    """
    assert_kxta_owned(table)
    if table not in TABLE_SCHEMAS:
        raise KdbWriteError(f"no schema defined for table '{table}'")
    if not rows:
        return {"ok": True, "isError": False, "error": None, "rows": 0}
    try:
        await asyncio.to_thread(_insert_sync, table, rows)
        return {"ok": True, "isError": False, "error": None, "rows": len(rows)}
    except Exception as e:
        logger.warning(f"kdb_insert into {table} failed: {e}")
        return {"ok": False, "isError": True, "error": str(e), "rows": 0}
