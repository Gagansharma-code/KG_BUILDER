"""Gate tests for BR-004-4 — topology install wiring + traversable goal mapping."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.knowledge_graph import KnowledgeGraph, query_graph
from src.knowledge_graph.query.goal_mapper import _START_NODE_TYPES, map_goal_to_nodes
from src.knowledge_graph.topology import TOPOLOGY_SLUGS, install_topologies
from src.schemas.datasheet import ExtractionMethod
from src.schemas.intent import DesignMethodology, IntentDict
from src.schemas.kg import KGEdge, KGNode, KGNodeType, KGRelation


_BUCK_BLOCK_SLUGS = {
    "switching_loop",
    "feedback_divider",
    "compensation_network",
    "bootstrap_circuit",
    "output_filter",
}


@pytest.fixture
def mock_config() -> MagicMock:
    cfg = MagicMock()
    cfg.kg_traversal_max_depth = 4
    cfg.kg_min_edge_confidence = 0.60
    return cfg


def test_install_topologies_runs_on_backend_startup() -> None:
    """Fresh KnowledgeGraph() must have topology nodes without manual install."""
    graph = KnowledgeGraph()
    for slug in TOPOLOGY_SLUGS:
        node = graph.get_node(f"topology:{slug}")
        assert node is not None
        assert node.node_type == KGNodeType.TOPOLOGY


def test_install_topologies_is_idempotent() -> None:
    """Repeated install on the same graph must not duplicate nodes or error."""
    graph = KnowledgeGraph()
    stats_after_startup = graph.stats()
    written = install_topologies(graph)
    assert written > 0
    assert graph.stats() == stats_after_startup


def test_topology_included_in_start_node_types() -> None:
    assert KGNodeType.TOPOLOGY in _START_NODE_TYPES


def test_query_graph_returns_topology_for_goal(mock_config: MagicMock) -> None:
    """query_graph() returns topology + functional blocks for buck_converter goal."""
    graph = KnowledgeGraph()
    intent = IntentDict(
        goal="buck_converter",
        application="test",
        design_methodology=DesignMethodology.POWER_MANAGEMENT,
        board_type="2-layer FR4",
        raw_prompt="buck_converter",
    )

    subgraph = query_graph(intent, graph, mock_config)

    assert "topology:buck_converter" in subgraph.path_confidences
    for slug in _BUCK_BLOCK_SLUGS:
        block_id = f"functional_block:buck_converter:{slug}"
        assert block_id in subgraph.path_confidences, (
            f"expected functional block {block_id!r} in path_confidences"
        )

    block_edges = graph.get_edges_to(
        "topology:buck_converter", relation=KGRelation.PART_OF
    )
    assert {e.source_id.split(":")[-1] for e in block_edges} == _BUCK_BLOCK_SLUGS


@pytest.fixture
def component_type_fixture_graph() -> KnowledgeGraph:
    """Minimal graph with only COMPONENT_TYPE nodes — no topologies."""
    graph = KnowledgeGraph()
    patch_antenna = KGNode(
        id="component_type:patch_antenna",
        node_type=KGNodeType.COMPONENT_TYPE,
        layer=1,
        label="patch_antenna",
        properties={},
        source="test",
        confidence=1.0,
        extraction_method=ExtractionMethod.MANUAL,
        created_at="2026-01-01T00:00:00Z",
    )
    graph.add_node(patch_antenna)
    return graph


def test_existing_component_type_recipe_queries_unaffected(
    component_type_fixture_graph: KnowledgeGraph,
) -> None:
    """COMPONENT_TYPE / DESIGN_RECIPE goal mapping unchanged by TOPOLOGY addition."""
    nodes = map_goal_to_nodes("patch_antenna", component_type_fixture_graph)
    assert len(nodes) >= 1
    assert any(n.id == "component_type:patch_antenna" for n in nodes)
    assert all(n.node_type != KGNodeType.TOPOLOGY for n in nodes)
