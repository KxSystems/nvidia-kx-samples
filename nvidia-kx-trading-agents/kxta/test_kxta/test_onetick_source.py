# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the standalone OneTick Cloud source agent (no network)."""

import pandas as pd
import pytest

from kxta.source_agents.onetick import OneTickSource
from kxta.source_agents.onetick import _extract_tickers
from kxta.source_agents.onetick import _extract_window
from kxta.source_agents.onetick import _summarize_frame


# ---------------------------------------------------------------------------
# Query parsing
# ---------------------------------------------------------------------------
def test_extract_tickers_filters_common_words():
    assert _extract_tickers("NVDA and TSLA tick data for the last 30 days") == ["NVDA", "TSLA"]


def test_extract_tickers_caps_and_dedupes():
    out = _extract_tickers("AAPL MSFT AMD TSM NVDA AAPL")
    assert out == ["AAPL", "MSFT", "AMD", "TSM"]  # capped at 4, deduped


def test_extract_window_defaults_and_phrases():
    start, end = _extract_window("NVDA price history")
    assert (pd.Timestamp(end) - pd.Timestamp(start)).days == 30
    start, end = _extract_window("NVDA over the last 90 days")
    assert (pd.Timestamp(end) - pd.Timestamp(start)).days == 90
    start, end = _extract_window("TSLA this week volatility")
    assert (pd.Timestamp(end) - pd.Timestamp(start)).days == 7


# ---------------------------------------------------------------------------
# Frame summarization
# ---------------------------------------------------------------------------
def test_summarize_frame_computes_stats():
    df = pd.DataFrame({
        "CLOSE": [100.0, 110.0, 105.0, 120.0],
        "HIGH": [101, 112, 108, 122],
        "LOW": [99, 104, 103, 110],
        "VOLUME": [1000, 2000, 1500, 2500],
    })
    s = _summarize_frame("NVDA", df)
    assert s["symbol"] == "NVDA" and s["rows"] == 4
    assert s["last_close"] == 120.0
    assert s["period_change_pct"] == 20.0
    assert s["period_high"] == 122 and s["period_low"] == 99
    assert s["avg_daily_volume"] == 1750
    assert s["daily_vol_pct"] > 0


def test_summarize_frame_lenient_columns():
    df = pd.DataFrame({"price": [10.0, 12.0]})  # lowercase, PRICE alias
    s = _summarize_frame("X", df)
    assert s["last_close"] == 12.0


# ---------------------------------------------------------------------------
# Availability + run guards
# ---------------------------------------------------------------------------
def test_unavailable_without_env(monkeypatch):
    monkeypatch.delenv("ONETICK_CLIENT_ID", raising=False)
    monkeypatch.delenv("ONETICK_CLIENT_SECRET", raising=False)
    assert OneTickSource().is_available() is False


@pytest.mark.asyncio
async def test_run_returns_empty_without_tickers():
    src = OneTickSource()
    result = await src.run("what is happening in the markets today", {"configurable": {}}, lambda m: None)
    assert result.source == "onetick" and result.content == ""


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------
def test_registered_and_flag_gated():
    from kxta.source_agents.registry import get_registry
    reg = get_registry()
    names = [s.name for s in reg.all_sources()]
    assert "onetick" in names
    src = next(s for s in reg.all_sources() if s.name == "onetick")
    assert reg._is_selected(src, {"use_onetick": True}) is True
    assert reg._is_selected(src, {}) is False


def test_fallback_chains_include_onetick():
    from kxta.source_agents.routing import FALLBACK_CHAINS
    assert FALLBACK_CHAINS["kdb"][0] == "onetick"
    assert "kdb" in FALLBACK_CHAINS["onetick"]


def test_clamp_window_no_overlap_slides_to_available_end():
    from kxta.source_agents.onetick import _clamp_window
    s, e, adj = _clamp_window("2026-05-12", "2026-06-11", "2024-01-01", "2024-03-31")
    assert adj is True
    assert e == "2024-03-31"
    assert s == "2024-03-01"  # same 30-day length, slid into range


def test_clamp_window_partial_overlap_clamps():
    from kxta.source_agents.onetick import _clamp_window
    s, e, adj = _clamp_window("2023-12-01", "2024-01-15", "2024-01-01", "2024-03-31")
    assert (s, e, adj) == ("2024-01-01", "2024-01-15", True)


def test_clamp_window_inside_range_untouched():
    from kxta.source_agents.onetick import _clamp_window
    s, e, adj = _clamp_window("2024-02-01", "2024-02-20", "2024-01-01", "2024-03-31")
    assert (s, e, adj) == ("2024-02-01", "2024-02-20", False)
