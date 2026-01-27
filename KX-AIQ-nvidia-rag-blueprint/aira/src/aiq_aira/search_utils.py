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
import aiohttp
import re
import time
import xml.etree.ElementTree as ET
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass
from langchain_openai import ChatOpenAI
from langchain_core.runnables import RunnableConfig
from aiq_aira.constants import ASYNC_TIMEOUT
from langgraph.types import StreamWriter
import logging
from langchain_core.utils.json import parse_json_markdown
from aiq_aira.schema import GeneratedQuery
from aiq_aira.prompts import relevancy_checker
from aiq_aira.tools import search_rag, search_tavily
from aiq_aira.utils import dummy, _escape_markdown
# Import KDB+ tools (requires NAT 1.3.0+ with MCP package)
from aiq_aira.kdb_tools_nat import (
    search_kdb_nat_with_fallback,
    search_kdb_nat,
    is_kdb_query,
    KDB_ENABLED,
    _mcp_available,
)
import html


@dataclass
class SourceResult:
    """Result from a single data source with metadata."""
    source: str  # 'kdb', 'rag', 'web'
    content: str
    citation: str
    is_relevant: bool = True
    record_count: Optional[int] = None
    duration_seconds: float = 0.0

    def is_empty(self) -> bool:
        """Check if the result has meaningful content."""
        if not self.content:
            return True
        # Check for common empty/error responses
        empty_patterns = [
            "no data",
            "no results",
            "not found",
            "no relevant",
            "no information",
            "unable to",
            "error",
        ]
        content_lower = self.content.lower()
        return any(p in content_lower for p in empty_patterns) and len(self.content) < 200


def merge_hybrid_results(
    kdb_result: Optional[SourceResult],
    rag_result: Optional[SourceResult],
    query: str
) -> Tuple[str, str]:
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
    Checks if an answer is relevant to the query using the 'relevancy_checker' prompt, returning JSON
    like { "score": "yes" } or { "score": "no" }.
    """
    logger.info("CHECK RELEVANCY")    
    writer({"relevancy_checker": "\n Starting relevancy check \n"})
    processed_answer_for_display = html.escape(_escape_markdown(answer))

    try:
        async with asyncio.timeout(ASYNC_TIMEOUT):
            response = await llm.ainvoke(
                relevancy_checker.format(document=answer, query=query)
            )
            score = parse_json_markdown(response.content)
            writer({"relevancy_checker": f""" =
    ---
    Relevancy score: {score.get("score")}  
    Query: {query}
    Answer: {processed_answer_for_display}
    """})

            return score
    
    except asyncio.TimeoutError as e:
             writer({"relevancy_checker": f""" 
----------                
LLM time out evaluating relevancy. Query: {query} \n \n Answer: {processed_answer_for_display} 
----------
"""})   
    except Exception as e:
        writer({"relevancy_checker": f"""
---------
Error checking relevancy. Query: {query} \n \n Answer: {processed_answer_for_display} 
---------
"""})
        logger.debug(f"Error parsing relevancy JSON: {e}")

    # default if fails
    return {"score": "yes"}


async def fetch_query_results(
    rag_url: str,
    prompt: str,
    writer: StreamWriter,
    collection: str
):
    """
    Calls the search_rag tool for a prompt.
    Returns a tuple (answer, citations, doc_count).
    """
    async with aiohttp.ClientSession() as session:
        result = await search_rag(session, rag_url, prompt, writer, collection)
        # search_rag returns (answer, citations, doc_count)
        return result



def deduplicate_and_format_sources(
    sources: List[str],
    generated_answers: List[str],
    relevant_list: List[dict],
    web_results: List[str],
    queries: List[GeneratedQuery]
):
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



async def process_single_query(
        query: str,
        config: RunnableConfig,
        writer: StreamWriter,
        collection,
        llm,
        search_web: bool,
        use_kdb: bool | None = None,
        hybrid_mode: bool = True
):
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

    rag_url = config["configurable"].get("rag_url")

    # Determine which sources to query
    kdb_allowed = (use_kdb is True) or KDB_ENABLED
    kdb_enabled = kdb_allowed and _mcp_available
    rag_enabled = collection and collection.strip()

    # For hybrid mode: run KDB and RAG in parallel
    if hybrid_mode and kdb_enabled and rag_enabled:
        logger.info(f"HYBRID SEARCH: Running KDB+ and RAG in parallel for: {query[:50]}...")
        writer({"hybrid_search": "Starting parallel KDB+ and RAG search..."})

        # Define async tasks for parallel execution
        async def search_kdb_async():
            kdb_start = time.time()
            try:
                answer, citation, record_count = await search_kdb_nat_with_fallback(query, writer, None)
                duration = time.time() - kdb_start
                return SourceResult(
                    source='kdb',
                    content=answer or "",
                    citation=citation or "",
                    record_count=record_count,
                    duration_seconds=duration
                )
            except Exception as e:
                logger.error(f"KDB+ search failed: {e}")
                return SourceResult(source='kdb', content="", citation="", duration_seconds=time.time() - kdb_start)

        async def search_rag_async():
            rag_start = time.time()
            try:
                answer, citation, doc_count = await fetch_query_results(rag_url, query, writer, collection)
                duration = time.time() - rag_start
                return SourceResult(
                    source='rag',
                    content=answer or "",
                    citation=citation or "",
                    record_count=doc_count,
                    duration_seconds=duration
                )
            except Exception as e:
                logger.error(f"RAG search failed: {e}")
                return SourceResult(source='rag', content="", citation="", duration_seconds=time.time() - rag_start)

        # Execute both searches in parallel
        kdb_result, rag_result = await asyncio.gather(search_kdb_async(), search_rag_async())

        # Stream individual results
        if kdb_result.content:
            duration_str = format_duration(kdb_result.duration_seconds)
            record_info = f"{kdb_result.record_count} records" if kdb_result.record_count else "query complete"
            writer({"kdb_answer": f"[{duration_str}, {record_info}]\n{kdb_result.citation}"})

        if rag_result.content:
            duration_str = format_duration(rag_result.duration_seconds)
            doc_info = f"{rag_result.record_count} docs" if rag_result.record_count else "search complete"
            writer({"rag_answer": f"[{duration_str}, {doc_info}]\n{rag_result.citation}"})

        # Check relevancy for both results
        if kdb_result.content:
            kdb_relevancy = await check_relevancy(llm, query, kdb_result.content, writer)
            kdb_result.is_relevant = kdb_relevancy.get("score") == "yes"

        if rag_result.content:
            rag_relevancy = await check_relevancy(llm, query, rag_result.content, writer)
            rag_result.is_relevant = rag_relevancy.get("score") == "yes"

        # Merge results from both sources
        merged_content, merged_citation = merge_hybrid_results(kdb_result, rag_result, query)

        # Determine overall relevancy
        overall_relevant = kdb_result.is_relevant or rag_result.is_relevant
        relevancy = {"score": "yes" if overall_relevant else "no"}

        # Log hybrid search outcome
        sources_used = []
        if kdb_result.content and kdb_result.is_relevant:
            sources_used.append("KDB+")
        if rag_result.content and rag_result.is_relevant:
            sources_used.append("RAG")
        logger.info(f"HYBRID SEARCH complete. Sources used: {', '.join(sources_used) or 'None relevant'}")
        writer({"hybrid_search": f"Merged results from: {', '.join(sources_used) or 'searching web fallback...'}"})

        # Web search fallback if neither source was relevant
        web_answer, web_citation = None, None
        if search_web and not overall_relevant:
            web_answer, web_citation = await _perform_web_search(query, writer)

        return merged_content, merged_citation, relevancy, web_answer, web_citation

    # Sequential mode (legacy behavior) or single-source queries
    # Classify query to determine best data source
    query_type = await classify_query_type(query, llm, use_kdb=use_kdb)

    # Try KDB+ first for financial/time-series queries (or when explicitly enabled)
    kdb_answer, kdb_citation, kdb_relevancy = None, None, None

    if query_type == "kdb" and kdb_enabled:
        logger.info(f"Routing query to KDB+ (query_type={query_type}): {query[:50]}...")
        logger.info("Using intelligent MCP client for KDB+")
        kdb_start = time.time()
        kdb_answer, kdb_citation, kdb_record_count = await search_kdb_nat_with_fallback(
            query, writer, None
        )
        kdb_duration = time.time() - kdb_start

        if kdb_answer:
            duration_str = format_duration(kdb_duration)
            record_info = f"{kdb_record_count} records" if kdb_record_count else "query complete"
            writer({"kdb_answer": f"[{duration_str}, {record_info}]\n{kdb_citation}"})
            kdb_relevancy = await check_relevancy(llm, query, kdb_answer, writer)
            if kdb_relevancy.get("score") == "yes":
                logger.info("KDB+ provided relevant answer, skipping RAG")
                return kdb_answer, kdb_citation, kdb_relevancy, None, None
            else:
                logger.info("KDB+ answer not relevant, will try RAG fallback if collection specified")

    # Process RAG search if collection is specified
    if rag_enabled:
        rag_start = time.time()
        rag_answer, rag_citation, rag_doc_count = await fetch_query_results(rag_url, query, writer, collection)
        rag_duration = time.time() - rag_start
        duration_str = format_duration(rag_duration)
        doc_info = f"{rag_doc_count} docs" if rag_doc_count else "search complete"
        writer({"rag_answer": f"[{duration_str}, {doc_info}]\n{rag_citation}"})
    else:
        # No RAG collection - use KDB result if available, otherwise empty
        if kdb_answer:
            logger.info("No RAG collection specified, using KDB+ result")
            return kdb_answer, kdb_citation, kdb_relevancy or {"score": "yes"}, None, None
        else:
            logger.warning(f"No RAG collection and no KDB result for query: {query[:50]}...")
            rag_answer = "No data source available for this query. Please select a RAG collection or enable KDB+."
            rag_citation = ""

    # Check relevancy for RAG answer
    relevancy = await check_relevancy(llm, query, rag_answer, writer)

    # Web search fallback
    web_answer, web_citation = None, None
    if search_web and relevancy["score"] == "no":
        web_answer, web_citation = await _perform_web_search(query, writer)

    return rag_answer, rag_citation, relevancy, web_answer, web_citation


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

        web_answers = [
            res['content'] if 'score' in res and float(res['score']) > 0.6 else ""
            for res in result
        ]

        web_citations = [
            f"""
---
QUERY:
{query}

ANSWER:
{res['content']}

CITATION:
{res['url'].strip()}

"""
            if 'score' in res and float(res['score']) > 0.6 else ""
            for res in result
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