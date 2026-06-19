import asyncio
from unittest.mock import AsyncMock, patch

from kxta.source_agents.web_search import WebSearchSource


def test_web_search_source_identity_and_keywords():
    s = WebSearchSource()
    assert s.name == "web_search"
    assert "news" in s.keywords or "latest" in s.keywords
    assert s.requires_env == ["FIRECRAWL_API_KEY"]


def test_web_search_source_runs_graph_and_maps_output():
    class _Graph:
        ainvoke = AsyncMock(return_value={
            "final_report": "WEB REPORT", "key_findings": ["k"],
            "data_summary": {"articles_analyzed": 2}, "sources": [{"title": "S", "url": "http://u"}],
        })
    cfg = {"configurable": {"llm": object()}}
    with patch.object(WebSearchSource, "_build_graph", new=AsyncMock(return_value=_Graph())):
        res = asyncio.run(WebSearchSource().run("latest news on X", cfg, writer=lambda e: None))
    assert "WEB REPORT" in res.content
    assert res.record_count == 2
    assert res.source == "web_search"
