# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Firecrawl MCP web-search/scrape tools for the vendored web_search agent.

Self-contained port of the borrowed project's get_firecrawl_tools(). The MCP
client (langchain_mcp_adapters / firecrawl-mcp) is imported lazily INSIDE the
function so importing this module does not require those packages installed --
they are only needed at runtime when the web_search source actually runs.
"""

from __future__ import annotations

import asyncio
import os
import threading

_firecrawl_tools_cache: list | None = None
_firecrawl_tools_lock: threading.Lock | None = None


async def _initialize_firecrawl_client() -> list:
    """Initialize the Firecrawl MCP client and return its tools (async)."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    mcp_config = {
        "firecrawl-mcp": {
            "command": "npx",
            "args": ["-y", "firecrawl-mcp"],
            "transport": "stdio",
            "env": {
                "FIRECRAWL_API_KEY": os.getenv("FIRECRAWL_API_KEY")
            }
        }
    }

    client = MultiServerMCPClient(mcp_config)
    tools = await client.get_tools()
    return tools


def get_firecrawl_tools() -> list:
    """Get configured Firecrawl MCP tools for web scraping and search.

    Initializes the MCP client once and caches the tools. Returns async tools
    which work natively with LangGraph's ToolNode when using ainvoke.
    """
    global _firecrawl_tools_cache, _firecrawl_tools_lock

    if _firecrawl_tools_cache is not None:
        return _firecrawl_tools_cache

    if _firecrawl_tools_lock is None:
        _firecrawl_tools_lock = threading.Lock()

    with _firecrawl_tools_lock:
        # Double-check after acquiring lock
        if _firecrawl_tools_cache is not None:
            return _firecrawl_tools_cache

        try:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If loop is already running, create a new loop in a thread
                    import concurrent.futures

                    def run_in_new_loop():
                        new_loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(new_loop)
                        try:
                            return new_loop.run_until_complete(_initialize_firecrawl_client())
                        finally:
                            new_loop.close()

                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(run_in_new_loop)
                        async_tools = future.result()
                else:
                    async_tools = loop.run_until_complete(_initialize_firecrawl_client())
            except RuntimeError:
                # No event loop exists, create one with asyncio.run()
                async_tools = asyncio.run(_initialize_firecrawl_client())

            # Return async tools directly - they work with ToolNode.ainvoke()
            _firecrawl_tools_cache = async_tools
            return _firecrawl_tools_cache
        except Exception as e:
            print(f"[firecrawl_tools] Warning: Could not create Firecrawl MCP tools: {e}")
            import traceback
            traceback.print_exc()
            # Return empty list if Firecrawl tools can't be created
            _firecrawl_tools_cache = []
            return []
