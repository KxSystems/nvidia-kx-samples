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
KDB+ Chat Routes

This module provides a natural language chat interface for querying KDB+ data.
Users can ask questions about their financial data in plain English, and the
system will generate and execute SQL queries against KDB+.

The chat uses SSE (Server-Sent Events) for real-time streaming of:
- Thinking/planning phase
- Generated SQL query
- Query results and natural language response
"""

import asyncio
import json
import logging
import os
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# KDB MCP Internal flag - indicates if MCP server is deployed by this blueprint
# When True: Data loader is enabled (write operations allowed)
# When False: Data loader is disabled (read-only mode for external MCP)
KDB_MCP_INTERNAL = os.getenv("KDB_MCP_INTERNAL", "false").lower() == "true"

# Import KDB client
try:
    from aiq_aira.kdb_tools_nat import get_kdb_nat_client, KDB_ENABLED, KDBNATClient
except ImportError:
    KDB_ENABLED = False
    get_kdb_nat_client = None
    KDBNATClient = None
    logger.warning("KDB NAT client not available. KDB chat will be disabled.")


class KDBChatRequest(BaseModel):
    """Request model for KDB chat"""
    message: str = Field(..., min_length=1, max_length=2000, description="User's question about the data")
    session_id: Optional[str] = Field(None, description="Optional session ID for context continuity")


class KDBChatMessage(BaseModel):
    """A single chat message"""
    role: str  # 'user' or 'assistant'
    content: str
    sql_query: Optional[str] = None
    data: Optional[list] = None
    tool_results: Optional[list] = None


async def sse_event(event_type: str, data: dict) -> str:
    """Format an SSE event"""
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


async def generate_chat_stream(
    message: str,
    session_id: Optional[str] = None
) -> AsyncGenerator[str, None]:
    """
    Generate SSE stream for KDB chat response.

    Streams the following events:
    1. thinking: Shows planning phase
    2. query: Shows generated SQL query
    3. result: Shows query results and natural language answer
    4. error: Shows any errors

    Args:
        message: User's question
        session_id: Optional session ID for context
    """
    if not KDB_ENABLED or get_kdb_nat_client is None:
        yield await sse_event("error", {
            "message": "KDB+ integration is not enabled. Please configure KDB_ENABLED=true and ensure MCP server is running."
        })
        return

    try:
        client = get_kdb_nat_client()
        if client is None:
            yield await sse_event("error", {
                "message": "KDB client not available. Please check MCP server connection."
            })
            return

        # Phase 1: Thinking/Planning
        yield await sse_event("thinking", {
            "content": "Analyzing your question and planning query..."
        })

        # Initialize client (discovers schema and tools)
        try:
            await client.initialize()
        except Exception as e:
            logger.error(f"Failed to initialize KDB client: {e}")
            yield await sse_event("error", {
                "message": f"Failed to connect to KDB+ server: {str(e)}"
            })
            return

        yield await sse_event("thinking", {
            "content": "Connected to KDB+. Discovering available tables and schema..."
        })

        # Get schema info for display
        schema_info = await client.get_schema_description()
        if schema_info and "No schema" not in schema_info:
            yield await sse_event("thinking", {
                "content": f"Found database schema. Generating SQL query..."
            })

        # Phase 2: Execute simple chat query
        # This is optimized for interactive chat:
        # - Uses instruct model (no thinking tokens)
        # - Single SQL query generation
        # - Faster response times

        answer, sql_query, query_data = await client.simple_chat_query(message)

        # Phase 3: Send query event if we have SQL
        if sql_query:
            yield await sse_event("query", {
                "content": "Generated SQL query",
                "sql_query": sql_query
            })
            await asyncio.sleep(0.1)  # Small delay for visual feedback

        # Phase 4: Send result
        if answer and not answer.startswith("Unable to answer") and not answer.startswith("Error:"):
            yield await sse_event("result", {
                "content": answer,
                "sql_query": sql_query,
                "data": query_data,
                "tool_results": [
                    {
                        "tool": "kdbx_run_sql_query",
                        "purpose": "Execute SQL query",
                        "success": bool(query_data)
                    }
                ] if sql_query else []
            })
        else:
            yield await sse_event("result", {
                "content": answer or "I couldn't find an answer to your question. Please try rephrasing or ask about available data.",
                "sql_query": sql_query,
                "data": None
            })

    except Exception as e:
        logger.error(f"KDB chat error: {e}", exc_info=True)
        yield await sse_event("error", {
            "message": f"An error occurred: {str(e)}"
        })


async def check_kdb_connection() -> dict:
    """
    Check if KDB+ connection is available and return status.

    Returns dict with:
    - connected: bool
    - message: str
    - tables: list of table names (if connected)
    """
    if not KDB_ENABLED:
        return {
            "connected": False,
            "message": "KDB+ integration is disabled (KDB_ENABLED=false)",
            "data_loader_enabled": KDB_MCP_INTERNAL
        }

    if get_kdb_nat_client is None:
        return {
            "connected": False,
            "message": "KDB client not available",
            "data_loader_enabled": KDB_MCP_INTERNAL
        }

    try:
        client = get_kdb_nat_client()
        await client.initialize()

        # Get schema to verify connection
        schema = await client.get_schema_description()

        # Try to extract table names
        tables = []
        if schema and "No schema" not in schema:
            # Parse schema to find table names
            for line in schema.split("\n"):
                line = line.strip()
                if line.startswith("- ") or line.startswith("* "):
                    table_name = line[2:].split(":")[0].split(" ")[0].strip()
                    if table_name and not table_name.startswith("#"):
                        tables.append(table_name)

        return {
            "connected": True,
            "message": "Connected to KDB+ via MCP",
            "tables": tables if tables else ["Schema available - query for details"],
            "mcp_endpoint": os.getenv("KDB_MCP_ENDPOINT", "Not configured"),
            "data_loader_enabled": KDB_MCP_INTERNAL
        }

    except Exception as e:
        logger.error(f"KDB connection check failed: {e}")
        return {
            "connected": False,
            "message": f"Connection failed: {str(e)}",
            "data_loader_enabled": KDB_MCP_INTERNAL
        }


async def add_kdb_chat_routes(app: FastAPI):
    """Add KDB chat routes to the FastAPI app"""

    async def kdb_chat(request: KDBChatRequest):
        """
        Natural language chat with KDB+ database.

        Send a question about your financial data and receive:
        - The generated SQL query
        - Query results
        - Natural language explanation

        Uses SSE streaming for real-time updates.
        """
        return StreamingResponse(
            generate_chat_stream(request.message, request.session_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )

    async def kdb_status():
        """
        Check KDB+ connection status.

        Returns connection status, available tables, and MCP endpoint info.
        """
        return await check_kdb_connection()

    async def kdb_schema():
        """
        Get KDB+ database schema.

        Returns the discovered schema from the MCP server.
        """
        if not KDB_ENABLED or get_kdb_nat_client is None:
            raise HTTPException(
                status_code=503,
                detail="KDB+ integration is not enabled"
            )

        try:
            client = get_kdb_nat_client()
            await client.initialize()

            schema = await client.get_schema_description()
            tools = await client.get_tools_description()

            return {
                "schema": schema,
                "tools": tools,
                "sql_guidance": client._sql_guidance if hasattr(client, '_sql_guidance') else None
            }
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get schema: {str(e)}"
            )

    # Add routes
    app.add_api_route(
        "/kdb/chat",
        kdb_chat,
        methods=["POST"],
        tags=["kdb-chat"],
        summary="Natural language chat with KDB+ database"
    )

    app.add_api_route(
        "/kdb/status",
        kdb_status,
        methods=["GET"],
        tags=["kdb-chat"],
        summary="Check KDB+ connection status"
    )

    app.add_api_route(
        "/kdb/schema",
        kdb_schema,
        methods=["GET"],
        tags=["kdb-chat"],
        summary="Get KDB+ database schema"
    )

    logger.info("Added KDB chat routes")
