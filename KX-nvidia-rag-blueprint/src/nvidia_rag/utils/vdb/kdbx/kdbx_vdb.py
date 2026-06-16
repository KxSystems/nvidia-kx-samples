# SPDX-FileCopyrightText: Copyright (c) 2026 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""KdbxVDB — VDBRag implementation backed by KDB-X via PyKX IPC."""
from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
import uuid
from typing import Any
from urllib.parse import urlparse

import numpy as np
import pykx
from langchain_core.documents import Document
from opentelemetry import context as otel_context

from nvidia_rag.utils.vdb.vdb_base import VDBRag

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class KdbxError(Exception):
    """Base for all KDB-X adapter errors."""


class KdbxQError(KdbxError):
    """Any q-side signal raised by the KDB-X server."""


class DimensionMismatchError(KdbxQError):
    """Vector dimension didn't match collection dim (q signal: 'length)."""


class InvalidVectorTypeError(KdbxQError):
    """Vector type wasn't real (float32) (q signal: 'type)."""


class UnsupportedFeatureError(KdbxQError):
    """q raised 'nyi — feature not yet implemented."""


class KdbxOutOfMemoryError(KdbxQError):
    """q raised 'wsfull — workspace full."""


class KdbxGpuFaultError(KdbxQError):
    """CUDA fault — pod restart required for recovery."""


class KdbxNotBootstrappedError(KdbxError):
    """KDB-X server does not have kdbx-init.q loaded.

    Load kdbx-init.q at q startup:  q /opt/kx/conf/kdbx-init.q -p <port>
    See docs/change-vectordb-kdbx.md for setup instructions.
    """


class KdbxVDB(VDBRag):
    """KDB-X vector database adapter — HNSW (CPU) and CAGRA (GPU via kx.cuvs).

    PyKX is used in unlicensed/IPC mode — only pykx.QConnection is touched,
    no q binaries are required client-side.
    """

    def __init__(
        self,
        kdbx_endpoint: str,
        embedding_model: Any | None = None,
        collection_name: str = "",
        **kwargs: Any,
    ) -> None:
        self._embedding_model = embedding_model
        self._host, self._port = self._parse_endpoint(kdbx_endpoint)
        self._conn: pykx.QConnection | None = None  # opened lazily
        # Set once _assert_server_ready confirms kdbx-init.q is loaded.
        # kdbx-init.q is loaded at q startup, so this is a one-time check.
        # The rag-server calls this adapter from a ThreadPoolExecutor, so the
        # check-and-set is guarded by a lock (TODO 2.1): without it two threads
        # can both probe, and the flag write is unsynchronized shared state.
        self._server_ready = False
        self._ready_lock = threading.Lock()
        # nv-ingest plugins are bound to a single collection at construction
        # time — the rag dispatcher passes one through.
        self._collection_name = collection_name
        # Optional metadata-mapping plumbing (parity with kdbai/elastic
        # adapters' cleanup_records signature; defaults make it a no-op).
        self.meta_dataframe = kwargs.get("meta_dataframe")
        self.meta_source_field = kwargs.get("meta_source_field")
        self.meta_fields = kwargs.get("meta_fields")

        # Backend preference (Phase 2). The kdbx q server has ONE index per
        # collection, so the two kdbai-style toggles can't be independent —
        # collapse them: CAGRA is preferred when index_type asks for it OR
        # either GPU toggle is on. This is only a PREFERENCE sent to
        # createCollection; the server downgrades to hnsw when cuVS isn't
        # loaded. metric is the requested default for new collections.
        self._metric = (kwargs.get("metric") or "L2").upper()
        requested = (kwargs.get("index_type") or "hnsw").lower()
        gpu = bool(kwargs.get("enable_gpu_index")) or bool(kwargs.get("enable_gpu_search"))
        # kdbai's GPU index types (cagra) map to our cagra; anything else -> hnsw.
        self._index_type = "cagra" if (requested == "cagra" or gpu) else "hnsw"

    # ------------------------------------------------------------------
    # Lifecycle — context-manager protocol (kdbai parity)
    # ------------------------------------------------------------------

    def close(self) -> None:
        """No-op: we open a fresh SyncQConnection per call, so there is no
        persistent session to release.  Defined for VDBRag parity with
        KDBAIVDB so callers can use ``with KdbxVDB(...) as v:`` and expect
        tidy semantics.
        """
        logger.debug("KdbxVDB.close() — per-call connections, nothing to release")

    def __enter__(self) -> KdbxVDB:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.close()
        return False  # never swallow exceptions

    @staticmethod
    def _parse_endpoint(endpoint: str) -> tuple[str, int]:
        """Accept either host:port or kdbx://host:port (or q://host:port)."""
        if "://" in endpoint:
            parsed = urlparse(endpoint)
            return (parsed.hostname or "kdbx", parsed.port or 5000)
        host, _, port = endpoint.partition(":")
        return (host or "kdbx", int(port) if port else 5000)

    # q symbol names: lead with letter/underscore, then [A-Za-z0-9_.].  Anything
    # else risks escaping the backtick-symbol context when we build q-expression
    # strings that interpolate the collection name (count value, .rag.search).
    _CNAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")

    @classmethod
    def _validate_cname(cls, cname: str) -> str:
        """Reject collection names that could escape a q expression.  Used
        before any f-string that interpolates a cname into a q expression."""
        if not isinstance(cname, str) or not cls._CNAME_RE.match(cname):
            raise ValueError(
                f"Invalid collection name {cname!r}: must match {cls._CNAME_RE.pattern}"
            )
        return cname

    @staticmethod
    def _gen_ids(n: int) -> list[int]:
        """Return *n* collision-free, q-long-safe row ids from uuid4 (top 63 bits).

        Every insert path must use globally-unique ids -- not per-call/per-batch
        sequences. The q keyed upsert dedupes on the id column, and .rag.search
        builds an id->doc dict, so a duplicate id silently overwrites a row and
        drops search results. Sequential range(len) ids restart at 0 on every
        call, so two uploads to the same collection would collide; uuid4 avoids
        that without the TOCTOU of a read-then-offset scheme. (WS-IDFIX)
        """
        return [uuid.uuid4().int >> 65 for _ in range(n)]

    # ------------------------------------------------------------------
    # Connection management — per-call SyncQConnection
    # ------------------------------------------------------------------
    # Fresh SyncQConnection per _q() call avoids the poisoned-connection bug
    # seen on EKS (a long-lived QConnection in a uvicorn worker fails after a
    # kdbx pod restart; a fresh process connects fine). Cost: ~a few ms per
    # call — negligible at our request volumes.
    #
    # pykx exception model:
    #   pykx.QError (subclass of PyKXException) — q-side signal; handle first.
    #   pykx.PyKXException — Python/IPC level (connection, license).

    _CONN_LOST_MARKERS = (
        "authentication error",
        "connection error",
        "connection broken",
        "connection reset",
        "connection closed",
        "broken pipe",
    )

    def _connect(self):
        """Construct a fresh SyncQConnection (caller owns lifetime via `with`)."""
        return pykx.SyncQConnection(host=self._host, port=self._port)

    # ------------------------------------------------------------------
    # Server readiness check
    # ------------------------------------------------------------------

    @staticmethod
    def _qstr(v: Any) -> str:
        """Coerce a pykx char/symbol result to a Python str ("" for null/empty)."""
        try:
            p = v.py()
        except Exception:
            p = v
        if isinstance(p, bytes):
            return p.decode("utf-8", "replace")
        if p is None:
            return ""
        return str(p)

    def _assert_server_ready(self, conn) -> None:
        """Raise KdbxNotBootstrappedError if kdbx-init.q is not loaded on the server.

        Called once per KdbxVDB instance on the first IPC operation. kdbx-init.q
        must be loaded at q startup — the adapter no longer pushes it.
        """
        # Probe must return a CHAR ("1"/"0"), not a boolean: _qstr stringifies a
        # q boolean 1b via .py() -> Python True -> str() -> "True" (not "1"), so a
        # 1b/0b probe would always fail the `ok != "1"` check below and wrongly
        # report .rag.* as not loaded. Return char so _qstr yields "1"/"0".
        ok = self._qstr(conn('@[{.rag.ping[];"1"};::;{"0"}]'))
        if ok != "1":
            raise KdbxNotBootstrappedError(
                f"KDB-X server at {self._host}:{self._port} does not have "
                ".rag.* loaded. Load kdbx-init.q at q startup:\n"
                "  q /opt/kx/conf/kdbx-init.q -p <port>\n"
                "See docs/change-vectordb-kdbx.md for setup instructions."
            )
        self._server_ready = True
        logger.debug("kdbx: server at %s:%s is ready (.rag.ping OK)", self._host, self._port)

    def _q(self, expr: str, *args: Any, retries: int = 5) -> Any:
        """Send a q expression over IPC using a fresh per-call connection.

        Retries with exponential backoff on connection-level errors (e.g. kdbx
        still starting up). q-side signals propagate immediately without retry.
        Raises KdbxNotBootstrappedError on the first call if kdbx-init.q is not
        loaded on the server.
        """
        last_err: Exception | None = None
        for attempt in range(retries):
            try:
                with self._connect() as conn:
                    if not self._server_ready:
                        # Double-checked lock (TODO 2.1): exactly one thread
                        # runs the readiness probe; latecomers re-check the
                        # flag under the lock and skip it.
                        with self._ready_lock:
                            if not self._server_ready:
                                self._assert_server_ready(conn)
                    return conn(expr, *args)
            except pykx.QError as e:
                raise self._map_q_error(e) from e
            except pykx.PyKXException as e:
                msg = str(e).lower()
                if any(m in msg for m in self._CONN_LOST_MARKERS):
                    last_err = e
                    if attempt == retries - 1:
                        raise KdbxQError(str(e)) from e
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise
            except (ConnectionError, OSError) as e:
                last_err = e
                if attempt == retries - 1:
                    # Wrap like the PyKXException branch so callers catching
                    # KdbxError see a uniform type (TODO 2.6).
                    raise KdbxQError(str(e)) from e
                time.sleep(0.5 * (2 ** attempt))
        # Unreachable: every final attempt raises inline. Kept for type-safety.
        raise KdbxQError(str(last_err))

    @staticmethod
    def _map_q_error(e: pykx.QError) -> KdbxQError:
        """Map a pykx.QError to the appropriate KdbxQError subclass.

        The q wrappers raise *named* signals (e.g. `insert_dim_mismatch) rather
        than bare q primitives, so match those names first (pykx-4).  A signal
        like `insert_dim_mismatch contains neither "length" nor "type", so the
        old generic-substring matching never actually fired the right subclass.
        Fall back to the native-primitive substrings last, for errors that
        bubble straight up from kx.ai / kdb+ rather than our wrappers.
        """
        msg = str(e)
        # Named signals emitted by kdbx-init.q wrappers.
        if "dim_mismatch" in msg:
            return DimensionMismatchError(msg)
        # Native q / kx.ai primitives (last-resort substring fallbacks).
        if "wsfull" in msg:
            return KdbxOutOfMemoryError(msg)
        if "CUDA" in msg or "illegal memory" in msg:
            return KdbxGpuFaultError(msg)
        if "nyi" in msg:
            return UnsupportedFeatureError(msg)
        if "length" in msg:
            return DimensionMismatchError(msg)
        if "type" in msg:
            return InvalidVectorTypeError(msg)
        return KdbxQError(msg)

    # ------------------------------------------------------------------
    # VDB (parent) abstract methods — filled in by later tasks
    # ------------------------------------------------------------------

    def create_index(self, **kwargs: Any) -> None:
        """nv-ingest hook: no-op for kdbx (the collection table is created up
        front by .rag.createCollection through create_collection)."""
        return None

    def write_to_index(self, records: list, **kwargs: Any) -> None:
        """nv-ingest hook: translate cleaned records to a .rag.insert batch.

        nv-ingest hands us a list of record dicts containing at least:
          - vector (list[float])      — pre-computed embedding
          - text (str)                — chunk text
          - source (str | dict)       — origin file metadata
          - content_metadata (dict)   — per-chunk metadata
        We map these to (ids, vecs, docs, metas) for the q-side insert wrapper.
        """
        import json as _json

        from nv_ingest_client.util.milvus import cleanup_records

        cleaned = cleanup_records(
            records=records,
            meta_dataframe=getattr(self, "meta_dataframe", None),
            meta_source_field=getattr(self, "meta_source_field", None),
            meta_fields=getattr(self, "meta_fields", None),
        )
        if not cleaned:
            return

        # Build batches keyed by collection name (the adapter is bound to one
        # collection, but make it explicit for the q call).
        cname = self._collection_name or kwargs.get("collection_name") or ""
        if not cname:
            raise ValueError("write_to_index: collection_name unset on adapter")
        # Validate before any string interpolation into a q expression.
        self._validate_cname(cname)

        # Generate collision-resistant long ids from uuid4.  Earlier versions
        # used a read-then-write offset off `count value cname` — that pattern
        # is a TOCTOU under concurrent ingest (two pipelines read the same N,
        # both assign starting at N, the second batch's upsert silently
        # overwrites the first because q keyed upsert dedupes on `id`).
        # uuid4 gives ~122 bits of randomness; the high 63 keep us in q long
        # range (signed 64-bit).  Truly collision-free under realistic load.
        ids: list[int] = []
        vecs: list[list[float]] = []
        docs: list[str] = []
        metas: list[dict[str, Any]] = []
        for i, rec in enumerate(cleaned):
            vec = rec.get("vector") or []
            if not vec:
                continue
            # Preserve the FULL source dict (the rag-server's prepare_citations
            # branch for non-string source does `source.get("source_id")` and
            # passes that to os.path.basename, so source has to round-trip as a
            # dict with at least `source_id` populated).  cleanup_records hands
            # us the original dict; coerce a bare string fallback into the
            # minimum shape downstream is happy with.
            source = rec.get("source", {})
            if not isinstance(source, dict):
                source = {"source_id": str(source), "source_name": str(source)} if source else {}
            if not source.get("source_id"):
                source["source_id"] = source.get("source_name", "")
            meta: dict[str, Any] = {
                "source": _json.dumps(source),
                "content_metadata": _json.dumps(rec.get("content_metadata", {})),
            }
            # Single id-gen codepath (TODO 2.6): _gen_ids owns the uuid4>>65
            # q-long-safe construction so the bit-width can't silently diverge.
            ids.append(self._gen_ids(1)[0])
            vecs.append([float(x) for x in vec])
            docs.append(rec.get("text", "") or "")
            metas.append(meta)

        if not ids:
            return
        logger.info(
            "KDB-X ingestion: writing %d records to collection %r", len(ids), cname
        )
        self._q(
            ".rag.insert",
            cname,
            ids,
            vecs,
            docs,
            metas,
        )

    def retrieval(self, queries: list, **kwargs: Any) -> Any:
        """nv-ingest hook: not used for kdbx — retrieval goes through
        retrieval_langchain on the rag-server side."""
        raise NotImplementedError(
            "Use retrieval_langchain on KdbxVDB for kdbx retrieval"
        )

    def run(self, records: list) -> Any:
        """nv-ingest hook: pipeline entrypoint — create_index then write."""
        self.create_index()
        self.write_to_index(records)
        return None

    def reindex(self, records: list, **kwargs: Any) -> Any:
        """nv-ingest hook: drop the active collection and re-ingest *records*.

        Mirrors KDBAIVDB.reindex (drop + re-run).  Not invoked by the rag or
        ingestor servers today; provided for nv-ingest VDB-interface parity so
        anything depending on it gets the expected drop-and-reload semantics.
        """
        logger.info(
            "Reindexing %d records in %r", len(records), self._collection_name
        )
        if self._collection_name and self.check_collection_exists(self._collection_name):
            self.delete_collections([self._collection_name])
        return self.run(records)

    # ------------------------------------------------------------------
    # VDBRag abstract methods — filled in by later tasks
    # ------------------------------------------------------------------

    @property
    def collection_name(self) -> str:
        return self._collection_name

    @collection_name.setter
    def collection_name(self, value: str) -> None:
        """Set the active collection (kdbai parity).  Most methods take the
        collection name as an explicit argument, so this is rarely needed —
        but it completes the property contract KDBAIVDB exposes."""
        self._collection_name = value

    async def check_health(self) -> dict[str, Any]:
        """Ping KDB-X and return a DatabaseHealthInfo-shaped dict.

        The ingestor's HealthResponse pydantic model requires `service` + `url`
        + `status` keys on each entry of `databases`.  Returning only `status`
        (the old shape) causes the entire /health endpoint to fail validation
        with a 500, which in turn breaks the frontend's create-collection UI
        because it gates on a successful health probe.

        Uses `.rag.ping[]` (note the trailing `[]`) so q invokes the function
        rather than returning its definition.
        """
        base: dict[str, Any] = {
            "service": "KDB-X",
            "url": f"kdbx://{self._host}:{self._port}",
        }
        try:
            # _q is synchronous blocking IPC (TCP connect + q round-trip).
            # Run it in the default executor so the probe doesn't stall the
            # uvicorn event loop for every in-flight request (TODO 2.2).
            result = await asyncio.get_running_loop().run_in_executor(
                None, self._q, ".rag.ping[]"
            )
            if hasattr(result, "py"):
                result = result.py()
            if str(result) != "pong":
                logger.warning("Unexpected ping response: %r", result)
            return {**base, "status": "healthy"}
        except Exception as e:
            return {**base, "status": "unhealthy", "error": str(e)}

    def create_collection(
        self,
        collection_name: str,
        dimension: int = 2048,
        collection_type: str = "text",
    ) -> None:
        """Create a collection in KDB-X with the configured index backend.

        Sends the backend *preference* (``self._index_type`` — "hnsw" or
        "cagra") as the 4th arg.  The q wrapper honors it only when cuVS is
        loaded, else downgrades to hnsw and stamps the chosen type.
        """
        # Positional IPC args are injection-safe, but validate anyway so an
        # invalid name (hyphens, leading digit, ...) surfaces as a clean
        # ValueError instead of a confusing q-side signal (TODO 2.4).
        self._validate_cname(collection_name)
        # 5th arg: the requested metric (review-2 #3 — previously self._metric
        # was stored and never used, so collections always built with the q
        # pod's KDBX_METRIC global regardless of search_type). The q side
        # resolves it against `L2`CS`IP and stamps it per-collection.
        chosen = self._q(
            ".rag.createCollection",
            collection_name,
            dimension,
            [],
            self._index_type,
            self._metric,
        )
        if hasattr(chosen, "py"):
            chosen = chosen.py()
        chosen_s = chosen.decode() if isinstance(chosen, bytes) else str(chosen)
        logger.info(
            "Created collection %r (dim=%d, type=%s, requested=%s, server-chose=%s)",
            collection_name, dimension, collection_type, self._index_type, chosen_s,
        )

    def check_collection_exists(self, collection_name: str) -> bool:
        """Return True if the collection exists in KDB-X."""
        self._validate_cname(collection_name)
        result = self._q(".rag.collectionExists", collection_name)
        return bool(result)

    def get_collection(self) -> list[dict[str, Any]]:
        """Return all collections in the shape the ingestor + rag-server expect.

        Q-side catalogue uses `name` for the collection identifier; both upstream
        servers iterate using `collection_name`.  Rename here so callers don't
        have to know about the q-side column convention.  Also surface
        `metadata_schema` (decoded from its JSON blob, if any) and the live row
        count per collection (the frontend's "X entities" badge — was hardcoded
        to 0 in the first pass).
        """
        import json as _json
        # One IPC round-trip for BOTH the row counts and the catalogue (TODO
        # 2.6 — this was two sequential calls, each a fresh TCP connection,
        # and the frontend hits this on every collection-list refresh).
        # `(.rag.listCollections[]; .rag.collections)` is a 2-list of
        # name!count and the keyed catalogue table.
        both = self._q("(.rag.listCollections[]; .rag.collections)")
        if hasattr(both, "py"):
            both = both.py()
        if isinstance(both, (list, tuple)) and len(both) == 2:
            counts_raw, result = both[0], both[1]
        else:  # defensive: unexpected shape — treat as catalogue-only
            counts_raw, result = {}, both
        counts: dict[str, int] = {}
        if isinstance(counts_raw, dict):
            counts = {str(k): int(v) for k, v in counts_raw.items()}
        # `.rag.collections` is a q keyed table.  pykx maps it to a KeyedTable;
        # KeyedTable.py() returns a key-major dict shape:
        #   {(name,): {dim: ..., metaSchema: ..., indexFP: ..., indexType: ...}, ...}
        # NOT a column-major {name: [...], dim: [...]} dict.  Earlier code read
        # the wrong shape and produced an empty list → frontend never saw the
        # collections it had just created.
        if hasattr(result, "py"):
            result = result.py()
        rows: list[dict[str, Any]] = []
        if isinstance(result, dict):
            for key, row in result.items():
                # key is a tuple of the keyed-column values; .rag.collections
                # keys on `name` (a single column), so it's a 1-tuple.
                name = key[0] if isinstance(key, tuple) and key else key
                if not isinstance(row, dict):
                    row = {}
                rows.append({"name": str(name), **row})
        elif isinstance(result, (list, tuple)):
            rows = [r for r in result if isinstance(r, dict)]

        out: list[dict[str, Any]] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            cname = str(r.get("name", ""))
            if not cname:
                continue
            # metadata_schema is stored as a JSON-encoded char vector; decode
            # it back to list-of-dicts so the ingestor's pydantic validator
            # sees the expected shape.  Missing/blank → [].
            schema_raw = r.get("metaSchema")
            schema: list[dict[str, Any]] = []
            if isinstance(schema_raw, (bytes, str)) and schema_raw:
                try:
                    decoded = _json.loads(schema_raw)
                    if isinstance(decoded, list):
                        schema = decoded
                except (ValueError, TypeError):
                    pass
            out.append(
                {
                    "collection_name": cname,
                    "num_entities": counts.get(cname, 0),
                    "metadata_schema": schema,
                }
            )
        return out

    def delete_collections(self, collection_names: list[str]) -> dict[str, Any]:
        """Drop each collection from KDB-X.

        Returns the shape that the ingestor's `CollectionsResponse(**...)` expects:
        `{message, successful, failed, total_success, total_failed}`. The handler
        unpacks this with `**`, so returning None blows up with a TypeError.
        """
        successful: list[str] = []
        failed: list[dict[str, Any]] = []
        for name in collection_names:
            try:
                self._q(".rag.deleteCollection", name)
                logger.info("Deleted collection %r", name)
                successful.append(name)
            except Exception as e:
                logger.error("Failed to delete collection %r: %s", name, e)
                failed.append({"collection_name": name, "error_message": str(e)})
        return {
            "message": "Collection deletion process completed.",
            "successful": successful,
            "failed": failed,
            "total_success": len(successful),
            "total_failed": len(failed),
        }

    def upload_text(
        self,
        collection_name: str,
        documents: list[str],
        metadatas: list[dict[str, Any]] | None = None,
        ids: list[int] | None = None,
        batch_size: int = 200,
    ) -> None:
        """Embed and insert documents into a KDB-X collection in batches."""
        if self._embedding_model is None:
            raise ValueError("embedding_model must be set before calling upload_text")
        self._validate_cname(collection_name)

        metadatas = metadatas or [{} for _ in documents]
        # Globally-unique ids (NOT range(len), which restarts at 0 each call and
        # would collide across uploads to the same collection — the q keyed
        # upsert would then silently overwrite earlier rows). (WS-IDFIX)
        ids = ids if ids is not None else self._gen_ids(len(documents))

        for batch_start in range(0, len(documents), batch_size):
            batch_docs = documents[batch_start : batch_start + batch_size]
            batch_metas = metadatas[batch_start : batch_start + batch_size]
            batch_ids = ids[batch_start : batch_start + batch_size]

            raw_vecs = self._embedding_model.embed_documents(batch_docs)
            vecs = [np.asarray(v, dtype=np.float32).tolist() for v in raw_vecs]

            self._q(
                ".rag.insert",
                collection_name,
                batch_ids,
                vecs,
                batch_docs,
                batch_metas,
            )
            logger.debug("Inserted batch of %d docs into %r", len(batch_docs), collection_name)

    def get_documents(self, collection_name: str) -> list[dict[str, Any]]:
        """Return one dict per distinct source document in *collection_name*.

        Each entry is ``{"document_name": <basename>, "metadata": <schema-keyed dict>}``.
        Mirrors the kdbai adapter: the per-chunk ``content_metadata`` blob is
        JSON-decoded and sliced down to whatever fields the collection's metadata
        schema declares.  Documents are de-duplicated by name; the first chunk
        seen for a source supplies its document-level metadata.

        The q ``source`` column stores a JSON-encoded dict (see upload_text —
        we preserve the full source dict so the rag-server's citation builder
        can call ``source.get("source_id")``).  ``source_name`` is the
        originating path; we basename it so the value matches what the
        ingestor's post-upload land-check and the frontend expect.
        """
        import json as _json
        import os as _os

        self._validate_cname(collection_name)
        schema = self.get_metadata_schema(collection_name)
        schema_fields = [
            s.get("name")
            for s in schema
            if isinstance(s, dict) and s.get("name")
        ]

        rows = self._q(".rag.getDocumentsWithMeta", collection_name)
        if hasattr(rows, "py"):
            rows = rows.py()
        # pykx maps a q table to a column-major dict {col: [...]}.  Tolerate a
        # list-of-dicts shape too (defensive).
        if isinstance(rows, dict):
            sources = list(rows.get("source", []))
            metas = list(rows.get("contentMeta", []))
        elif isinstance(rows, (list, tuple)):
            sources = [r.get("source", "") for r in rows if isinstance(r, dict)]
            metas = [r.get("contentMeta", "") for r in rows if isinstance(r, dict)]
        else:
            sources, metas = [], []

        def _decode(blob: Any) -> Any:
            if isinstance(blob, bytes):
                blob = blob.decode()
            if not isinstance(blob, str) or not blob:
                return None
            try:
                return _json.loads(blob)
            except (ValueError, TypeError):
                return None

        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        # sources and metas are aligned per row; zip stops at the shorter.
        for raw_src, raw_meta in zip(sources, metas, strict=False):
            decoded_src = _decode(raw_src)
            if isinstance(decoded_src, dict):
                name = decoded_src.get("source_name") or decoded_src.get("source_id") or ""
            else:
                # Legacy bare-string source.
                name = raw_src.decode() if isinstance(raw_src, bytes) else (raw_src or "")
            doc_name = _os.path.basename(name) if name else ""
            if not doc_name or doc_name in seen:
                continue
            seen.add(doc_name)

            cm = _decode(raw_meta)
            metadata = (
                {field: cm.get(field) for field in schema_fields}
                if isinstance(cm, dict)
                else {}
            )
            out.append({"document_name": doc_name, "metadata": metadata})
        return out

    def delete_documents(self, collection_name: str, source_values: list[str]) -> bool:
        """Delete every row whose source.source_name matches one of source_values.

        The ingestor passes plain filenames (basename only, when
        include_upload_path=False; otherwise the upload-folder-prefixed path —
        we strip to basename to be tolerant of both shapes).

        The `source` column in q stores a JSON-encoded dict — we can't filter
        on a parsed field from q without writing a JSON parser, so we resolve
        target filenames → matching source-blobs on the Python side and pass
        the literal blobs to `.rag.deleteDocumentsByMeta`.

        COST (TODO 2.5): `.rag.getDocuments` below transfers every DISTINCT
        source blob in the collection over IPC, and the q-side delete then
        rebuilds the whole index from the surviving vectors — both scale with
        collection size.  Fine at document counts in the thousands; for very
        large collections expect this call to be slow.  The long-term fix is a
        q-side source index (q-layer change).
        """
        import json as _json
        import os as _os

        self._validate_cname(collection_name)
        targets = {_os.path.basename(v) for v in (source_values or []) if v}
        if not targets:
            return False

        # Pull every stored source blob from the collection's meta table.
        raw_result = self._q(".rag.getDocuments", collection_name)
        if hasattr(raw_result, "py"):
            raw_result = raw_result.py()
        if isinstance(raw_result, dict):
            source_blobs = list(raw_result.get("source", []))
        elif isinstance(raw_result, (list, tuple)):
            source_blobs = list(raw_result)
        else:
            source_blobs = []

        # Filter to blobs whose decoded source_name matches our target filenames.
        matching_blobs: list[str] = []
        for raw in source_blobs:
            if isinstance(raw, bytes):
                raw = raw.decode()
            elif not isinstance(raw, str):
                raw = str(raw)
            try:
                decoded = _json.loads(raw)
            except (ValueError, TypeError):
                decoded = None
            if isinstance(decoded, dict):
                name = decoded.get("source_name") or decoded.get("source_id") or ""
            else:
                # Legacy bare-string source; treat as its own name.
                name = raw
            # nv-ingest stores source_name as the full upload-folder path
            # (`/tmp-data/uploaded_files/<col>/<file>`); the ingestor's DELETE
            # endpoint gives us just the basename.  Compare basenames so
            # paths with or without the upload prefix match.
            if _os.path.basename(name) in targets:
                matching_blobs.append(raw)

        if not matching_blobs:
            logger.info(
                "delete_documents: no matching source in %r for %r",
                collection_name, sorted(targets),
            )
            return False

        deleted = self._q(
            ".rag.deleteDocumentsByMeta", collection_name, matching_blobs,
        )
        if hasattr(deleted, "py"):
            deleted = deleted.py()
        logger.info(
            "delete_documents: removed %d row(s) from %r (matched %d source(s))",
            int(deleted), collection_name, len(matching_blobs),
        )
        return bool(deleted)

    def create_metadata_schema_collection(self) -> None:
        """No-op — KDB-X per-collection schema is set via add_metadata_schema."""
        return

    def add_metadata_schema(
        self,
        collection_name: str,
        metadata_schema: list[dict[str, Any]],
    ) -> None:
        """Persist *metadata_schema* for *collection_name* in KDB-X.

        The schema is JSON-encoded and stored as an opaque q char vector so q
        doesn't auto-promote the uniform list-of-dicts into a table — that
        promotion makes the round-trip non-symmetric (we'd get back a
        column-major dict-of-lists instead of the original list-of-dicts).
        """
        import json as _json
        self._validate_cname(collection_name)
        self._q(
            ".rag.addMetadataSchema",
            collection_name,
            _json.dumps(metadata_schema),
        )

    def get_metadata_schema(self, collection_name: str) -> list[dict[str, Any]]:
        """Retrieve the stored metadata schema for *collection_name*."""
        import json as _json
        self._validate_cname(collection_name)
        result = self._q(".rag.getMetadataSchema", collection_name)
        if hasattr(result, "py"):
            result = result.py()
        # Phase 1: schema is stored as a JSON-encoded char vector (see
        # add_metadata_schema).  Decode it back to a list-of-dicts.  An empty
        # dict means "no schema stored" — return [].
        if isinstance(result, (bytes, str)):
            try:
                decoded = _json.loads(result)
                return decoded if isinstance(decoded, list) else [decoded]
            except (ValueError, TypeError):
                return []
        if isinstance(result, dict) and not result:
            return []
        if isinstance(result, list):
            return result
        return [result] if result else []

    def get_langchain_vectorstore(self, collection_name: str) -> Any:
        """Return a sentinel that the rag-server passes through to
        retrieval_langchain.  Our retrieval_langchain does its own IPC search
        via .rag.search and ignores this argument, so a full LangChain
        VectorStore implementation is unnecessary in Phase 1.
        """
        return self

    def retrieval_langchain(
        self,
        query: str,
        collection_name: str,
        top_k: int = 10,
        filter_expr: str | list[dict[str, Any]] = "",
        **kwargs: Any,
    ) -> list[Document]:
        """Embed *query*, call .rag.search over IPC, return LangChain Documents.

        Metadata filtering is NOT supported on the kdbx backend yet. The q wrapper
        (.rag.search) accepts a filter and kdbx_filters.translate_filter is a
        partial dict-AST->q-triples translator, but the rag-server emits
        filter_expr in Milvus-string / Elasticsearch-list form
        (utils.common.process_filter_expr), which translate_filter does not
        consume. Rather than SILENTLY drop the filter and return unfiltered (i.e.
        wrong) results — a silent divergence from the kdbai/milvus/elastic
        backends — a non-empty filter_expr is REJECTED. Default queries pass ""
        and are unaffected (ENABLE_FILTER_GENERATOR defaults to False).
        """
        if self._embedding_model is None:
            raise ValueError("embedding_model must be set before calling retrieval_langchain")

        # Fail loud on an unsupported filter (see docstring) — never silently
        # return unfiltered results.  Only the EXACT empty string / empty
        # non-string is "no filter": the old compound test let a
        # whitespace-only string fall through and run UNFILTERED (TODO 2.3) —
        # and whitespace-only is indistinguishable from a filter mangled
        # upstream, so it is rejected too.
        filter_is_empty = (
            filter_expr == "" if isinstance(filter_expr, str) else not filter_expr
        )
        if not filter_is_empty:
            raise UnsupportedFeatureError(
                "metadata filtering (filter_expr) is not yet supported on the "
                "kdbx vector backend; the query was rejected rather than silently "
                "returning unfiltered results. Omit the filter / set "
                "ENABLE_FILTER_GENERATOR=False, or use a backend that supports "
                "filtering (kdbai/milvus/elasticsearch)."
            )

        # Propagate the OpenTelemetry context the rag-server passes via otel_ctx
        # (kdbx-2) so the embed + IPC search spans nest under the request trace,
        # matching the kdbai adapter.  Detach in finally so the token never leaks.
        otel_ctx = kwargs.get("otel_ctx")
        token = otel_context.attach(otel_ctx) if otel_ctx is not None else None
        try:
            query_vec = np.asarray(
                self._embedding_model.embed_query(query), dtype=np.float32
            ).tolist()

            # Defense-in-depth: the call below is positional (no q string to
            # escape), but keep the collection-name allowlist check anyway.
            self._validate_cname(collection_name)

            # pykx serializes Python lists/dicts/floats over IPC even in
            # unlicensed mode — the insert path passes vectors positionally the
            # same way — so hand .rag.search the query vector as a positional
            # argument and let the q wrapper cast it to real ("e"$).  No bespoke
            # q-expression string builder, no injection surface, ~half the wire
            # size, and nan/inf become a benign server-side 0n/0w rather than a
            # parse trap.  [pykx-1]  Empty filter list -> q () (unfiltered).
            result = self._q(
                ".rag.search", collection_name, query_vec, int(top_k), []
            )

            # Unpack the q-side dict.  Indexing a pykx.Dictionary with a Python
            # str needs pykx.q (str → q-symbol conversion), which isn't available
            # in unlicensed mode.  `.py()` on the whole result does that conversion
            # server-side via the live IPC connection — it works without a
            # client-side license.  Unit-test mocks pass a plain Python dict, so
            # tolerate both shapes.
            if hasattr(result, "py"):
                result = result.py()
            if not isinstance(result, dict):
                return []

            ids = result.get("ids", [])
            distances = result.get("distances", [])
            docs = result.get("docs", [])
            metas_raw = result.get("metas", [])

            # Q may auto-promote a uniform list-of-dict-of-same-keys into a
            # Table; after `.py()` that becomes a dict-of-lists (column-major).
            # Detect and re-shape back to row-major list[dict].
            if isinstance(metas_raw, dict) and metas_raw:
                cols = list(metas_raw.keys())
                n = len(metas_raw[cols[0]])
                metas = [{c: metas_raw[c][i] for c in cols} for i in range(n)]
            elif isinstance(metas_raw, list):
                metas = metas_raw
            else:
                metas = []

            import json as _json
            documents: list[Document] = []
            for i, (doc_text, meta) in enumerate(zip(docs, metas, strict=False)):
                # Drop empty / whitespace-only chunks. nv-ingest can emit tiny or
                # blank chunks (page breaks, image/table placeholders); the
                # reranker NIM rejects any passage with <1 char ('string_too_short'),
                # which 422s the ENTIRE query. Such chunks carry no retrievable
                # text anyway, so skip them. (distances[i]/ids[i] stay aligned —
                # i still indexes the original docs/metas zip.)
                if not str(doc_text).strip():
                    continue
                merged_meta: dict[str, Any] = dict(meta) if isinstance(meta, dict) else {}
                # write_to_index stored `source` and `content_metadata` as
                # JSON-encoded strings (the q meta-table is a tall (id, key, value)
                # shape; nested dicts have to be flattened).  Decode them back so
                # the rag-server's chain code (prepare_citations etc.) sees the
                # original dict shape — `doc.metadata["source"]["source_id"]` is
                # what it expects.
                for k in ("source", "content_metadata"):
                    v = merged_meta.get(k)
                    if isinstance(v, (bytes, str)) and v:
                        try:
                            merged_meta[k] = _json.loads(v)
                        except (ValueError, TypeError):
                            pass  # leave the string in place if it's not valid JSON
                if not isinstance(merged_meta.get("source"), dict):
                    merged_meta["source"] = {}
                # Stamp the collection name on every result, like the kdbai/milvus/
                # elastic adapters do.  The rag-server citation path reads
                # doc.metadata["collection_name"] (response_generator.py, vlm.py) to
                # build the MinIO thumbnail id for image/table/chart citations; if
                # it's missing those multimodal citations silently resolve to the
                # wrong object.
                merged_meta["collection_name"] = collection_name
                merged_meta["_distance"] = distances[i] if i < len(distances) else None
                merged_meta["_id"] = ids[i] if i < len(ids) else None
                documents.append(Document(page_content=str(doc_text), metadata=merged_meta))

            return documents
        finally:
            if token is not None:
                otel_context.detach(token)
