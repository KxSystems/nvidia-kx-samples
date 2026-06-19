# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

import asyncio
import html
import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import aiohttp
from langchain_core.runnables import RunnableConfig
from langchain_core.utils.json import parse_json_markdown
from langchain_openai import ChatOpenAI
from langgraph.types import StreamWriter

from kxta.constants import ASYNC_TIMEOUT
# Import KDB+ tools (requires NAT 1.3.0+ with MCP package)
from kxta.kdb_tools_nat import KDB_ENABLED
from kxta.kdb_tools_nat import is_kdb_query
from kxta.prompts import relevancy_checker
from kxta.embeddings import semantic_is_novel
from kxta.embeddings import semantic_route
from kxta.reranker import rerank_relevancy
from kxta.reranker import reranker_enabled
from kxta.schema import GeneratedQuery
# Re-exported for back-compat; merge_hybrid_results is retired in the process_single_query refactor (Task 4).
from kxta.source_agents.base import SourceResult  # noqa: F401
from kxta.source_agents.base import merge_source_results
from kxta.source_agents.registry import get_registry
from kxta.source_agents.routing import fallback_sources
from kxta.source_agents.routing import select_sources
from kxta.tools import search_rag
from kxta.tools import search_tavily
from kxta.utils import as_no_think_messages, _escape_markdown
from kxta.utils import dummy


# Deprecated: superseded by source_agents registry (merge_source_results).
def merge_hybrid_results(kdb_result: Optional[SourceResult], rag_result: Optional[SourceResult],
                         query: str) -> Tuple[str, str]:
    """
    Merge results from KDB and RAG sources into a unified response.

    Strategy:
    1. If both sources have relevant data, combine them with source attribution
    2. If only one source has data, use that source
    3. Prioritize KDB for quantitative data, RAG for qualitative context

    Args:
        kdb_result: Result from KDB+ financial database
        rag_result: Result from RAG document retrieval
        query: Original query for context

    Returns:
        Tuple of (merged_content, merged_citation)
    """
    has_kdb = kdb_result and not kdb_result.is_empty() and kdb_result.is_relevant
    has_rag = rag_result and not rag_result.is_empty() and rag_result.is_relevant

    # Case 1: Both sources have relevant data - merge them
    if has_kdb and has_rag:
        merged_content = f"""**Financial Data (KDB+):**
{kdb_result.content}

**Document Analysis (RAG):**
{rag_result.content}"""

        merged_citation = ""
        if kdb_result.citation:
            merged_citation += f"[KDB+ Source]\n{kdb_result.citation}\n"
        if rag_result.citation:
            merged_citation += f"\n[Document Source]\n{rag_result.citation}"

        return merged_content, merged_citation

    # Case 2: Only KDB has relevant data
    if has_kdb:
        return kdb_result.content, kdb_result.citation

    # Case 3: Only RAG has relevant data
    if has_rag:
        return rag_result.content, rag_result.citation

    # Case 4: Neither source has relevant data - return best available
    if kdb_result and kdb_result.content:
        return kdb_result.content, kdb_result.citation or ""
    if rag_result and rag_result.content:
        return rag_result.content, rag_result.citation or ""

    return "No relevant information found from available sources.", ""


def format_duration(seconds: float) -> str:
    """Format duration in human-readable format."""
    if seconds < 1:
        return f"{int(seconds * 1000)}ms"
    elif seconds < 60:
        return f"{seconds:.1f}s"
    else:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"


logger = logging.getLogger(__name__)


def compute_query_similarity(query_a: str, query_b: str) -> float:
    """Jaccard word-overlap similarity between two queries. Returns 0.0-1.0."""
    words_a = set(query_a.lower().split())
    words_b = set(query_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def is_query_novel(new_query: str, previous_queries: list[str], threshold: float = 0.7) -> bool:
    """True if new_query is below similarity threshold against ALL previous queries."""
    return all(compute_query_similarity(new_query, prev) < threshold for prev in previous_queries)


async def query_is_novel(new_query: str, previous_queries: list[str]) -> bool:
    """Novelty check for follow-up queries: semantic (embedding NIM) when available,
    Jaccard word-overlap fallback otherwise."""
    sem = await semantic_is_novel(new_query, previous_queries)
    if sem is not None:
        return sem
    return is_query_novel(new_query, previous_queries)


# Deprecated: superseded by source_agents registry (routing.select_sources).
async def classify_query_type(query: str, llm: ChatOpenAI = None, use_kdb: bool | None = None) -> str:
    """
    Classify a query to determine the best data source.

    Uses keyword heuristics for fast classification.
    Optionally uses LLM for more accurate classification.

    Args:
        query: The search query
        llm: Optional LLM for more accurate classification
        use_kdb: Explicit KDB control flag:
            - None (default): Auto-detect based on query content (legacy behavior, requires KDB_ENABLED env var)
            - True: Force KDB classification for all queries (bypasses KDB_ENABLED check)
            - False: Never classify as KDB

    Returns:
        'kdb' - Financial/time-series data queries
        'rag' - Document/unstructured content queries
        'web' - Current events/general web queries
    """
    # Handle explicit use_kdb flag (new UI behavior)
    if use_kdb is True:
        # Force KDB for all queries when explicitly enabled by user
        # This bypasses KDB_ENABLED env var - user explicitly requested KDB
        logger.info(f"Query classified as KDB+ (explicit use_kdb=True): {query[:50]}...")
        return "kdb"
    elif use_kdb is False:
        # Never use KDB when explicitly disabled
        logger.info(f"Query classified as RAG (explicit use_kdb=False): {query[:50]}...")
        return "rag"

    # Legacy behavior (use_kdb=None): Auto-detect based on query content
    # Requires KDB_ENABLED env var for backward compatibility
    if KDB_ENABLED and is_kdb_query(query):
        logger.info(f"Query classified as KDB+ (keyword match, auto-detect): {query[:50]}...")
        return "kdb"

    # Default to RAG for document queries
    return "rag"


async def check_relevancy(llm: ChatOpenAI, query: str, answer: str, writer: StreamWriter):
    """
    Checks if an answer is relevant to the query, returning JSON like
    { "score": "yes" } or { "score": "no" }.

    Preferred judge: a reranker NIM (RERANKER_NIM_URL — one ~1B forward pass per
    result instead of an LLM generation). Falls back to the LLM-as-judge prompt
    when the reranker is unconfigured or unavailable.
    """
    logger.info("CHECK RELEVANCY")
    writer({"relevancy_checker": "\n Starting relevancy check \n"})
    processed_answer_for_display = html.escape(_escape_markdown(answer))

    if reranker_enabled():
        rr = await rerank_relevancy(query, answer)
        if rr is not None:
            logit = rr.get("logit")
            writer({
                "relevancy_checker":
                    f"""
    ---
    Relevancy score: {rr.get("score")} (reranker NIM, logit={logit if logit is None else round(logit, 2)})
    Query: {query}
    """
            })
            return rr

    try:
        async with asyncio.timeout(ASYNC_TIMEOUT):
            response = await llm.ainvoke(
                as_no_think_messages(llm, relevancy_checker.format(document=answer, query=query)))
            score = parse_json_markdown(response.content)
            writer({
                "relevancy_checker":
                    f""" =
    ---
    Relevancy score: {score.get("score")}  
    Query: {query}
    Answer: {processed_answer_for_display}
    """
            })

            return score

    except asyncio.TimeoutError as e:
        writer({
            "relevancy_checker":
                f""" 
----------                
LLM time out evaluating relevancy. Query: {query} \n \n Answer: {processed_answer_for_display} 
----------
"""
        })
    except Exception as e:
        writer({
            "relevancy_checker":
                f"""
---------
Error checking relevancy. Query: {query} \n \n Answer: {processed_answer_for_display}
---------
"""
        })
        logger.debug(f"Error parsing relevancy JSON: {e}")

    # Judge unavailable: accept the answer but FLAG it as unjudged instead of the
    # old silent fail-open (which made the gate vanish exactly when the LLM was
    # flaky). Callers can distinguish a real "yes" from an unjudged pass, and the
    # condition is visible in the stream instead of invisible.
    logger.warning(f"Relevancy judge unavailable for query '{query[:60]}...' — passing answer through UNJUDGED")
    return {"score": "yes", "judge_error": True}


async def fetch_query_results(rag_url: str, prompt: str, writer: StreamWriter, collection: str):
    """
    Calls the search_rag tool for a prompt.
    Returns a tuple (answer, citations, doc_count).
    """
    async with aiohttp.ClientSession() as session:
        result = await search_rag(session, rag_url, prompt, writer, collection)
        # search_rag returns (answer, citations, doc_count)
        return result


def deduplicate_and_format_sources(sources: List[str],
                                   generated_answers: List[str],
                                   relevant_list: List[dict],
                                   web_results: List[str],
                                   queries: List[GeneratedQuery]):
    """
    Convert RAG and fallback results into an XML structure <sources><source>...</source></sources>.
    Each <source> has <query> and <answer>.
    If 'relevant_list' says "score": "no", we fallback to 'web_results' if present.
    """
    logger.info("DEDUPLICATE RESULTS")
    root = ET.Element("sources")

    for q_json, src, relevant_info, fallback_ans, gen_ans in zip(
        queries, sources, relevant_list, web_results, generated_answers
    ):
        source_elem = ET.SubElement(root, "source")
        query_elem = ET.SubElement(source_elem, "query")
        query_elem.text = q_json.query
        answer_elem = ET.SubElement(source_elem, "answer")

        # If the RAG doc was relevant, use gen_ans; else fallback to 'fallback_ans'
        if relevant_info["score"] == "yes" or fallback_ans is None:
            answer_elem.text = gen_ans
        else:
            answer_elem.text = fallback_ans

    return ET.tostring(root, encoding="unicode")


def build_findings_digest(prior_results: List[str], max_chars: int = 1500) -> str:
    """Compact cross-agent digest of earlier research rounds.

    Injected into later agent invocations (deepen hops, supervisor steps,
    reflection rounds) so agents can build on — instead of repeat — what other
    agents already found. Parses the <sources> XML blobs that web_research
    accumulates in state.web_research_results.
    """
    entries: List[str] = []
    for blob in prior_results or []:
        try:
            root = ET.fromstring(blob)
        except ET.ParseError:
            continue
        for src in root.findall("source"):
            q = (src.findtext("query") or "").strip()
            a = re.sub(r"\s+", " ", (src.findtext("answer") or "")).strip()
            if q and a:
                entries.append(f"- {q[:110]}: {a[:240]}")
    return "\n".join(entries)[:max_chars]


async def process_single_query(query: str,
                               config: RunnableConfig,
                               writer: StreamWriter,
                               collection,
                               llm,
                               search_web: bool,
                               use_kdb: bool | None = None,
                               hybrid_mode: bool = True,
                               scratchpad: 'Scratchpad | None' = None,
                               preferred_source: str | None = None):
    """
    Process a single query with hybrid search across multiple data sources.

    Hybrid Mode (default, hybrid_mode=True):
      - Executes KDB+ and RAG searches in parallel when both are enabled
      - Merges results from both sources with source attribution
      - Provides comprehensive answers combining quantitative and qualitative data

    Sequential Mode (hybrid_mode=False):
      - Legacy behavior: KDB first, early exit if relevant
      - Falls back to RAG only if KDB not relevant

    Args:
        query: The search query
        config: Runnable configuration
        writer: Stream writer for progress updates
        collection: RAG collection to search
        llm: LLM instance for relevancy checking
        search_web: Whether to perform web search fallback
        use_kdb: KDB control flag:
            - None (default): Auto-detect based on query content (legacy behavior)
            - True: Force KDB search for all queries
            - False: Disable KDB search entirely
        hybrid_mode: Enable parallel KDB+RAG execution with result merging (default: True)

    Returns a tuple of:
      (answer, citation, relevancy, web_answer, web_citation)
    """
    configurable = dict(config["configurable"])
    # Honor the explicit use_kdb arg passed by callers (overrides config copy).
    if use_kdb is not None:
        configurable["use_kdb"] = use_kdb
    configurable.setdefault("collection", collection)
    # Carry the resolved configurable (incl. collection) into the config the
    # sources receive — callers may pass collection as an arg only (e.g. artifact_qa).
    run_config = {**config, "configurable": configurable}

    registry = get_registry()
    enabled = registry.enabled_sources(configurable)
    chosen = select_sources(query, enabled, llm, preferred=preferred_source)

    # Semantic routing upgrade (embedding NIM): when neither the planner tag nor
    # keyword matching picked a specialized source (only the RAG floor remains),
    # try cosine similarity between the query and source descriptions.
    if chosen and all(not getattr(s, "keywords", []) for s in chosen):
        specialized = [(s.name, getattr(s, "description", "") or s.name) for s in enabled if getattr(s, "keywords", [])]
        best = await semantic_route(query, specialized)
        if best:
            picked = next((s for s in enabled if s.name == best), None)
            if picked is not None and picked not in chosen:
                chosen.insert(0, picked)
                logger.info(f"semantic_route -> '{best}' for: {query[:50]}...")

    if not chosen:
        # No data source available — preserve the legacy message + web fallback path.
        logger.warning(f"No source available for query: {query[:50]}...")
        # Surface it in the UI stream too — a silent no-op here produced
        # evidence-free reports with no visible explanation.
        writer({"search_progress": f"No data source enabled for: {query[:80]}"})
        relevancy = {"score": "no"}
        web_answer, web_citation = (None, None)
        if search_web:
            web_answer, web_citation = await _perform_web_search(query, writer)
        return ("No data source available for this query.", "", relevancy, web_answer, web_citation)

    async def _run_and_score(sources):
        """Dispatch the query to sources, stream per-source previews, judge relevancy."""
        batch = await asyncio.gather(*[s.run(query, run_config, writer) for s in sources])
        for r in batch:
            if r.content:
                dur = format_duration(r.duration_seconds)
                info = f"{r.record_count} records" if r.record_count else "complete"
                writer({f"{r.source}_answer": f"[{dur}, {info}]\n{r.citation}"})
                rel = await check_relevancy(llm, query, r.content, writer)
                r.is_relevant = rel.get("score") == "yes"
            else:
                r.is_relevant = False
        return batch

    writer({"search_progress": f"Querying {', '.join(s.name for s in chosen)}..."})
    results = await _run_and_score(chosen)
    overall_relevant = any(r.is_relevant for r in results)

    # Failure-aware rerouting: when the chosen sources produced nothing usable
    # (empty results or all judged irrelevant), re-dispatch ONCE to the next-best
    # sources from the fallback chains instead of giving up. Bounded to 2 fallback
    # sources per query.
    if not overall_relevant:
        tried = {s.name for s in chosen}
        failed = [s.name for s in chosen]
        fallbacks = fallback_sources(failed, enabled, tried)[:2]
        if fallbacks:
            names = ", ".join(s.name for s in fallbacks)
            writer({"search_progress": f"No usable result from {', '.join(failed)} — rerouting to {names}..."})
            logger.info(f"Rerouting query to fallback sources {names} after {failed} returned nothing usable")
            results.extend(await _run_and_score(fallbacks))
            overall_relevant = any(r.is_relevant for r in results)

    relevancy = {"score": "yes" if overall_relevant else "no"}

    merged_content, merged_citation = merge_source_results(results, query)

    if scratchpad:
        scratchpad.log("search_result",
                       {
                           "query": query,
                           "sources_used": [r.source for r in results if r.is_relevant],
                           "relevant": overall_relevant,
                       })

    web_answer, web_citation = (None, None)
    if search_web and not overall_relevant:
        writer({"search_progress": "Falling back to web search..."})
        web_answer, web_citation = await _perform_web_search(query, writer)

    return merged_content, merged_citation, relevancy, web_answer, web_citation


async def _perform_web_search(query: str, writer: StreamWriter) -> Tuple[Optional[str], Optional[str]]:
    """
    Perform web search as a fallback when other sources don't have relevant results.

    Returns:
        Tuple of (web_answer, web_citation)
    """
    web_start = time.time()
    web_result_count = 0

    result = await search_tavily(query, writer)
    web_duration = time.time() - web_start

    if result is not None:
        web_result_count = len([r for r in result if 'score' in r and float(r['score']) > 0.6])

        web_answers = [res['content'] if 'score' in res and float(res['score']) > 0.6 else "" for res in result]

        web_citations = [
            f"""
---
QUERY:
{query}

ANSWER:
{res['content']}

CITATION:
{res['url'].strip()}

""" if 'score' in res and float(res['score']) > 0.6 else "" for res in result
        ]

        web_answer = "\n".join(web_answers)
        web_citation = "\n".join(web_citations)

        # Guard against empty results
        if bool(re.fullmatch(r"\n*", web_answer)):
            web_answer = "No relevant result found in web search"
            web_citation = ""
    else:
        web_answer = "Web search not performed"
        web_citation = ""

    # Stream web results
    duration_str = format_duration(web_duration)
    result_info = f"{web_result_count} results" if web_result_count else "search complete"
    web_result_to_stream = web_citation if web_citation != "" else f"--- \n {web_answer} \n "
    writer({"web_answer": f"[{duration_str}, {result_info}]\n{web_result_to_stream}"})

    return web_answer, web_citation
