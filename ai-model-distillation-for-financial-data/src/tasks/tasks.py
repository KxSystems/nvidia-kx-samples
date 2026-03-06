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
import os
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

import requests

from bson import ObjectId
from celery import Celery, chain, group, signals

from src.api.db import init_db
from src.api.db_manager import TaskDBManager, get_db_manager
from src.api.models import (
    DatasetType,
    EvalType,
    EvaluationResult,
    FlywheelRunStatus,
    LLMJudgeRun,
    NIMCustomization,
    NIMEvaluation,
    NIMRun,
    NIMRunStatus,
    TaskResult,
    ToolEvalType,
    WorkloadClassification,
)
from src.api.schemas import DeploymentStatus
from src.config import DataSplitConfig, NIMConfig, settings
from src.lib.flywheel.cancellation import FlywheelCancelledError, check_cancellation
from src.lib.flywheel.cleanup_manager import CleanupManager
from src.lib.flywheel.job_manager import FlywheelJobManager
from src.lib.flywheel.util import (
    identify_workload_type,
)
from src.lib.integration.dataset_creator import DatasetCreator
from src.lib.integration.mlflow_client import MLflowClient
from src.lib.integration.record_exporter import RecordExporter
from src.lib.nemo.customizer import Customizer
from src.lib.nemo.dms_client import DMSClient
from src.lib.nemo.evaluator import Evaluator
from src.lib.nemo.llm_as_judge import LLMAsJudge
from src.log_utils import setup_logging

logger = setup_logging("data_flywheel.tasks")

# Centralised DB helper - keeps KDB-X specifics out of individual tasks
db_manager = None

# Initialize Celery
celery_app = Celery(
    "llm_api",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
)

# Configure Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Prevent Redis from re-queuing long-running tasks
    broker_transport_options={
        "visibility_timeout": 36000,  # 10 hours in seconds (longer than max workflow time)
    },
)


@signals.worker_shutting_down.connect
def worker_shutdown(sig, how, exitcode, **kwargs):
    if str(kwargs.get("sender", "")).startswith("main_worker"):
        logger.info(f"Worker shutdown for the worker: {sig!s}")
        logger.info(f"How: {how!s}")
        logger.info(f"Exitcode: {exitcode!s}")

        logger.info("Calling Cleanup Manager")
        db_manager = get_db_manager()
        cleanup_manager = CleanupManager(db_manager)
        cleanup_manager.cleanup_all_running_resources()


@signals.worker_process_init.connect
def init_worker(**kwargs):
    """Initialize database connection after worker process is forked."""
    global db_manager
    init_db()
    db_manager = get_db_manager()


@celery_app.task(name="tasks.initialize_workflow", pydantic=True)
def initialize_workflow(
    workload_id: str,
    flywheel_run_id: str,
    client_id: str,
    output_dataset_prefix: str = "",
    data_split_config: dict | None = None,
) -> TaskResult:
    """Initializes the workflow for the given workload.
    This task is the first task in the workflow. It is responsible for initializing the workflow.
    Here the flywheel run is updated to running and all the NIMs records are created and set to pending.

    Args:
        workload_id: Unique identifier for this workload
        flywheel_run_id: ID of the FlywheelRun document
        client_id: ID of the client
        output_dataset_prefix: Optional prefix for dataset names
        data_split_config: Optional configuration for data splitting
    """

    # Check for cancellation at the beginning
    # Before we start each task, we need to check the cancellation status of the flywheel run.
    # If the run is cancelled, we need to raise not continue the task. The cancellation and cleanup is handled for each task
    # For the initialize_workflow task, we need to raise an error and stop the workflow.
    _check_cancellation(flywheel_run_id, raise_error=True)

    # update flywheel run status to running
    db_manager.update_flywheel_run_status(flywheel_run_id, FlywheelRunStatus.RUNNING)

    # read llm_as_judge config - only needed for tool-calling-judge evaluation
    # For classification workloads, this is not needed
    needs_llm_judge = (
        settings.evaluation_config.workload_type == "tool_calling"
        and settings.evaluation_config.tool_eval_type == "tool-calling-judge"
    )
    
    if needs_llm_judge:
        llm_as_judge = LLMAsJudge()
        llm_as_judge_cfg = llm_as_judge.config

        # Create LLM judge run using TaskDBManager
        llm_judge_run = LLMJudgeRun(
            flywheel_run_id=ObjectId(flywheel_run_id),
            model_name=llm_as_judge_cfg.model_name,
            deployment_type=llm_as_judge_cfg.deployment_type,
            deployment_status=(
                DeploymentStatus.READY if llm_as_judge_cfg.is_remote else DeploymentStatus.CREATED
            ),
        )

        # Insert using TaskDBManager
        llm_judge_run.id = db_manager.create_llm_judge_run(llm_judge_run)
    else:
        # For classification workloads, we don't need an LLM judge
        llm_as_judge_cfg = None

    # Create NIM runs for each NIM in settings
    for nim in settings.nims:
        nim_config = NIMConfig(**nim.model_dump())
        # Create NIM run in the nims collection
        nim_run = NIMRun(
            flywheel_run_id=ObjectId(flywheel_run_id),
            model_name=nim_config.model_name,
            evaluations=[],
            started_at=None,
            finished_at=None,  # Will be updated when evaluations complete
            runtime_seconds=0,  # Will be updated when evaluations complete
            status=NIMRunStatus.PENDING,
        )

        # Persist and mark status via DB manager
        nim_run.id = db_manager.create_nim_run(nim_run)

    # data_split_config is configurataion that is passed from the API call to the workflow.
    # It is used to configure the data split for the workflow.
    # Convert data_split_config to DataSplitConfig if provided
    split_config = DataSplitConfig(**data_split_config) if data_split_config else None

    # Return the TaskResult with the initialized workflow
    return TaskResult(
        workload_id=workload_id,
        flywheel_run_id=flywheel_run_id,
        client_id=client_id,
        error=None,  # Reset any previous errors
        datasets={},
        llm_judge_config=llm_as_judge_cfg,
        data_split_config=split_config,
    )


@celery_app.task(name="tasks.create_datasets", pydantic=True)
def create_datasets(previous_result: TaskResult) -> TaskResult:
    """Create datasets for the given workload."""
    # This is a quirk of celery, we need to assert the types here
    # https://github.com/celery/celery/blob/main/examples/pydantic/tasks.py
    assert isinstance(previous_result, TaskResult)

    # Extract parameters from previous result
    workload_id = previous_result.workload_id
    flywheel_run_id = previous_result.flywheel_run_id
    client_id = previous_result.client_id

    try:
        # Handle Celery serialization - convert dict to TaskResult if needed
        if isinstance(previous_result, dict):
            previous_result = TaskResult(**previous_result)  # type: ignore

        _check_cancellation(previous_result.flywheel_run_id, raise_error=True)

        # Use custom data split config if provided, otherwise use default
        split_config = (
            previous_result.data_split_config
            if previous_result.data_split_config
            else settings.data_split_config
        )

        # The record exporter is used to export the records from the database.
        # The records are exported based on the split configuration.
        # this uses the client_id and workload_id to get the records from the database.
        records = RecordExporter().get_records(client_id, workload_id, split_config)

        # --- Market data enrichment ---
        if settings.enrichment_config.enabled:
            from kdbx.enrichment import enrich_training_pairs_batch, extract_sym_from_record

            enrichable = []
            for rec in records:
                sym = extract_sym_from_record(rec, settings.enrichment_config)
                ts = rec.get(settings.enrichment_config.timestamp_field)
                if sym and ts:
                    rec["_enrich_sym"] = sym
                    rec["_enrich_ts"] = ts
                    enrichable.append(rec)

            if enrichable:
                logger.info(f"Enriching {len(enrichable)} records with market context")
                try:
                    enriched = enrich_training_pairs_batch(
                        enrichable,
                        sym_field="_enrich_sym",
                        timestamp_field="_enrich_ts",
                    )
                    records = enriched
                    previous_result.enrichment_stats = {
                        "num_enriched": len(enriched),
                        "total_records": len(records),
                        "fields_added": [
                            "market_close", "market_vwap", "market_high",
                            "market_low", "market_volume", "market_bid",
                            "market_ask", "market_spread", "market_mid",
                        ],
                    }
                    logger.info(f"Enrichment complete: {len(enriched)} records enriched")
                except Exception as e:
                    logger.warning(f"Enrichment failed (non-fatal): {e}")
                finally:
                    # Clean up temp keys from all records regardless of success/failure
                    for rec in records:
                        rec.pop("_enrich_sym", None)
                        rec.pop("_enrich_ts", None)

        # --- Market-return labeling ---
        if settings.signal_config.labeling.enabled:
            from kdbx.labeling import compute_return_labels_batch, generate_template_rationale
            from kdbx.enrichment import extract_sym_from_record

            labelable = []
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                sym = extract_sym_from_record(rec, settings.enrichment_config)
                ts = rec.get(settings.enrichment_config.timestamp_field)
                content = (rec.get("response", {}).get("choices", [{}])[0]
                           .get("message", {}).get("content", ""))
                if sym and ts and not content:
                    labelable.append((rec, sym, ts))

            if labelable:
                try:
                    labels = compute_return_labels_batch(
                        [s for _, s, _ in labelable],
                        [t for _, _, t in labelable],
                        settings.signal_config.labeling.return_threshold_bps,
                    )
                    labeled_count = 0
                    for (rec, sym, _), label in zip(labelable, labels):
                        if label["direction"] is None:
                            continue
                        rationale = generate_template_rationale(
                            label["direction"], sym,
                            label["return_pct"], label["entry_price"], label["exit_price"],
                        )
                        rec["response"]["choices"][0]["message"]["content"] = rationale
                        labeled_count += 1
                    logger.info("Labeled %d/%d records with market-return directions",
                                labeled_count, len(labelable))
                except Exception as e:
                    logger.warning("Labeling failed (non-fatal): %s", e)

        # The workload type is identified based on the records.
        # This is used to determine the type of evaluation to be run.
        # Config can override auto-detection with explicit workload_type setting
        workload_type = identify_workload_type(
            records, config_override=settings.evaluation_config.workload_type
        )

        # The dataset creator is used to create the datasets.
        # This validates to ensures that the datasets are created in the correct format for the evaluation and customization.
        datasets = DatasetCreator(
            records,
            flywheel_run_id,
            "",
            workload_id,  # Using empty prefix for now
            client_id,
            split_config=split_config,  # Pass the split config to DatasetCreator
        ).create_datasets(workload_type)

        # Update the existing TaskResult with new data
        previous_result.workload_type = workload_type
        previous_result.datasets = datasets

        return previous_result
    except Exception as e:
        error_msg = f"Error creating datasets: {e!s}"
        logger.error(error_msg)
        # Update flywheel run with error via the DB manager
        db_manager.mark_flywheel_run_error(
            previous_result.flywheel_run_id, error_msg, finished_at=datetime.utcnow()
        )
        # Update all the NIM runs to error
        status = (
            NIMRunStatus.CANCELLED if isinstance(e, FlywheelCancelledError) else NIMRunStatus.FAILED
        )
        db_manager.mark_all_nims_status(previous_result.flywheel_run_id, status, error_msg=str(e))
        # Return a TaskResult so that downstream tasks can gracefully short-circuit
        raise e


@celery_app.task(name="tasks.wait_for_llm_as_judge", pydantic=True)
def wait_for_llm_as_judge(previous_result: TaskResult) -> TaskResult:
    """
    Llm judge could be either local or remote.
    The llm judge is spun up while starting the service. It takes time for the llm judge to be ready.
    If it is local, we need to wait for the model to be loaded.
    If it is remote, we can directly ignore the task and continue.
    """
    # This is a quirk of celery, we need to assert the types here
    # https://github.com/celery/celery/blob/main/examples/pydantic/tasks.py
    assert isinstance(previous_result, TaskResult)

    llm_as_judge_cfg = previous_result.llm_judge_config
    
    # If llm_as_judge_cfg is None (e.g., for classification workloads), skip this task
    if llm_as_judge_cfg is None:
        logger.info("LLM Judge not configured for this workload, skipping wait_for_llm_as_judge task")
        return previous_result
    
    llm_judge_run = LLMJudgeRun(**db_manager.find_llm_judge_run(previous_result.flywheel_run_id))

    try:
        # Check for cancellation at the beginning - this should happen regardless of deployment type
        # If the run is cancelled, we need to raise an error and stop the workflow.
        _check_cancellation(previous_result.flywheel_run_id, raise_error=True)

        if llm_as_judge_cfg.is_remote:
            logger.info("Remote LLM Judge will be used")
            return previous_result

        # Update LLM judge deployment status to pending
        db_manager.update_llm_judge_deployment_status(llm_judge_run.id, DeploymentStatus.PENDING)

        dms_client = DMSClient(nmp_config=settings.nmp_config, nim=llm_as_judge_cfg)

        def progress_callback(status: dict):
            db_manager.update_llm_judge_deployment_status(
                llm_judge_run.id,
                DeploymentStatus(status.get("status", "unknown")),
            )

        # If it is local, we need to wait for the model to be loaded.
        # This will exit if the run is cancelled. This is handled in the DMSClient wait_for_deployment method.
        dms_client.wait_for_deployment(
            flywheel_run_id=previous_result.flywheel_run_id,
            progress_callback=progress_callback,
        )
        # Once the llm judge is ready, it takes time for the model to be synced.
        # This will exit if the run is cancelled. This is handled in the DMSClient wait_for_model_sync method.
        dms_client.wait_for_model_sync(
            flywheel_run_id=previous_result.flywheel_run_id,
            model_name=llm_as_judge_cfg.target_model_for_evaluation(),
        )
    except Exception as e:
        # if any error occurs in the llm judge step, we cannot continue the workflow.
        # we need to mark the flywheel run and all the NIMs as error and raise an exception to stop the workflow.
        error_msg = f"Error waiting for LLM as judge: {e!s}"
        logger.error(error_msg)

        # Handle LLM judge cancellation vs failure properly
        if isinstance(e, FlywheelCancelledError):
            db_manager.mark_llm_judge_cancelled(previous_result.flywheel_run_id, error_msg)
        else:
            db_manager.mark_llm_judge_error(llm_judge_run.id, error_msg)

        # Update flywheel run with error via the DB manager
        db_manager.mark_flywheel_run_error(
            previous_result.flywheel_run_id, error_msg, finished_at=datetime.utcnow()
        )
        # Update all the NIM runs to error
        status = (
            NIMRunStatus.CANCELLED if isinstance(e, FlywheelCancelledError) else NIMRunStatus.FAILED
        )
        db_manager.mark_all_nims_status(previous_result.flywheel_run_id, status, error_msg=str(e))
        raise ValueError(error_msg) from e
    return previous_result


@celery_app.task(name="tasks.spin_up_nim", pydantic=True)
def spin_up_nim(previous_result: TaskResult, nim_config: dict) -> TaskResult:
    """
    Spin up a NIM instance.
    Takes the result from the previous task as input.

    Args:
        previous_result: Result from the previous task
        nim_config: Full NIM configuration including model_name, context_length, etc.
    """
    # for each NIM, we need to spin up the NIM instance before running the evaluation.

    # This is a quirk of celery, we need to assert the types here
    # https://github.com/celery/celery/blob/main/examples/pydantic/tasks.py
    assert isinstance(previous_result, TaskResult)

    # find the nim run for the given model name
    nim_config = NIMConfig(**nim_config)

    previous_result.nim = nim_config
    # Reset all the previous errors as the errors are for the previous NIMs
    previous_result.error = None

    # find the nim run for the given model name
    # This is the NIM run that will be used to run the evaluation.
    # It is fetched from the database using the flywheel run id and the model name.
    # The NIM run is updated with the status of the NIM deployment.
    nim_run = db_manager.find_nim_run(
        previous_result.flywheel_run_id,
        nim_config.model_name,
    )
    if nim_run:
        nim_run = NIMRun(**nim_run)

    try:
        # Check for cancellation at the beginning
        # If the run is cancelled, we need to raise an error but continue the workflow.
        # The cleanup is handled in the except block.
        # This is to ensure that the workflow is not stopped if one of the NIMs is not deployed.
        # The workflow will continue to run for the remaining NIMs.
        # All the subsequent tasks for this NIM will be skipped by checking the cancellation status.
        _check_cancellation(previous_result.flywheel_run_id, raise_error=True)

        dms_client = DMSClient(nmp_config=settings.nmp_config, nim=nim_config)

        start_time = datetime.utcnow()
        if not dms_client.is_deployed():
            logger.info(f"Deploying NIM {nim_config.model_name}")

            try:
                dms_client.deploy_model()
            except Exception as e:
                logger.error(f"Error deploying NIM {nim_config.model_name}: {e}")
                if nim_run:
                    db_manager.mark_nim_error(
                        nim_run.id,
                        error_msg=str(e),
                    )
                previous_result.error = str(e)
                return previous_result
        else:
            logger.info(f"NIM {nim_config.model_name} is already deployed")

        # Set started_at once, deployment has been initiated or NIM was already deployed.
        if nim_run:
            db_manager.set_nim_started(nim_run.id, start_time)

        # This is the progress callback for the NIM deployment.
        # It updates the NIM run with the status of the NIM deployment.
        # It also updates the runtime of the NIM deployment.
        def progress_callback(status: dict):
            current_time = datetime.utcnow()
            runtime_seconds = (current_time - start_time).total_seconds()
            db_manager.update_nim_deployment_status(
                nim_run.id,
                DeploymentStatus(status.get("status", "unknown")),
                runtime_seconds,
            )

        # wait for the NIM deployment to be ready
        # This will exit if the run is cancelled. This is handled in the DMSClient wait_for_deployment method.
        dms_client.wait_for_deployment(
            flywheel_run_id=previous_result.flywheel_run_id,
            progress_callback=progress_callback if nim_run else None,
        )
        # wait for the NIM model to be synced
        # This will exit if the run is cancelled. This is handled in the DMSClient wait_for_model_sync method.
        dms_client.wait_for_model_sync(
            flywheel_run_id=previous_result.flywheel_run_id,
            model_name=nim_config.target_model_for_evaluation(),
        )

        # update the NIM run with the status of the NIM deployment.
        if nim_run:
            db_manager.set_nim_status(
                nim_run.id,
                NIMRunStatus.RUNNING,
                deployment_status=DeploymentStatus.READY,
            )

        return previous_result
    except Exception as e:
        # if any error occurs in the NIM deployment, we need to shut down the NIM deployment.
        # we also need to persist the error on the NIM run.
        error_msg = f"Error spinning up NIM: {e!s}"
        logger.error(error_msg)
        try:
            dms_client.shutdown_deployment()
        except Exception as dms_client_err:
            logger.error(f"Error shutting down NIM {nim_config.model_name}: {dms_client_err!s}")
        # Persist error on NIM run and mark the NIM run as cancelled if the error is due to cancellation.
        if isinstance(e, FlywheelCancelledError):
            if nim_run:
                db_manager.mark_nim_cancelled(
                    nim_run.id,
                    error_msg="Flywheel run cancelled",
                )
            previous_result.error = f"Flywheel run cancelled: {e.message}"
        else:
            if nim_run:
                db_manager.mark_nim_error(
                    nim_run.id,
                    error_msg=str(e),
                )
            previous_result.error = error_msg
        return previous_result


@celery_app.task(name="tasks.run_base_eval", pydantic=True)
def run_base_eval(previous_result: TaskResult) -> TaskResult:
    return run_generic_eval(previous_result, EvalType.BASE, DatasetType.BASE)


def run_generic_eval(
    previous_result: TaskResult, eval_type: EvalType, dataset_type: DatasetType
) -> TaskResult:
    """
    Run the Base/Customization evaluation against the NIM based on the eval_type.
    Takes the NIM details from the previous task.
    """
    # if there any error in the previous task, we need to gracefully skip the evaluation.
    if _should_skip_stage(previous_result, f"run_{eval_type}_eval"):
        return previous_result

    # Check for cancellation at the beginning
    # If the run is cancelled, we need to raise an error but continue the workflow.
    # The cleanup is handled in the except block.
    # This is to ensure that the workflow is not stopped if one of the NIMs is not deployed.
    # The workflow will continue to run for the remaining NIMs.
    # All the subsequent tasks for this NIM will be skipped by checking the cancellation status.
    if _check_cancellation(previous_result.flywheel_run_id, raise_error=False):
        if previous_result and not previous_result.error:
            previous_result.error = (
                f"Task cancelled for flywheel run {previous_result.flywheel_run_id}"
            )
        return previous_result

    logger.info(f"Running {eval_type} evaluation")

    # Get the judge model config from the previous result
    # For classification workloads, llm_judge_config can be None
    llm_judge_config = previous_result.llm_judge_config
    judge_model_config = llm_judge_config.judge_model_config() if llm_judge_config else None
    evaluator = Evaluator(judge_model_config=judge_model_config)
    start_time = datetime.utcnow()

    tool_eval_types = [None]
    if previous_result.workload_type == WorkloadClassification.TOOL_CALLING:
        tool_eval_types = [ToolEvalType.TOOL_CALLING_METRIC]  # , ToolEvalType.TOOL_CALLING_JUDGE]

    jobs: list[dict[str, Any]] = []

    # This is the loop to start evaluation for each tool evaluation type.
    for tool_eval_type in tool_eval_types:
        # Find the NIM run for this model
        nim_run = db_manager.find_nim_run(
            previous_result.flywheel_run_id,
            previous_result.nim.model_name,
        )
        if not nim_run:
            msg = f"No NIM run found for model {previous_result.nim.model_name}"
            logger.error(msg)
            raise ValueError(msg)

        # Create evaluation document first
        evaluation = NIMEvaluation(
            nim_id=nim_run["_id"],
            eval_type=eval_type,
            scores={},  # Will be updated when evaluation completes
            started_at=start_time,
            finished_at=None,  # Will be updated when evaluation completes
            runtime_seconds=0.0,  # Will be updated when evaluation completes
            progress=0.0,  # Will be updated during evaluation
        )

        # Add evaluation to the database
        db_manager.insert_evaluation(evaluation)

        # Fix: Create closure with bound variables
        def make_progress_callback(manager: TaskDBManager, eval_instance):
            def callback(update_data):
                """Update evaluation document with progress"""
                current_time = datetime.utcnow()
                update_data["runtime_seconds"] = (current_time - start_time).total_seconds()
                manager.update_evaluation(eval_instance.id, update_data)

            return callback

        # Create callback with properly bound variables
        progress_callback = make_progress_callback(db_manager, evaluation)

        # Run the evaluation
        try:
            # Based on the eval type, use the appropriate model name.
            # Use customized model name for customization evaluation
            target_model = (
                previous_result.customization.model_name
                if eval_type == EvalType.CUSTOMIZED
                else previous_result.nim.target_model_for_evaluation()
            )

            job_id = evaluator.run_evaluation(
                dataset_name=previous_result.datasets[dataset_type],
                workload_type=previous_result.workload_type,
                target_model=target_model,  # Use the selected target model
                test_file="eval_data.jsonl",
                tool_eval_type=tool_eval_type,
                limit=settings.data_split_config.limit,
            )
            logger.info("Evaluation job id: %s", job_id)

            # update uri in evaluation
            evaluation.nmp_uri = evaluator.get_job_uri(job_id)
            evaluation.job_id = job_id
            progress_callback({"nmp_uri": evaluation.nmp_uri, "job_id": job_id})

            jobs.append(
                {
                    "job_id": job_id,
                    "evaluation": evaluation,
                    "progress_callback": progress_callback,
                    "tool_eval_type": tool_eval_type,
                }
            )
        except Exception as e:
            error_msg = f"Error running {eval_type} evaluation: {e!s}"
            logger.error(error_msg)
            db_manager.update_evaluation(
                evaluation.id,
                {
                    "error": error_msg,
                    "finished_at": datetime.utcnow(),
                    "progress": 0.0,
                },
            )
            previous_result.error = error_msg
            return previous_result

    for job in jobs:
        # Wait for completion with progress updates
        try:
            # This will wait for the evaluation to complete.
            # This will exit if the run is cancelled. This is handled in the evaluator wait_for_evaluation method.
            evaluator.wait_for_evaluation(
                job_id=job["job_id"],
                flywheel_run_id=previous_result.flywheel_run_id,
                polling_interval=5,
                timeout=10800,
                progress_callback=job["progress_callback"],
            )

            # Get final results
            results = evaluator.get_evaluation_results(job["job_id"])
            logger.info(results)

            # Update final results
            finished_time = datetime.utcnow()
            scores: dict[str, float] = {}
            if previous_result.workload_type == WorkloadClassification.TOOL_CALLING:
                if results["tasks"]["custom-tool-calling"]:
                    scores["function_name"] = results["tasks"]["custom-tool-calling"]["metrics"][
                        "tool-calling-accuracy"
                    ]["scores"]["function_name_accuracy"]["value"]
                    scores["function_name_and_args_accuracy"] = results["tasks"][
                        "custom-tool-calling"
                    ]["metrics"]["tool-calling-accuracy"]["scores"][
                        "function_name_and_args_accuracy"
                    ]["value"]

                if results["tasks"]["custom-tool-calling"]["metrics"]["correctness"]:
                    scores["tool_calling_correctness"] = results["tasks"]["custom-tool-calling"][
                        "metrics"
                    ]["correctness"]["scores"]["rating"]["value"]
            elif previous_result.workload_type == WorkloadClassification.GENERIC:
                if results["tasks"]["chat-completion"]:
                    scores["f1_score"] = results["tasks"]["chat-completion"]["metrics"]["f1"][
                        "scores"
                    ]["f1_score"]["value"]
            else:
                raise ValueError(f"Unsupported workload type: {previous_result.workload_type}")

            # MLflow integration - upload results if enabled
            mlflow_uri = None
            if settings.mlflow_config.enabled:
                logger.info(
                    f"MLflow integration enabled - uploading {eval_type} evaluation results for model {previous_result.nim.model_name}"
                )
                try:
                    # Create MLflow client and upload results
                    mlflow_client = MLflowClient(settings.mlflow_config)

                    # Upload evaluation results to MLflow (single call)
                    mlflow_uri = mlflow_client.upload_evaluation_results(
                        job_id=job["job_id"],
                        nmp_eval_uri=job["evaluation"].nmp_uri,
                        flywheel_run_id=previous_result.flywheel_run_id,
                        model_name=previous_result.nim.model_name,
                        eval_type=eval_type.value,
                        workload_type=previous_result.workload_type,
                    )

                except Exception as mlflow_error:
                    logger.error(
                        f"MLflow upload failed for {eval_type} evaluation: {mlflow_error!s}"
                    )
                    # Don't fail the evaluation if MLflow upload fails
                    mlflow_uri = None
                else:
                    if mlflow_uri:
                        logger.info(
                            f"Successfully uploaded {eval_type} evaluation to MLflow: {mlflow_uri}"
                        )
                    else:
                        logger.warning(
                            f"MLflow upload completed but no URI returned for {eval_type} evaluation"
                        )
            else:
                logger.debug(
                    f"MLflow integration disabled - skipping upload for {eval_type} evaluation"
                )

            # Update evaluation with MLflow URI
            job["progress_callback"](
                {
                    "scores": scores,
                    "finished_at": finished_time,
                    "runtime_seconds": (finished_time - start_time).total_seconds(),
                    "progress": 100.0,
                    "mlflow_uri": mlflow_uri,
                }
            )
            previous_result.add_evaluation(
                eval_type,
                EvaluationResult(
                    job_id=job["job_id"],
                    scores=scores,
                    started_at=start_time,
                    finished_at=finished_time,
                    percent_done=100.0,
                ),
            )
        except Exception as e:
            error_msg = f"Error running {eval_type} evaluation: {e!s}"
            logger.error(error_msg)
            db_manager.update_evaluation(
                job["evaluation"].id,
                {
                    "error": error_msg,
                    "finished_at": datetime.utcnow(),
                    "progress": 0.0,
                },
            )
            # cancel evaluation job is not implementedin the evaluator
            # We need to cancel the job here when the evaluator supports it
            # for now, since the job has failed, we ignore the cancellation as it doesn't take up any resources
            # and the NMP will cancel it
            previous_result.error = error_msg

    return previous_result


@celery_app.task(name="tasks.start_customization", pydantic=True)
def start_customization(previous_result: TaskResult) -> TaskResult:
    """
    Start customization process for the NIM.
    Takes the previous evaluation results.

    Args:
        previous_result: Result from the previous task containing workload_id and target_llm_model
    """
    # If the run is cancelled, we need to raise an error but continue the workflow.
    if _check_cancellation(previous_result.flywheel_run_id, raise_error=False):
        if previous_result and not previous_result.error:
            previous_result.error = (
                f"Task cancelled for flywheel run {previous_result.flywheel_run_id}"
            )
        return previous_result

    # skip customization if there is any error in the previous task
    if _should_skip_stage(previous_result, "start_customization"):
        return previous_result

    # skip customization if the NIM is not enabled for customization
    if not previous_result.nim.customization_enabled:
        logger.info(
            f"Customization skipped for {previous_result.nim.model_name} because it is using an external NIM"
        )
        return previous_result

    workload_id = previous_result.workload_id
    target_llm_model = previous_result.nim.model_name
    logger.info(
        f"Starting NIM customization for workload {workload_id} on model {target_llm_model}"
    )

    # Find the NIM run
    nim_run = db_manager.find_nim_run(
        previous_result.flywheel_run_id,
        previous_result.nim.model_name,
    )
    if not nim_run:
        msg = f"No NIM run found for model {target_llm_model}"
        logger.error(msg)
        raise ValueError(msg)

    start_time = datetime.utcnow()
    customizer = Customizer()

    # Create customization document with training tracking fields
    customization = NIMCustomization(
        nim_id=nim_run["_id"],
        workload_id=workload_id,
        base_model=target_llm_model,
        customized_model=None,  # Will be set when job starts
        started_at=start_time,
        progress=0.0,
        epochs_completed=0,
        steps_completed=0,
    )

    # Add customization to database
    db_manager.insert_customization(customization)

    def progress_callback(update_data):
        """Update customization document with progress"""
        current_time = datetime.utcnow()
        update_data["runtime_seconds"] = (current_time - start_time).total_seconds()
        db_manager.update_customization(customization.id, update_data)

    output_model_name = f"customized-{target_llm_model}".replace("/", "-")

    try:
        # Start customization job
        customization_job_id, customized_model = customizer.start_training_job(
            name=f"customization-{workload_id}-{target_llm_model}",
            base_model=previous_result.nim.model_name,
            output_model_name=output_model_name,
            dataset_name=previous_result.datasets[DatasetType.TRAIN],
            training_config=settings.training_config,
            nim_config=previous_result.nim,
        )
        logger.info(f"Customization job id: {customization_job_id}")

        # update uri in customization
        customization.nmp_uri = customizer.get_job_uri(customization_job_id)
        customization.job_id = customization_job_id
        db_manager.update_customization(
            customization.id,
            {
                "nmp_uri": customization.nmp_uri,
                "job_id": customization_job_id,
            },
        )

        # Update customization with model name
        progress_callback({"customized_model": customized_model})

        # Wait for completion with progress updates
        # this will exit if the run is cancelled. This is handled in the customizer wait_for_customization method.
        customizer.wait_for_customization(
            customization_job_id,
            flywheel_run_id=previous_result.flywheel_run_id,
            progress_callback=progress_callback,
        )
        customizer.wait_for_model_sync(
            flywheel_run_id=previous_result.flywheel_run_id,
            customized_model=customized_model,
        )

        # Update completion status
        finished_time = datetime.utcnow()
        final_update = {
            "finished_at": finished_time,
            "runtime_seconds": (finished_time - start_time).total_seconds(),
            "progress": 100.0,
        }
        progress_callback(final_update)

        # Final TaskResult update
        previous_result.update_customization(
            job_id=customization_job_id,
            model_name=customized_model,
            started_at=start_time,
            finished_at=finished_time,
            percent_done=100.0,
        )

    except Exception as e:
        # if any error occurs in the customization step, we need to cancel the customization job.
        # we also need to persist the error on the customization document.
        error_msg = f"Error starting customization: {e!s}"
        logger.error(error_msg)
        db_manager.update_customization(
            customization.id,
            {
                "error": error_msg,
                "finished_at": datetime.utcnow(),
                "progress": 0.0,
            },
        )
        try:
            customizer.cancel_job(customization_job_id)
        except Exception as e:
            logger.error(f"Error cancelling customization job: {e}")
        previous_result.error = error_msg
    return previous_result


@celery_app.task(name="tasks.run_customization_eval", pydantic=True)
def run_customization_eval(previous_result: TaskResult) -> TaskResult:
    """Run evaluation on the customized model."""

    # If the run is cancelled, we need to raise an error but continue the workflow.
    _check_cancellation(previous_result.flywheel_run_id, raise_error=False)

    # skip customization evaluation if there is any error in the previous task
    if _should_skip_stage(previous_result, "run_customization_eval"):
        return previous_result

    try:
        # skip customization evaluation if the NIM is not enabled for customization
        if not previous_result.nim.customization_enabled:
            logger.info(f"Customization disabled for {previous_result.nim.model_name}")
            return previous_result

        # if there is no customized model, we will skip the customization evaluation.
        if not previous_result.customization or not previous_result.customization.model_name:
            msg = "No customized model available for evaluation"
            logger.error(msg)
            raise ValueError(msg)

        customization_model = previous_result.customization.model_name
        workload_id = previous_result.workload_id

        # Find the customization document
        customization_doc = db_manager.find_customization(
            workload_id,
            customization_model,
        )
        if not customization_doc:
            msg = f"No customization found for model {customization_model}"
            logger.error(msg)
            raise ValueError(msg)

        logger.info(
            f"Running evaluation on customized model {customization_model} for workload {workload_id}"
        )

        # Run the evaluation for the customized model.
        next_result = run_generic_eval(previous_result, EvalType.CUSTOMIZED, DatasetType.BASE)

        return next_result
    except Exception as e:
        error_msg = f"Error running customization evaluation: {e!s}"
        logger.error(error_msg)
        previous_result.error = error_msg
        return previous_result


_BUY_KEYWORDS = [
    "BUY", "BULLISH", "LONG", "UPGRADE", "BEAT",
    "OUTPERFORM", "OVERWEIGHT", "POSITIVE", "ACCUMULATE",
]
_SELL_KEYWORDS = [
    "SELL", "BEARISH", "SHORT", "DOWNGRADE", "MISS",
    "UNDERPERFORM", "UNDERWEIGHT", "NEGATIVE", "REDUCE",
    "CRASH", "DECLINE",
]


def _parse_direction(response_text: str) -> str:
    """Extract trading direction from model response text.

    Performs case-insensitive keyword search against financial sentiment
    terms.  Returns ``"HOLD"`` if no actionable keyword is found.
    """
    upper = response_text.upper()
    for kw in _BUY_KEYWORDS:
        if kw in upper:
            return "BUY"
    for kw in _SELL_KEYWORDS:
        if kw in upper:
            return "SELL"
    return "HOLD"


@celery_app.task(name="tasks.generate_signals", pydantic=True)
def generate_signals(previous_result: TaskResult, model_type: str = "base") -> TaskResult:
    """Generate trading signals by running eval records through the NIM and writing to KDB-X."""
    if _should_skip_stage(previous_result, "generate_signals"):
        return previous_result
    if not settings.backtest_config.enabled:
        return previous_result
    if _check_cancellation(previous_result.flywheel_run_id, raise_error=False):
        if previous_result and not previous_result.error:
            previous_result.error = (
                f"Task cancelled for flywheel run {previous_result.flywheel_run_id}"
            )
        return previous_result

    from kdbx.enrichment import extract_sym_from_record
    from kdbx.signals import write_signals_batch

    try:
        # Determine model name based on model_type
        if model_type == "customized":
            if not previous_result.customization or not previous_result.customization.model_name:
                logger.info("No customized model available, skipping signal generation")
                return previous_result
            model_name = previous_result.customization.model_name
        else:
            model_name = previous_result.nim.target_model_for_evaluation()

        # Fetch eval records
        split_config = (
            previous_result.data_split_config
            if previous_result.data_split_config
            else settings.data_split_config
        )
        records = RecordExporter().get_records(
            previous_result.client_id,
            previous_result.workload_id,
            split_config,
        )

        nim_url = f"{settings.nmp_config.nim_base_url}/v1/chat/completions"
        signals_batch: list[dict] = []

        for rec in records:
            # Build chat messages from the record
            messages = rec.get("request", {}).get("messages") if isinstance(rec.get("request"), dict) else None
            if not messages:
                continue

            # Inject system prompt for trading direction classification
            if not messages or messages[0].get("role") != "system":
                messages = [{"role": "system", "content": settings.signal_config.system_prompt}] + messages

            try:
                resp = requests.post(
                    nim_url,
                    json={"model": model_name, "messages": messages},
                    timeout=60,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
            except Exception as e:
                logger.warning("Signal generation request failed for record: %s", e)
                continue

            direction = _parse_direction(content)
            sym = extract_sym_from_record(rec, settings.enrichment_config)

            if not sym:
                continue

            # Use original event timestamp for backtesting; fall back to now
            event_ts = rec.get(settings.enrichment_config.timestamp_field)
            sig_ts = datetime.fromisoformat(event_ts) if event_ts else datetime.utcnow()

            signals_batch.append({
                "signal_id": str(uuid.uuid4()),
                "timestamp": sig_ts,
                "sym": sym,
                "direction": direction,
                "confidence": 0.0,
                "model_id": model_name,
                "rationale": content,
            })

        if signals_batch:
            write_signals_batch(signals_batch)
            logger.info(
                "Generated %d signals for model %s (%s)",
                len(signals_batch), model_name, model_type,
            )
        else:
            logger.info("No signals generated for model %s (%s)", model_name, model_type)

    except Exception as e:
        logger.error("Signal generation failed (non-fatal): %s", e)

    return previous_result


@celery_app.task(name="tasks.run_backtest_assessment", pydantic=True)
def run_backtest_assessment(previous_result: TaskResult, model_type: str = "base") -> TaskResult:
    """Run backtest using signals from the signals table."""
    if _should_skip_stage(previous_result, "run_backtest_assessment"):
        return previous_result
    if not settings.backtest_config.enabled:
        return previous_result
    if _check_cancellation(previous_result.flywheel_run_id, raise_error=False):
        if previous_result and not previous_result.error:
            previous_result.error = (
                f"Task cancelled for flywheel run {previous_result.flywheel_run_id}"
            )
        return previous_result

    from kdbx.backtest import run_backtest
    from kdbx.connection import pykx_connection
    import pykx as kx

    start_time = datetime.utcnow()

    # Select model_id based on model_type
    if model_type == "customized" and previous_result.customization and previous_result.customization.model_name:
        model_id = previous_result.customization.model_name
    else:
        model_id = previous_result.nim.model_name

    nim_run = db_manager.find_nim_run(
        previous_result.flywheel_run_id,
        previous_result.nim.model_name,
    )
    if not nim_run:
        logger.warning(f"No NIM run found for backtest: {model_id}")
        return previous_result

    assessment = NIMEvaluation(
        nim_id=nim_run["_id"],
        eval_type=EvalType.BACKTEST,
        scores={},
        started_at=start_time,
        runtime_seconds=0.0,
        progress=0.0,
    )
    db_manager.insert_evaluation(assessment)

    try:
        with pykx_connection() as q:
            sig_count = int(q(
                "{[mid] count select from signals where model_id = mid}",
                kx.SymbolAtom(model_id),
            ).py())

        if sig_count < settings.backtest_config.min_signals:
            logger.info(
                f"Backtest skipped: {sig_count} signals "
                f"(min={settings.backtest_config.min_signals})"
            )
            db_manager.update_evaluation(assessment.id, {
                "scores": {"n_signals": sig_count, "skipped": True},
                "finished_at": datetime.utcnow(),
                "progress": 100.0,
                "runtime_seconds": (datetime.utcnow() - start_time).total_seconds(),
            })
            return previous_result

        db_manager.update_evaluation(assessment.id, {"progress": 50.0})
        results = run_backtest(
            model_id=model_id,
            cost_bps=settings.backtest_config.cost_bps,
        )

        scores = {
            "sharpe": results["sharpe"],
            "max_drawdown": results["max_drawdown"],
            "total_return": results["total_return"],
            "win_rate": results["win_rate"],
            "n_trades": float(results["n_trades"]),
        }

        finished = datetime.utcnow()
        db_manager.update_evaluation(assessment.id, {
            "scores": scores,
            "finished_at": finished,
            "progress": 100.0,
            "runtime_seconds": (finished - start_time).total_seconds(),
        })

        previous_result.add_evaluation(
            EvalType.BACKTEST,
            EvaluationResult(scores=scores),
        )
        logger.info(
            f"Backtest complete: Sharpe={results['sharpe']:.4f}, trades={results['n_trades']}"
        )

    except Exception as e:
        error_msg = f"Backtest failed: {e!s}"
        logger.error(error_msg)
        db_manager.update_evaluation(assessment.id, {
            "error": error_msg,
            "finished_at": datetime.utcnow(),
            "runtime_seconds": (datetime.utcnow() - start_time).total_seconds(),
        })
        # Backtest failure is non-fatal

    return previous_result


@celery_app.task(name="tasks.shutdown_deployment", pydantic=True)
def shutdown_deployment(previous_results: list[TaskResult] | TaskResult) -> TaskResult:
    """Shutdown the NIM deployment.

    Args:
        previous_results: A single ``TaskResult`` (sequential DAG) or a list (legacy ``group``).
    """
    # This task will spin down the NIM deployment.
    # It will also mark the NIM run as completed.
    previous_result: TaskResult | None = None
    try:
        # Sequential DAG passes a single TaskResult; legacy group passes a list.
        if isinstance(previous_results, TaskResult):
            previous_result = previous_results
            assert previous_result.nim is not None, "TaskResult missing NIM config"
        else:
            previous_result = _extract_previous_result(
                previous_results,
                validator=lambda r: getattr(r, "nim", None) is not None,
                error_msg="No valid TaskResult with NIM config found in results",
            )
        # Mark the NIM run as completed first
        # This will ensure that the NIM run is marked as completed
        # even if the deployment is not shut down in case if the llm judge is same as the NIM.
        try:
            nim_run_doc = db_manager.find_nim_run(
                previous_result.flywheel_run_id,
                previous_result.nim.model_name,
            )
            if nim_run_doc:
                if _check_cancellation(previous_result.flywheel_run_id, raise_error=False):
                    db_manager.mark_nim_cancelled(
                        nim_run_doc["_id"],
                        error_msg="Flywheel run cancelled",
                    )
                else:
                    db_manager.mark_nim_completed(nim_run_doc["_id"], nim_run_doc["started_at"])
        except Exception as update_err:
            logger.error("Failed to update NIM run status to COMPLETED: %s", update_err)

        if (
            previous_result.llm_judge_config
            and not previous_result.llm_judge_config.is_remote
            and previous_result.llm_judge_config.model_name == previous_result.nim.model_name
        ):
            logger.info(
                f"Skip shutting down NIM {previous_result.nim.model_name} as it is the same as the LLM Judge"
            )
            return previous_result

        dms_client = DMSClient(
            nmp_config=settings.nmp_config,
            nim=previous_result.nim,
        )
        # Shutdown the NIM deployment
        dms_client.shutdown_deployment()

        return previous_result
    except Exception as e:
        # if any error occurs in the shutdown deployment step, we need to mark the NIM run as failed.
        error_msg = f"Error shutting down NIM deployment: {e!s}"
        logger.error(error_msg)

        # ``previous_result`` may not be available if extraction failed.
        previous_result = locals().get("previous_result")  # type: ignore[arg-type]
        if not previous_result:
            return previous_result  # type: ignore[return-value]

        nim_run_doc = db_manager.find_nim_run(
            previous_result.flywheel_run_id,
            previous_result.nim.model_name,
        )
        if not nim_run_doc:
            logger.error(
                f"Could not find NIM run for flywheel_run_id: {previous_result.flywheel_run_id}"
            )
            return previous_result

        # Update nim document with error
        db_manager.mark_nim_error(nim_run_doc["_id"], error_msg)
        previous_result.error = error_msg
    return previous_result


@celery_app.task(name="tasks.finalize_flywheel_run", pydantic=True)
def finalize_flywheel_run(previous_results: list[TaskResult] | TaskResult) -> TaskResult:
    """Finalize the Flywheel run by setting its ``finished_at`` timestamp.
    This is the final step of the workflow.
    It will mark the flywheel run as completed and update the flywheel run document with the finished_at timestamp.

    Args:
        previous_results: Either a single ``TaskResult`` or a list returned by a ``group``.
    """

    previous_result: TaskResult | None = None
    try:
        previous_result = _extract_previous_result(
            previous_results,
            validator=lambda r: bool(r.flywheel_run_id),
            error_msg="Could not determine flywheel_run_id when finalizing Flywheel run",
        )
        # sleeping for 1 minute to allow the deployment to be deleted
        # We need to sleep here to allow time for all deployment resources to be fully cleaned up.
        # We cannot poll the deployment status because the endpoint returns "not found" immediately
        # after the deletion is initiated, but the actual cleanup of k8s resources (pods, services, etc.)
        # takes longer. This sleep ensures those resources are fully removed before proceeding.
        # This is done in the finalize step to ensure all deployments have been requested for shutdown
        # before we wait for their cleanup.
        time.sleep(60)

        # This will mark the flywheel run as completed and update the flywheel run document with the finished_at timestamp.
        # this will update only if there is no error recorded on the flywheel run document.
        db_manager.mark_flywheel_run_completed(previous_result.flywheel_run_id, datetime.utcnow())

        logger.info(
            "Flywheel run %s marked as finished at %s",
            previous_result.flywheel_run_id,
            datetime.utcnow(),
        )
        return previous_result
    except Exception as e:
        error_msg = f"Error finalizing Flywheel run: {e!s}"
        logger.error(error_msg)
        if not previous_result:
            return TaskResult(error=error_msg)

        previous_result.error = error_msg
        db_manager.mark_flywheel_run_error(
            previous_result.flywheel_run_id, error_msg, finished_at=datetime.utcnow()
        )

        # sleeping for 1 minute to allow the deployment to be deleted
        # We need to sleep here to allow time for all deployment resources to be fully cleaned up.
        # We cannot poll the deployment status because the endpoint returns "not found" immediately
        # after the deletion is initiated, but the actual cleanup of k8s resources (pods, services, etc.)
        # takes longer. This sleep ensures those resources are fully removed before proceeding.
        # This is done in the finalize step to ensure all deployments have been requested for shutdown
        # before we wait for their cleanup.
        time.sleep(60)
        # If we cannot obtain previous_result, construct a minimal one
        return TaskResult(error=error_msg)


@celery_app.task(
    name="tasks.run_nim_workflow_dag",
    pydantic=True,
    queue="parent_queue",
)
def run_nim_workflow_dag(
    workload_id: str,
    flywheel_run_id: str,
    client_id: str,
    data_split_config: dict | None = None,
) -> dict:
    """
    Execute the NIM workflow as a fully sequential DAG:
    - Data upload and enrichment complete first
    - Per NIM: base eval → signal generation → backtest → customization → cust eval → signal generation → backtest → shutdown
    - Finalize the flywheel run
    """

    # fix for duplicate execution
    # Check if this flywheel run is already running to prevent duplicate execution
    flywheel_run_doc = db_manager.get_flywheel_run(flywheel_run_id)
    if not flywheel_run_doc:
        error_msg = f"FlywheelRun {flywheel_run_id} not found in database"
        logger.error(error_msg)
        raise ValueError(error_msg)

    # sometimes celery runs the task multiple times, so we need to check if the flywheel has already run
    if flywheel_run_doc.get("status") not in [FlywheelRunStatus.PENDING]:
        logger.warning(
            f"FlywheelRun {flywheel_run_id} is already {flywheel_run_doc.get('status')}. Skipping execution."
        )
        return {
            "status": "skipped",
            "reason": f"already_{flywheel_run_doc.get('status')}",
            "flywheel_run_id": flywheel_run_id,
        }

    # Convert data_split_config to DataSplitConfig if provided
    split_config = DataSplitConfig(**data_split_config) if data_split_config else None

    # Create dataset workflow (no longer needs embedding setup since ICL is removed)
    dataset_workflow = create_datasets.s()

    # Create a group of chains for each NIM
    nim_chains = []
    for nim in settings.nims:
        assert isinstance(nim, NIMConfig)
        # For each NIM, create a sequential chain: eval -> signals -> backtest per model
        nim_chain = chain(
            spin_up_nim.s(nim_config=nim.model_dump()),  # Convert NIMConfig to dict
            run_base_eval.s(),
            generate_signals.s(model_type="base"),
            run_backtest_assessment.s(model_type="base"),
            start_customization.s(),
            run_customization_eval.s(),
            generate_signals.s(model_type="customized"),
            run_backtest_assessment.s(model_type="customized"),
            shutdown_deployment.s(),
        )
        nim_chains.append(nim_chain)

    # Create the complete workflow
    workflow = chain(
        initialize_workflow.s(
            workload_id=workload_id,
            flywheel_run_id=flywheel_run_id,
            client_id=client_id,
            data_split_config=split_config.model_dump() if split_config else None,
        ),
        dataset_workflow,
        wait_for_llm_as_judge.s(),  ## spin up llm-judge
        chain(*nim_chains),
        finalize_flywheel_run.s(),
    )

    # Submit the workflow to Celery and block until completion.
    # The application is not currently aware of how
    # many GPUs are available to it, so it serializes all calls
    # to `run_nim_workflow_dag` to prevent spinning up NIMs from taking
    # up all the GPUs and not leaving any available for customizations.
    # The following call to `get` will block. Since this task is running
    # on the ``parent_queue`` it will be serialized with all other tasks
    # on that queue. All other tasks run on the default celery queue,
    # which has a concurrency limit of 50.
    async_result = workflow.apply_async()
    return async_result.get(disable_sync_subtasks=False)


@celery_app.task(name="tasks.delete_job_resources", pydantic=True)
def delete_job_resources(job_id: str) -> None:
    """
    Delete all resources associated with a job including:
    - Customized models
    - Evaluation jobs
    - Datasets
    - KDB-X records

    Args:
        job_id: ID of the job to delete
    """
    cleanup_manager = FlywheelJobManager(db_manager)
    cleanup_manager.delete_job(job_id)


@celery_app.task(name="tasks.cancel_job_resources", pydantic=True)
def cancel_job_resources(job_id: str) -> None:
    """
    Cancel a job by marking it as cancelled in the database.

    Args:
        job_id: ID of the job to cancel
    """
    job_manager = FlywheelJobManager(db_manager)
    job_manager.cancel_job(job_id)


# -------------------------------------------------------------
# Helper utilities
# -------------------------------------------------------------


def _should_skip_stage(previous_result: TaskResult | None, stage_name: str) -> bool:
    """Return True if the previous_result already carries an error.

    When a stage fails we record the error message on the TaskResult instance.
    Any subsequent stage that receives a TaskResult with ``error`` set will
    short-circuit by returning immediately so the overall DAG keeps running
    serially without raising.
    """

    if isinstance(previous_result, TaskResult) and previous_result.error:
        logger.warning(
            "Skipping %s because a previous stage failed: %s",
            stage_name,
            previous_result.error,
        )
        return True
    return False


def _check_cancellation(flywheel_run_id, raise_error=False):
    try:
        check_cancellation(flywheel_run_id)
    except FlywheelCancelledError as e:
        logger.info(f"Flywheel run cancelled: {e}")
        if raise_error:
            raise e
        return True
    return False


# -------------------------------------------------------------
# Shared helpers
# -------------------------------------------------------------


def _extract_previous_result(
    previous_results: list[TaskResult] | TaskResult | dict,
    *,
    validator: Callable[[TaskResult], bool] | None = None,
    error_msg: str = "No valid TaskResult found",
) -> TaskResult:
    """Return a single ``TaskResult`` from *previous_results*.

    Celery tasks can receive either a single ``TaskResult`` instance, a raw
    ``dict`` serialized version of it, or a list containing any mix of those.
    This helper normalises that input so downstream code can safely assume it
    has a *TaskResult* instance to work with.

    If *previous_results* is a list the items are inspected **in reverse
    order** (i.e. most-recent first) until one satisfies the *validator*
    callable.  When *validator* is *None* the first item is returned.

    Args:
        previous_results: The value passed by the upstream Celery task.
        validator: Optional callable that returns *True* for a result that
            should be selected.
        error_msg: Message to include in the raised ``ValueError`` when no
            suitable result can be found.

    Returns:
        TaskResult: The selected result.

    Raises:
        ValueError: If *previous_results* does not contain a suitable
            ``TaskResult``.
    """

    # Fast-path: a single object (TaskResult or dict)
    if not isinstance(previous_results, list):
        if isinstance(previous_results, dict):
            return TaskResult(**previous_results)
        assert isinstance(previous_results, TaskResult)
        return previous_results

    # It is a list - iterate from the end (latest first)
    for result in reversed(previous_results):
        if isinstance(result, dict):
            result = TaskResult(**result)
        if not isinstance(result, TaskResult):
            continue
        if validator is None or validator(result):
            return result

    # Nothing matched - raise so caller can handle
    logger.error(error_msg)
    raise ValueError(error_msg)
