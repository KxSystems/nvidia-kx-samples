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
"""Shim replacing the borrowed projects' src/config.py.

Every LLM getter returns the KXTA blueprint LLM injected via use_blueprint_llm().
No litellm / OpenAI / Fireworks / Anthropic clients are constructed here.
Tool getters build KXTA-side tools. Prompt loading reads the vendored prompts dir.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_blueprint_llm: contextvars.ContextVar = contextvars.ContextVar("kxta_blueprint_llm", default=None)

# Iteration caps preserved from the borrowed config (tune later).
WEB_SEARCH_MAX_ITERATIONS = 6
WEB_SEARCH_MAX_CONTEXT_TOKENS = 24000
WEB_SEARCH_TOOL_SUMMARIZATION_THRESHOLD = 4000
WEB_SEARCH_KEEP_RECENT_ITERATIONS = 2
MARKET_DATA_MAX_ITERATIONS = 6
MARKET_DATA_MIN_ITERATIONS_FOR_COMPLETION = 3
MARKET_DATA_SUMMARIZE_INDICATORS_LIMIT = 3
MARKET_DATA_SUMMARIZATION_THRESHOLD = 20000
MARKET_DATA_USE_SIMPLE_EXTRACTION = True
MARKET_DATA_BATCH_SUMMARIZATION = True
FUNDAMENTALS_MAX_ITERATIONS = 6
FUNDAMENTALS_MIN_ITERATIONS_FOR_COMPLETION = 2
FUNDAMENTALS_SUMMARIZATION_THRESHOLD = 15000
NEWS_HEADLINES_MAX_ITERATIONS = 6

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


@contextlib.contextmanager
def use_blueprint_llm(llm):
    """Scope the blueprint LLM all vendored getters return, for one source run."""
    token = _blueprint_llm.set(llm)
    try:
        yield
    finally:
        _blueprint_llm.reset(token)


def _require_llm():
    llm = _blueprint_llm.get()
    if llm is None:
        raise RuntimeError("No blueprint LLM injected. A SourceAgent must wrap agent invocation in "
                           "use_blueprint_llm(config['configurable']['llm']) (see spec section 9a).")
    return llm


# All LLM roles collapse to the single blueprint instruct LLM.
def get_research_llm():
    return _require_llm()


class _NoThinkLLM:
    """Thin pass-through that injects the reasoning-off system message into direct
    .invoke/.ainvoke calls (the agents' summarization prompts are plain strings,
    which would otherwise default to reasoning ON on Nemotron models). Not used
    in LCEL pipelines — vendored agents only call invoke/ainvoke/bind_tools."""

    def __init__(self, inner, prefix: str):
        self._inner = inner
        self._prefix = prefix

    def _patch(self, input):
        from langchain_core.messages import HumanMessage, SystemMessage
        if isinstance(input, str):
            return [SystemMessage(content=self._prefix), HumanMessage(content=input)]
        if isinstance(input, list):
            msgs = list(input)
            if msgs and isinstance(msgs[0], SystemMessage):
                if self._prefix not in msgs[0].content:
                    msgs[0] = SystemMessage(content=f"{self._prefix}\n\n{msgs[0].content}")
            else:
                msgs.insert(0, SystemMessage(content=self._prefix))
            return msgs
        return input

    def invoke(self, input, *args, **kwargs):
        return self._inner.invoke(self._patch(input), *args, **kwargs)

    async def ainvoke(self, input, *args, **kwargs):
        return await self._inner.ainvoke(self._patch(input), *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


_summarization_llm_cache = None


def _build_small_summarization_llm():
    """Dedicated small NIM for the agents' summarization calls (roadmap item 3).

    ENHANCE-WHEN-PRESENT: only when SUMMARIZATION_MODEL_NAME is set (e.g.
    meta/llama-3.1-8b-instruct). Endpoint defaults to the instruct LLM's
    OpenAI-compatible base URL; unset -> the blueprint LLM as before. These
    compression calls are the chattiest LLM path in a report, so a small model
    here is a large cost/latency win with no quality-critical writing involved.
    """
    global _summarization_llm_cache
    model = os.getenv("SUMMARIZATION_MODEL_NAME", "").strip()
    if not model:
        return None
    if _summarization_llm_cache is not None:
        return _summarization_llm_cache
    try:
        from langchain_openai import ChatOpenAI
        base_url = os.getenv("SUMMARIZATION_BASE_URL", "").strip() or os.getenv("INSTRUCT_BASE_URL", "").strip()
        if not base_url:
            return None
        _summarization_llm_cache = ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key=os.getenv("NVIDIA_API_KEY") or os.getenv("INSTRUCT_API_KEY") or "none",
            temperature=0.1,
            max_tokens=1024,
        )
        logger.info(f"Summarization LLM: dedicated small NIM '{model}' at {base_url}")
    except Exception as e:
        logger.warning(f"Failed to build summarization NIM client ({e}); using blueprint LLM")
        _summarization_llm_cache = None
    return _summarization_llm_cache


def get_summarization_llm():
    small = _build_small_summarization_llm()
    llm = small if small is not None else _require_llm()
    prefix = _reasoning_off_prefix_for(llm)
    return _NoThinkLLM(llm, prefix) if prefix else llm


def _reasoning_off_prefix_for(llm) -> str:
    """Reasoning-off marker for a SPECIFIC llm (the small NIM may differ from
    the blueprint LLM)."""
    try:
        from kxta.utils import no_think_prefix
        return no_think_prefix(llm)
    except Exception:
        return ""


def get_query_summary_llm():
    return _require_llm()


def get_orchestrator_llm():
    return _require_llm()


def _reasoning_off_prefix() -> str:
    """Reasoning-OFF marker for the current blueprint LLM ('' for non-Nemotron).

    Agent tool-planning and summarization never benefit from chain-of-thought;
    leaving it on multiplies per-call latency across dozens of calls per report.
    """
    try:
        from kxta.utils import no_think_prefix
        return no_think_prefix(_blueprint_llm.get())
    except Exception:
        return ""


def load_prompt(name: str) -> str:
    """Load a vendored .txt prompt verbatim (missing file -> empty).

    These are the agents' SYSTEM prompts — the reasoning-off marker is prepended
    here (single choke point) when the blueprint LLM is a Nemotron model.
    """
    path = _PROMPTS_DIR / name
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8").strip()
    prefix = _reasoning_off_prefix()
    return f"{prefix}\n\n{text}" if prefix else text


def load_prompt_template(name: str, **kwargs) -> str:
    """Load a vendored .txt prompt and .format(**kwargs) it (missing file -> empty)."""
    path = _PROMPTS_DIR / name
    if not path.exists():
        return ""
    prefix = _reasoning_off_prefix()
    text = path.read_text(encoding="utf-8")
    if prefix:
        text = f"{prefix}\n\n{text}"
    try:
        return text.format(**kwargs) if kwargs else text
    except (KeyError, IndexError):
        return text  # prompts with literal braces: return raw


# --- Tool getters (KXTA-side). LAZY imports — the tool modules are vendored in later tasks. ---


def get_all_web_tools() -> list:
    from kxta.source_agents._vendor.tools.firecrawl_tools import get_firecrawl_tools
    return get_firecrawl_tools()
