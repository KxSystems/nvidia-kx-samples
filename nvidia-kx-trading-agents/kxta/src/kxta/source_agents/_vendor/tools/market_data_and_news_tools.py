# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Vendored into the KXTA source-agents layer from the KX "agentic-anomaly-market-research" project
# (faithful copy; imports rewritten and heavy imports made lazy -- no logic changes).
import asyncio
import aiohttp
import re
import requests
from typing import List, Dict, Any
from langchain_core.tools import tool
import os


class MarketDataAndNewsTools:
    """Wrapper for Alpha Vantage API operations."""

    def __init__(self):
        from langchain_community.utilities.alpha_vantage import AlphaVantageAPIWrapper
        self.api_key = os.getenv("ALPHAVANTAGE_API_KEY")
        if not self.api_key:
            raise ValueError("ALPHAVANTAGE_API_KEY must be set in environment variables")
        # Set env var for AlphaVantageAPIWrapper to use
        os.environ["ALPHA_VANTAGE_API_KEY"] = self.api_key
        self.alpha_vantage = AlphaVantageAPIWrapper()
        self._ticker_cache = {}  # Cache ticker objects

    def _ticker(self, symbol: str):
        """Get or create cached ticker object."""
        import yfinance as yf
        symbol = symbol.strip().upper()
        if symbol not in self._ticker_cache:
            self._ticker_cache[symbol] = yf.Ticker(symbol)
        return self._ticker_cache[symbol]

    async def _alpha_get_async(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Async Alpha Vantage API call."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except Exception as e:
            return {"error": f"Alpha Vantage request failed: {e}"}

    async def get_news_async(self, symbol: str) -> List[Dict[str, Any]]:
        """Fetch news sentiment data for a stock symbol (async)."""
        symbol = self._validate_symbol(symbol)
        url = "https://www.alphavantage.co/query"
        params = {"function": "NEWS_SENTIMENT", "tickers": symbol, "apikey": self.api_key}

        data = await self._alpha_get_async(url, params)

        if "error" in data:
            raise ValueError(data["error"])
        if "Error Message" in data:
            raise ValueError(f"API error: {data['Error Message']}")
        if "Note" in data:
            raise ValueError(f"Rate limit: {data['Note']}")

        news_feed = data.get("feed", [])
        return [{
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "time_published": item.get("time_published", ""),
            "authors": item.get("authors", []),
            "source_domain": item.get("source_domain", ""),
            "summary": item.get("summary", ""),
        } for item in news_feed]

    def get_news(self, symbol: str) -> List[Dict[str, Any]]:
        """Fetch news sentiment data for a stock symbol (sync wrapper)."""
        try:
            loop = asyncio.get_running_loop()
            return [{"error": "Use async version in async context"}]
        except RuntimeError:
            return asyncio.run(self.get_news_async(symbol))

    def _is_crypto_symbol(self, symbol: str) -> bool:
        """Check if symbol is a cryptocurrency (e.g., BTC-USD, ETH-USD)."""
        crypto_bases = [
            'BTC',
            'ETH',
            'BNB',
            'SOL',
            'ADA',
            'XRP',
            'DOT',
            'DOGE',
            'AVAX',
            'SHIB',
            'MATIC',
            'LTC',
            'UNI',
            'ATOM',
            'ETC',
            'XLM',
            'ALGO',
            'VET',
            'ICP',
            'FIL',
            'TRX',
            'EOS',
            'AAVE',
            'THETA',
            'FTM',
            'AXS',
            'SAND',
            'MANA',
            'GALA',
            'CHZ',
            'ENJ',
            'BAT',
            'ZEC',
            'DASH',
            'XMR',
            'ZRX',
            'OMG',
            'MKR',
            'COMP',
            'SNX',
            'YFI',
            'CRV',
            'SUSHI',
            '1INCH',
            'ALPHA',
            'REN',
            'KNC',
            'BAND',
            'NMR',
            'UMA',
            'LRC',
            'STORJ',
            'SKL',
            'GRT',
            'BAL',
            'MIR',
            'FIDA',
            'RAY',
            'COPE',
            'ALEPH'
        ]
        symbol_upper = symbol.upper()
        if '-' in symbol_upper:
            base = symbol_upper.split('-')[0]
            return base in crypto_bases
        for crypto in crypto_bases:
            if symbol_upper.startswith(crypto) and len(symbol_upper) > len(crypto):
                return True
        return False

    def _validate_symbol(self, symbol: str) -> str:
        """Validate and normalize a symbol. Raises ValueError for unsupported formats."""
        if not symbol or not symbol.strip():
            raise ValueError("Symbol cannot be empty")
        symbol = symbol.strip().upper()
        # Allow: 1-5 uppercase letters, optional dot for class shares (BRK.B), optional dash for crypto (BTC-USD)
        if not re.match(r'^[A-Z]{1,5}(\.[A-Z]{1,2})?(-[A-Z]{1,5})?$', symbol):
            raise ValueError(f"Unsupported symbol format: '{symbol}'. "
                             f"Expected stock ticker (e.g., AAPL), class share (e.g., BRK.B), "
                             f"or crypto pair (e.g., BTC-USD). "
                             f"Futures (CL=F), forex (EUR/USD), and indices (^VIX) are not supported.")
        return symbol

    async def get_quote_async(self, symbol: str) -> Dict[str, Any]:
        """Get real-time quote data for a stock or crypto symbol (async)."""
        symbol = self._validate_symbol(symbol)

        # Use yfinance for crypto symbols (Alpha Vantage doesn't support crypto)
        if self._is_crypto_symbol(symbol):
            try:
                ticker = self._ticker(symbol)
                info = ticker.info
                # Get latest price data
                hist = ticker.history(period="1d", interval="1m")
                if not hist.empty:
                    latest = hist.iloc[-1]
                    # Format to match Alpha Vantage structure for compatibility
                    return {
                        "01. symbol":
                            symbol,
                        "02. open":
                            str(latest['Open']),
                        "03. high":
                            str(latest['High']),
                        "04. low":
                            str(latest['Low']),
                        "05. price":
                            str(latest['Close']),
                        "06. volume":
                            str(int(latest['Volume'])),
                        "07. latest trading day":
                            latest.name.strftime("%Y-%m-%d") if hasattr(latest.name, 'strftime') else str(latest.name),
                        "08. previous close":
                            str(hist.iloc[-2]['Close']) if len(hist) > 1 else str(latest['Close']),
                        "09. change":
                            str(latest['Close'] - (hist.iloc[-2]['Close'] if len(hist) > 1 else latest['Close'])),
                        "10. change percent":
                            f"{((latest['Close'] - (hist.iloc[-2]['Close'] if len(hist) > 1 else latest['Close'])) / (hist.iloc[-2]['Close'] if len(hist) > 1 else latest['Close']) * 100):.2f}%"
                    }
                else:
                    # Fallback to info if history is empty
                    current_price = info.get('regularMarketPrice') or info.get('currentPrice') or info.get(
                        'previousClose', 'N/A')
                    return {
                        "01. symbol": symbol,
                        "05. price": str(current_price),
                        "06. volume": str(info.get('volume24Hr', info.get('regularMarketVolume', 'N/A'))),
                        "09. change": "N/A",
                        "10. change percent": "N/A"
                    }
            except Exception as e:
                return {"error": f"Error fetching crypto quote: {str(e)}"}

        # Use Alpha Vantage for stocks (async)
        try:
            url = "https://www.alphavantage.co/query"
            params = {"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": self.api_key}
            result = await self._alpha_get_async(url, params)

            if "error" in result:
                return result
            # Alpha Vantage returns data nested under 'Global Quote'
            if isinstance(result, dict) and "Global Quote" in result:
                return result["Global Quote"]
            elif isinstance(result, dict):
                return result
            else:
                return {"error": f"Unexpected response format: {type(result)}"}
        except Exception as e:
            return {"error": f"Error fetching stock quote: {str(e)}"}

    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """Get real-time quote data for a stock or crypto symbol (sync wrapper)."""
        try:
            loop = asyncio.get_running_loop()
            return {"error": "Use async version in async context"}
        except RuntimeError:
            return asyncio.run(self.get_quote_async(symbol))


# Singleton instance
_instance = None


def _get_instance() -> MarketDataAndNewsTools:
    """Get or create the singleton instance."""
    global _instance
    if _instance is None:
        _instance = MarketDataAndNewsTools()
    return _instance


@tool
def get_news_tool(symbol: str) -> List[Dict[str, Any]]:
    """
    Retrieve recent news and sentiment data for a stock ticker symbol.

    Args:
        symbol: Stock ticker symbol (e.g., 'AAPL', 'MSFT'). Case-insensitive.

    Returns:
        List of news items with title, url, time_published, authors, source_domain, and summary.
        Returns a list with a single error dict if the request fails.
    """
    try:
        result = _get_instance().get_news(symbol)
        # Ensure we return a list
        if isinstance(result, list):
            return result
        elif isinstance(result, dict):
            # If it's a dict, wrap it in a list
            return [result]
        else:
            return [{"error": f"Unexpected response type: {type(result)}"}]
    except Exception as e:
        error_msg = str(e)
        print(f"[get_news_tool] Error for symbol {symbol}: {error_msg}")
        return [{"error": error_msg, "symbol": symbol}]


@tool
def get_quote_tool(symbol: str) -> Dict[str, Any]:
    """
    Retrieve real-time stock quote data for a ticker symbol.

    Args:
        symbol: Stock ticker symbol (e.g., 'AAPL', 'MSFT'). Case-insensitive.

    Returns:
        Dictionary with quote information (price, volume, high/low, timestamp).
        Returns a dict with an "error" key if the request fails.
    """
    try:
        result = _get_instance().get_quote(symbol)
        # Ensure we return a dict
        if isinstance(result, dict):
            return result
        else:
            return {"error": f"Unexpected response type: {type(result)}", "symbol": symbol}
    except Exception as e:
        error_msg = str(e)
        print(f"[get_quote_tool] Error for symbol {symbol}: {error_msg}")
        return {"error": error_msg, "symbol": symbol}
