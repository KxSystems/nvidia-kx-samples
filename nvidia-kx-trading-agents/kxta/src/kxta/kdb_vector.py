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
"""Direct-IPC vector search over KDB-X AI tables (roadmap #1: unified retrieval).

KDB-X is a single engine for structured time-series AND unstructured vectors.
This module retrieves unstructured documents stored as embeddings in KDB-X:

1. The query text is embedded with a NeMo Retriever model — the in-cluster
   EMBEDDING_NIM_URL when set, otherwise the NVIDIA hosted API.
2. An in-engine cosine search runs over the table's real-vector column via kdb+
   IPC, reusing kdb_direct_write's licensed-server / unlicensed-client connection
   (the licensed KDB-X executes; the unlicensed PyKX client only ships data).

The query text becomes a NUMERIC vector *before* it touches q, so no q code is
ever built from user input — there is no injection surface. Table / column names
are validated as plain identifiers, and ingest writes only to the named table.
"""

import asyncio
import logging
import os
import re

import aiohttp

from kxta.kdb_direct_write import _connect, _pykx

logger = logging.getLogger(__name__)

# Embedding endpoint: prefer the in-cluster NIM (EMBEDDING_NIM_URL), else hosted.
# KDB_VECTOR_EMBED_MODEL must match the model the table's vectors were built with.
# Base URL WITHOUT a trailing /v1 — we append /v1/embeddings (matches embeddings.py).
_EMBED_URL = (os.getenv("KDB_VECTOR_EMBED_URL") or os.getenv("EMBEDDING_NIM_URL")
              or "https://integrate.api.nvidia.com").rstrip("/")
if _EMBED_URL.endswith("/v1"):
    _EMBED_URL = _EMBED_URL[:-3]
_EMBED_MODEL = os.getenv("KDB_VECTOR_EMBED_MODEL", "nvidia/nv-embedqa-e5-v5")
_HOSTED = "integrate.api.nvidia.com" in _EMBED_URL
_DEFAULT_TABLE = os.getenv("KDB_VECTOR_TABLE", "kxta_sec_nvda")
_MAX_DOC_CHARS = 1800  # keep chunks within the embedder's context window
# Index/metric for the blueprint .rag.* collection API. Empty -> the pod default
# (cagra + L2 on a GPU/cuVS pod, hnsw on CPU), so KXTA inherits GPU acceleration.
_RAG_INDEX = os.getenv("KDB_VECTOR_INDEX", "").strip()
_RAG_METRIC = os.getenv("KDB_VECTOR_METRIC", "").strip()

_IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _ident(name: str, kind: str) -> str:
    """Allow only plain identifiers for table/column names embedded in q code."""
    if not _IDENT_RE.match(name or ""):
        raise ValueError(f"invalid {kind} name: {name!r}")
    return name


def embedding_configured() -> bool:
    """True when an embedding endpoint usable for kdb_docs query embedding is configured.

    Mirrors _embed's resolution: an explicit in-cluster endpoint
    (KDB_VECTOR_EMBED_URL / EMBEDDING_NIM_URL) is assumed usable; the hosted
    default (integrate.api.nvidia.com) 401s without a key, so it only counts
    when NVIDIA_API_KEY is set. Cheap config check — no network call.
    """
    url = (os.getenv("KDB_VECTOR_EMBED_URL", "").strip()
           or os.getenv("EMBEDDING_NIM_URL", "").strip()
           or "https://integrate.api.nvidia.com")
    if "integrate.api.nvidia.com" in url:
        return bool(os.getenv("NVIDIA_API_KEY", "").strip())
    return True


async def _embed(texts: list[str], input_type: str, timeout_s: float = 60.0) -> list[list[float]]:
    headers = {}
    key = os.getenv("NVIDIA_API_KEY", "")
    if _HOSTED and key:
        headers["Authorization"] = f"Bearer {key}"
    out: list[list[float]] = []
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout_s)) as s:
        for i in range(0, len(texts), 32):
            async with s.post(
                    f"{_EMBED_URL}/v1/embeddings",
                    headers=headers,
                    json={
                        "model": _EMBED_MODEL,
                        "input": texts[i:i + 32],
                        "input_type": input_type,
                        "truncate": "END",
                    },
            ) as r:
                r.raise_for_status()
                data = await r.json()
            out.extend(d["embedding"] for d in data["data"])
    return out


def _decode(value) -> str:
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    return str(value)


def _rag_present(q) -> bool:
    """True when the blueprint's .rag.* collection API is loaded on the server."""
    try:
        return bool(q("`createCollection in key `.rag").py())
    except Exception:
        return False


def _search_sync(table: str, qvec: list[float], n: int, vec_col: str, text_col: str) -> list[dict]:
    kx = _pykx()
    with _connect() as q:
        q["qv"] = kx.RealVector(qvec)
        # Preferred: the blueprint's persisted, GPU-indexed collection (cagra/cuVS or hnsw).
        if _rag_present(q) and bool(q(f"`{table} in exec name from .rag.collections").py()):
            res = q(f".rag.search[`{table}; qv; {int(n)}; ()]").py()
            docs, dists = res.get("docs") or [], res.get("distances") or []
            # .rag.search returns best-first; `score` is the index distance.
            return [{"score": round(float(d), 4), "text": _decode(t)} for t, d in zip(docs, dists)]
        # Fallback: raw table + in-engine cosine (ephemeral tables / no .rag.* API).
        q("kdbvcos:{(sum x*y)%(sqrt sum x*x)*sqrt sum y*y}")
        # `sublist` (not `#`): take cycles/repeats rows when n exceeds the row count.
        expr = (f"{int(n)} sublist `kdbvsim xdesc "
                f"select kdbvsim:kdbvcos[qv] each {vec_col}, kdbvtxt:{text_col} from {table}")
        df = q(expr).pd()
    return [{"score": round(float(r["kdbvsim"]), 4), "text": _decode(r["kdbvtxt"])} for _, r in df.iterrows()]


async def kdb_vector_search(query: str,
                            table: str | None = None,
                            n: int = 5,
                            vec_col: str = "vec",
                            text_col: str = "doc") -> dict:
    """Semantic search over a KDB-X vector table. Returns {ok,isError,error,rows}.

    rows = [{"score": float, "text": str}, ...] ranked by cosine similarity.
    """
    table = _ident(table or _DEFAULT_TABLE, "table")
    vec_col = _ident(vec_col, "column")
    text_col = _ident(text_col, "column")
    try:
        qv = (await _embed([query], "query"))[0]
        rows = await asyncio.to_thread(_search_sync, table, qv, n, vec_col, text_col)
        return {"ok": True, "isError": False, "error": None, "rows": rows}
    except Exception as e:
        logger.warning(f"kdb_vector_search failed: {e}")
        return {"ok": False, "isError": True, "error": str(e), "rows": []}


def chunk_text(text: str, size: int = 1500, overlap: int = 150) -> list[str]:
    """Whitespace-normalize and split text into overlapping character windows."""
    text = " ".join((text or "").split())
    if not text:
        return []
    if len(text) <= size:
        return [text]
    step = max(1, size - overlap)
    return [text[i:i + size] for i in range(0, len(text), step)]


def _ingest_sync(table: str, ids: list[int], vecs: list[list[float]], texts: list[str], replace: bool) -> int:
    import numpy as np
    kx = _pykx()
    dim = len(vecs[0]) if vecs else 0
    with _connect() as q:
        q["kdbvid"] = kx.LongVector(np.array(ids, dtype=np.int64))
        q["kdbvvec"] = kx.toq([kx.RealVector(np.array(v, dtype=np.float32)) for v in vecs])
        q["kdbvdoc"] = kx.toq([t.encode("utf-8") for t in texts])
        if _rag_present(q):
            # Persisted, GPU-indexed collection via the blueprint API (survives pod
            # restart through DATA_DIR + .rag.rehydrate, and is visible to the RAG system).
            idx = f"`{_RAG_INDEX}" if _RAG_INDEX else "`"     # `` = null sym -> pod default (cagra/cuVS)
            met = f"`{_RAG_METRIC}" if _RAG_METRIC else "`"
            q("kdbvmeta:(count kdbvid)#enlist ()!()")
            if replace:
                q(f"if[`{table} in exec name from .rag.collections; .rag.deleteCollection[`{table}]]")
            q(f".rag.createCollection[`{table}; {int(dim)}; (); {idx}; {met}]")
            q(f".rag.insert[`{table}; kdbvid; kdbvvec; kdbvdoc; kdbvmeta]")
            return int(q(f"(.rag.listCollections[])`{table}").py())
        # Fallback: raw ephemeral table (no .rag.* API present).
        exists = bool(q(f"`{table} in tables[]").py())
        if replace or not exists:
            q(f"{table}:([] id:kdbvid; vec:kdbvvec; doc:kdbvdoc)")
        else:
            q(f"{table} insert (kdbvid; kdbvvec; kdbvdoc)")
        return int(q(f"count {table}").py())


async def kdb_vector_ingest(table: str, texts: list[str], ids: list[int] | None = None,
                            replace: bool = True) -> dict:
    """Embed texts (passage mode) and create (replace=True) or append (replace=False) an
    KXTA-owned KDB-X vector table.

    Schema: ([] id:long; vec:real; doc:char-vector). Returns {ok,isError,error,rows}
    where rows is the total table count after the write.
    """
    table = _ident(table, "table")
    texts = [(t or "")[:_MAX_DOC_CHARS] for t in texts]
    if not texts:
        return {"ok": True, "isError": False, "error": None, "rows": 0}
    try:
        vecs = await _embed(texts, "passage")
        ids = ids if ids is not None else list(range(len(texts)))
        cnt = await asyncio.to_thread(_ingest_sync, table, ids, vecs, texts, replace)
        return {"ok": True, "isError": False, "error": None, "rows": cnt}
    except Exception as e:
        logger.warning(f"kdb_vector_ingest into {table} failed: {e}")
        return {"ok": False, "isError": True, "error": str(e), "rows": 0}
