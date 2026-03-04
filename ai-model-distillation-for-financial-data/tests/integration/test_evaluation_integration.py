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

"""
Consolidated Evaluation Integration Tests

Tests evaluation workflows with real database dependencies:
- Base, ICL, and customization evaluation workflows
- cross-evaluation scenarios
- Error handling and cancellation scenarios
- Only mocks external evaluation APIs, keeps internal logic real
"""

import json
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId

from src.api.models import (
    CustomizationResult,
    EvalType,
    TaskResult,
)
from src.config import LLMJudgeConfig
from src.tasks.tasks import run_base_eval, run_customization_eval


def dict_to_task_result(data: dict[str, Any]) -> TaskResult:
    """Convert dictionary back to TaskResult object for testing."""
    return TaskResult(**data)


def ensure_task_result(result) -> TaskResult:
    """Ensure result is a TaskResult, converting from dict if needed."""
    return dict_to_task_result(result) if isinstance(result, dict) else result


@pytest.fixture(autouse=True)
def setup_db_manager(mongo_db):
    """Setup database manager for evaluation tests."""
    import src.tasks.tasks as tasks_module
    from src.api.db import init_db
    from src.api.db_manager import get_db_manager

    init_db()
    tasks_module.db_manager = get_db_manager()

    yield


def load_tool_calling_data():
    """Load first 30 records from aiva-test.jsonl for tool-calling tests."""
    try:
        with open("data/aiva-test.jsonl") as f:
            records = []
            for i, line in enumerate(f):
                if i >= 30:  # Load 30 records to get more unique records after deduplication
                    break
                records.append(json.loads(line.strip()))
            return records
    except FileNotFoundError:
        return []


@pytest.fixture(scope="module")
def load_evaluation_test_data():
    """Load test data once for all evaluation tests."""
    from src.api.db import get_db, init_db
    from tests.integration.conftest import insert_log_records

    init_db()
    db = get_db()

    # Load tool-calling data once
    aiva_records = load_tool_calling_data()
    tc_records = []
    for i, aiva_record in enumerate(aiva_records):
        tc_records.append({
            "client_id": "test-client-tool_calling-evaluation",
            "workload_id": "test-tool_calling-evaluation",
            "request": aiva_record["request"],
            "response": aiva_record["response"],
            "timestamp": f"2023-01-01T{i//60:02d}:{i%60:02d}:00Z",
        })
    insert_log_records(db, tc_records, "test-tool_calling-evaluation", "test-client-tool_calling-evaluation")

    # Load generic data once
    generic_records = []
    for i in range(20):
        generic_records.append({
            "client_id": "test-client-generic-evaluation",
            "workload_id": "test-generic-evaluation",
            "request": {"messages": [{"role": "user", "content": f"Test question {i}?"}]},
            "response": {"choices": [{"message": {"role": "assistant", "content": f"Test response {i}"}}]},
            "timestamp": f"2023-01-01T{i//60:02d}:{i%60:02d}:00Z",
        })
    insert_log_records(db, generic_records, "test-generic-evaluation", "test-client-generic-evaluation")

    yield

    # Cleanup
    try:
        db.flywheel_logs.delete_many({"client_id": "test-client-tool_calling-evaluation", "workload_id": "test-tool_calling-evaluation"})
        db.flywheel_logs.delete_many({"client_id": "test-client-generic-evaluation", "workload_id": "test-generic-evaluation"})
    except Exception as e:
        print(f"Warning: Failed to cleanup test data: {e}")


@pytest.fixture(params=["generic", "tool_calling"])
def workload_type(request):
    """Simple workload type parameterization."""
    return request.param


@pytest.fixture
def evaluation_environment(
    mongo_db, workload_type, validation_test_settings, load_evaluation_test_data
):
    """Setup evaluation environment with parameterized workload types."""
    from src.tasks.tasks import create_datasets, initialize_workflow, wait_for_llm_as_judge

    workload_type = workload_type

    base_client_id = f"test-client-{workload_type}-evaluation"
    base_workload_id = f"test-{workload_type}-evaluation"

    # Setup comprehensive mocking for external services only
    with (
        patch("src.lib.nemo.evaluator.requests") as mock_requests,
        patch("src.lib.nemo.data_uploader.DataUploader.upload_data") as mock_upload,
        patch("src.lib.nemo.data_uploader.DataUploader.get_file_uri") as mock_get_uri,
        patch("time.sleep") as mock_sleep,
        patch("src.lib.nemo.dms_client.DMSClient") as mock_dms,
    ):
        # Setup evaluation service mocking
        job_counter = 0

        def mock_post_request(url, **kwargs):
            nonlocal job_counter
            if "/v1/evaluation/jobs" in str(url):
                job_counter += 1
                job_id = f"eval-job-{job_counter}"
                return MagicMock(status_code=200, json=lambda: {"id": job_id})
            else:
                raise ValueError(f"Unexpected POST request: {url}")

        def mock_get_request(url, **kwargs):
            url_str = str(url)
            if "/v1/evaluation/jobs/" in url_str and "/results" not in url_str:
                return MagicMock(
                    status_code=200,
                    json=lambda: {"status": "completed", "status_details": {"progress": 100}},
                )
            elif "/v1/evaluation/jobs/" in url_str and "/results" in url_str:
                return MagicMock(
                    status_code=200,
                    json=lambda: {
                        "tasks": {
                            "llm-as-judge": {
                                "metrics": {
                                    "llm-judge": {"scores": {"similarity": {"value": 0.85}}}
                                }
                            },
                            "custom-tool-calling": {
                                "metrics": {
                                    "tool-calling-accuracy": {
                                        "scores": {
                                            "function_name_accuracy": {"value": 0.90},
                                            "function_name_and_args_accuracy": {"value": 0.85},
                                        }
                                    },
                                    "correctness": {"scores": {"rating": {"value": 0.88}}},
                                }
                            },
                        }
                    },
                )
            else:
                raise ValueError(f"Unexpected GET request: {url}")

        mock_requests.post.side_effect = mock_post_request
        mock_requests.get.side_effect = mock_get_request
        mock_sleep.return_value = None

        # Setup file upload mocking
        mock_upload.return_value = None
        mock_get_uri.return_value = f"test://dataset-uri-{base_workload_id}"

        # Setup DMS client mocking
        mock_dms_instance = mock_dms.return_value
        mock_dms_instance.wait_for_deployment.return_value = None
        mock_dms_instance.wait_for_model_sync.return_value = None

        # Create flywheel run record
        flywheel_run_id = ObjectId()
        mongo_db.flywheel_runs.insert_one(
            {
                "_id": flywheel_run_id,
                "workload_id": base_workload_id,
                "client_id": base_client_id,
                "started_at": datetime.utcnow(),
                "status": "pending",
                "num_records": 0,
            }
        )

        # Run real initialize_workflow
        with (
            patch("src.tasks.tasks.settings") as mock_settings,
            patch("src.tasks.tasks.LLMAsJudge") as mock_llm_judge,
        ):
            from src.config import CustomizerConfig, NIMConfig

            sample_customizer = CustomizerConfig(
                target="test-model@v1.0.0",
                gpus=1,
                num_nodes=1,
                tensor_parallel_size=1,
                data_parallel_size=1,
                use_sequence_parallel=False,
                micro_batch_size=1,
                training_precision="bf16-mixed",
                max_seq_length=8192,
            )

            mock_settings.nims = [
                NIMConfig(
                    model_name="test-model",
                    context_length=8192,
                    gpus=1,
                    pvc_size="10Gi",
                    tag="latest",
                    customization_enabled=True,
                    customizer_configs=sample_customizer,
                )
            ]

            llm_judge_config = LLMJudgeConfig(
                deployment_type="remote",  # Use remote to skip deployment waiting
                model_name="test-judge",
                context_length=8192,
                url="http://test-judge-url/v1/chat/completions",
                api_key="test-api-key",
            )
            mock_llm_judge.return_value.config = llm_judge_config

            # Use base IDs for data lookup, but unique IDs for the flywheel run
            task_result = initialize_workflow(
                workload_id=base_workload_id,  # Use base ID for data lookup
                flywheel_run_id=str(flywheel_run_id),
                client_id=base_client_id,  # Use base ID for data lookup
            )

        # Ensure task_result is TaskResult object
        task_result = ensure_task_result(task_result)

        # Adjust validation requirements for tool-calling tests
        if workload_type == "tool_calling":
            # Use custom split config with lower requirements for tool-calling data
            from src.config import DataSplitConfig

            custom_split_config = DataSplitConfig(
                eval_size=10,  # Lower eval size to fit within available records
                val_ratio=0.1,
                min_total_records=10,  # Lower minimum for tool-calling due to deduplication
                random_seed=42,  # Set specific seed for consistent behavior
                limit=1000,
                parse_function_arguments=True,
            )
            task_result.data_split_config = custom_split_config
        else:
            # Use custom split config for generic data as well
            from src.config import DataSplitConfig

            custom_split_config = DataSplitConfig(
                eval_size=10,  # Lower eval size to fit within available records
                val_ratio=0.1,
                min_total_records=20,  # Lower minimum
                random_seed=42,  # Set specific seed for consistent behavior
                limit=1000,
                parse_function_arguments=True,
            )
            task_result.data_split_config = custom_split_config

        # Run real create_datasets (RecordExporter will find the indexed data)
        task_result = ensure_task_result(create_datasets(task_result))

        # Run real wait_for_llm_as_judge
        task_result = ensure_task_result(wait_for_llm_as_judge(task_result))

        # Get created NIM info from database
        nim_docs = list(mongo_db.nims.find({"flywheel_run_id": flywheel_run_id}))
        assert len(nim_docs) > 0, "No NIMs were created by initialize_workflow"

        # Add nim config to task result for evaluation
        from src.config import CustomizerConfig, NIMConfig

        sample_customizer = CustomizerConfig(
            target="test-model@v1.0.0",
            gpus=1,
        )

        task_result.nim = NIMConfig(
            model_name="test-model",
            context_length=8192,
            gpus=1,
            pvc_size="10Gi",
            tag="latest",
            customization_enabled=True,
            customizer_configs=sample_customizer,
        )

        # Return comprehensive environment info
        environment_info = {
            "flywheel_run_id": str(flywheel_run_id),
            "nim_id": nim_docs[0]["_id"],
            "model_name": "test-model",
            "customization_enabled": True,
            "task_result": task_result,
            "test_records": [],  # Data is now pre-loaded, so no need to return it here
            "num_records": 0,  # Data is now pre-loaded, so no need to return it here
            "workload_type": workload_type,
            "workload_id": base_workload_id,
            "client_id": base_client_id,
            "mocks": {
                "requests": mock_requests,
                "sleep": mock_sleep,
                "upload": mock_upload,
                "dms": mock_dms,
            },
        }

        yield environment_info

        # Cleanup: MongoDB collections are cleaned up after each test
        mongo_db.evaluations.delete_many({})
        mongo_db.customizations.delete_many({})
        mongo_db.nims.delete_many({})
        mongo_db.flywheel_runs.delete_many({})
        mongo_db.llm_judge_runs.delete_many({})


@pytest.mark.integration
@pytest.mark.evaluation
class TestEvaluationWorkflows:
    """Test evaluation workflows with real database dependencies."""

    def test_base_evaluation_workflow(
        self,
        evaluation_environment,
        mongo_db,
    ):
        """Test base evaluation workflow with real data flow."""
        env_info = evaluation_environment
        task_result = env_info["task_result"]

        # Execute base evaluation
        base_result = ensure_task_result(run_base_eval(task_result))
        assert base_result.error is None
        assert EvalType.BASE in base_result.evaluations
        base_eval = base_result.evaluations[EvalType.BASE]
        assert base_eval.scores is not None
        assert base_eval.percent_done == 100.0

        # Verify database state
        evaluations = list(mongo_db.evaluations.find({"nim_id": env_info["nim_id"]}))
        assert len(evaluations) == 1

    def test_customization_evaluation_workflow(
        self,
        evaluation_environment,
        mongo_db,
    ):
        """Test customization evaluation workflow with database relationships."""
        env_info = evaluation_environment
        task_result = env_info["task_result"]
        customized_model = f"customized-{env_info['model_name']}"

        # Create customization record
        custom_id = ObjectId()
        mongo_db.customizations.insert_one(
            {
                "_id": custom_id,
                "nim_id": env_info["nim_id"],
                "workload_id": env_info["task_result"].workload_id,
                "base_model": env_info["model_name"],
                "customized_model": customized_model,
                "started_at": datetime.utcnow(),
                "finished_at": datetime.utcnow(),
                "progress": 100.0,
            }
        )

        # Add customization to task result
        task_result.customization = CustomizationResult(
            job_id="custom-job-123",
            model_name=customized_model,
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
            percent_done=100.0,
        )

        # Execute customization evaluation
        result = ensure_task_result(run_customization_eval(task_result))
        assert result.error is None
        assert EvalType.CUSTOMIZED in result.evaluations
        custom_eval = result.evaluations[EvalType.CUSTOMIZED]
        assert custom_eval.scores is not None
        assert custom_eval.percent_done == 100.0

    def test_evaluation_cancellation_handling(
        self,
        evaluation_environment,
        mongo_db,
    ):
        """Test evaluation cancellation handling and database state updates."""
        env_info = evaluation_environment
        task_result = env_info["task_result"]

        # Mock flywheel run as cancelled
        mongo_db.flywheel_runs.update_one(
            {"_id": ObjectId(env_info["flywheel_run_id"])}, {"$set": {"status": "cancelled"}}
        )

        # Execute evaluation (should be cancelled)
        result = ensure_task_result(run_base_eval(task_result))
        assert result.error is not None
        assert "Task cancelled for flywheel run" in result.error

        # Verify no evaluation records created due to cancellation
        evaluations = list(mongo_db.evaluations.find({"nim_id": env_info["nim_id"]}))
        assert len(evaluations) == 0

    def test_evaluation_skip_on_previous_error(
        self,
        evaluation_environment,
        mongo_db,
    ):
        """Test evaluation skipping when previous task has error."""
        env_info = evaluation_environment
        task_result = env_info["task_result"]

        # Add previous error to task result
        task_result.error = "Previous task failed"

        # Execute evaluation (should be skipped)
        result = ensure_task_result(run_base_eval(task_result))
        assert result.error == "Previous task failed"

        # Verify no evaluation records created
        evaluations = list(mongo_db.evaluations.find({"nim_id": env_info["nim_id"]}))
        assert len(evaluations) == 0


@pytest.mark.integration
@pytest.mark.evaluation
class TestCrossEvaluationFlows:
    """Test scenarios involving multiple evaluation types with real infrastructure."""

    def test_sequential_base_evaluation_tracking(
        self,
        evaluation_environment,
        mongo_db,
    ):
        """Test base evaluation executed with database state tracking."""
        env_info = evaluation_environment
        task_result = env_info["task_result"]

        # Execute base evaluation
        base_result = ensure_task_result(run_base_eval(task_result))

        assert base_result.error is None
        assert EvalType.BASE in base_result.evaluations

        # Verify database state shows evaluation completed
        all_evals = list(
            mongo_db.evaluations.find({"nim_id": env_info["nim_id"]}).sort("started_at", 1)
        )
        assert len(all_evals) == 1

        # Verify database record consistency
        for eval_doc in all_evals:
            assert eval_doc["nim_id"] == env_info["nim_id"]
            assert eval_doc["progress"] == 100.0
            assert eval_doc["runtime_seconds"] >= 0
            assert eval_doc["job_id"].startswith("eval-job-")

    def test_evaluation_failure_isolation(
        self,
        evaluation_environment,
        mongo_db,
    ):
        """Test that base evaluation succeeds independently."""
        env_info = evaluation_environment
        task_result = env_info["task_result"]

        # Execute base evaluation
        base_result = ensure_task_result(run_base_eval(task_result))

        # Verify base succeeded
        assert base_result.error is None
        assert EvalType.BASE in base_result.evaluations

        # Verify database state
        base_evals = list(
            mongo_db.evaluations.find(
                {"nim_id": env_info["nim_id"], "eval_type": EvalType.BASE}
            )
        )
        assert len(base_evals) == 1
        assert base_evals[0]["progress"] == 100.0

    def test_evaluation_database_transaction_rollback_on_failure(
        self,
        evaluation_environment,
        mongo_db,
    ):
        """Test proper database state rollback when evaluation fails mid-process."""
        env_info = evaluation_environment
        task_result = env_info["task_result"]

        # Mock evaluation service to fail after job creation
        with (
            patch("src.lib.nemo.evaluator.requests") as mock_requests,
            patch("time.sleep") as mock_sleep,
        ):

            def failing_post_mock(url, **kwargs):
                if "/v1/evaluation/jobs" in str(url):
                    return MagicMock(status_code=200, json=lambda: {"id": "fail-job-123"})
                else:
                    raise ValueError(f"Unexpected POST request: {url}")

            def failing_get_mock(url, **kwargs):
                if "/v1/evaluation/jobs/fail-job-123" in str(url):
                    raise Exception("Network timeout during evaluation")
                else:
                    raise ValueError(f"Unexpected GET request: {url}")

            mock_requests.post.side_effect = failing_post_mock
            mock_requests.get.side_effect = failing_get_mock
            mock_sleep.return_value = None

            # Execute evaluation (should fail)
            result = ensure_task_result(run_base_eval(task_result))

            assert result.error is not None
            assert "Network timeout during evaluation" in result.error

            # Verify database state consistency after failure
            eval_docs = list(mongo_db.evaluations.find({"nim_id": env_info["nim_id"]}))
            assert len(eval_docs) == 1

            eval_doc = eval_docs[0]
            assert eval_doc["progress"] == 0.0
            assert eval_doc["finished_at"] is not None
            assert "error" in eval_doc
            assert eval_doc["job_id"] == "fail-job-123"

    def test_evaluation_external_service_failure_isolation(
        self,
        evaluation_environment,
        mongo_db,
    ):
        """Test that external evaluation service failures are isolated and don't affect database consistency."""
        env_info = evaluation_environment
        task_result = env_info["task_result"]

        # Mock external evaluation service to fail completely
        with (
            patch("src.lib.nemo.evaluator.requests") as mock_requests,
            patch("time.sleep") as mock_sleep,
        ):

            def external_failure(url, **kwargs):
                raise Exception("Internal server error")

            mock_requests.post.side_effect = external_failure
            mock_requests.get.side_effect = external_failure
            mock_sleep.return_value = None

            # Execute evaluation (should fail due to external service)
            result = ensure_task_result(run_base_eval(task_result))

            assert result.error is not None
            assert "Internal server error" in result.error

            # Verify database remains consistent despite external failure
            eval_docs = list(mongo_db.evaluations.find({"nim_id": env_info["nim_id"]}))
            assert len(eval_docs) == 1

            eval_doc = eval_docs[0]
            assert eval_doc["progress"] == 0.0
            assert "error" in eval_doc
            assert eval_doc["finished_at"] is not None
