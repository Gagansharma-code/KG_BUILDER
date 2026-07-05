"""Unit tests for src/knowledge_graph/topology/ — formal topology layer."""

from __future__ import annotations

import pytest

from src.knowledge_graph import KnowledgeGraph
from src.knowledge_graph.backends import NodeNotFoundError
from src.knowledge_graph.topology import (
    SCALING_LAWS_KEY,
    TOPOLOGY_SLUGS,
    ScalingLaw,
    install_topologies,
    link_component_implements,
)
from src.schemas.datasheet import ExtractionMethod
from src.schemas.kg import KGNode, KGNodeType, KGRelation


class TestScalingLaw:
    def test_roundtrip_via_edge_constraints(self) -> None:
        law = ScalingLaw(
            parameter="switching_frequency_hz",
            affects="loop_area_mm2",
            direction="inverse",
            rationale="test",
        )
        constraints = {SCALING_LAWS_KEY: [law.to_constraint_entry()]}
        restored = ScalingLaw.list_from_edge_constraints(constraints)
        assert restored == [law]

    def test_malformed_entries_skipped(self) -> None:
        constraints = {SCALING_LAWS_KEY: [{"bogus": True}, "not a dict"]}
        assert ScalingLaw.list_from_edge_constraints(constraints) == []

    def test_missing_key_returns_empty(self) -> None:
        assert ScalingLaw.list_from_edge_constraints({}) == []

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(Exception):
            ScalingLaw(
                parameter="p", affects="a", direction="inverse",
                rationale="r", bogus=1,  # type: ignore[call-arg]
            )


class TestInstallTopologies:
    def test_installs_both_topologies(self) -> None:
        graph = KnowledgeGraph()
        written = install_topologies(graph)
        assert written > 0
        for slug in TOPOLOGY_SLUGS:
            node = graph.get_node(f"topology:{slug}")
            assert node is not None
            assert node.node_type == KGNodeType.TOPOLOGY
            assert node.layer == 4

    def test_ldo_blocks_present_with_part_of_edges(self) -> None:
        graph = KnowledgeGraph()
        install_topologies(graph)
        expected = {"input_cap", "pass_element", "output_cap", "feedback"}
        edges = graph.get_edges_to("topology:ldo", relation=KGRelation.PART_OF)
        block_slugs = {e.source_id.split(":")[-1] for e in edges}
        assert block_slugs == expected

    def test_buck_converter_blocks_present(self) -> None:
        graph = KnowledgeGraph()
        install_topologies(graph)
        expected = {
            "switching_loop", "feedback_divider", "compensation_network",
            "bootstrap_circuit", "output_filter",
        }
        edges = graph.get_edges_to(
            "topology:buck_converter", relation=KGRelation.PART_OF
        )
        assert {e.source_id.split(":")[-1] for e in edges} == expected

    def test_buck_switching_loop_carries_parameterized_scaling(self) -> None:
        """The critical requirement: not a flat block list."""
        graph = KnowledgeGraph()
        install_topologies(graph)
        edges = graph.get_edges_to(
            "topology:buck_converter", relation=KGRelation.PART_OF
        )
        loop_edge = next(
            e for e in edges
            if e.source_id == "functional_block:buck_converter:switching_loop"
        )
        laws = ScalingLaw.list_from_edge_constraints(loop_edge.constraints)
        assert len(laws) >= 2
        inverse_law = next(l for l in laws if l.affects == "loop_area_mm2")
        assert inverse_law.parameter == "switching_frequency_hz"
        assert inverse_law.direction == "inverse"

    def test_ldo_uses_same_schema_pattern(self) -> None:
        """LDO must not take a shortcut — its edges also carry scaling laws."""
        graph = KnowledgeGraph()
        install_topologies(graph)
        edges = graph.get_edges_to("topology:ldo", relation=KGRelation.PART_OF)
        laws_per_edge = [
            ScalingLaw.list_from_edge_constraints(e.constraints) for e in edges
        ]
        assert all(len(laws) >= 1 for laws in laws_per_edge)

    def test_idempotent(self) -> None:
        graph = KnowledgeGraph()
        install_topologies(graph)
        stats_first = graph.stats()
        install_topologies(graph)
        assert graph.stats() == stats_first

    def test_slugs_match_existing_vocabulary(self) -> None:
        """Node IDs resolve from existing goal_topology / template keys."""
        from src.schematic.structural_verifier import TOPOLOGY_TEMPLATES

        graph = KnowledgeGraph()
        install_topologies(graph)
        for slug in TOPOLOGY_SLUGS:
            assert slug in TOPOLOGY_TEMPLATES
            assert graph.node_exists(f"topology:{slug}")


class TestLinkComponentImplements:
    def _component_node(self) -> KGNode:
        return KGNode(
            id="component_instance:TPS5430",
            node_type=KGNodeType.COMPONENT_INSTANCE,
            layer=3,
            label="TPS5430",
            properties={},
            source="test",
            confidence=0.9,
            extraction_method=ExtractionMethod.MANUAL,
            created_at="2026-01-01T00:00:00Z",
        )

    def test_creates_implements_edge(self) -> None:
        graph = KnowledgeGraph()
        install_topologies(graph)
        graph.add_node(self._component_node())
        link_component_implements(
            graph, "component_instance:TPS5430", "buck_converter"
        )
        edges = graph.get_edges_from(
            "component_instance:TPS5430", relation=KGRelation.IMPLEMENTS
        )
        assert len(edges) == 1
        assert edges[0].target_id == "topology:buck_converter"

    def test_missing_component_raises(self) -> None:
        graph = KnowledgeGraph()
        install_topologies(graph)
        with pytest.raises(NodeNotFoundError):
            link_component_implements(graph, "component_instance:GHOST", "ldo")
