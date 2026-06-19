# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
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

"""Unit tests for report_gen_utils.py with mocked LLM."""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from conftest import CaptureWriter, make_mock_llm
from kxta.report_gen_utils import summarize_report


class TestSummarizeReport:

    @pytest.mark.asyncio
    async def test_initial_draft_uses_summarizer_prompt(self):
        """existing_summary='' -> uses summarizer_instructions prompt."""
        writer = CaptureWriter()
        llm = make_mock_llm(["This is the initial report draft."])

        # Mock the chain's astream
        result = await summarize_report(
            existing_summary="",
            new_source="<sources><source><query>q1</query><answer>a1</answer></source></sources>",
            report_organization="Test organization",
            llm=llm,
            writer=writer,
        )

        assert "initial report draft" in result
        assert writer.has_event_matching("summarize_sources", "Starting summary")

    @pytest.mark.asyncio
    async def test_extension_uses_extender_prompt(self):
        """existing_summary='...' -> uses report_extender prompt."""
        writer = CaptureWriter()
        llm = make_mock_llm(["Extended report with new insights."])

        result = await summarize_report(
            existing_summary="# Existing Report\n\nSome content here.",
            new_source="<sources><source><query>q2</query><answer>a2</answer></source></sources>",
            report_organization="Test organization",
            llm=llm,
            writer=writer,
        )

        assert "Extended report" in result

    @pytest.mark.asyncio
    async def test_think_tag_removal(self):
        """<think>...</think>Content -> returns Content."""
        writer = CaptureWriter()
        llm = make_mock_llm(["<think>reasoning here</think>", "Clean report content"])

        result = await summarize_report(
            existing_summary="",
            new_source="test source",
            report_organization="Test",
            llm=llm,
            writer=writer,
        )

        assert "reasoning here" not in result
        assert "Clean report content" in result

    @pytest.mark.asyncio
    async def test_think_tag_no_open_tag(self):
        """stuff</think>Content -> returns Content."""
        writer = CaptureWriter()
        llm = make_mock_llm(["reasoning stuff</think>", "Actual content after think"])

        result = await summarize_report(
            existing_summary="",
            new_source="test source",
            report_organization="Test",
            llm=llm,
            writer=writer,
        )

        assert "reasoning stuff" not in result
        assert "Actual content after think" in result

    @pytest.mark.asyncio
    async def test_timeout_returns_input(self):
        """TimeoutError -> returns formatted prompt unchanged."""
        writer = CaptureWriter()
        mock_llm = MagicMock()
        mock_llm.model = "test-model"
        mock_llm.model_name = "test-model"

        # Make astream raise TimeoutError
        async def mock_astream_timeout(*args, **kwargs):
            raise asyncio.TimeoutError()
            yield  # make it a generator  # noqa: E501

        mock_llm.astream = mock_astream_timeout

        # Patch the timeout to be very short
        with patch('kxta.report_gen_utils.ASYNC_TIMEOUT', 0.001):
            result = await summarize_report(
                existing_summary="",
                new_source="test source",
                report_organization="Test",
                llm=mock_llm,
                writer=writer,
            )

        # On timeout, function returns the user_input (the formatted prompt)
        assert "test source" in result or "Test" in result
        assert writer.has_event_matching("summarize_sources", "Timeout")
