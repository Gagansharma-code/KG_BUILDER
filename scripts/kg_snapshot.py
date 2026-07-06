"""Manual, on-demand Knowledge Graph snapshot.

Usage:
    python -m scripts.kg_snapshot --label "before_pilot_ingest"

For the active backend (per config.knowledge_graph.backend), this:
1. Computes the knowledge_version(graph) tag (reused, not reinvented --
   see src/knowledge_graph/constraints/__init__.py, the same tag used for
   DESIGN_CONSTRAINT node versioning).
2. If the active backend is Neo4j: takes a native `neo4j-admin database
   dump` (see scripts/_kg_docker.py for why this briefly stops/restarts the
   container -- Community Edition cannot dump a mounted database).
3. Regardless of backend: calls graph.save() to also produce a backend
   -neutral, human-readable GraphML snapshot.
4. Appends one entry to kg_snapshots/SNAPSHOT_LOG.md.

This is manual and on-demand only -- no scheduling, no automatic triggers.
Does not build any new parsing/scraping/KG logic; only orchestrates the
existing knowledge_version(), GraphBackend.save(), and neo4j-admin.
"""

from __future__ import annotations

import argparse
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from scripts._kg_docker import (
    NEO4J_CONTAINER,
    NEO4J_DATABASE,
    docker_image_for,
    start_container,
    stop_container,
    wait_healthy,
)
from src.config import Config, get_config
from src.knowledge_graph.backends import GraphBackend, GraphBackendRegistry
from src.knowledge_graph.backends.networkx_backend import NetworkXGraphBackend
from src.knowledge_graph.constraints import knowledge_version

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS_DIR = PROJECT_ROOT / "kg_snapshots"
LOG_PATH_NAME = "SNAPSHOT_LOG.md"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _get_graph(config: Config) -> GraphBackend:
    """Return the live graph for the active backend.

    For networkx, mirrors the load-if-present convention used by
    scripts/pilot_ingest.py -- the GraphML file at config.graph_path *is*
    the live database for this backend. For neo4j, the registry's backend
    instance is already connected to the live, self-hosted database.
    """
    if config.knowledge_graph.backend == "networkx":
        if config.graph_path.exists():
            return NetworkXGraphBackend.load(config.graph_path)
        return NetworkXGraphBackend()
    return GraphBackendRegistry(config).get_graph_backend()


def dump_neo4j_native(dest_path: Path) -> None:
    """Take a native neo4j-admin dump, stopping/restarting the container.

    Raises on failure (caller decides whether that's fatal to the whole
    snapshot run -- it is not; the GraphML snapshot still proceeds).
    """
    image = docker_image_for(NEO4J_CONTAINER)
    stop_container(NEO4J_CONTAINER)
    try:
        with open(dest_path, "wb") as fh:
            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--volumes-from",
                    NEO4J_CONTAINER,
                    image,
                    "neo4j-admin",
                    "database",
                    "dump",
                    NEO4J_DATABASE,
                    "--to-stdout",
                ],
                stdout=fh,
                stderr=subprocess.PIPE,
                timeout=600,
            )
        if result.returncode != 0:
            dest_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"neo4j-admin database dump failed: {result.stderr.decode(errors='replace')}"
            )
    finally:
        start_container(NEO4J_CONTAINER)
        wait_healthy(NEO4J_CONTAINER)


def _append_log(
    log_path: Path,
    *,
    timestamp: str,
    label: str,
    version: str,
    stats: dict[str, int],
    graphml_name: str,
    dump_name: str | None,
    dump_error: str | None,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not log_path.exists()
    with open(log_path, "a", encoding="utf-8") as fh:
        if is_new:
            fh.write("# Knowledge Graph Snapshot Log\n\n")
            fh.write(
                "One entry per `python -m scripts.kg_snapshot` run. "
                "This file is tracked in git (small, text, valuable history); "
                "the `.dump`/`.graphml` files it references are gitignored "
                "(can be large binaries) -- see the .gitignore comment.\n\n"
            )
        fh.write(f"## {timestamp} — {label}\n\n")
        fh.write(f"- knowledge_version: {version}\n")
        fh.write(f"- nodes: {stats.get('node_count', 0)}, edges: {stats.get('edge_count', 0)}\n")
        fh.write(f"- graphml: {graphml_name}\n")
        if dump_name:
            fh.write(f"- dump: {dump_name}\n")
        elif dump_error:
            fh.write(f"- dump: unavailable ({dump_error})\n")
        else:
            fh.write("- dump: not applicable (active backend is not neo4j)\n")
        fh.write("\n")


def snapshot(label: str, config: Config, snapshots_dir: Path = SNAPSHOTS_DIR) -> dict:
    """Take one manual snapshot and append the SNAPSHOT_LOG.md entry.

    Never raises: a failed Neo4j dump is recorded as unavailable rather
    than aborting the (always-attempted) GraphML snapshot.
    """
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    graph = _get_graph(config)
    version = knowledge_version(graph)
    timestamp = _timestamp()
    base_name = f"{timestamp}_{version}_{label}"

    graphml_path = snapshots_dir / f"{base_name}.graphml"
    graph.save(graphml_path)
    # Captured before the (disruptive, backend==neo4j) native dump below,
    # which stops/restarts the container -- the driver connection this
    # `graph` instance holds does not survive that restart.
    stats = graph.stats()

    dump_path: Path | None = None
    dump_error: str | None = None
    if config.knowledge_graph.backend == "neo4j":
        candidate = snapshots_dir / f"{base_name}.dump"
        try:
            dump_neo4j_native(candidate)
            dump_path = candidate
        except Exception as exc:
            dump_error = str(exc)

    _append_log(
        snapshots_dir / LOG_PATH_NAME,
        timestamp=timestamp,
        label=label,
        version=version,
        stats=stats,
        graphml_name=graphml_path.name,
        dump_name=dump_path.name if dump_path else None,
        dump_error=dump_error,
    )

    return {
        "label": label,
        "knowledge_version": version,
        "timestamp": timestamp,
        "stats": stats,
        "graphml_path": str(graphml_path),
        "dump_path": str(dump_path) if dump_path else None,
        "dump_error": dump_error,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Take a manual KG snapshot")
    parser.add_argument("--label", required=True, help="Short human label, e.g. before_pilot_ingest")
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args()

    config = get_config(args.config)
    result = snapshot(args.label, config)

    print(f"Snapshot: {result['knowledge_version']} ({result['label']})")
    print(f"  stats: {result['stats']}")
    print(f"  graphml: {result['graphml_path']}")
    if result["dump_path"]:
        print(f"  dump:    {result['dump_path']}")
    elif result["dump_error"]:
        print(f"  dump:    unavailable ({result['dump_error']})")
    else:
        print("  dump:    not applicable (active backend is not neo4j)")
    print(f"Logged to {SNAPSHOTS_DIR / LOG_PATH_NAME}")


if __name__ == "__main__":
    main()
