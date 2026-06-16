# SPDX-FileCopyrightText: Copyright (c) 2026 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Integration-test fixtures for KDB-X.

The ``kdbx_endpoint`` fixture resolves the KDB-X server in one of two ways:

1. **Environment variable** — if ``KDBX_HOST`` is set the fixture uses it
   directly (format: ``host:port`` or a full URL).
2. **Docker Compose** — if neither ``KDBX_HOST`` is set nor docker is
   reachable, the test is skipped with a clear message.

This ensures that the integration tests are skipped cleanly in plain CI
environments that have not provisioned a KDB-X instance.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Stub langchain_openai before any nvidia_rag import.  The installed
# langchain_openai is incompatible with the installed langchain_core and
# raises ImportError(ModelProfileRegistry) — which nvidia_rag.__init__ only
# tolerates when it's ModuleNotFoundError.  Our adapter tests don't touch
# the LLM, so a stub is safe here.
if "langchain_openai" not in sys.modules:
    _fake_loai = types.ModuleType("langchain_openai")
    _fake_loai.ChatOpenAI = MagicMock()
    _fake_loai.AzureChatOpenAI = MagicMock()
    sys.modules["langchain_openai"] = _fake_loai
    sys.modules["langchain_openai.chat_models"] = _fake_loai

# Stub nvidia_rag.utils.minio_operator so the ingestor's module-level
# ``get_minio_operator_instance()._make_bucket(...)`` call doesn't try to
# reach a real MinIO at localhost:9010 during the kdbx round-trip test.
# Mirrors tests/unit/conftest.py.
if "nvidia_rag.utils.minio_operator" not in sys.modules:
    _fake_minio = types.ModuleType("nvidia_rag.utils.minio_operator")
    _fake_minio.get_minio_operator = lambda *a, **kw: MagicMock()
    _fake_minio.get_unique_thumbnail_id_collection_prefix = lambda *a, **kw: MagicMock()
    _fake_minio.get_unique_thumbnail_id_file_name_prefix = lambda *a, **kw: MagicMock()
    _fake_minio.get_unique_thumbnail_id = lambda *a, **kw: MagicMock()
    _fake_minio.MinioOperator = MagicMock()
    sys.modules["nvidia_rag.utils.minio_operator"] = _fake_minio

_COMPOSE_FILE = Path(__file__).parent / "docker-compose-kdbx.yml"
# Host port the compose stack publishes KDB-X on (override to dodge local
# port conflicts -- ship-readiness TODO 5.2).
_TEST_PORT = os.environ.get("KDBX_TEST_PORT", "5001").strip() or "5001"
# Where the compose-published KDB-X port is reachable. Defaults to localhost for
# local dev, but in CI where Docker runs on a separate host (e.g. a dind service)
# the port is published on the docker-host, not the job's localhost — override
# with KDBX_COMPOSE_ENDPOINT (e.g. "docker:5001").
_DEFAULT_ENDPOINT = os.environ.get("KDBX_COMPOSE_ENDPOINT", f"localhost:{_TEST_PORT}")
# CI sets KDBX_REQUIRED=1 so an environment problem (docker missing, compose
# failed, server unreachable) turns the job RED instead of silently
# green-skipping every test (ship-readiness TODO 5.1).
_REQUIRED = os.environ.get("KDBX_REQUIRED", "").strip() == "1"

# Set by kdbx_endpoint when the compose path provisioned the server -- the
# restart fixture below only works against a compose-managed container.
_compose_cmd: list[str] | None = None


def _bail(msg: str) -> None:
    """Skip locally; hard-FAIL when KDBX_REQUIRED=1 (CI)."""
    if _REQUIRED:
        pytest.fail(f"KDBX_REQUIRED=1 but the KDB-X test server is unavailable: {msg}", pytrace=False)
    pytest.skip(msg)


def _compose_env() -> dict[str, str]:
    return {**os.environ, "KDBX_TEST_PORT": _TEST_PORT}


def _docker_available() -> bool:
    """Return True if the ``docker`` CLI is reachable and the daemon is up."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _wait_for_kdbx(host: str, port: int, timeout: int = 60) -> bool:
    """Poll until KDB-X accepts a TCP connection or *timeout* seconds elapse."""
    import socket

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except OSError:
            time.sleep(2)
    return False


def _wait_for_healthy(compose_cmd: list[str], timeout: int = 120) -> bool:
    """Wait for the compose `kdbx` service's HEALTHCHECK to report healthy.

    TCP-accept is NOT enough: q binds the port at startup but only answers IPC
    after kdbx-init.q finishes loading, and a slow start would fail the first
    test with KdbxNotBootstrappedError (TODO 5.3). The compose healthcheck runs
    healthcheck.q in-container, so "healthy" == .rag.* genuinely serving.
    """
    cid = subprocess.run(
        compose_cmd + ["ps", "-q", "kdbx"],
        capture_output=True, text=True, timeout=30, env=_compose_env(),
    ).stdout.strip()
    if not cid:
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", cid],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        if status == "healthy":
            return True
        time.sleep(2)
    return False


@pytest.fixture(scope="session")
def kdbx_endpoint():
    """Yield a ``host:port`` string pointing at a live KDB-X server.

    Locally: skip gracefully when no server can be provisioned.
    CI (KDBX_REQUIRED=1): fail instead, so the job can't green-skip.
    """
    global _compose_cmd
    env_host = os.environ.get("KDBX_HOST", "").strip()

    if env_host:
        # Trust the caller — just yield what they provided.
        yield env_host
        return

    # Try to spin up via docker compose.
    if not _docker_available():
        _bail(
            "KDB-X integration tests require either KDBX_HOST env var or a "
            "running Docker daemon. Neither was found."
        )

    compose_cmd = ["docker", "compose", "-f", str(_COMPOSE_FILE)]

    try:
        subprocess.run(
            compose_cmd + ["up", "-d", "--quiet-pull"],
            check=True,
            capture_output=True,
            timeout=120,
            env=_compose_env(),
        )
    except subprocess.CalledProcessError as exc:
        _bail(
            f"docker compose up failed (returncode={exc.returncode}).\n"
            f"stderr: {exc.stderr.decode(errors='replace')}"
        )

    # Wait for the in-container healthcheck (init fully loaded), then confirm
    # the published port is reachable from here.
    host, port_str = _DEFAULT_ENDPOINT.split(":")
    port = int(port_str)
    healthy = _wait_for_healthy(compose_cmd, timeout=120)
    if not healthy or not _wait_for_kdbx(host, port, timeout=60):
        subprocess.run(compose_cmd + ["down", "-v"], capture_output=True, timeout=30, env=_compose_env())
        _bail("KDB-X container did not become healthy/reachable in time.")

    _compose_cmd = compose_cmd
    yield _DEFAULT_ENDPOINT

    # Teardown: bring down the stack after the session.
    _compose_cmd = None
    subprocess.run(
        compose_cmd + ["down", "-v"],
        capture_output=True,
        timeout=60,
        env=_compose_env(),
    )


@pytest.fixture
def kdbx_restart(kdbx_endpoint):
    """Return a callable that restarts the compose-managed KDB-X container and
    waits for it to come back healthy — for restart/rehydrate round-trip tests.

    Skips (never fails, even under KDBX_REQUIRED) when the server is external
    (KDBX_HOST): we can't restart a customer-managed endpoint.
    """
    if _compose_cmd is None:
        pytest.skip("restart test requires the compose-managed kdbx container")

    def _restart() -> None:
        subprocess.run(
            _compose_cmd + ["restart", "kdbx"],
            check=True, capture_output=True, timeout=180, env=_compose_env(),
        )
        host, port_str = _DEFAULT_ENDPOINT.split(":")
        assert _wait_for_healthy(_compose_cmd, timeout=120), "kdbx not healthy after restart"
        assert _wait_for_kdbx(host, int(port_str), timeout=60), "kdbx port unreachable after restart"

    return _restart
