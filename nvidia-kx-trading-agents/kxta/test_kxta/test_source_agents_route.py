# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from kxta.fastapi_extensions.routes.source_agents import add_source_agents_routes


def test_source_agents_endpoint_lists_sources():
    app = FastAPI()
    asyncio.run(add_source_agents_routes(app))
    client = TestClient(app)
    resp = client.get("/source_agents")
    assert resp.status_code == 200
    data = resp.json()
    names = {d["name"] for d in data}
    assert {"rag", "kdb", "web_search", "sec_filings", "macro_economic"} <= names
    for d in data:
        assert d["state"] in {"available", "needs_key", "unavailable"}
