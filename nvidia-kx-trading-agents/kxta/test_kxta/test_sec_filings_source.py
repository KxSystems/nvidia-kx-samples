import asyncio
from unittest.mock import AsyncMock, patch

from kxta.source_agents.sec_filings import SecFilingsSource


def test_identity_and_keywords():
    s = SecFilingsSource()
    assert s.name == "sec_filings"
    assert any(k in s.keywords for k in ("10-k", "filing", "sec", "risk factors"))
    assert s.requires_modules == ["edgar"]


def test_runs_via_tool_graph():
    class _Graph:
        ainvoke = AsyncMock(return_value={
            "research_report": "SEC REPORT", "key_findings": [], "data_summary": {}, "sources": [],
        })
    cfg = {"configurable": {"llm": object()}}
    with patch.object(SecFilingsSource, "_build_graph", new=AsyncMock(return_value=_Graph())):
        res = asyncio.run(SecFilingsSource().run("risk factors in the latest 10-K", cfg, writer=lambda e: None))
    assert "SEC REPORT" in res.content and res.source == "sec_filings"
