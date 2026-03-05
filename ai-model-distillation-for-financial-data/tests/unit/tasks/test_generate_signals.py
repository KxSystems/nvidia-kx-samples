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
"""Tests for generate_signals task and _parse_direction helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId

from src.api.models import CustomizationResult, TaskResult
from src.config import NIMConfig, settings
from src.tasks.tasks import _parse_direction, generate_signals


def _as_task_result(result) -> TaskResult:
    """Convert Celery's JSON-serialized dict back to TaskResult."""
    if isinstance(result, dict):
        return TaskResult(**result)
    return result


# ---------------------------------------------------------------------------
# _parse_direction tests
# ---------------------------------------------------------------------------


class TestParseDirection:
    def test_buy_keyword(self):
        assert _parse_direction("I recommend a BUY on AAPL") == "BUY"

    def test_sell_keyword(self):
        assert _parse_direction("The outlook is bearish, SELL") == "SELL"

    def test_hold_keyword(self):
        assert _parse_direction("I would HOLD this position") == "HOLD"

    def test_case_insensitive(self):
        assert _parse_direction("you should buy this stock") == "BUY"
        assert _parse_direction("consider selling now") == "SELL"

    def test_defaults_to_hold(self):
        assert _parse_direction("The market is uncertain") == "HOLD"

    def test_empty_string(self):
        assert _parse_direction("") == "HOLD"

    def test_buy_takes_precedence_over_sell(self):
        # BUY is checked first
        assert _parse_direction("BUY now, don't SELL") == "BUY"


# ---------------------------------------------------------------------------
# generate_signals task tests
# ---------------------------------------------------------------------------


class TestGenerateSignals:
    @pytest.fixture()
    def nim_config(self, sample_customizer_config):
        return NIMConfig(
            model_name="meta/llama-3.1-8b-instruct",
            context_length=2048,
            gpus=1,
            pvc_size="10Gi",
            tag="latest",
            registry_base="nvcr.io/nim",
            customization_enabled=True,
            customizer_configs=sample_customizer_config,
        )

    @pytest.fixture()
    def base_result(self, nim_config):
        return TaskResult(
            workload_id="test-workload",
            flywheel_run_id=str(ObjectId()),
            client_id="test-client",
            nim=nim_config,
        )

    @pytest.fixture(autouse=True)
    def enable_backtest(self, monkeypatch):
        monkeypatch.setattr(settings.backtest_config, "enabled", True, raising=False)

    def test_skips_when_backtest_disabled(self, base_result, monkeypatch):
        monkeypatch.setattr(settings.backtest_config, "enabled", False, raising=False)
        result = generate_signals(base_result, model_type="base")
        assert _as_task_result(result).error is None

    def test_skips_when_previous_error(self, base_result):
        base_result.error = "previous stage failed"
        result = generate_signals(base_result, model_type="base")
        assert _as_task_result(result).error == "previous stage failed"

    def test_skips_customized_when_no_customization(self, base_result):
        result = generate_signals(base_result, model_type="customized")
        assert _as_task_result(result).error is None

    @patch("kdbx.signals.write_signals_batch")
    @patch("kdbx.enrichment.extract_sym_from_record")
    @patch("src.tasks.tasks.RecordExporter")
    @patch("src.tasks.tasks.requests.post")
    def test_base_generates_signals(
        self, mock_post, mock_exporter_cls, mock_extract_sym, mock_write, base_result
    ):
        # Setup records
        records = [
            {
                "request": {
                    "messages": [
                        {"role": "user", "content": "What about AAPL?"},
                    ]
                }
            }
        ]
        mock_exporter_cls.return_value.get_records.return_value = records
        mock_extract_sym.return_value = "AAPL"

        # Setup NIM response
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "I recommend a BUY on AAPL"}}]
        }
        mock_post.return_value = mock_resp

        result = generate_signals(base_result, model_type="base")

        assert _as_task_result(result).error is None
        mock_write.assert_called_once()
        signals = mock_write.call_args[0][0]
        assert len(signals) == 1
        assert signals[0]["direction"] == "BUY"
        assert signals[0]["sym"] == "AAPL"
        assert signals[0]["model_id"] == "meta/llama-3.1-8b-instruct"

    @patch("kdbx.signals.write_signals_batch")
    @patch("kdbx.enrichment.extract_sym_from_record")
    @patch("src.tasks.tasks.RecordExporter")
    @patch("src.tasks.tasks.requests.post")
    def test_customized_uses_customized_model(
        self, mock_post, mock_exporter_cls, mock_extract_sym, mock_write, base_result
    ):
        base_result.customization = CustomizationResult(
            model_name="custom-model@v1",
        )
        records = [
            {
                "request": {
                    "messages": [{"role": "user", "content": "SELL MSFT?"}]
                }
            }
        ]
        mock_exporter_cls.return_value.get_records.return_value = records
        mock_extract_sym.return_value = "MSFT"

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "SELL MSFT due to earnings miss"}}]
        }
        mock_post.return_value = mock_resp

        result = generate_signals(base_result, model_type="customized")

        assert _as_task_result(result).error is None
        mock_write.assert_called_once()
        signals = mock_write.call_args[0][0]
        assert signals[0]["model_id"] == "custom-model@v1"
        assert signals[0]["direction"] == "SELL"

    @patch("kdbx.signals.write_signals_batch")
    @patch("kdbx.enrichment.extract_sym_from_record")
    @patch("src.tasks.tasks.RecordExporter")
    @patch("src.tasks.tasks.requests.post")
    def test_nim_failure_skips_record(
        self, mock_post, mock_exporter_cls, mock_extract_sym, mock_write, base_result
    ):
        records = [
            {"request": {"messages": [{"role": "user", "content": "AAPL?"}]}},
            {"request": {"messages": [{"role": "user", "content": "MSFT?"}]}},
        ]
        mock_exporter_cls.return_value.get_records.return_value = records
        mock_extract_sym.return_value = "AAPL"

        # First call fails, second succeeds
        mock_post.side_effect = [
            Exception("NIM timeout"),
            MagicMock(
                json=MagicMock(return_value={
                    "choices": [{"message": {"content": "BUY AAPL"}}]
                }),
                raise_for_status=MagicMock(),
            ),
        ]

        result = generate_signals(base_result, model_type="base")

        assert _as_task_result(result).error is None
        # Only one signal written (the one that succeeded)
        mock_write.assert_called_once()
        assert len(mock_write.call_args[0][0]) == 1

    @patch("kdbx.signals.write_signals_batch")
    @patch("kdbx.enrichment.extract_sym_from_record")
    @patch("src.tasks.tasks.RecordExporter")
    @patch("src.tasks.tasks.requests.post")
    def test_no_signals_when_no_sym(
        self, mock_post, mock_exporter_cls, mock_extract_sym, mock_write, base_result
    ):
        records = [
            {"request": {"messages": [{"role": "user", "content": "hello"}]}},
        ]
        mock_exporter_cls.return_value.get_records.return_value = records
        mock_extract_sym.return_value = None  # No sym extracted

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "BUY something"}}]
        }
        mock_post.return_value = mock_resp

        result = generate_signals(base_result, model_type="base")

        assert _as_task_result(result).error is None
        mock_write.assert_not_called()
