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
"""Routes for the kdb (time-series) table selection (agent picker -> KDB tables)."""
import logging
import os
from typing import List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from kxta.kdb_direct_write import kdb_table_counts
from kxta.kdb_tables_settings import get_selected_tables, set_selected_tables

logger = logging.getLogger(__name__)


class KdbTablesSettingsRequest(BaseModel):
    """Request body for selecting the kdb agent's visible tables."""
    tables: List[str] = []


def _available_tables() -> List[str]:
    """Tables the user may choose from = the base allowlist (NOT the current selection).

    Mirrors the base computation in kdb_tools_nat._visible_tables(): KDB_VISIBLE_TABLES
    env (minus the '*'/'all' sentinels) if set, else KXTA's owned tick tables. When the
    deployment is unscoped ('*'/'all') we don't enumerate every co-located table here —
    return [] and let the operator scope via KDB_VISIBLE_TABLES.
    """
    raw = os.getenv("KDB_VISIBLE_TABLES", "").strip()
    if raw and raw not in ("*", "all"):
        return sorted({t.strip() for t in raw.split(",") if t.strip()})
    if raw in ("*", "all"):
        return []
    try:
        from kxta.kdb_direct_write import KXTA_OWNED_TABLES
        return sorted(KXTA_OWNED_TABLES)
    except Exception:  # noqa: BLE001
        return []


async def add_kdb_tables_settings_routes(app: FastAPI):
    async def get_settings():
        available = _available_tables()
        try:
            table_rows = await kdb_table_counts(available)
        except Exception:  # noqa: BLE001
            table_rows = {}
        return {
            "selected_tables": get_selected_tables(),
            "available_tables": available,
            "table_rows": table_rows,
        }

    async def put_settings(req: KdbTablesSettingsRequest):
        try:
            current = set_selected_tables(req.tables)
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        return {"selected_tables": current, "available_tables": _available_tables()}

    app.add_api_route(
        "/settings/kdb-tables", get_settings, methods=["GET"],
        tags=["kdb-docs"],
        summary="Get the selected KDB time-series tables and the available tables",
    )
    app.add_api_route(
        "/settings/kdb-tables", put_settings, methods=["PUT"],
        tags=["kdb-docs"],
        summary="Select which KDB time-series tables the kdb agent may query",
    )
