# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""GET /source_agents — report each research source's availability for the UI."""

import logging

from fastapi import FastAPI

from kxta.source_agents.registry import get_registry

logger = logging.getLogger(__name__)


async def add_source_agents_routes(app: FastAPI):

    async def get_source_agents():
        return get_registry().describe_sources()

    app.add_api_route("/source_agents", get_source_agents, methods=["GET"])
