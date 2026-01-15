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
KDB+ MCP Client using the mcp package (bundled with NAT 1.3.0+)

This module provides an intelligent MCP client that:
1. Discovers available tools from the MCP server dynamically
2. Uses an LLM to decide which tools to call based on user queries
3. No hardcoded schemas or tool names - everything is discovered at runtime

Usage:
    This module is automatically used when KDB_USE_NAT_CLIENT=true (default).
    Falls back to kdb_tools.py when the MCP client is unavailable.
"""

import json
import logging
import os
from typing import Any, Optional

from langchain_openai import ChatOpenAI
from langgraph.types import StreamWriter

logger = logging.getLogger(__name__)

# Environment configuration
KDB_ENABLED = os.getenv("KDB_ENABLED", "false").lower() == "true"
KDB_USE_NAT_CLIENT = os.getenv("KDB_USE_NAT_CLIENT", "true").lower() == "true"
KDB_MCP_ENDPOINT = os.getenv("KDB_MCP_ENDPOINT", "https://kdbxmcp.kxailab.com/mcp")
KDB_TIMEOUT = int(os.getenv("KDB_TIMEOUT", "30"))

# Import MCP client from the mcp package (bundled with NAT 1.3.0+)
# This is a hard requirement - NAT 1.3.0+ must be installed
try:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    _mcp_available = True
    logger.info("MCP client available (mcp package from NAT 1.3.0+)")
except ImportError as e:
    _mcp_available = False
    logger.warning(f"MCP client not available: {e}. KDB+ integration will be disabled.")


# Keywords that indicate a query might be relevant to KDB+ (financial/time-series data)
KDB_KEYWORDS = [
    "price", "stock", "trade", "market", "ticker", "volume",
    "time-series", "timeseries", "historical", "financial data",
    "quote", "bid", "ask", "spread", "ohlc", "candle",
    "moving average", "returns", "volatility", "correlation",
    "portfolio", "equity", "bond", "forex", "fx", "currency",
    "derivative", "option", "future", "swap", "index",
    "nasdaq", "nyse", "s&p", "dow jones", "ftse",
    "trading", "execution", "order", "position", "pnl",
    "profit", "loss", "sharpe", "drawdown", "var", "risk"
]


def is_kdb_query(query: str) -> bool:
    """
    Check if a query should be routed to KDB+ based on keywords.

    This is a fast heuristic check to determine if a query is likely
    to be about financial or time-series data.

    Args:
        query: The search query

    Returns:
        True if query appears to be financial/time-series related
    """
    query_lower = query.lower()
    return any(keyword in query_lower for keyword in KDB_KEYWORDS)


# LLM prompt for intelligent tool selection and execution
TOOL_SELECTION_PROMPT = """You are an intelligent data assistant with access to a KDB+ database via MCP (Model Context Protocol).

## Available MCP Tools:
{tools_description}

## Database Schema and Table Information:
{schema_description}

## Discovered Data Content (actual data in tables):
{data_content}

## SQL Query Syntax Guidance (IMPORTANT - follow this exactly):
{sql_guidance}

## Additional Resources from MCP Server:
{additional_context}

## User Query:
{user_query}

## Your Task:
You MUST use the available tools to answer the user's query. Follow these steps:

### Step 1: CAREFULLY Check Schema AND Data Content
BEFORE writing any SQL, you MUST:
1. Look at the schema above and identify which table(s) are relevant
2. List the EXACT column names from that table's schema
3. Check the "Discovered Data Content" section to see what data actually exists
4. ONLY use columns that appear in the schema - NEVER invent or guess column names
5. ONLY filter by values that exist in the data - check the "Available values" lists

### Step 2: Check Data Availability
**CRITICAL**: Before querying, verify the data exists:
- If filtering by a symbol/ticker, check if it exists in the "Available values" list
- If looking for specific text content, check "Sample values" to understand what's actually in the data
- If the requested data doesn't exist in the schema, be HONEST and explain what IS available

### Step 3: Generate SQL Query
Based on the EXACT columns from the schema and available data:
- Use standard SQL: SELECT, FROM, WHERE, ORDER BY, LIMIT, GROUP BY, AVG, SUM, COUNT, etc.
- ONLY use columns that exist in the schema
- For symbol/ticker filtering: use the symbol column with the ticker value (e.g., WHERE "sym" = 'TICKER'), NOT company names
- For text search: use LIKE with the actual text columns shown in schema
- If searching text columns, also search in related columns (e.g., both title AND summary)

**IMPORTANT - Column name quoting:**
- ALWAYS quote column names with double quotes, especially SQL reserved words
- SQL reserved words that MUST be quoted: "date", "time", "open", "close", "high", "low", "name", "type", "index", "select", "from", "where", "order", "group", "limit"
- Pattern: SELECT "column1", "column2" FROM tablename WHERE "column3" = 'value'

**IMPORTANT - Date handling:**
- KDB-X SQL does NOT support CURRENT_DATE, NOW(), or GETDATE()
- For "today", "latest", "most recent" queries: use ORDER BY date_column DESC LIMIT n
- This gets the most recent data available
- Do NOT use LIKE on date columns - it won't work correctly
- For year filtering: EXTRACT(YEAR FROM "date") = 2023
- For month filtering: EXTRACT(MONTH FROM "date") = 12
- For date ranges: "date" >= '2023-01-01' AND "date" <= '2023-12-31'
- For specific date: "date" = '2023-06-15'
- ALWAYS close string literals with quotes: 'AAPL' not 'AAPL

**IMPORTANT - Symbol/Ticker filtering:**
- Use ticker symbols NOT company names when filtering by symbol columns
- Check the "Available values" in the Discovered Data Content section to see valid symbols
- FIRST verify the symbol exists in the discovered data before querying

## Response Format:
You MUST respond with ONLY a JSON object (no other text before or after):
```json
{{
    "reasoning": "Brief explanation including: 1) which table/columns I'm using, 2) what data exists, 3) any limitations",
    "data_available": true,
    "limitations": "Any limitations or missing data (null if none)",
    "steps": [
        {{
            "tool": "kdbx_run_sql_query",
            "arguments": {{"query": "YOUR SQL QUERY HERE"}},
            "purpose": "What this query returns"
        }}
    ]
}}
```

If the requested data doesn't exist:
```json
{{
    "reasoning": "Explanation of why data is not available",
    "data_available": false,
    "limitations": "What data is missing and what IS available instead",
    "steps": []
}}
```

## Examples:
User: "Show me data from a table"
```json
{{
    "reasoning": "User wants sample data. Checking schema for available tables and their columns.",
    "data_available": true,
    "limitations": null,
    "steps": [
        {{
            "tool": "kdbx_run_sql_query",
            "arguments": {{"query": "SELECT * FROM tablename LIMIT 10"}},
            "purpose": "Get sample rows from table"
        }}
    ]
}}
```

User: "What is the average volume for [TICKER]?"
```json
{{
    "reasoning": "User wants average volume. Verified: 1) table has volume column, 2) ticker exists in available symbols from Discovered Data Content.",
    "data_available": true,
    "limitations": null,
    "steps": [
        {{
            "tool": "kdbx_run_sql_query",
            "arguments": {{"query": "SELECT AVG(\"volume\") as avg_volume FROM tablename WHERE \"sym\" = 'TICKER'"}},
            "purpose": "Calculate average volume for the requested ticker"
        }}
    ]
}}
```

User: "Show me [metric] data for [company]"
```json
{{
    "reasoning": "User wants specific metric. Checking schema: requested column does NOT exist. Available columns are: [list actual columns from schema].",
    "data_available": false,
    "limitations": "The database does not contain the requested metric. Available metrics from schema are: [list what exists]. You can query those instead.",
    "steps": []
}}
```

CRITICAL RULES:
1. ALWAYS check the "Discovered Data Content" section before writing queries
2. Use ticker symbols from "Available values", NOT company names
3. **NEVER invent column names** - only use columns from the schema
4. If data doesn't exist, set data_available=false and explain what IS available
5. For text searches, search multiple relevant columns (e.g., title AND summary)
6. Respond with ONLY the JSON object, no additional text"""


RESULT_SYNTHESIS_PROMPT = """You are a helpful data assistant. Based on the following tool results, provide a clear and informative answer to the user's query.

## User Query:
{user_query}

## Tool Execution Results:
{tool_results}

## Instructions:
- Synthesize the results into a clear, informative response
- If the data shows specific values, include them
- If there were errors, explain what went wrong
- Be concise but complete

Provide your response:"""


class KDBNATClient:
    """
    Intelligent KDB+ MCP client using the mcp package (bundled with NAT 1.3.0+).

    This client:
    1. Discovers available tools from the MCP server dynamically
    2. Discovers available resources (tables/schema) from the MCP server
    3. Uses an LLM to decide which tools to call based on user queries
    4. Executes the tools and synthesizes results
    5. No hardcoded schemas or tool names - everything is discovered at runtime
    """

    # Column name patterns for auto-detection (configurable)
    # These are used to identify column types when probing tables
    DEFAULT_SYMBOL_PATTERNS = ['sym', 'symbol', 'ticker', 'stock', 'instrument', 'security']
    DEFAULT_DATE_PATTERNS = ['date', 'datetime', 'time', 'timestamp', 'dt', 'ts']
    DEFAULT_TEXT_PATTERNS = ['title', 'summary', 'description', 'text', 'content', 'name',
                             'headline', 'body', 'message', 'comment', 'note']
    # Words to filter out when extracting table names from schema text
    DEFAULT_TABLE_FILTER_WORDS = ['table', 'tables', 'schema', 'column', 'columns',
                                  'type', 'description', 'example', 'name', 'the',
                                  'select', 'from', 'where', 'and', 'or', 'not']

    def __init__(
        self,
        endpoint: str = KDB_MCP_ENDPOINT,
        timeout: int = KDB_TIMEOUT,
        symbol_patterns: list[str] = None,
        date_patterns: list[str] = None,
        text_patterns: list[str] = None,
        table_filter_words: list[str] = None,
    ):
        self.endpoint = endpoint
        self.timeout = timeout
        self._tools: dict[str, Any] = {}
        self._tools_description: str = ""
        self._resources: list[dict] = []
        self._schema_description: str = ""
        self._sql_guidance: str = ""  # SQL syntax guidance from MCP server
        self._additional_context: dict = {}  # Other resources for LLM context
        self._initialized = False
        # Data content discovery cache
        self._data_content: dict = {}  # {table: {symbols: [], date_range: {}, sample_content: {}}}
        self._data_content_discovered = False

        # Configurable column detection patterns
        self.symbol_patterns = symbol_patterns or self.DEFAULT_SYMBOL_PATTERNS
        self.date_patterns = date_patterns or self.DEFAULT_DATE_PATTERNS
        self.text_patterns = text_patterns or self.DEFAULT_TEXT_PATTERNS
        self.table_filter_words = table_filter_words or self.DEFAULT_TABLE_FILTER_WORDS

    async def _call_with_session(self, operation):
        """
        Execute an operation within an MCP session context.

        The MCP SDK uses context managers for session lifecycle management.
        Each call creates a new session to ensure clean state.
        """
        if not _mcp_available:
            raise RuntimeError("MCP client not available")

        async with streamablehttp_client(self.endpoint) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                # Initialize the session
                await session.initialize()
                # Execute the operation
                return await operation(session)

    async def refresh_schema(self):
        """
        Refresh the schema by re-discovering tables from the MCP server.
        Call this after creating new tables to update the LLM's knowledge.
        """
        logger.info("Refreshing KDB+ schema...")
        self._schema_description = ""
        self._additional_context = {}
        self._data_content = {}
        self._data_content_discovered = False
        await self._discover_schema()
        logger.info(f"Schema refreshed. Tables: {self._schema_description[:300] if self._schema_description else 'None'}...")

    def _extract_tables_and_columns_from_schema(self) -> dict[str, list[str]]:
        """
        Extract table names and their columns from the discovered schema description.

        Parses the schema text (from kdbx_describe_tables resource) to find
        table names and column information dynamically.

        Returns:
            Dict mapping table names to list of column names:
            {"daily": ["date", "sym", "open", "high", "low", "close", "volume"], ...}
        """
        tables_with_columns = {}
        if not self._schema_description:
            return tables_with_columns

        import re

        # Pattern 1: Table with columns listed (common format from kdbx_describe_tables)
        # KDB-X MCP format: "TABLE ANALYSIS: tablename" followed by schema info
        # Example: "TABLE ANALYSIS: daily\n...\nSchema Information:\n  date | type=..."
        table_column_patterns = [
            # "TABLE ANALYSIS: tablename" - KDB-X MCP server format
            r'TABLE\s+ANALYSIS:\s+(\w+)',
            # "### tablename\n...columns: col1, col2, ..."
            r'###\s+(\w+)\s*\n[^\n]*?[Cc]olumns?[:\s]+([^\n]+)',
            # "Table: tablename\n...columns: col1, col2, ..."
            r'[Tt]able[:\s]+(\w+)\s*\n[^\n]*?[Cc]olumns?[:\s]+([^\n]+)',
            # "- tablename: col1, col2, ..." or "- tablename (col1, col2, ...)"
            r'^-\s+(\w+)[:\s]+([a-zA-Z_,\s]+)$',
            r'^-\s+(\w+)\s*\(([^)]+)\)',
            # "tablename | col1 | col2 | ..." (markdown table format)
            r'^\|\s*(\w+)\s*\|([^|]+(?:\|[^|]+)*)\|?\s*$',
        ]

        for pattern in table_column_patterns:
            matches = re.findall(pattern, self._schema_description, re.MULTILINE)
            for match in matches:
                # Handle both single captures (just table name) and tuple captures (table + columns)
                if isinstance(match, tuple):
                    table_name = match[0]
                    columns_str = match[1] if len(match) > 1 else ""
                else:
                    table_name = match
                    columns_str = ""

                # Filter out non-table words
                if table_name.lower() in self.table_filter_words:
                    continue

                # Parse columns from the string
                columns = []
                if columns_str:
                    # Split by comma, pipe, or whitespace and clean up
                    potential_cols = re.split(r'[,|\s]+', columns_str)
                    for col in potential_cols:
                        col = col.strip().strip('`"\'')
                        if col and col.lower() not in self.table_filter_words and len(col) > 1:
                            columns.append(col)

                if table_name not in tables_with_columns:
                    tables_with_columns[table_name] = columns
                elif columns:  # Merge columns if we found more
                    existing = set(tables_with_columns[table_name])
                    tables_with_columns[table_name] = list(existing.union(columns))

        # Fallback: extract just table names if no column info found
        if not tables_with_columns:
            table_only_patterns = [
                r'[Tt]able[:\s]+[`"\']?(\w+)[`"\']?',
                r'###\s+(\w+)',
                r'^-\s+(\w+)\s*:',
                r'FROM\s+(\w+)',
            ]
            for pattern in table_only_patterns:
                matches = re.findall(pattern, self._schema_description, re.MULTILINE)
                for match in matches:
                    if match.lower() not in self.table_filter_words and match not in tables_with_columns:
                        tables_with_columns[match] = []  # Empty column list

        # Second pass: Extract columns for tables from KDB-X format
        # Format: "  colname | type=XXX | f=..." after each TABLE ANALYSIS
        if tables_with_columns:
            # Find columns for each table in KDB-X format
            table_sections = re.split(r'TABLE\s+ANALYSIS:\s+', self._schema_description)
            for section in table_sections[1:]:  # Skip first empty split
                # Get table name from start of section
                table_match = re.match(r'(\w+)', section)
                if table_match:
                    table_name = table_match.group(1)
                    if table_name in tables_with_columns and not tables_with_columns[table_name]:
                        # Extract columns from "  colname | type=XXX" format
                        col_matches = re.findall(r'^\s{2}(\w+)\s+\|\s+type=', section, re.MULTILINE)
                        if col_matches:
                            tables_with_columns[table_name] = col_matches
                            logger.debug(f"Extracted columns for {table_name}: {col_matches}")

        logger.debug(f"Extracted tables from schema: {list(tables_with_columns.keys())}")
        return tables_with_columns

    def _extract_tables_from_schema(self) -> list[str]:
        """
        Extract table names from the discovered schema description.

        Returns:
            List of table names
        """
        return list(self._extract_tables_and_columns_from_schema().keys())

    async def discover_data_content(self, tables: list[str] = None, force_refresh: bool = False) -> dict:
        """
        Discover actual data content in tables - symbols, date ranges, sample content.

        This probes the database to understand what data exists, enabling smarter
        query generation. Call this before constructing complex queries.

        Args:
            tables: List of tables to probe. If None, extracts from discovered schema.
            force_refresh: Force re-discovery even if cached.

        Returns:
            Dict with discovered content per table:
            {
                "tablename": {
                    "symbols": [...],  # if symbol column exists
                    "date_range": {"min": "2023-01-01", "max": "2024-01-15"},  # if date column exists
                    "row_count": 10000,
                    "columns": ["col1", "col2", ...],
                    "sample_text_content": {...}  # for text columns
                }
            }
        """
        if self._data_content_discovered and not force_refresh:
            logger.info("Data content already discovered (cached), skipping")
            return self._data_content

        logger.info("=== Starting data content discovery ===")

        if not self._initialized:
            logger.info("Client not initialized, initializing first...")
            await self.initialize()

        # Extract tables AND columns from schema (parsed from kdbx_describe_tables resource)
        # This avoids redundant SQL queries - schema already has this info
        logger.info(f"Extracting tables from schema ({len(self._schema_description)} chars)...")
        tables_with_columns = self._extract_tables_and_columns_from_schema()
        logger.info(f"Extracted {len(tables_with_columns)} tables from schema: {list(tables_with_columns.keys())}")

        # If specific tables requested, filter to those
        if tables is not None:
            tables_with_columns = {t: tables_with_columns.get(t, []) for t in tables if t in tables_with_columns}

        # Fallback: try SQL discovery if schema parsing found nothing
        if not tables_with_columns:
            table_list = await self._discover_tables_via_sql()
            tables_with_columns = {t: [] for t in table_list}

        if not tables_with_columns:
            logger.warning("No tables found to discover content from")
            return self._data_content

        logger.info(f"Discovering data content for tables: {list(tables_with_columns.keys())}")

        for table, schema_columns in tables_with_columns.items():
            try:
                table_info = {"columns": schema_columns}

                # Only query for columns if schema didn't provide them
                columns = schema_columns
                if not columns:
                    result = await self.call_tool("kdbx_run_sql_query", {
                        "query": f"SELECT * FROM {table} LIMIT 1"
                    })
                    columns = self._extract_columns_from_result(result)
                    if columns:
                        table_info["columns"] = columns
                        logger.info(f"Table {table}: discovered columns via SQL {columns}")
                else:
                    logger.info(f"Table {table}: using columns from schema {columns}")

                # Get row count (data value - not in schema)
                result = await self.call_tool("kdbx_run_sql_query", {
                    "query": f"SELECT COUNT(*) as row_count FROM {table}"
                })
                if not result.get("error") and not result.get("isError"):
                    count_info = self._extract_single_value(result, "row_count")
                    if count_info is not None:
                        table_info["row_count"] = count_info

                # If there's a symbol/ticker column, get distinct values (data values - not in schema)
                symbol_columns = [c for c in columns if c.lower() in self.symbol_patterns]
                if symbol_columns:
                    sym_col = symbol_columns[0]
                    result = await self.call_tool("kdbx_run_sql_query", {
                        "query": f"SELECT DISTINCT {sym_col} FROM {table} LIMIT 100"
                    })
                    if not result.get("error") and not result.get("isError"):
                        symbols = self._extract_column_values(result, sym_col)
                        if symbols:
                            table_info["symbols"] = symbols
                            table_info["symbol_column"] = sym_col
                            logger.info(f"Table {table}: found {len(symbols)} symbols in column '{sym_col}'")

                # If there's a date column, get date range
                date_columns = [c for c in columns if c.lower() in self.date_patterns]
                if date_columns:
                    date_col = date_columns[0]
                    result = await self.call_tool("kdbx_run_sql_query", {
                        "query": f"SELECT MIN({date_col}) as min_date, MAX({date_col}) as max_date FROM {table}"
                    })
                    if not result.get("error") and not result.get("isError"):
                        date_info = self._extract_date_range(result)
                        if date_info:
                            table_info.update(date_info)
                            table_info["date_column"] = date_col
                            logger.info(f"Table {table}: date range {date_info.get('date_range', {})}")

                # For text columns, get sample content (useful for search queries)
                text_columns = [c for c in columns if c.lower() in self.text_patterns]
                if text_columns:
                    table_info["text_columns"] = text_columns
                    # Get sample from first text column
                    text_col = text_columns[0]
                    order_clause = f"ORDER BY {date_columns[0]} DESC" if date_columns else ""
                    result = await self.call_tool("kdbx_run_sql_query", {
                        "query": f"SELECT DISTINCT {text_col} FROM {table} {order_clause} LIMIT 10"
                    })
                    if not result.get("error") and not result.get("isError"):
                        samples = self._extract_column_values(result, text_col)
                        if samples:
                            table_info["sample_text"] = {text_col: samples[:10]}

                if table_info.get("columns"):
                    self._data_content[table] = table_info

            except Exception as e:
                logger.warning(f"Failed to discover content for table {table}: {e}")

        self._data_content_discovered = True
        logger.info(f"=== Data content discovery complete ===")
        logger.info(f"Discovered tables: {list(self._data_content.keys())}")
        for table, info in self._data_content.items():
            logger.info(f"  {table}: {info.get('row_count', 'N/A')} rows, symbols={len(info.get('symbols', []))}, date_range={info.get('date_range', 'N/A')}")
        return self._data_content

    def _extract_column_values(self, result: dict, column: str) -> list:
        """Extract values from a specific column in query results."""
        values = []
        content = result.get("content", [])
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                try:
                    text = item.get("text", "")
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        data = parsed.get("data", [])
                        if isinstance(data, str):
                            data = json.loads(data)
                        for row in data:
                            if isinstance(row, dict) and column in row:
                                val = row[column]
                                if val and val not in values:
                                    values.append(val)
                except (json.JSONDecodeError, TypeError):
                    pass
        return values

    def _extract_date_range(self, result: dict) -> dict:
        """Extract date range and row count from query results."""
        content = result.get("content", [])
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                try:
                    text = item.get("text", "")
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        data = parsed.get("data", [])
                        if isinstance(data, str):
                            data = json.loads(data)
                        if data and len(data) > 0:
                            row = data[0]
                            info = {}
                            if "min_date" in row and "max_date" in row:
                                info["date_range"] = {
                                    "min": str(row["min_date"]),
                                    "max": str(row["max_date"])
                                }
                            if "row_count" in row:
                                info["row_count"] = row["row_count"]
                            return info
                except (json.JSONDecodeError, TypeError):
                    pass
        return {}

    def _extract_columns_from_result(self, result: dict) -> list[str]:
        """Extract column names from a SELECT * query result."""
        columns = []
        content = result.get("content", [])
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                try:
                    text = item.get("text", "")
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        data = parsed.get("data", [])
                        if isinstance(data, str):
                            data = json.loads(data)
                        if data and len(data) > 0 and isinstance(data[0], dict):
                            columns = list(data[0].keys())
                            return columns
                except (json.JSONDecodeError, TypeError):
                    pass
        return columns

    def _extract_single_value(self, result: dict, key: str):
        """Extract a single value from query results."""
        content = result.get("content", [])
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                try:
                    text = item.get("text", "")
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        data = parsed.get("data", [])
                        if isinstance(data, str):
                            data = json.loads(data)
                        if data and len(data) > 0 and isinstance(data[0], dict):
                            return data[0].get(key)
                except (json.JSONDecodeError, TypeError):
                    pass
        return None

    async def _discover_tables_via_sql(self) -> list[str]:
        """
        Discover available tables via SQL queries.

        Fallback when schema parsing doesn't find tables.
        """
        tables = []

        # Try common SQL patterns for listing tables
        discovery_queries = [
            "SHOW TABLES",
            "SELECT name FROM tables",
            "SELECT table_name FROM information_schema.tables",
        ]

        for query in discovery_queries:
            try:
                result = await self.call_tool("kdbx_run_sql_query", {"query": query})
                if not result.get("error") and not result.get("isError"):
                    # Try to extract table names from various result formats
                    content = result.get("content", [])
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text = item.get("text", "")
                            try:
                                parsed = json.loads(text)
                                if isinstance(parsed, dict):
                                    data = parsed.get("data", [])
                                    if isinstance(data, str):
                                        data = json.loads(data)
                                    for row in data:
                                        if isinstance(row, dict):
                                            # Try common column names for table names
                                            for col in ['name', 'table_name', 'tablename', 'TABLE_NAME']:
                                                if col in row and row[col]:
                                                    tables.append(row[col])
                                        elif isinstance(row, str):
                                            tables.append(row)
                            except (json.JSONDecodeError, TypeError):
                                pass

                    if tables:
                        logger.info(f"Discovered tables via SQL: {tables}")
                        return tables

            except Exception as e:
                logger.debug(f"Table discovery query failed: {query} - {e}")

        return tables

    def get_data_content_description(self) -> str:
        """
        Get a human-readable description of discovered data content.

        Returns:
            Formatted string describing available data for LLM context.
        """
        if not self._data_content:
            return "No data content discovered yet. Run discover_data_content() first."

        parts = ["## Available Data Content (Discovered from Database)"]

        # Add dynamic guidance based on discovered columns
        symbol_cols = set()
        for info in self._data_content.values():
            if "symbol_column" in info:
                symbol_cols.add(info["symbol_column"])
        if symbol_cols:
            cols_str = ", ".join(f"`{c}`" for c in symbol_cols)
            parts.append(f"**IMPORTANT**: Use {cols_str} column(s) for filtering by ticker/symbol, not company names.")
        parts.append("")

        for table, info in self._data_content.items():
            parts.append(f"### Table: {table}")

            # Show columns
            if "columns" in info and info["columns"]:
                parts.append(f"- **Columns**: {', '.join(info['columns'])}")

            if "symbols" in info:
                sym_col = info.get("symbol_column", "symbol")
                symbols_preview = info["symbols"][:20]
                parts.append(f"- **Available values in `{sym_col}`**: {', '.join(str(s) for s in symbols_preview)}")
                if len(info["symbols"]) > 20:
                    parts.append(f"  (and {len(info['symbols']) - 20} more)")

            if "date_range" in info:
                dr = info["date_range"]
                parts.append(f"- **Date range**: {dr.get('min', 'N/A')} to {dr.get('max', 'N/A')}")

            if "row_count" in info:
                parts.append(f"- **Total rows**: {info['row_count']:,}")

            if "text_columns" in info:
                parts.append(f"- **Text columns** (searchable): {', '.join(info['text_columns'])}")

            if "sample_text" in info:
                for col, samples in info["sample_text"].items():
                    parts.append(f"- **Sample `{col}` values**:")
                    for sample in samples[:5]:
                        sample_str = str(sample)[:80]
                        parts.append(f"  - {sample_str}{'...' if len(str(sample)) > 80 else ''}")

            parts.append("")

        return "\n".join(parts)

    async def initialize(self, force_refresh: bool = False):
        """Initialize the client and discover available tools and resources."""
        if self._initialized and not force_refresh:
            return

        try:
            # Discover tools
            async def _init_tools(session):
                result = await session.list_tools()
                return result.tools if hasattr(result, 'tools') else result

            tools = await self._call_with_session(_init_tools)
            self._tools = {tool.name: tool for tool in tools}

            # Build a comprehensive tools description for the LLM
            self._tools_description = self._build_tools_description()

            logger.info(f"MCP client initialized with {len(self._tools)} tools: {list(self._tools.keys())}")
            logger.debug(f"Tools description:\n{self._tools_description}")

            # Discover resources (schema/tables)
            await self._discover_schema()

            logger.info(f"Schema discovery complete. Schema: {self._schema_description[:200] if self._schema_description else 'None'}...")

            self._initialized = True

        except Exception as e:
            logger.error(f"Failed to initialize MCP client: {e}")
            raise

    def _is_resource_for_llm(self, resource: dict) -> bool:
        """
        Check if a resource is intended for LLM consumption based on annotations.

        MCP Best Practice: Use resource annotations to filter resources.
        Resources with audience: ["llm"] are specifically intended for LLM context.
        If no audience is specified, include the resource by default.

        Args:
            resource: Resource metadata dict with optional annotations

        Returns:
            True if resource should be included in LLM context
        """
        annotations = resource.get('annotations', {})
        if not annotations:
            return True  # No annotations = include by default

        # Check audience annotation
        audience = annotations.get('audience', [])
        if audience:
            # If audience is specified, check if 'llm' or 'assistant' is included
            if isinstance(audience, list):
                return any(a in ['llm', 'assistant', 'ai'] for a in audience)
            return audience in ['llm', 'assistant', 'ai']

        return True  # No audience specified = include by default

    def _get_resource_priority(self, resource: dict) -> float:
        """
        Get the priority of a resource for ordering.

        MCP Best Practice: Use priority annotation to order resources.
        Higher priority resources are included first in the context.

        Args:
            resource: Resource metadata dict with optional annotations

        Returns:
            Priority value (higher = more important, default 0.5)
        """
        annotations = resource.get('annotations', {})
        priority = annotations.get('priority', 0.5)
        try:
            return float(priority)
        except (TypeError, ValueError):
            return 0.5

    def _sort_resources_by_priority(self, resources: list[dict]) -> list[dict]:
        """
        Sort resources by priority annotation (highest first).

        MCP Best Practice: Process higher priority resources first.

        Args:
            resources: List of resource metadata dicts

        Returns:
            Sorted list with highest priority first
        """
        return sorted(resources, key=lambda r: self._get_resource_priority(r), reverse=True)

    async def _discover_schema(self):
        """
        Discover available resources from the MCP server following MCP best practices.

        According to MCP spec, we should:
        1. List all available resources
        2. Read ALL resources to provide full context to the LLM
        3. Use resource annotations to filter and prioritize content
        4. Categorize resources by type (schema, SQL guidance, etc.)
        """
        try:
            # Try to list resources from MCP server
            async def _list_resources(session):
                try:
                    result = await session.list_resources()
                    return result.resources if hasattr(result, 'resources') else result
                except Exception as e:
                    logger.debug(f"list_resources not supported: {e}")
                    return []

            resources = await self._call_with_session(_list_resources)

            if resources:
                self._resources = [
                    {
                        "uri": str(getattr(r, 'uri', r)),  # Convert AnyUrl to string
                        "name": str(getattr(r, 'name', '')),
                        "description": str(getattr(r, 'description', '')),
                        "mimeType": str(getattr(r, 'mimeType', '')),
                        # MCP best practice: capture annotations if available
                        "annotations": getattr(r, 'annotations', None) or {}
                    }
                    for r in resources
                ]
                logger.info(f"Discovered {len(self._resources)} resources from MCP server: {[r.get('name', r.get('uri')) for r in self._resources]}")

                # MCP Best Practice: Filter resources by audience annotation
                llm_resources = [r for r in self._resources if self._is_resource_for_llm(r)]
                filtered_count = len(self._resources) - len(llm_resources)
                if filtered_count > 0:
                    logger.info(f"Filtered {filtered_count} resources not intended for LLM (audience annotation)")

                # MCP Best Practice: Sort by priority annotation
                llm_resources = self._sort_resources_by_priority(llm_resources)
                if llm_resources:
                    priorities = [self._get_resource_priority(r) for r in llm_resources[:3]]
                    logger.debug(f"Resource priorities (top 3): {priorities}")

                # MCP Best Practice: Read ALL LLM-relevant resources and categorize by content
                # This ensures the LLM has full context from the server
                all_resource_contents = {}
                schema_content_parts = []
                sql_guidance_parts = []
                other_content_parts = []

                logger.info(f"Reading {len(llm_resources)} resources for LLM context...")

                for resource in llm_resources:
                    uri = resource.get('uri')
                    name = str(resource.get('name', '')).lower()
                    description = str(resource.get('description', '')).lower()
                    resource_name = resource.get('name', uri)
                    priority = self._get_resource_priority(resource)

                    try:
                        content = await self._read_resource(uri)
                        if content:
                            all_resource_contents[resource_name] = content
                            logger.info(f"Read resource: {resource_name} (priority={priority}, {len(content)} chars)")
                            logger.debug(f"Resource content preview: {content[:500]}...")

                            # Categorize content based on name/description
                            # Check both name and description for keywords
                            combined_text = f"{name} {description}"
                            if any(keyword in combined_text for keyword in ['schema', 'tables', 'describe', 'meta', 'column', 'structure']):
                                schema_content_parts.append((priority, f"## {resource_name}\n{content}"))
                                logger.info(f"Categorized as SCHEMA: {resource_name}")
                            elif any(keyword in combined_text for keyword in ['sql', 'guidance', 'query', 'syntax', 'example', 'how to']):
                                sql_guidance_parts.append((priority, f"## {resource_name}\n{content}"))
                                logger.info(f"Categorized as SQL_GUIDANCE: {resource_name}")
                            else:
                                # IMPORTANT: Still include uncategorized resources as context
                                other_content_parts.append((priority, resource_name, content))
                                logger.info(f"Categorized as OTHER_CONTEXT: {resource_name}")
                        else:
                            logger.warning(f"Resource {resource_name} returned empty content")
                    except Exception as e:
                        logger.warning(f"Failed to read resource {resource_name}: {e}")

                # Sort content parts by priority before combining
                schema_content_parts.sort(key=lambda x: x[0], reverse=True)
                sql_guidance_parts.sort(key=lambda x: x[0], reverse=True)
                other_content_parts.sort(key=lambda x: x[0], reverse=True)

                # Combine schema content (already sorted by priority)
                if schema_content_parts:
                    self._schema_description = "\n\n".join([part[1] for part in schema_content_parts])
                    logger.info(f"Combined schema from {len(schema_content_parts)} resources")

                # Combine SQL guidance content (already sorted by priority)
                if sql_guidance_parts:
                    self._sql_guidance = "\n\n".join([part[1] for part in sql_guidance_parts])
                    logger.info(f"Combined SQL guidance from {len(sql_guidance_parts)} resources")

                # Store other content for additional context
                if other_content_parts:
                    self._additional_context = {name: content for _, name, content in other_content_parts}
                    logger.info(f"Stored {len(other_content_parts)} additional context resources")

                # If no categorized content, include all resources as general context
                if not self._schema_description and all_resource_contents:
                    self._schema_description = self._build_schema_description_from_contents(all_resource_contents)

                # Fallback to resource list description
                if not self._schema_description:
                    self._schema_description = self._build_schema_description()
            else:
                # If no resources endpoint, try querying for schema via available tools
                logger.info("No resources endpoint, attempting schema discovery via tools")
                await self._discover_schema_via_tools()

        except Exception as e:
            logger.warning(f"Failed to discover schema: {e}")
            # Try schema discovery via tools as fallback
            await self._discover_schema_via_tools()

    def _build_schema_description_from_contents(self, contents: dict) -> str:
        """Build schema description from all resource contents."""
        if not contents:
            return "No schema information available."

        parts = ["## Available Resources from MCP Server"]
        for name, content in contents.items():
            parts.append(f"\n### {name}")
            # Truncate very long content
            if len(content) > 5000:
                parts.append(content[:5000] + "\n... (truncated)")
            else:
                parts.append(content)

        return "\n".join(parts)

    async def _read_resource(self, uri: str) -> str:
        """Read content from an MCP resource."""
        try:
            async def _read(session):
                try:
                    result = await session.read_resource(uri)
                    # Extract content from result
                    if hasattr(result, 'contents'):
                        contents = result.contents
                        text_parts = []
                        for content in contents:
                            if hasattr(content, 'text'):
                                text_parts.append(content.text)
                            elif isinstance(content, dict) and 'text' in content:
                                text_parts.append(content['text'])
                        return "\n".join(text_parts)
                    elif isinstance(result, str):
                        return result
                    return str(result)
                except Exception as e:
                    logger.debug(f"read_resource failed for {uri}: {e}")
                    return ""

            content = await self._call_with_session(_read)
            return content
        except Exception as e:
            logger.warning(f"Failed to read resource {uri}: {e}")
            return ""

    async def _discover_schema_via_tools(self):
        """
        Discover schema by dynamically finding and calling schema-related tools.

        This is a fallback when MCP resources endpoint is not available.
        Instead of hardcoding tool names, we look for any tool that appears
        to be schema-related based on its name or description.
        """
        # Look for schema-related tools dynamically from discovered tools
        schema_keywords = ['schema', 'tables', 'describe', 'list', 'meta', 'columns']

        for tool_name, tool in self._tools.items():
            tool_name_lower = tool_name.lower()
            tool_desc = getattr(tool, 'description', '').lower()

            # Check if tool appears to be schema-related
            if any(keyword in tool_name_lower or keyword in tool_desc for keyword in schema_keywords):
                try:
                    logger.info(f"Attempting schema discovery via tool: {tool_name}")
                    # Call with empty args - schema tools typically don't need arguments
                    result = await self.call_tool(tool_name, {})

                    if result and not result.get("error"):
                        content = result.get("content", [])
                        schema_text = self._extract_schema_from_result(content)
                        if schema_text and "error" not in schema_text.lower():
                            self._schema_description = schema_text
                            logger.info(f"Schema discovered via tool: {tool_name}")
                            return
                except Exception as e:
                    logger.debug(f"Schema discovery via {tool_name} failed: {e}")

        # Fallback: try SQL-based discovery if there's a query tool
        sql_tools = [name for name in self._tools.keys() if 'sql' in name.lower() or 'query' in name.lower()]
        for sql_tool in sql_tools:
            try:
                logger.info(f"Attempting schema discovery via SQL tool: {sql_tool}")
                # Try common SQL patterns for getting table info
                queries = [
                    "tables[]",  # KDB+ function
                    "meta `",  # KDB+ meta
                    "SHOW TABLES",
                    "SELECT name FROM tables",
                ]

                for query in queries:
                    try:
                        result = await self.call_tool(sql_tool, {"query": query})
                        if result and not result.get("error"):
                            content = result.get("content", [])
                            schema_text = self._extract_schema_from_result(content)
                            if schema_text and "error" not in schema_text.lower() and "can't lookup" not in schema_text.lower():
                                self._schema_description = f"Available tables:\n{schema_text}"
                                logger.info(f"Schema discovered via SQL query: {query}")
                                return
                    except Exception:
                        continue
            except Exception as e:
                logger.debug(f"Schema discovery via {sql_tool} failed: {e}")

        # If all else fails, provide guidance for dynamic discovery
        self._schema_description = """Schema information not available at initialization.
IMPORTANT: Use the available tools to discover the database schema dynamically before querying data.
Do NOT assume any table or column names exist."""
        logger.warning("Could not discover schema - LLM instructed to discover dynamically")

    def _extract_schema_from_result(self, content: list) -> str:
        """Extract schema text from tool result content."""
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
            elif isinstance(item, str):
                text_parts.append(item)
        return "\n".join(text_parts)

    def _build_schema_description(self) -> str:
        """Build a description of available resources/schema for the LLM."""
        if not self._resources:
            return "No schema information available."

        descriptions = ["Available resources/tables:"]
        for resource in self._resources:
            uri = resource.get("uri", "")
            name = resource.get("name", uri)
            desc = resource.get("description", "")

            resource_desc = f"- {name}"
            if desc:
                resource_desc += f": {desc}"
            descriptions.append(resource_desc)

        return "\n".join(descriptions)

    def _build_tools_description(self) -> str:
        """Build a detailed description of available tools for the LLM."""
        descriptions = []

        for name, tool in self._tools.items():
            tool_desc = f"### {name}\n"
            tool_desc += f"Description: {getattr(tool, 'description', 'No description available')}\n"

            # Extract input schema if available
            input_schema = getattr(tool, 'inputSchema', None)
            if input_schema:
                tool_desc += "Parameters:\n"
                properties = input_schema.get('properties', {})
                required = input_schema.get('required', [])

                for param_name, param_info in properties.items():
                    param_type = param_info.get('type', 'any')
                    param_desc = param_info.get('description', '')
                    is_required = param_name in required
                    req_str = " (required)" if is_required else " (optional)"
                    tool_desc += f"  - {param_name}: {param_type}{req_str}"
                    if param_desc:
                        tool_desc += f" - {param_desc}"
                    tool_desc += "\n"
            else:
                tool_desc += "Parameters: None or unknown\n"

            descriptions.append(tool_desc)

        return "\n".join(descriptions)

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """
        Call an MCP tool following MCP best practices.

        According to MCP spec, tool results can have:
        - content: list of content items (text, image, etc.)
        - isError: boolean flag indicating if the tool execution failed
        - structuredContent: optional structured JSON content

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            Tool result as dictionary with:
            - content: list of content items
            - tool: tool name
            - arguments: tool arguments
            - isError: boolean (from MCP result or our error handling)
            - error: error message (if applicable)
        """
        try:
            async def _call(session):
                result = await session.call_tool(tool_name, arguments)
                return result

            result = await self._call_with_session(_call)

            # Convert MCP result format to our expected format
            response = {
                "tool": tool_name,
                "arguments": arguments,
                "isError": False  # Default to no error
            }

            # MCP Best Practice: Check for isError flag in result
            if hasattr(result, 'isError'):
                response["isError"] = result.isError

            if hasattr(result, 'content'):
                content_list = []
                for item in result.content:
                    if hasattr(item, 'text'):
                        content_list.append({"type": "text", "text": item.text})
                    elif hasattr(item, 'type') and hasattr(item, 'data'):
                        content_list.append({"type": item.type, "data": item.data})
                    elif hasattr(item, 'resource'):
                        # MCP embedded resource content
                        resource = item.resource
                        content_list.append({
                            "type": "resource",
                            "uri": str(getattr(resource, 'uri', '')),
                            "text": getattr(resource, 'text', ''),
                            "mimeType": getattr(resource, 'mimeType', '')
                        })
                    else:
                        content_list.append({"type": "text", "text": str(item)})
                response["content"] = content_list

                # If isError is True, also set error message from content
                if response["isError"] and content_list:
                    error_texts = [c.get("text", "") for c in content_list if c.get("type") == "text"]
                    if error_texts:
                        response["error"] = " ".join(error_texts)

            # MCP Best Practice: Handle structuredContent if available
            if hasattr(result, 'structuredContent'):
                response["structuredContent"] = result.structuredContent

            elif isinstance(result, dict):
                response.update(result)
                response["tool"] = tool_name
                response["arguments"] = arguments
            else:
                response["content"] = [{"type": "text", "text": str(result)}]

            return response

        except Exception as e:
            logger.error(f"MCP tool call failed for {tool_name}: {e}")
            # Return error in MCP-compliant format
            return {
                "error": str(e),
                "tool": tool_name,
                "arguments": arguments,
                "isError": True,
                "content": [{"type": "text", "text": f"Tool execution error: {str(e)}"}]
            }

    async def get_tools_description(self) -> str:
        """Get the description of available tools."""
        if not self._initialized:
            await self.initialize()
        return self._tools_description

    async def get_schema_description(self) -> str:
        """Get the description of available schema/tables."""
        if not self._initialized:
            await self.initialize()
        return self._schema_description

    async def list_tools(self) -> list[dict]:
        """List available tools from the MCP server."""
        if not self._initialized:
            await self.initialize()

        return [
            {
                "name": name,
                "description": getattr(tool, 'description', ''),
                "inputSchema": getattr(tool, 'inputSchema', {})
            }
            for name, tool in self._tools.items()
        ]

    async def intelligent_query(
        self,
        user_query: str,
        llm: Optional[ChatOpenAI] = None,
        max_iterations: int = 3
    ) -> tuple[str, list[dict]]:
        """
        Intelligently answer a user query using available MCP tools.

        This method uses an iterative approach:
        1. Plan tool usage (may include schema discovery)
        2. Execute tools
        3. If schema was discovered, re-plan with new knowledge
        4. Continue until we have data or hit max iterations
        5. Synthesize the results into an answer

        Args:
            user_query: The user's natural language query
            llm: Optional LLM instance (creates one if not provided)
            max_iterations: Maximum planning iterations (default 3)

        Returns:
            Tuple of (answer, tool_results)
        """
        if not self._initialized:
            await self.initialize()

        # Discover actual data content before planning queries
        if not self._data_content_discovered:
            logger.info("Discovering data content for intelligent query...")
            await self.discover_data_content()

        if llm is None:
            llm = self._get_default_llm()

        all_tool_results = []
        discovered_schema = ""

        for iteration in range(max_iterations):
            logger.info(f"Planning iteration {iteration + 1}/{max_iterations}")

            # Plan tool usage, including any discovered schema from previous iterations
            plan = await self._plan_tool_usage(
                user_query,
                llm,
                additional_schema=discovered_schema
            )

            # Check if data is not available (LLM determined schema doesn't support the query)
            if plan.get("data_available") is False:
                limitations = plan.get("limitations", "")
                reasoning = plan.get("reasoning", "")
                answer = f"{reasoning}\n\n{limitations}" if limitations else reasoning
                logger.info(f"Data not available: {answer[:100]}...")
                return answer, []

            if not plan.get("steps"):
                if iteration == 0:
                    logger.info(f"No tools needed for query: {user_query[:50]}...")
                    return plan.get("reasoning", "Unable to answer with available tools."), []
                else:
                    # We've done some work, break and synthesize
                    break

            # Execute the planned tools
            iteration_results = []
            schema_discovery_done = False

            for step in plan["steps"]:
                tool_name = step.get("tool")
                arguments = step.get("arguments", {})
                purpose = step.get("purpose", "").lower()

                logger.info(f"Executing tool: {tool_name} with args: {arguments}")
                result = await self.call_tool(tool_name, arguments)
                result["purpose"] = step.get("purpose", "")
                iteration_results.append(result)
                all_tool_results.append(result)

                # Check if this was a schema discovery step
                if any(keyword in purpose for keyword in ['schema', 'discover', 'list tables', 'describe', 'metadata']):
                    schema_discovery_done = True
                    # Extract schema info from result
                    if not result.get("error"):
                        schema_text = self._extract_schema_from_result(result.get("content", []))
                        if schema_text:
                            discovered_schema += f"\n\nDiscovered from {tool_name}:\n{schema_text}"
                            logger.info(f"Schema discovered: {schema_text[:200]}...")

                # If there's an error, log it but continue
                if result.get("error"):
                    logger.warning(f"Tool {tool_name} returned error: {result['error']}")

            # If we discovered schema, re-plan with the new knowledge
            if schema_discovery_done and iteration < max_iterations - 1:
                logger.info("Schema discovered, re-planning with new knowledge...")
                continue
            else:
                # No more schema discovery needed, we're done planning
                break

        if not all_tool_results:
            return "Unable to answer with available tools.", []

        # Synthesize results into an answer
        answer = await self._synthesize_results(user_query, all_tool_results, llm)

        return answer, all_tool_results

    def _format_additional_context(self) -> str:
        """
        Format additional context resources for the LLM prompt.

        MCP Best Practice: Include all relevant resources in the prompt,
        but keep the format concise to avoid token waste.

        Returns:
            Formatted string of additional context or a note if none available
        """
        if not self._additional_context:
            return "No additional context available."

        parts = []
        for name, content in self._additional_context.items():
            # Truncate very long content to avoid token waste
            if len(content) > 2000:
                content = content[:2000] + "\n... (truncated)"
            parts.append(f"### {name}\n{content}")

        return "\n\n".join(parts)

    async def _plan_tool_usage(
        self,
        user_query: str,
        llm: ChatOpenAI,
        additional_schema: str = ""
    ) -> dict:
        """Ask the LLM to plan which tools to use."""
        # Use SQL guidance from MCP server if available, otherwise provide a default note
        sql_guidance = self._sql_guidance if self._sql_guidance else "No specific SQL syntax guidance available. Use standard SQL syntax."

        # Format additional context from other resources
        additional_context = self._format_additional_context()

        # Combine known schema with any dynamically discovered schema
        schema_description = self._schema_description
        if additional_schema:
            schema_description += f"\n\n## Dynamically Discovered Schema:\n{additional_schema}"

        # Get data content description (discovered data in tables)
        data_content = self.get_data_content_description()

        prompt = TOOL_SELECTION_PROMPT.format(
            tools_description=self._tools_description,
            schema_description=schema_description,
            data_content=data_content,
            sql_guidance=sql_guidance,
            additional_context=additional_context,
            user_query=user_query
        )

        try:
            response = await llm.ainvoke(prompt)
            content = response.content.strip()
            logger.debug(f"LLM raw response ({len(content)} chars): {content[:500]}...")

            # Extract JSON from the response
            json_match = self._extract_json(content)
            if json_match:
                plan = json.loads(json_match)
                logger.info(f"Tool plan: {plan.get('reasoning', 'No reasoning')}")
                logger.info(f"Tool steps: {len(plan.get('steps', []))} steps planned")
                return plan
            else:
                logger.warning(f"Could not extract JSON from LLM response. Full response:\n{content[:1000]}...")

                # Fallback: Try to extract SQL query directly
                sql_query = self._extract_sql_fallback(content)
                if sql_query:
                    logger.info(f"Using SQL fallback: {sql_query[:100]}...")
                    return {
                        "reasoning": "Extracted SQL from response (JSON parsing failed)",
                        "steps": [{
                            "tool": "kdbx_run_sql_query",
                            "arguments": {"query": sql_query},
                            "purpose": "Execute user query"
                        }]
                    }

                # Return a fallback with debug info
                # Include first 200 chars of response for debugging
                preview = content[:200].replace('\n', ' ') if content else "empty"
                return {"reasoning": f"Failed to parse LLM response. Preview: {preview}...", "steps": []}

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error in tool plan: {e}")
            return {"reasoning": f"JSON parse error: {e}", "steps": []}
        except Exception as e:
            logger.error(f"Error planning tool usage: {e}")
            return {"reasoning": f"Error: {e}", "steps": []}

    async def _synthesize_results(
        self,
        user_query: str,
        tool_results: list[dict],
        llm: ChatOpenAI
    ) -> str:
        """Synthesize tool results into a coherent answer."""
        # Format tool results for the LLM
        results_text = []
        for i, result in enumerate(tool_results, 1):
            tool_name = result.get("tool", "unknown")
            purpose = result.get("purpose", "")
            content = result.get("content", [])
            error = result.get("error")

            results_text.append(f"### Step {i}: {tool_name}")
            if purpose:
                results_text.append(f"Purpose: {purpose}")

            if error:
                results_text.append(f"Error: {error}")
            elif content:
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        results_text.append(item.get("text", ""))
                    elif isinstance(item, str):
                        results_text.append(item)
            results_text.append("")

        prompt = RESULT_SYNTHESIS_PROMPT.format(
            user_query=user_query,
            tool_results="\n".join(results_text)
        )

        try:
            response = await llm.ainvoke(prompt)
            return response.content.strip()
        except Exception as e:
            logger.error(f"Error synthesizing results: {e}")
            return f"Error synthesizing results: {e}\n\nRaw results:\n" + "\n".join(results_text)

    def _extract_json(self, text: str) -> Optional[str]:
        """Extract JSON from text that might contain markdown code blocks or thinking tags."""
        import re

        original_text = text  # Keep for logging

        # Strip ALL Nemotron thinking tags (handle multiple blocks and nested content)
        # Use greedy match to catch everything between <think> and </think>
        text = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.IGNORECASE)
        # Also handle unclosed think tags (model sometimes doesn't close them)
        text = re.sub(r'<think>[\s\S]*$', '', text, flags=re.IGNORECASE)
        text = text.strip()

        # If text is empty after stripping, log and return None
        if not text:
            logger.warning(f"Text empty after stripping think tags. Original: {original_text[:500]}...")
            return None

        # Try to find JSON in code blocks first (greedy match for nested content)
        code_block_match = re.search(r'```(?:json)?\s*(\{[\s\S]*\})\s*```', text)
        if code_block_match:
            candidate = code_block_match.group(1).strip()
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass

        # Try to find the outermost JSON object by matching braces
        # Find first { and last } and try to parse
        first_brace = text.find('{')
        if first_brace == -1:
            logger.debug(f"No opening brace found in: {text[:300]}...")
            return None

        last_brace = text.rfind('}')
        if last_brace == -1 or last_brace <= first_brace:
            logger.debug(f"No valid closing brace found in: {text[:300]}...")
            return None

        candidate = text[first_brace:last_brace + 1]
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError as e:
            logger.debug(f"JSON decode failed for first/last brace approach: {e}")

        # Try a balanced brace approach
        depth = 0
        start = -1
        for i, char in enumerate(text):
            if char == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0 and start != -1:
                    candidate = text[start:i + 1]
                    try:
                        json.loads(candidate)
                        return candidate
                    except json.JSONDecodeError:
                        start = -1  # Try next potential JSON

        return None

    async def _answer_from_schema(self, user_query: str, llm: ChatOpenAI) -> Optional[str]:
        """
        Answer schema/metadata questions using MCP resources.
        Reads kdbx_describe_tables resource for fresh schema info.
        """
        schema_info = ""

        # Read MCP resources for schema info
        # kdbx_describe_tables - lists tables and their columns
        # kdbx_sql_query_guidance - SQL syntax help
        schema_resource_names = ['kdbx_describe_tables', 'kdbx_sql_query_guidance']

        for resource in self._resources:
            uri = resource.get("uri", "")
            name = resource.get("name", "")

            if name in schema_resource_names:
                try:
                    logger.info(f"Reading MCP resource: {name}")
                    content = await self._read_resource(uri)
                    if content:
                        schema_info += f"\n## {name}\n{content}\n"
                except Exception as e:
                    logger.debug(f"Resource {name} read failed: {e}")

        # Fall back to cached schema
        if not schema_info and self._schema_description:
            schema_info = self._schema_description

        if not schema_info:
            return None

        prompt = f"""Answer the user's question about the database.

## Database Information:
{schema_info}

## User Question:
{user_query}

Answer based on the information above. Be concise and helpful."""

        try:
            response = await llm.ainvoke(prompt)
            return response.content.strip()
        except Exception as e:
            logger.error(f"Schema answer generation failed: {e}")
            return None

    def _extract_sql_fallback(self, text: str) -> Optional[str]:
        """
        Fallback: Try to extract SQL query directly from LLM response.
        Used when JSON parsing fails but the model might have included a query.
        """
        import re

        # Strip think tags
        text = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.IGNORECASE)
        text = re.sub(r'<think>[\s\S]*$', '', text, flags=re.IGNORECASE)

        # Look for SQL patterns
        sql_patterns = [
            r'SELECT\s+[\s\S]+?(?:FROM|LIMIT)\s+\w+',  # SELECT ... FROM/LIMIT
            r'"query"\s*:\s*"([^"]+)"',  # "query": "..."
            r'`([^`]*SELECT[^`]*)`',  # `SELECT ...`
            r'query["\']?\s*[:=]\s*["\']([^"\']+)["\']',  # query: "..." or query='...'
        ]

        for pattern in sql_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                sql = match.group(1) if match.lastindex else match.group(0)
                sql = sql.strip()
                if sql and len(sql) > 10:  # Sanity check
                    logger.info(f"Extracted SQL via fallback: {sql[:100]}...")
                    return sql

        return None

    def _get_default_llm(self) -> ChatOpenAI:
        """Get the default LLM for tool planning and synthesis."""
        instruct_base_url = os.getenv("INSTRUCT_BASE_URL", "https://integrate.api.nvidia.com/v1")
        instruct_model_name = os.getenv("INSTRUCT_MODEL_NAME", "meta/llama-3.3-70b-instruct")
        instruct_api_key = os.getenv("INSTRUCT_API_KEY", os.getenv("NVIDIA_API_KEY", ""))

        llm_config = {
            "base_url": instruct_base_url,
            "model": instruct_model_name,
            "temperature": 0.0,
            "max_tokens": 2000
        }
        if instruct_api_key:
            llm_config["api_key"] = instruct_api_key

        return ChatOpenAI(**llm_config)

    async def simple_chat_query(
        self,
        user_query: str,
        llm: Optional[ChatOpenAI] = None
    ) -> tuple[str, str, list]:
        """
        Simple chat query - generates ONE SQL query directly without complex planning.

        Optimized for interactive chat:
        - Uses instruct model (no thinking tokens)
        - Single query generation (no iterations)
        - Faster response times
        - Schema questions answered directly (no SQL needed)

        Args:
            user_query: The user's natural language query
            llm: Optional LLM instance

        Returns:
            Tuple of (answer, sql_query, data)
        """
        if not self._initialized:
            await self.initialize()

        # Discover actual data content before generating queries
        if not self._data_content_discovered:
            logger.info("Discovering data content for simple chat query...")
            await self.discover_data_content()

        if llm is None:
            llm = self._get_default_llm()

        # Check if this is a schema/metadata question (answer from cached schema, no SQL)
        query_lower = user_query.lower()
        schema_keywords = ['what table', 'which table', 'list table', 'show table', 'available table',
                          'what schema', 'describe schema', 'database schema', 'what column']

        if any(keyword in query_lower for keyword in schema_keywords):
            logger.info(f"Schema question detected, answering from cached schema")
            schema_answer = await self._answer_from_schema(user_query, llm)
            if schema_answer:
                return schema_answer, None, []

        # Get data content description for context
        data_content = self.get_data_content_description()

        # Enhanced prompt with data content
        prompt = f"""Generate a SQL query for this question. Return ONLY the SQL, nothing else.

Schema:
{self._schema_description[:2000]}

Available Data (IMPORTANT - check this before querying):
{data_content[:2000]}

IMPORTANT RULES:
- ALWAYS quote column names with double quotes: SELECT "col1", "col2" FROM tablename
- SQL reserved words MUST be quoted: "date", "time", "open", "close", "high", "low", "name", "type", "index"
- Use ticker symbols for filtering, NOT company names
- Check "Available values" above to verify the symbol exists BEFORE querying
- Only use columns that exist in the schema
- If searching text, search multiple text columns
- DATE FILTERING: Do NOT use LIKE on date columns. Instead use:
  * For year: EXTRACT(YEAR FROM "date") = 2023
  * For month: EXTRACT(MONTH FROM "date") = 12
  * For date range: "date" >= '2023-01-01' AND "date" <= '2023-12-31'
  * For specific date: "date" = '2023-06-15'
- ALWAYS close string literals with matching quotes: WHERE "sym" = 'AAPL' (not 'AAPL)

Question: {user_query}

SQL:"""

        try:
            # Generate SQL
            response = await llm.ainvoke(prompt)
            sql_query = response.content.strip()

            # Strip think tags if present
            import re
            sql_query = re.sub(r'<think>[\s\S]*?</think>', '', sql_query, flags=re.IGNORECASE)
            sql_query = re.sub(r'<think>[\s\S]*$', '', sql_query, flags=re.IGNORECASE)

            # Clean up the SQL (remove markdown, quotes, etc.)
            sql_query = sql_query.replace('```sql', '').replace('```', '').strip()
            sql_query = sql_query.strip('"\'')

            # Fix JSON-escaped quotes (LLM might return escaped strings)
            # Handle double-escaped: \\\" -> "
            sql_query = sql_query.replace('\\"', '"')
            # Handle backslash-escaped single quotes too
            sql_query = sql_query.replace("\\'", "'")

            # Validate it looks like SQL
            if not sql_query.upper().startswith('SELECT'):
                logger.warning(f"LLM response doesn't look like SQL: {sql_query[:100]}")
                # Try to extract SQL from response
                import re
                match = re.search(r'SELECT\s+.+', sql_query, re.IGNORECASE | re.DOTALL)
                if match:
                    sql_query = match.group(0).strip()
                else:
                    return f"Could not generate SQL for: {user_query}", None, []

            logger.info(f"Generated SQL: {sql_query}")

            # Execute the query
            result = await self.call_tool("kdbx_run_sql_query", {"query": sql_query})

            if result.get("error") or result.get("isError"):
                error_msg = result.get("error", "Query execution failed")
                return f"Query failed: {error_msg}", sql_query, []

            # Extract data from result
            data = []
            content = result.get("content", [])
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text", "")
                    try:
                        parsed = json.loads(text)
                        if isinstance(parsed, dict):
                            if "data" in parsed:
                                data = parsed["data"]
                                if isinstance(data, str):
                                    data = json.loads(data)
                            elif "rows" in parsed:
                                data = parsed["rows"]
                            elif "status" in parsed and parsed.get("status") == "success":
                                data = parsed.get("data", [])
                    except json.JSONDecodeError:
                        pass

            # Generate simple answer
            if data:
                answer = await self._generate_simple_answer(user_query, sql_query, data, llm)
            else:
                answer = "Query executed but returned no data."

            return answer, sql_query, data

        except Exception as e:
            logger.error(f"Simple chat query failed: {e}")
            return f"Error: {str(e)}", None, []

    async def _generate_simple_answer(
        self,
        user_query: str,
        sql_query: str,
        data: list,
        llm: ChatOpenAI
    ) -> str:
        """Generate a simple natural language answer from query results."""
        # Limit data for prompt
        data_preview = data[:10] if len(data) > 10 else data
        data_str = json.dumps(data_preview, indent=2)

        prompt = f"""Based on this data, provide a brief answer to the user's question.

Question: {user_query}
SQL: {sql_query}
Data ({len(data)} rows):
{data_str}

Provide a concise, helpful answer (2-4 sentences). Include key numbers/values from the data."""

        try:
            response = await llm.ainvoke(prompt)
            return response.content.strip()
        except Exception as e:
            logger.error(f"Answer generation failed: {e}")
            return f"Found {len(data)} rows of data."


# Global client instance
_kdb_nat_client: Optional[KDBNATClient] = None


def get_kdb_nat_client() -> Optional[KDBNATClient]:
    """Get or create the global MCP-based KDB+ client."""
    global _kdb_nat_client

    if not _mcp_available:
        return None

    if _kdb_nat_client is None:
        _kdb_nat_client = KDBNATClient()

    return _kdb_nat_client


async def search_kdb_nat(
    query: str,
    writer: StreamWriter,
    tool: str = "intelligent",  # Default to intelligent mode
    llm: Optional[ChatOpenAI] = None
) -> tuple[str, str, int]:
    """
    Search KDB+ using the intelligent MCP client.

    This function uses an LLM to:
    1. Discover what tools are available on the MCP server
    2. Decide which tools to call based on the user's query
    3. Execute the tools and synthesize results

    No hardcoded schemas or tool names - everything is discovered dynamically.

    Args:
        query: Search query (natural language)
        writer: Stream writer for progress updates
        tool: Mode of operation (ignored - always uses intelligent mode)
        llm: Optional LLM for tool planning and synthesis

    Returns:
        Tuple of (answer_content, citations, record_count)
    """
    if not KDB_ENABLED:
        logger.debug("KDB+ integration is disabled")
        return "", "", 0

    client = get_kdb_nat_client()

    # Stream progress update
    writer({"searching": "kdb", "query": query, "client": "mcp-sdk-intelligent"})

    try:
        # Use the intelligent query method
        answer, tool_results = await client.intelligent_query(query, llm)

        if not answer or answer.startswith("Unable to answer"):
            logger.info(f"KDB+ could not answer query: {query[:50]}...")
            return "", "", 0

        # Format citations from tool results
        citations = _format_intelligent_citations(query, tool_results)

        # Count records from tool results
        record_count = _count_records_from_results(tool_results)

        logger.info(f"Intelligent KDB+ search successful for query: {query[:50]}...")
        return answer, citations, record_count

    except Exception as e:
        logger.error(f"Intelligent KDB+ search failed: {e}")
        return "", "", 0


def _count_records_from_results(tool_results: list[dict]) -> int:
    """Count total records from tool results."""
    total = 0
    for result in tool_results:
        content = result.get("content", [])
        if content and not result.get("error"):
            # Each content item might be a row or a result
            total += len(content)
    return total


def _format_intelligent_citations(query: str, tool_results: list[dict]) -> str:
    """Format tool results as citations."""
    if not tool_results:
        return ""

    citation_parts = [
        "---",
        "**Source**: KDB+ Database (Intelligent MCP Client)",
        f"**Query**: {query}",
        "**Tools Used**:"
    ]

    for result in tool_results:
        tool_name = result.get("tool", "unknown")
        purpose = result.get("purpose", "")
        arguments = result.get("arguments", {})

        citation_parts.append(f"- {tool_name}")
        if purpose:
            citation_parts.append(f"  Purpose: {purpose}")
        if arguments:
            citation_parts.append(f"  Arguments: {json.dumps(arguments)}")

        # Include relevant content
        content = result.get("content", [])
        if content and not result.get("error"):
            citation_parts.append("  Result preview:")
            for item in content[:2]:  # Limit to first 2 items
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text", "")[:200]
                    citation_parts.append(f"    {text}...")

    citation_parts.append("---")
    return "\n".join(citation_parts)


# Alias for backwards compatibility
async def search_kdb_nat_with_fallback(
    query: str,
    writer: StreamWriter,
    llm: Optional[ChatOpenAI] = None
) -> tuple[str, str, int]:
    """
    Search KDB+ using the intelligent MCP client.

    This is now just an alias for search_kdb_nat() which uses intelligent
    tool discovery and execution.

    Args:
        query: Search query (natural language)
        writer: Stream writer for progress updates
        llm: Optional LLM for tool planning and synthesis

    Returns:
        Tuple of (answer_content, citations, record_count)
    """
    return await search_kdb_nat(query, writer, "intelligent", llm)
