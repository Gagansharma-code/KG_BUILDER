"""Shared docker plumbing for kg_snapshot.py / kg_restore.py.

Neo4j Community Edition cannot dump or load a database that is mounted in a
running server, and has no `STOP DATABASE` administration command (that is
Enterprise-only). The only way to run `neo4j-admin database dump/load`
against the self-hosted container from docker/neo4j/docker-compose.yml is
to stop the whole container, run the admin command via a throwaway
container that shares its volumes, then restart it. Verified by hand
against the actual running container (image neo4j:5.26.27-community).

Not a new KG mechanism itself -- purely the subprocess/docker orchestration
shared by the dump and load code paths.
"""

from __future__ import annotations

import os
import subprocess
import time

NEO4J_CONTAINER = os.getenv("OPENFORGE_NEO4J_CONTAINER", "openforge-neo4j")
NEO4J_DATABASE = "neo4j"


def docker_image_for(container: str) -> str:
    """Return the image tag the given container is currently running."""
    result = subprocess.run(
        ["docker", "inspect", container, "--format", "{{.Config.Image}}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return result.stdout.strip()


def stop_container(container: str) -> None:
    subprocess.run(
        ["docker", "stop", container], capture_output=True, text=True, timeout=60, check=True
    )


def start_container(container: str) -> None:
    subprocess.run(
        ["docker", "start", container], capture_output=True, text=True, timeout=60, check=True
    )


def wait_healthy(container: str, timeout_s: int = 120) -> None:
    """Poll `docker inspect` until the container reports healthy.

    Raises RuntimeError on timeout so callers can surface a clear failure
    instead of silently leaving Neo4j down.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", container],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.stdout.strip() == "healthy":
            return
        time.sleep(2)
    raise RuntimeError(
        f"{container} did not report healthy within {timeout_s}s after restart"
    )
