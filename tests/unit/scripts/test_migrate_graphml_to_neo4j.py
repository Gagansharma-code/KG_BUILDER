"""Unit tests for the GraphML-to-Neo4j migration script."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.schemas.datasheet import ExtractionMethod
from src.schemas.kg import KGEdge, KGNode, KGNodeType, KGRelation

MODULE = "scripts.migrate_graphml_to_neo4j"


def _make_node(node_id: str) -> KGNode:
    return KGNode(
        id=node_id,
        node_type=KGNodeType.COMPONENT_TYPE,
        layer=2,
        label=node_id,
        properties={},
        source="test",
        confidence=0.9,
        extraction_method=ExtractionMethod.P1_VECTOR,
        created_at="2026-01-01T00:00:00Z",
    )


def _make_edge(source_id: str, target_id: str) -> KGEdge:
    return KGEdge(
        source_id=source_id,
        relation=KGRelation.REQUIRES,
        target_id=target_id,
        constraints={},
        source_document="test.pdf",
        confidence=0.85,
        layer=2,
    )


def test_migration_loads_graphml_writes_neo4j_and_verifies(
    tmp_path: Path,
) -> None:
    graph_path = tmp_path / "kg.graphml"
    config = MagicMock()
    config.graph_path = graph_path

    from src.knowledge_graph.backends.networkx_backend import NetworkXGraphBackend

    source = NetworkXGraphBackend()
    source.add_node(_make_node("a:x"))
    source.add_node(_make_node("b:y"))
    source.add_edge(_make_edge("a:x", "b:y"))

    target = MagicMock()
    target.stats.return_value = source.stats()
    target.get_node.side_effect = lambda node_id: _make_node(node_id)

    with (
        patch(f"{MODULE}.get_config", return_value=config),
        patch(f"{MODULE}.NetworkXGraphBackend.load", return_value=source),
        patch(f"{MODULE}.Neo4jGraphBackend", return_value=target),
    ):
        from scripts.migrate_graphml_to_neo4j import migrate

        result = migrate(config_path=tmp_path / "default.yaml", sample_size=2)

    assert result == source.stats()
    target.load_into.assert_called_once_with(graph_path)
    target.add_node.assert_not_called()
    target.add_edge.assert_not_called()
    target.get_node.assert_any_call("a:x")
    target.get_node.assert_any_call("b:y")


def test_migration_fails_when_stats_differ(tmp_path: Path) -> None:
    config = MagicMock()
    config.graph_path = tmp_path / "kg.graphml"
    source = MagicMock()
    source._graph.nodes = []
    source._graph.edges = []
    source.stats.return_value = {"node_count": 1, "edge_count": 0}
    target = MagicMock()
    target.stats.return_value = {"node_count": 0, "edge_count": 0}

    with (
        patch(f"{MODULE}.get_config", return_value=config),
        patch(f"{MODULE}.NetworkXGraphBackend.load", return_value=source),
        patch(f"{MODULE}.Neo4jGraphBackend", return_value=target),
    ):
        from scripts.migrate_graphml_to_neo4j import migrate

        with pytest.raises(RuntimeError, match="Stats mismatch"):
            migrate(config_path=None, sample_size=0)
