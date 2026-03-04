"""Tests for market data enrichment integration in the pipeline."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId

from src.api.models import (
    DatasetType,
    TaskResult,
    WorkloadClassification,
)
from src.config import EnrichmentConfig, settings
from src.tasks.tasks import create_datasets
from tests.unit.tasks.conftest import convert_result_to_task_result


class TestEnrichmentIntegration:
    """Tests for enrichment in create_datasets."""

    @pytest.fixture(autouse=True)
    def enable_enrichment(self, monkeypatch):
        """Enable enrichment config for these tests."""
        monkeypatch.setattr(settings.enrichment_config, "enabled", True, raising=False)
        monkeypatch.setattr(settings.enrichment_config, "sym_field", "sym", raising=False)
        monkeypatch.setattr(
            settings.enrichment_config, "timestamp_field", "timestamp", raising=False
        )
        monkeypatch.setattr(settings.enrichment_config, "sym_extraction", "field", raising=False)

    def _make_previous_result(self):
        return TaskResult(
            workload_id="test-workload",
            flywheel_run_id=str(ObjectId()),
            client_id="test-client",
        )

    @patch("src.tasks.tasks.DatasetCreator")
    @patch("src.tasks.tasks.RecordExporter")
    @patch("src.tasks.tasks.identify_workload_type")
    @patch("kdbx.enrichment.pykx_connection")
    def test_enrichment_called_with_correct_records(
        self,
        mock_pykx,
        mock_identify,
        mock_exporter_cls,
        mock_creator_cls,
        mock_task_db,
    ):
        """Verify enrich_training_pairs_batch called with enrichable records."""
        records = [
            {"sym": "AAPL", "timestamp": "2025-01-15T10:00:00", "request": "buy"},
            {"sym": "MSFT", "timestamp": "2025-01-15T11:00:00", "request": "sell"},
        ]
        mock_exporter_cls.return_value.get_records.return_value = records
        mock_identify.return_value = WorkloadClassification.CLASSIFICATION
        mock_creator_cls.return_value.create_datasets.return_value = {
            DatasetType.BASE: "ds-base",
        }

        with patch(
            "kdbx.enrichment.enrich_training_pairs_batch"
        ) as mock_enrich:
            # Return enriched records with market fields added
            enriched = [
                {**r, "market_close": 150.0, "_enrich_sym": r["sym"], "_enrich_ts": r["timestamp"]}
                for r in records
            ]
            mock_enrich.return_value = enriched

            previous = self._make_previous_result()
            result = create_datasets(previous)
            result = convert_result_to_task_result(result)

            mock_enrich.assert_called_once()
            call_args = mock_enrich.call_args
            assert call_args.kwargs["sym_field"] == "_enrich_sym"
            assert call_args.kwargs["timestamp_field"] == "_enrich_ts"
            assert len(call_args.args[0]) == 2

    @patch("src.tasks.tasks.DatasetCreator")
    @patch("src.tasks.tasks.RecordExporter")
    @patch("src.tasks.tasks.identify_workload_type")
    @patch("kdbx.enrichment.pykx_connection")
    def test_enrichment_stats_set_on_result(
        self,
        mock_pykx,
        mock_identify,
        mock_exporter_cls,
        mock_creator_cls,
        mock_task_db,
    ):
        """Verify enrichment_stats is set on TaskResult after enrichment."""
        records = [
            {"sym": "AAPL", "timestamp": "2025-01-15T10:00:00", "request": "buy"},
        ]
        mock_exporter_cls.return_value.get_records.return_value = records
        mock_identify.return_value = WorkloadClassification.CLASSIFICATION
        mock_creator_cls.return_value.create_datasets.return_value = {
            DatasetType.BASE: "ds-base",
        }

        with patch(
            "kdbx.enrichment.enrich_training_pairs_batch"
        ) as mock_enrich:
            enriched = [{**records[0], "market_close": 150.0}]
            mock_enrich.return_value = enriched

            previous = self._make_previous_result()
            result = create_datasets(previous)
            result = convert_result_to_task_result(result)

            assert result.enrichment_stats is not None
            assert result.enrichment_stats["num_enriched"] == 1
            assert "market_close" in result.enrichment_stats["fields_added"]

    @patch("src.tasks.tasks.DatasetCreator")
    @patch("src.tasks.tasks.RecordExporter")
    @patch("src.tasks.tasks.identify_workload_type")
    def test_enrichment_failure_is_non_fatal(
        self,
        mock_identify,
        mock_exporter_cls,
        mock_creator_cls,
        mock_task_db,
    ):
        """Verify enrichment failure doesn't abort the pipeline."""
        records = [
            {"sym": "AAPL", "timestamp": "2025-01-15T10:00:00", "request": "buy"},
        ]
        mock_exporter_cls.return_value.get_records.return_value = records
        mock_identify.return_value = WorkloadClassification.CLASSIFICATION
        mock_creator_cls.return_value.create_datasets.return_value = {
            DatasetType.BASE: "ds-base",
        }

        with patch(
            "kdbx.enrichment.enrich_training_pairs_batch",
            side_effect=Exception("KDB-X connection failed"),
        ):
            previous = self._make_previous_result()
            # Should NOT raise — enrichment failure is non-fatal
            result = create_datasets(previous)
            result = convert_result_to_task_result(result)

            # Pipeline should continue with unenriched records
            assert result.enrichment_stats is None
            assert result.error is None

    @patch("src.tasks.tasks.DatasetCreator")
    @patch("src.tasks.tasks.RecordExporter")
    @patch("src.tasks.tasks.identify_workload_type")
    def test_enrichment_skipped_when_disabled(
        self,
        mock_identify,
        mock_exporter_cls,
        mock_creator_cls,
        mock_task_db,
        monkeypatch,
    ):
        """Verify enrichment is skipped when enrichment_config.enabled=false."""
        monkeypatch.setattr(settings.enrichment_config, "enabled", False, raising=False)

        records = [
            {"sym": "AAPL", "timestamp": "2025-01-15T10:00:00", "request": "buy"},
        ]
        mock_exporter_cls.return_value.get_records.return_value = records
        mock_identify.return_value = WorkloadClassification.CLASSIFICATION
        mock_creator_cls.return_value.create_datasets.return_value = {
            DatasetType.BASE: "ds-base",
        }

        with patch(
            "kdbx.enrichment.enrich_training_pairs_batch"
        ) as mock_enrich:
            previous = self._make_previous_result()
            result = create_datasets(previous)
            result = convert_result_to_task_result(result)

            mock_enrich.assert_not_called()
            assert result.enrichment_stats is None

    @patch("src.tasks.tasks.DatasetCreator")
    @patch("src.tasks.tasks.RecordExporter")
    @patch("src.tasks.tasks.identify_workload_type")
    def test_enrichment_skipped_when_no_enrichable_records(
        self,
        mock_identify,
        mock_exporter_cls,
        mock_creator_cls,
        mock_task_db,
    ):
        """Verify enrichment is skipped when records lack sym/timestamp."""
        records = [
            {"request": "buy AAPL"},  # no sym or timestamp field
        ]
        mock_exporter_cls.return_value.get_records.return_value = records
        mock_identify.return_value = WorkloadClassification.CLASSIFICATION
        mock_creator_cls.return_value.create_datasets.return_value = {
            DatasetType.BASE: "ds-base",
        }

        with patch(
            "kdbx.enrichment.enrich_training_pairs_batch"
        ) as mock_enrich:
            previous = self._make_previous_result()
            result = create_datasets(previous)
            result = convert_result_to_task_result(result)

            mock_enrich.assert_not_called()

    @patch("src.tasks.tasks.DatasetCreator")
    @patch("src.tasks.tasks.RecordExporter")
    @patch("src.tasks.tasks.identify_workload_type")
    @patch("kdbx.enrichment.pykx_connection")
    def test_temp_keys_cleaned_after_enrichment(
        self,
        mock_pykx,
        mock_identify,
        mock_exporter_cls,
        mock_creator_cls,
        mock_task_db,
    ):
        """Verify _enrich_sym and _enrich_ts are removed after enrichment."""
        records = [
            {"sym": "AAPL", "timestamp": "2025-01-15T10:00:00", "request": "buy"},
        ]
        mock_exporter_cls.return_value.get_records.return_value = records
        mock_identify.return_value = WorkloadClassification.CLASSIFICATION
        mock_creator_cls.return_value.create_datasets.return_value = {
            DatasetType.BASE: "ds-base",
        }

        with patch(
            "kdbx.enrichment.enrich_training_pairs_batch"
        ) as mock_enrich:
            enriched = [
                {
                    "sym": "AAPL",
                    "timestamp": "2025-01-15T10:00:00",
                    "request": "buy",
                    "market_close": 150.0,
                    "_enrich_sym": "AAPL",
                    "_enrich_ts": "2025-01-15T10:00:00",
                }
            ]
            mock_enrich.return_value = enriched

            previous = self._make_previous_result()
            create_datasets(previous)

            # Check that DatasetCreator received records without temp keys
            creator_call = mock_creator_cls.call_args
            passed_records = creator_call.args[0]
            for rec in passed_records:
                assert "_enrich_sym" not in rec
                assert "_enrich_ts" not in rec
