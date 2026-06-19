# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Vendored into the KXTA source-agents layer from the KX "agentic-anomaly-market-research" project
# (faithful copy; imports rewritten and heavy imports made lazy -- no logic changes).
"""
Market Data Agent for getting real-time stock quotes and news from financial APIs.
Fully async implementation with parallel tool execution support.
"""

import asyncio
import json
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from kxta.source_agents._vendor.agents.base import MarketDataAgentState
from kxta.source_agents.streaming import get_event_emitter
from kxta.source_agents._vendor.config import (
    get_research_llm,
    get_summarization_llm,
    MARKET_DATA_MAX_ITERATIONS,
    MARKET_DATA_MIN_ITERATIONS_FOR_COMPLETION,
    MARKET_DATA_SUMMARIZE_INDICATORS_LIMIT,
    MARKET_DATA_SUMMARIZATION_THRESHOLD,
    MARKET_DATA_USE_SIMPLE_EXTRACTION,
    MARKET_DATA_BATCH_SUMMARIZATION,
)
from kxta.source_agents._vendor.config import load_prompt
from kxta.source_agents._vendor.tools.market_data_and_news_tools import get_quote_tool
from kxta.source_agents._vendor.tools.technical_indicators_tools import get_stock_data_tool, get_indicators_tool
from kxta.source_agents._vendor.utils.tool_display import get_tool_display_name
from kxta.source_agents._vendor.report_utils import (
    format_market_data_report,
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
    if tool_name == 'get_quote_tool':
        ticker = tool_args.get('ticker', '')
        if ticker:
            return f"Fetching quote for {ticker}"
        else:
            # Show all args if ticker not found
            args_str = ', '.join([f"{k}={v}" for k, v in tool_args.items()]) if tool_args else "no args"
            return f"Fetching quote ({args_str})"
    elif tool_name == 'get_stock_data_tool':
        ticker = tool_args.get('ticker', '')
        if ticker:
            return f"Fetching stock data for {ticker}"
        else:
            # Show all args if ticker not found
            args_str = ', '.join([f"{k}={v}" for k, v in tool_args.items()]) if tool_args else "no args"
            return f"Fetching stock data ({args_str})"
    elif tool_name == 'get_indicators_tool':
        ticker = tool_args.get('ticker', '')
        indicators = tool_args.get('indicators', [])

        # Build a descriptive message with all available info
        if ticker and indicators:
            indicators_str = ', '.join(indicators)  # Show all indicators
            return f"Calculating {indicators_str} for {ticker}"
        elif ticker:
            return f"Calculating indicators for {ticker}"
        elif indicators:
            indicators_str = ', '.join(indicators)
            return f"Calculating {indicators_str}"
        else:
            # If no args found in expected fields, show all args for debugging
            args_str = ', '.join([f"{k}={v}" for k, v in tool_args.items()]) if tool_args else "no args"
            return f"Calculating indicators ({args_str})"
    else:
        # Generic format for unknown tools - use display name
        display_name = get_tool_display_name(tool_name)
        if tool_args:
            # Try to create a meaningful description from all args
            args_preview = ', '.join([f"{k}={v}" for k, v in tool_args.items()])
            if len(args_preview) > 100:
                args_preview = args_preview[:97] + "..."
            return f"{display_name}: {args_preview}" if args_preview else display_name
        return display_name


def _emit_progress(agent_name: str, current_step: str, preview: dict | None = None) -> None:
    """Emit agent_progress via context-held event emitter, if available."""
    emitter = get_event_emitter()
    if not emitter:
        return
    try:
        emitter.emit_agent_progress_sync(agent_name=agent_name, current_step=current_step, preview=preview or {})
    except Exception as e:
        print(f"[MarketDataAgent] Error emitting progress: {e}")


async def process_tool_response(tool_message: ToolMessage,
                                llm,
                                max_size: int = MARKET_DATA_SUMMARIZATION_THRESHOLD,
                                research_query: str = "") -> ToolMessage:
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

    # Handle Python objects (list/dict) - convert to JSON string first for size checking
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

        # Handle Python objects (list/dict) - already converted to string above
        if isinstance(tool_content, str):
            try:
                parsed_content = json.loads(tool_content)
                # Create a more readable representation for the LLM
                if isinstance(parsed_content, dict):
                    # Extract key metadata
                    symbol = parsed_content.get("symbol", "N/A")
                    if "data" in parsed_content and isinstance(parsed_content.get("data"), list):
                        data_count = len(parsed_content["data"])
                        period = parsed_content.get("period", "N/A")
                        interval = parsed_content.get("interval", "N/A")
                        # Sample first and last few data points for context
                        sample_size = min(5, data_count)
                        sample_data = (parsed_content["data"][:sample_size] +
                                       (parsed_content["data"][-sample_size:] if data_count > sample_size * 2 else []))
                        content_str = json.dumps(
                            {
                                "symbol": symbol,
                                "period": period,
                                "interval": interval,
                                "data_points_count": data_count,
                                "sample_data": sample_data,
                                "full_data_available": True
                            },
                            indent=2)
                    elif "indicators" in parsed_content:
                        indicators = parsed_content["indicators"]
                        indicator_count = len(indicators) if isinstance(indicators, dict) else 0

                        def _simple_indicator_summary(ind_data):
                            if not isinstance(ind_data, dict) or not ind_data:
                                return {"latest": ind_data}

                            dates = sorted(ind_data.keys(), reverse=True)
                            latest_date = dates[0]
                            latest_value = ind_data[latest_date]

                            previous_value = ind_data[dates[1]] if len(dates) >= 2 else None
                            change_pct = None
                            try:
                                if previous_value not in [None, 0]:
                                    change_pct = ((latest_value - previous_value) / previous_value * 100)
                            except Exception:
                                change_pct = None

                            if previous_value is None:
                                trend = "flat"
                            elif latest_value > previous_value:
                                trend = "up"
                            elif latest_value < previous_value:
                                trend = "down"
                            else:
                                trend = "flat"

                            summary = {
                                "latest_date": latest_date,
                                "latest": latest_value,
                                "previous": previous_value,
                                "change_pct": change_pct,
                                "trend": trend,
                            }
                            return summary

                        summarized_indicators = {}
                        summarize_targets = []
                        if isinstance(indicators, dict) and indicator_count > 0:
                            summarize_targets = list(indicators.keys())[:MARKET_DATA_SUMMARIZE_INDICATORS_LIMIT]

                            batched_indicator_summaries = {}
                            if MARKET_DATA_BATCH_SUMMARIZATION and not MARKET_DATA_USE_SIMPLE_EXTRACTION and summarize_targets:
                                try:
                                    # Prepare compact recent samples for batch summarization
                                    compact_indicators = {}
                                    for ind_name in summarize_targets:
                                        ind_data = indicators.get(ind_name, {})
                                        if isinstance(ind_data, dict):
                                            compact_indicators[ind_name] = dict(list(ind_data.items())[-100:])
                                        else:
                                            compact_indicators[ind_name] = ind_data

                                    research_context = f"\n\nRESEARCH CONTEXT: {research_query}" if research_query else ""
                                    batch_prompt = f"""You are summarizing multiple technical indicators for a financial research query.
{research_context}

INDICATOR DATA (recent samples per indicator):
{json.dumps(compact_indicators, indent=2)}

For each indicator, return a JSON object with keys: pattern, key_values, notable_changes.
Respond with a single JSON object mapping indicator name to its summary."""
                                    batch_response = await llm.ainvoke(batch_prompt)
                                    batch_content = batch_response.content if hasattr(
                                        batch_response, "content") else str(batch_response)
                                    try:
                                        batched_indicator_summaries = json.loads(batch_content) if batch_content else {}
                                    except Exception:
                                        batched_indicator_summaries = {}
                                except Exception as e:
                                    print(f"[MarketData] Warning: Failed batch indicator summarization: {e}")

                            for ind_name, ind_data in indicators.items():
                                # Default: simple extraction to avoid heavy LLM usage
                                summary_payload = _simple_indicator_summary(ind_data)

                                should_use_llm = (not MARKET_DATA_USE_SIMPLE_EXTRACTION
                                                  and ind_name in summarize_targets and not batched_indicator_summaries)

                                if ind_name in batched_indicator_summaries:
                                    summary_payload = batched_indicator_summaries.get(ind_name, summary_payload)
                                elif should_use_llm:
                                    try:
                                        # Trim data to most recent 200 points to keep prompt small
                                        if isinstance(ind_data, dict):
                                            recent_items = list(ind_data.items())[-200:]
                                            ind_data_for_prompt = dict(recent_items)
                                        else:
                                            ind_data_for_prompt = ind_data

                                        ind_json = json.dumps({ind_name: ind_data_for_prompt}, indent=2)
                                        research_context = f"\n\nRESEARCH CONTEXT: {research_query}" if research_query else ""
                                        ind_summary_prompt = f"""You are analyzing a technical indicator for a financial research query.

INDICATOR: {ind_name}
{research_context}

INDICATOR DATA (recent sample):
{ind_json}

Summarize briefly:
- Current pattern/trend
- Key recent values (current, previous)
- Notable changes or breakouts
Keep it concise JSON with fields: pattern, key_values, notable_changes."""
                                        ind_summary_response = await llm.ainvoke(ind_summary_prompt)
                                        ind_summary_content = ind_summary_response.content if hasattr(
                                            ind_summary_response, 'content') else str(ind_summary_response)
                                        try:
                                            summary_payload = json.loads(ind_summary_content)
                                        except Exception:
                                            summary_payload = {"summary": ind_summary_content}
                                    except Exception as e:
                                        print(f"[MarketData] Warning: Failed to summarize indicator {ind_name}: {e}")

                                summarized_indicators[ind_name] = summary_payload

                            content_str = json.dumps(
                                {
                                    "symbol":
                                        symbol,
                                    "indicators_count":
                                        indicator_count,
                                    "summarized_indicators":
                                        summarized_indicators,
                                    "note":
                                        f"Summarized up to {MARKET_DATA_SUMMARIZE_INDICATORS_LIMIT} indicators; others use simple extraction"
                                },
                                indent=2)
                        else:
                            content_str = json.dumps(
                                {
                                    "symbol": symbol,
                                    "indicators_count": indicator_count,
                                    "indicators": indicators,
                                    "note": "No indicators to summarize"
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

        # For non-indicator responses, use standard summarization
        # (Indicators are already handled above with individual summarization)
        # Check if we've already processed indicators (content_str will contain "summarized_indicators")
        indicators_already_processed = isinstance(
            parsed_content, dict) and "indicators" in parsed_content and "summarized_indicators" in content_str

        if not indicators_already_processed:
            # Check token count before sending to LLM to prevent API errors
            try:
                import tiktoken
                encoding = tiktoken.get_encoding("cl100k_base")
                content_tokens = len(encoding.encode(content_str))

                # If the content alone is too large, truncate it more aggressively.
                # Threshold derives from the SERVED context window (NIM_MAX_MODEL_LEN,
                # default 32768) — the old hardcoded 150k could never fire against a
                # 32k-context NIM.
                import os as _os
                _ctx_limit = int(_os.getenv("NIM_MAX_MODEL_LEN", "32768") or "32768")
                _token_budget = int(_ctx_limit * 0.75)  # leave room for prompt + output
                if content_tokens > _token_budget:
                    print(f"[MarketData] Warning: Content for {tool_name} is very large "
                          f"({content_tokens:,} tokens > budget {_token_budget:,}), truncating")
                    # For other types, truncate string content
                    max_chars = 50000  # ~12k tokens
                    if len(content_str) > max_chars:
                        content_str = content_str[:max_chars //
                                                  2] + "\n\n[... content truncated ...]\n\n" + content_str[-max_chars //
                                                                                                           2:]
            except ImportError:
                # tiktoken not available, skip token counting
                pass
            except Exception as e:
                print(f"[MarketData] Warning: Error counting tokens: {e}")

            # Create summarization prompt
            research_context = f"\n\nRESEARCH CONTEXT: {research_query}" if research_query else ""
            summary_prompt = f"""You are summarizing a tool response from {tool_name} to reduce token usage while preserving all critical information.
{research_context}

TOOL RESPONSE (may be truncated or sampled):
{content_str}

Create a concise but comprehensive summary that:
1. Preserves all key numerical values (prices, volumes, indicators, etc.)
2. Maintains important metadata (symbols, dates, periods, intervals)
3. Captures trends and patterns if present
4. Keeps the summary in a structured format (preferably JSON if the original was JSON)
5. Is significantly shorter than the original while retaining essential information

If the original was JSON, return a JSON summary. Otherwise, return a structured text summary.
Focus on facts and data - no interpretation or recommendations needed."""

            # Get summary from LLM
            summary_response = await llm.ainvoke(summary_prompt)
            summary_content = summary_response.content if hasattr(summary_response,
                                                                  'content') else str(summary_response)
        else:
            # For indicators, content_str already contains the summarized indicators
            summary_content = content_str

        # Create new ToolMessage with summarized content
        return ToolMessage(content=summary_content,
                           tool_call_id=getattr(tool_message, 'tool_call_id', None),
                           name=tool_name)

    except Exception as e:
        # If summarization fails, fall back to truncation with metadata
        print(f"[MarketData] Warning: Failed to summarize tool response from {tool_name}: {e}")
        # Create a minimal summary with metadata
        # Handle Python objects (list/dict) - convert to JSON string first
        if isinstance(tool_content, (list, dict)):
            tool_content = json.dumps(tool_content)

        if isinstance(tool_content, str):
            try:
                parsed = json.loads(tool_content)
                if isinstance(parsed, dict):
                    if "data" in parsed and isinstance(parsed.get("data"), list):
                        data_count = len(parsed["data"])
                        symbol = parsed.get("symbol", "N/A")
                        fallback_summary = json.dumps({
                            "symbol": symbol,
                            "data_points": data_count,
                            "summary": f"Large dataset with {data_count} data points collected successfully",
                            "note": "Full data available but truncated for token management"
                        })
                    elif "indicators" in parsed:
                        ind_count = len(parsed["indicators"]) if isinstance(parsed["indicators"], dict) else 0
                        # Count total data points across all indicators
                        total_data_points = 0
                        if isinstance(parsed["indicators"], dict):
                            for ind_data in parsed["indicators"].values():
                                if isinstance(ind_data, dict):
                                    total_data_points += len(ind_data)
                        fallback_summary = json.dumps({
                            "symbol":
                                parsed.get("symbol", "N/A"),
                            "indicators_count":
                                ind_count,
                            "total_data_points":
                                total_data_points,
                            "summary":
                                f"Indicator data with {ind_count} indicators ({total_data_points} total data points) collected successfully",
                            "note":
                                "Full data available but truncated for token management"
                        })
                    else:
                        fallback_summary = json.dumps({
                            "summary": "Large tool response collected", "note": "Data truncated for token management"
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


async def create_market_data_agent_async():
    """
    Creates a market data agent for researching market behavior.
    Async implementation with parallel tool execution.

    Returns:
        Compiled LangGraph agent for market data analysis.
    """
    llm = get_research_llm()
    summarization_llm = get_summarization_llm()  # Use smaller model for summarization
    tool_list = [get_quote_tool, get_stock_data_tool, get_indicators_tool]  # Removed get_news_tool
    tool_node = ToolNode(tool_list, handle_tool_errors=True)
    llm_node = llm.bind_tools(tool_list, parallel_tool_calls=True)

    graph = StateGraph(MarketDataAgentState)

    async def agent(state):
        messages = state.get("messages", [])
        research_query = state.get("research_query", "")
        summaries = state.get("summaries", {})
        market_details = state.get("market_details", [])
        next_step = state.get("next_step", "")
        iteration_count = state.get("iteration_count", 0)

        # Prevent infinite loops - max iterations
        if iteration_count >= MARKET_DATA_MAX_ITERATIONS:
            return {
                "messages": [AIMessage(content="RESEARCH COMPLETE: Maximum iterations reached. Summarizing findings.")],
                "next_step": "complete",
                "iteration_count": iteration_count + 1
            }

        system_instructions = load_prompt("market_data.txt")

        context_info = ""
        # Use summaries if available, otherwise mention raw data counts
        if summaries:
            if summaries.get("quote_summary"):
                context_info += f"\n\nMarket Quote: {summaries['quote_summary']}"
            if summaries.get("indicators_summary"):
                context_info += f"\n\nTechnical Indicators: {summaries['indicators_summary']}"
        else:
            if market_details:
                context_info += f"\nYou have already collected market quote data (will be summarized after collection)."

        # Check if we have any data yet
        if not summaries and not market_details and iteration_count > 0:
            context_info += "\n\nWARNING: No data collected yet. You MUST call get_quote_tool to gather information."

        # Clean up messages to prevent token overflow
        # Keep only: system message, initial query, summaries, and last 1 tool_use/tool_result pair (with size limits)
        cleaned_messages = []
        if messages:
            # Keep system message if present
            if messages and isinstance(messages[0], SystemMessage):
                cleaned_messages.append(messages[0])

            # Keep initial human message (research query)
            for msg in messages:
                if isinstance(msg, HumanMessage) and "RESEARCH QUESTION" in str(msg.content):
                    cleaned_messages.append(msg)
                    break

            # If we have summaries, add them as context instead of raw tool results
            if summaries:
                summary_text = "CURRENT FINDINGS:\n"
                if summaries.get("quote_summary"):
                    summary_text += f"Market Quote: {summaries['quote_summary']}\n"
                if summaries.get("indicators_summary"):
                    summary_text += f"Technical Indicators: {summaries['indicators_summary']}"
                # Strip trailing whitespace to avoid Anthropic API error
                cleaned_messages.append(AIMessage(content=summary_text.rstrip()))

            # Keep only the LAST tool_use/tool_result pair (most recent) to prevent token overflow
            # Tool responses should already be summarized by process_tool_response, but check again
            tool_pairs = []
            i = 0
            while i < len(messages):
                msg = messages[i]
                if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls') and msg.tool_calls:
                    # Found a tool_use, collect it and its tool_results
                    pair = [msg]
                    i += 1
                    # Collect corresponding ToolMessages
                    while i < len(messages) and isinstance(messages[i], ToolMessage):
                        tool_msg = messages[i]
                        # If somehow a large tool message got through, summarize it now (using smaller model)
                        tool_content = getattr(tool_msg, 'content', '')
                        if isinstance(tool_content, str) and len(tool_content) > 5000:
                            tool_msg = await process_tool_response(tool_msg,
                                                                   summarization_llm,
                                                                   max_size=5000,
                                                                   research_query=research_query)
                        pair.append(tool_msg)
                        i += 1
                    tool_pairs.append(pair)
                else:
                    i += 1

            # Keep only the LAST tool pair (most recent)
            if tool_pairs:
                cleaned_messages.extend(tool_pairs[-1])

            # Keep the last AI response if it exists and isn't already included
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg not in cleaned_messages:
                    # Check if this is the most recent response
                    if not any(isinstance(m, AIMessage) and m != msg for m in messages[messages.index(msg):]):
                        cleaned_messages.append(msg)
                        break

        if not cleaned_messages:
            message_list = [
                SystemMessage(content=system_instructions + context_info),
                HumanMessage(content="RESEARCH QUESTION: " + research_query)
            ]
            next_step = "research"
        else:
            # Update system message with current context if summaries exist
            message_list = list(cleaned_messages)

            # Update or add system message with current summaries
            if message_list and isinstance(message_list[0], SystemMessage):
                # Update existing system message with current context
                message_list[0] = SystemMessage(
                    content=f"{system_instructions}{context_info}\n\nContinue the research.")
            else:
                # Prepend system message
                message_list.insert(
                    0, SystemMessage(content=f"{system_instructions}{context_info}\n\nContinue the research."))

        # Strip trailing whitespace from all AIMessage content to avoid Anthropic API error
        for i, msg in enumerate(message_list):
            if isinstance(msg, AIMessage) and hasattr(msg, 'content'):
                content = msg.content
                if isinstance(content, str):
                    # Create a new AIMessage with stripped content to avoid modifying the original
                    message_list[i] = AIMessage(content=content.rstrip(),
                                                tool_calls=getattr(msg, 'tool_calls', None),
                                                tool_call_id=getattr(msg, 'tool_call_id', None),
                                                id=getattr(msg, 'id', None),
                                                name=getattr(msg, 'name', None),
                                                additional_kwargs=getattr(msg, 'additional_kwargs', {}))

        response = await llm_node.ainvoke(message_list)

        # Check if response has tool calls - if not and we have no data, encourage tool usage
        has_tool_calls = hasattr(response, 'tool_calls') and response.tool_calls
        if not has_tool_calls and not market_details and iteration_count < 3:
            # Force tool usage if we haven't collected any data
            print(
                f"[MarketData] WARNING: No tool calls in response and no data collected. Response: {getattr(response, 'content', '')[:200]}"
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

        # Strip trailing whitespace from response to avoid future API errors
        if isinstance(response, AIMessage) and hasattr(response, 'content'):
            content = response.content
            if isinstance(content, str) and content.rstrip() != content:
                # Create new response with stripped content
                response = AIMessage(content=content.rstrip(),
                                     tool_calls=getattr(response, 'tool_calls', None),
                                     tool_call_id=getattr(response, 'tool_call_id', None),
                                     id=getattr(response, 'id', None),
                                     name=getattr(response, 'name', None),
                                     additional_kwargs=getattr(response, 'additional_kwargs', {}))

        return {"messages": [response], "next_step": next_step, "iteration_count": iteration_count + 1}

    async def tools_with_tracking(state):
        """Execute tools asynchronously and collect market data (quotes, stock data, indicators)."""
        messages = state.get("messages", [])
        # Emit progress for upcoming tool calls (based on last AI message)
        last_message = messages[-1] if messages else None
        if last_message and hasattr(last_message, "tool_calls") and last_message.tool_calls:
            # Emit each tool call separately with its arguments
            for tool_call in last_message.tool_calls:
                description = _format_tool_call_description(tool_call)
                _emit_progress("market_data", description)

        tool_results = await tool_node.ainvoke(state)
        market_details = state.get("market_details", [])
        research_query = state.get("research_query", "")

        tool_errors = []
        processed_messages = []

        # Process tool results and summarize large ones
        for msg in tool_results.get("messages", []):
            if isinstance(msg, ToolMessage):
                # Process large tool responses with intelligent summarization (using smaller model)
                # Pass research_query so indicators can be summarized with context
                processed_msg = await process_tool_response(
                    msg,
                    summarization_llm,
                    max_size=MARKET_DATA_SUMMARIZATION_THRESHOLD,
                    research_query=research_query,
                )
                processed_messages.append(processed_msg)

                tool_name = getattr(processed_msg, 'name', '')
                tool_content = getattr(processed_msg, 'content', '')

                try:
                    if isinstance(tool_content, str):
                        try:
                            parsed_content = json.loads(tool_content)
                        except (json.JSONDecodeError, TypeError):
                            parsed_content = tool_content
                    else:
                        parsed_content = tool_content

                except Exception as e:
                    parsed_content = tool_content
                    tool_errors.append(f"Error parsing {tool_name}: {str(e)}")

                # Check for errors in tool response
                if isinstance(parsed_content, dict) and "error" in parsed_content:
                    error_msg = parsed_content.get("error", "Unknown error")
                    tool_errors.append(f"{tool_name} error: {error_msg}")
                    continue

                if "get_quote" in tool_name.lower() or "quote" in tool_name.lower():
                    if isinstance(parsed_content, dict) and "error" not in parsed_content:
                        symbol = parsed_content.get("01. symbol") or parsed_content.get("Symbol") or parsed_content.get(
                            "symbol")
                        is_duplicate = any(
                            existing.get("01. symbol") == symbol or existing.get("Symbol") == symbol
                            or existing.get("symbol") == symbol for existing in market_details
                            if isinstance(existing, dict) and symbol)
                        if not is_duplicate:
                            market_details.append(parsed_content)
            else:
                # Keep non-tool messages as-is
                processed_messages.append(msg)

        # Log tool errors if any
        if tool_errors:
            print(f"[MarketData] Tool errors encountered: {tool_errors}")

        # Log what we collected
        if market_details:
            print(f"[MarketData] Collected: {len(market_details)} quotes/market data items")
        elif not tool_errors:
            print(f"[MarketData] WARNING: No data collected from tools, but no errors reported")

        return {
            "messages": processed_messages,  # Use processed messages with summarized tool responses
            "market_details": market_details,
            "next_step": "summarize"  # Go to summarization after collecting data
        }

    def summarize_findings(state):
        """Summarize collected data into key findings and numbers, removing large JSON payloads."""
        market_details = state.get("market_details", [])
        research_query = state.get("research_query", "")
        summaries = state.get("summaries", {})
        messages = state.get("messages", [])

        _emit_progress(
            "market_data",
            "Summarizing market data",
            preview={
                "quotes_collected": len(market_details),
                "has_summaries": bool(summaries),
                "query": research_query[:120],
            },
        )

        # Extract ticker from query or market details
        import re
        ticker_matches = re.findall(r'\b([A-Z]{1,5})\b', research_query)
        ticker = ticker_matches[0] if ticker_matches else ""
        if not ticker and market_details:
            for detail in market_details:
                if isinstance(detail, dict):
                    ticker = detail.get("01. symbol") or detail.get("Symbol") or detail.get("symbol", "")
                    if ticker:
                        break

        # Summarize market quote data
        quote_summary = summaries.get("quote_summary", "")
        if market_details:
            quote_data = []
            for detail in market_details:
                if isinstance(detail, dict) and "error" not in detail:
                    # Extract key numbers only
                    symbol = detail.get("01. symbol") or detail.get("Symbol") or detail.get("symbol", "")
                    price = detail.get("05. price") or detail.get("Price") or detail.get("price", "")
                    change = detail.get("09. change") or detail.get("Change") or detail.get("change", "")
                    change_pct = detail.get("10. change percent") or detail.get("Change Percent") or detail.get(
                        "change_percent", "")
                    volume = detail.get("06. volume") or detail.get("Volume") or detail.get("volume", "")
                    high = detail.get("03. high") or detail.get("High") or detail.get("high", "")
                    low = detail.get("04. low") or detail.get("Low") or detail.get("low", "")

                    quote_data.append({
                        "symbol": symbol,
                        "price": price,
                        "change": change,
                        "change_percent": change_pct,
                        "volume": volume,
                        "high": high,
                        "low": low
                    })

            if quote_data:
                quote_lines = []
                for q in quote_data:
                    volume_val = q.get('volume', 'N/A')
                    volume_str = f"{volume_val:,}" if isinstance(volume_val, (int, float)) else str(volume_val)
                    quote_lines.append(f"{q.get('symbol', 'N/A')}: ${q.get('price', 'N/A')}, "
                                       f"{q.get('change', 'N/A')} ({q.get('change_percent', 'N/A')}), "
                                       f"volume {volume_str}, range ${q.get('low', 'N/A')}-${q.get('high', 'N/A')}")
                quote_summary = " | ".join(quote_lines)

        # Check messages for technical indicators and stock data
        # Tool messages should already be summarized by process_tool_response, so we can process them more easily
        indicators_summary = summaries.get("indicators_summary", "")
        stock_data_summary = ""

        # Process tool messages to extract summaries
        # Since tool responses are already summarized, we can process them more efficiently
        processed_count = 0
        max_tool_messages_to_process = 5  # Limit number of tool messages to process

        for msg in reversed(messages):
            if processed_count >= max_tool_messages_to_process:
                break

            if isinstance(msg, ToolMessage):
                processed_count += 1
                tool_name = getattr(msg, 'name', '')
                tool_content = getattr(msg, 'content', '')

                try:
                    if isinstance(tool_content, str):
                        parsed = json.loads(tool_content)
                    else:
                        parsed = tool_content

                    if isinstance(parsed, dict) and "error" not in parsed:
                        # Process stock data (OHLCV series)
                        # If it's already summarized, it may have a "summary" field or "sample_data"
                        if "data" in parsed and isinstance(parsed.get("data"), list):
                            data_points = parsed["data"]
                            if data_points:
                                # Calculate key statistics from the time series
                                closes = [d.get("close") for d in data_points if d.get("close") is not None]
                                highs = [d.get("high") for d in data_points if d.get("high") is not None]
                                lows = [d.get("low") for d in data_points if d.get("low") is not None]
                                volumes = [d.get("volume") for d in data_points if d.get("volume") is not None]

                                if closes:
                                    latest_close = closes[-1]
                                    first_close = closes[0] if len(closes) > 1 else latest_close
                                    period_change = ((latest_close - first_close) / first_close *
                                                     100) if first_close else 0
                                    max_high = max(highs) if highs else None
                                    min_low = min(lows) if lows else None
                                    avg_volume = sum(volumes) / len(volumes) if volumes else None

                                    symbol = parsed.get("symbol", "N/A")
                                    period = parsed.get("period", "N/A")
                                    interval = parsed.get("interval", "N/A")

                                    stock_data_summary = f"{symbol} ({period}, {interval}): Latest close ${latest_close:.2f}, period change {period_change:+.2f}%, range ${min_low:.2f}-${max_high:.2f}, avg volume {avg_volume:,.0f if avg_volume else 'N/A'}"
                        # If it's a summary with data_points_count, extract that info
                        elif "data_points_count" in parsed:
                            symbol = parsed.get("symbol", "N/A")
                            period = parsed.get("period", "N/A")
                            interval = parsed.get("interval", "N/A")
                            data_count = parsed.get("data_points_count", 0)
                            if parsed.get("sample_data"):
                                sample = parsed["sample_data"]
                                if sample and isinstance(sample, list) and len(sample) > 0:
                                    latest = sample[-1] if sample else {}
                                    latest_close = latest.get("close", "N/A")
                                    stock_data_summary = f"{symbol} ({period}, {interval}): {data_count} data points, latest close ${latest_close}"

                        # Process technical indicators
                        if "summarized_indicators" in parsed:
                            indicator_sentences = []
                            indicators_dict = parsed["summarized_indicators"]

                            if isinstance(indicators_dict, dict):
                                for ind_name, ind_data in indicators_dict.items():
                                    if isinstance(ind_data, dict):
                                        latest = ind_data.get("latest")
                                        trend = ind_data.get("trend", "")
                                        change_pct = ind_data.get("change_pct")
                                        if latest is not None:
                                            if change_pct is not None:
                                                indicator_sentences.append(
                                                    f"{ind_name}: {latest} ({trend}, {change_pct:+.2f}%)")
                                            else:
                                                indicator_sentences.append(f"{ind_name}: {latest} ({trend})")
                                    else:
                                        indicator_sentences.append(f"{ind_name}: {ind_data}")

                            if indicator_sentences:
                                indicators_summary = ". ".join(indicator_sentences[:8])
                                break
                        if "indicators" in parsed:
                            indicator_sentences = []
                            indicators_dict = parsed["indicators"]

                            # Process all indicators (should be manageable since already summarized)
                            for ind_name, ind_data in indicators_dict.items():
                                if isinstance(ind_data, dict) and "error" not in ind_data:
                                    # Get latest value and trend
                                    dates = sorted(ind_data.keys(), reverse=True)
                                    if dates:
                                        latest_date = dates[0]
                                        latest_value = ind_data[latest_date]

                                        # Calculate trend if we have multiple values
                                        if len(dates) >= 2:
                                            prev_value = ind_data[dates[1]]
                                            trend = "↑" if latest_value > prev_value else "↓" if latest_value < prev_value else "→"
                                            change_pct = ((latest_value - prev_value) / prev_value *
                                                          100) if prev_value else 0
                                            indicator_sentences.append(
                                                f"{ind_name}: {latest_value:.2f} {trend} ({change_pct:+.2f}%)")
                                        else:
                                            indicator_sentences.append(f"{ind_name}: {latest_value:.2f}")

                            if indicator_sentences:
                                indicators_summary = ". ".join(
                                    indicator_sentences[:8])  # Limit to 8 indicators for conciseness
                                break
                        # If it's a summary with indicators_count, extract that info
                        elif "indicators_count" in parsed:
                            ind_count = parsed.get("indicators_count", 0)
                            if parsed.get("sample_indicators"):
                                sample_indicators = parsed["sample_indicators"]
                                if sample_indicators and isinstance(sample_indicators, dict):
                                    ind_sentences = []
                                    for ind_name, ind_data in sample_indicators.items():
                                        if isinstance(ind_data, dict):
                                            dates = sorted(ind_data.keys(), reverse=True)
                                            if dates:
                                                latest_value = ind_data[dates[0]]
                                                ind_sentences.append(f"{ind_name}: {latest_value:.2f}")
                                    if ind_sentences:
                                        indicators_summary = f"{ind_count} indicators collected. Sample: {'. '.join(ind_sentences)}"
                except Exception as e:
                    # If parsing fails, skip this message
                    continue

        # Combine stock data and indicators summaries
        if stock_data_summary and indicators_summary:
            indicators_summary = f"{stock_data_summary}. Indicators: {indicators_summary}"
        elif stock_data_summary:
            indicators_summary = stock_data_summary

        # Update summaries
        new_summaries = {"quote_summary": quote_summary, "indicators_summary": indicators_summary}

        # Generate research_report markdown from summaries
        research_report = format_market_data_report(new_summaries, symbol=ticker)

        # Build key_findings from the summary data
        key_findings = []
        if quote_summary:
            key_findings.append(quote_summary)
        if indicators_summary:
            # Split indicators summary into individual findings if too long
            if len(indicators_summary) > 150:
                ind_parts = indicators_summary.split(". ")
                key_findings.extend(ind_parts[:3])  # Add up to 3 indicator findings
            else:
                key_findings.append(indicators_summary)

        # Build data_summary with structured metrics
        data_summary = {
            "symbol": ticker,
            "quotes_collected": len(market_details),
        }

        # Extract specific values from quote if available
        if market_details and isinstance(market_details[0], dict):
            detail = market_details[0]
            price = detail.get("05. price") or detail.get("Price") or detail.get("price")
            change_pct = detail.get("10. change percent") or detail.get("Change Percent") or detail.get(
                "change_percent")
            volume = detail.get("06. volume") or detail.get("Volume") or detail.get("volume")
            if price:
                try:
                    data_summary["price"] = float(price) if isinstance(price, str) else price
                except (ValueError, TypeError):
                    data_summary["price"] = price
            if change_pct:
                data_summary["change_percent"] = change_pct
            if volume:
                try:
                    data_summary["volume"] = int(volume) if isinstance(volume, str) else volume
                except (ValueError, TypeError):
                    data_summary["volume"] = volume

        # Sources for market data
        sources = [{"title": "Alpha Vantage", "url": "https://alphavantage.co"}]

        # Create standardized output
        standardized = create_standardized_output(
            research_report=research_report,
            key_findings=key_findings[:5],  # Max 5 findings
            data_summary=data_summary,
            sources=sources,
            status="success" if (quote_summary or indicators_summary) else "no_data")

        # Clear raw data to save tokens (keep only summaries)
        # But keep a minimal version for reference
        print(f"[MarketData] Summarized findings: Quotes ({len(market_details)} items)")

        # Clean up messages after summarizing to prevent token overflow
        # Keep only: system message, initial query, and summary message (NO tool results)
        cleaned_messages = []
        if messages:
            # Keep system message
            if messages and isinstance(messages[0], SystemMessage):
                cleaned_messages.append(messages[0])

            # Keep initial human message
            for msg in messages:
                if isinstance(msg, HumanMessage) and "RESEARCH QUESTION" in str(msg.content):
                    cleaned_messages.append(msg)
                    break

            # Add a summary message with the findings (this replaces all tool results)
            if quote_summary or indicators_summary:
                summary_text = "SUMMARY OF FINDINGS:\n"
                if quote_summary:
                    summary_text += f"Market Quote: {quote_summary}\n"
                if indicators_summary:
                    summary_text += f"Technical Indicators: {indicators_summary}"
                # Strip trailing whitespace to avoid Anthropic API error
                cleaned_messages.append(AIMessage(content=summary_text.rstrip()))
            else:
                # If no summaries yet, keep minimal context
                cleaned_messages.append(
                    AIMessage(content="Data collection in progress. Continue gathering market data."))

        return {
            "summaries": new_summaries,
            "market_details": market_details[:1] if market_details else [],  # Keep only 1 quote for reference
            "messages": cleaned_messages,  # Return cleaned messages to prevent token overflow
            "next_step": "agent",  # Standardized output fields
            "research_report": standardized["research_report"],
            "key_findings": standardized["key_findings"],
            "data_summary": standardized["data_summary"],
            "sources": standardized["sources"],
        }

    def should_continue(state):
        next_step = state.get("next_step", "")
        messages = state.get("messages", [])
        iteration_count = state.get("iteration_count", 0)
        market_details = state.get("market_details", [])
        summaries = state.get("summaries", {})

        # Force end if max iterations reached
        if iteration_count >= MARKET_DATA_MAX_ITERATIONS:
            return "end"

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

        # If we have data collected (summaries or raw data) and done minimum iterations, we're done
        has_data = summaries.get("quote_summary") or summaries.get("indicators_summary") or market_details
        if has_data and iteration_count >= MARKET_DATA_MIN_ITERATIONS_FOR_COMPLETION:
            return "end"

        # If we've done many iterations with no data and no tool calls, end to prevent infinite loops
        # But allow more attempts if we're still trying to call tools
        if iteration_count >= 10 and not market_details:
            # Check if last message suggests we should continue
            if "error" in content_str.lower() or "retry" in content_str.lower() or "try" in content_str.lower():
                # Agent is trying to handle errors, allow continuation
                if iteration_count < MARKET_DATA_MAX_ITERATIONS:
                    return "end"  # But still end to prevent true infinite loops
            return "end"

        # Default: end (prevents infinite loops)
        return "end"

    def should_summarize_before_end(state):
        """Check if we should summarize before ending."""
        summaries = state.get("summaries", {})
        market_details = state.get("market_details", [])
        messages = state.get("messages", [])

        # Check if we have any tool results in messages that haven't been summarized
        has_tool_results = False
        for msg in messages:
            if hasattr(msg, 'name') and ('tool' in str(type(msg)).lower() or 'ToolMessage' in str(type(msg))):
                has_tool_results = True
                break

        # If we have data (market_details or tool results) but no summaries, summarize first
        if (market_details
                or has_tool_results) and not (summaries.get("quote_summary") or summaries.get("indicators_summary")):
            return "summarize"
        return "end"

    def should_continue_after_summarize(state):
        """After summarizing, decide whether to continue or end."""
        next_step = state.get("next_step", "")
        iteration_count = state.get("iteration_count", 0)
        summaries = state.get("summaries", {})
        market_details = state.get("market_details", [])

        # If we have both quote and indicators summaries, we're done
        if summaries.get("quote_summary") and summaries.get("indicators_summary"):
            return "end"

        # If we have at least one summary and done minimum iterations, end
        if (summaries.get("quote_summary") or
                summaries.get("indicators_summary")) and iteration_count >= MARKET_DATA_MIN_ITERATIONS_FOR_COMPLETION:
            return "end"

        # If we're explicitly done or hit max iterations, end
        if next_step == "complete" or iteration_count >= MARKET_DATA_MAX_ITERATIONS:
            return "end"

        # If we have data but no summaries yet, something went wrong - end to prevent infinite loop
        if market_details and not (summaries.get("quote_summary") or summaries.get("indicators_summary")):
            if iteration_count >= 3:  # Give it a few tries
                return "end"

        # Otherwise, continue with agent (but limit iterations)
        if iteration_count >= 5:  # Limit to 5 iterations max
            return "end"
        return "agent"

    # Pass-through node that just returns state unchanged (used for conditional routing)
    def check_summarize_node(state):
        return state

    graph.add_node("agent", agent)
    graph.add_node("tools", tools_with_tracking)
    graph.add_node("summarize", summarize_findings)
    graph.add_node("check_summarize", check_summarize_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": "check_summarize"})
    graph.add_edge("tools", "summarize")  # After tools, summarize the data
    graph.add_conditional_edges("summarize", should_continue_after_summarize, {"agent": "agent", "end": END})
    graph.add_conditional_edges("check_summarize", should_summarize_before_end, {"summarize": "summarize", "end": END})
    return graph.compile()


def create_market_data_agent():
    """
    Synchronous wrapper for creating the market data agent.
    Use create_market_data_agent_async() in async contexts.
    """
    try:
        loop = asyncio.get_running_loop()
        raise RuntimeError("create_market_data_agent() cannot be called from async context. "
                           "Use 'await create_market_data_agent_async()' instead.")
    except RuntimeError as e:
        if "no running event loop" in str(e):
            return asyncio.run(create_market_data_agent_async())
        raise
