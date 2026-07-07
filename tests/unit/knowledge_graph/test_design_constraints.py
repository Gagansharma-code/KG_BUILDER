"""Unit tests for src/knowledge_graph/constraints/ — persisted constraint nodes."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from src.knowledge_graph import KnowledgeGraph
from src.knowledge_graph.backends.neo4j_backend import _node_props
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
        stats = graph.stats()
        assert knowledge_version(graph) == (
            f"kg-v{stats['node_count']}.{stats['edge_count']}"
        )


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
        baseline = knowledge_version(graph)
        nodes = persist_design_constraints(_intent(), "design-abc", graph)
        assert nodes[0].properties["knowledge_version"] == baseline

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


def _main_rail_intent() -> ImprovedIntentDict:
    return _intent(
        electrical=ElectricalConstraints(
            supply_voltage=VoltageSpec(min_v=4.2, typ_v=5.0, max_v=5.5, raw_text="5V"),
            output_current=CurrentSpec(max_ma=500, raw_text="500mA"),
        ),
        thermal=None,
        inferred_constraints=[],
    )


def _sensing_rail_intent() -> ImprovedIntentDict:
    return _intent(
        electrical=ElectricalConstraints(
            supply_current_budget=CurrentSpec(max_ma=0.25, raw_text="250uA"),
            output_voltage_compliance=VoltageSpec(
                min_v=0.0, typ_v=1.65, max_v=3.3, raw_text="1.65V"
            ),
        ),
        thermal=None,
        inferred_constraints=[],
    )


class TestScopedDesignConstraints:
    def test_two_scoped_constraints_same_kind_coexist(self) -> None:
        graph = KnowledgeGraph()
        design_id = "design-multi-rail"

        main_nodes = persist_design_constraints(
            _main_rail_intent(), design_id, graph, scope="main_rail"
        )
        sensing_nodes = persist_design_constraints(
            _sensing_rail_intent(), design_id, graph, scope="sensing_rail"
        )

        electrical = [
            n
            for n in main_nodes + sensing_nodes
            if n.properties.get("kind") == "electrical"
        ]
        assert len(electrical) == 2
        ids = {node.id for node in electrical}
        assert ids == {
            f"design_constraint:{design_id}:electrical:main_rail",
            f"design_constraint:{design_id}:electrical:sensing_rail",
        }
        for node_id in ids:
            assert graph.node_exists(node_id)

    def test_default_scope_reproduces_prior_behavior(self) -> None:
        graph = KnowledgeGraph()
        design_id = "design-default-scope"
        intent = _main_rail_intent()

        first = persist_design_constraints(intent, design_id, graph)
        second = persist_design_constraints(intent, design_id, graph)

        electrical_id = f"design_constraint:{design_id}:electrical:default"
        assert first[0].id == electrical_id
        assert second[0].id == electrical_id
        assert graph.node_exists(electrical_id)

        electrical = get_design_constraints(graph, design_id, kind="electrical")
        assert len(electrical) == 1

    def test_scalar_promotion_queryable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        graph = KnowledgeGraph()
        nodes = persist_design_constraints(
            _main_rail_intent(), "design-scalar", graph, scope="main_rail"
        )
        node = nodes[0]
        assert node.properties["supply_voltage_max_v"] == pytest.approx(5.5)
        assert node.properties["output_current_max_ma"] == pytest.approx(500)
        assert node.properties["spec"]["supply_voltage"]["max_v"] == pytest.approx(5.5)

        driver = MagicMock()
        session_cm = MagicMock()
        session = MagicMock()
        session_cm.__enter__.return_value = session
        driver.session.return_value = session_cm
        module = ModuleType("neo4j")
        module.GraphDatabase = MagicMock(driver=MagicMock(return_value=driver))
        monkeypatch.setitem(sys.modules, "neo4j", module)

        neo4j_props = _node_props(node)
        assert neo4j_props["supply_voltage_max_v"] == pytest.approx(5.5)
        assert neo4j_props["output_current_max_ma"] == pytest.approx(500)
        # Promoted scalars are direct Neo4j node properties (Cypher-queryable),
        # not only nested under properties_json → spec.
        assert "supply_voltage_max_v" in neo4j_props
        assert "output_current_max_ma" in neo4j_props

    def test_get_design_constraints_returns_all_scopes(self) -> None:
        graph = KnowledgeGraph()
        design_id = "design-all-scopes"
        persist_design_constraints(
            _main_rail_intent(), design_id, graph, scope="main_rail"
        )
        persist_design_constraints(
            _sensing_rail_intent(), design_id, graph, scope="sensing_rail"
        )

        electrical = get_design_constraints(graph, design_id, kind="electrical")
        assert len(electrical) == 2
        scopes = {node.properties["scope"] for node in electrical}
        assert scopes == {"main_rail", "sensing_rail"}
