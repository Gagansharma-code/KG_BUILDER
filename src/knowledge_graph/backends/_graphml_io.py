"""Shared GraphML serialization for knowledge graph backends."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from src.schemas.kg import KGEdge, KGNode

logger = logging.getLogger(__name__)


def write_graphml(path: Path, nodes: Iterable[KGNode], edges: Iterable[KGEdge]) -> None:
    """Write KGNode/KGEdge models to the backend-neutral GraphML format."""
    import networkx as nx

    export_graph = nx.DiGraph()

    for node in nodes:
        export_graph.add_node(node.id, data=node.model_dump_json())

    for edge in edges:
        export_graph.add_edge(
            edge.source_id,
            edge.target_id,
            data=edge.model_dump_json(),
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(export_graph, str(path))


def read_graphml(path: Path) -> tuple[list[KGNode], list[KGEdge]]:
    """Read KGNode/KGEdge models from the backend-neutral GraphML format."""
    import networkx as nx

    if not path.exists():
        raise FileNotFoundError(f"Graph file not found: {path}")

    loaded_graph = nx.read_graphml(str(path))
    nodes: list[KGNode] = []
    edges: list[KGEdge] = []

    for node_id in loaded_graph.nodes:
        json_str = loaded_graph.nodes[node_id].get("data", "{}")
        try:
            nodes.append(KGNode.model_validate_json(json_str))
        except Exception as exc:
            logger.warning(f"Failed to parse node {node_id}: {exc}")

    for source_id, target_id, edge_data in loaded_graph.edges(data=True):
        json_str = edge_data.get("data", "{}")
        try:
            edges.append(KGEdge.model_validate_json(json_str))
        except Exception as exc:
            logger.warning(f"Failed to parse edge {source_id} -> {target_id}: {exc}")

    return nodes, edges
