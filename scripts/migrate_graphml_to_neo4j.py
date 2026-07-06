"""One-time GraphML-to-Neo4j migration for the knowledge graph."""

from __future__ import annotations

import argparse
import random
from pathlib import Path

from src.config import get_config
from src.knowledge_graph.backends.neo4j_backend import Neo4jGraphBackend
from src.knowledge_graph.backends.networkx_backend import NetworkXGraphBackend
from src.schemas.kg import KGNode


def migrate(
    config_path: Path | str | None = None,
    *,
    sample_size: int = 10,
    random_seed: int = 0,
) -> dict[str, int]:
    """Migrate config.graph_path from GraphML into the configured Neo4j backend.

    Existing GraphML files are never modified or deleted; they remain the
    rollback artifact if the deployment switches back to the NetworkX backend.
    """
    config = get_config(config_path)
    source = NetworkXGraphBackend.load(config.graph_path)
    target = Neo4jGraphBackend(config)

    nodes = _nodes(source)
    target.load_into(config.graph_path)

    source_stats = source.stats()
    target_stats = target.stats()
    if source_stats != target_stats:
        raise RuntimeError(
            f"Stats mismatch after migration: source={source_stats}, target={target_stats}"
        )

    _verify_round_trips(source, target, nodes, sample_size, random_seed)
    return target_stats


def _nodes(source: NetworkXGraphBackend) -> list[KGNode]:
    nodes: list[KGNode] = []
    for node_id in source._graph.nodes:
        node = source.get_node(node_id)
        if node is not None:
            nodes.append(node)
    return nodes


def _verify_round_trips(
    source: NetworkXGraphBackend,
    target: Neo4jGraphBackend,
    nodes: list[KGNode],
    sample_size: int,
    random_seed: int,
) -> None:
    if sample_size <= 0 or not nodes:
        return

    rng = random.Random(random_seed)
    sampled_nodes = rng.sample(nodes, k=min(sample_size, len(nodes)))
    for source_node in sampled_nodes:
        target_node = target.get_node(source_node.id)
        if target_node != source_node:
            raise RuntimeError(
                "Round-trip mismatch for "
                f"{source_node.id}: source={source_node}, target={target_node}"
            )
        if source.get_node(source_node.id) != source_node:
            raise RuntimeError(f"Source graph failed self-check for {source_node.id}")


def main() -> None:
    """Run the migration from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config YAML; defaults to configs/default.yaml",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=10,
        help="Number of random node round-trips to verify",
    )
    args = parser.parse_args()
    stats = migrate(config_path=args.config, sample_size=args.sample_size)
    print(f"Migration complete: {stats}")


if __name__ == "__main__":
    main()
