# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

FROM ghcr.io/astral-sh/uv:python3.12-bookworm AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

WORKDIR /build

# Copy the source code
COPY ./pyproject.toml /build/pyproject.toml
COPY ./kxta/ /build/kxta/

# Build the package. Mount .git to get the version from the git tag
RUN --mount=source=.git,target=.git,type=bind \
   uv build --directory /build


######## Final Stage #########
FROM nvcr.io/nvidia/base/ubuntu:jammy-20250619

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Install uv package manager
# The installer requires curl (and certificates) to download the release archive
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates tzdata gnupg

# Node.js 20 + the Firecrawl MCP server. The web_search ("Deep Web Research") agent runs
# Firecrawl via `npx -y firecrawl-mcp`, which requires Node. Pre-installing firecrawl-mcp
# globally means npx launches it instantly (no runtime download) and works air-gapped.
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g firecrawl-mcp \
    && npm cache clean --force \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Download the latest installer
ADD https://astral.sh/uv/install.sh /uv-installer.sh

# Run the installer then remove it
RUN sh /uv-installer.sh && rm /uv-installer.sh

# Ensure the installed binary is on the `PATH`
ENV PATH="/root/.local/bin/:$PATH"

WORKDIR /app

# Install python 3.12 as the default python version
RUN uv python install 3.12
RUN uv venv --python-preference managed --seed

# Copy the local build context (your project files) into the container's /app directory
COPY ./deploy/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

# Copy the built package into the container's /app directory.
# Also install the optional source-agent deps so SEC filings / FRED macro / firecrawl
# web research are present (they then surface as available or needs-key, never "not installed").
RUN --mount=from=builder,source=/build,target=/build,type=bind \
    --mount=type=cache,target=/root/.cache/uv \
   uv pip install /build/dist/kxta-*.whl \
       "edgartools>=2.0.0" "fredapi>=0.5.1" "langchain-mcp-adapters>=0.1.0" \
       "pykx>=3.0" "onetick-py" "onetick-query-webapi"

# PyKX runs UNLICENSED here: the backend is only an IPC client to KDB-X (data
# loader direct writes), which needs no license.
ENV PYKX_UNLICENSED=true

# Only copy the configs directory. The rest of the code is copied in the install
COPY ./configs/* /app/configs/

# Uncomment if we want to use the CMD instead of the entrypoint
# CMD ["uv", "run","aiq", "serve", "--config_file", "/app/configs/config.yml", "--host", "0.0.0.0", "--port", "3838"]

CMD ["/entrypoint.sh"]
