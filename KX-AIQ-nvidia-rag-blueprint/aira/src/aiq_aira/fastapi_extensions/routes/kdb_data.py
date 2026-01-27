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

"""
KDB+ Historical Data Loading Routes

This module provides endpoints for loading historical stock market data
from Yahoo Finance into KDB+ via MCP (Model Context Protocol).

DEMO FEATURE: This will clear all existing KDB+ tables and load:
- daily: Real OHLCV data from Yahoo Finance
- trade: Synthetic tick trades based on daily data
- quote: Synthetic bid/ask quotes based on daily data

The data loading is performed asynchronously with SSE (Server-Sent Events)
progress streaming to provide real-time feedback to the frontend.
"""

import asyncio
import json
import logging
import os
import random
import uuid
from datetime import datetime, timedelta
from typing import AsyncGenerator, List, Optional

import redis
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# KDB MCP Internal flag - indicates if MCP server is deployed by this blueprint
# When True: Data loader routes are enabled (write operations allowed)
# When False (default): Data loader is disabled (read-only mode for external MCP)
#
# This flag should be set to "true" by helm/docker-compose when deploying the
# internal MCP server. For production deployments pointing to an organization's
# existing MCP server, this should remain "false" to prevent accidental data writes.
KDB_MCP_INTERNAL = os.getenv("KDB_MCP_INTERNAL", "false").lower() == "true"

# Redis client for job state persistence
_redis_client: Optional[redis.Redis] = None
JOB_TTL_SECONDS = 24 * 60 * 60  # 24 hours


def get_redis_client() -> Optional[redis.Redis]:
    """Get or create Redis client for job tracking"""
    global _redis_client
    if _redis_client is None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        try:
            _redis_client = redis.from_url(redis_url, decode_responses=True)
            _redis_client.ping()  # Test connection
            logger.info(f"Connected to Redis at {redis_url}")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Job tracking will be disabled.")
            return None
    return _redis_client


class JobStatus(BaseModel):
    """Job status model for tracking data loading progress"""
    job_id: str
    status: str  # running, completed, failed, cancelled
    symbols: List[str]
    completed_symbols: List[str] = []
    current_symbol: Optional[str] = None
    phase: str = "initializing"
    overall_progress: int = 0
    total_rows: int = 0
    rows_loaded: int = 0
    error: Optional[str] = None
    start_time: str
    last_update: str
    start_date: str
    end_date: str


class JobSummary(BaseModel):
    """Summary model for job list"""
    job_id: str
    status: str
    symbols: List[str]
    overall_progress: int
    rows_loaded: int
    start_time: str


def save_job_state(job: JobStatus) -> bool:
    """Save job state to Redis"""
    client = get_redis_client()
    if client is None:
        return False
    try:
        key = f"kdb:job:{job.job_id}"
        client.setex(key, JOB_TTL_SECONDS, job.model_dump_json())
        # Also track in job list
        client.zadd("kdb:jobs", {job.job_id: datetime.now().timestamp()})
        return True
    except Exception as e:
        logger.error(f"Failed to save job state: {e}")
        return False


def get_job_state(job_id: str) -> Optional[JobStatus]:
    """Get job state from Redis"""
    client = get_redis_client()
    if client is None:
        return None
    try:
        key = f"kdb:job:{job_id}"
        data = client.get(key)
        if data:
            return JobStatus.model_validate_json(data)
        return None
    except Exception as e:
        logger.error(f"Failed to get job state: {e}")
        return None


def list_recent_jobs(limit: int = 10) -> List[JobSummary]:
    """List recent jobs from Redis"""
    client = get_redis_client()
    if client is None:
        return []
    try:
        # Get most recent job IDs
        job_ids = client.zrevrange("kdb:jobs", 0, limit - 1)
        jobs = []
        for job_id in job_ids:
            job = get_job_state(job_id)
            if job:
                jobs.append(JobSummary(
                    job_id=job.job_id,
                    status=job.status,
                    symbols=job.symbols,
                    overall_progress=job.overall_progress,
                    rows_loaded=job.rows_loaded,
                    start_time=job.start_time
                ))
        return jobs
    except Exception as e:
        logger.error(f"Failed to list jobs: {e}")
        return []


def get_active_job() -> Optional[JobStatus]:
    """Get the currently running job, if any"""
    client = get_redis_client()
    if client is None:
        return None
    try:
        job_ids = client.zrevrange("kdb:jobs", 0, 20)  # Check recent jobs
        for job_id in job_ids:
            job = get_job_state(job_id)
            if job and job.status == "running":
                return job
        return None
    except Exception as e:
        logger.error(f"Failed to get active job: {e}")
        return None


def is_job_cancelled(job_id: str) -> bool:
    """Check if a job has been cancelled"""
    job = get_job_state(job_id)
    return job is not None and job.status == "cancelled"

# Import yfinance for fetching stock data
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    logger.warning("yfinance not installed. KDB data loading will use mock data.")

# Import MCP client for KDB+ integration
try:
    from aiq_aira.kdb_tools_nat import get_kdb_nat_client, KDB_ENABLED
except ImportError:
    KDB_ENABLED = False
    get_kdb_nat_client = None
    logger.warning("KDB NAT client not available. KDB data loading will be disabled.")


class LoadHistoricalDataRequest(BaseModel):
    """Request model for loading historical data"""
    symbols: List[str] = Field(..., min_length=1, description="List of stock symbols to load")
    start_date: str = Field(..., description="Start date in YYYY-MM-DD format")
    end_date: str = Field(..., description="End date in YYYY-MM-DD format")


class LoadPublicDataRequest(BaseModel):
    """Request model for loading public data from various sources"""
    symbols: List[str] = Field(..., min_length=1, description="List of stock symbols")
    data_types: List[str] = Field(
        default=["fundamentals", "news"],
        description="Types of data to load: fundamentals, news, financials, recommendations"
    )
    period: str = Field(default="1y", description="Historical period for financials (1y, 2y, 5y)")


async def sse_event(event_type: str, data: dict) -> str:
    """Format an SSE event"""
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


def generate_synthetic_trades(daily_data: list, trades_per_day: int = 50) -> list:
    """
    Generate synthetic trade data based on daily OHLCV.

    For each day, generates trades that:
    - Stay within the day's high/low range
    - Have realistic volume distribution
    - Have timestamps spread throughout trading hours (9:30 AM - 4:00 PM ET)

    Args:
        daily_data: List of daily OHLCV dicts
        trades_per_day: Number of synthetic trades per day

    Returns:
        List of trade dicts with: date, time, sym, price, size
    """
    trades = []

    for day in daily_data:
        date_str = day["date"]
        sym = day["sym"]
        open_price = day["open"]
        high = day["high"]
        low = day["low"]
        close = day["close"]
        volume = day["volume"]

        # Distribute volume across trades
        avg_size = max(100, volume // trades_per_day)

        # Trading hours: 9:30 AM to 4:00 PM (390 minutes)
        for i in range(trades_per_day):
            # Generate time (spread across trading day)
            minutes_from_open = int((i / trades_per_day) * 390) + random.randint(0, 5)
            trade_time = f"{9 + (30 + minutes_from_open) // 60:02d}:{(30 + minutes_from_open) % 60:02d}:00.000"

            # Generate price within day's range
            # Bias towards open at start, close at end
            progress = i / trades_per_day
            base_price = open_price * (1 - progress) + close * progress

            # Add some noise within the day's range
            price_range = high - low
            noise = random.uniform(-0.3, 0.3) * price_range
            price = max(low, min(high, base_price + noise))

            # Generate size with some variation
            size = max(1, int(avg_size * random.uniform(0.1, 3.0)))

            trades.append({
                "date": date_str,
                "time": trade_time,
                "sym": sym,
                "price": round(price, 2),
                "size": size
            })

    return trades


def generate_synthetic_quotes(daily_data: list, quotes_per_day: int = 100) -> list:
    """
    Generate synthetic quote (bid/ask) data based on daily OHLCV.

    For each day, generates quotes that:
    - Have realistic bid/ask spreads (0.01% to 0.1% of price)
    - Stay within the day's high/low range
    - Have timestamps spread throughout trading hours

    Args:
        daily_data: List of daily OHLCV dicts
        quotes_per_day: Number of synthetic quotes per day

    Returns:
        List of quote dicts with: date, time, sym, bid, ask, bsize, asize
    """
    quotes = []

    for day in daily_data:
        date_str = day["date"]
        sym = day["sym"]
        open_price = day["open"]
        high = day["high"]
        low = day["low"]
        close = day["close"]

        for i in range(quotes_per_day):
            # Generate time (spread across trading day)
            minutes_from_open = int((i / quotes_per_day) * 390) + random.randint(0, 3)
            quote_time = f"{9 + (30 + minutes_from_open) // 60:02d}:{(30 + minutes_from_open) % 60:02d}:00.000"

            # Generate mid price (similar to trades)
            progress = i / quotes_per_day
            mid_price = open_price * (1 - progress) + close * progress

            # Add noise within day's range
            price_range = high - low
            noise = random.uniform(-0.2, 0.2) * price_range
            mid_price = max(low, min(high, mid_price + noise))

            # Generate spread (typically 0.01% to 0.1% of price)
            spread_pct = random.uniform(0.0001, 0.001)
            half_spread = mid_price * spread_pct / 2

            bid = round(mid_price - half_spread, 2)
            ask = round(mid_price + half_spread, 2)

            # Generate sizes
            bsize = random.randint(1, 50) * 100
            asize = random.randint(1, 50) * 100

            quotes.append({
                "date": date_str,
                "time": quote_time,
                "sym": sym,
                "bid": bid,
                "ask": ask,
                "bsize": bsize,
                "asize": asize
            })

    return quotes


async def load_fundamentals(symbol: str) -> dict:
    """
    Load company fundamentals from Yahoo Finance.

    Returns dict with company info like market cap, PE ratio, etc.
    """
    if not YFINANCE_AVAILABLE:
        return {"success": False, "message": "yfinance not available", "data": []}

    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info

        if not info:
            return {"success": False, "message": f"No info for {symbol}", "data": []}

        # Extract key fundamentals
        fundamentals = {
            "sym": symbol,
            "date": datetime.now().strftime("%Y.%m.%d"),
            "name": info.get("longName", info.get("shortName", symbol)),
            "sector": info.get("sector", "Unknown"),
            "industry": info.get("industry", "Unknown"),
            "market_cap": float(info.get("marketCap", 0)),
            "pe_ratio": float(info.get("trailingPE", 0)) if info.get("trailingPE") else 0.0,
            "forward_pe": float(info.get("forwardPE", 0)) if info.get("forwardPE") else 0.0,
            "peg_ratio": float(info.get("pegRatio", 0)) if info.get("pegRatio") else 0.0,
            "price_to_book": float(info.get("priceToBook", 0)) if info.get("priceToBook") else 0.0,
            "eps": float(info.get("trailingEps", 0)) if info.get("trailingEps") else 0.0,
            "dividend_yield": float(info.get("dividendYield", 0) or 0) * 100,
            "beta": float(info.get("beta", 0)) if info.get("beta") else 0.0,
            "fifty_two_week_high": float(info.get("fiftyTwoWeekHigh", 0)) if info.get("fiftyTwoWeekHigh") else 0.0,
            "fifty_two_week_low": float(info.get("fiftyTwoWeekLow", 0)) if info.get("fiftyTwoWeekLow") else 0.0,
            "avg_volume": int(info.get("averageVolume", 0)),
            "shares_outstanding": int(info.get("sharesOutstanding", 0)),
        }

        return {"success": True, "message": f"Loaded fundamentals for {symbol}", "data": [fundamentals]}

    except Exception as e:
        logger.error(f"Error loading fundamentals for {symbol}: {e}")
        return {"success": False, "message": str(e), "data": []}


async def load_news(symbol: str, limit: int = 20) -> dict:
    """
    Load recent news for a symbol from Yahoo Finance.

    Returns list of news articles with title, link, timestamp.
    Note: yfinance 1.0+ changed the API structure - news is now nested under 'content'.
    """
    if not YFINANCE_AVAILABLE:
        return {"success": False, "message": "yfinance not available", "data": []}

    try:
        ticker = yf.Ticker(symbol)
        news_list = ticker.news

        if not news_list:
            return {"success": True, "message": f"No news for {symbol}", "data": []}

        news_data = []
        for article in news_list[:limit]:
            # yfinance 1.0+ structure: article['content']['title'], etc.
            content = article.get("content", article)  # Fallback to article itself for old API

            # Get title - try new structure first, then old
            title = content.get("title", "") if isinstance(content, dict) else ""

            # Get publisher - new structure uses provider.displayName
            provider = content.get("provider", {}) if isinstance(content, dict) else {}
            publisher = provider.get("displayName", "Unknown") if isinstance(provider, dict) else "Unknown"

            # Get publication date - new structure uses pubDate (ISO format)
            pub_date_str = content.get("pubDate", "") if isinstance(content, dict) else ""
            if pub_date_str:
                try:
                    # Parse ISO format: "2026-01-07T22:00:38Z"
                    from datetime import datetime as dt
                    pub_dt = dt.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                    pub_date = pub_dt.strftime("%Y.%m.%d")
                    pub_timestamp = pub_dt.strftime("%H:%M:%S.000")
                except Exception:
                    pub_date = datetime.now().strftime("%Y.%m.%d")
                    pub_timestamp = "00:00:00.000"
            else:
                # Fallback to old API structure
                pub_time = article.get("providerPublishTime", 0)
                pub_date = datetime.fromtimestamp(pub_time).strftime("%Y.%m.%d") if pub_time else datetime.now().strftime("%Y.%m.%d")
                pub_timestamp = datetime.fromtimestamp(pub_time).strftime("%H:%M:%S.000") if pub_time else "00:00:00.000"

            # Get link - new structure uses previewUrl or canonicalUrl
            link = ""
            if isinstance(content, dict):
                link = content.get("previewUrl", "")
                if not link:
                    canonical = content.get("canonicalUrl", {})
                    link = canonical.get("url", "") if isinstance(canonical, dict) else ""

            # Get content type
            news_type = content.get("contentType", "STORY") if isinstance(content, dict) else "STORY"

            # Get summary/description - yfinance 1.0+ provides summary in content
            summary = ""
            if isinstance(content, dict):
                summary = content.get("summary", "")
                if not summary:
                    summary = content.get("description", "")

            news_data.append({
                "date": pub_date,
                "time": pub_timestamp,
                "sym": symbol,
                "title": str(title)[:200],  # Truncate long titles
                "summary": str(summary)[:500] if summary else "",  # Short summary/description
                "publisher": str(publisher)[:50],
                "link": str(link)[:500],
                "news_type": str(news_type)[:20],
            })

        return {"success": True, "message": f"Loaded {len(news_data)} news for {symbol}", "data": news_data}

    except Exception as e:
        logger.error(f"Error loading news for {symbol}: {e}")
        return {"success": False, "message": str(e), "data": []}


async def load_recommendations(symbol: str) -> dict:
    """
    Load analyst recommendations (upgrades/downgrades) from Yahoo Finance.

    Returns list of analyst ratings with firm, grade changes, and actions.
    Note: yfinance 1.0+ uses upgrades_downgrades instead of recommendations.
    """
    if not YFINANCE_AVAILABLE:
        return {"success": False, "message": "yfinance not available", "data": []}

    try:
        ticker = yf.Ticker(symbol)

        # yfinance 1.0+ uses upgrades_downgrades for analyst-by-analyst data
        # Old ticker.recommendations now returns aggregated summary data
        recs = None
        try:
            recs = ticker.upgrades_downgrades
        except Exception:
            pass

        if recs is None or recs.empty:
            # Fallback to old API
            try:
                recs = ticker.recommendations
            except Exception:
                pass

        if recs is None or recs.empty:
            return {"success": True, "message": f"No recommendations for {symbol}", "data": []}

        rec_data = []
        # Get last 20 recommendations (most recent first)
        for idx, row in recs.tail(20).iterrows():
            # Handle date from index (DatetimeIndex in upgrades_downgrades)
            if hasattr(idx, 'strftime'):
                date_str = idx.strftime("%Y.%m.%d")
            elif isinstance(idx, (int, float)):
                date_str = datetime.now().strftime("%Y.%m.%d")
            else:
                try:
                    date_str = str(idx)[:10].replace("-", ".")
                    if len(date_str) != 10 or date_str.count(".") != 2:
                        date_str = datetime.now().strftime("%Y.%m.%d")
                except Exception:
                    date_str = datetime.now().strftime("%Y.%m.%d")

            # yfinance 1.0+ columns: Firm, ToGrade, FromGrade, Action
            # Old API columns: Firm, To Grade, From Grade, Action
            firm = row.get("Firm", row.get("firm", "Unknown"))
            to_grade = row.get("ToGrade", row.get("To Grade", ""))
            from_grade = row.get("FromGrade", row.get("From Grade", ""))
            action = row.get("Action", row.get("action", ""))

            rec_data.append({
                "date": date_str,
                "sym": symbol,
                "firm": str(firm)[:50] if firm else "Unknown",
                "to_grade": str(to_grade)[:20] if to_grade else "",
                "from_grade": str(from_grade)[:20] if from_grade else "",
                "action": str(action)[:20] if action else "",
            })

        return {"success": True, "message": f"Loaded {len(rec_data)} recommendations for {symbol}", "data": rec_data}

    except Exception as e:
        logger.error(f"Error loading recommendations for {symbol}: {e}")
        return {"success": False, "message": str(e), "data": []}


async def create_public_data_tables() -> dict:
    """
    Create tables for public data if they don't exist.
    Uses q code to create empty typed tables.
    """
    if not KDB_ENABLED or get_kdb_nat_client is None:
        return {"success": True, "message": "KDB disabled"}

    try:
        client = get_kdb_nat_client()
        await client.initialize()

        # Table creation queries (q code) - creates empty typed tables
        # Using simpler column types that work reliably
        tables = {
            "fundamentals": "`fundamentals set ([]date:`date$();sym:`$();name:();sector:();industry:();market_cap:0f;pe_ratio:0f;forward_pe:0f;peg_ratio:0f;price_to_book:0f;eps:0f;dividend_yield:0f;beta:0f;fifty_two_week_high:0f;fifty_two_week_low:0f;avg_volume:0j;shares_outstanding:0j)",
            "news": "`news set ([]date:`date$();time:`time$();sym:`$();title:();summary:();publisher:();link:();news_type:())",
            "recommendations": "`recommendations set ([]date:`date$();sym:`$();firm:();to_grade:();from_grade:();action:())",
        }

        created = []
        errors = []
        for table_name, create_query in tables.items():
            try:
                # Check if table exists by trying to count it
                check_query = f"`count_{table_name} set count {table_name}"
                check_result = await client.call_tool("kdbx_run_sql_query", {"query": check_query})
                logger.info(f"Table check for {table_name}: {check_result}")

                # If check failed (table doesn't exist), create it
                if check_result.get("error") or check_result.get("isError") or "error" in str(check_result).lower():
                    logger.info(f"Creating table {table_name}...")
                    result = await client.call_tool("kdbx_run_sql_query", {"query": create_query})
                    logger.info(f"Create result for {table_name}: {result}")
                    if not result.get("error") and not result.get("isError"):
                        created.append(table_name)
                    else:
                        errors.append(f"{table_name}: {result}")
                else:
                    logger.info(f"Table {table_name} already exists")
            except Exception as e:
                logger.warning(f"Table check/create for {table_name}: {e}")
                # Try to create anyway
                try:
                    result = await client.call_tool("kdbx_run_sql_query", {"query": create_query})
                    logger.info(f"Fallback create for {table_name}: {result}")
                    if not result.get("error") and not result.get("isError"):
                        created.append(table_name)
                except Exception as e2:
                    errors.append(f"{table_name}: {e2}")

        msg = f"Tables created: {created}" if created else "Tables already exist or failed"
        if errors:
            msg += f", Errors: {errors}"
        logger.info(msg)

        # Refresh schema so the agent knows about the new tables
        if created:
            try:
                logger.info("Refreshing KDB+ schema after creating tables...")
                await client.refresh_schema()
                logger.info("Schema refreshed successfully")
            except Exception as e:
                logger.warning(f"Failed to refresh schema: {e}")

        return {"success": True, "message": msg}

    except Exception as e:
        logger.error(f"Error creating public data tables: {e}")
        return {"success": False, "message": str(e)}


async def insert_public_data(data_type: str, data: list) -> dict:
    """
    Insert public data into KDB+ tables.
    """
    if not data:
        return {"success": True, "message": "No data to insert", "rows_inserted": 0}

    if not KDB_ENABLED or get_kdb_nat_client is None:
        return {"success": True, "message": "KDB disabled (mock)", "rows_inserted": len(data)}

    try:
        client = get_kdb_nat_client()
        await client.initialize()

        rows_inserted = 0

        if data_type == "fundamentals":
            for row in data:
                # q syntax: date is just YYYY.MM.DD, sym has backtick prefix, strings in quotes
                # Escape quotes in string fields
                name = str(row.get('name', '')).replace('"', '\\"')
                sector = str(row.get('sector', '')).replace('"', '\\"')
                industry = str(row.get('industry', '')).replace('"', '\\"')
                query = f'`fundamentals insert ({row["date"]};`{row["sym"]};"{name}";"{sector}";"{industry}";{row["market_cap"]};{row["pe_ratio"]};{row["forward_pe"]};{row["peg_ratio"]};{row["price_to_book"]};{row["eps"]};{row["dividend_yield"]};{row["beta"]};{row["fifty_two_week_high"]};{row["fifty_two_week_low"]};{row["avg_volume"]};{row["shares_outstanding"]})'
                result = await client.call_tool("kdbx_run_sql_query", {"query": query})
                if not result.get("error") and not result.get("isError"):
                    rows_inserted += 1
                else:
                    logger.warning(f"Insert failed for fundamentals {row['sym']}: {result}")

        elif data_type == "news":
            for row in data:
                # Escape quotes in string fields
                title = str(row.get('title', '')).replace('"', '\\"')
                summary = str(row.get('summary', '')).replace('"', '\\"')
                publisher = str(row.get('publisher', '')).replace('"', '\\"')
                link = str(row.get('link', '')).replace('"', '\\"')
                news_type = str(row.get('news_type', '')).replace('"', '\\"')
                # q syntax: date is YYYY.MM.DD, time is HH:MM:SS.mmm, sym has backtick
                query = f'`news insert ({row["date"]};{row["time"]};`{row["sym"]};"{title}";"{summary}";"{publisher}";"{link}";"{news_type}")'
                result = await client.call_tool("kdbx_run_sql_query", {"query": query})
                if not result.get("error") and not result.get("isError"):
                    rows_inserted += 1
                else:
                    logger.warning(f"Insert failed for news {row['sym']}: {result}")

        elif data_type == "recommendations":
            for row in data:
                # Escape quotes in string fields
                firm = str(row.get('firm', '')).replace('"', '\\"')
                to_grade = str(row.get('to_grade', '')).replace('"', '\\"')
                from_grade = str(row.get('from_grade', '')).replace('"', '\\"')
                action = str(row.get('action', '')).replace('"', '\\"')
                # q syntax: date is YYYY.MM.DD, sym has backtick
                query = f'`recommendations insert ({row["date"]};`{row["sym"]};"{firm}";"{to_grade}";"{from_grade}";"{action}")'
                result = await client.call_tool("kdbx_run_sql_query", {"query": query})
                if not result.get("error") and not result.get("isError"):
                    rows_inserted += 1
                else:
                    logger.warning(f"Insert failed for recommendations {row['sym']}: {result}")

        return {"success": True, "message": f"Inserted {rows_inserted} rows", "rows_inserted": rows_inserted}

    except Exception as e:
        logger.error(f"Error inserting {data_type}: {e}")
        return {"success": False, "message": str(e), "rows_inserted": 0}


async def generate_public_data_stream(request: LoadPublicDataRequest) -> AsyncGenerator[str, None]:
    """
    Stream progress of loading public data from yfinance.
    """
    symbols = request.symbols
    data_types = request.data_types

    yield await sse_event("progress", {
        "phase": "Starting public data import...",
        "overall_progress": 0,
        "status": "loading"
    })

    # Create tables if needed
    yield await sse_event("progress", {
        "phase": "Preparing tables...",
        "overall_progress": 5,
        "status": "loading"
    })
    await create_public_data_tables()

    total_steps = len(symbols) * len(data_types)
    current_step = 0
    total_rows = 0

    for symbol in symbols:
        for data_type in data_types:
            current_step += 1
            progress = int(5 + (current_step / total_steps) * 90)

            yield await sse_event("progress", {
                "phase": f"Loading {data_type} for {symbol}...",
                "overall_progress": progress,
                "symbol": symbol,
                "data_type": data_type,
                "status": "loading"
            })

            # Fetch data based on type
            if data_type == "fundamentals":
                result = await load_fundamentals(symbol)
            elif data_type == "news":
                result = await load_news(symbol)
            elif data_type == "recommendations":
                result = await load_recommendations(symbol)
            else:
                result = {"success": False, "message": f"Unknown data type: {data_type}", "data": []}

            if result["success"] and result["data"]:
                # Insert into KDB
                insert_result = await insert_public_data(data_type, result["data"])
                total_rows += insert_result.get("rows_inserted", 0)

                yield await sse_event("progress", {
                    "phase": f"Loaded {data_type} for {symbol}",
                    "overall_progress": progress,
                    "symbol": symbol,
                    "data_type": data_type,
                    "status": "complete",
                    "message": f"{insert_result.get('rows_inserted', 0)} rows",
                    "rows_loaded": insert_result.get("rows_inserted", 0)
                })
            else:
                yield await sse_event("progress", {
                    "phase": f"No {data_type} for {symbol}",
                    "overall_progress": progress,
                    "symbol": symbol,
                    "data_type": data_type,
                    "status": "complete",
                    "message": result.get("message", "No data")
                })

            await asyncio.sleep(0.1)

    yield await sse_event("complete", {
        "message": f"Public data import complete - {total_rows} total rows loaded",
        "overall_progress": 100,
        "rows_loaded": total_rows
    })


async def load_symbol_data(symbol: str, start_date: str, end_date: str) -> dict:
    """
    Load historical data for a single symbol from Yahoo Finance.

    Returns a dict with:
    - success: bool
    - daily_rows: int
    - trade_rows: int
    - quote_rows: int
    - message: str
    - daily: list of daily OHLCV dicts
    - trades: list of synthetic trade dicts
    - quotes: list of synthetic quote dicts
    """
    if not YFINANCE_AVAILABLE:
        # Return mock data for testing
        return {
            "success": True,
            "daily_rows": 252,
            "trade_rows": 12600,
            "quote_rows": 25200,
            "message": f"Mock data for {symbol} (yfinance not installed)",
            "daily": [],
            "trades": [],
            "quotes": []
        }

    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(start=start_date, end=end_date)

        if hist.empty:
            return {
                "success": False,
                "daily_rows": 0,
                "trade_rows": 0,
                "quote_rows": 0,
                "message": f"No data found for {symbol}",
                "daily": [],
                "trades": [],
                "quotes": []
            }

        # Convert to list of dicts for daily table
        daily_data = []
        for date, row in hist.iterrows():
            daily_data.append({
                "date": date.strftime("%Y.%m.%d"),
                "sym": symbol,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]),
            })

        # Generate synthetic trade and quote data (reduced volume for demo)
        trades = generate_synthetic_trades(daily_data, trades_per_day=5)
        quotes = generate_synthetic_quotes(daily_data, quotes_per_day=10)

        return {
            "success": True,
            "daily_rows": len(daily_data),
            "trade_rows": len(trades),
            "quote_rows": len(quotes),
            "message": f"Loaded {len(daily_data)} days, {len(trades)} trades, {len(quotes)} quotes for {symbol}",
            "daily": daily_data,
            "trades": trades,
            "quotes": quotes
        }

    except Exception as e:
        logger.error(f"Error loading data for {symbol}: {e}")
        return {
            "success": False,
            "daily_rows": 0,
            "trade_rows": 0,
            "quote_rows": 0,
            "message": f"Error: {str(e)}",
            "daily": [],
            "trades": [],
            "quotes": []
        }


async def insert_data_to_kdb(symbol: str, data: dict, progress_callback=None) -> dict:
    """
    Insert all data (daily, trades, quotes) into KDB+ via MCP using batch inserts.

    Args:
        symbol: Stock symbol
        data: Dict with daily, trades, quotes lists
        progress_callback: Optional async callback(rows_done, total_rows) for progress updates

    Returns a dict with:
    - success: bool
    - message: str
    - rows_inserted: int
    """
    daily_rows = data.get("daily", [])
    trade_rows = data.get("trades", [])
    quote_rows = data.get("quotes", [])
    total_rows = len(daily_rows) + len(trade_rows) + len(quote_rows)

    if not KDB_ENABLED or get_kdb_nat_client is None:
        # Mock insertion for testing
        await asyncio.sleep(0.5)
        return {
            "success": True,
            "message": f"Mock insertion for {symbol} (KDB disabled)",
            "rows_inserted": total_rows
        }

    try:
        client = get_kdb_nat_client()
        if client is None:
            return {
                "success": False,
                "message": "KDB client not available",
                "rows_inserted": 0
            }

        await client.initialize()
        rows_inserted = 0
        batch_size = 100  # Insert 100 rows per batch

        # Helper to build q insert query for a batch
        def build_daily_batch_query(rows):
            dates = ";".join([str(r['date']) for r in rows])
            syms = ";".join([f"`{r['sym']}" for r in rows])
            opens = ";".join([str(r['open']) for r in rows])
            highs = ";".join([str(r['high']) for r in rows])
            lows = ";".join([str(r['low']) for r in rows])
            closes = ";".join([str(r['close']) for r in rows])
            volumes = ";".join([str(r['volume']) for r in rows])
            return f"`daily insert flip `date`sym`open`high`low`close`volume!(({dates});({syms});({opens});({highs});({lows});({closes});({volumes}))"

        def build_trade_batch_query(rows):
            dates = ";".join([str(r['date']) for r in rows])
            times = ";".join([str(r['time']) for r in rows])
            syms = ";".join([f"`{r['sym']}" for r in rows])
            prices = ";".join([str(r['price']) for r in rows])
            sizes = ";".join([str(r['size']) for r in rows])
            return f"`trade insert flip `date`time`sym`price`size!(({dates});({times});({syms});({prices});({sizes}))"

        def build_quote_batch_query(rows):
            dates = ";".join([str(r['date']) for r in rows])
            times = ";".join([str(r['time']) for r in rows])
            syms = ";".join([f"`{r['sym']}" for r in rows])
            bids = ";".join([str(r['bid']) for r in rows])
            asks = ";".join([str(r['ask']) for r in rows])
            bsizes = ";".join([str(r['bsize']) for r in rows])
            asizes = ";".join([str(r['asize']) for r in rows])
            return f"`quote insert flip `date`time`sym`bid`ask`bsize`asize!(({dates});({times});({syms});({bids});({asks});({bsizes});({asizes}))"

        # Insert daily data in batches
        for i in range(0, len(daily_rows), batch_size):
            batch = daily_rows[i:i + batch_size]
            query = build_daily_batch_query(batch)
            result = await client.call_tool("kdbx_run_sql_query", {"query": query})
            is_error = result.get("isError", False) or result.get("error")
            if not is_error:
                rows_inserted += len(batch)
            else:
                logger.warning(f"Batch insert failed for daily {symbol} batch {i}: {result}")
            if progress_callback:
                await progress_callback(rows_inserted, total_rows)

        # Insert trade data in batches
        for i in range(0, len(trade_rows), batch_size):
            batch = trade_rows[i:i + batch_size]
            query = build_trade_batch_query(batch)
            result = await client.call_tool("kdbx_run_sql_query", {"query": query})
            is_error = result.get("isError", False) or result.get("error")
            if not is_error:
                rows_inserted += len(batch)
            else:
                logger.warning(f"Batch insert failed for trade {symbol} batch {i}: {result}")
            if progress_callback:
                await progress_callback(rows_inserted, total_rows)

        # Insert quote data in batches
        for i in range(0, len(quote_rows), batch_size):
            batch = quote_rows[i:i + batch_size]
            query = build_quote_batch_query(batch)
            result = await client.call_tool("kdbx_run_sql_query", {"query": query})
            is_error = result.get("isError", False) or result.get("error")
            if not is_error:
                rows_inserted += len(batch)
            else:
                logger.warning(f"Batch insert failed for quote {symbol} batch {i}: {result}")
            if progress_callback:
                await progress_callback(rows_inserted, total_rows)

        return {
            "success": True,
            "message": f"Inserted {rows_inserted} rows for {symbol}",
            "rows_inserted": rows_inserted
        }

    except Exception as e:
        logger.error(f"Error inserting data to KDB for {symbol}: {e}")
        return {
            "success": False,
            "message": f"Error: {str(e)}",
            "rows_inserted": 0
        }


async def clear_kdb_tables() -> dict:
    """
    Clear all KDB+ tables (daily, trade, quote) before loading new data.

    Returns a dict with:
    - success: bool
    - message: str
    """
    if not KDB_ENABLED or get_kdb_nat_client is None:
        await asyncio.sleep(0.3)
        return {
            "success": True,
            "message": "Mock table clear (KDB disabled)"
        }

    try:
        client = get_kdb_nat_client()
        if client is None:
            return {
                "success": False,
                "message": "KDB client not available"
            }

        await client.initialize()

        tables_cleared = []

        # Clear each table
        for table in ["daily", "trade", "quote"]:
            queries = [
                f"DELETE FROM {table}",
                f"{table}: 0#{table}",
            ]

            for query in queries:
                try:
                    result = await client.call_tool("kdbx_run_sql_query", {"query": query})
                    if not result.get("error"):
                        tables_cleared.append(table)
                        break
                except Exception as e:
                    logger.debug(f"Clear query failed: {query}, error: {e}")
                    continue

        if tables_cleared:
            return {
                "success": True,
                "message": f"Cleared tables: {', '.join(tables_cleared)}"
            }
        else:
            return {
                "success": True,
                "message": "Tables prepared for loading"
            }

    except Exception as e:
        logger.error(f"Error clearing KDB tables: {e}")
        return {
            "success": False,
            "message": f"Error: {str(e)}"
        }


async def generate_progress_stream(
    request: LoadHistoricalDataRequest,
    job_id: Optional[str] = None,
    resume_from: Optional[List[str]] = None
) -> AsyncGenerator[str, None]:
    """
    Generate SSE progress stream for data loading.

    NOTE: This is a DEMO feature. It will:
    1. Clear all KDB+ tables (daily, trade, quote) - unless resuming
    2. Fetch OHLCV data from Yahoo Finance for each symbol
    3. Generate synthetic trade and quote data
    4. Insert all data into KDB+ via MCP
    5. Stream progress updates to the client

    Args:
        request: Load request with symbols and date range
        job_id: Optional job ID for tracking (generated if not provided)
        resume_from: List of already completed symbols (skip these)
    """
    symbols = request.symbols
    total_symbols = len(symbols)
    completed_symbols = resume_from or []
    is_resume = bool(resume_from)

    # Generate or use provided job ID
    if job_id is None:
        job_id = str(uuid.uuid4())

    # Create initial job state
    now = datetime.now().isoformat()
    job = JobStatus(
        job_id=job_id,
        status="running",
        symbols=symbols,
        completed_symbols=completed_symbols,
        current_symbol=None,
        phase="initializing",
        overall_progress=0,
        total_rows=0,
        rows_loaded=0,
        error=None,
        start_time=now,
        last_update=now,
        start_date=request.start_date,
        end_date=request.end_date
    )
    save_job_state(job)

    # Send job_id in first event so client can track
    yield await sse_event("progress", {
        "job_id": job_id,
        "phase": "Starting data load..." if not is_resume else "Resuming data load...",
        "overall_progress": 0,
        "symbol": None,
        "status": "loading"
    })

    # Phase 0: Clear existing tables (skip if resuming)
    if not is_resume:
        job.phase = "clearing"
        job.last_update = datetime.now().isoformat()
        save_job_state(job)

        yield await sse_event("progress", {
            "job_id": job_id,
            "phase": "Clearing existing tables...",
            "overall_progress": 2,
            "symbol": None,
            "status": "loading",
            "message": "Clearing daily, trade, and quote tables"
        })

        clear_result = await clear_kdb_tables()
        if not clear_result["success"]:
            job.status = "failed"
            job.error = f"Failed to clear tables: {clear_result['message']}"
            job.last_update = datetime.now().isoformat()
            save_job_state(job)
            yield await sse_event("error", {
                "job_id": job_id,
                "message": job.error
            })
            return

        yield await sse_event("progress", {
            "job_id": job_id,
            "phase": "Tables cleared",
            "overall_progress": 5,
            "symbol": None,
            "status": "complete",
            "message": clear_result["message"]
        })

        await asyncio.sleep(0.2)
    else:
        # Skip to 5% if resuming
        yield await sse_event("progress", {
            "job_id": job_id,
            "phase": "Resuming - skipping table clear",
            "overall_progress": 5,
            "symbol": None,
            "status": "complete",
            "message": f"Resuming from {len(completed_symbols)} completed symbols"
        })

    all_data = {}

    # Phase 1: Fetch data from Yahoo Finance and generate synthetic data
    job.phase = "fetching"
    job.last_update = datetime.now().isoformat()
    save_job_state(job)

    for i, symbol in enumerate(symbols):
        # Skip already completed symbols (resume case)
        if symbol in completed_symbols:
            continue

        # Check for cancellation
        if is_job_cancelled(job_id):
            job.status = "cancelled"
            job.last_update = datetime.now().isoformat()
            save_job_state(job)
            yield await sse_event("error", {
                "job_id": job_id,
                "message": "Job cancelled by user"
            })
            return

        job.current_symbol = symbol
        job.last_update = datetime.now().isoformat()
        save_job_state(job)

        yield await sse_event("progress", {
            "job_id": job_id,
            "phase": f"Fetching {symbol} from Yahoo Finance...",
            "overall_progress": int(5 + (i / total_symbols) * 35),
            "symbol": symbol,
            "status": "loading",
            "message": "Downloading OHLCV + generating synthetic trades/quotes"
        })

        result = await load_symbol_data(symbol, request.start_date, request.end_date)
        all_data[symbol] = result

        if result["success"]:
            total_rows = result["daily_rows"] + result["trade_rows"] + result["quote_rows"]
            job.total_rows += total_rows
            job.last_update = datetime.now().isoformat()
            save_job_state(job)

            yield await sse_event("progress", {
                "job_id": job_id,
                "phase": f"Generated data for {symbol}",
                "overall_progress": int(5 + ((i + 1) / total_symbols) * 35),
                "symbol": symbol,
                "status": "complete",
                "message": f"{result['daily_rows']} daily + {result['trade_rows']} trades + {result['quote_rows']} quotes",
                "rows_loaded": total_rows
            })
        else:
            yield await sse_event("progress", {
                "job_id": job_id,
                "phase": f"Failed to fetch {symbol}",
                "overall_progress": int(5 + ((i + 1) / total_symbols) * 35),
                "symbol": symbol,
                "status": "error",
                "message": result["message"],
                "rows_loaded": 0
            })

        await asyncio.sleep(0.1)

    # Phase 2: Insert data into KDB+
    job.phase = "inserting"
    job.last_update = datetime.now().isoformat()
    save_job_state(job)

    for i, symbol in enumerate(symbols):
        # Skip already completed symbols (resume case)
        if symbol in completed_symbols:
            continue

        if symbol not in all_data or not all_data[symbol]["success"]:
            continue

        # Check for cancellation
        if is_job_cancelled(job_id):
            job.status = "cancelled"
            job.last_update = datetime.now().isoformat()
            save_job_state(job)
            yield await sse_event("error", {
                "job_id": job_id,
                "message": "Job cancelled by user"
            })
            return

        job.current_symbol = symbol
        job.last_update = datetime.now().isoformat()
        save_job_state(job)

        data = all_data[symbol]
        total_rows = data["daily_rows"] + data["trade_rows"] + data["quote_rows"]

        yield await sse_event("progress", {
            "job_id": job_id,
            "phase": f"Inserting {symbol} into KDB+...",
            "overall_progress": int(40 + (i / total_symbols) * 60),
            "symbol": symbol,
            "status": "loading",
            "message": f"Inserting {total_rows} rows into daily/trade/quote tables"
        })

        result = await insert_data_to_kdb(symbol, data)

        # Mark symbol as completed after successful insertion
        if result["success"]:
            job.completed_symbols.append(symbol)
            job.rows_loaded += result["rows_inserted"]
            job.overall_progress = int(40 + ((i + 1) / total_symbols) * 60)

        job.last_update = datetime.now().isoformat()
        save_job_state(job)

        yield await sse_event("progress", {
            "job_id": job_id,
            "phase": f"Inserted {symbol}",
            "overall_progress": int(40 + ((i + 1) / total_symbols) * 60),
            "symbol": symbol,
            "status": "complete" if result["success"] else "error",
            "message": result["message"],
            "rows_loaded": result["rows_inserted"]
        })

        await asyncio.sleep(0.1)

    # Complete
    job.status = "completed"
    job.phase = "complete"
    job.overall_progress = 100
    job.current_symbol = None
    job.last_update = datetime.now().isoformat()
    save_job_state(job)

    yield await sse_event("complete", {
        "job_id": job_id,
        "message": "Data loading complete - all tables populated",
        "overall_progress": 100,
        "rows_loaded": job.rows_loaded
    })


async def add_kdb_data_routes(app: FastAPI):
    """Add KDB data loading routes to the FastAPI app.

    NOTE: These routes perform WRITE operations (clear tables, insert data) and are
    only enabled when KDB_MCP_INTERNAL=true. This flag indicates the MCP server was
    deployed by this blueprint (helm/docker-compose) and is safe for testing.

    For production deployments using an external MCP server, these routes are disabled
    to prevent accidental data modifications.
    """

    # Check if data loader should be enabled
    if not KDB_MCP_INTERNAL:
        logger.info(
            "KDB data loader routes DISABLED (KDB_MCP_INTERNAL=false). "
            "Set KDB_MCP_INTERNAL=true only when using the blueprint's internal MCP server."
        )
        return

    logger.info("KDB data loader routes ENABLED (KDB_MCP_INTERNAL=true)")

    async def load_historical_data(request: LoadHistoricalDataRequest):
        """
        Load historical stock data from Yahoo Finance into KDB+.

        DEMO FEATURE: This will clear ALL existing KDB+ tables and replace with:
        - daily: Real OHLCV data from Yahoo Finance
        - trade: Synthetic tick trades based on daily data
        - quote: Synthetic bid/ask quotes based on daily data

        Returns an SSE stream with progress updates.
        """
        # Validate dates
        try:
            start = datetime.strptime(request.start_date, "%Y-%m-%d")
            end = datetime.strptime(request.end_date, "%Y-%m-%d")
            if start >= end:
                raise ValueError("Start date must be before end date")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Check for already running job
        active_job = get_active_job()
        if active_job:
            raise HTTPException(
                status_code=409,
                detail=f"A job is already running (job_id: {active_job.job_id}). "
                "Wait for it to complete or cancel it first."
            )

        return StreamingResponse(
            generate_progress_stream(request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )

    async def list_jobs(limit: int = 10):
        """
        List recent KDB data loading jobs.

        Returns up to `limit` recent jobs sorted by start time (most recent first).
        """
        jobs = list_recent_jobs(limit)
        return {"jobs": [job.model_dump() for job in jobs]}

    async def get_job(job_id: str):
        """
        Get detailed status of a specific job.

        Use this endpoint to poll for job status when SSE connection is lost.
        """
        job = get_job_state(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        return job.model_dump()

    async def get_active():
        """
        Get the currently running job, if any.

        Returns the active job or null if no job is running.
        """
        job = get_active_job()
        if job is None:
            return {"active_job": None}
        return {"active_job": job.model_dump()}

    async def cancel_job(job_id: str):
        """
        Cancel a running job.

        Sets the job status to 'cancelled'. The job will stop
        at the next checkpoint (between symbols).
        """
        job = get_job_state(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        if job.status != "running":
            raise HTTPException(
                status_code=400,
                detail=f"Job is not running (status: {job.status})"
            )

        job.status = "cancelled"
        job.last_update = datetime.now().isoformat()
        save_job_state(job)

        return {
            "message": f"Job {job_id} marked for cancellation",
            "job_id": job_id
        }

    async def retry_job(job_id: str):
        """
        Retry a failed or cancelled job.

        Creates a new job that resumes from where the original job left off.
        Successfully completed symbols will be skipped.
        """
        job = get_job_state(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        if job.status == "running":
            raise HTTPException(
                status_code=400,
                detail="Cannot retry a running job. Cancel it first."
            )

        if job.status == "completed":
            raise HTTPException(
                status_code=400,
                detail="Job already completed successfully. Start a new job instead."
            )

        # Check for already running job
        active_job = get_active_job()
        if active_job:
            raise HTTPException(
                status_code=409,
                detail=f"A job is already running (job_id: {active_job.job_id}). "
                "Wait for it to complete or cancel it first."
            )

        # Create new job that resumes from completed symbols
        new_job_id = str(uuid.uuid4())
        request = LoadHistoricalDataRequest(
            symbols=job.symbols,
            start_date=job.start_date,
            end_date=job.end_date
        )

        # Determine remaining symbols
        remaining_symbols = [s for s in job.symbols if s not in job.completed_symbols]

        return StreamingResponse(
            generate_progress_stream(
                request,
                job_id=new_job_id,
                resume_from=job.completed_symbols
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-New-Job-Id": new_job_id,
                "X-Resuming-From": ",".join(job.completed_symbols),
                "X-Symbols-Remaining": ",".join(remaining_symbols),
            }
        )

    # Add the routes (nginx strips /api prefix, so use /kdb/... paths)
    app.add_api_route(
        "/kdb/load-historical",
        load_historical_data,
        methods=["POST"],
        tags=["kdb-endpoints"],
        summary="Load historical stock data into KDB+ (DEMO - clears all tables)"
    )

    app.add_api_route(
        "/kdb/jobs",
        list_jobs,
        methods=["GET"],
        tags=["kdb-endpoints"],
        summary="List recent data loading jobs"
    )

    app.add_api_route(
        "/kdb/jobs/active",
        get_active,
        methods=["GET"],
        tags=["kdb-endpoints"],
        summary="Get currently running job"
    )

    app.add_api_route(
        "/kdb/jobs/{job_id}",
        get_job,
        methods=["GET"],
        tags=["kdb-endpoints"],
        summary="Get status of a specific job"
    )

    app.add_api_route(
        "/kdb/jobs/{job_id}/cancel",
        cancel_job,
        methods=["POST"],
        tags=["kdb-endpoints"],
        summary="Cancel a running job"
    )

    app.add_api_route(
        "/kdb/jobs/{job_id}/retry",
        retry_job,
        methods=["POST"],
        tags=["kdb-endpoints"],
        summary="Retry a failed or cancelled job"
    )

    async def load_public_data(request: LoadPublicDataRequest):
        """
        Load public data (fundamentals, news, recommendations) from Yahoo Finance into KDB+.

        This endpoint fetches additional financial data from public sources and stores it
        in KDB+ tables for use in research queries.

        Available data types:
        - fundamentals: Company info (market cap, PE ratio, EPS, etc.)
        - news: Recent news articles
        - recommendations: Analyst ratings

        Returns an SSE stream with progress updates.
        """
        # Validate data types
        valid_types = {"fundamentals", "news", "recommendations"}
        invalid_types = set(request.data_types) - valid_types
        if invalid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid data types: {invalid_types}. Valid types: {valid_types}"
            )

        return StreamingResponse(
            generate_public_data_stream(request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )

    app.add_api_route(
        "/kdb/load-public",
        load_public_data,
        methods=["POST"],
        tags=["kdb-endpoints"],
        summary="Load public data (fundamentals, news, recommendations) into KDB+"
    )

    logger.info("Added KDB data loading routes with job tracking")
