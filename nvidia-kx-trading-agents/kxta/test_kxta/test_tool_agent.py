import asyncio

from langchain_core.tools import tool
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from kxta.source_agents.tool_agent import build_tool_react_graph
from kxta.source_agents._vendor.config import use_blueprint_llm


@tool
def echo_tool(text: str) -> str:
    """Echo the text back."""
    return f"echoed: {text}"


class _ToolBindableFake(FakeListChatModel):
    # FakeListChatModel inherits BaseChatModel.bind_tools, which raises
    # NotImplementedError in langchain_core 0.3.x. Real chat models (NIM /
    # ChatOpenAI) implement it; the agent node calls llm.bind_tools(tools).
    # The fake emits no tool calls, so binding is a no-op that returns self.
    def bind_tools(self, tools, **kwargs):
        return self


def test_tool_graph_runs_without_tool_calls_and_summarizes():
    # FakeListChatModel emits no tool calls -> graph goes straight to summarize.
    fake = _ToolBindableFake(responses=["I have enough info.", "## Report\n- finding one\nSources: none"])
    with use_blueprint_llm(fake):
        graph = build_tool_react_graph([echo_tool], system_prompt="Research helper.", max_iterations=2)
        result = asyncio.run(graph.ainvoke({"query": "test", "messages": [], "iteration_count": 0},
                                           {"recursion_limit": 10}))
    assert "research_report" in result
    assert isinstance(result["research_report"], str) and result["research_report"]
    assert "key_findings" in result and "sources" in result and "data_summary" in result
