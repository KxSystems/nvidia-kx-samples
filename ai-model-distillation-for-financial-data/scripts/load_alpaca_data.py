# SPDX-FileCopyrightText: Copyright (c) 2026 KX Systems, Inc. All rights reserved.
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
"""Fetch real market data from Alpaca and load into KDB-X.

POC script for running the data flywheel on real financial data.

Usage
-----
# 1. Save Parquet only (no KDB-X needed):
ALPACA_API_KEY=xxx ALPACA_SECRET_KEY=yyy \\
    python scripts/load_alpaca_data.py --symbol AAPL --parquet-only

# 2. Save Parquet + load into KDB-X:
ALPACA_API_KEY=xxx ALPACA_SECRET_KEY=yyy KDBX_ENDPOINT=localhost:8082 \\
    python scripts/load_alpaca_data.py --symbol AAPL

# 3. Include news headlines (for flywheel_logs):
ALPACA_API_KEY=xxx ALPACA_SECRET_KEY=yyy KDBX_ENDPOINT=localhost:8082 \\
    python scripts/load_alpaca_data.py --symbol AAPL --with-news

Environment
-----------
ALPACA_API_KEY     Alpaca API key ID (required)
ALPACA_SECRET_KEY  Alpaca API secret key (required)
KDBX_ENDPOINT      host:port of KDB-X (required unless --parquet-only)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ALPACA_DATA_URL = "https://data.alpaca.markets"


# ---------------------------------------------------------------------------
# Alpaca API helpers
# ---------------------------------------------------------------------------

def _headers() -> dict[str, str]:
    key = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        logger.error("Set ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables")
        sys.exit(1)
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def fetch_bars(
    symbol: str,
    start: str,
    end: str,
    timeframe: str = "1Day",
) -> pd.DataFrame:
    """Fetch historical bars from Alpaca.

    Parameters
    ----------
    symbol : str
        Ticker symbol (e.g. ``"AAPL"``).
    start, end : str
        ISO-8601 date strings (``"2024-03-01"``).
    timeframe : str
        Alpaca timeframe: ``"1Min"``, ``"1Hour"``, ``"1Day"``, etc.

    Returns
    -------
    pd.DataFrame
        Columns matching ``market_ticks`` schema.
    """
    url = f"{ALPACA_DATA_URL}/v2/stocks/{symbol}/bars"
    all_bars: list[dict] = []
    page_token = None

    while True:
        params: dict = {
            "start": start,
            "end": end,
            "timeframe": timeframe,
            "limit": 10000,
            "feed": "iex",
        }
        if page_token:
            params["page_token"] = page_token

        resp = requests.get(url, headers=_headers(), params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        bars = data.get("bars") or []
        if not bars:
            break
        all_bars.extend(bars)
        logger.info("Fetched %d bars (total: %d)", len(bars), len(all_bars))

        page_token = data.get("next_page_token")
        if not page_token:
            break

    if not all_bars:
        logger.warning("No bars returned for %s", symbol)
        return pd.DataFrame()

    df = pd.DataFrame(all_bars)
    df = df.rename(columns={
        "t": "timestamp",
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
        "v": "volume",
        "vw": "vwap",
        "n": "trade_count",
    })
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["sym"] = symbol
    df["source"] = "alpaca"

    cols = ["sym", "timestamp", "open", "high", "low", "close",
            "volume", "vwap", "trade_count", "source"]
    return df[cols].sort_values("timestamp").reset_index(drop=True)


def derive_order_book(bars_df: pd.DataFrame) -> pd.DataFrame:
    """Derive order_book from bar data with realistic spread.

    AAPL typically has a 1-2 cent spread. We use 0.01% of price
    (floored at $0.01) to approximate NBBO.
    """
    book = bars_df[["sym", "timestamp", "close"]].copy()
    half_spread = (book["close"] * 0.0001).clip(lower=0.005)
    book["bid_price"] = (book["close"] - half_spread).round(4)
    book["ask_price"] = (book["close"] + half_spread).round(4)
    book["bid_size"] = 100
    book["ask_size"] = 100
    book["mid"] = book["close"].round(4)
    book["spread"] = (half_spread * 2).round(4)
    return book.drop(columns=["close"])


def fetch_news(
    symbol: str,
    start: str,
    end: str,
    limit: int = 200,
) -> pd.DataFrame:
    """Fetch news headlines from Alpaca News API.

    Returns a DataFrame with columns ready for ``flywheel_logs`` insertion.
    """
    url = f"{ALPACA_DATA_URL}/v1beta1/news"
    all_news: list[dict] = []
    page_token = None

    while len(all_news) < limit:
        params: dict = {
            "symbols": symbol,
            "start": start,
            "end": end,
            "limit": min(50, limit - len(all_news)),
            "sort": "desc",
        }
        if page_token:
            params["page_token"] = page_token

        resp = requests.get(url, headers=_headers(), params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        news = data.get("news") or []
        if not news:
            break
        all_news.extend(news)
        logger.info("Fetched %d news articles (total: %d)", len(news), len(all_news))

        page_token = data.get("next_page_token")
        if not page_token:
            break

    if not all_news:
        logger.warning("No news returned for %s", symbol)
        return pd.DataFrame()

    records = []
    for item in all_news:
        headline = item.get("headline", "")
        # Format as a classification request matching the flywheel prompt format
        request_obj = {
            "model": "teacher",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Classify the following financial news headline for {symbol}: "
                        f'"{headline}"'
                    ),
                }
            ],
        }
        response_obj = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",  # empty — teacher will label these
                    }
                }
            ],
        }
        records.append({
            "doc_id": str(uuid.uuid4()),
            "workload_id": f"alpaca-news-{symbol.lower()}",
            "client_id": "alpaca-poc",
            "timestamp": item.get("created_at", ""),
            "request": json.dumps(request_obj),
            "response": json.dumps(response_obj),
        })

    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Parquet output
# ---------------------------------------------------------------------------

def save_parquet(bars_df: pd.DataFrame, book_df: pd.DataFrame, out_dir: Path) -> Path:
    """Save combined market data as Parquet compatible with load_parquet_data().

    The output Parquet has all columns from both market_ticks and order_book
    schemas, merged on (sym, timestamp).
    """
    combined = bars_df.merge(book_df, on=["sym", "timestamp"], how="left")
    out_path = out_dir / "market_data.parquet"
    combined.to_parquet(out_path, index=False)
    logger.info("Saved %d rows to %s", len(combined), out_path)
    return out_path


def save_news_parquet(news_df: pd.DataFrame, out_dir: Path) -> Path:
    """Save news headlines as Parquet."""
    out_path = out_dir / "news_headlines.parquet"
    news_df.to_parquet(out_path, index=False)
    logger.info("Saved %d news articles to %s", len(news_df), out_path)
    return out_path


# ---------------------------------------------------------------------------
# KDB-X loading
# ---------------------------------------------------------------------------

def _ts_to_q(ts: pd.Timestamp) -> str:
    """Convert pandas Timestamp to q timestamp literal."""
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.isoformat().replace("-", ".").replace("T", "D")


def load_into_kdbx(parquet_path: Path) -> dict[str, int]:
    """Load Parquet into KDB-X using IPC-safe PyKX (no license required).

    Uses q string expressions to avoid the 8-parameter IPC limit
    and the categorical/license issue with ``kx.toq()``.
    """
    from kdbx.connection import pykx_connection
    from kdbx.market_tables import create_market_tables

    create_market_tables(drop_existing=False)

    df = pd.read_parquet(parquet_path)
    logger.info("Read %d rows from %s", len(df), parquet_path)

    # --- market_ticks ---
    ticks = df[["sym", "timestamp", "open", "high", "low", "close",
                "volume", "vwap", "trade_count", "source"]].copy()
    ticks = ticks.sort_values(["sym", "timestamp"]).reset_index(drop=True)

    # --- order_book ---
    book = df[["sym", "timestamp", "bid_price", "bid_size",
               "ask_price", "ask_size", "mid", "spread"]].copy()
    book = book.sort_values(["sym", "timestamp"]).reset_index(drop=True)

    with pykx_connection() as q:
        # Insert market_ticks row-by-row via q expressions (no param limit)
        for _, r in ticks.iterrows():
            ts_q = _ts_to_q(r["timestamp"])
            q(
                f'`market_ticks insert `sym`timestamp`open`high`low`close`volume`vwap`trade_count`source!'
                f'(`$"{r["sym"]}";{ts_q};{r["open"]};{r["high"]};{r["low"]};'
                f'{r["close"]};{int(r["volume"])};{r["vwap"]};{int(r["trade_count"])};`$"{r["source"]}")'
            )
        q("`sym`timestamp xasc `market_ticks")
        tick_count = int(q("count market_ticks").py())
        logger.info("Inserted %d rows into market_ticks", tick_count)

        # Insert order_book
        for _, r in book.iterrows():
            ts_q = _ts_to_q(r["timestamp"])
            q(
                f'`order_book insert `sym`timestamp`bid_price`bid_size`ask_price`ask_size`mid`spread!'
                f'(`$"{r["sym"]}";{ts_q};{r["bid_price"]};{int(r["bid_size"])};'
                f'{r["ask_price"]};{int(r["ask_size"])};{r["mid"]};{r["spread"]})'
            )
        q("`sym`timestamp xasc `order_book")
        book_count = int(q("count order_book").py())
        logger.info("Inserted %d rows into order_book", book_count)

    return {"market_ticks": tick_count, "order_book": book_count}


def load_news_into_kdbx(news_df: pd.DataFrame) -> int:
    """Insert news records into flywheel_logs table."""
    import pykx as kx

    from kdbx.connection import pykx_connection
    from kdbx.schema import create_all_tables

    # Ensure tables exist
    create_all_tables(drop_existing=False)

    count = 0
    with pykx_connection() as q:
        for _, row in news_df.iterrows():
            q(
                "{[d;w;c;t;rq;rs] `flywheel_logs insert `doc_id`workload_id`client_id`timestamp`request`response!(d;w;c;t;rq;rs)}",
                kx.SymbolAtom(row["doc_id"]),
                kx.SymbolAtom(row["workload_id"]),
                kx.SymbolAtom(row["client_id"]),
                kx.TimestampAtom(row["timestamp"].to_pydatetime()),
                str(row["request"]),
                str(row["response"]),
            )
            count += 1

        logger.info("Inserted %d records into flywheel_logs", count)
    return count


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch real market data from Alpaca for POC",
    )
    parser.add_argument("--symbol", default="AAPL", help="Ticker symbol (default: AAPL)")
    parser.add_argument(
        "--days", type=int, default=365,
        help="Number of calendar days of history (default: 365)",
    )
    parser.add_argument(
        "--timeframe", default="1Day",
        help="Bar timeframe: 1Min, 1Hour, 1Day (default: 1Day)",
    )
    parser.add_argument(
        "--parquet-only", action="store_true",
        help="Save Parquet files only, skip KDB-X loading",
    )
    parser.add_argument(
        "--with-news", action="store_true",
        help="Also fetch news headlines and load into flywheel_logs",
    )
    parser.add_argument(
        "--news-limit", type=int, default=200,
        help="Max news articles to fetch (default: 200)",
    )
    parser.add_argument(
        "--out-dir", default="data/alpaca",
        help="Output directory for Parquet files (default: data/alpaca)",
    )
    args = parser.parse_args()

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    start_str = start.strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")

    logger.info(
        "Fetching %s data for %s from %s to %s",
        args.timeframe, args.symbol, start_str, end_str,
    )

    # -- Fetch bars --
    bars_df = fetch_bars(args.symbol, start_str, end_str, args.timeframe)
    if bars_df.empty:
        logger.error("No bar data returned. Check your Alpaca credentials and symbol.")
        sys.exit(1)
    logger.info("Got %d bars for %s", len(bars_df), args.symbol)

    # -- Derive order book --
    book_df = derive_order_book(bars_df)

    # -- Save Parquet --
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = save_parquet(bars_df, book_df, out_dir)

    # -- Fetch news --
    news_df = pd.DataFrame()
    if args.with_news:
        news_df = fetch_news(args.symbol, start_str, end_str, args.news_limit)
        if not news_df.empty:
            save_news_parquet(news_df, out_dir)

    # -- Load into KDB-X --
    if not args.parquet_only:
        logger.info("Loading market data into KDB-X...")
        counts = load_into_kdbx(parquet_path)
        logger.info("KDB-X market data: %s", counts)

        if args.with_news and not news_df.empty:
            logger.info("Loading %d news articles into flywheel_logs...", len(news_df))
            n = load_news_into_kdbx(news_df)
            logger.info("KDB-X flywheel_logs: %d records", n)

    # -- Summary --
    print(f"\n{'='*60}")
    print(f"  Alpaca POC Data Load — {args.symbol}")
    print(f"{'='*60}")
    print(f"  Period:      {start_str} to {end_str}")
    print(f"  Timeframe:   {args.timeframe}")
    print(f"  Bars:        {len(bars_df):,}")
    print(f"  Order book:  {len(book_df):,} (derived)")
    if args.with_news:
        print(f"  News:        {len(news_df):,} headlines")
    print(f"  Parquet:     {parquet_path}")
    if not args.parquet_only:
        print(f"  KDB-X:       loaded")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
