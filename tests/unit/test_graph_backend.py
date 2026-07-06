"""Unit tests for src/knowledge_graph/backends/.

Covers the GraphBackend interface contract, the NetworkXGraphBackend
default implementation, the GraphBackendRegistry, and backward
compatibility of the KnowledgeGraph class.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import Config
from src.knowledge_graph import KnowledgeGraph
from src.knowledge_graph.backends import (
    GRAPH_BACKEND_REGISTRY,
    GraphBackend,
    GraphBackendRegistry,
    KnowledgeGraphConfig,
    NetworkXGraphBackend,
    NodeNotFoundError,
)
from src.schemas.datasheet import ExtractionMethod
from src.schemas.kg import KGEdge, KGNode, KGNodeType, KGRelation


def _make_node(node_id: str = "component_type:regulator", layer: int = 2) -> KGNode:
    return KGNode(
        id=node_id,
        node_type=KGNodeType.COMPONENT_TYPE,
        layer=layer,
        label=node_id.split(":")[-1],
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


class TestGraphBackendInterface:
    """GraphBackend is abstract and NetworkXGraphBackend satisfies it."""

    def test_cannot_instantiate_interface(self) -> None:
        with pytest.raises(TypeError):
            GraphBackend()  # type: ignore[abstract]

    def test_networkx_backend_is_graph_backend(self) -> None:
        assert isinstance(NetworkXGraphBackend(), GraphBackend)

    def test_knowledge_graph_is_graph_backend(self) -> None:
        """Backward compat: KnowledgeGraph implements the interface."""
        assert isinstance(KnowledgeGraph(), GraphBackend)
        assert isinstance(KnowledgeGraph(), NetworkXGraphBackend)


class TestNetworkXGraphBackend:
    """Behavior of the default backend through the interface methods."""

    def test_add_and_get_node(self) -> None:
        backend = NetworkXGraphBackend()
        node = _make_node()
        backend.add_node(node)
        assert backend.node_exists(node.id)
        fetched = backend.get_node(node.id)
        assert fetched is not None
        assert fetched.label == "regulator"

    def test_get_missing_node_returns_none(self) -> None:
        backend = NetworkXGraphBackend()
        assert backend.get_node("nope") is None

    def test_add_edge_requires_both_nodes(self) -> None:
        backend = NetworkXGraphBackend()
        backend.add_node(_make_node("a:x"))
        with pytest.raises(NodeNotFoundError):
            backend.add_edge(_make_edge("a:x", "b:missing"))

    def test_edge_filters(self) -> None:
        backend = NetworkXGraphBackend()
        backend.add_node(_make_node("a:x"))
        backend.add_node(_make_node("b:y"))
        backend.add_edge(_make_edge("a:x", "b:y"))
        assert len(backend.get_edges_from("a:x")) == 1
        assert backend.get_edges_from("a:x", min_confidence=0.99) == []
        assert len(backend.get_edges_to("b:y")) == 1
        neighbors = backend.get_neighbors("a:x")
        assert [n.id for n in neighbors] == ["b:y"]

    def test_find_by_type_and_layer(self) -> None:
        backend = NetworkXGraphBackend()
        backend.add_node(_make_node("a:x", layer=2))
        backend.add_node(_make_node("b:y", layer=3))
        assert len(backend.find_nodes_by_type(KGNodeType.COMPONENT_TYPE)) == 2
        assert len(backend.find_nodes_by_layer(3)) == 1

    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        backend = NetworkXGraphBackend()
        backend.add_node(_make_node("a:x"))
        backend.add_node(_make_node("b:y"))
        backend.add_edge(_make_edge("a:x", "b:y"))
        graph_file = tmp_path / "graph.graphml"
        backend.save(graph_file)

        loaded = NetworkXGraphBackend.load(graph_file)
        assert loaded.node_exists("a:x")
        assert len(loaded.get_edges_from("a:x")) == 1

    def test_load_into_missing_file_raises(self, tmp_path: Path) -> None:
        backend = NetworkXGraphBackend()
        with pytest.raises(FileNotFoundError):
            backend.load_into(tmp_path / "missing.graphml")

    def test_stats(self) -> None:
        backend = NetworkXGraphBackend()
        backend.add_node(_make_node("a:x", layer=2))
        stats = backend.stats()
        assert stats["node_count"] == 1
        assert stats["nodes_layer_2"] == 1
        assert stats["edge_count"] == 0


class TestKnowledgeGraphBackwardCompat:
    """KnowledgeGraph keeps its historical API surface."""

    def test_load_classmethod_returns_knowledge_graph(self, tmp_path: Path) -> None:
        kg = KnowledgeGraph()
        kg.add_node(_make_node())
        path = tmp_path / "kg.graphml"
        kg.save(path)
        loaded = KnowledgeGraph.load(path)
        assert isinstance(loaded, KnowledgeGraph)
        assert loaded.node_exists("component_type:regulator")

    def test_internal_graph_attribute_preserved(self) -> None:
        """validator.py iterates graph._graph directly — must keep working."""
        kg = KnowledgeGraph()
        kg.add_node(_make_node())
        assert len(kg._graph.nodes) == 1


class TestGraphBackendRegistry:
    """Registry follows BackendRegistry conventions."""

    def test_default_backend_is_networkx(self) -> None:
        config = Config()
        registry = GraphBackendRegistry(config)
        backend = registry.get_graph_backend()
        assert isinstance(backend, NetworkXGraphBackend)

    def test_backend_instance_is_cached(self) -> None:
        registry = GraphBackendRegistry(Config())
        assert registry.get_graph_backend() is registry.get_graph_backend()

    def test_unknown_backend_raises_value_error(self) -> None:
        config = Config()
        config.knowledge_graph = KnowledgeGraphConfig(backend="missing")
        with pytest.raises(ValueError, match="Unknown knowledge_graph.backend"):
            GraphBackendRegistry(config)

    def test_registry_contains_networkx_and_neo4j(self) -> None:
        assert set(GRAPH_BACKEND_REGISTRY.keys()) == {"networkx", "neo4j"}


class TestKnowledgeGraphConfig:
    """Config sub-model defaults and validation."""

    def test_default_is_networkx(self) -> None:
        assert KnowledgeGraphConfig().backend == "networkx"

    def test_config_has_knowledge_graph_field(self) -> None:
        config = Config()
        assert config.knowledge_graph.backend == "networkx"
        assert config.knowledge_graph.neo4j_uri == "bolt://localhost:7687"

    def test_neo4j_config_fields(self) -> None:
        kg_config = KnowledgeGraphConfig(
            backend="neo4j",
            neo4j_uri="bolt://neo4j:7687",
            neo4j_username="neo4j",
            neo4j_password="secret",
            neo4j_database="kg",
        )
        assert kg_config.neo4j_uri == "bolt://neo4j:7687"
        assert kg_config.neo4j_username == "neo4j"
        assert kg_config.neo4j_password == "secret"
        assert kg_config.neo4j_database == "kg"

    def test_extra_keys_forbidden(self) -> None:
        with pytest.raises(Exception):
            KnowledgeGraphConfig(backend="networkx", bogus=1)  # type: ignore[call-arg]
