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
"""Relevancy gating via a NeMo Retriever reranker NIM (roadmap item 1).

Replaces the per-result LLM-as-judge call with a ~1B reranker forward pass when
RERANKER_NIM_URL is configured (e.g. the RAG cluster's own
nemoretriever-ranking-ms). ENHANCE-WHEN-PRESENT: when the env is unset or the
NIM call fails, callers fall back to the existing LLM judge — the reranker is
an upgrade slot, never a point of failure.

Score scale (measured against llama-nemotron-rerank-1b-v2): relevant passages
score strongly positive logits (~+10), off-topic ones strongly negative
(~-15 to -21), so the default threshold of 0.0 sits in a wide margin.
"""

from __future__ import annotations

import logging
import os

import aiohttp

logger = logging.getLogger(__name__)

RERANKER_NIM_URL = os.getenv("RERANKER_NIM_URL", "").rstrip("/")
RERANKER_NIM_MODEL = os.getenv("RERANKER_NIM_MODEL", "nvidia/llama-nemotron-rerank-1b-v2")
RERANKER_RELEVANCY_THRESHOLD = float(os.getenv("RERANKER_RELEVANCY_THRESHOLD", "0.0"))

# Rerankers have bounded input windows; long answers are scored in chunks and
# judged by their best chunk (one strong passage = the answer is relevant).
_CHUNK_CHARS = 1800
_MAX_CHUNKS = 4


def reranker_enabled() -> bool:
    return bool(RERANKER_NIM_URL)


def _chunk(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    chunks = [text[i:i + _CHUNK_CHARS] for i in range(0, len(text), _CHUNK_CHARS)]
    return chunks[:_MAX_CHUNKS]


async def rerank_relevancy(query: str, answer: str, timeout_s: float = 15.0) -> dict | None:
    """Judge answer relevancy with the reranker NIM.

    Returns {"score": "yes"|"no", "judge": "reranker", "logit": <max logit>} or
    None when the reranker is not configured / the call fails (caller falls back
    to the LLM judge).
    """
    if not reranker_enabled():
        return None
    passages = _chunk(answer)
    if not passages:
        return {"score": "no", "judge": "reranker", "logit": None}

    payload = {
        "model": RERANKER_NIM_MODEL,
        "query": {
            "text": query[:2000]
        },
        "passages": [{
            "text": p
        } for p in passages],
    }
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout_s)) as session:
            async with session.post(f"{RERANKER_NIM_URL}/v1/ranking", json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()
        rankings = data.get("rankings") or []
        if not rankings:
            return None
        max_logit = max(float(r["logit"]) for r in rankings)
        verdict = "yes" if max_logit >= RERANKER_RELEVANCY_THRESHOLD else "no"
        return {"score": verdict, "judge": "reranker", "logit": max_logit}
    except Exception as e:
        logger.warning(f"Reranker NIM unavailable ({type(e).__name__}: {e}) — falling back to LLM judge")
        return None
