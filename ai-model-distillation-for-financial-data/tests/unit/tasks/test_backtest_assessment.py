"""Tests for the backtest assessment task."""

from datetime import datetime
from unittest.mock import ANY, MagicMock, patch

import pytest
from bson import ObjectId

from src.api.models import (
    DatasetType,
    EvalType,
    NIMConfig,
    TaskResult,
    WorkloadClassification,
)
from src.config import settings
from src.tasks.tasks import run_backtest_assessment
from tests.unit.tasks.conftest import convert_result_to_task_result


class TestBacktestAssessment:
    """Tests for run_backtest_assessment task."""

    @pytest.fixture(autouse=True)
    def enable_backtest(self, monkeypatch):
        """Enable backtest config for these tests."""
        monkeypatch.setattr(settings.backtest_config, "enabled", True, raising=False)
        monkeypatch.setattr(settings.backtest_config, "cost_bps", 5.0, raising=False)
        monkeypatch.setattr(settings.backtest_config, "min_signals", 10, raising=False)

    def _make_previous_result(self, valid_nim_config):
        return TaskResult(
            status="success",
            workload_id="test-workload",
            client_id="test-client",
            flywheel_run_id=str(ObjectId()),
            nim=valid_nim_config,
            workload_type=WorkloadClassification.CLASSIFICATION,
            datasets={DatasetType.BASE: "test-base-dataset"},
            evaluations={},
        )

    @patch("kdbx.backtest.run_backtest")
    @patch("kdbx.connection.pykx_connection")
    def test_backtest_success(
        self,
        mock_pykx_conn,
        mock_run_backtest,
        mock_task_db,
        valid_nim_config,
    ):
        """Verify backtest runs and stores scores correctly."""
        nim_id = ObjectId()
        mock_task_db.find_nim_run.return_value = {
            "_id": nim_id,
            "model_name": valid_nim_config.model_name,
        }

        # Mock signal count query
        mock_q = MagicMock()
        mock_q.return_value.py.return_value = 50
        mock_pykx_conn.return_value.__enter__ = MagicMock(return_value=mock_q)
        mock_pykx_conn.return_value.__exit__ = MagicMock(return_value=False)

        mock_run_backtest.return_value = {
            "sharpe": 1.5,
            "max_drawdown": -0.1,
            "total_return": 0.25,
            "win_rate": 0.6,
            "n_trades": 42,
        }

        previous = self._make_previous_result(valid_nim_config)
        result = run_backtest_assessment(previous)
        result = convert_result_to_task_result(result)

        # Verify NIMEvaluation was inserted
        mock_task_db.insert_evaluation.assert_called_once()
        eval_arg = mock_task_db.insert_evaluation.call_args[0][0]
        assert eval_arg.eval_type == EvalType.BACKTEST

        # Verify scores were updated
        update_calls = mock_task_db.update_evaluation.call_args_list
        final_call = update_calls[-1]
        scores = final_call[0][1]["scores"]
        assert scores["sharpe"] == 1.5
        assert scores["max_drawdown"] == -0.1
        assert scores["total_return"] == 0.25
        assert scores["win_rate"] == 0.6
        assert scores["n_trades"] == 42.0

        # Verify evaluation added to TaskResult
        assert EvalType.BACKTEST in result.evaluations

    def test_backtest_skipped_when_disabled(
        self,
        mock_task_db,
        valid_nim_config,
        monkeypatch,
    ):
        """Verify backtest skipped when backtest_config.enabled=false."""
        monkeypatch.setattr(settings.backtest_config, "enabled", False, raising=False)

        previous = self._make_previous_result(valid_nim_config)
        result = run_backtest_assessment(previous)
        result = convert_result_to_task_result(result)

        mock_task_db.insert_evaluation.assert_not_called()
        assert EvalType.BACKTEST not in result.evaluations

    def test_backtest_skipped_on_previous_error(
        self,
        mock_task_db,
        valid_nim_config,
    ):
        """Verify backtest is skipped when previous task has error."""
        previous = self._make_previous_result(valid_nim_config)
        previous.error = "Previous stage failed"

        result = run_backtest_assessment(previous)
        result = convert_result_to_task_result(result)

        mock_task_db.insert_evaluation.assert_not_called()
        assert result.error == "Previous stage failed"

    @patch("kdbx.connection.pykx_connection")
    def test_backtest_skipped_when_insufficient_signals(
        self,
        mock_pykx_conn,
        mock_task_db,
        valid_nim_config,
    ):
        """Verify backtest skips when signal count < min_signals."""
        nim_id = ObjectId()
        mock_task_db.find_nim_run.return_value = {
            "_id": nim_id,
            "model_name": valid_nim_config.model_name,
        }

        # Return signal count below threshold
        mock_q = MagicMock()
        mock_q.return_value.py.return_value = 3  # < min_signals=10
        mock_pykx_conn.return_value.__enter__ = MagicMock(return_value=mock_q)
        mock_pykx_conn.return_value.__exit__ = MagicMock(return_value=False)

        previous = self._make_previous_result(valid_nim_config)
        result = run_backtest_assessment(previous)
        result = convert_result_to_task_result(result)

        # Evaluation should still be inserted (to record the skip)
        mock_task_db.insert_evaluation.assert_called_once()

        # Should have update with skipped=True
        update_calls = mock_task_db.update_evaluation.call_args_list
        final_scores = update_calls[-1][0][1]["scores"]
        assert final_scores["skipped"] is True
        assert final_scores["n_signals"] == 3

        # No backtest evaluation on the TaskResult
        assert EvalType.BACKTEST not in result.evaluations

    @patch("kdbx.backtest.run_backtest", side_effect=Exception("KDB-X timeout"))
    @patch("kdbx.connection.pykx_connection")
    def test_backtest_failure_is_non_fatal(
        self,
        mock_pykx_conn,
        mock_run_backtest,
        mock_task_db,
        valid_nim_config,
    ):
        """Verify backtest failure doesn't raise — non-fatal."""
        nim_id = ObjectId()
        mock_task_db.find_nim_run.return_value = {
            "_id": nim_id,
            "model_name": valid_nim_config.model_name,
        }

        mock_q = MagicMock()
        mock_q.return_value.py.return_value = 50
        mock_pykx_conn.return_value.__enter__ = MagicMock(return_value=mock_q)
        mock_pykx_conn.return_value.__exit__ = MagicMock(return_value=False)

        previous = self._make_previous_result(valid_nim_config)
        # Should NOT raise
        result = run_backtest_assessment(previous)
        result = convert_result_to_task_result(result)

        # Error should be recorded on the evaluation, not the TaskResult
        update_calls = mock_task_db.update_evaluation.call_args_list
        error_call = [c for c in update_calls if "error" in c[0][1]]
        assert len(error_call) > 0
        assert "KDB-X timeout" in error_call[0][0][1]["error"]

        # TaskResult should NOT have an error (non-fatal)
        assert result.error is None

    def test_backtest_no_nim_run_gracefully_skipped(
        self,
        mock_task_db,
        valid_nim_config,
    ):
        """Verify backtest returns when no NIM run found."""
        mock_task_db.find_nim_run.return_value = None

        previous = self._make_previous_result(valid_nim_config)
        result = run_backtest_assessment(previous)
        result = convert_result_to_task_result(result)

        mock_task_db.insert_evaluation.assert_not_called()

    @patch("src.tasks.tasks._check_cancellation", return_value=True)
    def test_backtest_cancelled(
        self,
        mock_cancel,
        mock_task_db,
        valid_nim_config,
    ):
        """Verify backtest sets error when cancelled."""
        previous = self._make_previous_result(valid_nim_config)
        result = run_backtest_assessment(previous)
        result = convert_result_to_task_result(result)

        assert result.error is not None
        assert "cancelled" in result.error.lower()
        mock_task_db.insert_evaluation.assert_not_called()
