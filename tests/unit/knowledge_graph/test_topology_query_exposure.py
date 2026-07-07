"""Gate tests for BR-004-5 — goal_topology matching + typed DesignSubgraph exposure."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.knowledge_graph import KnowledgeGraph, query_graph
from src.knowledge_graph.query.goal_mapper import map_goal_to_nodes
from src.schemas.datasheet import ExtractionMethod
from src.schemas.intent import DesignMethodology, IntentDict
from src.schemas.kg import KGNode, KGNodeType

_BUCK_BLOCK_SLUGS = {
    "switching_loop",
    "feedback_divider",
    "compensation_network",
    "bootstrap_circuit",
    "output_filter",
}

_NON_MATCHING_GOAL = "compact switching supply for drone avionics"


@pytest.fixture
def mock_config() -> MagicMock:
    cfg = MagicMock()
    cfg.kg_traversal_max_depth = 4
    cfg.kg_min_edge_confidence = 0.60
    return cfg


@pytest.fixture
def topology_intent() -> IntentDict:
    return IntentDict(
        goal=_NON_MATCHING_GOAL,
        goal_topology="buck_converter",
        application="test",
        design_methodology=DesignMethodology.POWER_MANAGEMENT,
        board_type="2-layer FR4",
        raw_prompt=_NON_MATCHING_GOAL,
    )


def test_query_graph_matches_on_goal_topology(
    mock_config: MagicMock,
    topology_intent: IntentDict,
) -> None:
    """goal_topology alone must match when goal text does not."""
    graph = KnowledgeGraph()

    # Goal string must not accidentally match the buck topology label
    goal_nodes = map_goal_to_nodes(topology_intent.goal, graph)
    assert not any(n.id == "topology:buck_converter" for n in goal_nodes)

    subgraph = query_graph(topology_intent, graph, mock_config)

    assert "topology:buck_converter" in subgraph.path_confidences
    assert any(n.id == "topology:buck_converter" for n in subgraph.topologies)


@pytest.fixture
def component_type_fixture_graph() -> KnowledgeGraph:
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


def test_existing_goal_matching_unaffected(
    component_type_fixture_graph: KnowledgeGraph,
) -> None:
    """COMPONENT_TYPE goal mapping unchanged by goal_topology additions."""
    nodes = map_goal_to_nodes("patch_antenna", component_type_fixture_graph)
    assert len(nodes) >= 1
    assert any(n.id == "component_type:patch_antenna" for n in nodes)
    assert all(n.node_type != KGNodeType.TOPOLOGY for n in nodes)


def test_design_subgraph_exposes_topology_typed_field(
    mock_config: MagicMock,
    topology_intent: IntentDict,
) -> None:
    """Topology + functional blocks appear in typed fields, not only path_confidences."""
    graph = KnowledgeGraph()
    subgraph = query_graph(topology_intent, graph, mock_config)

    topology_ids = {n.id for n in subgraph.topologies}
    assert topology_ids == {"topology:buck_converter"}

    block_ids = {n.id for n in subgraph.functional_blocks}
    expected_block_ids = {
        f"functional_block:buck_converter:{slug}" for slug in _BUCK_BLOCK_SLUGS
    }
    assert block_ids == expected_block_ids

    for block_id in expected_block_ids:
        assert block_id in subgraph.path_confidences
