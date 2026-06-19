import asyncio
from unittest.mock import AsyncMock, patch

from kxta.source_agents.news_headlines import NewsHeadlinesSource


def test_identity_and_keywords():
    s = NewsHeadlinesSource()
    assert s.name == "news_headlines"
    assert "headline" in s.keywords or "news" in s.keywords


def test_runs_and_maps():
    class _Graph:
        ainvoke = AsyncMock(return_value={
            "research_report": "NEWS REPORT", "key_findings": [], "data_summary": {"articles_analyzed": 4},
            "sources": [{"title": "H", "url": "http://n"}],
        })
    cfg = {"configurable": {"llm": object()}}
    with patch.object(NewsHeadlinesSource, "_build_graph", new=AsyncMock(return_value=_Graph())):
        res = asyncio.run(NewsHeadlinesSource().run("latest headlines on X", cfg, writer=lambda e: None))
    assert "NEWS REPORT" in res.content and res.record_count == 4 and "http://n" in res.citation


def test_headlines_analyzed_maps_to_record_count():
    class _Graph:
        ainvoke = AsyncMock(return_value={
            "research_report": "R", "key_findings": [], "data_summary": {"headlines_analyzed": 9}, "sources": [],
        })
    cfg = {"configurable": {"llm": object()}}
    with patch.object(NewsHeadlinesSource, "_build_graph", new=AsyncMock(return_value=_Graph())):
        res = asyncio.run(NewsHeadlinesSource().run("headlines", cfg, writer=lambda e: None))
    assert res.record_count == 9
