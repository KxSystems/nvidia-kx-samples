# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for embedding-NIM semantic routing/dedup (no network)."""

import pytest

import kxta.embeddings as emb


def _fake_session(vectors_by_text):

    class FakeResp:

        def __init__(self, payload):
            self._p = payload

        def raise_for_status(self):
            pass

        async def json(self):
            return self._p

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class FakeSession:

        def post(self, url, json=None):
            data = [{"embedding": vectors_by_text[t]} for t in json["input"]]
            return FakeResp({"data": data})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    return lambda *a, **k: FakeSession()


@pytest.fixture(autouse=True)
def clear_cache():
    emb._cache.clear()
    yield
    emb._cache.clear()


def test_cosine():
    assert emb.cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert emb.cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert emb.cosine([0, 0], [1, 1]) == 0.0


@pytest.mark.asyncio
async def test_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(emb, "EMBEDDING_NIM_URL", "")
    assert await emb.embed(["x"]) is None
    assert await emb.semantic_is_novel("a", ["b"]) is None
    assert await emb.semantic_route("a", [("s", "d")]) is None


@pytest.mark.asyncio
async def test_semantic_is_novel_thresholds(monkeypatch):
    monkeypatch.setattr(emb, "EMBEDDING_NIM_URL", "http://fake:8000")
    vecs = {"new q": [1.0, 0.0], "dup q": [0.99, 0.14], "other": [0.0, 1.0]}
    monkeypatch.setattr(emb.aiohttp, "ClientSession", _fake_session(vecs))
    assert await emb.semantic_is_novel("new q", ["dup q"]) is False  # cos ~0.99
    emb._cache.clear()
    assert await emb.semantic_is_novel("new q", ["other"]) is True  # cos 0


@pytest.mark.asyncio
async def test_semantic_route_picks_best_and_respects_min_sim(monkeypatch):
    monkeypatch.setattr(emb, "EMBEDDING_NIM_URL", "http://fake:8000")
    vecs = {
        "NVDA tick history": [1.0, 0.0],
        "tick data, bars, volatility": [0.95, 0.31],
        "company financial statements": [0.0, 1.0],
    }
    monkeypatch.setattr(emb.aiohttp, "ClientSession", _fake_session(vecs))
    best = await emb.semantic_route("NVDA tick history",
                                    [
                                        ("onetick", "tick data, bars, volatility"),
                                        ("fundamentals", "company financial statements"),
                                    ])
    assert best == "onetick"
    emb._cache.clear()
    # nothing similar enough
    best = await emb.semantic_route("NVDA tick history", [("fundamentals", "company financial statements")])
    assert best is None


@pytest.mark.asyncio
async def test_failure_falls_back_to_none(monkeypatch):
    monkeypatch.setattr(emb, "EMBEDDING_NIM_URL", "http://fake:8000")

    class Boom:

        def __init__(self, *a, **k):
            raise ConnectionError("down")

    monkeypatch.setattr(emb.aiohttp, "ClientSession", Boom)
    assert await emb.embed(["x"]) is None
