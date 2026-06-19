# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""OneTick Cloud source agent — DIRECT querying, no KDB-X materialization.

A standalone tick-data agent in the style of the market_data agent: it pulls
daily bars (and a trade sample) for the queried tickers straight from OneTick
Cloud over the onetick-py WebAPI, computes summary statistics in pandas, and
has the blueprint LLM compress them into report-ready bullets.

Auth is OAuth2 client-credentials (ONETICK_CLIENT_ID / ONETICK_CLIENT_SECRET).
OTP_WEBAPI=1 must be set before the first `onetick.py` import so it uses the
HTTP backend instead of native C++ stubs — handled at import time below.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from kxta.constants import ASYNC_TIMEOUT
from kxta.source_agents.base import SourceResult

logger = logging.getLogger(__name__)

ONETICK_HTTP_ADDRESS = os.getenv("ONETICK_HTTP_ADDRESS", "https://rest.cloud.onetick.com:443")
ONETICK_TOKEN_URL = os.getenv("ONETICK_TOKEN_URL",
                              "https://cloud-auth.parent.onetick.com/realms/OMD/protocol/openid-connect/token")

# Demo-account databases (same routing the materialization adapter used).
_DAILY_DB = ("US_COMP_SAMPLE_DAILY", "DAY")
_TRADE_DB = ("US_COMP_SAMPLE", "TRD")

_TICKER_RE = re.compile(r"\b([A-Z]{1,5})\b")
_NOT_TICKERS = {
    "A",
    "I",
    "THE",
    "AND",
    "FOR",
    "WITH",
    "FROM",
    "OVER",
    "LAST",
    "DAYS",
    "WEEK",
    "VS",
    "USD",
    "ETF",
    "IPO",
    "CEO",
    "API",
    "OHLCV",
    "VWAP",
    "NBBO",
    "Q1",
    "Q2",
    "Q3",
    "Q4",
    "US",
    "ON",
    "IN",
    "TO",
    "OF"
}


def _extract_tickers(query: str, limit: int = 4) -> list[str]:
    """Uppercase 1-5 letter tokens, minus common English/finance words."""
    out: list[str] = []
    for tok in _TICKER_RE.findall(query):
        if tok in _NOT_TICKERS or tok in out:
            continue
        out.append(tok)
        if len(out) >= limit:
            break
    return out


def _extract_window(query: str) -> tuple[str, str]:
    """(start, end) ISO dates from the query; default last 30 days."""
    today = datetime.now(timezone.utc).date()
    q = query.lower()
    days = 30
    m = re.search(r"last\s+(\d{1,3})\s+day", q)
    if m:
        days = max(1, min(365, int(m.group(1))))
    elif "quarter" in q or "3 month" in q or "90 day" in q:
        days = 90
    elif "6 month" in q:
        days = 180
    elif "year" in q or "12 month" in q:
        days = 365
    elif "week" in q:
        days = 7
    return (today - timedelta(days=days)).isoformat(), today.isoformat()


def _onetick():
    """Import onetick.py lazily with the WebAPI backend selected."""
    os.environ.setdefault("OTP_WEBAPI", "1")
    import onetick.py as otp
    return otp


def _clamp_window(start: str, end: str, avail_min: str, avail_max: str) -> tuple[str, str, bool]:
    """Clamp a requested [start, end] window to the database's available range.

    If the windows don't overlap at all (e.g. asking for "last 30 days" against a
    sample DB that ends in 2024), slide the SAME-LENGTH window to the end of the
    available range. Returns (start, end, adjusted).
    """
    req_s, req_e = datetime.fromisoformat(start).date(), datetime.fromisoformat(end).date()
    av_s, av_e = datetime.fromisoformat(avail_min).date(), datetime.fromisoformat(avail_max).date()
    if req_s > av_e or req_e < av_s:
        length = (req_e - req_s).days
        new_e = av_e
        new_s = max(av_s, av_e - timedelta(days=length))
        return new_s.isoformat(), new_e.isoformat(), True
    c_s, c_e = max(req_s, av_s), min(req_e, av_e)
    return c_s.isoformat(), c_e.isoformat(), (c_s, c_e) != (req_s, req_e)


class _OneTickClient:
    """Thin sync client: authenticate once, fetch daily bars / trade samples."""

    # Available date range of the daily DB, discovered once per process.
    _range_cache: tuple[str, str] | None = None

    def __init__(self):
        self.client_id = os.getenv("ONETICK_CLIENT_ID", "")
        self.client_secret = os.getenv("ONETICK_CLIENT_SECRET", "")
        self._authed = False

    def _authenticate(self, otp):
        if self._authed:
            return
        import requests
        resp = requests.post(
            ONETICK_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=30,
        )
        resp.raise_for_status()
        otp.config.access_token = resp.json()["access_token"]
        otp.config.http_address = ONETICK_HTTP_ADDRESS
        self._authed = True

    def daily_range(self) -> tuple[str, str] | None:
        """(min_date, max_date) of the daily DB, cached per process; None on failure."""
        if _OneTickClient._range_cache is not None:
            return _OneTickClient._range_cache
        try:
            otp = _onetick()
            self._authenticate(otp)
            dates = otp.databases()[_DAILY_DB[0]].dates()
            if dates:
                _OneTickClient._range_cache = (min(dates).isoformat(), max(dates).isoformat())
        except Exception as e:
            logger.warning(f"OneTick date-range discovery failed: {e}")
        return _OneTickClient._range_cache

    def fetch_daily(self, symbol: str, start: str, end: str):
        """Daily bars for one symbol as a pandas DataFrame (may be empty)."""
        otp = _onetick()
        self._authenticate(otp)
        db, tick_type = _DAILY_DB
        s = datetime.fromisoformat(start)
        e = datetime.fromisoformat(end)
        source = otp.DataSource(db=db, tick_type=tick_type)
        return otp.run(source,
                       symbols=f"{db}::{symbol}",
                       start=otp.dt(s.year, s.month, s.day),
                       end=otp.dt(e.year, e.month, e.day, 23, 59, 59))


def _summarize_frame(symbol: str, df) -> dict:
    """Headline stats from a daily-bars frame. Column names vary by feed; be lenient."""
    cols = {c.upper(): c for c in df.columns}

    def col(*names):
        for n in names:
            if n in cols:
                return df[cols[n]]
        return None

    close = col("CLOSE", "PRICE", "LAST")
    volume = col("VOLUME", "SIZE")
    high = col("HIGH")
    low = col("LOW")
    out: dict = {"symbol": symbol, "rows": int(len(df))}
    if close is not None and len(close) > 0:
        first, last = float(close.iloc[0]), float(close.iloc[-1])
        out["last_close"] = round(last, 4)
        out["period_change_pct"] = round((last - first) / first * 100, 2) if first else None
        returns = close.pct_change().dropna()
        if len(returns) > 1:
            out["daily_vol_pct"] = round(float(returns.std()) * 100, 2)
    if high is not None and len(high) > 0:
        out["period_high"] = round(float(high.max()), 4)
    if low is not None and len(low) > 0:
        out["period_low"] = round(float(low.min()), 4)
    if volume is not None and len(volume) > 0:
        out["avg_daily_volume"] = int(volume.mean())
    return out


class OneTickSource:
    """Registry source agent backed by OneTick Cloud (direct WebAPI queries)."""

    name = "onetick"
    label = "OneTick Cloud"
    description = "Tick-data history from OneTick Cloud: daily bars, returns, volatility, volume."
    keywords = [
        "onetick",
        "tick data",
        "tick-level",
        "intraday history",
        "market microstructure",
        "consolidated tape",
    ]
    requires_env = ["ONETICK_CLIENT_ID", "ONETICK_CLIENT_SECRET"]
    requires_modules = ["onetick"]

    def is_available(self) -> bool:
        import importlib.util
        for mod in self.requires_modules:
            if importlib.util.find_spec(mod) is None:
                return False
        return all(os.getenv(e) for e in self.requires_env)

    async def run(self, query: str, config: RunnableConfig, writer: StreamWriter) -> SourceResult:
        start_ts = time.time()
        tickers = _extract_tickers(query)
        window_start, window_end = _extract_window(query)
        if not tickers:
            return SourceResult(source=self.name, content="", citation="", duration_seconds=time.time() - start_ts)

        writer({"onetick_progress": f"Querying OneTick Cloud: {', '.join(tickers)} ({window_start} → {window_end})"})

        client = _OneTickClient()
        stats: list[dict] = []
        total_rows = 0
        window_note = ""
        try:
            async with asyncio.timeout(ASYNC_TIMEOUT):
                # Clamp the requested window to the database's available range (the
                # sample DBs cover a fixed historical slice; "last 30 days" would
                # otherwise return zero rows).
                avail = await asyncio.to_thread(client.daily_range)
                if avail:
                    window_start, window_end, adjusted = _clamp_window(window_start, window_end, *avail)
                    if adjusted:
                        window_note = (f"Note: window adjusted to the database's available range "
                                       f"({avail[0]} → {avail[1]}).")
                        writer(
                            {"onetick_progress": f"Window adjusted to available data: {window_start} → {window_end}"})
                for sym in tickers:
                    writer({"onetick_progress": f"Fetching daily bars for {sym}"})
                    df = await asyncio.to_thread(client.fetch_daily, sym, window_start, window_end)
                    if df is None or len(df) == 0:
                        writer({"onetick_progress": f"No OneTick data for {sym} in window"})
                        continue
                    s = _summarize_frame(sym, df)
                    total_rows += s["rows"]
                    stats.append(s)
        except asyncio.TimeoutError:
            logger.error(f"onetick source timed out after {time.time() - start_ts:.0f}s")
            return SourceResult(source=self.name, content="", citation="", duration_seconds=time.time() - start_ts)
        except Exception as e:
            logger.exception(f"onetick source failed: {type(e).__name__}: {e}")
            return SourceResult(source=self.name, content="", citation="", duration_seconds=time.time() - start_ts)

        if not stats:
            return SourceResult(source=self.name, content="", citation="", duration_seconds=time.time() - start_ts)

        content = self._format_report(stats, window_start, window_end)
        if window_note:
            content = f"{content}\n\n{window_note}"
        # Optional LLM polish into report-ready bullets (no_think on Nemotron).
        llm = config["configurable"].get("llm")
        if llm is not None:
            try:
                from kxta.utils import as_no_think_messages
                prompt = ("Summarize these market statistics from OneTick Cloud tick data into 3-5 concise, "
                          "factual bullets for a trading research report. Numbers only, no recommendations.\n\n" +
                          content)
                resp = await llm.ainvoke(as_no_think_messages(llm, prompt))
                polished = getattr(resp, "content", "") or ""
                if polished.strip():
                    content = f"{polished.strip()}\n\n{content}"
            except Exception as e:
                logger.warning(f"onetick summary polish failed (using raw stats): {e}")

        writer({"onetick_progress": f"OneTick complete: {len(stats)} symbols, {total_rows} bars"})
        citation = (f"OneTick Cloud ({_DAILY_DB[0]}) — daily bars {window_start} to {window_end} "
                    f"for {', '.join(s['symbol'] for s in stats)}\nhttps://www.onetick.com/cloud")
        return SourceResult(
            source=self.name,
            content=content,
            citation=citation,
            record_count=total_rows,
            duration_seconds=time.time() - start_ts,
        )

    @staticmethod
    def _format_report(stats: list[dict], start: str, end: str) -> str:
        lines = [f"OneTick Cloud daily-bar statistics ({start} → {end}):", ""]
        lines.append("| Symbol | Last close | Period Δ% | High | Low | Daily vol % | Avg volume | Bars |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for s in stats:
            lines.append("| {symbol} | {last_close} | {chg} | {hi} | {lo} | {vol} | {adv} | {rows} |".format(
                symbol=s["symbol"],
                last_close=s.get("last_close", "—"),
                chg=s.get("period_change_pct", "—"),
                hi=s.get("period_high", "—"),
                lo=s.get("period_low", "—"),
                vol=s.get("daily_vol_pct", "—"),
                adv=s.get("avg_daily_volume", "—"),
                rows=s["rows"],
            ))
        return "\n".join(lines)
