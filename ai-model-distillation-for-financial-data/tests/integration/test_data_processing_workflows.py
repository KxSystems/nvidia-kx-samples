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
Data Processing Workflow Integration Tests

Comprehensive integration tests for data processing workflows covering:
- Data extraction, validation, and dataset creation
- Different workload types and data quality scenarios
- Data splitting configurations and error handling
- End-to-end user workflows without external service dependencies
"""

import uuid
from typing import Any
from unittest.mock import patch

import pytest
from bson import ObjectId

from src.api.models import DatasetType, TaskResult, WorkloadClassification
from src.config import settings
from tests.integration.conftest import insert_log_records
from src.log_utils import setup_logging
from src.tasks.tasks import (
    create_datasets,
    initialize_workflow,
)

logger = setup_logging("data_flywheel.test_data_processing_workflows")


def normalize_task_result(result: TaskResult | dict) -> TaskResult:
    """Convert task result to TaskResult object if it's a dictionary (from Celery serialization)."""
    if isinstance(result, dict):
        return TaskResult(**result)
    return result


@pytest.fixture
def test_workload_id() -> str:
    """Generate a unique workload ID for each test."""
    return f"test-workload-{uuid.uuid4()}"


@pytest.fixture
def client_id() -> str:
    """Generate a unique client ID for each test."""
    return f"test-client-{uuid.uuid4()}"


@pytest.fixture
def flywheel_run_id() -> str:
    """Generate a unique flywheel run ID for each test."""
    return str(ObjectId())


@pytest.fixture(autouse=True)
def setup_db_manager():
    """Setup database manager for tests that need it."""
    import src.tasks.tasks as tasks_module
    from src.api.db import init_db
    from src.api.db_manager import get_db_manager

    init_db()
    tasks_module.db_manager = get_db_manager()
    yield


@pytest.fixture
def index_test_data(db):
    """Fixture to index test data in KDB-X flywheel_logs and clean it up afterward."""
    indexed_doc_ids = []

    def _index_data(data: list[dict], workload_id: str, client_id: str):
        doc_ids = insert_log_records(db, data, workload_id, client_id)
        indexed_doc_ids.extend(doc_ids)
        logger.info(
            f"Indexed {len(data)} records for workload_id={workload_id}, client_id={client_id}"
        )

    yield _index_data

    # Cleanup
    for doc_id in indexed_doc_ids:
        try:
            db.flywheel_logs.delete_one({"doc_id": doc_id})
        except Exception:
            pass


@pytest.mark.integration
@pytest.mark.dataset
class TestDataProcessingWorkflows:
    """Core data processing workflow tests using real database and KDB-X."""

    @pytest.mark.parametrize(
        "workload_type",
        [
            WorkloadClassification.GENERIC,
            WorkloadClassification.TOOL_CALLING,
        ],
    )
    def test_complete_data_processing_workflow(
        self,
        test_workload_id,
        client_id,
        create_flywheel_run_generic,
        mock_external_services_validation,
        validation_test_settings,
        workload_type,
        index_test_data,
    ):
        """Test complete data processing workflow for different workload types."""
        flywheel_run_id, mongo_db = create_flywheel_run_generic

        # Create test data for this test - different data for different workload types
        if workload_type == WorkloadClassification.TOOL_CALLING:
            # For tool calling, create data with tool_calls in the response
            test_data = [
                {
                    "request": {
                        "messages": [{"role": "user", "content": f"Call function to get data {i}"}]
                    },
                    "response": {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": None,
                                    "tool_calls": [
                                        {
                                            "id": f"call_{i}",
                                            "type": "function",
                                            "function": {
                                                "name": "get_data",
                                                "arguments": f'{{"query": "data {i}"}}',
                                            },
                                        }
                                    ],
                                },
                                "finish_reason": "tool_calls",
                            }
                        ]
                    },
                }
                for i in range(15)  # Enough records for testing
            ]
        else:
            # For generic workloads, use simple conversational data
            test_data = [
                {
                    "request": {"messages": [{"role": "user", "content": f"Question {i}"}]},
                    "response": {
                        "choices": [{"message": {"role": "assistant", "content": f"Answer {i}"}}]
                    },
                }
                for i in range(15)  # Enough records for testing
            ]

        # Index test data in KDB-X
        index_test_data(test_data, test_workload_id, client_id)

        with patch("src.tasks.tasks.identify_workload_type") as mock_identify:
            mock_identify.return_value = workload_type

            # Initialize workflow
            init_result = normalize_task_result(
                initialize_workflow(
                    workload_id=test_workload_id,
                    flywheel_run_id=flywheel_run_id,
                    client_id=client_id,
                )
            )

            assert init_result.error is None
            assert init_result.workload_id == test_workload_id

            # Verify flywheel run status was updated to RUNNING
            db_doc = mongo_db.flywheel_runs.find_one({"_id": ObjectId(flywheel_run_id)})
            assert db_doc["status"] == "running"

            # Create datasets
            dataset_result = normalize_task_result(create_datasets(init_result))

            assert dataset_result.error is None
            assert dataset_result.workload_type == workload_type
            assert len(dataset_result.datasets) == 3
            assert all(
                dt in dataset_result.datasets
                for dt in [DatasetType.BASE, DatasetType.ICL, DatasetType.TRAIN]
            )

            # Verify database state
            db_doc = mongo_db.flywheel_runs.find_one({"_id": ObjectId(flywheel_run_id)})
            assert db_doc["num_records"] == settings.data_split_config.limit
            assert len(db_doc["datasets"]) == 3
            assert db_doc["finished_at"] is None

            for dataset in db_doc["datasets"]:
                assert all(field in dataset for field in ["name", "num_records", "nmp_uri"])
                assert test_workload_id in dataset["name"]

    @pytest.mark.parametrize(
        "eval_size,val_ratio,expected_splits",
        [
            (2, 0.25, (2, 6, 2)),  # 10 -> 2 eval, 8 remaining -> 6 train, 2 val
            (3, 0.2, (3, 5, 2)),  # 10 -> 3 eval, 7 remaining -> 5 train, 2 val
            (1, 0.33, (1, 6, 3)),  # 10 -> 1 eval, 9 remaining -> 6 train, 3 val
        ],
    )
    def test_data_splitting_configurations(
        self,
        test_workload_id,
        client_id,
        create_flywheel_run_generic,
        mock_external_services_validation,
        validation_test_settings,
        monkeypatch,
        eval_size,
        val_ratio,
        expected_splits,
        index_test_data,
    ):
        """Test various data splitting configurations."""
        flywheel_run_id, mongo_db = create_flywheel_run_generic
        expected_eval, expected_train, _ = expected_splits

        # Configure split settings
        monkeypatch.setattr(settings.data_split_config, "eval_size", eval_size)
        monkeypatch.setattr(settings.data_split_config, "val_ratio", val_ratio)

        # Create test data for this test
        test_data = [
            {
                "request": {"messages": [{"role": "user", "content": f"Question {i}"}]},
                "response": {
                    "choices": [{"message": {"role": "assistant", "content": f"Answer {i}"}}]
                },
            }
            for i in range(15)  # Enough records for testing
        ]

        # Index test data in KDB-X
        index_test_data(test_data, test_workload_id, client_id)

        with patch("src.tasks.tasks.identify_workload_type") as mock_identify:
            mock_identify.return_value = WorkloadClassification.GENERIC

            init_result = TaskResult(
                workload_id=test_workload_id,
                flywheel_run_id=flywheel_run_id,
                client_id=client_id,
            )

            dataset_result = normalize_task_result(create_datasets(init_result))
            assert dataset_result.error is None

            # Verify split counts in database
            db_doc = mongo_db.flywheel_runs.find_one({"_id": ObjectId(flywheel_run_id)})

            datasets = {d["name"].split("-")[1]: d for d in db_doc["datasets"]}
            assert set(datasets.keys()) == {"eval", "train", "icl"}

            assert datasets["eval"]["num_records"] == expected_eval
            assert datasets["train"]["num_records"] == expected_train
            # ICL dataset has same count as eval
            assert datasets["icl"]["num_records"] == expected_eval

    @pytest.mark.parametrize(
        "test_scenario,expected_outcome",
        [
            ("no_records", "should_fail"),
            ("insufficient_records", "should_fail"),
            ("mixed_valid_invalid", "should_succeed"),
            ("all_duplicates", "should_fail"),
        ],
    )
    def test_data_validation_scenarios(
        self,
        test_workload_id,
        client_id,
        create_flywheel_run_generic,
        mock_external_services_validation,
        validation_test_settings,
        monkeypatch,
        test_scenario,
        expected_outcome,
        index_test_data,
    ):
        """Test various data validation scenarios using controlled test data."""
        flywheel_run_id, mongo_db = create_flywheel_run_generic

        # Adjust settings for specific test scenarios
        if test_scenario == "insufficient_records":
            # Set a higher minimum to ensure 3 records is insufficient
            monkeypatch.setattr(settings.data_split_config, "min_total_records", 5, raising=False)
        elif test_scenario == "all_duplicates":
            # Set minimum to 3 so that 1 record after deduplication is insufficient
            monkeypatch.setattr(settings.data_split_config, "min_total_records", 3, raising=False)

        # Create test records factory
        def create_test_records(
            record_type: str, count: int = 10, **kwargs
        ) -> list[dict[str, Any]]:
            base_record = {}

            if record_type == "generic":
                return [
                    {
                        **base_record,
                        "request": {"messages": [{"role": "user", "content": f"Question {i}"}]},
                        "response": {
                            "choices": [
                                {"message": {"role": "assistant", "content": f"Answer {i}"}}
                            ]
                        },
                    }
                    for i in range(count)
                ]
            elif record_type == "invalid":
                return [
                    {**base_record, "request": {}},  # Missing messages
                    {**base_record, "response": {"choices": []}},  # Empty choices
                    {**base_record, "request": {"messages": "not a list"}},  # Invalid format
                ][:count]
            elif record_type == "duplicate":
                return [
                    {
                        **base_record,
                        "request": {"messages": [{"role": "user", "content": "Same question"}]},
                        "response": {
                            "choices": [
                                {"message": {"role": "assistant", "content": f"Response {i}"}}
                            ]
                        },
                    }
                    for i in range(count)
                ]
            return []

        # Configure test data based on scenario
        if test_scenario == "no_records":
            test_data = []
        elif test_scenario == "insufficient_records":
            test_data = create_test_records("generic", count=3)  # Below min_total_records=5
        elif test_scenario == "mixed_valid_invalid":
            test_data = create_test_records("generic", count=8) + create_test_records(
                "invalid", count=3
            )
        elif test_scenario == "all_duplicates":
            test_data = create_test_records("duplicate", count=15)

        # Index test data in KDB-X
        index_test_data(test_data, test_workload_id, client_id)

        with patch("src.tasks.tasks.identify_workload_type") as mock_identify:
            mock_identify.return_value = WorkloadClassification.GENERIC

            init_result = TaskResult(
                workload_id=test_workload_id,
                flywheel_run_id=flywheel_run_id,
                client_id=client_id,
            )

            if expected_outcome == "should_fail":
                with pytest.raises((ValueError, Exception)) as exc_info:
                    create_datasets(init_result)
                error_message = str(exc_info.value).lower()
                # Validate the error message contains expected phrases
                assert any(
                    phrase in error_message
                    for phrase in [
                        "not enough records found",
                        "insufficient valid records",
                        "minimum",
                        "required",
                    ]
                )

                # Verify flywheel run status was set to error
                db_doc = mongo_db.flywheel_runs.find_one({"_id": ObjectId(flywheel_run_id)})
                assert db_doc["status"] == "failed"
                assert db_doc["error"] is not None
                assert db_doc["finished_at"] is not None
            else:
                dataset_result = normalize_task_result(create_datasets(init_result))
                assert dataset_result.error is None
                assert len(dataset_result.datasets) == 3

    @pytest.mark.parametrize(
        "tool_records,simple_records,workload_type,should_succeed",
        [
            (
                10,
                0,
                WorkloadClassification.TOOL_CALLING,
                True,
            ),  # All tool records for tool workload
            (
                0,
                10,
                WorkloadClassification.TOOL_CALLING,
                False,
            ),  # No tool records for tool workload
            (5, 5, WorkloadClassification.TOOL_CALLING, True),  # Mixed, enough tool records
            (10, 0, WorkloadClassification.GENERIC, True),  # Tool records work for generic
            (0, 10, WorkloadClassification.GENERIC, True),  # Simple records work for generic
        ],
    )
    def test_workload_type_quality_filtering(
        self,
        test_workload_id,
        client_id,
        create_flywheel_run_generic,
        mock_external_services_validation,
        validation_test_settings,
        tool_records,
        simple_records,
        workload_type,
        should_succeed,
        index_test_data,
    ):
        """Test quality filtering behavior for different workload types."""
        flywheel_run_id, mongo_db = create_flywheel_run_generic

        # Create test records factory
        def create_test_records(record_type: str, count: int = 10) -> list[dict[str, Any]]:
            if record_type == "tool_calling":
                return [
                    {
                        "request": {"messages": [{"role": "user", "content": f"Tool request {i}"}]},
                        "response": {
                            "choices": [
                                {
                                    "message": {
                                        "role": "assistant",
                                        "content": f"Response {i}",
                                        "tool_calls": [
                                            {
                                                "type": "function",
                                                "function": {
                                                    "name": "test_function",
                                                    "arguments": '{"param": "value"}',
                                                },
                                            }
                                        ],
                                    }
                                }
                            ]
                        },
                    }
                    for i in range(count)
                ]
            else:  # generic
                return [
                    {
                        "request": {"messages": [{"role": "user", "content": f"Question {i}"}]},
                        "response": {
                            "choices": [
                                {"message": {"role": "assistant", "content": f"Answer {i}"}}
                            ]
                        },
                    }
                    for i in range(count)
                ]

        # Create mixed test data
        test_data = create_test_records("tool_calling", count=tool_records) + create_test_records(
            "generic", count=simple_records
        )

        # Index test data in KDB-X
        index_test_data(test_data, test_workload_id, client_id)

        with patch("src.tasks.tasks.identify_workload_type") as mock_identify:
            mock_identify.return_value = workload_type

            init_result = TaskResult(
                workload_id=test_workload_id,
                flywheel_run_id=flywheel_run_id,
                client_id=client_id,
            )

            if should_succeed:
                dataset_result = normalize_task_result(create_datasets(init_result))
                assert dataset_result.error is None
                assert dataset_result.workload_type == workload_type
            else:
                with pytest.raises(ValueError) as exc_info:
                    create_datasets(init_result)
                assert "insufficient" in str(exc_info.value).lower()

                # Verify flywheel run status was set to error
                db_doc = mongo_db.flywheel_runs.find_one({"_id": ObjectId(flywheel_run_id)})
                assert db_doc["status"] == "failed"
                assert db_doc["error"] is not None
                assert db_doc["finished_at"] is not None

    def test_database_consistency_across_workflow_stages(
        self,
        test_workload_id,
        client_id,
        create_flywheel_run_generic,
        mock_external_services_validation,
        validation_test_settings,
        index_test_data,
    ):
        """Test data consistency is maintained across all workflow stages."""
        flywheel_run_id, mongo_db = create_flywheel_run_generic

        # Create test data for this test
        test_data = [
            {
                "request": {"messages": [{"role": "user", "content": f"Question {i}"}]},
                "response": {
                    "choices": [{"message": {"role": "assistant", "content": f"Answer {i}"}}]
                },
            }
            for i in range(15)  # Enough records for testing
        ]

        # Index test data in KDB-X
        index_test_data(test_data, test_workload_id, client_id)

        with patch("src.tasks.tasks.identify_workload_type") as mock_identify:
            mock_identify.return_value = WorkloadClassification.GENERIC

            # Execute workflow stages
            init_result = normalize_task_result(
                initialize_workflow(
                    workload_id=test_workload_id,
                    flywheel_run_id=flywheel_run_id,
                    client_id=client_id,
                )
            )

            # Verify initial status was set correctly
            db_doc = mongo_db.flywheel_runs.find_one({"_id": ObjectId(flywheel_run_id)})
            assert db_doc["status"] == "running"

            dataset_result = normalize_task_result(create_datasets(init_result))

            # Verify data consistency
            for result in [init_result, dataset_result]:
                assert result.workload_id == test_workload_id
                assert result.flywheel_run_id == flywheel_run_id
                assert result.client_id == client_id

            # Verify dataset metadata consistency
            for dataset_type, dataset_name in dataset_result.datasets.items():
                assert test_workload_id in dataset_name
                # Check for the actual naming pattern used: flywheel-{type}-workload-...
                # BASE -> eval, ICL -> icl, TRAIN -> train
                expected_patterns = {
                    DatasetType.BASE: "eval",
                    DatasetType.ICL: "icl",
                    DatasetType.TRAIN: "train",
                }
                expected_pattern = expected_patterns.get(dataset_type)
                if expected_pattern:
                    assert (
                        expected_pattern in dataset_name
                    ), f"Expected '{expected_pattern}' in dataset name '{dataset_name}'"

            # Verify database state consistency
            db_doc = mongo_db.flywheel_runs.find_one({"_id": ObjectId(flywheel_run_id)})
            assert db_doc["workload_id"] == test_workload_id
            assert db_doc["client_id"] == client_id
            assert db_doc["finished_at"] is None

            for dataset in db_doc["datasets"]:
                assert test_workload_id in dataset["name"]
                assert dataset["num_records"] > 0
                assert dataset["nmp_uri"] == "test_uri"

    def test_dataset_content_validation(
        self,
        test_workload_id,
        client_id,
        create_flywheel_run_generic,
        mock_external_services_validation,
        validation_test_settings,
        index_test_data,
    ):
        """Test that dataset content is properly formatted and uploaded."""
        flywheel_run_id, mongo_db = create_flywheel_run_generic

        # Create test data for this test
        test_data = [
            {
                "request": {"messages": [{"role": "user", "content": f"Question {i}"}]},
                "response": {
                    "choices": [{"message": {"role": "assistant", "content": f"Answer {i}"}}]
                },
            }
            for i in range(15)  # Enough records for testing
        ]

        # Index test data in KDB-X
        index_test_data(test_data, test_workload_id, client_id)

        with patch("src.tasks.tasks.identify_workload_type") as mock_identify:
            mock_identify.return_value = WorkloadClassification.GENERIC

            init_result = TaskResult(
                workload_id=test_workload_id,
                flywheel_run_id=flywheel_run_id,
                client_id=client_id,
            )

            dataset_result = normalize_task_result(create_datasets(init_result))
            assert dataset_result.error is None

            # Verify external service calls
            mock_upload = mock_external_services_validation["upload_data"]
            mock_get_uri = mock_external_services_validation["get_file_uri"]

            # Should upload 4 files: eval, icl, train, val data
            assert mock_upload.call_count == 4
            assert mock_get_uri.call_count == 3  # One URI per dataset type

            # Verify uploaded data is not None
            for call in mock_upload.call_args_list:
                uploaded_data = call[0][0]
                assert uploaded_data is not None

    @pytest.mark.parametrize(
        "scenario,tool_distributions,expected_workload_type,eval_size,limit",
        [
            # Multiple tools scenario
            (
                "multiple_tools",
                [("get_weather", 30), ("schedule_meeting", 20), (None, 10)],
                WorkloadClassification.TOOL_CALLING,
                3,
                20,
            ),
            # Single class fallback scenario
            ("single_class", [("single_tool", 50)], WorkloadClassification.GENERIC, 3, 20),
            # Mixed tool/no-tool scenario
            (
                "mixed_tool_no_tool",
                [("api_tool", 40), (None, 20)],
                WorkloadClassification.GENERIC,
                4,
                20,
            ),
            # Imbalanced classes scenario
            (
                "imbalanced_classes",
                [("major_tool", 90), ("minor_tool", 10)],
                WorkloadClassification.GENERIC,
                4,
                20,
            ),
        ],
    )
    def test_stratified_splitting_scenarios(
        self,
        test_workload_id,
        client_id,
        create_flywheel_run_generic,
        mock_external_services_validation,
        validation_test_settings,
        monkeypatch,
        index_test_data,
        scenario,
        tool_distributions,
        expected_workload_type,
        eval_size,
        limit,
    ):
        """Test stratified splitting with various data distributions and scenarios."""
        flywheel_run_id, mongo_db = create_flywheel_run_generic

        # Configure settings based on scenario
        monkeypatch.setattr(settings.data_split_config, "eval_size", eval_size, raising=False)
        monkeypatch.setattr(
            settings.data_split_config,
            "val_ratio",
            0.3 if scenario == "multiple_tools" else 0.25,
            raising=False,
        )
        monkeypatch.setattr(settings.data_split_config, "random_seed", 42, raising=False)
        monkeypatch.setattr(settings.data_split_config, "limit", limit, raising=False)

        # Create test data based on tool distributions
        test_data = []
        record_index = 0

        for tool_name, count in tool_distributions:
            for _ in range(count):
                if tool_name is None:
                    # Records without tools
                    test_data.append(
                        {
                            "request": {
                                "messages": [
                                    {"role": "user", "content": f"General question {record_index}"}
                                ]
                            },
                            "response": {
                                "choices": [
                                    {
                                        "message": {
                                            "role": "assistant",
                                            "content": f"General response {record_index}",
                                            "tool_calls": None,
                                        }
                                    }
                                ]
                            },
                        }
                    )
                else:
                    # Records with tools
                    test_data.append(
                        {
                            "request": {
                                "messages": [
                                    {
                                        "role": "user",
                                        "content": f"{tool_name} request {record_index}",
                                    }
                                ],
                                "tools": [{"type": "function", "function": {"name": tool_name}}],
                            },
                            "response": {
                                "choices": [
                                    {
                                        "message": {
                                            "role": "assistant",
                                            "content": f"{tool_name} response {record_index}",
                                            "tool_calls": [
                                                {
                                                    "type": "function",
                                                    "function": {
                                                        "name": tool_name,
                                                        "arguments": "{}",
                                                    },
                                                }
                                            ],
                                        }
                                    }
                                ]
                            },
                        }
                    )
                record_index += 1

        # Index test data in KDB-X
        index_test_data(test_data, test_workload_id, client_id)

        with patch("src.tasks.tasks.identify_workload_type") as mock_identify:
            mock_identify.return_value = expected_workload_type

            init_result = TaskResult(
                workload_id=test_workload_id,
                flywheel_run_id=flywheel_run_id,
                client_id=client_id,
            )

            dataset_result = normalize_task_result(create_datasets(init_result))
            assert dataset_result.error is None

            # Verify datasets were created successfully
            db_doc = mongo_db.flywheel_runs.find_one({"_id": ObjectId(flywheel_run_id)})

            datasets = {d["name"].split("-")[1]: d for d in db_doc["datasets"]}
            assert set(datasets.keys()) == {"eval", "train", "icl"}

            # Verify split sizes
            assert datasets["eval"]["num_records"] == eval_size
            assert datasets["train"]["num_records"] > 0, "Train set should not be empty"
            assert datasets["icl"]["num_records"] == eval_size, "ICL set should match eval set size"


