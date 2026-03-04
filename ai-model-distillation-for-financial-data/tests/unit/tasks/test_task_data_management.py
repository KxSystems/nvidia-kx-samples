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

"""Tests for data management tasks."""

from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId

from src.api.models import TaskResult, WorkloadClassification
from src.config import DataSplitConfig
from src.lib.flywheel.cancellation import FlywheelCancelledError
from src.tasks.tasks import create_datasets
from tests.unit.tasks.conftest import convert_result_to_task_result


@pytest.fixture
def mock_es_client():
    """Fixture to mock KDB-X data access client.

    Uses the pykx bridge from the root conftest to translate ES-style
    ``mock_es_client.search.return_value`` into ``pykx_connection`` behaviour.
    """
    from tests.unit.conftest import _make_pykx_bridge

    mock_instance = MagicMock()

    mock_instance.search.return_value = {"_scroll_id": "scroll123", "hits": {"hits": []}}
    mock_instance.ping.return_value = True

    pykx_bridge = _make_pykx_bridge(mock_instance)

    with (
        patch("src.lib.integration.es_client.get_es_client", return_value=mock_instance),
        patch("src.lib.integration.es_client.index_embeddings_to_es", return_value="test_index"),
        patch("src.lib.integration.es_client.search_similar_embeddings", return_value=[]),
        patch("src.lib.integration.es_client.delete_embeddings_index", return_value=None),
        patch("src.lib.integration.record_exporter.pykx_connection", pykx_bridge),
    ):
        yield mock_instance


@pytest.fixture
def mock_data_uploader():
    """Fixture to mock DataUploader."""
    with patch("src.lib.integration.dataset_creator.DataUploader") as mock:
        mock_instance = MagicMock()
        # Ensure that `get_file_uri` (used when recording dataset metadata) returns a
        # plain string.  A raw ``MagicMock`` instance cannot be encoded by BSON and
        # causes an ``InvalidDocument`` error when the code under test attempts to
        # update KDB-X.
        mock_instance.get_file_uri.return_value = "nmp://test-namespace/datasets/dummy.jsonl"
        mock.return_value = mock_instance
        yield mock_instance


class TestDatasetCreationBasic:
    """Tests for basic dataset creation functionality."""

    def test_create_datasets(
        self,
        mock_es_client,
        mock_data_uploader,
        mock_task_db,
        mock_settings,
        mock_dms_client,
    ):
        """Test creating datasets from KDB-X data."""
        workload_id = "test-workload"
        flywheel_run_id = str(ObjectId())
        client_id = "test-client"

        previous_result = TaskResult(
            workload_id=workload_id,
            flywheel_run_id=flywheel_run_id,
            client_id=client_id,
        )

        # Adjust settings to match the sample data size
        mock_settings.data_split_config.limit = 5

        mock_es_client.search.return_value = {
            "_scroll_id": "scroll123",
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "request": {
                                "messages": [
                                    {"role": "user", "content": f"Question {i}"},
                                    {"role": "assistant", "content": f"Answer {i}"},
                                ]
                            },
                            "response": {"choices": [{"message": {"content": f"Response {i}"}}]},
                        }
                    }
                    for i in range(5)
                ]
                + [
                    {
                        "_source": {
                            "request": {
                                "messages": [
                                    {"role": "user", "content": "What are transformers?"},
                                    {"role": "assistant", "content": "Transformers are..."},
                                ]
                            },
                            "response": {
                                "choices": [{"message": {"content": "Transformer architecture..."}}]
                            },
                        }
                    },
                ]
            },
        }

        result = convert_result_to_task_result(create_datasets(previous_result))

        assert isinstance(result, TaskResult)
        assert result.workload_id == workload_id
        assert result.client_id == client_id
        assert result.flywheel_run_id == flywheel_run_id
        assert result.datasets is not None
        assert len(result.datasets) > 0

        assert mock_data_uploader.upload_data.call_count >= 1

class TestDatasetCreationConfiguration:
    """Tests for dataset creation with custom configurations."""

    def test_create_datasets_with_custom_data_split_config(
        self,
        mock_es_client,
        mock_data_uploader,
        mock_task_db,
        mock_settings,
        mock_dms_client,
    ):
        """Test create_datasets with custom data split config."""

        workload_id = "test-workload"
        flywheel_run_id = str(ObjectId())
        client_id = "test-client"

        # Create a real data split config
        custom_split_config = DataSplitConfig(
            min_total_records=10, random_seed=123, eval_size=5, val_ratio=0.2, limit=10
        )

        previous_result = TaskResult(
            workload_id=workload_id,
            flywheel_run_id=flywheel_run_id,
            client_id=client_id,
            data_split_config=custom_split_config,
        )

        mock_es_client.search.return_value = {
            "_scroll_id": "scroll123",
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "request": {
                                "messages": [
                                    {"role": "user", "content": f"Question {i}"},
                                    {"role": "assistant", "content": f"Answer {i}"},
                                ]
                            },
                            "response": {"choices": [{"message": {"content": f"Response {i}"}}]},
                        }
                    }
                    for i in range(5)
                ]
            },
        }

        with (
            patch("src.tasks.tasks.RecordExporter") as mock_record_exporter_class,
            patch("src.tasks.tasks.identify_workload_type") as mock_identify_workload,
            patch("src.tasks.tasks.DatasetCreator") as mock_dataset_creator_class,
            patch("src.tasks.tasks._check_cancellation") as mock_check_cancellation,
        ):
            mock_record_exporter = mock_record_exporter_class.return_value
            mock_record_exporter.get_records.return_value = ["record1", "record2"]

            mock_check_cancellation.return_value = None
            mock_identify_workload.return_value = WorkloadClassification.GENERIC

            mock_dataset_creator = mock_dataset_creator_class.return_value
            mock_dataset_creator.create_datasets.return_value = {"base": "test-dataset"}

            convert_result_to_task_result(create_datasets(previous_result))

            # Verify custom split config was used
            mock_record_exporter.get_records.assert_called_once_with(
                client_id, workload_id, custom_split_config
            )

            # Verify DatasetCreator was called with custom split config
            mock_dataset_creator_class.assert_called_once_with(
                ["record1", "record2"],
                flywheel_run_id,
                "",
                workload_id,
                client_id,
                split_config=custom_split_config,
            )

    def test_create_datasets_celery_serialization_dict_handling(self):
        """Test create_datasets with dict input to cover line 195 (Celery serialization)."""
        workload_id = "test-workload"
        flywheel_run_id = str(ObjectId())
        client_id = "test-client"

        # Pass a dict instead of TaskResult to test Celery serialization handling (line 195)
        previous_result_dict = {
            "workload_id": workload_id,
            "flywheel_run_id": flywheel_run_id,
            "client_id": client_id,
        }

        with (
            patch("src.tasks.tasks.RecordExporter") as mock_record_exporter_class,
            patch("src.tasks.tasks._check_cancellation") as mock_check_cancellation,
            patch("src.tasks.tasks.identify_workload_type") as mock_identify_workload,
            patch("src.tasks.tasks.DatasetCreator") as mock_dataset_creator_class,
        ):
            mock_record_exporter = mock_record_exporter_class.return_value
            mock_record_exporter.get_records.return_value = ["record1", "record2"]

            mock_check_cancellation.return_value = None
            mock_identify_workload.return_value = WorkloadClassification.GENERIC

            mock_dataset_creator = mock_dataset_creator_class.return_value
            mock_dataset_creator.create_datasets.return_value = {"base": "test-dataset"}

            # This should trigger line 195: if isinstance(previous_result, dict)
            result = convert_result_to_task_result(create_datasets(previous_result_dict))

            assert isinstance(result, TaskResult)
            assert result.workload_id == workload_id
            assert result.client_id == client_id
            assert result.flywheel_run_id == flywheel_run_id

    def test_create_datasets_direct_dict_input(
        self,
        mock_es_client,
        mock_data_uploader,
        mock_task_db,
        mock_settings,
        mock_dms_client,
    ):
        """Test create_datasets with direct dict input to specifically cover line 195."""
        workload_id = "test-workload"
        flywheel_run_id = str(ObjectId())
        client_id = "test-client"

        # Pass a dict directly to trigger line 195: if isinstance(previous_result, dict)
        previous_result_dict = {
            "workload_id": workload_id,
            "flywheel_run_id": flywheel_run_id,
            "client_id": client_id,
        }

        mock_settings.data_split_config.limit = 5

        mock_es_client.search.return_value = {
            "_scroll_id": "scroll123",
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "request": {
                                "messages": [
                                    {"role": "user", "content": "Question 1"},
                                    {"role": "assistant", "content": "Answer 1"},
                                ]
                            },
                            "response": {"choices": [{"message": {"content": "Response 1"}}]},
                        }
                    }
                ]
            },
        }

        with (
            patch("src.tasks.tasks.RecordExporter") as mock_record_exporter_class,
            patch("src.tasks.tasks._check_cancellation") as mock_check_cancellation,
            patch("src.tasks.tasks.identify_workload_type") as mock_identify_workload,
            patch("src.tasks.tasks.DatasetCreator") as mock_dataset_creator_class,
        ):
            mock_record_exporter = mock_record_exporter_class.return_value
            mock_record_exporter.get_records.return_value = ["record1"]

            mock_check_cancellation.return_value = None
            mock_identify_workload.return_value = WorkloadClassification.GENERIC

            mock_dataset_creator = mock_dataset_creator_class.return_value
            mock_dataset_creator.create_datasets.return_value = {"base": "test-dataset"}

            # This should trigger line 195: previous_result = TaskResult(**previous_result)
            result = convert_result_to_task_result(create_datasets(previous_result_dict))

            assert isinstance(result, TaskResult)
            assert result.workload_id == workload_id


class TestDatasetCreationErrorHandling:
    """Tests for dataset creation error handling scenarios."""

    def test_create_datasets_empty_data(
        self,
        mock_es_client,
        mock_data_uploader,
        mock_task_db,
        mock_settings,
        mock_dms_client,
    ):
        """Test creating datasets with empty KDB-X response."""
        workload_id = "test-workload"
        flywheel_run_id = str(ObjectId())
        client_id = "test-client"

        previous_result = TaskResult(
            workload_id=workload_id,
            flywheel_run_id=flywheel_run_id,
            client_id=client_id,
        )

        mock_es_client.search.return_value = {
            "_scroll_id": "scroll123",
            "hits": {
                "hits": []  # Empty hits list
            },
        }

        with (
            patch("src.tasks.tasks._check_cancellation") as mock_check_cancellation,
        ):
            mock_check_cancellation.return_value = None

            with pytest.raises(Exception) as exc_info:
                create_datasets(previous_result)

            # The error message now comes from DataValidator instead of RecordExporter
            assert "Not enough records found for the given workload" in str(exc_info.value)

            mock_data_uploader.upload_data.assert_not_called()

    def test_create_datasets_error_handling_unboundlocalerror_expected(
        self,
        mock_es_client,
        mock_data_uploader,
        mock_task_db,
        mock_dms_client,
    ):
        """Test create_datasets error handling - UnboundLocalError is expected when RecordExporter fails."""
        workload_id = "test-workload"
        flywheel_run_id = str(ObjectId())
        client_id = "test-client"

        previous_result = TaskResult(
            workload_id=workload_id,
            flywheel_run_id=flywheel_run_id,
            client_id=client_id,
        )

        with (
            patch("src.tasks.tasks.RecordExporter") as mock_record_exporter_class,
            patch("src.tasks.tasks._check_cancellation") as mock_check_cancellation,
        ):
            # Make RecordExporter raise an exception
            mock_record_exporter_class.side_effect = Exception("Record export failed")

            # Configure cancellation check to pass (not cancelled)
            mock_check_cancellation.return_value = None

            # This should raise the exception as expected when RecordExporter fails
            with pytest.raises(Exception) as exc_info:
                create_datasets(previous_result)

            assert "Record export failed" in str(exc_info.value)


class TestDatasetCreationCancellation:
    """Tests for dataset creation cancellation scenarios."""

    def test_create_datasets_cancellation(
        self,
        mock_task_db,
        mock_es_client,
        mock_data_uploader,
        mock_dms_client,
    ):
        """Test create_datasets when job is cancelled."""
        workload_id = "test-workload"
        flywheel_run_id = str(ObjectId())
        client_id = "test-client"

        previous_result = TaskResult(
            workload_id=workload_id,
            flywheel_run_id=flywheel_run_id,
            client_id=client_id,
        )

        with patch("src.tasks.tasks._check_cancellation") as mock_check_cancellation:
            # Configure cancellation check to raise FlywheelCancelledError
            mock_check_cancellation.side_effect = FlywheelCancelledError(
                flywheel_run_id, "Flywheel run was cancelled"
            )

            with pytest.raises(FlywheelCancelledError):
                create_datasets(previous_result)

            # Verify cancellation was checked
            mock_check_cancellation.assert_called_once_with(flywheel_run_id, raise_error=True)

            # Verify that no data processing occurred after cancellation
            mock_es_client.search.assert_not_called()
            mock_data_uploader.upload_data.assert_not_called()

