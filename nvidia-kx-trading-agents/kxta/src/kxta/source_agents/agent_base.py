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
"""Generic adapter wrapping a borrowed compiled-graph ReAct agent as a SourceAgent."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import time

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from kxta.constants import ASYNC_TIMEOUT
from kxta.source_agents._vendor.config import use_blueprint_llm
from kxta.source_agents.base import SourceResult
from kxta.source_agents.streaming import WriterEmitter
from kxta.source_agents.streaming import use_emitter

logger = logging.getLogger(__name__)


class AgentSource:
    """Base class. Subclasses set class attrs + implement _build_graph()/_initial_state()."""

    name: str = ""
    label: str = ""
    description: str = ""
    keywords: list[str] = []
    requires_env: list[str] = []  # env vars that must be set for availability
    requires_modules: list[str] = []  # importable modules required for availability
    recursion_limit: int = 50

    def is_available(self) -> bool:
        for mod in self.requires_modules:
            if importlib.util.find_spec(mod) is None:
                return False
        for env in self.requires_env:
            if not os.getenv(env):
                return False
        return True

    async def _build_graph(self):
        raise NotImplementedError

    def _initial_state(self, query: str) -> dict:
        raise NotImplementedError

    def _record_count(self, data_summary: dict) -> int | None:
        for k in ("record_count", "articles_analyzed", "headlines_analyzed", "rows", "results"):
            if isinstance(data_summary, dict) and isinstance(data_summary.get(k), int):
                return data_summary[k]
        return None

    def _format_citation(self, sources: list[dict]) -> str:
        parts = []
        for s in sources or []:
            title = s.get("title") or s.get("name") or ""
            url = s.get("url") or s.get("link") or ""
            if title or url:
                parts.append(f"{title}\n{url}".strip())
        return "\n\n".join(parts)

    async def run(self, query: str, config: RunnableConfig, writer: StreamWriter) -> SourceResult:
        start = time.time()
        llm = config["configurable"].get("llm")
        emitter = WriterEmitter(writer, self.name)
        # Cross-agent memory: on follow-up rounds (deepen / supervisor) the
        # orchestrator passes a digest of what other agents already found, so this
        # agent builds on it instead of re-fetching covered ground.
        digest = (config["configurable"].get("findings_digest") or "").strip()
        effective_query = query if not digest else (
            f"{query}\n\n<prior_findings>\nFindings already gathered by other agents this run:\n{digest}\n"
            "</prior_findings>\nDo not repeat covered ground — focus on gaps and new information.")
        try:
            async with asyncio.timeout(ASYNC_TIMEOUT):
                with use_blueprint_llm(llm), use_emitter(emitter):
                    graph = await self._build_graph()
                    result = await graph.ainvoke(self._initial_state(effective_query),
                                                 {"recursion_limit": self.recursion_limit})
            # Vendored agents are inconsistent about the key holding their report:
            # most use research_report/final_report, the news agent uses "summary".
            report = result.get("research_report") or result.get("final_report") or result.get("summary") or ""
            data_summary = result.get("data_summary", {}) or {}
            return SourceResult(
                source=self.name,
                content=report,
                citation=self._format_citation(result.get("sources", [])),
                record_count=self._record_count(data_summary),
                duration_seconds=time.time() - start,
            )
        except asyncio.TimeoutError:
            # asyncio.timeout raises TimeoutError, whose str() is empty — log a clear,
            # actionable message (with the limit) instead of "source failed: ".
            elapsed = time.time() - start
            logger.error(f"{self.name} source timed out after {elapsed:.0f}s "
                         f"(ASYNC_TIMEOUT={ASYNC_TIMEOUT}s); raise KXTA_ASYNC_TIMEOUT if this source is just slow")
            return SourceResult(source=self.name, content="", citation="", duration_seconds=elapsed)
        except Exception as e:
            # Many exceptions (timeouts, some tool errors) have an empty str(); include the
            # type and full traceback so the cause is visible in the logs.
            elapsed = time.time() - start
            logger.exception(f"{self.name} source failed after {elapsed:.0f}s: {type(e).__name__}: {e}")
            return SourceResult(source=self.name, content="", citation="", duration_seconds=elapsed)
