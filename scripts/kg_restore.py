"""Manual, on-demand Knowledge Graph restore from a scripts/kg_snapshot.py snapshot.

Usage:
    python -m scripts.kg_restore --snapshot <name> --confirm

<name> is the shared "{timestamp}_{knowledge_version}_{label}" base name
printed by kg_snapshot.py and recorded in kg_snapshots/SNAPSHOT_LOG.md (not
a full file path, and without the .dump/.graphml extension).

Restore is destructive -- it overwrites the live graph -- so it refuses to
do anything without --confirm. Without --confirm it only reports what it
would do.

Restore mechanism used depends on what's available and the active backend:
- A .dump file + active backend is neo4j: native `neo4j-admin database
  load` (briefly stops/restarts the container -- see scripts/_kg_docker.py).
- Only a .graphml file: reported as such, never silently substituted for a
  Neo4j-native restore. Rebuilt via GraphBackend.load_into() -- for neo4j
  this is the same re-migration scripts/migrate_graphml_to_neo4j.py already
  performs, generalized to any GraphML snapshot; for networkx it's a direct
  overwrite of config.graph_path (the GraphML file *is* that backend's
  live database).

Does not build any new parsing/scraping/KG logic; only orchestrates the
existing GraphBackend.load_into() and neo4j-admin.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from scripts._kg_docker import (
    NEO4J_CONTAINER,
    NEO4J_DATABASE,
    docker_image_for,
    start_container,
    stop_container,
    wait_healthy,
)
from scripts.kg_snapshot import SNAPSHOTS_DIR
from src.config import Config, get_config
from src.knowledge_graph.backends import GraphBackendRegistry


def load_neo4j_native(dump_path: Path) -> None:
    """Restore Neo4j from a native dump, stopping/restarting the container."""
    image = docker_image_for(NEO4J_CONTAINER)
    stop_container(NEO4J_CONTAINER)
    try:
        with open(dump_path, "rb") as fh:
            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-i",
                    "--volumes-from",
                    NEO4J_CONTAINER,
                    image,
                    "neo4j-admin",
                    "database",
                    "load",
                    NEO4J_DATABASE,
                    "--from-stdin",
                    "--overwrite-destination=true",
                ],
                stdin=fh,
                capture_output=True,
                timeout=600,
            )
        if result.returncode != 0:
            raise RuntimeError(
                f"neo4j-admin database load failed: {result.stderr.decode(errors='replace')}"
            )
    finally:
        start_container(NEO4J_CONTAINER)
        wait_healthy(NEO4J_CONTAINER)


def restore(
    snapshot_name: str,
    config: Config,
    confirm: bool,
    snapshots_dir: Path = SNAPSHOTS_DIR,
) -> dict:
    """Restore the graph from a named snapshot.

    Returns a report dict describing what happened (or would happen,
    without --confirm) instead of raising, so the CLI can print a clear
    message either way.
    """
    dump_path = snapshots_dir / f"{snapshot_name}.dump"
    graphml_path = snapshots_dir / f"{snapshot_name}.graphml"
    has_dump = dump_path.exists()
    has_graphml = graphml_path.exists()
    backend = config.knowledge_graph.backend

    if not has_dump and not has_graphml:
        return {
            "status": "not_found",
            "message": f"No snapshot files found for '{snapshot_name}' in {snapshots_dir}",
        }

    if backend == "neo4j" and has_dump:
        method = "neo4j_native_load"
        method_description = f"neo4j-admin database load from {dump_path.name}"
    elif has_graphml:
        method = "graphml_rebuild" if backend == "neo4j" else "graphml_copy"
        method_description = (
            f"No .dump file for this snapshot (only .graphml) -- "
            f"{'re-migrating into Neo4j via load_into()' if backend == 'neo4j' else 'copying GraphML'} "
            f"from {graphml_path.name}"
        )
    else:
        return {
            "status": "no_compatible_snapshot_for_backend",
            "message": (
                f"Only a .dump file exists for '{snapshot_name}', but the active backend "
                f"is '{backend}', which cannot use a Neo4j-native dump."
            ),
        }

    if not confirm:
        return {
            "status": "refused_no_confirm",
            "method": method,
            "message": (
                f"Restore refused: this overwrites the live graph. {method_description}. "
                "Re-run with --confirm to proceed."
            ),
        }

    if method == "neo4j_native_load":
        load_neo4j_native(dump_path)
    elif method == "graphml_rebuild":
        graph = GraphBackendRegistry(config).get_graph_backend()
        graph.load_into(graphml_path)
    elif method == "graphml_copy":
        config.graph_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(graphml_path, config.graph_path)

    return {
        "status": "restored",
        "method": method,
        "message": f"Restored '{snapshot_name}' via {method_description}",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore the KG from a manual snapshot")
    parser.add_argument("--snapshot", required=True, help="Snapshot base name (no extension)")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required to actually perform the restore; without it, only reports what would happen",
    )
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args()

    config = get_config(args.config)
    result = restore(args.snapshot, config, args.confirm)

    print(result["message"])
    if result["status"] == "refused_no_confirm":
        raise SystemExit(1)
    if result["status"] in ("not_found", "no_compatible_snapshot_for_backend"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
