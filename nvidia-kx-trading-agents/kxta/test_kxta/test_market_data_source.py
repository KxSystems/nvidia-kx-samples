import asyncio
from unittest.mock import AsyncMock, patch

from kxta.source_agents.market_data import MarketDataSource


def test_identity_and_keywords():
    s = MarketDataSource()
    assert s.name == "market_data"
    assert "price" in s.keywords and "volume" in s.keywords


def test_runs_and_maps():
    class _Graph:
        ainvoke = AsyncMock(return_value={
            "research_report": "MD REPORT", "key_findings": [], "data_summary": {"rows": 7}, "sources": [],
        })
    cfg = {"configurable": {"llm": object()}}
    with patch.object(MarketDataSource, "_build_graph", new=AsyncMock(return_value=_Graph())):
        res = asyncio.run(MarketDataSource().run("average volume for the stock", cfg, writer=lambda e: None))
    assert "MD REPORT" in res.content and res.record_count == 7
