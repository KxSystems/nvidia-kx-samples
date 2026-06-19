import asyncio
from unittest.mock import AsyncMock, patch

from kxta.source_agents.macro_economic import MacroEconomicSource


def test_identity_keywords_and_key_requirement():
    s = MacroEconomicSource()
    assert s.name == "macro_economic"
    assert any(k in s.keywords for k in ("inflation", "gdp", "unemployment", "interest rate"))
    assert s.requires_env == ["FRED_API_KEY"]
    assert s.requires_modules == ["fredapi"]


def test_runs_via_tool_graph():
    class _Graph:
        ainvoke = AsyncMock(return_value={
            "research_report": "MACRO REPORT", "key_findings": [], "data_summary": {}, "sources": [],
        })
    cfg = {"configurable": {"llm": object()}}
    with patch.object(MacroEconomicSource, "_build_graph", new=AsyncMock(return_value=_Graph())):
        res = asyncio.run(MacroEconomicSource().run("US inflation trend over the last year", cfg, writer=lambda e: None))
    assert "MACRO REPORT" in res.content and res.source == "macro_economic"
