"""Unit tests for src/knowledge_graph/metrics/ — predicted output metric nodes."""

from __future__ import annotations

import pytest

from src.knowledge_graph import KnowledgeGraph
from src.knowledge_graph.constraints import knowledge_version, persist_design_constraints
from src.knowledge_graph.metrics import get_predicted_metrics, persist_predicted_metric
from src.schemas.common import ConditionScope
from src.schemas.datasheet import ExtractionMethod
from src.schemas.intent import (
    CurrentSpec,
    DesignMethodology,
    ElectricalConstraints,
    ImprovedIntentDict,
    VoltageSpec,
)
from src.schemas.kg import KGEdge, KGNode, KGNodeType, KGRelation


def _design_id() -> str:
    return "design-metric-audit-001"


def _constraint_input(graph: KnowledgeGraph, design_id: str) -> KGNode:
    intent = ImprovedIntentDict(
        goal="ldo_regulator",
        application="iot",
        design_methodology=DesignMethodology.POWER_MANAGEMENT,
        board_type="double_sided_SMD",
        raw_prompt="test prompt",
        electrical=ElectricalConstraints(
            supply_current_budget=CurrentSpec(max_ma=0.25, raw_text="250uA"),
            supply_voltage=VoltageSpec(min_v=3.0, typ_v=3.7, max_v=4.2, raw_text="Li-ion"),
        ),
    )
    nodes = persist_design_constraints(intent, design_id, graph, scope="sensing_rail")
    electrical = next(n for n in nodes if n.properties.get("kind") == "electrical")
    return electrical


def _component_input(graph: KnowledgeGraph) -> KGNode:
    node = KGNode(
        id="component_instance:ada4522-1",
        node_type=KGNodeType.COMPONENT_INSTANCE,
        layer=3,
        label="ADA4522-1",
        properties={"part_number": "ADA4522-1"},
        source="test",
        confidence=1.0,
        extraction_method=ExtractionMethod.MANUAL,
        created_at="2026-07-07T00:00:00Z",
    )
    graph.add_node(node)
    return node


def _topology_input(graph: KnowledgeGraph) -> KGNode:
    node = KGNode(
        id="topology:instrumentation_amplifier",
        node_type=KGNodeType.TOPOLOGY,
        layer=4,
        label="Instrumentation Amplifier",
        properties={"goal": "instrumentation_amplifier"},
        source="test",
        confidence=1.0,
        extraction_method=ExtractionMethod.MANUAL,
        created_at="2026-07-07T00:00:00Z",
    )
    graph.add_node(node)
    return node


class TestPredictedMetricNode:
    def test_predicted_metric_node_created(self) -> None:
        graph = KnowledgeGraph()
        design_id = _design_id()
        condition = ConditionScope(
            parameter="frequency_hz",
            at=1000.0,
            raw_text="at 1 kHz",
        )

        node = persist_predicted_metric(
            graph,
            design_id=design_id,
            metric_kind="cmrr_db",
            value=118.5,
            unit="dB",
            method="noise_estimator:v0.1-mock",
            derived_from=[],
            condition=condition,
        )

        assert node is not None
        assert node.node_type == KGNodeType.PREDICTED_METRIC
        assert node.layer == 5
        assert node.design_id == design_id
        assert node.id == f"predicted_metric:{design_id}:cmrr_db:noise_estimator:v0.1-mock"
        assert node.properties["metric_kind"] == "cmrr_db"
        assert node.properties["value"] == pytest.approx(118.5)
        assert node.properties["unit"] == "dB"
        assert node.properties["method"] == "noise_estimator:v0.1-mock"
        restored = ConditionScope.model_validate(node.properties["condition"])
        assert restored == condition
        assert "knowledge_version" in node.properties
        assert graph.node_exists(node.id)


class TestDerivedFromEdges:
    def test_derived_from_edges_link_real_inputs(self) -> None:
        graph = KnowledgeGraph()
        design_id = _design_id()
        constraint = _constraint_input(graph, design_id)
        component = _component_input(graph)
        topology = _topology_input(graph)

        metric = persist_predicted_metric(
            graph,
            design_id=design_id,
            metric_kind="battery_life_h",
            value=312.0,
            unit="h",
            method="power_budget:v0.1-mock",
            derived_from=[
                (
                    constraint.id,
                    {"contribution": "supply_current_budget", "share": 0.41},
                ),
                (
                    component.id,
                    {"contribution": "quiescent_current", "share": 0.35},
                ),
                (
                    topology.id,
                    {"contribution": "topology_efficiency_model", "share": 0.24},
                ),
            ],
        )

        assert metric is not None
        edges = graph.get_edges_from(metric.id, relation=KGRelation.DERIVED_FROM)
        assert len(edges) == 3

        by_target = {edge.target_id: edge for edge in edges}
        assert set(by_target) == {constraint.id, component.id, topology.id}
        assert by_target[constraint.id].constraints == {
            "contribution": "supply_current_budget",
            "share": 0.41,
        }
        assert by_target[component.id].constraints == {
            "contribution": "quiescent_current",
            "share": 0.35,
        }
        assert by_target[topology.id].constraints == {
            "contribution": "topology_efficiency_model",
            "share": 0.24,
        }


class TestAuditTrailTraversal:
    def test_audit_trail_traversal_end_to_end(self) -> None:
        """MATCH (m)-[:DERIVED_FROM]->(input) equivalent on a real graph backend."""
        graph = KnowledgeGraph()
        design_id = _design_id()
        constraint = _constraint_input(graph, design_id)
        component = _component_input(graph)
        topology = _topology_input(graph)

        persist_predicted_metric(
            graph,
            design_id=design_id,
            metric_kind="cmrr_db",
            value=92.0,
            unit="dB",
            method="cmrr_estimator:v0.1-mock",
            derived_from=[
                (constraint.id, {"contribution": "input_mismatch", "share": 0.5}),
                (component.id, {"contribution": "opamp_cmrr", "share": 0.3}),
                (topology.id, {"contribution": "topology_gain_error", "share": 0.2}),
            ],
        )

        metrics = get_predicted_metrics(graph, design_id, metric_kind="cmrr_db")
        assert len(metrics) == 1
        metric = metrics[0]

        inputs = graph.get_neighbors(metric.id, relation=KGRelation.DERIVED_FROM)
        input_ids = {node.id for node in inputs}
        assert input_ids == {constraint.id, component.id, topology.id}

        for edge in graph.get_edges_from(metric.id, relation=KGRelation.DERIVED_FROM):
            assert edge.source_id == metric.id
            assert edge.relation == KGRelation.DERIVED_FROM
            assert "contribution" in edge.constraints
            assert "share" in edge.constraints


class TestGetPredictedMetricsReader:
    def test_get_predicted_metrics_reader(self) -> None:
        graph = KnowledgeGraph()
        design_id = _design_id()

        persist_predicted_metric(
            graph,
            design_id=design_id,
            metric_kind="battery_life_h",
            value=400.0,
            unit="h",
            method="power_budget:v0.1-mock",
            derived_from=[],
        )
        persist_predicted_metric(
            graph,
            design_id=design_id,
            metric_kind="cmrr_db",
            value=95.0,
            unit="dB",
            method="cmrr_estimator:v0.1-mock",
            derived_from=[],
        )

        all_metrics = get_predicted_metrics(graph, design_id)
        assert len(all_metrics) == 2
        kinds = {node.properties["metric_kind"] for node in all_metrics}
        assert kinds == {"battery_life_h", "cmrr_db"}

        filtered = get_predicted_metrics(graph, design_id, metric_kind="cmrr_db")
        assert len(filtered) == 1
        assert filtered[0].properties["metric_kind"] == "cmrr_db"


class TestKnowledgeVersionReuse:
    def test_knowledge_version_reused(self) -> None:
        graph = KnowledgeGraph()
        design_id = _design_id()
        baseline = knowledge_version(graph)

        node = persist_predicted_metric(
            graph,
            design_id=design_id,
            metric_kind="phase_noise_dbc_hz",
            value=-118.0,
            unit="dBc/Hz",
            method="pll_estimator:v0.1-mock",
            derived_from=[],
        )

        assert node is not None
        assert node.properties["knowledge_version"] == baseline


class TestMethodScopedMetricIdentity:
    def test_cross_method_same_metric_kind_coexist(self) -> None:
        graph = KnowledgeGraph()
        design_id = _design_id()

        heuristic = persist_predicted_metric(
            graph,
            design_id=design_id,
            metric_kind="cmrr_db",
            value=88.0,
            unit="dB",
            method="cmrr_heuristic:v0.1-mock",
            derived_from=[],
        )
        simulation = persist_predicted_metric(
            graph,
            design_id=design_id,
            metric_kind="cmrr_db",
            value=112.0,
            unit="dB",
            method="cmrr_simulation:v0.1-mock",
            derived_from=[],
        )

        assert heuristic is not None
        assert simulation is not None
        ids = {heuristic.id, simulation.id}
        assert ids == {
            f"predicted_metric:{design_id}:cmrr_db:cmrr_heuristic:v0.1-mock",
            f"predicted_metric:{design_id}:cmrr_db:cmrr_simulation:v0.1-mock",
        }
        for node_id in ids:
            assert graph.node_exists(node_id)

        cmrr_nodes = get_predicted_metrics(graph, design_id, metric_kind="cmrr_db")
        assert len(cmrr_nodes) == 2

    def test_same_method_rewrite_still_upserts(self) -> None:
        graph = KnowledgeGraph()
        design_id = _design_id()
        method = "cmrr_estimator:v0.1-mock"

        first = persist_predicted_metric(
            graph,
            design_id=design_id,
            metric_kind="cmrr_db",
            value=90.0,
            unit="dB",
            method=method,
            derived_from=[],
        )
        second = persist_predicted_metric(
            graph,
            design_id=design_id,
            metric_kind="cmrr_db",
            value=96.5,
            unit="dB",
            method=method,
            derived_from=[],
        )

        node_id = f"predicted_metric:{design_id}:cmrr_db:{method}"
        assert first is not None
        assert second is not None
        assert first.id == node_id
        assert second.id == node_id

        cmrr_nodes = get_predicted_metrics(graph, design_id, metric_kind="cmrr_db")
        assert len(cmrr_nodes) == 1
        assert cmrr_nodes[0].properties["value"] == pytest.approx(96.5)


class TestPredictedMetricConditionScope:
    def test_predicted_metric_condition_uses_real_model(self) -> None:
        graph = KnowledgeGraph()
        design_id = _design_id()
        condition = ConditionScope(
            parameter="frequency_hz",
            at=1000.0,
            raw_text="at 1 kHz",
        )

        node = persist_predicted_metric(
            graph,
            design_id=design_id,
            metric_kind="phase_noise_dbc_hz",
            value=-118.0,
            unit="dBc/Hz",
            method="pll_estimator:v0.1-mock",
            derived_from=[],
            condition=condition,
        )

        assert node is not None
        stored = graph.get_node(node.id)
        assert stored is not None
        restored = ConditionScope.model_validate(stored.properties["condition"])
        assert isinstance(restored, ConditionScope)
        assert restored.parameter == "frequency_hz"
        assert restored.at == pytest.approx(1000.0)
        assert restored.raw_text == "at 1 kHz"
