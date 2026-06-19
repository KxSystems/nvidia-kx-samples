# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Vendored into the KXTA source-agents layer from the KX "agentic-anomaly-market-research" project
# (faithful copy; imports rewritten and heavy imports made lazy -- no logic changes).
"""
Web Search Agent for searching the web and scraping articles for news and analysis.
Fully async implementation with parallel tool execution support.
"""

import asyncio
from typing import Sequence, List
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from kxta.source_agents._vendor.agents.base import WebResearchState
from kxta.source_agents._vendor.config import (
    get_research_llm,
    get_summarization_llm,
    get_all_web_tools,
    WEB_SEARCH_MAX_CONTEXT_TOKENS,
    WEB_SEARCH_MAX_ITERATIONS,
    WEB_SEARCH_TOOL_SUMMARIZATION_THRESHOLD,
    WEB_SEARCH_KEEP_RECENT_ITERATIONS,
)
from kxta.source_agents._vendor.config import load_prompt_template
from kxta.source_agents.streaming import get_event_emitter
from kxta.source_agents._vendor.utils.tool_display import get_tool_display_name
from kxta.source_agents._vendor.report_utils import (
    extract_key_findings_from_markdown,
    extract_sources_from_markdown,
    parse_sentiment,
    create_standardized_output,
)

try:
    import tiktoken
except ImportError:
    tiktoken = None


def _format_tool_call_description(tool_call) -> str:
    """Format a tool call with its arguments for display."""
    if isinstance(tool_call, dict):
        tool_name = tool_call.get('name', 'unknown')
        tool_args = tool_call.get('args', {})
    else:
        tool_name = getattr(tool_call, 'name', 'unknown')
        tool_args = getattr(tool_call, 'args', {})

    if tool_name == 'firecrawl_search':
        query = tool_args.get('query', '')
        return f"Searching web: {query}" if query else "Searching web"
    elif tool_name == 'firecrawl_scrape':
        url = tool_args.get('url', '')
        return f"Scraping article: {url[:60]}..." if url else "Scraping article"
    else:
        display_name = get_tool_display_name(tool_name)
        if tool_args:
            first_arg = next(iter(tool_args.values()), '')
            if isinstance(first_arg, str) and first_arg:
                return f"{display_name}: {first_arg[:60]}"
        return display_name


def _emit_progress(current_step: str, preview: dict | None = None) -> None:
    """Emit progress event for web search agent."""
    emitter = get_event_emitter()
    if not emitter:
        return
    try:
        emitter.emit_agent_progress_sync(agent_name="web_search", current_step=current_step, preview=preview or {})
    except Exception as e:
        print(f"[WebSearchAgent] Error emitting progress: {e}")


def _approx_token_count(text: str) -> int:
    """Approximate token count; prefer tiktoken when available."""
    if not text:
        return 0
    if tiktoken:
        try:
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except Exception:
            pass
    return max(1, len(text) // 4)


def _messages_token_count(messages: Sequence) -> int:
    """Count approximate tokens across all messages."""
    total = 0
    for msg in messages or []:
        content = getattr(msg, "content", "")
        if isinstance(content, list):
            content = " ".join(str(part) for part in content)
        total += _approx_token_count(str(content))
    return total


def _compress_messages_if_needed(
    messages: Sequence,
    summarization_llm,
    max_tokens: int = WEB_SEARCH_MAX_CONTEXT_TOKENS,
    keep_recent: int = WEB_SEARCH_KEEP_RECENT_ITERATIONS,
) -> List:
    """Compress older messages to stay within token limits while preserving recent tool iterations."""
    if not messages:
        return []

    token_count = _messages_token_count(messages)
    if token_count <= max_tokens:
        return list(messages)

    print(f"[WebSearch] Context compression triggered: {token_count} tokens > {max_tokens} limit")

    # Keep recent tool iterations from the end (as paired AI+ToolMessage units)
    tail = []
    tool_pairs_kept = 0
    consumed = set()
    for idx in range(len(messages) - 1, -1, -1):
        if idx in consumed:
            continue
        msg = messages[idx]
        if isinstance(msg, ToolMessage):
            pair = [msg]
            prev_idx = idx - 1
            if prev_idx >= 0:
                prev_msg = messages[prev_idx]
                if isinstance(prev_msg, AIMessage) and getattr(prev_msg, "tool_calls", None):
                    pair.insert(0, prev_msg)
                    consumed.add(prev_idx)
            tail = pair + tail
            consumed.add(idx)
            tool_pairs_kept += 1
            if tool_pairs_kept >= keep_recent:
                break
            continue
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            if idx + 1 < len(messages) and (idx + 1) in consumed:
                consumed.add(idx)
                continue
        tail.insert(0, msg)
        consumed.add(idx)
        if tool_pairs_kept >= keep_recent and len(tail) >= keep_recent * 2:
            break

    older_messages = [m for i, m in enumerate(messages) if i not in consumed]

    summary_message = None
    if older_messages:
        older_text_parts = []
        for msg in older_messages:
            content = getattr(msg, "content", "")
            if isinstance(content, list):
                content = " ".join(str(part) for part in content)
            older_text_parts.append(str(content))
        combined_text = "\n\n".join(older_text_parts)
        summary_prompt = f"""You are compressing previous web research findings to keep context small.

PRIOR FINDINGS (compressed input):
{combined_text[:6000]}

Create a concise bullet summary that preserves key facts, URLs, data points, and sources.
Keep it short; avoid repetition."""
        try:
            summary_resp = summarization_llm.invoke(summary_prompt)
            summary_content = getattr(summary_resp, "content", "") or str(summary_resp)
            summary_message = HumanMessage(content=f"Previous research summary:\n{summary_content}")
        except Exception as e:
            print(f"[WebSearch] Warning: failed to compress older messages: {e}")
            summary_message = HumanMessage(content="Previous research summary: (compression failed)")

    new_messages = []
    if summary_message:
        new_messages.append(summary_message)
    new_messages.extend(tail)

    new_count = _messages_token_count(new_messages)
    print(
        f"[WebSearch] Compressed {token_count} -> {new_count} tokens ({len(messages)} -> {len(new_messages)} messages)")
    return new_messages


async def _summarize_tool_response(content: str, tool_name: str, summarization_llm) -> str:
    """Summarize a large tool response to reduce token usage."""
    summary_prompt = f"""Summarize this {tool_name} response, preserving all key facts, data points, URLs, and quotes.
Be concise but do not drop important information.

CONTENT:
{content[:8000]}"""
    try:
        response = await summarization_llm.ainvoke(summary_prompt)
        summary = getattr(response, "content", "") or str(response)
        print(f"[WebSearch] Summarized {tool_name} response: {len(content)} -> {len(summary)} chars")
        return summary
    except Exception as e:
        print(f"[WebSearch] Tool summarization failed for {tool_name}: {e}")
        return content[:8000] + "\n\n[Content truncated due to length]"


async def create_web_search_agent_async():
    """
    Creates a web search agent for researching market information.
    Async implementation with parallel tool execution.

    Returns:
        Compiled LangGraph agent for web search and research.
    """
    llm = get_research_llm()
    summarization_llm = get_summarization_llm()
    all_tools = get_all_web_tools()
    llm_with_tools = llm.bind_tools(all_tools, parallel_tool_calls=True)
    tool_node = ToolNode(all_tools, handle_tool_errors=True)

    graph = StateGraph(WebResearchState)

    async def agent(state):
        """Main agent node - decides what tools to call."""
        query = state.get("query", "")
        messages = state.get("messages", [])
        iteration = state.get("iteration_count", 0)
        system_instructions = load_prompt_template("web_search.txt", iteration=iteration)

        if not messages:
            full_query = f"{system_instructions}\n\nRESEARCH QUESTION: {query}"
            message_list = [HumanMessage(content=full_query)]
        else:
            compressed = _compress_messages_if_needed(
                messages,
                summarization_llm,
                max_tokens=WEB_SEARCH_MAX_CONTEXT_TOKENS,
                keep_recent=WEB_SEARCH_KEEP_RECENT_ITERATIONS,
            )
            # History first so LLM sees its prior work, then the continue nudge
            message_list = list(compressed)
            message_list.append(
                HumanMessage(content=f"{system_instructions}\n\nContinue the research based on the results above."))

        response = await llm_with_tools.ainvoke(message_list)
        return {"messages": [response], "iteration_count": iteration + 1}

    async def tools_with_tracking(state):
        """Execute tools asynchronously with progress tracking."""
        messages = state.get("messages", [])

        # Emit planned tool usage
        last_message = messages[-1] if messages else None
        if last_message and hasattr(last_message, "tool_calls") and last_message.tool_calls:
            for tool_call in last_message.tool_calls:
                description = _format_tool_call_description(tool_call)
                _emit_progress(description)

        try:
            tool_results = await tool_node.ainvoke(state)
        except Exception as e:
            print(f"[WebSearch] Tool execution error: {e}")
            error_message = str(e)

            tool_messages = []
            new_findings = []
            iteration = state.get("iteration_count", 0)

            if messages:
                last_message = messages[-1]
                if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
                    for tool_call in last_message.tool_calls:
                        if isinstance(tool_call, dict):
                            tool_name = tool_call.get('name', 'unknown')
                            tool_args = tool_call.get('args', {})
                            tool_id = tool_call.get('id', 'error')
                        else:
                            tool_name = getattr(tool_call, 'name', 'unknown')
                            tool_args = getattr(tool_call, 'args', {})
                            tool_id = getattr(tool_call, 'id', 'error')

                        new_findings.append({
                            "tool": tool_name,
                            "query": tool_args,
                            "iteration": iteration,
                            "status": "error",
                            "error": str(error_message)[:200]
                        })

                        tool_msg = ToolMessage(
                            content=
                            f"Error: {error_message}. The tool '{tool_name}' failed. Please try a different approach.",
                            tool_call_id=tool_id,
                            name=tool_name)
                        tool_messages.append(tool_msg)

            existing_findings = state.get("findings", [])
            return {"messages": tool_messages if tool_messages else [], "findings": existing_findings + new_findings}

        if not messages:
            return tool_results

        # Summarize large tool responses to prevent token overflow
        result_messages = tool_results.get("messages", [])
        summarized_messages = []
        for msg in result_messages:
            if isinstance(msg, ToolMessage):
                content = getattr(msg, "content", "")
                if isinstance(content, str) and _approx_token_count(content) > WEB_SEARCH_TOOL_SUMMARIZATION_THRESHOLD:
                    tool_name = getattr(msg, "name", "unknown")
                    summarized_content = await _summarize_tool_response(content, tool_name, summarization_llm)
                    summarized_messages.append(
                        ToolMessage(
                            content=summarized_content,
                            tool_call_id=msg.tool_call_id,
                            name=getattr(msg, "name", None),
                        ))
                else:
                    summarized_messages.append(msg)
            else:
                summarized_messages.append(msg)

        last_message = messages[-1]
        new_findings = []
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            for tool_call in last_message.tool_calls:
                if isinstance(tool_call, dict):
                    tool_name = tool_call.get('name', 'unknown')
                    tool_args = tool_call.get('args', {})
                else:
                    tool_name = getattr(tool_call, 'name', 'unknown')
                    tool_args = getattr(tool_call, 'args', {})
                finding = {"tool": tool_name, "query": tool_args, "iteration": state.get("iteration_count", 0)}
                new_findings.append(finding)

        existing_findings = state.get("findings", [])
        return {"messages": summarized_messages, "findings": existing_findings + new_findings}

    def should_continue(state):
        """Determine next step based on agent response."""
        messages = state.get("messages", [])
        iteration = state.get("iteration_count", 0)

        if not messages:
            return "end"

        last_message = messages[-1]
        if hasattr(last_message, 'content') and last_message.content:
            if isinstance(last_message.content, str):
                content = last_message.content.upper()
                if "RESEARCH COMPLETE" in content:
                    return "summarize"
            elif isinstance(last_message.content, list):
                content_str = str(last_message.content).upper()
                if "RESEARCH COMPLETE" in content_str:
                    return "summarize"

        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            if iteration >= WEB_SEARCH_MAX_ITERATIONS:
                return "summarize"
            return "tools"

        return "summarize"

    async def summarize(state):
        """Generate final research report."""
        query = state.get("query", "")
        findings = state.get("findings", [])
        messages = state.get("messages", [])

        _emit_progress(
            "Summarizing web search findings",
            preview={
                "sources_found": len(findings), "query": query[:120]
            },
        )

        findings_summary = "\n".join([f"- Used {f['tool']} (iteration {f['iteration']})" for f in findings])
        research_notes = []
        for msg in messages:
            if not (hasattr(msg, 'content') and msg.content and hasattr(msg, 'type')):
                continue
            content = msg.content
            if isinstance(content, list):
                content = " ".join(str(part) for part in content)
            else:
                content = str(content)
            if msg.type == "ai":
                research_notes.append(content)
            elif msg.type == "tool":
                tool_name = getattr(msg, 'name', 'tool')
                research_notes.append(f"[{tool_name} result]: {content}")

        research_notes_str = "\n".join(str(note) for note in research_notes)
        summary_prompt = f"""You are creating a final research report.

ORIGINAL QUERY: {query}

RESEARCH PROCESS:
{findings_summary}

RESEARCH NOTES AND FINDINGS:
{research_notes_str}

Create a comprehensive, well-structured report with:

1. EXECUTIVE SUMMARY
2. KEY FINDINGS
3. DETAILED ANALYSIS
4. SOURCES CONSULTED
5. KEY FINDINGS SUMMARY

Format with clear headers and bullet points for readability.
Be specific and fact-based, citing what you learned from your research.
Focus on facts and findings only - do not provide recommendations or actionable insights.

INSUFFICIENT DATA: If you were unable to gather sufficient information (limited search results,
tool errors, or no relevant findings), do NOT make up information or provide speculative recommendations. Instead:
- Summarize whatever data you were able to collect, even if minimal
- Clearly state what information was unavailable or could not be retrieved
- Present only the facts you have - no recommendations or conclusions beyond the data
"""
        response = await llm.ainvoke(summary_prompt)
        report_content = response.content or ""

        # Extract structured data for standardized output
        key_findings = extract_key_findings_from_markdown(report_content, max_items=5)
        sources = extract_sources_from_markdown(report_content)
        sentiment = parse_sentiment(report_content)

        # Build data summary
        data_summary = {
            "articles_analyzed": len(findings),
            "sentiment": sentiment,
            "iterations": state.get("iteration_count", 0),
        }

        # Create standardized output
        standardized = create_standardized_output(research_report=report_content,
                                                  key_findings=key_findings,
                                                  data_summary=data_summary,
                                                  sources=sources,
                                                  status="success" if report_content else "no_data")

        return {
            "final_report": report_content,
            "key_findings": standardized["key_findings"],
            "data_summary": standardized["data_summary"],
            "sources": standardized["sources"],
        }

    graph.add_node("agent", agent)
    graph.add_node("tools", tools_with_tracking)
    graph.add_node("summarize", summarize)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent",
                                should_continue, {
                                    "tools": "tools", "summarize": "summarize", "end": "summarize"
                                })
    graph.add_edge("tools", "agent")
    graph.add_edge("summarize", END)
    return graph.compile()


def create_web_search_agent():
    """
    Synchronous wrapper for creating the web search agent.
    Use create_web_search_agent_async() in async contexts.
    """
    try:
        loop = asyncio.get_running_loop()
        raise RuntimeError("create_web_search_agent() cannot be called from async context. "
                           "Use 'await create_web_search_agent_async()' instead.")
    except RuntimeError as e:
        if "no running event loop" in str(e):
            return asyncio.run(create_web_search_agent_async())
        raise
