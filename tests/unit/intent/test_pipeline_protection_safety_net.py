"""Gate tests for protection safety-net wiring in run_intent_pipeline."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.config import Config
from src.knowledge_graph.graph import KnowledgeGraph
from src.review._schemas import GateStage
from src.review.queue import _get_db_path, get_review_item
from src.schemas.common import ImpliedRequirement
from src.schemas.intent import (
    BOMEntry,
    DesignMethodology,
    ImprovedIntentDict,
    ProtectionRequirement,
    ValidatedBOM,
)
from src.schemas.kg import DesignSubgraph

PROMPT = "design with reverse-current protection"


def _intent(
    *,
    protection_requirements: list[ProtectionRequirement] | None = None,
    contradictions_detected: list[str] | None = None,
    implied_requirements: list[ImpliedRequirement] | None = None,
) -> ImprovedIntentDict:
    return ImprovedIntentDict(
        goal="current_source",
        application="lab",
        design_methodology=DesignMethodology.MIXED_SIGNAL,
        board_type="double_sided_SMD",
        raw_prompt=PROMPT,
        protection_requirements=protection_requirements or [],
        contradictions_detected=contradictions_detected or [],
        implied_requirements=implied_requirements or [],
    )


def _subgraph() -> DesignSubgraph:
    return DesignSubgraph(
        component_types=[],
        component_instances=[],
        design_rules=[],
        placement_rules=[],
        routing_hints=[],
        design_methodology="standard_SMD",
        path_confidences={},
        query_depth=0,
        query_metadata={},
    )


def _validated_bom(
    intent: ImprovedIntentDict,
    *,
    review_required: bool = False,
    review_flags: list[str] | None = None,
) -> ValidatedBOM:
    return ValidatedBOM(
        design_id="design-protection-pipeline",
        intent=intent,
        components=[
            BOMEntry(
                ref="U1",
                component_type="regulator",
                specific_part="TPS62933",
                justification="test",
                source="rule",
                confidence=0.95,
            ),
        ],
        total_confidence=0.95,
        review_required=review_required,
        review_flags=review_flags or [],
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


@pytest.fixture
def config(tmp_path) -> Config:
    cfg = Config()
    cfg.output_dir = tmp_path / "output"
    cfg.review_queue_path = tmp_path / "review_queue.db"
    return cfg


@pytest.fixture
def graph() -> KnowledgeGraph:
    return KnowledgeGraph()


@patch("src.intent.pipeline.validate_bom")
@patch("src.intent.pipeline.generate_bom")
@patch("src.intent.pipeline.query_graph")
@patch("src.intent.pipeline.run_completion_engine")
@patch("src.intent.pipeline.parse_intent")
def test_pipeline_enqueues_unresolved_protection_automatically(
    mock_parse_intent,
    mock_run_completion_engine,
    mock_query_graph,
    mock_generate_bom,
    mock_validate_bom,
    config: Config,
    graph: KnowledgeGraph,
) -> None:
    requirement = ProtectionRequirement(
        kind="reverse_current",
        raw_text="reverse-current protection rated for 100mA",
    )
    intent = _intent(
        protection_requirements=[requirement],
        contradictions_detected=[
            "Protection ask recorded from prompt ('reverse-current protection rated for 100mA') "
            "but no topology-library block is available to satisfy it yet"
        ],
    )
    mock_parse_intent.return_value = intent
    mock_run_completion_engine.return_value = intent
    mock_query_graph.return_value = _subgraph()
    mock_generate_bom.return_value = MagicMock()
    mock_validate_bom.return_value = _validated_bom(intent, review_required=False)

    from src.intent.pipeline import run_intent_pipeline

    _, validated_bom, _ = run_intent_pipeline(PROMPT, graph, config)

    item = get_review_item(validated_bom.design_id, GateStage.BOM, config)
    assert item is not None

    db_path = _get_db_path(config)
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT verdict FROM review_queue WHERE component_id = ?",
            (validated_bom.design_id,),
        ).fetchall()
        assert any(row[0] == "PROTECTION_UNRESOLVED" for row in rows)
    finally:
        conn.close()


@patch("src.intent.pipeline.enqueue_bom")
@patch("src.intent.pipeline.validate_bom")
@patch("src.intent.pipeline.generate_bom")
@patch("src.intent.pipeline.query_graph")
@patch("src.intent.pipeline.run_completion_engine")
@patch("src.intent.pipeline.parse_intent")
def test_stage2_protection_contradiction_triggers_review(
    mock_parse_intent,
    mock_run_completion_engine,
    mock_query_graph,
    mock_generate_bom,
    mock_validate_bom,
    mock_enqueue_bom,
    config: Config,
    graph: KnowledgeGraph,
) -> None:
    requirement = ProtectionRequirement(
        kind="esd",
        raw_text="ESD protection on RF input",
    )
    intent = _intent(
        protection_requirements=[requirement],
        contradictions_detected=[
            "Protection ask recorded from prompt ('ESD protection on RF input') "
            "but no topology-library block is available to satisfy it yet"
        ],
    )
    mock_parse_intent.return_value = intent
    mock_run_completion_engine.return_value = intent
    mock_query_graph.return_value = _subgraph()
    mock_generate_bom.return_value = MagicMock()
    mock_validate_bom.return_value = _validated_bom(intent, review_required=False)

    from src.intent.pipeline import run_intent_pipeline

    _, validated_bom, _ = run_intent_pipeline(PROMPT, graph, config)

    mock_enqueue_bom.assert_called_once()
    enqueued_bom = mock_enqueue_bom.call_args[0][0]
    assert enqueued_bom.review_required is True
    assert any(
        flag.startswith("protection_unresolved:esd:")
        for flag in enqueued_bom.review_flags
    )

    item = get_review_item(validated_bom.design_id, GateStage.BOM, config)
    assert item is not None
    assert any(
        flag.startswith("protection_unresolved:esd:")
        for flag in item.flags
    )


@patch("src.intent.pipeline.enqueue_bom")
@patch("src.intent.pipeline.validate_bom")
@patch("src.intent.pipeline.generate_bom")
@patch("src.intent.pipeline.query_graph")
@patch("src.intent.pipeline.run_completion_engine")
@patch("src.intent.pipeline.parse_intent")
def test_non_protection_contradiction_unaffected(
    mock_parse_intent,
    mock_run_completion_engine,
    mock_query_graph,
    mock_generate_bom,
    mock_validate_bom,
    mock_enqueue_bom,
    config: Config,
    graph: KnowledgeGraph,
) -> None:
    bypass_warning = (
        "LDO output noise is only effective with proper bypass at the load"
    )
    intent = _intent(
        contradictions_detected=[bypass_warning],
        implied_requirements=[
            ImpliedRequirement(
                requirement="Use low-noise LDO",
                component_implication="low_noise_ldo",
                reasoning="Ultra low noise requirement",
                confidence=0.9,
                source_constraint="topology",
            ),
        ],
    )
    mock_parse_intent.return_value = intent
    mock_run_completion_engine.return_value = intent
    mock_query_graph.return_value = _subgraph()
    mock_generate_bom.return_value = MagicMock()
    mock_validate_bom.return_value = _validated_bom(intent, review_required=False)

    from src.intent.pipeline import run_intent_pipeline

    _, validated_bom, _ = run_intent_pipeline(PROMPT, graph, config)

    assert validated_bom.review_required is False
    assert validated_bom.review_flags == []
    mock_enqueue_bom.assert_not_called()
