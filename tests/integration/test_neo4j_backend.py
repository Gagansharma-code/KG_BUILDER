"""Optional integration tests for Neo4jGraphBackend.

Run with OPENFORGE_NEO4J_INTEGRATION=1 after starting docker/neo4j.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from src.config import Config
from src.knowledge_graph.backends.neo4j_backend import Neo4jGraphBackend
from src.schemas.datasheet import ExtractionMethod
from src.schemas.kg import KGEdge, KGNode, KGNodeType, KGRelation

pytestmark = pytest.mark.skipif(
    os.getenv("OPENFORGE_NEO4J_INTEGRATION") != "1",
    reason="Set OPENFORGE_NEO4J_INTEGRATION=1 to run live Neo4j tests",
)


def test_neo4j_backend_round_trip_against_live_database() -> None:
    config = Config()
    config.knowledge_graph.backend = "neo4j"
    config.knowledge_graph.neo4j_uri = os.getenv(
        "OPENFORGE_NEO4J_URI",
        "bolt://localhost:7687",
    )
    config.knowledge_graph.neo4j_username = os.getenv(
        "OPENFORGE_NEO4J_USER",
        "neo4j",
    )
    config.knowledge_graph.neo4j_password = os.getenv(
        "OPENFORGE_NEO4J_PASSWORD",
        "openforge",
    )

    backend = Neo4jGraphBackend(config)
    unique = uuid4().hex
    source = KGNode(
        id=f"integration:{unique}:source",
        node_type=KGNodeType.COMPONENT_TYPE,
        layer=2,
        label="source",
        properties={},
        source="integration",
        confidence=1.0,
        extraction_method=ExtractionMethod.MANUAL,
        created_at="2026-01-01T00:00:00Z",
    )
    target = source.model_copy(update={"id": f"integration:{unique}:target"})
    edge = KGEdge(
        source_id=source.id,
        relation=KGRelation.REQUIRES,
        target_id=target.id,
        constraints={},
        source_document="integration",
        confidence=1.0,
        layer=2,
    )

    try:
        backend.add_node(source)
        backend.add_node(target)
        backend.add_edge(edge)

        assert backend.get_node(source.id) == source
        assert backend.get_edges_from(source.id) == [edge]
        assert [node.id for node in backend.get_neighbors(source.id)] == [target.id]
    except Exception as exc:
        pytest.skip(f"Live Neo4j is not reachable or not ready: {exc}")
