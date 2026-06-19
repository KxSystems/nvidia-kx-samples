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
from kxta.source_agents.streaming import WriterEmitter, get_event_emitter, use_emitter


def test_emitter_forwards_progress_to_writer():
    events = []
    emitter = WriterEmitter(lambda e: events.append(e), source_name="web_search")
    emitter.emit_agent_progress_sync(agent_name="web_search", current_step="Searching web", preview={"q": "x"})
    assert events and "web_search_progress" in events[0]
    assert "Searching web" in events[0]["web_search_progress"]


def test_emitter_does_not_leak_raw_preview_dict():
    """The structured preview dict must not be dumped into the UI text."""
    events = []
    emitter = WriterEmitter(lambda e: events.append(e), source_name="fundamentals")
    emitter.emit_agent_progress_sync(current_step="Summarizing fundamental data",
                                     preview={"items": 6, "query": "NVIDIA 2024 highlights"})
    text = events[0]["fundamentals_progress"]
    assert text == "Summarizing fundamental data"
    assert "{" not in text and "items" not in text


def test_emitter_falls_back_to_query_when_no_step():
    events = []
    emitter = WriterEmitter(lambda e: events.append(e), source_name="market_data")
    emitter.emit_agent_progress_sync(current_step="", preview={"query": "AAPL price"})
    assert events[0]["market_data_progress"] == "AAPL price"


def test_emitter_skips_when_no_text_only_structured_preview():
    events = []
    emitter = WriterEmitter(lambda e: events.append(e), source_name="sec_filings")
    emitter.emit_agent_progress_sync(current_step="", preview={"items": 3})
    assert events == []


def test_contextvar_scopes_current_emitter():
    assert get_event_emitter() is None
    emitter = WriterEmitter(lambda e: None, source_name="market_data")
    with use_emitter(emitter):
        assert get_event_emitter() is emitter
    assert get_event_emitter() is None
