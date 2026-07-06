"""Mocked tests for the Neo4j knowledge graph backend.

These tests assert the Cypher text and parameters emitted by
Neo4jGraphBackend without requiring a live Neo4j server.
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from src.config import Config
from src.knowledge_graph.backends._interfaces import NodeNotFoundError
from src.schemas.datasheet import ExtractionMethod
from src.schemas.kg import KGEdge, KGNode, KGNodeType, KGRelation


def _make_node(
    node_id: str = "component_type:regulator",
    *,
    node_type: KGNodeType = KGNodeType.COMPONENT_TYPE,
    layer: int = 2,
    properties: dict[str, object] | None = None,
    design_id: str | None = None,
) -> KGNode:
    return KGNode(
        id=node_id,
        node_type=node_type,
        layer=layer,
        label=node_id.split(":")[-1],
        properties=properties or {},
        source="test",
        confidence=0.9,
        extraction_method=ExtractionMethod.P1_VECTOR,
        created_at="2026-01-01T00:00:00Z",
        design_id=design_id,
    )


def _make_edge(
    source_id: str = "a:x",
    target_id: str = "b:y",
    *,
    relation: KGRelation = KGRelation.REQUIRES,
) -> KGEdge:
    return KGEdge(
        source_id=source_id,
        relation=relation,
        target_id=target_id,
        constraints={"min": 1},
        source_document="test.pdf",
        confidence=0.85,
        layer=2,
    )


def _install_fake_neo4j(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    driver = MagicMock()
    session_cm = MagicMock()
    session = MagicMock()
    session_cm.__enter__.return_value = session
    driver.session.return_value = session_cm

    graph_database = MagicMock()
    graph_database.driver.return_value = driver
    module = ModuleType("neo4j")
    module.GraphDatabase = graph_database
    monkeypatch.setitem(sys.modules, "neo4j", module)
    return driver


def _backend(monkeypatch: pytest.MonkeyPatch):
    driver = _install_fake_neo4j(monkeypatch)
    from src.knowledge_graph.backends.neo4j_backend import Neo4jGraphBackend

    config = Config()
    config.knowledge_graph.neo4j_username = "neo4j"
    config.knowledge_graph.neo4j_password = "secret"
    backend = Neo4jGraphBackend(config)
    session = driver.session.return_value.__enter__.return_value
    session.run.reset_mock()
    return backend, driver, session


def test_neo4j_driver_is_imported_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "neo4j", raising=False)

    import src.knowledge_graph.backends.neo4j_backend  # noqa: F401

    assert "neo4j" not in sys.modules


def test_init_creates_driver_and_startup_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = _install_fake_neo4j(monkeypatch)
    from src.knowledge_graph.backends.neo4j_backend import Neo4jGraphBackend

    config = Config()
    config.knowledge_graph.neo4j_uri = "bolt://neo4j:7687"
    config.knowledge_graph.neo4j_username = "neo4j"
    config.knowledge_graph.neo4j_password = "secret"
    config.knowledge_graph.neo4j_database = "kg"

    Neo4jGraphBackend(config)

    sys.modules["neo4j"].GraphDatabase.driver.assert_called_once_with(  # type: ignore[attr-defined]
        "bolt://neo4j:7687",
        auth=("neo4j", "secret"),
    )
    driver.session.assert_called_with(database="kg")
    queries = [call.args[0] for call in driver.session.return_value.__enter__.return_value.run.call_args_list]
    assert any("CREATE CONSTRAINT kgnode_id IF NOT EXISTS" in query for query in queries)
    assert any("CREATE TEXT INDEX kgnode_label IF NOT EXISTS" in query for query in queries)


def test_init_prefers_auth_environment_over_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = _install_fake_neo4j(monkeypatch)
    monkeypatch.setenv("OPENFORGE_NEO4J_USER", "env-user")
    monkeypatch.setenv("OPENFORGE_NEO4J_PASSWORD", "env-secret")
    from src.knowledge_graph.backends.neo4j_backend import Neo4jGraphBackend

    config = Config()
    config.knowledge_graph.neo4j_username = "config-user"
    config.knowledge_graph.neo4j_password = "config-secret"

    Neo4jGraphBackend(config)

    sys.modules["neo4j"].GraphDatabase.driver.assert_called_once_with(  # type: ignore[attr-defined]
        "bolt://localhost:7687",
        auth=("env-user", "env-secret"),
    )


def test_add_node_uses_dual_labels_and_scalar_mappings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend, _, session = _backend(monkeypatch)
    node = _make_node(
        node_type=KGNodeType.DESIGN_CONSTRAINT,
        properties={"frequency_hz": 1000.0, "component_type": "capacitor"},
        design_id="design-1",
    )

    backend.add_node(node)

    query, params = session.run.call_args.args
    assert "MERGE (n:KGNode {id: $id})" in query
    assert "SET n = $props" in query
    assert "REMOVE n:PhysicsConcept" in query
    assert "SET n:DesignConstraint" in query
    assert params["id"] == node.id
    assert params["props"]["node_type"] == "design_constraint"
    assert params["props"]["properties_json"] == (
        '{"frequency_hz":1000.0,"component_type":"capacitor"}'
    )
    assert params["props"]["frequency_hz"] == 1000.0
    assert params["props"]["prop_component_type"] == "capacitor"
    assert params["props"]["design_id"] == "design-1"


def test_add_edge_checks_nodes_deletes_existing_and_creates_relationship(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend, _, session = _backend(monkeypatch)
    session.execute_write.side_effect = lambda callback, edge: callback(MagicMock(), edge)
    tx = MagicMock()
    tx.run.side_effect = [
        [{"found": 1}],
        [{"found": 1}],
        MagicMock(),
        MagicMock(),
    ]
    session.execute_write.side_effect = lambda callback, edge: callback(tx, edge)

    backend.add_edge(_make_edge())

    queries = [call.args[0] for call in tx.run.call_args_list]
    assert "MATCH (s:KGNode {id: $source_id}) RETURN count(s) AS found" in queries[0]
    assert "MATCH (s:KGNode {id: $target_id}) RETURN count(s) AS found" in queries[1]
    assert "MATCH (s:KGNode {id: $source_id})-[r]->(t:KGNode {id: $target_id})" in queries[2]
    assert "DELETE r" in queries[2]
    assert "CREATE (s)-[r:REQUIRES $props]->(t)" in queries[3]
    assert tx.run.call_args_list[3].kwargs["props"]["constraints_json"] == '{"min":1}'


def test_add_edge_raises_node_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    backend, _, session = _backend(monkeypatch)
    tx = MagicMock()
    tx.run.return_value = [{"found": 0}]
    session.execute_write.side_effect = lambda callback, edge: callback(tx, edge)

    with pytest.raises(NodeNotFoundError, match="a:x"):
        backend.add_edge(_make_edge())


def test_get_node_returns_model_or_none(monkeypatch: pytest.MonkeyPatch) -> None:
    backend, _, session = _backend(monkeypatch)
    raw_node = {
        "id": "component_type:regulator",
        "node_type": "component_type",
        "layer": 2,
        "label": "regulator",
        "properties_json": "{}",
        "source": "test",
        "confidence": 0.9,
        "extraction_method": "p1_vector",
        "created_at": "2026-01-01T00:00:00Z",
        "design_id": None,
    }
    session.run.return_value = [{"n": raw_node}]

    node = backend.get_node("component_type:regulator")

    assert node == _make_node()
    query, params = session.run.call_args.args
    assert "MATCH (n:KGNode {id: $node_id}) RETURN n" in query
    assert params == {"node_id": "component_type:regulator"}

    session.run.return_value = []
    assert backend.get_node("missing") is None


def test_read_methods_emit_documented_cypher(monkeypatch: pytest.MonkeyPatch) -> None:
    backend, _, session = _backend(monkeypatch)
    raw_edge = {
        "relation": "requires",
        "constraints_json": "{}",
        "source_document": "test.pdf",
        "confidence": 0.85,
        "layer": 2,
    }
    session.run.return_value = [
        {
            "source_id": "a:x",
            "r": raw_edge,
            "target_id": "b:y",
        }
    ]

    assert backend.get_edges_from("a:x", KGRelation.REQUIRES, 0.5) == [
        KGEdge(
            source_id="a:x",
            relation=KGRelation.REQUIRES,
            target_id="b:y",
            constraints={},
            source_document="test.pdf",
            confidence=0.85,
            layer=2,
        )
    ]
    query, params = session.run.call_args.args
    assert "MATCH (s:KGNode {id: $node_id})-[r]->(t:KGNode)" in query
    assert "r.confidence >= $min_confidence" in query
    assert params["relation"] == "requires"

    backend.get_edges_to("b:y")
    assert "MATCH (s:KGNode)-[r]->(t:KGNode {id: $node_id})" in session.run.call_args.args[0]


def test_get_neighbors_find_and_exists_methods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend, _, session = _backend(monkeypatch)
    raw_node = {
        "id": "b:y",
        "node_type": "component_type",
        "layer": 2,
        "label": "y",
        "properties_json": "{}",
        "source": "test",
        "confidence": 0.9,
        "extraction_method": "p1_vector",
        "created_at": "2026-01-01T00:00:00Z",
        "design_id": None,
    }
    session.run.return_value = [{"t": raw_node}]

    neighbors = backend.get_neighbors("a:x", min_confidence=0.2)

    assert [node.id for node in neighbors] == ["b:y"]
    assert "RETURN t" in session.run.call_args.args[0]

    session.run.return_value = [{"exists": True}]
    assert backend.node_exists("b:y") is True
    assert "RETURN count(n) > 0 AS exists" in session.run.call_args.args[0]

    session.run.return_value = [{"n": raw_node}]
    assert [node.id for node in backend.find_nodes_by_type(KGNodeType.COMPONENT_TYPE)] == [
        "b:y"
    ]
    assert "WHERE n.node_type = $node_type" in session.run.call_args.args[0]

    assert [node.id for node in backend.find_nodes_by_layer(2)] == ["b:y"]
    assert "WHERE n.layer = $layer" in session.run.call_args.args[0]


def test_stats_assembles_total_and_layer_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend, _, session = _backend(monkeypatch)
    session.run.side_effect = [
        [{"layer": 2, "node_count": 3}],
        [{"layer": 2, "edge_count": 4}],
    ]

    stats = backend.stats()

    assert stats["node_count"] == 3
    assert stats["edge_count"] == 4
    assert stats["nodes_layer_2"] == 3
    assert stats["edges_layer_2"] == 4
    assert stats["nodes_layer_1"] == 0


def test_load_into_uses_batched_unwind(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    backend, _, session = _backend(monkeypatch)
    from src.knowledge_graph.backends.networkx_backend import NetworkXGraphBackend

    graphml = tmp_path / "graph.graphml"
    source = NetworkXGraphBackend()
    source.add_node(_make_node("a:x"))
    source.add_node(_make_node("b:y"))
    source.add_edge(_make_edge("a:x", "b:y", relation=KGRelation.CONNECTS_TO))
    source.save(graphml)
    session.run.reset_mock()

    backend.load_into(graphml)

    queries = [call.args[0] for call in session.run.call_args_list]
    assert any("UNWIND $nodes AS row" in query for query in queries)
    assert any("UNWIND $edges AS row" in query for query in queries)
    assert any("OPTIONAL MATCH (s)-[existing]->(t)" in query for query in queries)
    assert any("DELETE existing" in query for query in queries)
    assert any("CREATE (s)-[r:CONNECTS_TO]->(t)" in query for query in queries)
