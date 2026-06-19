import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from kxta.source_agents.base import SourceResult
from kxta.source_agents.registry import RagSource
from kxta import search_utils


@pytest.fixture
def cfg():
    return {"configurable": {"llm": None, "rag_url": "http://rag", "collection": "demo",
                             "use_rag": True, "use_kdb": False}}


def _writer(event):
    pass


def test_rag_only_relevant_returns_rag_answer(cfg):
    rag = SourceResult(source="rag", content="RAG says X", citation="rag-cite")
    with patch.object(RagSource, "run", new=AsyncMock(return_value=rag)), \
         patch.object(RagSource, "is_available", return_value=True), \
         patch.object(search_utils, "check_relevancy", new=AsyncMock(return_value={"score": "yes"})):
        answer, citation, relevancy, web_answer, web_citation = asyncio.run(
            search_utils.process_single_query("topic q", cfg, _writer, "demo", None, search_web=False)
        )
    assert "RAG says X" in answer
    assert relevancy["score"] == "yes"
    assert web_answer is None


def test_collection_passed_as_arg_reaches_source():
    captured = {}

    async def fake_run(self, query, config, writer):
        captured["collection"] = config["configurable"].get("collection")
        return SourceResult(source="rag", content="ok", citation="c")

    cfg_no_collection = {"configurable": {"llm": None, "rag_url": "http://rag", "use_rag": True, "use_kdb": False}}
    with patch.object(RagSource, "run", new=fake_run), \
         patch.object(RagSource, "is_available", return_value=True), \
         patch.object(search_utils, "check_relevancy", new=AsyncMock(return_value={"score": "yes"})):
        asyncio.run(search_utils.process_single_query("q", cfg_no_collection, _writer, "demo-collection", None, search_web=False))
    assert captured["collection"] == "demo-collection"


def test_irrelevant_triggers_web_fallback(cfg):
    rag = SourceResult(source="rag", content="unrelated", citation="")
    with patch.object(RagSource, "run", new=AsyncMock(return_value=rag)), \
         patch.object(RagSource, "is_available", return_value=True), \
         patch.object(search_utils, "check_relevancy", new=AsyncMock(return_value={"score": "no"})), \
         patch.object(search_utils, "_perform_web_search",
                      new=AsyncMock(return_value=("web ans", "web cite"))):
        answer, citation, relevancy, web_answer, web_citation = asyncio.run(
            search_utils.process_single_query("topic q", cfg, _writer, "demo", None, search_web=True)
        )
    assert relevancy["score"] == "no"
    assert web_answer == "web ans"
    assert web_citation == "web cite"
