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

"""Unit tests for scratchpad.py audit trail module."""

import json
import pytest
from unittest.mock import patch

from kxta.scratchpad import Scratchpad


@pytest.fixture
def scratchpad_dir(tmp_path):
    """Patch SCRATCHPAD_DIR to use a tmp_path for tests."""
    with patch('kxta.scratchpad.SCRATCHPAD_DIR', str(tmp_path)):
        yield tmp_path


class TestScratchpadLog:

    def test_creates_file(self, scratchpad_dir):
        """.log() creates JSONL file at expected path."""
        sp = Scratchpad(session_id="test-session")
        sp.log("init", {"topic": "AI research"})

        filepath = scratchpad_dir / "test-session.jsonl"
        assert filepath.exists()

    def test_appends_jsonl(self, scratchpad_dir):
        """3 logs -> 3 lines in file, each valid JSON."""
        sp = Scratchpad(session_id="test-append")
        sp.log("init", {"topic": "test"})
        sp.log("search_result", {"query": "q1"})
        sp.log("finalize", {"report_length": 1000})

        filepath = scratchpad_dir / "test-append.jsonl"
        lines = filepath.read_text().strip().split("\n")
        assert len(lines) == 3
        for line in lines:
            parsed = json.loads(line)
            assert "session_id" in parsed
            assert "timestamp" in parsed
            assert "type" in parsed
            assert "data" in parsed


class TestScratchpadRead:

    def test_read_entries(self, scratchpad_dir):
        """Scratchpad.read() returns list of dicts."""
        sp = Scratchpad(session_id="test-read")
        sp.log("init", {"topic": "test"})
        sp.log("search_result", {"query": "q1"})

        entries = Scratchpad.read("test-read")
        assert len(entries) == 2
        assert entries[0]["type"] == "init"
        assert entries[1]["type"] == "search_result"

    def test_read_skips_malformed(self, scratchpad_dir):
        """Manually corrupt a line -> read returns only valid entries."""
        sp = Scratchpad(session_id="test-malformed")
        sp.log("init", {"topic": "test"})

        # Manually append a malformed line
        filepath = scratchpad_dir / "test-malformed.jsonl"
        with open(filepath, "a") as f:
            f.write("this is not valid json\n")

        sp.log("finalize", {"done": True})

        entries = Scratchpad.read("test-malformed")
        assert len(entries) == 2  # init + finalize, skipping malformed

    def test_read_nonexistent(self, scratchpad_dir):
        """Unknown session_id -> empty list."""
        entries = Scratchpad.read("nonexistent-session-id")
        assert entries == []


class TestScratchpadSessionId:

    def test_auto_session_id(self, scratchpad_dir):
        """No session_id arg -> UUID generated."""
        sp = Scratchpad()
        assert sp.session_id is not None
        assert len(sp.session_id) == 36  # UUID format: 8-4-4-4-12

    def test_custom_session_id(self, scratchpad_dir):
        """Custom session_id is preserved."""
        sp = Scratchpad(session_id="my-custom-id")
        assert sp.session_id == "my-custom-id"


class TestScratchpadErrorHandling:

    def test_log_exception_handling(self, scratchpad_dir):
        """Patch open to raise -> no exception propagates."""
        sp = Scratchpad(session_id="test-error")
        with patch('builtins.open', side_effect=PermissionError("denied")):
            # Should NOT raise - fire and forget
            sp.log("init", {"topic": "test"})


class TestScratchpadEntrySchema:

    def test_entry_schema(self, scratchpad_dir):
        """Entry has keys: session_id, timestamp, type, data."""
        sp = Scratchpad(session_id="test-schema")
        sp.log("query_generated", {"query": "test query", "rationale": "testing"})

        entries = Scratchpad.read("test-schema")
        assert len(entries) == 1
        entry = entries[0]
        assert entry["session_id"] == "test-schema"
        assert "timestamp" in entry
        assert entry["type"] == "query_generated"
        assert entry["data"]["query"] == "test query"
