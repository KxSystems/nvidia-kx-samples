# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Minimal ReAct loop that turns a LangChain tool-set into the SourceAgent contract.

build_tool_react_graph(tools, system_prompt, max_iterations) compiles a graph:
    agent (blueprint LLM + bound tools)  <->  ToolNode  ->  summarize
The blueprint LLM is read from the contextvar via _vendor.config.get_research_llm().
summarize produces {research_report, key_findings, data_summary, sources} using the
vendored report_utils extractors, matching the agent-backed sources' output shape.
"""

from __future__ import annotations

import operator
from typing import Annotated
from typing import Sequence
from typing import TypedDict

from langchain_core.messages import BaseMessage
from langchain_core.messages import HumanMessage
from langgraph.graph import END
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode

from kxta.source_agents._vendor.config import get_research_llm
from kxta.source_agents._vendor.report_utils import create_standardized_output
from kxta.source_agents._vendor.report_utils import extract_key_findings_from_markdown
from kxta.source_agents._vendor.report_utils import extract_sources_from_markdown
from kxta.source_agents.streaming import get_event_emitter


def _emit(step: str):
    """Best-effort progress emit to the active source's stream (no-op if unscoped)."""
    emitter = get_event_emitter()
    if emitter is not None:
        emitter.emit_agent_progress_sync(current_step=step)


class ToolAgentState(TypedDict, total=False):
    query: str
    messages: Annotated[Sequence[BaseMessage], operator.add]
    iteration_count: int
    research_report: str
    key_findings: list
    data_summary: dict
    sources: list


def build_tool_react_graph(tools: list, system_prompt: str, max_iterations: int = 4):
    """Compile a minimal tool-using ReAct graph. LLM is resolved at run time (blueprint)."""
    tool_node = ToolNode(tools, handle_tool_errors=True)
    graph = StateGraph(ToolAgentState)

    async def agent(state: ToolAgentState):
        llm = get_research_llm().bind_tools(tools)
        messages = list(state.get("messages", []))
        iteration = state.get("iteration_count", 0)
        if not messages:
            messages = [HumanMessage(content=f"{system_prompt}\n\nRESEARCH QUESTION: {state.get('query', '')}")]
            _emit("Analyzing the question and deciding which tools to use...")
        else:
            messages.append(HumanMessage(content="Continue based on the results above, or stop if you have enough."))
            _emit(f"Reviewing tool results (step {iteration + 1})...")
        response = await llm.ainvoke(messages)
        calls = getattr(response, "tool_calls", None) or []
        if calls:
            names = ", ".join(c.get("name", "tool") for c in calls)
            _emit(f"Calling: {names}")
        return {"messages": [response], "iteration_count": iteration + 1}

    def should_continue(state: ToolAgentState):
        messages = state.get("messages", [])
        if not messages:
            return "summarize"
        last = messages[-1]
        if getattr(last, "tool_calls", None) and state.get("iteration_count", 0) < max_iterations:
            return "tools"
        return "summarize"

    async def summarize(state: ToolAgentState):
        _emit("Writing up the findings...")
        llm = get_research_llm()
        notes = []
        for m in state.get("messages", []):
            content = getattr(m, "content", "")
            if isinstance(content, list):
                content = " ".join(str(p) for p in content)
            if content:
                notes.append(f"[{getattr(m, 'type', 'msg')}] {content}")
        prompt = (f"Write a concise, factual research report answering: {state.get('query', '')}\n\n"
                  f"Use ONLY the gathered data below. Include a KEY FINDINGS section and a SOURCES "
                  f"section. Do not speculate.\n\nGATHERED DATA:\n" + "\n".join(notes))
        resp = await llm.ainvoke(prompt)
        report = getattr(resp, "content", "") or ""
        standardized = create_standardized_output(
            research_report=report,
            key_findings=extract_key_findings_from_markdown(report, max_items=5),
            data_summary={"iterations": state.get("iteration_count", 0)},
            sources=extract_sources_from_markdown(report),
            status="success" if report else "no_data",
        )
        return {
            "research_report": standardized["research_report"],
            "key_findings": standardized["key_findings"],
            "data_summary": standardized["data_summary"],
            "sources": standardized["sources"],
        }

    graph.add_node("agent", agent)
    graph.add_node("tools", tool_node)
    graph.add_node("summarize", summarize)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "summarize": "summarize"})
    graph.add_edge("tools", "agent")
    graph.add_edge("summarize", END)
    return graph.compile()


class ToolAgentSource:
    """Mixin providing _build_graph()/_initial_state() for a tool-backed source.

    Concrete sources subclass AgentSource AND this, and set `tools`, `system_prompt`,
    `max_iterations`. AgentSource.run() supplies the blueprint LLM + emitter contextvars.
    """
    tools: list = []
    system_prompt: str = ""
    max_iterations: int = 4

    async def _build_graph(self):
        return build_tool_react_graph(self.tools, self.system_prompt, self.max_iterations)

    def _initial_state(self, query: str) -> dict:
        return {"query": query, "messages": [], "iteration_count": 0}
