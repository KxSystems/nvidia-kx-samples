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
"""KDB-X table schema definitions and creation utilities.

Defines the 7 tables that replace MongoDB and Elasticsearch in the
NVIDIA AI Model Distillation Blueprint, and provides a function to
create them via PyKX.

Tables
------
flywheel_runs       -- replaces MongoDB flywheel runs collection
nims                -- NIM deployment tracking
evaluations         -- evaluation results
customizations      -- model customization runs
llm_judge_runs      -- LLM judge deployment tracking
flywheel_logs       -- replaces Elasticsearch logs index
flywheel_embeddings -- replaces Elasticsearch embeddings index
"""

from __future__ import annotations

import logging

from kdbx.connection import pykx_connection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table names (canonical order)
# ---------------------------------------------------------------------------

TABLE_NAMES: list[str] = [
    "flywheel_runs",
    "nims",
    "evaluations",
    "customizations",
    "llm_judge_runs",
    "flywheel_logs",
    "flywheel_embeddings",
]

# ---------------------------------------------------------------------------
# DDL statements — q table literal syntax
# ---------------------------------------------------------------------------

def flip_ddl(table: str, cols: list[tuple[str, str]]) -> str:
    """Build a ``flip``-based DDL string that handles ``_id`` column names.

    In q, ``_`` is a built-in operator so ``_id`` in ``([] _id:...)``
    syntax is parsed as ``_ id``.  Using ``flip`` with ``(`$"_id")``
    avoids this.
    """
    names = ";".join(f'`$"{c}"' for c, _ in cols)
    types = ";".join(t for _, t in cols)
    return f'{table}:flip ({names})!({types})'


_TABLE_DDL: dict[str, str] = {
    "flywheel_runs": flip_ddl("flywheel_runs", [
        ("_id", "`symbol$()"), ("workload_id", "`symbol$()"),
        ("client_id", "`symbol$()"), ("status", "`symbol$()"),
        ("started_at", "`timestamp$()"), ("finished_at", "`timestamp$()"),
        ("num_records", "`long$()"), ("datasets", "()"),
        ("enrichment_stats", "()"), ("error", "()"),
    ]),
    "nims": flip_ddl("nims", [
        ("_id", "`symbol$()"), ("flywheel_run_id", "`symbol$()"),
        ("model_name", "`symbol$()"), ("status", "`symbol$()"),
        ("deployment_status", "()"), ("started_at", "`timestamp$()"),
        ("finished_at", "`timestamp$()"), ("runtime_seconds", "`float$()"),
        ("error", "()"),
    ]),
    "evaluations": flip_ddl("evaluations", [
        ("_id", "`symbol$()"), ("nim_id", "`symbol$()"),
        ("job_id", "()"), ("eval_type", "`symbol$()"), ("scores", "()"),
        ("started_at", "`timestamp$()"), ("finished_at", "`timestamp$()"),
        ("runtime_seconds", "`float$()"), ("progress", "`float$()"),
        ("nmp_uri", "()"), ("mlflow_uri", "()"), ("error", "()"),
    ]),
    "customizations": flip_ddl("customizations", [
        ("_id", "`symbol$()"), ("nim_id", "`symbol$()"),
        ("job_id", "()"), ("workload_id", "`symbol$()"),
        ("base_model", "`symbol$()"),
        ("customized_model", "()"), ("started_at", "`timestamp$()"),
        ("finished_at", "`timestamp$()"), ("runtime_seconds", "`float$()"),
        ("progress", "`float$()"), ("epochs_completed", "`long$()"),
        ("steps_completed", "`long$()"), ("nmp_uri", "()"), ("error", "()"),
    ]),
    "llm_judge_runs": flip_ddl("llm_judge_runs", [
        ("_id", "`symbol$()"), ("flywheel_run_id", "`symbol$()"),
        ("model_name", "`symbol$()"), ("deployment_type", "`symbol$()"),
        ("deployment_status", "()"), ("error", "()"),
    ]),
    "flywheel_logs": flip_ddl("flywheel_logs", [
        ("doc_id", "`symbol$()"), ("workload_id", "`symbol$()"),
        ("client_id", "`symbol$()"), ("timestamp", "`timestamp$()"),
        ("request", "()"), ("response", "()"),
    ]),
    "flywheel_embeddings": flip_ddl("flywheel_embeddings", [
        ("doc_id", "`symbol$()"), ("index_name", "`symbol$()"),
        ("embedding", "()"), ("tool_name", "`symbol$()"),
        ("query_text", "()"), ("record_id", "`symbol$()"),
        ("timestamp", "()"), ("record", "()"),
    ]),
}

# ---------------------------------------------------------------------------
# Per-table valid column sets — used for identifier validation
# ---------------------------------------------------------------------------

VALID_COLUMNS: dict[str, frozenset[str]] = {
    "flywheel_runs": frozenset({"_id", "workload_id", "client_id", "status", "started_at", "finished_at", "num_records", "datasets", "enrichment_stats", "error"}),
    "nims": frozenset({"_id", "flywheel_run_id", "model_name", "status", "deployment_status", "started_at", "finished_at", "runtime_seconds", "error"}),
    "evaluations": frozenset({"_id", "nim_id", "job_id", "eval_type", "scores", "started_at", "finished_at", "runtime_seconds", "progress", "nmp_uri", "mlflow_uri", "error"}),
    "customizations": frozenset({"_id", "nim_id", "job_id", "workload_id", "base_model", "customized_model", "started_at", "finished_at", "runtime_seconds", "progress", "epochs_completed", "steps_completed", "nmp_uri", "error"}),
    "llm_judge_runs": frozenset({"_id", "flywheel_run_id", "model_name", "deployment_type", "deployment_status", "error"}),
    "flywheel_logs": frozenset({"doc_id", "workload_id", "client_id", "timestamp", "request", "response"}),
    "flywheel_embeddings": frozenset({"doc_id", "index_name", "embedding", "tool_name", "query_text", "record_id", "timestamp", "record"}),
}

ALL_COLUMNS: frozenset[str] = frozenset().union(*VALID_COLUMNS.values())


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------


def create_all_tables(drop_existing: bool = False) -> None:
    """Create all 7 KDB-X tables.

    Parameters
    ----------
    drop_existing : bool
        If ``True``, drop each table before recreating it.  Useful for
        test fixtures that need a clean slate.
    """
    with pykx_connection() as q:

        # Query existing tables once
        existing = q("tables[]")
        # Convert q result to a Python list of strings for membership checks
        try:
            existing_names = [str(t) for t in existing]
        except TypeError:
            # If the result is empty or not iterable, treat as empty
            existing_names = []

        for name in TABLE_NAMES:
            if name in existing_names:
                if drop_existing:
                    logger.info("Dropping existing table: %s", name)
                    q(f"delete {name} from `.")
                else:
                    logger.info("Table %s already exists, skipping", name)
                    continue

            logger.info("Creating table: %s", name)
            q(_TABLE_DDL[name])

        logger.info("All %d tables ready", len(TABLE_NAMES))
