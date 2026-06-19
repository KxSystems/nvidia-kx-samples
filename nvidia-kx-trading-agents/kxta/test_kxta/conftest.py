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

import pytest
from unittest.mock import MagicMock, AsyncMock
from langchain_openai import ChatOpenAI
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from kxta.schema import GeneratedQuery, KXTAState, ConfigSchema


class CaptureWriter:
    """Callable that captures writer({"key": "val"}) calls into an events list."""

    def __init__(self):
        self.events = []

    def __call__(self, event: dict):
        self.events.append(event)

    def get_values(self, key: str) -> list[str]:
        """Get all values for a specific event key."""
        return [evt[key] for evt in self.events if key in evt]

    def has_event_matching(self, key: str, substring: str) -> bool:
        """Check if any event with the given key contains the substring."""
        return any(substring in val for val in self.get_values(key))


def make_mock_llm(responses: list[str]) -> FakeListChatModel:
    """
    Create a FakeListChatModel that works with LangChain's prompt | llm chains.
    The model streams characters from the concatenated responses.
    """
    # FakeListChatModel consumes one response per invocation
    combined = "".join(responses)
    return FakeListChatModel(responses=[combined])


@pytest.fixture
def mock_writer():
    """Fixture returning a CaptureWriter instance."""
    return CaptureWriter()


@pytest.fixture
def mock_llm():
    """Fixture returning a basic mock LLM with a single empty response."""
    return make_mock_llm([""])


@pytest.fixture
def mock_config(mock_llm):
    """Fixture returning a LangChain-style config dict with mock LLM."""
    return {
        "configurable": ConfigSchema(
            llm=mock_llm,
            report_organization="Test report organization",
            collection="test-collection",
            number_of_queries=2,
            rag_url="http://mock-rag:8081/v1",
            num_reflections=2,
            search_web=False,
            topic="Test topic",
        )
    }


@pytest.fixture
def sample_queries():
    """Fixture returning a list of 2 GeneratedQuery objects."""
    return [
        GeneratedQuery(
            query="What are the key findings on topic A",
            report_section="Introduction",
            rationale="Provides foundational understanding",
        ),
        GeneratedQuery(
            query="How does topic B compare to topic C",
            report_section="Analysis",
            rationale="Enables comparative analysis",
        ),
    ]


@pytest.fixture
def sample_kxta_state(sample_queries):
    """Fixture returning an KXTAState with queries populated."""
    return KXTAState(
        queries=sample_queries,
        web_research_results=["<sources><source><query>q1</query><answer>a1</answer></source></sources>"],
        citations="---\nQUERY:\nq1\n\nANSWER:\na1\n\nCITATION:\nhttp://example.com\n",
        running_summary="# Test Report\n\nThis is the initial test report content.",
    )
