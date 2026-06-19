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
"""
SEC Filings -> RAG Ingestion Routes (offline loader)

Loader-style endpoints (pattern: kdb_data.py) that fetch SEC EDGAR filings via
edgartools and upload them to the companion NVIDIA RAG blueprint ingestor, whose
nv-ingest pipeline parses document structure and tables. Each ticker gets its own
collection named ``sec_<ticker>`` (lowercase).

Endpoints:
- POST /sec/ingest       Fetch the latest N filings per form for one ticker and
                         upload them to the RAG ingestor (synchronous, bounded).
- GET  /sec/collections  List existing ``sec_*`` collections from the ingestor.

The ingestor API shape mirrors what the collections/documents proxy routes in this
package already use:
- POST {RAG_INGEST_URL}/collections   (JSON list of names + collection_type/embedding_dimension params)
- POST {RAG_INGEST_URL}/documents     (multipart 'documents' files + 'data' JSON form field)
- GET  {RAG_INGEST_URL}/collections   (returns {"collections": [{"collection_name": ...}, ...]})
"""

import asyncio
import importlib.util
import json
import logging
import os
import re
from typing import List
from typing import Optional

import httpx
from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator

logger = logging.getLogger(__name__)

# Embedding dimension used when creating a collection (matches the frontend default).
# RAG embedder (llama-nemotron-embed-1b-v2 / nv-embedqa-1b-v2) emits 2048-dim vectors;
# the collection dimension MUST match or nv-ingest rejects inserts (insert_dim_mismatch).
SEC_INGEST_EMBEDDING_DIM = int(os.getenv("SEC_INGEST_EMBEDDING_DIM", "2048"))

# Bounded, synchronous v1: a single ticker, a handful of filings.
MAX_FORMS = 6
MAX_COUNT = 5

# Upload timeout: blocking nv-ingest parsing of a 10-K can take a while.
UPLOAD_TIMEOUT_SECONDS = float(os.getenv("SEC_INGEST_UPLOAD_TIMEOUT", "600"))

_TICKER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9.\-]{0,9}$")
_FORM_RE = re.compile(r"^[0-9A-Za-z./\-]{1,12}$")


def _edgartools_available() -> bool:
    """Check whether the edgartools package (``edgar`` module) is importable."""
    try:
        return importlib.util.find_spec("edgar") is not None
    except (ImportError, ValueError):
        return False


class SecIngestRequest(BaseModel):
    """Request model for SEC filing ingestion."""
    ticker: str = Field(..., description="Stock ticker symbol, e.g. 'NVDA'")
    forms: List[str] = Field(default_factory=lambda: ["10-K", "10-Q"],
                             description="SEC form types to ingest, e.g. ['10-K', '10-Q']")
    count: int = Field(default=1, ge=1, le=MAX_COUNT, description="Latest N filings per form")

    @field_validator("ticker")
    @classmethod
    def _validate_ticker(cls, v: str) -> str:
        v = v.strip().upper()
        if not _TICKER_RE.match(v):
            raise ValueError(f"Invalid ticker '{v}': expected 1-10 chars (letters, digits, '.', '-')")
        return v

    @field_validator("forms")
    @classmethod
    def _validate_forms(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("At least one form type is required")
        if len(v) > MAX_FORMS:
            raise ValueError(f"At most {MAX_FORMS} form types per request")
        cleaned = []
        for form in v:
            form = form.strip().upper()
            if not _FORM_RE.match(form):
                raise ValueError(f"Invalid form type '{form}'")
            cleaned.append(form)
        return cleaned


def _fetch_filings_sync(ticker: str, forms: List[str], count: int) -> List[dict]:
    """Fetch the latest `count` filings per form from SEC EDGAR (blocking).

    Uses the same edgartools patterns and SEC_EDGAR_EMAIL identity as the
    sec_filings source agent. Prefers the primary document as HTML so the
    nv-ingest pipeline can parse tables/structure; falls back to plain text.
    """
    from edgar import Company
    from edgar import set_identity

    # SEC requires a user-agent identity for EDGAR access
    set_identity(os.getenv("SEC_EDGAR_EMAIL", "kxta@example.com"))

    company = Company(ticker)

    documents = []
    for form in forms:
        filings = company.get_filings(form=form)
        if filings is None:
            continue
        for filing in filings.head(count):
            safe_form = form.replace("/", "-")
            filing_date = str(getattr(filing, "filing_date", "") or "")
            doc = {
                "form": form,
                "filing_date": filing_date,
                "accession_no": str(getattr(filing, "accession_no", "") or ""),
                "content": None,
                "filename": None,
                "content_type": None,
                "error": None,
            }
            try:
                content = filing.html()
                ext, content_type = ".html", "text/html"
                if not content:
                    content = filing.text()
                    ext, content_type = ".txt", "text/plain"
            except Exception:
                try:
                    content = filing.text()
                    ext, content_type = ".txt", "text/plain"
                except Exception as e:  # pragma: no cover - depends on EDGAR internals
                    content = None
                    doc["error"] = f"Failed to read filing document: {e}"
            if content:
                doc["content"] = content
                doc["content_type"] = content_type
                doc["filename"] = f"{ticker}_{safe_form}_{filing_date or 'unknown'}{ext}"
            documents.append(doc)
    return documents


async def _ensure_collection(client: httpx.AsyncClient, rag_ingest_url: str, collection_name: str) -> None:
    """Create the collection in the RAG ingestor (no-op if it already exists)."""
    try:
        response = await client.post(f"{rag_ingest_url}/collections",
                                     json=[collection_name],
                                     params={
                                         "collection_type": "text",
                                         "embedding_dimension": SEC_INGEST_EMBEDDING_DIM,
                                     })
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"RAG ingestor unreachable at {rag_ingest_url}: {e}") from e

    if response.status_code == 200:
        return

    # Creation failed - tolerate "already exists" by checking the listing.
    try:
        listing = await client.get(f"{rag_ingest_url}/collections")
        if listing.status_code == 200:
            existing = {c.get("collection_name") for c in listing.json().get("collections", []) if isinstance(c, dict)}
            if collection_name in existing:
                logger.info("Collection '%s' already exists, skipping creation", collection_name)
                return
    except Exception as e:
        logger.warning("Failed to verify collection '%s' existence: %s", collection_name, e)

    raise HTTPException(status_code=502, detail=f"Failed to create collection '{collection_name}': {response.text}")


async def _ingest_to_kdbx(ticker: str, documents: List[dict]) -> dict:
    """Best-effort: chunk filing text, embed, and APPEND to a KDB-X vector table so the
    agentic ``kdb_docs`` source can retrieve filings straight from KDB-X (roadmap #1 —
    documents and market data in one engine).

    Gated on KDB_DB_HOST (enhance-when-present); writes to KDB_VECTOR_TABLE (default
    ``sec_docs``). Never raises — KDB-X enrichment must not break the RAG ingest path.
    """
    if not os.getenv("KDB_DB_HOST", "").strip():
        return {"enabled": False, "rows": 0}
    if os.getenv("KDB_DOCS_LEGACY_SEC_INGEST", "").strip().lower() not in ("1", "true", "yes", "on"):
        return {"enabled": False, "rows": 0,
                "reason": "legacy SEC->KDB-X ingest disabled; upload via RAG UI and select the "
                          "collection in Settings -> KDB-X Document Search"}
    import hashlib
    import re as _re

    from kxta.kdb_vector import chunk_text, kdb_vector_ingest

    table = os.getenv("KDB_VECTOR_TABLE", "sec_docs")
    texts: List[str] = []
    ids: List[int] = []
    for doc in documents:
        content = doc.get("content")
        if not content:
            continue
        if (doc.get("content_type") or "").startswith("text/html"):
            content = _re.sub(r"<[^>]+>", " ", content)  # crude HTML -> text for embedding
        fname = doc.get("filename") or ticker
        for idx, chunk in enumerate(chunk_text(content)):
            texts.append(chunk)
            # stable, unique 64-bit id per (filing, chunk) so re-ingest is idempotent-ish
            digest = hashlib.sha1(f"{fname}#{idx}".encode("utf-8")).digest()[:8]
            ids.append(int.from_bytes(digest, "big", signed=True))
    if not texts:
        return {"enabled": True, "rows": 0}
    res = await kdb_vector_ingest(table, texts, ids=ids, replace=False)
    return {
        "enabled": True,
        "table": table,
        "chunks": len(texts),
        "ok": res.get("ok"),
        "table_rows": res.get("rows"),
        "error": res.get("error"),
    }


async def add_sec_ingest_routes(app: FastAPI, rag_ingest_url: Optional[str] = None):
    """Add SEC filing ingestion routes to the FastAPI app.

    Mounted the same way as the KDB data loader / collections proxy routes
    (see fastapi_extensions/register.py). If `rag_ingest_url` is not provided,
    it is read from the RAG_INGEST_URL environment variable (no default), so
    the routes gate themselves with 503 when the ingestor is not configured.
    """
    if rag_ingest_url is None:
        rag_ingest_url = os.getenv("RAG_INGEST_URL") or None
    if rag_ingest_url:
        rag_ingest_url = rag_ingest_url.rstrip("/")

    def _require_ingestor():
        if not rag_ingest_url:
            raise HTTPException(status_code=503,
                                detail="SEC ingestion unavailable: RAG_INGEST_URL is not configured. "
                                "Point it at the RAG blueprint ingestor (e.g. http://ingestor-server:8082/v1).")

    async def ingest_sec_filings(request: SecIngestRequest):
        """
        Fetch SEC EDGAR filings for a ticker and ingest them into the RAG blueprint.

        Fetches the latest `count` filings for each requested form type (default
        10-K and 10-Q), then uploads the primary documents (HTML preferred) to the
        RAG ingestor so the nv-ingest pipeline can parse tables and structure.
        Documents land in the per-ticker collection ``sec_<ticker>``.
        """
        _require_ingestor()
        if not _edgartools_available():
            raise HTTPException(status_code=503,
                                detail="SEC ingestion unavailable: edgartools is not installed. "
                                "Install with: uv pip install -e '.[filings]'")

        ticker = request.ticker
        collection_name = f"sec_{ticker.lower()}"

        try:
            documents = await asyncio.to_thread(_fetch_filings_sync, ticker, request.forms, request.count)
        except Exception as e:
            if "not found" in str(e).lower() or "notfound" in type(e).__name__.lower():
                raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found on SEC EDGAR: {e}") from e
            raise HTTPException(status_code=502, detail=f"Failed to fetch filings from SEC EDGAR: {e}") from e

        if not documents:
            raise HTTPException(status_code=404,
                                detail=f"No filings found for ticker '{ticker}' with forms {request.forms}")

        uploadable = [d for d in documents if d["content"]]
        if not uploadable:
            raise HTTPException(status_code=502,
                                detail=f"Found {len(documents)} filings for '{ticker}' but could not "
                                "retrieve any filing documents from SEC EDGAR")

        files = [("documents", (doc["filename"], doc["content"].encode("utf-8"), doc["content_type"]))
                 for doc in uploadable]
        form_data = {"data": json.dumps({"collection_name": collection_name, "blocking": True})}

        async with httpx.AsyncClient(timeout=httpx.Timeout(UPLOAD_TIMEOUT_SECONDS)) as client:
            await _ensure_collection(client, rag_ingest_url, collection_name)

            try:
                response = await client.post(f"{rag_ingest_url}/documents", files=files, data=form_data)
            except httpx.RequestError as e:
                raise HTTPException(status_code=502, detail=f"Failed to upload documents to RAG ingestor: {e}") from e

            if response.status_code not in (200, 201):
                raise HTTPException(status_code=502,
                                    detail=f"RAG ingestor rejected upload ({response.status_code}): {response.text}")
            try:
                ingestor_response = response.json()
            except ValueError:
                ingestor_response = {"raw": response.text}

        filings_status = []
        for doc in documents:
            filings_status.append({
                "form": doc["form"],
                "filing_date": doc["filing_date"],
                "accession_no": doc["accession_no"],
                "filename": doc["filename"],
                "status": "uploaded" if doc["content"] else "failed",
                "error": doc["error"],
            })

        # Best-effort: also embed the filings into KDB-X vectors for the agentic
        # `kdb_docs` source (never fails the RAG ingest).
        try:
            kdbx_status = await _ingest_to_kdbx(ticker, uploadable)
        except Exception as e:  # pragma: no cover - defensive; helper already guards
            logger.warning("KDB-X vector enrichment failed for %s: %s", ticker, e)
            kdbx_status = {"enabled": True, "ok": False, "error": str(e)}

        logger.info("Ingested %d/%d SEC filings for %s into collection '%s' (kdbx: %s)",
                    len(uploadable),
                    len(documents),
                    ticker,
                    collection_name,
                    kdbx_status)

        return {
            "ticker": ticker,
            "collection": collection_name,
            "forms": request.forms,
            "documents_uploaded": len(uploadable),
            "documents_failed": len(documents) - len(uploadable),
            "filings": filings_status,
            "ingestor_response": ingestor_response,
            "kdbx_vectors": kdbx_status,
        }

    async def list_sec_collections():
        """List existing ``sec_*`` collections from the RAG ingestor."""
        _require_ingestor()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                response = await client.get(f"{rag_ingest_url}/collections")
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"RAG ingestor unreachable at {rag_ingest_url}: {e}") from e

        if response.status_code != 200:
            raise HTTPException(status_code=502,
                                detail=f"Failed to list collections ({response.status_code}): {response.text}")

        payload = response.json()
        collections = [
            c for c in payload.get("collections", [])
            if isinstance(c, dict) and str(c.get("collection_name", "")).startswith("sec_")
        ]
        return {"total_collections": len(collections), "collections": collections}

    app.add_api_route("/sec/ingest",
                      ingest_sec_filings,
                      methods=["POST"],
                      tags=["sec-endpoints"],
                      summary="Ingest SEC EDGAR filings for a ticker into the RAG blueprint")

    app.add_api_route("/sec/collections",
                      list_sec_collections,
                      methods=["GET"],
                      tags=["sec-endpoints"],
                      summary="List sec_* RAG collections")

    logger.info("Added SEC filings ingestion routes (ingestor: %s)", rag_ingest_url or "NOT CONFIGURED")
