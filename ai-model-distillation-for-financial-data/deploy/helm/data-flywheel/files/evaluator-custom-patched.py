import asyncio
import json
import logging
import os
import traceback
from datetime import datetime, timezone
from typing import List, Optional

from evaluator.jobs.constants import EVALUATION_RESULTS_FILE_NAME
from evaluator.jobs.progress_tracking import ProgressTracking
from evaluator.services import inference
from evaluator.services.inference import verify_model_reachable
from evaluator.services.metrics.ragas_metrics import RAGAS_METRIC_CLASSES
from evaluator.services.nmp_datasets import utils as datasets
from evaluator.services.runners.evalfactory.handlers.secrets import (
    SECRET_KEY_LLM_AS_A_JUDGE_API_KEY,
    SECRET_KEY_TARGET_MODEL_API_TOKEN,
    SECRET_REFS_TO_ENV_VAR_NAMES,
)
from evaluator.services.security.security_service import SecurityService
from evaluator.tasks import NewTask, Task
from jinja2.exceptions import UndefinedError as jinjaUndefinedError
from nmp_common.datamodel.datastore.datasets import Dataset
from nmp_common.datamodel.datastore.models.entities import Model
from nmp_common.datamodel.evaluation.entities import (
    EvaluationConfig,
    EvaluationJob,
    EvaluationResult,
    EvaluationTarget,
)
from nmp_common.datamodel.evaluation.enums import TargetType, TaskConfigType, TaskStatus
from nmp_common.datamodel.evaluation.values import EvaluationParams, EvaluationStatusDetails
from nmp_common.datamodel.types import URN
from nmp_common.jobs.constants import NEMO_JOB_ID_ENVVAR
from pydantic import BaseModel

log = logging.getLogger(__name__)

CUSTOM_TARGET_TYPES = [TargetType.MODEL, TargetType.ROWS, TargetType.DATASET]
CUSTOM_TASK_TYPES = [
    TaskConfigType.COMPLETION,
    TaskConfigType.CHAT_COMPLETION,
    TaskConfigType.DATA,
    TaskConfigType.PROMPT_OPTIMIZATION,
]


def custom_job_entrypoint() -> List[str]:
    """
    Entrypoint for custom eval job
    """
    return ["/bin/sh"]  # Use sh entrypoint for env expansion


def custom_job_entrypoint_args(
    results_dir: str,
    config_env: str,
    progress_tracking_url: Optional[str] = None,
    progress_tracking_interval: Optional[int] = None,
) -> List[str]:
    """
    Command args to run custom job
    """
    command = f"python -m evaluator.jobs.custom -d {results_dir} --config-env {config_env}"
    if progress_tracking_url:
        command += f" --progress-tracking-url {progress_tracking_url}"
    if progress_tracking_interval:
        command += f" --progress-tracking-interval {progress_tracking_interval}"
    return ["-c", command]


async def validate_custom_job(job: EvaluationJob, live: bool = False):
    assert isinstance(job.target, EvaluationTarget)
    assert isinstance(job.config, EvaluationConfig)
    if job.target.type not in CUSTOM_TARGET_TYPES:
        raise ValueError(f"Unsupported target type for custom evaluation: {job.target.type}")

    if not job.config.tasks:
        raise ValueError("A task is required for custom evaluation")

    has_prompt_optimization_task = False

    for task_name, task in job.config.tasks.items():
        if task.type not in CUSTOM_TASK_TYPES:
            raise ValueError(f"Unsupported task type for custom evaluation {CUSTOM_TASK_TYPES}: {task.type}")
        if task.type == TaskConfigType.PROMPT_OPTIMIZATION:
            has_prompt_optimization_task = True
        assert isinstance(job.target, EvaluationTarget), "Target must be an EvaluationTarget"
        # NewTask initialization performs validation checks and raises exception in case of invalid payload.
        NewTask(task, name=task_name, target=job.target)
        # Access task.metrics directly to get MetricConfig objects (not instantiated Metric objects)
        for _, metric_config in (task.metrics or {}).items():
            if metric_config.type in RAGAS_METRIC_CLASSES and not live:
                raise ValueError("RAGAS metrics are only supported in live evaluation endpoint")
            if metric_config.type == "llm-judge":
                assert isinstance(metric_config.params, dict)
                judge_model_config = metric_config.params.get("model", {})
                await verify_model_reachable(judge_model_config)

    if has_prompt_optimization_task and len(job.config.tasks) > 1:
        # Prompt optimization has to run as a subprocess
        raise ValueError(f"{TaskConfigType.PROMPT_OPTIMIZATION.value} cannot run with other tasks.")


async def validate_custom_config_models(config: EvaluationConfig):
    """
    Validate the config models.
    """
    if config.tasks is None:
        return True

    for task_config in config.tasks.values():
        for metric_config in (task_config.metrics or {}).values():
            if metric_config.type == "llm-judge":
                assert isinstance(metric_config.params, dict)
                judge_model_config = metric_config.params.get("model", {})
                await verify_model_reachable(judge_model_config)
    return True


def hydrate_custom_job_secrets(job: EvaluationJob):
    """
    Hydrates the job with secrets from corresponding environment variables.
    """
    secret_env_name = SECRET_REFS_TO_ENV_VAR_NAMES[SECRET_KEY_TARGET_MODEL_API_TOKEN]
    target_api_key = os.getenv(secret_env_name)
    if target_api_key:
        logging.info(f"Loaded job secret from {secret_env_name} environment variable.")
        assert isinstance(job.target, EvaluationTarget)
        assert isinstance(job.target.model, Model)
        assert job.target.model.api_endpoint is not None
        job.target.model.api_endpoint.api_key = target_api_key

    secret_env_name = SECRET_REFS_TO_ENV_VAR_NAMES[SECRET_KEY_LLM_AS_A_JUDGE_API_KEY]
    judge_api_key = os.getenv(secret_env_name)
    if judge_api_key:
        logging.info(f"Loaded job secret from {secret_env_name} environment variable.")
        assert isinstance(job.config, EvaluationConfig)
        for task in (job.config.tasks or {}).values():
            for metric in (task.metrics or {}).values():
                if metric.type == "llm-judge":
                    (metric.params or {})["model"]["api_endpoint"]["api_key"] = judge_api_key


async def run_custom_job(job: EvaluationJob, results_dir: str, progress_tracking: Optional[ProgressTracking] = None):
    """
    Entrypoint to run custom job with Jobs MS.
    """
    log.info("Running custom evaluation")
    assert isinstance(job.config, EvaluationConfig)
    assert isinstance(job.target, EvaluationTarget)
    assert isinstance(job.status_details, EvaluationStatusDetails)

    items = []
    if job.target.type == TargetType.MODEL:
        # Fetch information about the target model if needed
        assert isinstance(job.target.model, (Model, URN, str))
        job.target.model = await inference.fetch_model_info(job.target.model)
    elif job.target.type == TargetType.ROWS:
        # If we have a row target, we just use the rows directly
        items = job.target.rows
    elif job.target.type == TargetType.DATASET:
        # If we have a dataset target, we load the dataset
        assert isinstance(job.target.dataset, (Dataset, URN, str))
        items = await datasets.load_dataset(job.target.dataset, datasets.LoadingMode.DATASETS)
    else:
        raise ValueError(f"Unsupported target type for custom evaluation: {job.target.type}")

    job_config_params = job.config.params or EvaluationParams()
    job_config_params.max_retries = 1 if job_config_params.max_retries is None else job_config_params.max_retries

    evaluation_result = EvaluationResult(job=job.id)

    job.status_details.progress = 0.0
    job.status_details.samples_processed = 0

    tasks = {}
    task_items = {}
    total_items = 0  # get the total number of items for each task to calculate progress
    assert isinstance(job.target, EvaluationTarget), "Target must be an EvaluationTarget"
    assert job.config.tasks is not None
    for task_name, config_task in job.config.tasks.items():
        task: Task = NewTask(
            config_task,
            name=task_name,
            target=job.target,
            params=job_config_params,
            progress_tracking=progress_tracking,
        )
        if not items:
            items = await task.load_task_dataset()
        if job_config_params.limit_samples:
            items = items[: job_config_params.limit_samples]
        total_items += len(items)
        tasks[task_name] = task
        task_items[task_name] = items

    log.info(f"Processing {total_items} samples across {len(tasks)} task(s)")

    if progress_tracking:
        # Update progress tracking total number of samples
        progress_tracking.total_samples = total_items
        log.info(f"Progress tracking configured with interval {progress_tracking.interval}")

        # Initialize the task status for each task
        for task_name in job.config.tasks:
            progress_tracking.update_task_status(task_name, TaskStatus.PENDING.value)

    # We index the outputs per task
    task_logs = {}
    task_failures = []
    for task_name, task in tasks.items():
        try:
            items = task_items[task_name]

            log.info(f"Running task {task_name} with {len(items)} samples")
            if progress_tracking:
                progress_tracking.update_task_status(task_name, TaskStatus.RUNNING.value)

            # Run the task
            task_result, task_logs[task_name] = await task.run(job, items)

            # Update the task result
            if evaluation_result.tasks is None:
                evaluation_result.tasks = {}
            evaluation_result.tasks[task_name] = task_result
            evaluation_result.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

            # Update the task status to "completed".
            if progress_tracking:
                progress_tracking.update_task_status(task_name, TaskStatus.COMPLETED.value)

        except Exception as e:
            if isinstance(e, jinjaUndefinedError):
                curr_error = f"Task {task_name} has failed due to templating error: {str(e)}"
            else:
                curr_error = f"Task {task_name} has failed with error: {str(e) or e.__class__.__name__} // Traceback: {traceback.format_exc()}."
            log.exception(curr_error)
            task_failures.append(curr_error)

            if progress_tracking:
                progress_tracking.update_task_status(task_name, TaskStatus.FAILED.value)

    job_artifacts_dump(job, evaluation_result, task_logs, results_dir)

    if task_failures:
        raise RuntimeError("\n".join(task_failures))

    # Update progress to 100% after all tasks have completed successfully
    if progress_tracking:
        progress_tracking.update_progress(progress=100)
        progress_tracking.stop()


def job_artifacts_dump(job: EvaluationJob, evaluation_result: EvaluationResult, task_logs: dict, results_dir: str):
    """
    Write job artifacts to file

    * job.json: sanitized job entity
    * results.json: raw evaluation for each row
    * evaluation_results.json: aggregated evaluation for the job
    """
    os.makedirs(results_dir, exist_ok=True)

    sanitized_job = SecurityService().copy_sanitized(job)
    with open(f"{results_dir}/job.json", "w") as f:
        f.write(sanitized_job.model_dump_json(indent=2, exclude_none=True))
    if task_logs:
        # Writing empty task logs will make the upload to NDS fail
        with open(f"{results_dir}/results.json", "w") as f:
            f.write(json.dumps(task_logs, indent=2, default=_custom_json_serializer))
    with open(os.path.join(results_dir, EVALUATION_RESULTS_FILE_NAME), "w") as f:
        f.write(evaluation_result.model_dump_json(indent=2, exclude_none=True))


def _custom_json_serializer(obj):
    """Custom JSON serializer for handling Pydantic models and datetime."""
    import datetime as _dt
    if isinstance(obj, BaseModel):  # Check if the object is a Pydantic model
        return obj.model_dump(mode="json")  # Use model_dump() for serialization
    if hasattr(obj, "__name__") and hasattr(obj, "model_json_schema"):  # Check if it's a Pydantic model class
        return {"model_name": obj.__name__, "model_type": "pydantic_model_class"}
    if isinstance(obj, (_dt.datetime, _dt.date, _dt.time)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Watch benchmark container")
    parser.add_argument(
        "-d",
        "--directory",
        type=str,
        required=True,
        help="Path to local dir where eval results will be written.",
    )
    parser.add_argument(
        "--config-env",
        type=str,
        required=True,
        help="Environment variable to load from for the job configuration.",
    )
    parser.add_argument(
        "--progress-tracking-url",
        type=str,
        default=os.getenv("EVALUATIONS_CALLBACK_URL"),
        help="Optional callback URL to update progress tracking details.",
    )
    parser.add_argument(
        "--progress-tracking-interval",
        type=str,
        default=50,
        help="Interval to update progress tracking details.",
    )
    parser.add_argument(
        "--progress-tracking-interval-seconds",
        type=str,
        default=60,
        help="Time interval (seconds) to update progress tracking details.",
    )
    args = parser.parse_args()

    job_str = os.getenv(args.config_env)
    if not job_str:
        raise ValueError(f"{args.config_env} is required to configure Evaluation job as serialized json.")
    job = EvaluationJob.model_validate_json(job_str)
    job.id = os.getenv(NEMO_JOB_ID_ENVVAR, job.id)

    progress_tracking = None
    if args.progress_tracking_url:
        progress_tracking = ProgressTracking(
            args.progress_tracking_url, args.progress_tracking_interval, args.progress_tracking_interval_seconds
        )

    hydrate_custom_job_secrets(job)

    await run_custom_job(job, args.directory, progress_tracking)


if __name__ == "__main__":
    asyncio.run(main())

