"""Unit tests for src/knowledge_graph/constraints/ — persisted constraint nodes."""

from __future__ import annotations

from src.knowledge_graph import KnowledgeGraph
from src.knowledge_graph.constraints import (
    get_design_constraints,
    knowledge_version,
    persist_design_constraints,
)
from src.schemas.intent import (
    CurrentSpec,
    DesignMethodology,
    ElectricalConstraints,
    ImprovedIntentDict,
    ThermalConstraints,
    VoltageSpec,
)
from src.schemas.kg import KGNodeType


def _intent(**overrides) -> ImprovedIntentDict:
    defaults = dict(
        goal="ldo_regulator",
        application="iot",
        design_methodology=DesignMethodology.POWER_MANAGEMENT,
        board_type="double_sided_SMD",
        raw_prompt="test prompt",
        inferred_constraints=["low_power"],
        electrical=ElectricalConstraints(
            supply_voltage=VoltageSpec(min_v=4.5, typ_v=5.0, max_v=5.5, raw_text="5V"),
            output_current=CurrentSpec(max_ma=300, raw_text="300mA"),
        ),
        thermal=ThermalConstraints(operating_temp_max_c=85.0),
    )
    defaults.update(overrides)
    return ImprovedIntentDict(**defaults)


class TestKnowledgeVersion:
    def test_reflects_graph_state(self) -> None:
        graph = KnowledgeGraph()
        assert knowledge_version(graph) == "kg-v0.0"


class TestPersistDesignConstraints:
    def test_persists_scoped_nodes(self) -> None:
        graph = KnowledgeGraph()
        nodes = persist_design_constraints(_intent(), "design-abc", graph)
        assert len(nodes) == 3  # electrical, thermal, declared
        for node in nodes:
            assert node.node_type == KGNodeType.DESIGN_CONSTRAINT
            assert node.design_id == "design-abc"
            assert node.layer == 5
            assert "knowledge_version" in node.properties
            # persisted in the graph, not just returned
            assert graph.node_exists(node.id)

    def test_versioned_against_kg_state_at_creation(self) -> None:
        graph = KnowledgeGraph()
        nodes = persist_design_constraints(_intent(), "design-abc", graph)
        assert nodes[0].properties["knowledge_version"] == "kg-v0.0"

    def test_query_by_design_id(self) -> None:
        graph = KnowledgeGraph()
        persist_design_constraints(_intent(), "design-a", graph)
        persist_design_constraints(_intent(), "design-b", graph)
        found_a = get_design_constraints(graph, "design-a")
        found_b = get_design_constraints(graph, "design-b")
        assert len(found_a) == 3
        assert len(found_b) == 3
        assert all(n.design_id == "design-a" for n in found_a)

    def test_nothing_persisted_for_bare_intent(self) -> None:
        graph = KnowledgeGraph()
        bare = _intent(electrical=None, thermal=None, inferred_constraints=[])
        nodes = persist_design_constraints(bare, "design-x", graph)
        assert nodes == []

    def test_survives_after_run_no_cleanup(self) -> None:
        """Constraint nodes are the audit trail — nothing removes them."""
        graph = KnowledgeGraph()
        persist_design_constraints(_intent(), "design-abc", graph)
        # simulate later KG growth
        persist_design_constraints(_intent(), "design-later", graph)
        assert len(get_design_constraints(graph, "design-abc")) == 3
