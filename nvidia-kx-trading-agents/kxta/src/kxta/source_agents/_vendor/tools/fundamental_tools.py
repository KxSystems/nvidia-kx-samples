# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Vendored into the KXTA source-agents layer from the KX "agentic-anomaly-market-research" project
# (faithful copy; imports rewritten and heavy imports made lazy -- no logic changes).
import os
import asyncio
import aiohttp
import requests
import pandas as pd
from typing import Dict, Any, Optional, List
from functools import lru_cache
from langchain_core.tools import tool


class FundamentalTools:
    """Fundamental data retrieval utilities with yfinance primary, Alpha Vantage fallback."""

    def __init__(self):
        self.api_key = os.getenv("ALPHAVANTAGE_API_KEY")
        self.base_url = "https://www.alphavantage.co/query"
        self._ticker_cache = {}  # Cache ticker objects
        self._av_overview_cache = {}  # Cache Alpha Vantage OVERVIEW calls

    # ---------- helpers ----------
    async def _alpha_get_async(self, function: str, symbol: str, **params) -> Dict[str, Any]:
        """Async call to Alpha Vantage endpoint if API key is configured."""
        if not self.api_key:
            return {"error": "ALPHAVANTAGE_API_KEY not set; alpha vantage fallback unavailable"}

        query = {"function": function, "symbol": symbol, "apikey": self.api_key, **params}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.base_url, params=query, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    if "Error Message" in data:
                        return {"error": data["Error Message"]}
                    if "Note" in data:
                        return {"error": data["Note"]}
                    return data
        except Exception as e:
            return {"error": f"Alpha Vantage request failed: {e}"}

    def _alpha_get(self, function: str, symbol: str, **params) -> Dict[str, Any]:
        """Sync wrapper for Alpha Vantage calls (deprecated, use async version)."""
        try:
            loop = asyncio.get_running_loop()
            # If already in async context, we can't use asyncio.run
            return {"error": "Use _alpha_get_async in async context"}
        except RuntimeError:
            # No event loop running, safe to use asyncio.run
            return asyncio.run(self._alpha_get_async(function, symbol, **params))

    def _df_to_records(self, df: Optional["pd.DataFrame"], limit: int = 6) -> List[Dict[str, Any]]:
        """Convert a yfinance DataFrame (columns are periods) to list of records."""
        if df is None or df.empty:
            return []
        records = []
        # Take latest columns first
        for col in list(df.columns)[:limit]:
            col_series = df[col]
            record = {"period": str(col)}
            for idx, val in col_series.items():
                # Ensure JSON serializable
                if pd.isna(val):
                    continue
                try:
                    record[str(idx)] = float(val)
                except Exception:
                    record[str(idx)] = str(val)
            records.append(record)
        return records

    def _safe_info(self, info: Dict[str, Any], key: str, default=None):
        return info.get(key) if info and key in info else default

    # ---------- yfinance primary fetch ----------
    def _ticker(self, symbol: str):
        """Get or create cached ticker object."""
        import yfinance as yf
        symbol = symbol.strip().upper()
        if symbol not in self._ticker_cache:
            self._ticker_cache[symbol] = yf.Ticker(symbol)
        return self._ticker_cache[symbol]

    async def _get_av_overview_cached(self, symbol: str) -> Dict[str, Any]:
        """Get Alpha Vantage OVERVIEW with caching to avoid duplicate calls."""
        symbol = symbol.strip().upper()
        if symbol in self._av_overview_cache:
            return self._av_overview_cache[symbol]

        result = await self._alpha_get_async("OVERVIEW", symbol)
        self._av_overview_cache[symbol] = result
        return result

    # ---------- tool methods ----------
    async def get_company_overview_async(self, symbol: str) -> Dict[str, Any]:
        symbol = symbol.strip().upper()
        ticker = self._ticker(symbol)
        info = ticker.info or {}

        overview = {
            "symbol": symbol,
            "name": self._safe_info(info, "longName") or self._safe_info(info, "shortName"),
            "sector": self._safe_info(info, "sector"),
            "industry": self._safe_info(info, "industry"),
            "market_cap": self._safe_info(info, "marketCap"),
            "beta": self._safe_info(info, "beta"),
            "shares_outstanding": self._safe_info(info, "sharesOutstanding"),
            "employees": self._safe_info(info, "fullTimeEmployees"),
            "country": self._safe_info(info, "country"),
            "currency": self._safe_info(info, "currency"),
            "exchange": self._safe_info(info, "exchange"),
            "website": self._safe_info(info, "website"),
            "description": self._safe_info(info, "longBusinessSummary"),
        }

        # Only fallback to Alpha Vantage if yfinance data is missing
        if not overview["name"] and self.api_key:
            av = await self._get_av_overview_cached(symbol)
            if "error" not in av and isinstance(av, dict):
                overview.update({
                    "name": av.get("Name") or overview["name"],
                    "sector": av.get("Sector") or overview["sector"],
                    "industry": av.get("Industry") or overview["industry"],
                    "market_cap": av.get("MarketCapitalization") or overview["market_cap"],
                    "beta": av.get("Beta") or overview["beta"],
                    "shares_outstanding": av.get("SharesOutstanding") or overview["shares_outstanding"],
                    "description": av.get("Description") or overview["description"],
                    "exchange": av.get("Exchange") or overview["exchange"],
                    "country": av.get("Country") or overview["country"],
                })
                overview["alpha_vantage_note"] = av.get("Note")
            elif "error" in av:
                overview["alpha_vantage_error"] = av["error"]

        return overview

    def get_company_overview(self, symbol: str) -> Dict[str, Any]:
        """Sync wrapper for get_company_overview_async."""
        try:
            loop = asyncio.get_running_loop()
            return {"error": "Use async version in async context"}
        except RuntimeError:
            return asyncio.run(self.get_company_overview_async(symbol))

    async def get_financial_statements_async(self, symbol: str, statement_type: str = "all") -> Dict[str, Any]:
        symbol = symbol.strip().upper()
        ticker = self._ticker(symbol)

        income = self._df_to_records(getattr(ticker, "financials", None))
        balance = self._df_to_records(getattr(ticker, "balance_sheet", None))
        cashflow = self._df_to_records(getattr(ticker, "cashflow", None))

        result = {
            "symbol": symbol,
            "income_statement": income if statement_type in ("income", "all") else [],
            "balance_sheet": balance if statement_type in ("balance", "all") else [],
            "cash_flow": cashflow if statement_type in ("cashflow", "all") else [],
        }

        # Fallback to Alpha Vantage for missing pieces (async + concurrent)
        async def maybe_fill(key: str, fn: str):
            if result[key]:
                return
            av = await self._alpha_get_async(fn, symbol)
            if "error" in av:
                result[f"{key}_error"] = av["error"]
                return
            data_key = next((k for k in av.keys() if "report" in k.lower()), None)
            if data_key and isinstance(av[data_key], list):
                result[key] = av[data_key][:4]

        # Run all fallback calls concurrently
        tasks = []
        if statement_type in ("income", "all") and not income:
            tasks.append(maybe_fill("income_statement", "INCOME_STATEMENT"))
        if statement_type in ("balance", "all") and not balance:
            tasks.append(maybe_fill("balance_sheet", "BALANCE_SHEET"))
        if statement_type in ("cashflow", "all") and not cashflow:
            tasks.append(maybe_fill("cash_flow", "CASH_FLOW"))

        if tasks:
            await asyncio.gather(*tasks)

        return result

    def get_financial_statements(self, symbol: str, statement_type: str = "all") -> Dict[str, Any]:
        """Sync wrapper for get_financial_statements_async."""
        try:
            loop = asyncio.get_running_loop()
            return {"error": "Use async version in async context"}
        except RuntimeError:
            return asyncio.run(self.get_financial_statements_async(symbol, statement_type))

    async def get_valuation_ratios_async(self, symbol: str) -> Dict[str, Any]:
        symbol = symbol.strip().upper()
        info = self._ticker(symbol).info or {}

        ratios = {
            "symbol": symbol,
            "pe": self._safe_info(info, "trailingPE"),
            "forward_pe": self._safe_info(info, "forwardPE"),
            "pb": self._safe_info(info, "priceToBook"),
            "ps": self._safe_info(info, "priceToSalesTrailing12Months"),
            "ev_to_ebitda": self._safe_info(info, "enterpriseToEbitda"),
            "peg": self._safe_info(info, "pegRatio"),
            "market_cap": self._safe_info(info, "marketCap"),
            "enterprise_value": self._safe_info(info, "enterpriseValue"),
        }

        # Only use Alpha Vantage if key data is missing
        has_key_data = ratios["pe"] is not None or ratios["market_cap"] is not None
        if not has_key_data and self.api_key:
            av = await self._get_av_overview_cached(symbol)
            if "error" not in av and isinstance(av, dict):

                def _coalesce(current, alt_key):
                    return current if current is not None else av.get(alt_key)

                ratios["pe"] = _coalesce(ratios["pe"], "PERatio")
                ratios["forward_pe"] = _coalesce(ratios["forward_pe"], "ForwardPE")
                ratios["pb"] = _coalesce(ratios["pb"], "PriceToBookRatio")
                ratios["ps"] = _coalesce(ratios["ps"], "PriceToSalesRatioTTM")
                ratios["ev_to_ebitda"] = _coalesce(ratios["ev_to_ebitda"], "EVToEBITDA")
                ratios["peg"] = _coalesce(ratios["peg"], "PEGRatio")
                ratios["market_cap"] = _coalesce(ratios["market_cap"], "MarketCapitalization")
                ratios["enterprise_value"] = _coalesce(ratios["enterprise_value"], "EnterpriseValue")
            elif "error" in av:
                ratios["alpha_vantage_error"] = av["error"]

        return ratios

    def get_valuation_ratios(self, symbol: str) -> Dict[str, Any]:
        """Sync wrapper for get_valuation_ratios_async."""
        try:
            loop = asyncio.get_running_loop()
            return {"error": "Use async version in async context"}
        except RuntimeError:
            return asyncio.run(self.get_valuation_ratios_async(symbol))

    async def get_earnings_data_async(self, symbol: str) -> Dict[str, Any]:
        symbol = symbol.strip().upper()
        ticker = self._ticker(symbol)

        def _df_tail(df: Optional["pd.DataFrame"], limit: int = 8):
            if df is None or df.empty:
                return []
            df_sorted = df.sort_index()
            return [{
                "period": str(idx), **{
                    k: (float(v) if not pd.isna(v) else None)
                    for k, v in row.items()
                }
            } for idx, row in df_sorted.tail(limit).iterrows()]

        annual = _df_tail(getattr(ticker, "earnings", None), limit=8)
        quarterly = _df_tail(getattr(ticker, "quarterly_earnings", None), limit=12)
        info = ticker.info or {}

        earnings = {
            "symbol": symbol,
            "annual_eps": annual,
            "quarterly_eps": quarterly,
            "next_earnings_date": info.get("earningsTimestamp") or info.get("earningsTimestampStart"),
        }

        # Only fallback if both are missing
        if (not annual and not quarterly) and self.api_key:
            av = await self._alpha_get_async("EARNINGS", symbol)
            if "error" not in av and isinstance(av, dict):
                if "annualEarnings" in av:
                    earnings["annual_eps"] = av["annualEarnings"][:6]
                if "quarterlyEarnings" in av:
                    earnings["quarterly_eps"] = av["quarterlyEarnings"][:12]
            elif "error" in av:
                earnings["alpha_vantage_error"] = av["error"]

        return earnings

    def get_earnings_data(self, symbol: str) -> Dict[str, Any]:
        """Sync wrapper for get_earnings_data_async."""
        try:
            loop = asyncio.get_running_loop()
            return {"error": "Use async version in async context"}
        except RuntimeError:
            return asyncio.run(self.get_earnings_data_async(symbol))

    async def get_dividend_data_async(self, symbol: str) -> Dict[str, Any]:
        symbol = symbol.strip().upper()
        ticker = self._ticker(symbol)
        dividends = ticker.dividends if hasattr(ticker, "dividends") else None
        info = ticker.info or {}

        div_history = []
        if dividends is not None and not dividends.empty:
            div_history = [{
                "date": str(idx.date() if hasattr(idx, "date") else idx), "amount": float(val)
            } for idx, val in dividends.tail(12).items()]

        result = {
            "symbol": symbol,
            "dividend_yield": info.get("dividendYield"),
            "dividend_rate": info.get("dividendRate"),
            "payout_ratio": info.get("payoutRatio"),
            "ex_dividend_date": info.get("exDividendDate"),
            "dividend_history": div_history,
        }
        return result

    def get_dividend_data(self, symbol: str) -> Dict[str, Any]:
        """Sync wrapper for get_dividend_data_async."""
        try:
            loop = asyncio.get_running_loop()
            return {"error": "Use async version in async context"}
        except RuntimeError:
            return asyncio.run(self.get_dividend_data_async(symbol))

    async def get_analyst_ratings_async(self, symbol: str) -> Dict[str, Any]:
        symbol = symbol.strip().upper()
        ticker = self._ticker(symbol)
        recs = getattr(ticker, "recommendations", None)

        summary = {"buy": 0, "overweight": 0, "hold": 0, "underweight": 0, "sell": 0}
        latest_notes = []
        if recs is not None and not recs.empty:
            # Normalize recommendation column if present
            ratings_col = "To Grade" if "To Grade" in recs.columns else None
            action_col = "Action" if "Action" in recs.columns else None
            date_col = "Date" if "Date" in recs.columns else None

            def _norm(val: str) -> str:
                if not isinstance(val, str):
                    return ""
                v = val.lower()
                if "buy" in v and "strong" in v:
                    return "buy"
                if "buy" in v:
                    return "buy"
                if "over" in v:
                    return "overweight"
                if "under" in v:
                    return "underweight"
                if "sell" in v:
                    return "sell"
                if "hold" in v or "neutral" in v:
                    return "hold"
                return ""

            for _, row in recs.tail(20).iterrows():
                rating = _norm(row[ratings_col]) if ratings_col else ""
                if rating in summary:
                    summary[rating] += 1
                note = {
                    "date": str(row[date_col]) if date_col else None,
                    "action": row[action_col] if action_col and action_col in row else None,
                    "to_grade": row[ratings_col] if ratings_col and ratings_col in row else None,
                    "firm": row["Firm"] if "Firm" in row else None,
                }
                latest_notes.append(note)

        # Only use Alpha Vantage if yfinance has no data
        price_target = None
        if not any(summary.values()) and self.api_key:
            av = await self._get_av_overview_cached(symbol)
            if "error" not in av and isinstance(av, dict):
                # Alpha Vantage provides aggregate rating counts and target price
                try:

                    def _to_int(val):
                        try:
                            return int(float(val))
                        except Exception:
                            return 0

                    summary_from_av = {
                        "buy": _to_int(av.get("AnalystRatingBuy")),
                        "overweight": _to_int(av.get("AnalystRatingStrongBuy")),
                        "hold": _to_int(av.get("AnalystRatingHold")),
                        "underweight": _to_int(av.get("AnalystRatingWeakHold")),
                        "sell": _to_int(av.get("AnalystRatingSell")) + _to_int(av.get("AnalystRatingStrongSell")),
                    }
                    # Only replace if AV gives non-zero signal
                    if any(summary_from_av.values()):
                        summary = summary_from_av
                    price_target = av.get("AnalystTargetPrice")
                except Exception:
                    pass
            elif "error" in av:
                latest_notes.append({"note": f"alpha_vantage_error: {av['error']}"})

        # If still empty, add a clear note
        if not any(summary.values()) and not latest_notes:
            latest_notes.append({"note": "No analyst recommendations available from yfinance or Alpha Vantage."})

        result = {
            "symbol": symbol,
            "ratings_summary": summary,
            "latest_notes": latest_notes,
        }
        if price_target:
            result["target_price"] = price_target
        return result

    def get_analyst_ratings(self, symbol: str) -> Dict[str, Any]:
        """Sync wrapper for get_analyst_ratings_async."""
        try:
            loop = asyncio.get_running_loop()
            return {"error": "Use async version in async context"}
        except RuntimeError:
            return asyncio.run(self.get_analyst_ratings_async(symbol))


# Singleton
_instance: Optional[FundamentalTools] = None


def _get_instance() -> FundamentalTools:
    global _instance
    if _instance is None:
        _instance = FundamentalTools()
    return _instance


@tool
def get_company_overview_tool(symbol: str) -> Dict[str, Any]:
    """Company profile and overview (sector, industry, market cap, beta, description)."""
    return _get_instance().get_company_overview(symbol)


@tool
def get_financial_statements_tool(symbol: str, statement_type: str = "all") -> Dict[str, Any]:
    """
    Retrieve income statement, balance sheet, and cash flow.
    statement_type: 'income' | 'balance' | 'cashflow' | 'all'
    """
    try:
        stype = statement_type.lower().strip() if statement_type else "all"
    except Exception:
        stype = "all"
    if stype not in {"income", "balance", "cashflow", "all"}:
        stype = "all"
    return _get_instance().get_financial_statements(symbol, stype)


@tool
def get_valuation_ratios_tool(symbol: str) -> Dict[str, Any]:
    """Valuation ratios (P/E, P/B, P/S, EV/EBITDA, PEG, market cap)."""
    return _get_instance().get_valuation_ratios(symbol)


@tool
def get_earnings_data_tool(symbol: str) -> Dict[str, Any]:
    """Earnings history, quarterly EPS, and next earnings date."""
    return _get_instance().get_earnings_data(symbol)


@tool
def get_dividend_data_tool(symbol: str) -> Dict[str, Any]:
    """Dividend yield, payout ratio, and recent dividend history."""
    return _get_instance().get_dividend_data(symbol)


@tool
def get_analyst_ratings_tool(symbol: str) -> Dict[str, Any]:
    """Analyst ratings summary and recent notes."""
    return _get_instance().get_analyst_ratings(symbol)
