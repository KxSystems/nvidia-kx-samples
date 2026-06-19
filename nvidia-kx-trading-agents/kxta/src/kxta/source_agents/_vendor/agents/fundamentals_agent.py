# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Vendored into the KXTA source-agents layer from the KX "agentic-anomaly-market-research" project
# (faithful copy; imports rewritten and heavy imports made lazy -- no logic changes).
"""
Fundamentals Agent for company financials, valuation, earnings, dividends, and analyst data.
Fully async implementation with parallel tool execution support.
"""

import asyncio
import json
import re
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from kxta.source_agents._vendor.agents.base import FundamentalsAgentState
from kxta.source_agents.streaming import get_event_emitter
from kxta.source_agents._vendor.config import (
    get_research_llm,
    get_summarization_llm,
    FUNDAMENTALS_MAX_ITERATIONS,
    FUNDAMENTALS_MIN_ITERATIONS_FOR_COMPLETION,
    FUNDAMENTALS_SUMMARIZATION_THRESHOLD,
)
from kxta.source_agents._vendor.config import load_prompt
from kxta.source_agents._vendor.tools.fundamental_tools import (
    get_company_overview_tool,
    get_financial_statements_tool,
    get_valuation_ratios_tool,
    get_earnings_data_tool,
    get_dividend_data_tool,
    get_analyst_ratings_tool,
)
from kxta.source_agents._vendor.utils.tool_display import get_tool_display_name
from kxta.source_agents._vendor.report_utils import (
    format_fundamentals_report,
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
    ticker = tool_args.get('ticker', '')

    if tool_name == 'get_company_overview_tool':
        return f"Fetching company overview for {ticker}" if ticker else "Fetching company overview"
    elif tool_name == 'get_financial_statements_tool':
        return f"Fetching financial statements for {ticker}" if ticker else "Fetching financial statements"
    elif tool_name == 'get_valuation_ratios_tool':
        return f"Fetching valuation ratios for {ticker}" if ticker else "Fetching valuation ratios"
    elif tool_name == 'get_earnings_data_tool':
        return f"Fetching earnings data for {ticker}" if ticker else "Fetching earnings data"
    elif tool_name == 'get_dividend_data_tool':
        return f"Fetching dividend data for {ticker}" if ticker else "Fetching dividend data"
    elif tool_name == 'get_analyst_ratings_tool':
        return f"Fetching analyst ratings for {ticker}" if ticker else "Fetching analyst ratings"
    else:
        # Generic format for unknown tools - use display name
        display_name = get_tool_display_name(tool_name)
        if tool_args:
            first_arg = next(iter(tool_args.values()), '')
            if isinstance(first_arg, str) and first_arg:
                return f"{display_name}: {first_arg[:60]}"
        return display_name


def _emit_progress(agent_name: str, current_step: str, preview: dict | None = None) -> None:
    """Emit agent_progress via context-held event emitter, if available."""
    emitter = get_event_emitter()
    if not emitter:
        return
    try:
        emitter.emit_agent_progress_sync(agent_name=agent_name, current_step=current_step, preview=preview or {})
    except Exception as e:
        print(f"[FundamentalsAgent] Error emitting progress: {e}")


async def _summarize_tool_message(tool_message: ToolMessage,
                                  llm,
                                  max_size: int,
                                  research_query: str = "") -> ToolMessage:
    """Summarize large tool responses to keep context manageable."""
    tool_content = getattr(tool_message, "content", "")
    tool_name = getattr(tool_message, "name", "")

    if isinstance(tool_content, (list, dict)):
        try:
            tool_content = json.dumps(tool_content)
        except Exception:
            tool_content = str(tool_content)

    if not isinstance(tool_content, str) or len(tool_content) <= max_size:
        return tool_message

    # Truncate extremely large content before summarization
    content_for_prompt = tool_content
    if len(content_for_prompt) > max_size * 4:
        content_for_prompt = content_for_prompt[:max_size *
                                                2] + "\n\n[... truncated ...]\n\n" + content_for_prompt[-max_size:]

    research_context = f"\n\nRESEARCH CONTEXT: {research_query}" if research_query else ""
    prompt = f"""You are summarizing a tool response from {tool_name} to reduce token usage while preserving key financial facts.
{research_context}

TOOL RESPONSE (may be truncated):
{content_for_prompt}

Create a concise structured summary that keeps:
- Key numerical values (revenues, EPS, margins, ratios)
- Important metadata (periods, currency, units)
- Major trends (growth/decline) if present
Prefer JSON if the source was JSON-like."""

    try:
        summary_response = await llm.ainvoke(prompt)
        summary_content = summary_response.content if hasattr(summary_response, "content") else str(summary_response)
    except Exception as e:
        print(f"[FundamentalsAgent] Summarization failed for {tool_name}: {e}")
        summary_content = content_for_prompt[:max_size] + "... [truncated]"

    return ToolMessage(
        content=summary_content,
        tool_call_id=getattr(tool_message, "tool_call_id", None),
        name=tool_name,
    )


async def create_fundamentals_agent_async():
    """
    Creates a fundamentals agent for researching company financials and valuation.
    Async implementation with parallel tool execution.

    Returns:
        Compiled LangGraph agent for fundamental analysis.
    """
    llm = get_research_llm()
    summarization_llm = get_summarization_llm()
    tool_list = [
        get_company_overview_tool,
        get_financial_statements_tool,
        get_valuation_ratios_tool,
        get_earnings_data_tool,
        get_dividend_data_tool,
        get_analyst_ratings_tool,
    ]
    tool_node = ToolNode(tool_list, handle_tool_errors=True)
    llm_node = llm.bind_tools(tool_list, parallel_tool_calls=True)

    graph = StateGraph(FundamentalsAgentState)

    async def agent(state):
        messages = state.get("messages", [])
        research_query = state.get("research_query", "")
        summaries = state.get("summaries", {})
        fundamental_data = state.get("fundamental_data", [])
        next_step = state.get("next_step", "")
        iteration_count = state.get("iteration_count", 0)

        if iteration_count >= FUNDAMENTALS_MAX_ITERATIONS:
            return {
                "messages": [AIMessage(content="RESEARCH COMPLETE: Maximum iterations reached. Summarizing findings.")],
                "next_step": "summarize" if fundamental_data else "end",
                "iteration_count": iteration_count + 1,
            }

        system_instructions = load_prompt("fundamentals.txt")

        # Build context about what tools have been called by inspecting message history
        tools_called = set()
        for msg in messages:
            if isinstance(msg, ToolMessage):
                tool_name = getattr(msg, "name", "")
                if tool_name:
                    tools_called.add(tool_name)

        all_tools = {
            "get_company_overview_tool": "overview",
            "get_financial_statements_tool": "financials",
            "get_valuation_ratios_tool": "valuation",
            "get_earnings_data_tool": "earnings",
            "get_dividend_data_tool": "dividends",
            "get_analyst_ratings_tool": "analysts",
        }
        tools_missing = [name for name in all_tools if name not in tools_called]

        context_info = ""
        if tools_called:
            context_info += f"\n\nTOOLS ALREADY CALLED: {', '.join(tools_called)}"
        if tools_missing:
            context_info += f"\nTOOLS NOT YET CALLED: {', '.join(tools_missing)}"
            context_info += "\nCall the missing tools to gather complete fundamentals data."
        else:
            context_info += "\nAll tools have been called. Review the data and say RESEARCH COMPLETE if satisfied."

        # Build message list: keep full history but ensure system message is first
        if not messages:
            # First iteration: create initial messages
            message_list = [
                SystemMessage(content=system_instructions + context_info),
                HumanMessage(content="RESEARCH QUESTION: " + research_query),
            ]
            print(f"[FundamentalsAgent] First iteration, starting fresh. Missing tools: {tools_missing}")
        else:
            # Subsequent iterations: keep full history, update system message
            message_list = []
            # Add/update system message at start
            message_list.append(SystemMessage(content=system_instructions + context_info))

            # Add all non-system messages from history
            for msg in messages:
                if isinstance(msg, SystemMessage):
                    continue  # Skip old system messages, we added fresh one above
                message_list.append(msg)

            # Ensure we have the research question
            has_research_q = any(
                isinstance(m, HumanMessage) and "RESEARCH QUESTION" in str(getattr(m, "content", ""))
                for m in message_list)
            if not has_research_q:
                message_list.insert(1, HumanMessage(content="RESEARCH QUESTION: " + research_query))

            print(
                f"[FundamentalsAgent] Iteration {iteration_count + 1}, {len(message_list)} messages, tools_called={tools_called}, tools_missing={tools_missing}"
            )

        response = await llm_node.ainvoke(message_list)
        has_tool_calls = hasattr(response, "tool_calls") and response.tool_calls
        content = getattr(response, "content", "")
        content_str = " ".join(str(item) for item in content) if isinstance(content, list) else str(content)

        if has_tool_calls:
            tool_names = [
                tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "") for tc in response.tool_calls
            ]
            print(f"[FundamentalsAgent] LLM requested tools: {tool_names}")

        if "RESEARCH COMPLETE" in content_str.upper():
            next_step = "summarize" if fundamental_data else "end"
        elif has_tool_calls:
            next_step = "tools"
        elif fundamental_data:
            # We have some data but no new tool calls; move to summarize
            next_step = "summarize"
        else:
            print("[FundamentalsAgent] Warning: No tool calls and no data collected yet.")
            next_step = "end"

        return {
            "messages": [response],
            "next_step": next_step,
            "iteration_count": iteration_count + 1,
        }

    async def tools_with_tracking(state):
        messages = state.get("messages", [])
        research_query = state.get("research_query", "")
        fundamental_data = state.get("fundamental_data", [])

        last_message = messages[-1] if messages else None
        if last_message and hasattr(last_message, "tool_calls") and last_message.tool_calls:
            # Emit each tool call separately with its arguments
            for tool_call in last_message.tool_calls:
                description = _format_tool_call_description(tool_call)
                _emit_progress("fundamentals", description)
        else:
            print("[FundamentalsAgent] No planned tools in last message; tool phase still invoked.")

        tool_results = await tool_node.ainvoke(state)
        processed_messages = []

        for msg in tool_results.get("messages", []):
            if isinstance(msg, ToolMessage):
                tool_name = getattr(msg, "name", "")
                print(f"[FundamentalsAgent] Tool returned: {tool_name}")

                # Parse structured data from ORIGINAL tool content before
                # summarization so the LLM summary can't destroy the JSON.
                raw_content = getattr(msg, "content", "")
                try:
                    if isinstance(raw_content, str):
                        parsed = json.loads(raw_content) if raw_content else {}
                    else:
                        parsed = raw_content
                except Exception as e:
                    print(f"[FundamentalsAgent] JSON parse failed for {tool_name}: {e}")
                    parsed = {"_raw_content": raw_content, "_tool": tool_name}

                if isinstance(parsed, dict):
                    if "error" in parsed:
                        print(f"[FundamentalsAgent] Tool {tool_name} returned error: {parsed.get('error')}")
                    else:
                        parsed["_tool"] = tool_name
                        fundamental_data.append(parsed)
                        print(
                            f"[FundamentalsAgent] Parsed dict added from {tool_name}. Keys: {list(parsed.keys())[:8]}")
                else:
                    print(f"[FundamentalsAgent] Skipping non-dict content from {tool_name}: {type(parsed)}")

                # Summarize for message history (LLM context window management).
                # Data extraction already done above from the original content.
                processed_msg = await _summarize_tool_message(
                    msg,
                    summarization_llm,
                    max_size=FUNDAMENTALS_SUMMARIZATION_THRESHOLD,
                    research_query=research_query,
                )
                processed_messages.append(processed_msg)
            else:
                processed_messages.append(msg)

        if fundamental_data:
            _emit_progress(
                "fundamentals",
                "Collected fundamental data",
                {
                    "items": len(fundamental_data), "query": research_query[:120]
                },
            )
        else:
            print("[FundamentalsAgent] No fundamental_data collected after tools.")

        # Return to agent to decide next step (more tools or summarize)
        return {
            "messages": processed_messages,
            "fundamental_data": fundamental_data,
            "next_step": "agent",
        }

    async def summarize_findings(state):
        fundamental_data = state.get("fundamental_data", [])
        research_query = state.get("research_query", "")
        summaries = state.get("summaries", {}) or {}
        messages = state.get("messages", [])

        _emit_progress(
            "fundamentals",
            "Summarizing fundamental data",
            {
                "items": len(fundamental_data), "query": research_query[:120]
            },
        )

        # Deterministic extraction to avoid losing structured data in LLM summarization
        overview = {}
        financials = {}
        valuation = {}
        earnings = {}
        dividends = {}
        analysts = {}

        def _first(lst):
            return lst[0] if isinstance(lst, list) and lst else None

        for item in fundamental_data:
            if not isinstance(item, dict):
                continue
            if "sector" in item or "industry" in item:
                overview = {
                    "sector": item.get("sector"),
                    "industry": item.get("industry"),
                    "market_cap": item.get("market_cap"),
                    "beta": item.get("beta"),
                    "shares_outstanding": item.get("shares_outstanding"),
                    "employees": item.get("employees"),
                }
            if "income_statement" in item or item.get("_tool") == "get_financial_statements_tool":
                inc = _first(item.get("income_statement"))
                if isinstance(inc, dict):
                    financials = {
                        "revenue":
                            inc.get("Total Revenue") or inc.get("totalRevenue") or inc.get("Operating Revenue"),
                        "net_income":
                            inc.get("Net Income") or inc.get("netIncome") or inc.get("Net Income Common Stockholders"),
                        "ebitda":
                            inc.get("EBITDA") or inc.get("ebitda") or inc.get("Normalized EBITDA"),
                        "period":
                            inc.get("period"),
                    }
                elif "_raw_content" in item:
                    # Fallback: store raw content summary
                    financials = {"_raw": item.get("_raw_content", "")[:500]}
            if "pe" in item or "pb" in item:
                valuation = {
                    "pe": item.get("pe"),
                    "forward_pe": item.get("forward_pe"),
                    "pb": item.get("pb"),
                    "ps": item.get("ps"),
                    "ev_to_ebitda": item.get("ev_to_ebitda"),
                    "peg": item.get("peg"),
                    "market_cap": item.get("market_cap"),
                    "enterprise_value": item.get("enterprise_value"),
                }
            if "annual_eps" in item or "quarterly_eps" in item:
                annual = _first(item.get("annual_eps"))
                quarterly = _first(item.get("quarterly_eps"))
                earnings = {
                    "annual_eps_latest": annual,
                    "quarterly_eps_latest": quarterly,
                    "next_earnings_date": item.get("next_earnings_date"),
                }
            if "dividend_yield" in item or "dividend_history" in item:
                dividends = {
                    "dividend_yield": item.get("dividend_yield"),
                    "dividend_rate": item.get("dividend_rate"),
                    "payout_ratio": item.get("payout_ratio"),
                    "ex_dividend_date": item.get("ex_dividend_date"),
                    "dividend_history": item.get("dividend_history"),
                }
            if "ratings_summary" in item or "latest_notes" in item:
                analysts = {
                    "ratings_summary": item.get("ratings_summary"),
                    "latest_notes": item.get("latest_notes"),
                    "target_price": item.get("target_price"),
                }

        new_summaries = {
            "overview": overview,
            "financials": financials,
            "valuation": valuation,
            "earnings": earnings,
            "dividends": dividends,
            "analysts": analysts,
        }
        # Preserve any prior summaries that were already present
        new_summaries.update({k: v for k, v in summaries.items() if k not in new_summaries or not new_summaries[k]})

        print(
            f"[FundamentalsAgent] Summary assembly -> overview={bool(overview)}, financials={bool(financials)}, valuation={bool(valuation)}, earnings={bool(earnings)}, dividends={bool(dividends)}, analysts={bool(analysts)}"
        )

        # Concise LLM summary for final report (facts only, no recs)
        concise_prompt = (
            "You are producing a very concise factual summary of fundamentals.\n\n"
            f"DATA:\n{json.dumps(new_summaries, indent=2)[:6000]}\n\n"
            "Write 3-6 bullets. Each bullet: a key fact with numbers. No recommendations, no filler, no repetition. "
            "Keep under 80 words total.")
        concise_report = None
        try:
            concise_resp = await summarization_llm.ainvoke(concise_prompt)
            concise_report = concise_resp.content if hasattr(concise_resp, "content") else str(concise_resp)
        except Exception as e:
            print(f"[FundamentalsAgent] concise summary failed: {e}")

        if concise_report:
            new_summaries["report"] = concise_report

        # Extract tickers from query
        ticker_matches = re.findall(r'\b([A-Z]{1,5})\b', research_query)
        tickers = ticker_matches[:5] if ticker_matches else []
        ticker = ", ".join(tickers) if tickers else ""

        # Generate research_report markdown from summaries
        research_report = format_fundamentals_report(new_summaries, symbol=ticker)

        # Build key_findings from concise report or summaries
        key_findings = []
        if concise_report:
            # Extract bullet points from concise report
            lines = concise_report.strip().split('\n')
            for line in lines:
                line = line.strip()
                if line.startswith('-') or line.startswith('•') or line.startswith('*'):
                    finding = line.lstrip('-•* ').strip()
                    if finding and len(finding) > 10:
                        key_findings.append(finding)

        # If no findings extracted, build from summaries
        if not key_findings:
            if valuation.get("pe"):
                key_findings.append(f"P/E ratio: {valuation.get('pe')}")
            if valuation.get("market_cap"):
                key_findings.append(f"Market cap: {valuation.get('market_cap')}")
            if analysts.get("ratings_summary"):
                key_findings.append(f"Analyst ratings: {analysts.get('ratings_summary')}")
            if financials.get("revenue"):
                key_findings.append(f"Revenue: {financials.get('revenue')}")

        # Build data_summary from structured summaries
        data_summary = {
            "symbol": ticker,
            "symbols": tickers,
        }
        if valuation.get("pe"):
            data_summary["pe_ratio"] = valuation.get("pe")
        if valuation.get("forward_pe"):
            data_summary["forward_pe"] = valuation.get("forward_pe")
        if valuation.get("market_cap"):
            data_summary["market_cap"] = valuation.get("market_cap")
        if analysts.get("ratings_summary"):
            data_summary["analyst_consensus"] = analysts.get("ratings_summary")
        if analysts.get("target_price"):
            data_summary["target_price"] = analysts.get("target_price")
        if dividends.get("dividend_yield"):
            data_summary["dividend_yield"] = dividends.get("dividend_yield")

        # Sources
        sources = [{"title": "Yahoo Finance", "url": "https://finance.yahoo.com"}]

        # Create standardized output
        standardized = create_standardized_output(
            research_report=research_report,
            key_findings=key_findings[:5],
            data_summary=data_summary,
            sources=sources,
            status="success" if any([overview, financials, valuation, earnings, dividends, analysts]) else "no_data")

        cleaned_messages = []
        system_msg = SystemMessage(content=load_prompt("fundamentals.txt"))
        cleaned_messages.append(system_msg)
        cleaned_messages.append(HumanMessage(content="RESEARCH QUESTION: " + research_query))
        cleaned_messages.append(AIMessage(content="SUMMARY OF FINDINGS:\n" + json.dumps(new_summaries, indent=2)))

        return {
            "summaries": new_summaries,
            "fundamental_data": fundamental_data[:2] if fundamental_data else [],
            "messages": cleaned_messages,
            "next_step": "complete",  # Standardized output fields
            "research_report": standardized["research_report"],
            "key_findings": standardized["key_findings"],
            "data_summary": standardized["data_summary"],
            "sources": standardized["sources"],
        }

    def should_continue_after_agent(state):
        """Decide next step after agent node."""
        next_step = state.get("next_step", "")
        messages = state.get("messages", [])
        iteration_count = state.get("iteration_count", 0)
        fundamental_data = state.get("fundamental_data", [])

        if iteration_count >= FUNDAMENTALS_MAX_ITERATIONS:
            return "summarize" if fundamental_data else "end"
        if next_step == "summarize":
            return "summarize"
        if next_step == "tools":
            return "tools"
        if next_step == "end":
            return "summarize" if fundamental_data else "end"
        # Default
        return "end"

    def should_continue_after_tools(state):
        """After tools, always return to agent to decide next step."""
        return "agent"

    graph.add_node("agent", agent)
    graph.add_node("tools", tools_with_tracking)
    graph.add_node("summarize", summarize_findings)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent",
                                should_continue_after_agent, {
                                    "tools": "tools", "summarize": "summarize", "end": END
                                })
    graph.add_conditional_edges("tools", should_continue_after_tools, {"agent": "agent"})
    graph.add_edge("summarize", END)
    return graph.compile()


def create_fundamentals_agent():
    """
    Synchronous wrapper for creating the fundamentals agent.
    Use create_fundamentals_agent_async() in async contexts.
    """
    try:
        loop = asyncio.get_running_loop()
        raise RuntimeError("create_fundamentals_agent() cannot be called from async context. "
                           "Use 'await create_fundamentals_agent_async()' instead.")
    except RuntimeError as e:
        if "no running event loop" in str(e):
            return asyncio.run(create_fundamentals_agent_async())
        raise
