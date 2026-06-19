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
"""Routes for the kdb_docs collection selection (Settings → KDB-X Document Search)."""
import logging
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from kxta.kdb_docs_settings import get_selected_collection, set_selected_collection

logger = logging.getLogger(__name__)


class KdbDocsSettingsRequest(BaseModel):
    """Request body for selecting the kdb_docs collection."""
    collection: Optional[str] = None


async def _list_rag_collections(rag_ingest_url: str) -> list[str]:
    """Names of RAG collections (best-effort; empty list on any failure)."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            resp = await client.get(f"{rag_ingest_url}/collections")
            cols = (resp.json() or {}).get("collections") or []
            return [c.get("collection_name") for c in cols if c.get("collection_name")]
    except Exception as e:  # noqa: BLE001
        logger.warning("kdb-docs settings: failed to list RAG collections: %s", e)
        return []


async def add_kdb_docs_settings_routes(app: FastAPI, rag_ingest_url: str):
    async def get_settings():
        return {
            "collection": get_selected_collection(),
            "available_collections": await _list_rag_collections(rag_ingest_url),
        }

    async def put_settings(req: KdbDocsSettingsRequest):
        try:
            current = set_selected_collection(req.collection)
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        return {
            "collection": current,
            "available_collections": await _list_rag_collections(rag_ingest_url),
        }

    app.add_api_route(
        "/settings/kdb-docs", get_settings, methods=["GET"],
        tags=["kdb-docs"],
        summary="Get the selected KDB-X document collection and the available RAG collections",
    )
    app.add_api_route(
        "/settings/kdb-docs", put_settings, methods=["PUT"],
        tags=["kdb-docs"],
        summary="Select the KDB-X document collection the kdb_docs agent searches",
    )
