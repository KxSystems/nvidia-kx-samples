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

"""Unit tests for utils.py pure functions."""

import pytest
from unittest.mock import MagicMock

from kxta.utils import format_sources, _escape_markdown, update_system_prompt


class TestFormatSources:

    def test_proper_markdown_formatting(self):
        """Properly formats sources with **Source** N markers."""
        sources = """---
QUERY:
What is AI?

ANSWER:
Artificial Intelligence is a field of computer science.

CITATION:
http://example.com/ai
"""
        result = format_sources(sources)
        assert "**Source** 1" in result
        assert "**Query:** What is AI?" in result
        assert "Artificial Intelligence" in result

    def test_multiple_sources(self):
        """Formats multiple source entries correctly."""
        sources = """---
QUERY:
First query

ANSWER:
First answer

CITATION:
http://example.com/1

---
QUERY:
Second query

ANSWER:
Second answer

CITATION:
http://example.com/2
"""
        result = format_sources(sources)
        assert "**Source** 1" in result
        assert "**Source** 2" in result
        assert "First query" in result
        assert "Second query" in result

    def test_malformed_graceful_fallback(self):
        """Graceful fallback on badly structured input."""
        malformed = "This is not a proper source format at all"
        result = format_sources(malformed)
        # Should return input without crashing
        assert result is not None

    def test_empty_string(self):
        """Empty input returns empty output."""
        result = format_sources("")
        assert result == ""


class TestEscapeMarkdown:

    def test_unordered_list_escape(self):
        """* item -> \\* item."""
        result = _escape_markdown("* item one\n* item two")
        assert "\\*" in result

    def test_pipe_escape(self):
        """|cell| -> \\|cell\\|."""
        result = _escape_markdown("| col1 | col2 |")
        assert "\\|" in result

    def test_empty_string(self):
        result = _escape_markdown("")
        assert result == ""

    def test_none_returns_empty(self):
        result = _escape_markdown(None)
        assert result == ""

    def test_ordered_list_escape(self):
        """1. item -> \\1. item."""
        result = _escape_markdown("1. First item")
        assert "\\1." in result

    def test_newline_escape(self):
        """Newlines are escaped."""
        result = _escape_markdown("line1\nline2")
        assert "\\n" in result


class TestUpdateSystemPrompt:

    def test_nemotron_v1_model_thinking_on_default(self):
        """v1 nemotron, default -> reasoning ON via 'detailed thinking on'."""
        llm = MagicMock()
        llm.model = "nvidia/llama-3.3-nemotron-super-49b-v1"
        llm.model_name = "nvidia/llama-3.3-nemotron-super-49b-v1"
        result = update_system_prompt("", llm)
        assert result == "detailed thinking on"

    def test_nemotron_v1_5_model_thinking_on_default(self):
        """v1.5 nemotron, default -> reasoning ON via empty system prompt."""
        llm = MagicMock()
        llm.model = "nvidia/llama-3.3-nemotron-super-49b-v1.5"
        llm.model_name = "nvidia/llama-3.3-nemotron-super-49b-v1.5"
        result = update_system_prompt("", llm)
        assert result == ""

    def test_nemotron_thinking_off_via_env(self, monkeypatch):
        """KXTA_NEMOTRON_THINKING=off -> /no_think (v1.5), 'detailed thinking off' (v1)."""
        monkeypatch.setenv("KXTA_NEMOTRON_THINKING", "off")
        v15 = MagicMock(); v15.model = v15.model_name = "nvidia/llama-3.3-nemotron-super-49b-v1.5"
        v1 = MagicMock(); v1.model = v1.model_name = "nvidia/llama-3.3-nemotron-super-49b-v1"
        assert update_system_prompt("", v15) == "/no_think"
        assert update_system_prompt("", v1) == "detailed thinking off"

    def test_non_nemotron_model(self):
        """Other model -> unchanged empty string."""
        llm = MagicMock()
        llm.model = "llama-3.3-instruct-70b"
        llm.model_name = "llama-3.3-instruct-70b"
        result = update_system_prompt("", llm)
        assert result == ""

    def test_nemotron_in_model_name_only(self):
        """'nemotron' only in model_name attr -> reasoning ON default (non-v1.5)."""
        llm = MagicMock()
        llm.model = "some-other-model"
        llm.model_name = "nemotron-variant"
        result = update_system_prompt("", llm)
        assert result == "detailed thinking on"

    def test_preserves_existing_prompt_for_non_nemotron(self):
        """Non-nemotron model preserves existing prompt."""
        llm = MagicMock()
        llm.model = "gpt-4"
        llm.model_name = "gpt-4"
        result = update_system_prompt("existing prompt", llm)
        assert result == "existing prompt"
