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

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from src.scripts.load_test_data import create_openai_request_response, load_data_to_kdbx


@pytest.fixture
def sample_conversation_data():
    """Sample conversation data."""
    return {
        "messages": [
            {"role": "user", "content": "Hello, how are you?"},
            {"role": "assistant", "content": "I'm doing well, thank you!"},
        ],
        "tools": [{"name": "test_tool", "description": "A test tool"}],
    }


@pytest.fixture
def sample_log_format_data():
    """Sample data already in log format."""
    return [
        {
            "workload_id": "test_workload",
            "client_id": "test_client",
            "timestamp": 1234567890,
            "request": {"model": "test-model"},
            "response": {"id": "test-response"},
        }
    ]


@pytest.fixture
def test_data_dir():
    """Create and clean up test data directory."""
    from src.scripts.utils import get_project_root

    project_root = get_project_root()
    test_dir = os.path.join(project_root, "data", "test_files")
    os.makedirs(test_dir, exist_ok=True)

    yield test_dir

    import shutil

    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)


@pytest.fixture
def mock_pykx():
    """Mock pykx_connection for load_test_data."""
    mock_q = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_q)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    with patch("src.scripts.load_test_data.pykx_connection", return_value=mock_ctx):
        yield mock_q


def test_create_openai_request_response(sample_conversation_data):
    """Test the creation of OpenAI-style request/response pairs."""
    result = create_openai_request_response(sample_conversation_data)

    # Verify the structure of the result
    assert "timestamp" in result
    assert "request" in result
    assert "response" in result

    # Verify request structure
    request = result["request"]
    assert request["model"] == "not-a-model"
    assert request["temperature"] == 0.7
    assert request["max_tokens"] == 1000
    assert request["messages"] == sample_conversation_data["messages"][:-1]
    assert request["tools"] == sample_conversation_data["tools"]

    # Verify response structure
    response = result["response"]
    assert response["object"] == "chat.completion"
    assert response["model"] == "not-a-model"
    assert len(response["choices"]) == 1
    assert response["choices"][0]["message"] == sample_conversation_data["messages"][-1]
    assert "usage" in response


def test_load_data_with_log_format(mock_pykx, sample_log_format_data, test_data_dir):
    """Test loading data that's already in log format."""
    test_file = os.path.join(test_data_dir, "test_data.jsonl")
    with open(test_file, "w") as f:
        for item in sample_log_format_data:
            f.write(json.dumps(item) + "\n")

    load_data_to_kdbx(workload_id="new_workload", client_id="new_client", file_path=test_file)

    # Verify q insert was called once (one document)
    assert mock_pykx.call_count == 1
    call_args = mock_pykx.call_args
    # First arg is the q query string
    assert "flywheel_logs insert" in call_args[0][0]


def test_load_data_with_conversation_format(mock_pykx, sample_conversation_data, test_data_dir):
    """Test loading data that needs to be transformed into log format."""
    test_file = os.path.join(test_data_dir, "test_data.jsonl")
    with open(test_file, "w") as f:
        f.write(json.dumps(sample_conversation_data) + "\n")

    load_data_to_kdbx(workload_id="test_workload", client_id="test_client", file_path=test_file)

    # Verify q insert was called once (one document)
    assert mock_pykx.call_count == 1
    call_args = mock_pykx.call_args
    assert "flywheel_logs insert" in call_args[0][0]


def test_load_data_empty_file(mock_pykx, test_data_dir):
    """Test loading data from an empty file."""
    test_file = os.path.join(test_data_dir, "empty.jsonl")
    with open(test_file, "w") as _:
        pass

    load_data_to_kdbx(file_path=test_file)

    # No documents means no insert calls
    mock_pykx.assert_not_called()


def test_load_data_invalid_file(mock_pykx):
    """Test loading data with an invalid file path."""
    with pytest.raises(SystemExit):
        load_data_to_kdbx(file_path="nonexistent.jsonl")
