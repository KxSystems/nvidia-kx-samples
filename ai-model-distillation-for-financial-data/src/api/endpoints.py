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
from datetime import datetime
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, Request

from kdbx.schema import TABLE_NAMES, VALID_COLUMNS
from src.api.db import get_db
from src.api.job_service import cancel_job, delete_job, get_job_details
from src.api.models import FlywheelRun
from src.api.schemas import (
    BacktestResponse,
    FlywheelRunStatus,
    JobCancelResponse,
    JobDeleteResponse,
    JobDetailResponse,
    JobListItem,
    JobRequest,
    JobResponse,
    JobsListResponse,
    MarketStatusResponse,
)
from src.config import settings
from src.log_utils import setup_logging
from src.tasks.tasks import run_nim_workflow_dag

logger = setup_logging("data_flywheel.api.endpoints")

router = APIRouter()


@router.post("/jobs", response_model=JobResponse)
async def create_job(request: JobRequest) -> JobResponse:
    """
    Create a new job that runs the NIM workflow.
    """
    # create entry for current time, workload_id, and model_name
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"Request received at {current_time} for workload_id {request.workload_id} and client_id {request.client_id}"
    logger.info(entry)

    # Create FlywheelRun document
    flywheel_run = FlywheelRun(
        workload_id=request.workload_id,
        client_id=request.client_id,
        started_at=datetime.utcnow(),
        num_records=0,  # Will be updated when datasets are created
        nims=[],
        status=FlywheelRunStatus.PENDING,
    )

    # Save to database
    db = get_db()
    result = db.flywheel_runs.insert_one(flywheel_run.to_mongo())
    flywheel_run.id = str(result.inserted_id)

    # Call the NIM workflow task asynchronously. This will be executed
    # in the background.
    run_nim_workflow_dag.delay(
        workload_id=request.workload_id,
        flywheel_run_id=flywheel_run.id,
        client_id=request.client_id,
        data_split_config=request.data_split_config.model_dump()
        if request.data_split_config
        else None,
    )

    return JobResponse(id=flywheel_run.id, status="queued", message="NIM workflow started")


@router.get("/jobs", response_model=JobsListResponse)
async def get_jobs() -> JobsListResponse:
    """
    Get a list of all active and recent jobs.
    """
    db = get_db()
    jobs: list[JobListItem] = []

    # Get all FlywheelRun documents
    for doc in db.flywheel_runs.find():
        flywheel_run = FlywheelRun.from_mongo(doc)
        job = JobListItem(
            id=str(flywheel_run.id),
            workload_id=flywheel_run.workload_id,
            client_id=flywheel_run.client_id,
            status=flywheel_run.status,
            started_at=flywheel_run.started_at,
            finished_at=flywheel_run.finished_at,
            datasets=flywheel_run.datasets,
            error=flywheel_run.error,
        )
        jobs.append(job)

    return JobsListResponse(jobs=jobs)


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
async def get_job(job_id: str) -> JobDetailResponse:
    """
    Get the status and result of a job, including detailed information about all tasks in the workflow.
    """
    return get_job_details(job_id)


@router.delete("/jobs/{job_id}", response_model=JobDeleteResponse)
async def delete_job_endpoint(job_id: str) -> JobDeleteResponse:
    """
    Delete a job and all its associated resources from the database.
    This is an asynchronous operation - the endpoint returns immediately while
    the deletion continues in the background.

    If the job is still running, it must be cancelled first.
    """
    return delete_job(job_id)


@router.post("/jobs/{job_id}/cancel", response_model=JobCancelResponse)
async def cancel_job_endpoint(job_id: str) -> JobCancelResponse:
    """
    Cancel a running job.
    This will stop the job execution and mark it as cancelled.

    The job must be in a running state to be cancelled.
    Already finished jobs cannot be cancelled.
    """
    return cancel_job(job_id)


# ---------------------------------------------------------------------------
# Data Explorer endpoints
# ---------------------------------------------------------------------------

_RESERVED_PARAMS = frozenset({"limit"})


def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Make a KDB-X result row JSON-serializable."""
    out: dict[str, Any] = {}
    for key, val in row.items():
        if isinstance(val, ObjectId):
            out[key] = str(val)
        elif isinstance(val, datetime):
            out[key] = val.isoformat()
        else:
            out[key] = val
    return out


def _extract_filters(table: str, request: Request) -> dict[str, str]:
    """Pull column-equality filters from query params, ignoring non-column keys."""
    valid = VALID_COLUMNS[table]
    return {
        k: v
        for k, v in request.query_params.items()
        if k in valid and k not in _RESERVED_PARAMS
    }


@router.get("/data/schema", tags=["Data Explorer"])
async def get_schema() -> dict[str, Any]:
    """List all KDB-X tables and their columns."""
    return {"tables": {t: sorted(VALID_COLUMNS[t]) for t in TABLE_NAMES}}


@router.get("/data/{table}/count", tags=["Data Explorer"])
async def get_table_count(table: str, request: Request) -> dict[str, Any]:
    """Return the row count for a table, with optional column equality filters."""
    if table not in TABLE_NAMES:
        raise HTTPException(status_code=404, detail=f"Unknown table: {table}")
    db = get_db()
    collection = getattr(db, table)
    filters = _extract_filters(table, request)
    rows = collection.find(filters, limit=None)
    return {"table": table, "count": len(rows)}


@router.get("/data/{table}", tags=["Data Explorer"])
async def get_table_rows(
    table: str,
    request: Request,
    limit: int = Query(50, ge=1, le=1000),
) -> dict[str, Any]:
    """Query rows from a KDB-X table with optional column equality filters."""
    if table not in TABLE_NAMES:
        raise HTTPException(status_code=404, detail=f"Unknown table: {table}")
    db = get_db()
    collection = getattr(db, table)
    filters = _extract_filters(table, request)
    rows = collection.find(filters, limit=limit)
    serialized = [_serialize_row(r) for r in rows]
    return {"table": table, "count": len(serialized), "rows": serialized}


# ---------------------------------------------------------------------------
# Backtest & Market Status endpoints
# ---------------------------------------------------------------------------


@router.post("/backtest", tags=["Financial Analytics"])
async def run_backtest_endpoint(
    model_id: str,
    universe: list[str] | None = Query(None),
    cost_bps: float | None = None,
):
    """Run an ad-hoc backtest for a model's trading signals."""
    from kdbx.backtest import run_backtest

    actual_cost = cost_bps or settings.backtest_config.cost_bps
    results = run_backtest(model_id=model_id, universe=universe, cost_bps=actual_cost)
    return {
        "model_id": model_id,
        "cost_bps": actual_cost,
        "universe": universe,
        **results,
    }


@router.get("/market-status", response_model=MarketStatusResponse, tags=["Financial Analytics"])
async def get_market_status():
    """Get market data table statistics."""
    from kdbx.connection import pykx_connection
    import pykx as kx

    with pykx_connection() as q:
        status = {}
        for table in ["market_ticks", "order_book", "signals", "backtest_results"]:
            try:
                count = int(q("{[t] count value t}", kx.SymbolAtom(table)).py())
                status[table] = {"row_count": count}
            except Exception:
                status[table] = {"row_count": 0, "error": "table not found"}
    return status
