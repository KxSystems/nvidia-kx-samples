# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Dockerfile for KDB-X MCP Server
# Based on: https://github.com/KxSystems/kdb-x-mcp-server

FROM ghcr.io/astral-sh/uv:python3.12-bookworm AS builder

WORKDIR /app

# Clone the KDB-X MCP Server repository
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && \
    git clone --depth 1 https://github.com/KxSystems/kdb-x-mcp-server.git . && \
    rm -rf .git

# Install dependencies (without frozen to allow pykx upgrade)
RUN uv sync

# Upgrade PyKX to 4.0.0b4 (b3 has expired)
RUN uv pip install --upgrade "pykx==4.0.0b4"

######## Final Stage #########
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install uv package manager
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy uv from builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy the application from builder
COPY --from=builder /app /app

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create license directory (matches K8s mount path)
RUN mkdir -p /opt/kx/lic

# Default environment variables
ENV KDBX_MCP_TRANSPORT=streamable-http \
    KDBX_MCP_HOST=0.0.0.0 \
    KDBX_MCP_PORT=8000 \
    KDBX_MCP_LOG_LEVEL=INFO \
    KDBX_DB_HOST=localhost \
    KDBX_DB_PORT=5000 \
    KDBX_DB_TLS=false \
    KDBX_DB_TIMEOUT=1 \
    KDBX_DB_RETRY=2 \
    KDBX_DB_K=5 \
    KDBX_DB_METRIC=CS

# Expose the MCP server port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the MCP server via entrypoint (handles license setup)
ENTRYPOINT ["/entrypoint.sh"]
