# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Vendored into the KXTA source-agents layer from the KX "agentic-anomaly-market-research" project
# (faithful copy; imports rewritten and heavy imports made lazy -- no logic changes).
import asyncio
import aiohttp
import requests
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional
from langchain_core.tools import tool
import os
import json
from datetime import datetime, timedelta


class TechnicalIndicatorsTools:
    """Wrapper for technical indicators operations using Alpha Vantage API and yfinance."""

    def __init__(self):
        self.api_key = os.getenv("ALPHAVANTAGE_API_KEY")
        if not self.api_key:
            raise ValueError("ALPHAVANTAGE_API_KEY must be set in environment variables")
        self._ticker_cache = {}  # Cache ticker objects

    def _ticker(self, symbol: str):
        """Get or create cached ticker object."""
        import yfinance as yf
        symbol = symbol.strip().upper()
        if symbol not in self._ticker_cache:
            self._ticker_cache[symbol] = yf.Ticker(symbol)
        return self._ticker_cache[symbol]

    async def _alpha_get_async(self, function: str, symbol: str, **kwargs) -> Dict[str, Any]:
        """Async Alpha Vantage API call."""
        base_url = "https://www.alphavantage.co/query"
        params = {"function": function, "symbol": symbol.upper(), "apikey": self.api_key, **kwargs}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(base_url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    resp.raise_for_status()
                    data = await resp.json()

                    if "Error Message" in data:
                        return {"error": f"API error: {data['Error Message']}"}
                    if "Note" in data:
                        return {"error": f"Rate limit: {data['Note']}"}

                    return data
        except Exception as e:
            return {"error": f"Alpha Vantage request failed: {e}"}

    async def get_stock_data_async(self, symbol: str, period: str = "1y", interval: str = "1d") -> Dict[str, Any]:
        """
        Fetch historical stock price data using yfinance (async).

        Args:
            symbol: Stock ticker symbol (e.g., 'AAPL', 'MSFT')
            period: Period to fetch (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)
            interval: Data interval (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo)

        Returns:
            Dictionary with stock data in JSON format
        """
        if not symbol or not symbol.strip():
            raise ValueError("Symbol cannot be empty")

        symbol = symbol.strip().upper()

        try:
            ticker = self._ticker(symbol)
            df = ticker.history(period=period, interval=interval)

            if df.empty:
                return {"error": f"No data available for symbol {symbol}"}

            # Convert DataFrame to JSON format
            data = {"symbol": symbol, "period": period, "interval": interval, "data_points": len(df), "data": []}

            for date, row in df.iterrows():
                data["data"].append({
                    "date": date.strftime("%Y-%m-%d %H:%M:%S") if hasattr(date, 'strftime') else str(date),
                    "open": float(row["Open"]) if not pd.isna(row["Open"]) else None,
                    "high": float(row["High"]) if not pd.isna(row["High"]) else None,
                    "low": float(row["Low"]) if not pd.isna(row["Low"]) else None,
                    "close": float(row["Close"]) if not pd.isna(row["Close"]) else None,
                    "volume": int(row["Volume"]) if not pd.isna(row["Volume"]) else None,
                })

            return data
        except Exception as e:
            return {"error": f"Error fetching stock data: {str(e)}"}

    def get_stock_data(self, symbol: str, period: str = "1y", interval: str = "1d") -> Dict[str, Any]:
        """Sync wrapper for get_stock_data_async."""
        try:
            loop = asyncio.get_running_loop()
            return {"error": "Use async version in async context"}
        except RuntimeError:
            return asyncio.run(self.get_stock_data_async(symbol, period, interval))

    def _call_alpha_vantage(self, function: str, symbol: str, **kwargs) -> Dict[str, Any]:
        """Helper method to call Alpha Vantage API (sync wrapper)."""
        try:
            loop = asyncio.get_running_loop()
            return {"error": "Use _alpha_get_async in async context"}
        except RuntimeError:
            return asyncio.run(self._alpha_get_async(function, symbol, **kwargs))

    def _is_crypto_symbol(self, symbol: str) -> bool:
        """Check if symbol is a cryptocurrency (e.g., BTC-USD, ETH-USD)."""
        # Common crypto symbols that appear in trading pairs
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
        # Check if symbol contains a dash (crypto pairs like BTC-USD, BTCUSDT, etc.)
        if '-' in symbol_upper:
            base = symbol_upper.split('-')[0]
            return base in crypto_bases
        # Also check for formats like BTCUSDT (no dash)
        for crypto in crypto_bases:
            if symbol_upper.startswith(crypto) and len(symbol_upper) > len(crypto):
                return True
        return False

    async def _calculate_indicators_from_yfinance_async(self,
                                                        symbol: str,
                                                        indicators: List[str],
                                                        interval: str = "daily",
                                                        time_period: Optional[int] = None) -> Dict[str, Any]:
        """
        Calculate technical indicators from yfinance data (for crypto symbols).
        
        Args:
            symbol: Crypto symbol (e.g., 'BTC-USD')
            indicators: List of indicator names
            interval: Data interval (mapped to yfinance intervals)
            time_period: Optional time period override
        
        Returns:
            Dictionary with calculated indicator data
        """
        # Map interval to yfinance format
        interval_map = {
            "1min": "1m",
            "5min": "5m",
            "15min": "15m",
            "30min": "30m",
            "60min": "1h",
            "daily": "1d",
            "weekly": "1wk",
            "monthly": "1mo"
        }
        yf_interval = interval_map.get(interval.lower(), "1d")

        # Determine period based on interval
        if yf_interval in ["1m", "5m", "15m", "30m"]:
            period = "5d"  # Intraday data limited
        elif yf_interval == "1h":
            period = "1mo"
        else:
            period = "1y"  # Daily/weekly/monthly

        try:
            ticker = self._ticker(symbol)
            df = ticker.history(period=period, interval=yf_interval)

            if df.empty:
                return {"error": f"No data available for symbol {symbol}"}

            results = {"symbol": symbol, "interval": interval, "indicators": {}}

            # Calculate each indicator
            for indicator in indicators:
                indicator_lower = indicator.lower().strip()

                try:
                    if indicator_lower == "close_50_sma":
                        period_val = time_period or 50
                        sma = df['Close'].rolling(window=period_val).mean()
                        results["indicators"][indicator] = {
                            date.strftime("%Y-%m-%d %H:%M:%S"): float(val)
                            for date, val in sma.items() if not pd.isna(val)
                        }

                    elif indicator_lower == "close_200_sma":
                        period_val = time_period or 200
                        sma = df['Close'].rolling(window=period_val).mean()
                        results["indicators"][indicator] = {
                            date.strftime("%Y-%m-%d %H:%M:%S"): float(val)
                            for date, val in sma.items() if not pd.isna(val)
                        }

                    elif indicator_lower == "close_10_ema":
                        period_val = time_period or 10
                        ema = df['Close'].ewm(span=period_val, adjust=False).mean()
                        results["indicators"][indicator] = {
                            date.strftime("%Y-%m-%d %H:%M:%S"): float(val)
                            for date, val in ema.items() if not pd.isna(val)
                        }

                    elif indicator_lower == "rsi":
                        period_val = time_period or 14
                        delta = df['Close'].diff()
                        gain = (delta.where(delta > 0, 0)).rolling(window=period_val).mean()
                        loss = (-delta.where(delta < 0, 0)).rolling(window=period_val).mean()
                        rs = gain / loss
                        rsi = 100 - (100 / (1 + rs))
                        results["indicators"][indicator] = {
                            date.strftime("%Y-%m-%d %H:%M:%S"): float(val)
                            for date, val in rsi.items() if not pd.isna(val)
                        }

                    elif indicator_lower in ["macd", "macds", "macdh"]:
                        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
                        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
                        macd_line = exp1 - exp2
                        signal_line = macd_line.ewm(span=9, adjust=False).mean()
                        histogram = macd_line - signal_line

                        if indicator_lower == "macd":
                            results["indicators"][indicator] = {
                                date.strftime("%Y-%m-%d %H:%M:%S"): float(val)
                                for date, val in macd_line.items() if not pd.isna(val)
                            }
                        elif indicator_lower == "macds":
                            results["indicators"][indicator] = {
                                date.strftime("%Y-%m-%d %H:%M:%S"): float(val)
                                for date, val in signal_line.items() if not pd.isna(val)
                            }
                        elif indicator_lower == "macdh":
                            results["indicators"][indicator] = {
                                date.strftime("%Y-%m-%d %H:%M:%S"): float(val)
                                for date, val in histogram.items() if not pd.isna(val)
                            }

                    elif indicator_lower in ["boll", "boll_ub", "boll_lb"]:
                        period_val = time_period or 20
                        sma = df['Close'].rolling(window=period_val).mean()
                        std = df['Close'].rolling(window=period_val).std()
                        upper_band = sma + (std * 2)
                        lower_band = sma - (std * 2)

                        if indicator_lower == "boll":
                            results["indicators"][indicator] = {
                                date.strftime("%Y-%m-%d %H:%M:%S"): float(val)
                                for date, val in sma.items() if not pd.isna(val)
                            }
                        elif indicator_lower == "boll_ub":
                            results["indicators"][indicator] = {
                                date.strftime("%Y-%m-%d %H:%M:%S"): float(val)
                                for date, val in upper_band.items() if not pd.isna(val)
                            }
                        elif indicator_lower == "boll_lb":
                            results["indicators"][indicator] = {
                                date.strftime("%Y-%m-%d %H:%M:%S"): float(val)
                                for date, val in lower_band.items() if not pd.isna(val)
                            }

                    elif indicator_lower == "atr":
                        period_val = time_period or 14
                        high_low = df['High'] - df['Low']
                        high_close = np.abs(df['High'] - df['Close'].shift())
                        low_close = np.abs(df['Low'] - df['Close'].shift())
                        ranges = pd.concat([high_low, high_close, low_close], axis=1)
                        true_range = np.max(ranges, axis=1)
                        atr = true_range.rolling(window=period_val).mean()
                        results["indicators"][indicator] = {
                            date.strftime("%Y-%m-%d %H:%M:%S"): float(val)
                            for date, val in atr.items() if not pd.isna(val)
                        }

                    elif indicator_lower == "vwap":
                        # VWAP typically calculated for intraday data
                        typical_price = (df['High'] + df['Low'] + df['Close']) / 3
                        vwap = (typical_price * df['Volume']).cumsum() / df['Volume'].cumsum()
                        results["indicators"][indicator] = {
                            date.strftime("%Y-%m-%d %H:%M:%S"): float(val)
                            for date, val in vwap.items() if not pd.isna(val)
                        }

                    else:
                        results["indicators"][indicator] = {
                            "error": f"Indicator '{indicator}' calculation not implemented for crypto symbols"
                        }

                except Exception as e:
                    results["indicators"][indicator] = {"error": f"Error calculating {indicator}: {str(e)}"}

            return results

        except Exception as e:
            return {"error": f"Error fetching data for {symbol}: {str(e)}"}

    async def get_indicators_async(self,
                                   symbol: str,
                                   indicators: List[str],
                                   interval: str = "daily",
                                   time_period: Optional[int] = None) -> Dict[str, Any]:
        """
        Fetch technical indicators from Alpha Vantage API (for stocks) or calculate from yfinance (for crypto).
        Async version with concurrent API calls.

        Args:
            symbol: Stock ticker symbol (e.g., 'AAPL', 'MSFT') or crypto (e.g., 'BTC-USD')
            indicators: List of indicator names (e.g., ['close_50_sma', 'rsi', 'macd'])
            interval: Data interval (1min, 5min, 15min, 30min, 60min, daily, weekly, monthly)
            time_period: Optional time period for indicators that require it

        Returns:
            Dictionary with indicator data in JSON format
        """
        if not symbol or not symbol.strip():
            raise ValueError("Symbol cannot be empty")

        if not indicators:
            raise ValueError("At least one indicator must be specified")

        symbol = symbol.strip().upper()

        # Check if this is a crypto symbol - if so, use yfinance calculations
        if self._is_crypto_symbol(symbol):
            return await self._calculate_indicators_from_yfinance_async(symbol, indicators, interval, time_period)

        # Otherwise, use Alpha Vantage for stocks
        results = {"symbol": symbol, "interval": interval, "indicators": {}}

        # Map indicator names to Alpha Vantage functions and parameters
        indicator_mapping = {
            "close_50_sma": ("SMA", {
                "time_period": 50, "series_type": "close"
            }),
            "close_200_sma": ("SMA", {
                "time_period": 200, "series_type": "close"
            }),
            "close_10_ema": ("EMA", {
                "time_period": 10, "series_type": "close"
            }),
            "macd": ("MACD", {
                "series_type": "close"
            }),
            "macds": ("MACD", {
                "series_type": "close"
            }),
            "macdh": ("MACD", {
                "series_type": "close"
            }),
            "rsi": ("RSI", {
                "time_period": 14, "series_type": "close"
            }),
            "boll": ("BBANDS", {
                "time_period": 20, "series_type": "close", "nbdevup": 2, "nbdevdn": 2
            }),
            "boll_ub": ("BBANDS", {
                "time_period": 20, "series_type": "close", "nbdevup": 2, "nbdevdn": 2
            }),
            "boll_lb": ("BBANDS", {
                "time_period": 20, "series_type": "close", "nbdevup": 2, "nbdevdn": 2
            }),
            "atr": ("ATR", {
                "time_period": 14
            }),
            "vwap": ("VWAP", {}),
        }

        # Group indicators by their function to batch requests
        function_groups = {}
        for indicator in indicators:
            indicator_lower = indicator.lower().strip()

            if indicator_lower not in indicator_mapping:
                results["indicators"][indicator] = {
                    "error":
                        f"Indicator '{indicator}' not supported. Supported indicators: {list(indicator_mapping.keys())}"
                }
                continue

            function_name, params = indicator_mapping[indicator_lower]

            # Override time_period if provided
            if time_period and "time_period" in params:
                params = {**params, "time_period": time_period}

            # Add interval to params
            params = {**params, "interval": interval}

            # Group by function + params to avoid duplicate API calls
            params_key = (function_name, frozenset(params.items()))
            if params_key not in function_groups:
                function_groups[params_key] = []
            function_groups[params_key].append(indicator_lower)

        # Fetch all unique functions concurrently
        async def fetch_indicator_data(function_name: str, params: dict) -> tuple:
            try:
                data = await self._alpha_get_async(function_name, symbol, **params)
                return (function_name, params, data)
            except Exception as e:
                return (function_name, params, {"error": str(e)})

        tasks = [fetch_indicator_data(fn, dict(params)) for (fn, params), _ in function_groups.items()]

        # Wait for all API calls to complete
        api_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results and assign to indicators
        for (function_name, params_frozen), indicator_list in function_groups.items():
            params_dict = dict(params_frozen)

            # Find the corresponding API result
            matching_result = None
            for result in api_results:
                if isinstance(result, Exception):
                    continue
                fn, prm, data = result
                if fn == function_name and dict(prm) == params_dict:
                    matching_result = data
                    break

            if not matching_result or "error" in matching_result:
                error_msg = matching_result.get("error", "Unknown error") if matching_result else "No data returned"
                for indicator in indicator_list:
                    results["indicators"][indicator] = {"error": error_msg}
                continue

            # Extract data for each indicator in this group
            for indicator_lower in indicator_list:
                try:
                    if function_name == "MACD":
                        macd_key = f"Technical Analysis: {function_name}"
                        if macd_key in matching_result:
                            macd_data = matching_result[macd_key]
                            dates = sorted(macd_data.keys(), reverse=True)
                            if indicator_lower == "macd":
                                results["indicators"][indicator_lower] = {
                                    date: macd_data[date].get("MACD")
                                    for date in dates
                                }
                            elif indicator_lower == "macds":
                                results["indicators"][indicator_lower] = {
                                    date: macd_data[date].get("MACD_Signal")
                                    for date in dates
                                }
                            elif indicator_lower == "macdh":
                                results["indicators"][indicator_lower] = {
                                    date: macd_data[date].get("MACD_Hist")
                                    for date in dates
                                }
                        else:
                            results["indicators"][indicator_lower] = {"error": "No MACD data found in response"}

                    elif function_name == "BBANDS":
                        bbands_key = f"Technical Analysis: {function_name}"
                        if bbands_key in matching_result:
                            bbands_data = matching_result[bbands_key]
                            dates = sorted(bbands_data.keys(), reverse=True)

                            if indicator_lower == "boll":
                                results["indicators"][indicator_lower] = {
                                    date: bbands_data[date].get("Real Middle Band")
                                    for date in dates
                                }
                            elif indicator_lower == "boll_ub":
                                results["indicators"][indicator_lower] = {
                                    date: bbands_data[date].get("Real Upper Band")
                                    for date in dates
                                }
                            elif indicator_lower == "boll_lb":
                                results["indicators"][indicator_lower] = {
                                    date: bbands_data[date].get("Real Lower Band")
                                    for date in dates
                                }
                        else:
                            results["indicators"][indicator_lower] = {
                                "error": "No Bollinger Bands data found in response"
                            }

                    else:
                        # For SMA, EMA, RSI, ATR, VWAP
                        tech_key = f"Technical Analysis: {function_name}"
                        if tech_key in matching_result:
                            tech_data = matching_result[tech_key]
                            dates = sorted(tech_data.keys(), reverse=True)
                            # Get the value key (varies by indicator)
                            value_key = None
                            for key in tech_data[dates[0]].keys() if dates else []:
                                if function_name in key.upper() or "VWAP" in key.upper():
                                    value_key = key
                                    break

                            if value_key:
                                results["indicators"][indicator_lower] = {
                                    date: tech_data[date].get(value_key)
                                    for date in dates
                                }
                            else:
                                # Fallback: use first value key
                                if dates and tech_data[dates[0]]:
                                    first_key = list(tech_data[dates[0]].keys())[0]
                                    results["indicators"][indicator_lower] = {
                                        date: tech_data[date].get(first_key)
                                        for date in dates
                                    }
                                else:
                                    results["indicators"][indicator_lower] = {
                                        "error": "Could not extract indicator values"
                                    }
                        else:
                            results["indicators"][indicator_lower] = {
                                "error": f"No {function_name} data found in response"
                            }

                except Exception as e:
                    results["indicators"][indicator_lower] = {"error": str(e)}

        return results

    def get_indicators(self,
                       symbol: str,
                       indicators: List[str],
                       interval: str = "daily",
                       time_period: Optional[int] = None) -> Dict[str, Any]:
        """
        Fetch technical indicators from Alpha Vantage API (for stocks) or calculate from yfinance (for crypto).
        
        Args:
            symbol: Stock ticker symbol (e.g., 'AAPL', 'MSFT') or crypto (e.g., 'BTC-USD')
            indicators: List of indicator names (e.g., ['close_50_sma', 'rsi', 'macd'])
            interval: Data interval (1min, 5min, 15min, 30min, 60min, daily, weekly, monthly)
            time_period: Optional time period for indicators that require it
        
        Returns:
            Dictionary with indicator data in JSON format
        """
        if not symbol or not symbol.strip():
            raise ValueError("Symbol cannot be empty")

        if not indicators:
            raise ValueError("At least one indicator must be specified")

        symbol = symbol.strip().upper()

        # Check if this is a crypto symbol - if so, use yfinance calculations
        if self._is_crypto_symbol(symbol):
            try:
                loop = asyncio.get_running_loop()
                return {"error": "Use async version in async context for crypto"}
            except RuntimeError:
                return asyncio.run(
                    self._calculate_indicators_from_yfinance_async(symbol, indicators, interval, time_period))

        # Otherwise, use Alpha Vantage for stocks
        results = {"symbol": symbol, "interval": interval, "indicators": {}}

        # Map indicator names to Alpha Vantage functions and parameters
        # Note: macd, macds, macdh all use the same MACD function but extract different values
        # Note: boll, boll_ub, boll_lb all use the same BBANDS function but extract different bands
        indicator_mapping = {
            "close_50_sma": ("SMA", {
                "time_period": 50, "series_type": "close"
            }),
            "close_200_sma": ("SMA", {
                "time_period": 200, "series_type": "close"
            }),
            "close_10_ema": ("EMA", {
                "time_period": 10, "series_type": "close"
            }),
            "macd": ("MACD", {
                "series_type": "close"
            }),
            "macds": ("MACD", {
                "series_type": "close"
            }),  # Signal line from MACD
            "macdh": ("MACD", {
                "series_type": "close"
            }),  # Histogram from MACD
            "rsi": ("RSI", {
                "time_period": 14, "series_type": "close"
            }),
            "boll": ("BBANDS", {
                "time_period": 20, "series_type": "close", "nbdevup": 2, "nbdevdn": 2
            }),
            "boll_ub": ("BBANDS", {
                "time_period": 20, "series_type": "close", "nbdevup": 2, "nbdevdn": 2
            }),
            "boll_lb": ("BBANDS", {
                "time_period": 20, "series_type": "close", "nbdevup": 2, "nbdevdn": 2
            }),
            "atr": ("ATR", {
                "time_period": 14
            }),
            "vwap": ("VWAP", {}),
        }

        # Handle VWMA separately if needed (Alpha Vantage may not have it directly)
        # For now, we'll skip it or note it's not available

        for indicator in indicators:
            indicator_lower = indicator.lower().strip()

            if indicator_lower not in indicator_mapping:
                results["indicators"][indicator] = {
                    "error":
                        f"Indicator '{indicator}' not supported. Supported indicators: {list(indicator_mapping.keys())}"
                }
                continue

            function_name, params = indicator_mapping[indicator_lower]

            # Override time_period if provided
            if time_period and "time_period" in params:
                params["time_period"] = time_period

            # Add interval to params
            params["interval"] = interval

            try:
                data = self._call_alpha_vantage(function_name, symbol, **params)

                # Extract the relevant data based on indicator type
                if function_name == "MACD":
                    # MACD returns MACD, Signal, and Histogram
                    macd_key = f"Technical Analysis: {function_name}"
                    if macd_key in data:
                        macd_data = data[macd_key]
                        # Extract dates and values
                        dates = sorted(macd_data.keys(), reverse=True)
                        # Extract the specific component based on which indicator was requested
                        if indicator_lower == "macd":
                            results["indicators"][indicator] = {date: macd_data[date].get("MACD") for date in dates}
                        elif indicator_lower == "macds":
                            results["indicators"][indicator] = {
                                date: macd_data[date].get("MACD_Signal")
                                for date in dates
                            }
                        elif indicator_lower == "macdh":
                            results["indicators"][indicator] = {date: macd_data[date].get("MACD_Hist") for date in dates}
                        else:
                            # If somehow we get here, return all three
                            results["indicators"][indicator] = {
                                "macd": {
                                    date: macd_data[date].get("MACD")
                                    for date in dates
                                },
                                "macds": {
                                    date: macd_data[date].get("MACD_Signal")
                                    for date in dates
                                },
                                "macdh": {
                                    date: macd_data[date].get("MACD_Hist")
                                    for date in dates
                                }
                            }
                    else:
                        results["indicators"][indicator] = {"error": "No MACD data found in response"}

                elif function_name == "BBANDS":
                    # Bollinger Bands returns upper, middle, and lower bands
                    bbands_key = f"Technical Analysis: {function_name}"
                    if bbands_key in data:
                        bbands_data = data[bbands_key]
                        dates = sorted(bbands_data.keys(), reverse=True)

                        if indicator_lower == "boll":
                            results["indicators"][indicator] = {
                                date: bbands_data[date].get("Real Middle Band")
                                for date in dates
                            }
                        elif indicator_lower == "boll_ub":
                            results["indicators"][indicator] = {
                                date: bbands_data[date].get("Real Upper Band")
                                for date in dates
                            }
                        elif indicator_lower == "boll_lb":
                            results["indicators"][indicator] = {
                                date: bbands_data[date].get("Real Lower Band")
                                for date in dates
                            }
                    else:
                        results["indicators"][indicator] = {"error": "No Bollinger Bands data found in response"}

                else:
                    # For SMA, EMA, RSI, ATR, VWAP
                    tech_key = f"Technical Analysis: {function_name}"
                    if tech_key in data:
                        tech_data = data[tech_key]
                        dates = sorted(tech_data.keys(), reverse=True)
                        # Get the value key (varies by indicator)
                        value_key = None
                        for key in tech_data[dates[0]].keys() if dates else []:
                            if function_name in key.upper() or "VWAP" in key.upper():
                                value_key = key
                                break

                        if value_key:
                            results["indicators"][indicator] = {date: tech_data[date].get(value_key) for date in dates}
                        else:
                            # Fallback: use first value key
                            if dates and tech_data[dates[0]]:
                                first_key = list(tech_data[dates[0]].keys())[0]
                                results["indicators"][indicator] = {
                                    date: tech_data[date].get(first_key)
                                    for date in dates
                                }
                            else:
                                results["indicators"][indicator] = {"error": "Could not extract indicator values"}
                    else:
                        results["indicators"][indicator] = {"error": f"No {function_name} data found in response"}

            except Exception as e:
                results["indicators"][indicator] = {"error": str(e)}

        return results


# Singleton instance
_instance = None


def _get_instance() -> TechnicalIndicatorsTools:
    """Get or create the singleton instance."""
    global _instance
    if _instance is None:
        _instance = TechnicalIndicatorsTools()
    return _instance


@tool
def get_stock_data_tool(symbol: str, period: str = "1y", interval: str = "1d") -> Dict[str, Any]:
    """
    Retrieve historical stock price data for a ticker symbol.
    
    Args:
        symbol: Stock ticker symbol (e.g., 'AAPL', 'MSFT'). Case-insensitive.
        period: Period to fetch (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max). Default: 1y
        interval: Data interval (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo). Default: 1d
    
    Returns:
        Dictionary with historical stock data including date, open, high, low, close, and volume in JSON format.
    """
    try:
        return _get_instance().get_stock_data(symbol, period, interval)
    except Exception as e:
        return {"error": str(e)}


@tool
def get_indicators_tool(symbol: str,
                        indicators: List[str],
                        interval: str = "daily",
                        time_period: Optional[int] = None) -> Dict[str, Any]:
    """
    Retrieve technical indicators for a stock ticker symbol using Alpha Vantage API.
    
    Args:
        symbol: Stock ticker symbol (e.g., 'AAPL', 'MSFT'). Case-insensitive.
        indicators: List of indicator names. Supported indicators:
            - close_50_sma: 50-period Simple Moving Average
            - close_200_sma: 200-period Simple Moving Average
            - close_10_ema: 10-period Exponential Moving Average
            - macd: MACD (returns macd, macds, macdh)
            - rsi: Relative Strength Index
            - boll: Bollinger Bands Middle
            - boll_ub: Bollinger Bands Upper
            - boll_lb: Bollinger Bands Lower
            - atr: Average True Range
            - vwap: Volume Weighted Average Price
        interval: Data interval (1min, 5min, 15min, 30min, 60min, daily, weekly, monthly). Default: daily
        time_period: Optional time period to override default periods for indicators
    
    Returns:
        Dictionary with technical indicator data in JSON format organized by indicator name.
    """
    try:
        return _get_instance().get_indicators(symbol, indicators, interval, time_period)
    except Exception as e:
        return {"error": str(e)}
