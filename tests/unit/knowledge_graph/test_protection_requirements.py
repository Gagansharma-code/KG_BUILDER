"""Gate tests for protection_requirements KG wiring (schema review §4)."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest

from src.completion.contradiction_checker import run_rule_checker
from src.completion.schemas import RequirementCompletionResult
from src.knowledge_graph import KnowledgeGraph
from src.knowledge_graph.constraints import (
    persist_design_constraints,
    persist_protection_requirements,
)
from src.review._schemas import GateStage
from src.review.queue import _get_db_path, enqueue_unresolved_protection
from src.schemas.datasheet import ExtractionMethod
from src.schemas.intent import (
    DesignMethodology,
    ImprovedIntentDict,
    ProtectionRequirement,
)
from src.schemas.kg import KGEdge, KGNode, KGNodeType, KGRelation


def _intent(*requirements: ProtectionRequirement) -> ImprovedIntentDict:
    return ImprovedIntentDict(
        goal="current_source",
        application="lab",
        design_methodology=DesignMethodology.MIXED_SIGNAL,
        board_type="double_sided_SMD",
        raw_prompt="test protection prompt",
        protection_requirements=list(requirements),
    )


def _functional_block(block_slug: str) -> KGNode:
    return KGNode(
        id=f"functional_block:test_topology:{block_slug}",
        node_type=KGNodeType.FUNCTIONAL_BLOCK,
        layer=4,
        label=block_slug.replace("_", " ").title(),
        properties={"slug": block_slug},
        source="test",
        confidence=1.0,
        extraction_method=ExtractionMethod.MANUAL,
        created_at="2026-07-07T00:00:00Z",
    )


class TestProtectionRequirementModel:
    def test_protection_requirement_model_shape(self) -> None:
        req = ProtectionRequirement(
            kind="reverse_current",
            params={"current_rating_ma": 100.0},
            raw_text="reverse-current protection rated for 100mA",
        )
        assert req.kind == "reverse_current"
        assert req.params["current_rating_ma"] == pytest.approx(100.0)

    def test_dead_booleans_removed(self) -> None:
        from src.schemas.intent import ElectricalConstraints, ThermalConstraints

        assert "kelvin_sensing_required" not in ThermalConstraints.model_fields
        assert "polarity_generation_required" not in ElectricalConstraints.model_fields


class TestProtectionConstraintPersistence:
    def test_protection_persisted_as_constraint_node(self) -> None:
        graph = KnowledgeGraph()
        design_id = "design-protection-001"
        req = ProtectionRequirement(
            kind="esd",
            params={"voltage_v": 8.0},
            raw_text="ESD protection on RF input",
        )
        unresolved = persist_protection_requirements(
            _intent(req), design_id, graph
        )

        assert unresolved == [req]
        node_id = f"design_constraint:{design_id}:protection:esd"
        assert graph.node_exists(node_id)
        node = graph.get_node(node_id)
        assert node is not None
        assert node.properties["kind"] == "protection"
        assert node.properties["scope"] == "esd"
        assert node.properties["params_voltage_v"] == pytest.approx(8.0)
        assert node.properties["spec"]["requirement_kind"] == "esd"

    def test_protection_resolves_to_functional_block_when_available(self) -> None:
        graph = KnowledgeGraph()
        design_id = "design-protection-resolve"
        block = _functional_block("reverse_current_protection")
        graph.add_node(block)

        req = ProtectionRequirement(
            kind="reverse_current",
            raw_text="reverse-current protection",
        )
        unresolved = persist_protection_requirements(
            _intent(req), design_id, graph
        )

        assert unresolved == []
        node_id = f"design_constraint:{design_id}:protection:reverse_current"
        edges = graph.get_edges_from(node_id, relation=KGRelation.REQUIRES)
        assert len(edges) == 1
        assert edges[0].target_id == block.id


class TestProtectionSafetyNet:
    def test_protection_flags_review_when_unresolved(self, tmp_path) -> None:
        graph = KnowledgeGraph()
        design_id = "design-protection-review"
        config = MagicMock()
        config.review_queue_path = tmp_path / "review_queue.db"
        config.output_dir = tmp_path

        req = ProtectionRequirement(
            kind="kelvin_sensing",
            raw_text="Kelvin sensing on the sense resistor",
        )
        intent = _intent(req)

        unresolved = persist_protection_requirements(intent, design_id, graph)
        assert len(unresolved) == 1

        item = enqueue_unresolved_protection(intent, design_id, unresolved, config)
        assert item.stage == GateStage.BOM.value
        assert item.verdict == "PROTECTION_UNRESOLVED"
        assert any("protection_unresolved:kelvin_sensing" in flag for flag in item.flags)

        db_path = _get_db_path(config)
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                "SELECT flags FROM review_queue WHERE component_id = ?",
                (design_id,),
            ).fetchone()
            assert row is not None
        finally:
            conn.close()

        contradictions = run_rule_checker(
            intent,
            RequirementCompletionResult(),
        )
        assert any(
            c.severity == "WARNING" and "kelvin_sensing" in c.constraint_a
            for c in contradictions
        )

    def test_persist_design_constraints_enqueues_when_config_provided(
        self, tmp_path
    ) -> None:
        graph = KnowledgeGraph()
        design_id = "design-protection-auto-enqueue"
        config = MagicMock()
        config.review_queue_path = tmp_path / "review_queue.db"
        config.output_dir = tmp_path

        req = ProtectionRequirement(kind="soft_start", raw_text="soft-start")
        intent = _intent(req)

        persist_design_constraints(intent, design_id, graph, config=config)

        db_path = _get_db_path(config)
        conn = sqlite3.connect(str(db_path))
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM review_queue WHERE component_id = ?",
                (design_id,),
            ).fetchone()[0]
            assert count == 1
        finally:
            conn.close()
