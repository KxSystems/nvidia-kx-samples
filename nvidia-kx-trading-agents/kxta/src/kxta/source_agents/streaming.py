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
"""Bridge borrowed-agent progress events onto KXTA's LangGraph StreamWriter.

Borrowed agents resolve a process-wide emitter via get_event_emitter() and call
emitter.emit_agent_progress_sync(agent_name, current_step, preview). We scope an
emitter per source run via a contextvar so concurrent sources don't cross streams.
"""

from __future__ import annotations

import contextlib
import contextvars
from typing import Callable
from typing import Optional

_current_emitter: contextvars.ContextVar = contextvars.ContextVar("kxta_source_emitter", default=None)


class WriterEmitter:
    """Adapts emit_agent_progress_sync(...) calls to writer({f'{source}_progress': text})."""

    def __init__(self, writer: Callable[[dict], None], source_name: str):
        self._writer = writer
        self._source = source_name

    def emit_agent_progress_sync(self, agent_name: str = "", current_step: str = "", preview: dict | None = None):
        # Stream only the human-readable step sentence. `preview` is a structured debug dict
        # (e.g. {'items': 6, 'query': '...'}) — never dump its raw repr into the UI. If there's
        # no step sentence, fall back to the preview's query text, else skip the event.
        text = (current_step or "").strip()
        if not text and isinstance(preview, dict):
            q = preview.get("query") or preview.get("topic")
            text = str(q).strip() if q else ""
        if not text:
            return
        try:
            self._writer({f"{self._source}_progress": text})
        except Exception:
            pass  # streaming is best-effort; never break a source run

    async def emit_agent_progress(self, agent_name: str = "", current_step: str = "", preview: dict | None = None):
        self.emit_agent_progress_sync(agent_name, current_step, preview)


def get_event_emitter() -> Optional[WriterEmitter]:
    """Return the emitter for the current source run, or None (borrowed code guards on None)."""
    return _current_emitter.get()


@contextlib.contextmanager
def use_emitter(emitter: WriterEmitter):
    token = _current_emitter.set(emitter)
    try:
        yield
    finally:
        _current_emitter.reset(token)
