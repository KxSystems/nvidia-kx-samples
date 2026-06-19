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
"""Embedding-NIM helpers for semantic routing and query dedup (roadmap item 4).

ENHANCE-WHEN-PRESENT: active only when EMBEDDING_NIM_URL is set (e.g. the RAG
blueprint's nemoretriever-embedding-ms). Callers fall back to keyword routing /
Jaccard dedup when unset or on failure — the NIM is an upgrade slot, never a
point of failure.
"""

from __future__ import annotations

import logging
import math
import os

import aiohttp

logger = logging.getLogger(__name__)

EMBEDDING_NIM_URL = os.getenv("EMBEDDING_NIM_URL", "").rstrip("/")
EMBEDDING_NIM_MODEL = os.getenv("EMBEDDING_NIM_MODEL", "nvidia/llama-nemotron-embed-1b-v2")
# Cosine similarity above which two queries are considered duplicates.
# Calibrated live against llama-nemotron-embed-1b-v2: paraphrases score ~0.76,
# related-but-different queries ~0.60, unrelated ~0.16.
SEMANTIC_DEDUP_THRESHOLD = float(os.getenv("SEMANTIC_DEDUP_THRESHOLD", "0.70"))

# Tiny per-process cache: routing embeds the same source descriptions repeatedly
# and dedup re-embeds prior queries each round.
_cache: dict[tuple[str, str], list[float]] = {}
_CACHE_MAX = 512


def embeddings_enabled() -> bool:
    return bool(EMBEDDING_NIM_URL)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def embed(texts: list[str], input_type: str = "query", timeout_s: float = 15.0) -> list[list[float]] | None:
    """Embed texts via the NIM (with a small cache). None when disabled or on failure."""
    if not embeddings_enabled() or not texts:
        return None if not embeddings_enabled() else []

    missing = [t for t in texts if (input_type, t) not in _cache]
    if missing:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout_s)) as session:
                async with session.post(
                        f"{EMBEDDING_NIM_URL}/v1/embeddings",
                        json={
                            "model": EMBEDDING_NIM_MODEL,
                            "input": missing,
                            "input_type": input_type,
                        },
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
            vecs = [d["embedding"] for d in data["data"]]
            for t, v in zip(missing, vecs):
                if len(_cache) >= _CACHE_MAX:
                    _cache.pop(next(iter(_cache)))
                _cache[(input_type, t)] = v
        except Exception as e:
            logger.warning(f"Embedding NIM unavailable ({type(e).__name__}: {e}) — caller falls back")
            return None
    return [_cache[(input_type, t)] for t in texts]


async def semantic_is_novel(new_query: str, previous_queries: list[str]) -> bool | None:
    """True/False via embedding similarity; None when the NIM is unavailable
    (caller falls back to Jaccard)."""
    if not embeddings_enabled():
        return None
    if not previous_queries:
        return True
    vecs = await embed([new_query] + list(previous_queries))
    if vecs is None:
        return None
    new_vec, prev_vecs = vecs[0], vecs[1:]
    best = max((cosine(new_vec, p) for p in prev_vecs), default=0.0)
    return best < SEMANTIC_DEDUP_THRESHOLD


async def semantic_route(query: str, candidates: list[tuple[str, str]], min_sim: float = 0.30) -> str | None:
    """Pick the best-fit source for a query by cosine(query, source description).

    candidates: [(source_name, description)]. Returns the winning source name, or
    None when the NIM is unavailable / nothing clears min_sim (caller falls back).
    """
    if not embeddings_enabled() or not candidates:
        return None
    q_vec = await embed([query], input_type="query")
    d_vecs = await embed([d for _, d in candidates], input_type="passage")
    if q_vec is None or d_vecs is None:
        return None
    scored = [(cosine(q_vec[0], d), name) for (name, _), d in zip(candidates, d_vecs)]
    best_sim, best_name = max(scored)
    if best_sim < min_sim:
        return None
    return best_name
