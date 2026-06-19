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

import os
import pytest
import subprocess
import docker
import time

# These are heavyweight integration tests: they build/run the Docker images, which
# requires a Docker daemon and network/registry access to the NIM base images. They
# are skipped by default so the unit-test pass stays green offline. Opt in with:
#   RUN_DOCKER_TESTS=1 uv run pytest kxta/test_kxta/test_module_loads.py
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_DOCKER_TESTS"),
    reason="integration: requires Docker + buildable/pullable images; set RUN_DOCKER_TESTS=1 to enable",
)

@pytest.fixture(scope="session")
def docker_client():
    return docker.from_env()

def test_docker_compose_build():
    """Tests building the kxta-backend image using docker-compose."""
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", "../deploy/compose/docker-compose.yaml", "build", "kxta-backend", "--no-cache"],
            check=True,
            capture_output=True,
            text=True,
        )
        print(result.stdout) # helpful for debugging
    except subprocess.CalledProcessError as e:
        pytest.fail(f"Docker compose build failed: {e.stderr}")

def test_docker_run_import(docker_client):
    """Tests running the kxta-backend image and importing a module."""

    image_name = "compose-kxta-backend:latest"  
    try:
        container = docker_client.containers.run(
            image_name,
            ["uv", "run", "python", "-c", "from kxta.register import ai_researcher"],
            detach=False,
            remove=True, #cleanup
        )
        print(container) # helpful for debugging
    except docker.errors.ContainerError as e:
        pytest.fail(f"Docker run failed: {e.stderr}")
    except docker.errors.ImageNotFound:
        pytest.fail(f"Image {image_name} not found. Did the build step succeed?")

def test_docker_compose_up_server():
    """Tests starting the server and checking for the Uvicorn startup message."""
    try:
        process = subprocess.Popen(
            ["docker", "compose", "-f", "../deploy/compose/docker-compose.yaml", "up", "kxta-backend"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(5)
        start_time = time.time()
        
        timeout = 60  # Timeout in seconds

        client = docker.from_env()
        print(client.containers.list())
        container = client.containers.get("kxta-backend")
        
        while True:
            line = container.logs(stdout=True, stderr=True).decode("utf-8")
            print(line)
            if "Uvicorn running on http://0.0.0.0:3838" in line:
                break

            if time.time() - start_time > timeout:
                pytest.fail("Timeout waiting for Uvicorn startup message.")

            time.sleep(1)

        # Stop the container
        subprocess.run(["docker", "compose", "-f", "../deploy/compose/docker-compose.yaml", "down"], check=True)

    except subprocess.CalledProcessError as e:
        pytest.fail(f"Docker compose up/down failed: {e.stderr}")
    except FileNotFoundError:
        pytest.fail("docker-compose.yaml not found. Check the path.")
    except Exception as e:
        pytest.fail(f"An unexpected error occured: {e}")

