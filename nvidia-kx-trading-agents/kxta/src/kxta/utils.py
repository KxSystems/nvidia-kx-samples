# SPDX-FileCopyrightText: Copyright (c) 2025, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

import asyncio
import logging
import os
import re
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI


def current_date_str() -> str:
    """Today's date (UTC) as YYYY-MM-DD, used to time-anchor the trading prompts."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def tickers_display(config) -> str:
    """Human-readable ticker focus from the request config, for prompt injection."""
    raw = (config.get("configurable", {}).get("tickers") or "").strip()
    return raw or "none specified — infer from the topic"


logger = logging.getLogger(__name__)

# Colors for logging
BOLD = "\033[1m"
RESET = "\033[0m"


async def async_gen(num_loops: int):
    """
    Utility for retry loops or chunked iterations.
    """
    for i in range(num_loops):
        yield i
        await asyncio.sleep(0.0)


def update_system_prompt(system_prompt: str, llm: ChatOpenAI):
    """
    Set the reasoning-control system prompt for Nemotron models.

    Thinking is ON by default so the planning/reflection reasoning streams to the UI.
    Set KXTA_NEMOTRON_THINKING=off to disable it (useful if you also use Nemotron for
    report writing / Q&A and don't want chain-of-thought in those outputs).

    Thinking-control differs by model version:
      - v1   : "detailed thinking on" / "detailed thinking off"
      - v1.5 : empty system prompt = reasoning ON; "/no_think" = reasoning OFF
    """
    model_id = ""
    if hasattr(llm, "model") and isinstance(llm.model, str):
        model_id = llm.model
    if hasattr(llm, "model_name") and isinstance(llm.model_name, str):
        model_id = llm.model_name or model_id

    if "nemotron" not in model_id:
        return system_prompt

    thinking_on = os.getenv("KXTA_NEMOTRON_THINKING", "on").strip().lower() not in ("off", "false", "0", "no")

    if "v1.5" in model_id or "v1_5" in model_id:
        return "" if thinking_on else "/no_think"
    return "detailed thinking on" if thinking_on else "detailed thinking off"


def _model_id_of(llm) -> str:
    model_id = ""
    if hasattr(llm, "model") and isinstance(llm.model, str):
        model_id = llm.model
    if hasattr(llm, "model_name") and isinstance(llm.model_name, str):
        model_id = llm.model_name or model_id
    return model_id


def no_think_prefix(llm) -> str:
    """Reasoning-OFF system marker for INSTRUCT-role calls (report writer, Q&A,
    relevancy judge, source agents). Empty for non-Nemotron models, so the
    two-model deployment is unaffected. Unlike update_system_prompt (planning /
    reflection, where the thinking usefully streams to the UI), these paths never
    benefit from chain-of-thought -- it only multiplies latency. This is what
    makes a single-Nemotron deployment viable (one NIM instead of two).
    """
    model_id = _model_id_of(llm)
    if "nemotron" not in model_id:
        return ""
    if "v1.5" in model_id or "v1_5" in model_id:
        return "/no_think"
    return "detailed thinking off"


def as_no_think_messages(llm, prompt: str):
    """Wrap a plain string prompt with the reasoning-off system message when needed."""
    prefix = no_think_prefix(llm)
    if not prefix:
        return prompt
    return [SystemMessage(content=prefix), HumanMessage(content=prompt)]


def get_domain(url: str):
    """
    Extract the domain from a URL.
    """
    domain = url.split("/")[2]
    return domain.replace("www.", "") if domain.startswith("www.") else domain


async def dummy():
    """
    A do-nothing async function for placeholders.
    """
    return None


def format_sources(sources: str, source_num_start: int | None = None) -> str:
    """
    Format the sources into nicer looking markdown.
    """
    try:
        # Split sources into individual entries
        source_entries = re.split(r'(?=---\nQUERY:)', sources)
        formatted_sources = []
        src_count = 1

        for idx, entry in enumerate(source_entries):
            if not entry.strip():
                continue

            # Split into query, answer, and citations using a more precise pattern
            # This pattern looks for newlines followed by QUERY:, ANSWER:, or CITATION(S):
            # but only if they're not preceded by a pipe (|) character (markdown table)
            src_parts = re.split(r'(?<!\|)\n(?=QUERY:|ANSWER:|CITATION(?:S)?:)', entry.strip())

            if len(src_parts) >= 4:
                source_num = src_count
                # Remove the prefix from each part
                query = re.sub(r'^QUERY:', '', src_parts[1]).strip()
                answer = re.sub(r'^ANSWER:', '', src_parts[2]).strip()

                # Handle multiple citations
                citations = ''.join(src_parts[3:])

                formatted_entry = f"""
---
**Source** {source_num}

**Query:** {query}

**Answer:**
{answer}

{citations}
"""
                formatted_sources.append(formatted_entry)
                src_count += 1
            else:
                logger.info(f"Failed to clean up {entry} because it failed to parse")
                formatted_sources.append(entry)
                src_count += 1

        # Combine main content with formatted sources
        return "\n".join(formatted_sources)
    except Exception as e:
        logger.warning(f"Error formatting sources: {e}")
        return sources


def _escape_markdown(text: str) -> str:
    """
    Escapes Markdown to be rendered verbatim in the frontend in some scenarios
    Changes '* item' to '\* item', '1. item' to '\1. item', etc.
    """
    if not text:
        return ""
    # Escape unordered list items like * item, + item, - item
    text = re.sub(r"^(\s*)([*+-])(\s+)", r"\1\\\2\3", text, flags=re.MULTILINE)
    # Escape ordered list items like 1. item
    text = re.sub(r"^(\s*)(\d+\.)(\s+)", r"\1\\\2\3", text, flags=re.MULTILINE)
    text = text.replace("|", "\\|")
    text = text.replace("\n", "\\n")
    return text
