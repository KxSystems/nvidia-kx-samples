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
"""NemoGuard content-safety input rail (NIM roadmap item 2, piece 2).

ENHANCE-WHEN-PRESENT (same pattern as reranker.py): the rail activates only
when NEMOGUARD_MODEL_NAME is set — suggested value
"nvidia/llama-3.1-nemoguard-8b-content-safety" (verified working against the
hosted https://integrate.api.nvidia.com/v1 endpoint). When the env is unset or
the NIM call fails, check_content_safety returns None and callers proceed
exactly as they do today — the rail is an upgrade slot, never a point of
failure.

The NemoGuard 8B content-safety model card defines a prompt template that
wraps the conversation in a safety-category taxonomy and asks for a JSON
verdict like {"User Safety": "safe"|"unsafe", "Safety Categories": "..."}.
The NIM serving the model applies that template server-side for the
OpenAI-compatible /chat/completions route (confirmed live: a plain one-message
conversation of ~10 tokens bills ~400 prompt tokens and the completion is the
verdict JSON), so we send the text as a plain user message and parse the JSON
defensively.

Env:
- NEMOGUARD_MODEL_NAME  enable + model id (e.g. nvidia/llama-3.1-nemoguard-8b-content-safety)
- NEMOGUARD_BASE_URL    OpenAI-compatible base URL; falls back to INSTRUCT_BASE_URL,
                        then to the hosted https://integrate.api.nvidia.com/v1
- NVIDIA_API_KEY        bearer token (optional for unauthenticated local NIMs)
"""

from __future__ import annotations

import json
import logging
import os
import re

import aiohttp

logger = logging.getLogger(__name__)

NEMOGUARD_MODEL_NAME = os.getenv("NEMOGUARD_MODEL_NAME", "")
NEMOGUARD_BASE_URL = (os.getenv("NEMOGUARD_BASE_URL") or os.getenv("INSTRUCT_BASE_URL")
                      or "https://integrate.api.nvidia.com/v1").rstrip("/")

# Guard inputs are questions/topics; cap what we send to the safety model.
_MAX_INPUT_CHARS = 8000


def nemoguard_enabled() -> bool:
    return bool(NEMOGUARD_MODEL_NAME)


def _parse_verdict(content: str) -> dict | None:
    """Parse the NemoGuard verdict JSON, tolerating formatting variations.

    Returns {"safe": bool, "categories": str} or None when no verdict can be
    extracted.
    """
    content = (content or "").strip()
    if not content:
        return None

    candidates = [content]
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match and match.group(0) != content:
        candidates.append(match.group(0))

    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        verdict = None
        categories = ""
        for key, value in obj.items():
            key_norm = str(key).lower().strip().replace("_", " ")
            if key_norm == "user safety":
                verdict = str(value).lower().strip()
            elif key_norm in ("safety categories", "categories"):
                categories = str(value)
        if verdict in ("safe", "unsafe"):
            return {"safe": verdict == "safe", "categories": categories}

    # Some deployments answer with a bare token instead of JSON.
    lowered = content.lower()
    if lowered.startswith("unsafe"):
        return {"safe": False, "categories": ""}
    if lowered.startswith("safe"):
        return {"safe": True, "categories": ""}
    return None


async def check_content_safety(text: str, timeout_s: float = 15.0) -> dict | None:
    """Classify ``text`` with the NemoGuard content-safety NIM.

    Returns {"safe": bool, "categories": str}, or None when the rail is not
    configured or the call/parse fails — callers must treat None as "proceed"
    (today's behavior).
    """
    if not nemoguard_enabled():
        return None
    if not (text or "").strip():
        return {"safe": True, "categories": ""}

    payload = {
        "model": NEMOGUARD_MODEL_NAME,
        "messages": [{
            "role": "user", "content": text[:_MAX_INPUT_CHARS]
        }],
        "max_tokens": 200,
        "temperature": 0.0,
    }
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("NVIDIA_API_KEY") or os.getenv("INSTRUCT_API_KEY") or ""
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout_s)) as session:
            async with session.post(f"{NEMOGUARD_BASE_URL}/chat/completions", json=payload, headers=headers) as resp:
                resp.raise_for_status()
                data = await resp.json()
        content = data["choices"][0]["message"]["content"]
        verdict = _parse_verdict(content)
        if verdict is None:
            logger.warning(f"NemoGuard returned an unparseable verdict: {str(content)[:200]!r} — proceeding open")
        return verdict
    except Exception as e:
        logger.warning(f"NemoGuard content-safety NIM unavailable ({type(e).__name__}: {e}) — proceeding open")
        return None
