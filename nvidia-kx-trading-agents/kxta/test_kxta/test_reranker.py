# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for reranker-NIM relevancy gating (no network)."""

import pytest

import kxta.reranker as rr


def test_disabled_without_env(monkeypatch):
    monkeypatch.setattr(rr, "RERANKER_NIM_URL", "")
    assert rr.reranker_enabled() is False


@pytest.mark.asyncio
async def test_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(rr, "RERANKER_NIM_URL", "")
    assert await rr.rerank_relevancy("q", "answer") is None


def test_chunking_caps_and_splits():
    text = "x" * (rr._CHUNK_CHARS * 6)
    chunks = rr._chunk(text)
    assert len(chunks) == rr._MAX_CHUNKS
    assert all(len(c) <= rr._CHUNK_CHARS for c in chunks)
    assert rr._chunk("") == []


@pytest.mark.asyncio
async def test_threshold_verdicts(monkeypatch):
    monkeypatch.setattr(rr, "RERANKER_NIM_URL", "http://fake:8000")

    class FakeResp:

        def __init__(self, data):
            self._d = data

        def raise_for_status(self):
            pass

        async def json(self):
            return self._d

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class FakeSession:

        def __init__(self, data):
            self._d = data

        def post(self, url, json=None):
            return FakeResp(self._d)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    def fake_session_factory(data):
        return lambda *a, **k: FakeSession(data)

    monkeypatch.setattr(rr.aiohttp,
                        "ClientSession",
                        fake_session_factory({"rankings": [{
                            "index": 0, "logit": 10.8
                        }, {
                            "index": 1, "logit": -16.0
                        }]}))
    out = await rr.rerank_relevancy("q", "some answer")
    assert out == {"score": "yes", "judge": "reranker", "logit": 10.8}

    monkeypatch.setattr(rr.aiohttp, "ClientSession", fake_session_factory({"rankings": [{"index": 0, "logit": -14.4}]}))
    out = await rr.rerank_relevancy("q", "some answer")
    assert out["score"] == "no" and out["logit"] == -14.4


@pytest.mark.asyncio
async def test_failure_falls_back_to_none(monkeypatch):
    monkeypatch.setattr(rr, "RERANKER_NIM_URL", "http://fake:8000")

    class Boom:

        def __init__(self, *a, **k):
            raise ConnectionError("down")

    monkeypatch.setattr(rr.aiohttp, "ClientSession", Boom)
    assert await rr.rerank_relevancy("q", "answer") is None


@pytest.mark.asyncio
async def test_empty_answer_is_not_relevant(monkeypatch):
    monkeypatch.setattr(rr, "RERANKER_NIM_URL", "http://fake:8000")
    out = await rr.rerank_relevancy("q", "   ")
    assert out == {"score": "no", "judge": "reranker", "logit": None}
