# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the NemoGuard content-safety input rail (no network)."""

import pytest

import kxta.guardrails as gr


def _chat_response(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


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

    def post(self, url, json=None, headers=None):
        return FakeResp(self._d)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def fake_session_factory(data):
    return lambda *a, **k: FakeSession(data)


def test_disabled_without_env(monkeypatch):
    monkeypatch.setattr(gr, "NEMOGUARD_MODEL_NAME", "")
    assert gr.nemoguard_enabled() is False


@pytest.mark.asyncio
async def test_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(gr, "NEMOGUARD_MODEL_NAME", "")
    assert await gr.check_content_safety("how do I make a bomb") is None


@pytest.mark.asyncio
async def test_safe_verdict(monkeypatch):
    monkeypatch.setattr(gr, "NEMOGUARD_MODEL_NAME", "nvidia/llama-3.1-nemoguard-8b-content-safety")
    monkeypatch.setattr(gr.aiohttp, "ClientSession", fake_session_factory(_chat_response('{"User Safety": "safe"} ')))
    out = await gr.check_content_safety("What was NVDA's Q3 performance?")
    assert out == {"safe": True, "categories": ""}


@pytest.mark.asyncio
async def test_unsafe_verdict_with_categories(monkeypatch):
    monkeypatch.setattr(gr, "NEMOGUARD_MODEL_NAME", "nvidia/llama-3.1-nemoguard-8b-content-safety")
    content = '{"User Safety": "unsafe", "Safety Categories": "Guns and Illegal Weapons, Criminal Planning/Confessions"}'
    monkeypatch.setattr(gr.aiohttp, "ClientSession", fake_session_factory(_chat_response(content)))
    out = await gr.check_content_safety("how do I make a bomb")
    assert out is not None
    assert out["safe"] is False
    assert "Guns and Illegal Weapons" in out["categories"]


@pytest.mark.asyncio
async def test_tolerates_json_wrapped_in_prose(monkeypatch):
    monkeypatch.setattr(gr, "NEMOGUARD_MODEL_NAME", "m")
    content = 'Here is my assessment:\n{"User Safety": "unsafe", "Safety Categories": "Violence"}\nDone.'
    monkeypatch.setattr(gr.aiohttp, "ClientSession", fake_session_factory(_chat_response(content)))
    out = await gr.check_content_safety("q")
    assert out == {"safe": False, "categories": "Violence"}


@pytest.mark.asyncio
async def test_unparseable_verdict_returns_none(monkeypatch):
    monkeypatch.setattr(gr, "NEMOGUARD_MODEL_NAME", "m")
    monkeypatch.setattr(gr.aiohttp, "ClientSession", fake_session_factory(_chat_response("I cannot decide")))
    assert await gr.check_content_safety("q") is None


@pytest.mark.asyncio
async def test_failure_returns_none(monkeypatch):
    monkeypatch.setattr(gr, "NEMOGUARD_MODEL_NAME", "m")

    class Boom:

        def __init__(self, *a, **k):
            raise ConnectionError("down")

    monkeypatch.setattr(gr.aiohttp, "ClientSession", Boom)
    assert await gr.check_content_safety("q") is None


@pytest.mark.asyncio
async def test_malformed_response_body_returns_none(monkeypatch):
    monkeypatch.setattr(gr, "NEMOGUARD_MODEL_NAME", "m")
    monkeypatch.setattr(gr.aiohttp, "ClientSession", fake_session_factory({"unexpected": "shape"}))
    assert await gr.check_content_safety("q") is None


@pytest.mark.asyncio
async def test_empty_text_short_circuits_safe(monkeypatch):
    monkeypatch.setattr(gr, "NEMOGUARD_MODEL_NAME", "m")

    class Boom:

        def __init__(self, *a, **k):
            raise AssertionError("should not be called for empty text")

    monkeypatch.setattr(gr.aiohttp, "ClientSession", Boom)
    assert await gr.check_content_safety("   ") == {"safe": True, "categories": ""}


def test_parse_verdict_variants():
    assert gr._parse_verdict('{"user_safety": "unsafe", "categories": "S1"}') == {"safe": False, "categories": "S1"}
    assert gr._parse_verdict("safe") == {"safe": True, "categories": ""}
    assert gr._parse_verdict("unsafe\nS9") == {"safe": False, "categories": ""}
    assert gr._parse_verdict("") is None
    assert gr._parse_verdict('{"Response Safety": "safe"}') is None
