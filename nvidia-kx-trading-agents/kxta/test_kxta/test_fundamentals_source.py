import asyncio
from unittest.mock import AsyncMock, patch

from kxta.source_agents.fundamentals import FundamentalsSource


def test_identity_and_keywords():
    s = FundamentalsSource()
    assert s.name == "fundamentals"
    assert any(k in s.keywords for k in ("earnings", "revenue", "valuation", "balance sheet"))


def test_runs_and_maps():
    class _Graph:
        ainvoke = AsyncMock(return_value={
            "research_report": "FUND REPORT", "key_findings": [], "data_summary": {}, "sources": [],
        })
    cfg = {"configurable": {"llm": object()}}
    with patch.object(FundamentalsSource, "_build_graph", new=AsyncMock(return_value=_Graph())):
        res = asyncio.run(FundamentalsSource().run("revenue and margins for the company", cfg, writer=lambda e: None))
    assert "FUND REPORT" in res.content and res.source == "fundamentals"
