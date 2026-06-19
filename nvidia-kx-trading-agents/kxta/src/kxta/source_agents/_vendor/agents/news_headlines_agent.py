# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Vendored into the KXTA source-agents layer from the KX "agentic-anomaly-market-research" project
# (faithful copy; imports rewritten and heavy imports made lazy -- no logic changes).
"""
News Headlines Agent for fetching and filtering relevant news articles.
Fully async implementation with parallel tool execution support.
"""

import asyncio
import json
import re
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from kxta.source_agents._vendor.agents.base import NewsHeadlinesAgentState
from kxta.source_agents._vendor.config import get_research_llm, get_summarization_llm
from kxta.source_agents._vendor.config import load_prompt
from kxta.source_agents._vendor.tools.market_data_and_news_tools import get_news_tool
from kxta.source_agents.streaming import get_event_emitter
from kxta.source_agents._vendor.utils.tool_display import get_tool_display_name
from kxta.source_agents._vendor.report_utils import (
    extract_key_findings_from_markdown,
    parse_sentiment,
    create_standardized_output,
)


def _format_tool_call_description(tool_call) -> str:
    """Format a tool call with its arguments for display."""
    if isinstance(tool_call, dict):
        tool_name = tool_call.get('name', 'unknown')
        tool_args = tool_call.get('args', {})
    else:
        tool_name = getattr(tool_call, 'name', 'unknown')
        tool_args = getattr(tool_call, 'args', {})

    # Extract the most relevant argument for display
    if tool_name == 'get_news_tool':
        ticker = tool_args.get('ticker', '')
        return f"Fetching news for {ticker}" if ticker else "Fetching news"
    else:
        # Generic format for unknown tools - use display name
        display_name = get_tool_display_name(tool_name)
        if tool_args:
            first_arg = next(iter(tool_args.values()), '')
            if isinstance(first_arg, str) and first_arg:
                return f"{display_name}: {first_arg[:60]}"
        return display_name


def _emit_progress(current_step: str, preview: dict | None = None) -> None:
    emitter = get_event_emitter()
    if not emitter:
        return
    try:
        emitter.emit_agent_progress_sync(agent_name="news_headlines", current_step=current_step, preview=preview or {})
    except Exception as e:
        print(f"[NewsHeadlinesAgent] Error emitting progress: {e}")


async def process_tool_response(tool_message: ToolMessage, llm, max_size: int = 5000) -> ToolMessage:
    """
    Intelligently summarize large tool responses using LLM to preserve key information.

    Args:
        tool_message: The ToolMessage to process
        llm: LLM instance for summarization
        max_size: Maximum size in characters before summarization is triggered

    Returns:
        ToolMessage with original or summarized content
    """
    tool_content = getattr(tool_message, 'content', '')
    tool_name = getattr(tool_message, 'name', '')

    # If content is a Python object (list/dict), convert to JSON string first
    if isinstance(tool_content, (list, dict)):
        tool_content = json.dumps(tool_content)

    # If content is small enough, return as-is
    if isinstance(tool_content, str) and len(tool_content) <= max_size:
        return tool_message

    # For large responses, use LLM to create intelligent summary
    try:
        # Parse JSON if possible to provide context to LLM
        parsed_content = None
        content_str = tool_content

        # Handle Python objects (list/dict) - convert to JSON string first
        if isinstance(tool_content, (list, dict)):
            parsed_content = tool_content
            # Create a more readable representation for the LLM
            if isinstance(parsed_content, list):
                # News results - sample first and last few articles
                data_count = len(parsed_content)
                sample_size = min(3, data_count)
                sample_data = (parsed_content[:sample_size] +
                               (parsed_content[-sample_size:] if data_count > sample_size * 2 else []))
                content_str = json.dumps(
                    {
                        "results_count": data_count, "sample_results": sample_data, "full_data_available": True
                    }, indent=2)
            elif isinstance(parsed_content, dict):
                # Single news item or error - keep key fields
                if "error" in parsed_content:
                    content_str = json.dumps(parsed_content, indent=2)
                else:
                    # Extract key fields from news item
                    content_str = json.dumps(
                        {
                            "title": parsed_content.get("title", "N/A"),
                            "url": parsed_content.get("url", "N/A"),
                            "time_published": parsed_content.get("time_published", "N/A"),
                            "source_domain": parsed_content.get("source_domain", "N/A"),
                            "summary": parsed_content.get("summary", "")[:500] if parsed_content.get("summary") else "",
                            "full_data_available": True
                        },
                        indent=2)
        elif isinstance(tool_content, str):
            try:
                parsed_content = json.loads(tool_content)
                # Create a more readable representation for the LLM
                if isinstance(parsed_content, list):
                    # News results - sample first and last few articles
                    data_count = len(parsed_content)
                    sample_size = min(3, data_count)
                    sample_data = (parsed_content[:sample_size] +
                                   (parsed_content[-sample_size:] if data_count > sample_size * 2 else []))
                    content_str = json.dumps(
                        {
                            "results_count": data_count, "sample_results": sample_data, "full_data_available": True
                        },
                        indent=2)
                elif isinstance(parsed_content, dict):
                    # Single news item or error - keep key fields
                    if "error" in parsed_content:
                        content_str = json.dumps(parsed_content, indent=2)
                    else:
                        # Extract key fields from news item
                        content_str = json.dumps(
                            {
                                "title":
                                    parsed_content.get("title", "N/A"),
                                "url":
                                    parsed_content.get("url", "N/A"),
                                "time_published":
                                    parsed_content.get("time_published", "N/A"),
                                "source_domain":
                                    parsed_content.get("source_domain", "N/A"),
                                "summary":
                                    parsed_content.get("summary", "")[:500] if parsed_content.get("summary") else "",
                                "full_data_available":
                                    True
                            },
                            indent=2)
            except (json.JSONDecodeError, TypeError):
                # Not JSON, use string content
                parsed_content = None
                # Truncate to first and last portion for context
                if len(tool_content) > 10000:
                    content_str = tool_content[:
                                               3000] + "\n\n[... large content truncated for summarization ...]\n\n" + tool_content[
                                                   -3000:]
                else:
                    content_str = tool_content
        else:
            # Unknown type - convert to string
            content_str = str(tool_content)

        # Create summarization prompt
        summary_prompt = f"""You are summarizing a tool response from {tool_name} to reduce token usage while preserving all critical information.

TOOL RESPONSE (may be truncated or sampled):
{content_str}

Create a concise but comprehensive summary that:
1. Preserves all key information (article titles, URLs, publication times, sources, summaries)
2. Maintains important metadata (source domains, authors, timestamps)
3. Captures key news content and headlines if present
4. Keeps the summary in a structured format (preferably JSON if the original was JSON)
5. Is significantly shorter than the original while retaining essential information

If the original was JSON, return a JSON summary. Otherwise, return a structured text summary.
Focus on facts and data - no interpretation or recommendations needed."""

        # Get summary from LLM
        summary_response = await llm.ainvoke(summary_prompt)
        summary_content = summary_response.content if hasattr(summary_response, 'content') else str(summary_response)

        # Create new ToolMessage with summarized content
        return ToolMessage(content=summary_content,
                           tool_call_id=getattr(tool_message, 'tool_call_id', None),
                           name=tool_name)

    except Exception as e:
        # If summarization fails, fall back to truncation with metadata
        print(f"[NewsHeadlines] Warning: Failed to summarize tool response from {tool_name}: {e}")
        # Create a minimal summary with metadata
        # Handle Python objects (list/dict)
        if isinstance(tool_content, (list, dict)):
            try:
                if isinstance(tool_content, list):
                    data_count = len(tool_content)
                    fallback_summary = json.dumps({
                        "results_count": data_count,
                        "summary": f"Large dataset with {data_count} news articles collected successfully",
                        "note": "Full data available but truncated for token management"
                    })
                elif isinstance(tool_content, dict):
                    fallback_summary = json.dumps({
                        "title": tool_content.get("title", "N/A"),
                        "summary": "News article collected successfully",
                        "note": "Full data available but truncated for token management"
                    })
                else:
                    fallback_summary = '{"summary": "Large tool response collected", "note": "Data truncated for token management"}'
            except:
                fallback_summary = json.dumps(tool_content)[:max_size] + "... [truncated - summarization failed]"
        elif isinstance(tool_content, str):
            try:
                parsed = json.loads(tool_content)
                if isinstance(parsed, list):
                    data_count = len(parsed)
                    fallback_summary = json.dumps({
                        "results_count": data_count,
                        "summary": f"Large dataset with {data_count} news articles collected successfully",
                        "note": "Full data available but truncated for token management"
                    })
                elif isinstance(parsed, dict):
                    fallback_summary = json.dumps({
                        "title": parsed.get("title", "N/A"),
                        "summary": "News article collected successfully",
                        "note": "Full data available but truncated for token management"
                    })
                else:
                    fallback_summary = '{"summary": "Large tool response collected", "note": "Data truncated for token management"}'
            except:
                fallback_summary = tool_content[:max_size] + "... [truncated - summarization failed]"
        else:
            fallback_summary = str(tool_content)[:max_size] + "... [truncated - summarization failed]"

        return ToolMessage(content=fallback_summary,
                           tool_call_id=getattr(tool_message, 'tool_call_id', None),
                           name=tool_name)


async def create_news_headlines_agent_async():
    """
    Creates a news headlines agent for fetching and filtering relevant news.
    Async implementation with parallel tool execution.

    Returns:
        Compiled LangGraph agent for news headlines analysis.
    """
    llm = get_research_llm()
    summarization_llm = get_summarization_llm()  # Use smaller model for summarization
    tool_list = [get_news_tool]
    tool_node = ToolNode(tool_list, handle_tool_errors=True)
    llm_node = llm.bind_tools(tool_list, parallel_tool_calls=True)

    graph = StateGraph(NewsHeadlinesAgentState)

    async def agent(state):
        messages = state.get("messages", [])
        research_query = state.get("research_query", "")
        relevant_headlines = state.get("relevant_headlines", [])
        next_step = state.get("next_step", "")
        iteration_count = state.get("iteration_count", 0)

        # Prevent infinite loops - max iterations
        if iteration_count >= 5:  # Limit news agent to 5 iterations
            return {
                "messages": [AIMessage(content="RESEARCH COMPLETE: Maximum iterations reached. Filtering complete.")],
                "next_step": "complete",
                "iteration_count": iteration_count + 1
            }

        system_instructions = load_prompt("news_headlines.txt")

        context_info = ""
        if relevant_headlines:
            context_info += f"\n\nYou have already collected {len(relevant_headlines)} relevant headlines."

        # Check if we have any data yet
        if not relevant_headlines and iteration_count > 0:
            context_info += "\n\nWARNING: No relevant headlines collected yet. You MUST call get_news_tool to gather information."

        if not messages:
            message_list = [
                SystemMessage(content=system_instructions + context_info),
                HumanMessage(content="RESEARCH QUESTION: " + research_query)
            ]
            next_step = "research"
        else:
            # When continuing, preserve tool_use/tool_result pairs correctly
            # CRITICAL: Never break tool_use/tool_result pairs - this causes API errors
            message_list = list(messages)  # Create a copy to avoid modifying the original

            # Check if first message is already a SystemMessage
            if messages and isinstance(messages[0], SystemMessage):
                # System message already present - DON'T modify it to avoid breaking tool pairs
                pass  # Use messages as-is
            else:
                # No system message - prepend it (safe because we're adding at the beginning)
                message_list.insert(
                    0, SystemMessage(content=f"{system_instructions}{context_info}\n\nContinue the research."))

        response = await llm_node.ainvoke(message_list)

        # Check if response has tool calls
        has_tool_calls = hasattr(response, 'tool_calls') and response.tool_calls
        if not has_tool_calls and not relevant_headlines and iteration_count < 3:
            print(
                f"[NewsHeadlines] WARNING: No tool calls in response and no headlines collected. Response: {getattr(response, 'content', '')[:200]}"
            )

        content = getattr(response, 'content', '')
        if isinstance(content, list):
            content_str = ' '.join(str(item) for item in content)
        else:
            content_str = str(content) if content else ''

        if "RESEARCH COMPLETE" in content_str.upper():
            next_step = "complete"
        elif has_tool_calls:
            next_step = "tools"
        else:
            next_step = "continue"

        return {"messages": [response], "next_step": next_step, "iteration_count": iteration_count + 1}

    async def tools_with_filtering(state):
        """Execute tools asynchronously and filter news for relevance."""
        relevant_headlines = state.get("relevant_headlines", [])
        messages = state.get("messages", [])
        research_query = state.get("research_query", "")

        last_message = messages[-1] if messages else None
        if last_message and hasattr(last_message, "tool_calls") and last_message.tool_calls:
            # Emit each tool call separately with its arguments
            for tool_call in last_message.tool_calls:
                description = _format_tool_call_description(tool_call)
                _emit_progress(description)

        tool_results = await tool_node.ainvoke(state)

        tool_errors = []
        filtered_count = 0
        processed_messages = []

        # Extract key terms from research query for relevance filtering
        query_lower = (research_query or "").lower()
        query_terms = set()

        # Extract potential ticker (1-5 uppercase letters, but exclude common abbreviations)
        # Common abbreviations that shouldn't be treated as tickers
        common_abbreviations = {
            'ET', 'SEC', 'ARPU', 'NBA', 'DTC', 'M', 'A', 'Q', 'P', 'E', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z'
        }
        all_ticker_matches = re.findall(r'\b([A-Z]{1,5})\b', research_query)
        # Filter out single-letter matches and common abbreviations
        ticker_matches = [t for t in all_ticker_matches if len(t) >= 2 and t not in common_abbreviations]
        query_terms.update([t.lower() for t in ticker_matches])

        # Extract key words (3+ chars, not common words)
        common_words = {
            'the',
            'and',
            'for',
            'are',
            'but',
            'not',
            'you',
            'all',
            'can',
            'her',
            'was',
            'one',
            'our',
            'out',
            'day',
            'get',
            'has',
            'him',
            'his',
            'how',
            'its',
            'may',
            'new',
            'now',
            'old',
            'see',
            'two',
            'way',
            'who',
            'boy',
            'did',
            'let',
            'put',
            'say',
            'she',
            'too',
            'use',
            'this',
            'that',
            'with',
            'from',
            'have',
            'been',
            'will',
            'what',
            'when',
            'where',
            'which',
            'about',
            'into',
            'over',
            'after',
            'under',
            'above',
            'below',
            'between',
            'during',
            'before',
            'price',
            'stock',
            'market',
            'data',
            'news',
            'fetch',
            'intraday',
            'endofday',
            'premarket',
            'open',
            'close'
        }
        words = re.findall(r'\b([a-z]{3,})\b', query_lower)
        query_terms.update([w for w in words if w not in common_words])

        def is_relevant_news(item):
            """Check if a news item is relevant to the research query."""
            if not isinstance(item, dict) or "error" in item:
                return False

            # Check title, summary, and source for relevance
            title = (item.get('title') or '').lower()
            summary = (item.get('summary') or '').lower()
            source = (item.get('source_domain') or '').lower()
            text_to_check = f"{title} {summary} {source}"

            # Check for ticker matches
            relevance_score = 0
            for ticker in ticker_matches:
                if ticker.lower() in text_to_check:
                    relevance_score += 3  # Strong match for ticker

            # Count matches with query terms
            matching_terms = [term for term in query_terms if term in text_to_check]
            relevance_score += len(matching_terms)

            # Also check for date relevance if date in query
            date_match = re.search(r'\d{1,2}[th|st|nd|rd]?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)',
                                   query_lower)
            if date_match:
                time_published = item.get('time_published', '')
                if time_published:
                    relevance_score += 2

            # RELAXED FILTERING: Require minimum relevance score of 1 (was 2)
            # This ensures news has some connection to the query while being less restrictive
            # If we have a ticker match, that's enough
            # If we have query term matches, require at least 1 match
            if relevance_score < 1:
                return False

            # If we have a strong ticker match, always include
            if any(ticker.lower() in text_to_check for ticker in ticker_matches):
                return True

            # For query term matches, require at least 1 match (already checked with relevance_score >= 1)
            return True

        for tool_msg in tool_results.get("messages", []):
            if isinstance(tool_msg, ToolMessage):
                tool_name = getattr(tool_msg, 'name', '')
                tool_content = getattr(tool_msg, 'content', '')

                # DEBUG: Log the actual content type and format
                print(
                    f"[NewsHeadlines] Tool response - Name: {tool_name}, Content type: {type(tool_content)}, Is str: {isinstance(tool_content, str)}"
                )
                if isinstance(tool_content, str):
                    print(
                        f"[NewsHeadlines] Tool response - Content length: {len(tool_content)}, First 200 chars: {tool_content[:200]}"
                    )
                elif isinstance(tool_content, (list, dict)):
                    print(
                        f"[NewsHeadlines] Tool response - Content is {type(tool_content).__name__}, Length/Keys: {len(tool_content) if isinstance(tool_content, list) else list(tool_content.keys())[:5]}"
                    )

                # CRITICAL: Parse the ORIGINAL tool response BEFORE summarization
                # This ensures we extract news items even if the response gets summarized later
                original_parsed_content = None
                try:
                    # LangChain ToolNode may return the content as:
                    # 1. A Python object (list/dict) - if tool returns Python objects
                    # 2. A JSON string - if LangChain serializes it
                    # 3. A string representation - if LangChain calls str() on it

                    if isinstance(tool_content, (list, dict)):
                        # Content is already a Python object - use it directly
                        original_parsed_content = tool_content
                        print(
                            f"[NewsHeadlines] Tool returned Python object directly (type: {type(tool_content).__name__})"
                        )
                    elif isinstance(tool_content, str):
                        # Content is a string - try to parse as JSON
                        try:
                            original_parsed_content = json.loads(tool_content)
                            print(f"[NewsHeadlines] Successfully parsed JSON string")
                        except (json.JSONDecodeError, TypeError) as e:
                            # Not valid JSON - keep as string and log
                            original_parsed_content = tool_content
                            print(f"[NewsHeadlines] Failed to parse as JSON: {e}. Keeping as string.")
                    else:
                        # Unknown type - convert to string
                        original_parsed_content = str(tool_content)
                        print(f"[NewsHeadlines] Unknown content type {type(tool_content)}, converted to string")
                except Exception as e:
                    original_parsed_content = tool_content
                    tool_errors.append(f"Error parsing {tool_name}: {str(e)}")
                    print(f"[NewsHeadlines] Exception parsing tool content: {e}")

                # Process news items from ORIGINAL response (before summarization)
                if "get_news" in tool_name.lower() or "news" in tool_name.lower():
                    if isinstance(original_parsed_content, list):
                        for item in original_parsed_content:
                            if isinstance(item, dict):
                                # Check for errors first
                                if "error" in item:
                                    error_msg = item.get("error", "Unknown error")
                                    tool_errors.append(f"{tool_name}: {error_msg}")
                                else:
                                    # Filter by relevance before adding
                                    if is_relevant_news(item):
                                        is_duplicate = any(
                                            (existing.get("title") and item.get("title") and existing.get("title") ==
                                             item.get("title")) or (existing.get("url") and item.get("url")
                                                                    and existing.get("url") == item.get("url"))
                                            for existing in relevant_headlines if isinstance(existing, dict))
                                        if not is_duplicate:
                                            relevant_headlines.append(item)
                                    else:
                                        filtered_count += 1
                    elif isinstance(original_parsed_content, dict):
                        if "error" in original_parsed_content:
                            error_msg = original_parsed_content.get("error", "Unknown error")
                            tool_errors.append(f"{tool_name}: {error_msg}")
                        else:
                            # Filter by relevance before adding
                            if is_relevant_news(original_parsed_content):
                                if original_parsed_content not in relevant_headlines:
                                    relevant_headlines.append(original_parsed_content)
                            else:
                                filtered_count += 1
                    elif isinstance(original_parsed_content, str):
                        # Tool returned a string (non-JSON) - log it for debugging
                        print(
                            f"[NewsHeadlines] Tool returned string content (length: {len(original_parsed_content)}). First 500 chars: {original_parsed_content[:500]}"
                        )
                        # Try to extract any JSON-like structures from the string
                        try:
                            # Look for JSON arrays or objects in the string
                            json_matches = re.findall(r'\[.*?\]|\{.*?\}', original_parsed_content, re.DOTALL)
                            if json_matches:
                                for json_str in json_matches:
                                    try:
                                        parsed_json = json.loads(json_str)
                                        if isinstance(parsed_json, list):
                                            for item in parsed_json:
                                                if isinstance(item, dict) and is_relevant_news(item):
                                                    is_duplicate = any(
                                                        existing.get("title") == item.get("title")
                                                        or existing.get("url") == item.get("url")
                                                        for existing in relevant_headlines
                                                        if isinstance(existing, dict))
                                                    if not is_duplicate:
                                                        relevant_headlines.append(item)
                                        elif isinstance(parsed_json, dict) and is_relevant_news(parsed_json):
                                            if parsed_json not in relevant_headlines:
                                                relevant_headlines.append(parsed_json)
                                    except json.JSONDecodeError:
                                        continue
                        except Exception as e:
                            print(f"[NewsHeadlines] Error trying to extract JSON from string response: {e}")
                        tool_errors.append(
                            f"{tool_name}: Tool returned non-JSON string response (may need different parsing)")

                # NOW process/summarize the tool response for message history (after extracting data)
                processed_msg = await process_tool_response(tool_msg, summarization_llm, max_size=5000)
                processed_messages.append(processed_msg)

                # Check for errors in tool response (after processing)
                if isinstance(original_parsed_content, dict) and "error" in original_parsed_content:
                    error_msg = original_parsed_content.get("error", "Unknown error")
                    tool_errors.append(f"{tool_name} error: {error_msg}")
                    continue
            else:
                # Keep non-tool messages as-is
                processed_messages.append(tool_msg)

        if relevant_headlines:
            print(
                f"[NewsHeadlines] Collected: {len(relevant_headlines)} relevant headlines (filtered out {filtered_count} irrelevant items)"
            )
        elif tool_errors:
            print(f"[NewsHeadlines] Tool errors: {tool_errors}")
        else:
            print(f"[NewsHeadlines] WARNING: No relevant headlines collected from tools")

        return {
            "messages": processed_messages,  # Use processed messages with summarized tool responses
            "relevant_headlines": relevant_headlines,
            "next_step": "summarize"  # Go to summarization after collecting data
        }

    def should_continue(state):
        next_step = state.get("next_step", "")
        messages = state.get("messages", [])
        iteration_count = state.get("iteration_count", 0)
        relevant_headlines = state.get("relevant_headlines", [])

        # Force end if max iterations reached
        if iteration_count >= 5:
            return "end"

        # If next_step is "summarize", we should have already gone through tools
        # This shouldn't happen from agent node, but handle it just in case
        if next_step == "summarize":
            return "end"  # Summarize is handled by hard edge from tools

        if next_step == "complete":
            return "end"
        if not messages:
            return "end"

        last_message = messages[-1]

        # If we have tool calls, execute them
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            return "tools"

        # Check if agent said research is complete
        content = getattr(last_message, 'content', '')
        if isinstance(content, list):
            content_str = ' '.join(str(item) for item in content)
        else:
            content_str = str(content) if content else ''
        if "RESEARCH COMPLETE" in content_str.upper():
            return "end"

        # If we have headlines collected and done minimum iterations, we're done
        # BUT: Don't end here if we haven't summarized yet - let tools->summarize flow complete
        # This check is only for when agent decides to stop without calling tools
        if relevant_headlines and iteration_count >= 1:
            # Only end if we've already been through summarize (indicated by summary in state or complete next_step)
            # Otherwise, we need to go through tools->summarize first
            return "end"

        # If we've done many iterations with no data, end to prevent infinite loops
        if iteration_count >= 3 and not relevant_headlines:
            return "end"

        # Default: end (prevents infinite loops)
        return "end"

    async def summarize(state):
        """Summarize collected news headlines into a concise report."""
        messages = state.get("messages", [])
        relevant_headlines = state.get("relevant_headlines", [])
        research_query = state.get("research_query", "")

        _emit_progress(
            "Summarizing news headlines",
            preview={
                "headlines_count": len(relevant_headlines), "query": research_query[:120]
            },
        )

        # Messages should already be summarized, but ensure we don't exceed token limits
        # Check if any message is still too large
        cleaned_messages = []
        for msg in messages:
            if isinstance(msg, ToolMessage):
                content = getattr(msg, 'content', '')
                if isinstance(content, str) and len(content) > 100000:
                    # Still too large, summarize again (using smaller model)
                    processed_msg = await process_tool_response(msg, summarization_llm, max_size=10000)
                    cleaned_messages.append(processed_msg)
                else:
                    cleaned_messages.append(msg)
            else:
                cleaned_messages.append(msg)

        # Build summary of collected headlines
        headlines_summary = ""
        if relevant_headlines:
            headlines_summary = f"\n\nCollected {len(relevant_headlines)} relevant news articles:\n"
            for i, headline in enumerate(relevant_headlines[:10], 1):  # Limit to top 10 for summary
                if isinstance(headline, dict):
                    title = headline.get("title", "N/A")
                    url = headline.get("url", "")
                    time_pub = headline.get("time_published", "")
                    source = headline.get("source_domain", "")
                    headlines_summary += f"{i}. {title} ({source}, {time_pub})\n"
                    if url:
                        headlines_summary += f"   URL: {url}\n"

        summary_prompt = HumanMessage(content=f"""
        Based on all the news headlines collected, provide a CONCISE factual summary of
        the most important news articles relevant to the research query. Cite the sources and provide the links where applicable.
        Focus on facts and observations only - do not provide recommendations or actionable insights.

        Research Query: {research_query}
        {headlines_summary}

        IMPORTANT: Keep the summary brief and focused. Target approximately 1,000-2,000 words maximum.
        Include only the most relevant news articles and key information. Prioritize quality over quantity.

        Note: The tool responses have already been summarized to preserve key information while reducing size.
        Extract the most important insights from these summaries.

        INSUFFICIENT DATA: If you were unable to gather sufficient news (no relevant articles found,
        tool errors, or limited results), do NOT make up information or provide speculative recommendations. Instead:
        - Summarize whatever news you were able to collect, even if minimal
        - Clearly state what information was unavailable or could not be retrieved
        - Present only the facts you have - no recommendations or conclusions beyond the data
        """)

        # Use smaller model for final summarization
        response = await summarization_llm.ainvoke(cleaned_messages + [summary_prompt])
        report_content = response.content or ""

        # Extract structured data for standardized output
        key_findings = extract_key_findings_from_markdown(report_content, max_items=5)
        sentiment = parse_sentiment(report_content)

        # Build sources from collected headlines
        sources = []
        for headline in relevant_headlines[:10]:
            if isinstance(headline, dict):
                source_entry = {
                    "title": headline.get("title", "News Article"),
                    "url": headline.get("url"),
                    "source": headline.get("source_domain", ""),
                }
                if source_entry["url"]:
                    sources.append(source_entry)

        # Build data summary
        data_summary = {
            "headlines_analyzed":
                len(relevant_headlines),
            "time_range":
                "recent",  # Could be computed from headline timestamps
            "sentiment":
                sentiment,
            "top_sources":
                list(
                    set(
                        h.get("source_domain", "") for h in relevant_headlines
                        if isinstance(h, dict) and h.get("source_domain")))[:5],
        }

        # Create standardized output
        standardized = create_standardized_output(research_report=report_content,
                                                  key_findings=key_findings,
                                                  data_summary=data_summary,
                                                  sources=sources,
                                                  status="success" if report_content else "no_data")

        return {
            "messages": [response],
            "summary": report_content,
            "next_step": "complete",
            "key_findings": standardized["key_findings"],
            "data_summary": standardized["data_summary"],
            "sources": standardized["sources"],
        }

    graph.add_node("agent", agent)
    graph.add_node("tools", tools_with_filtering)
    graph.add_node("summarize", summarize)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END})
    graph.add_edge("tools", "summarize")
    graph.add_edge("summarize", END)
    return graph.compile()


def create_news_headlines_agent():
    """
    Synchronous wrapper for creating the news headlines agent.
    Use create_news_headlines_agent_async() in async contexts.
    """
    try:
        loop = asyncio.get_running_loop()
        raise RuntimeError("create_news_headlines_agent() cannot be called from async context. "
                           "Use 'await create_news_headlines_agent_async()' instead.")
    except RuntimeError as e:
        if "no running event loop" in str(e):
            return asyncio.run(create_news_headlines_agent_async())
        raise
