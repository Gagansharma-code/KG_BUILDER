"""Gate tests for Stage 2 failure handling in run_intent_pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.completion.engine import CompletionEngineError
from src.config import Config
from src.knowledge_graph.graph import KnowledgeGraph
from src.review._schemas import GateStage
from src.review.queue import get_review_item
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
) -> ImprovedIntentDict:
    return ImprovedIntentDict(
        goal="current_source",
        application="lab",
        design_methodology=DesignMethodology.MIXED_SIGNAL,
        board_type="double_sided_SMD",
        raw_prompt=PROMPT,
        protection_requirements=protection_requirements or [],
        contradictions_detected=contradictions_detected or [],
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
        design_id="design-stage2-incomplete",
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
def test_rule_checker_runs_on_stage2_failure(
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
    stage1_intent = _intent(protection_requirements=[requirement])
    mock_parse_intent.return_value = stage1_intent
    mock_run_completion_engine.side_effect = CompletionEngineError("LLM timeout")
    mock_query_graph.return_value = _subgraph()
    mock_generate_bom.return_value = MagicMock()
    mock_validate_bom.return_value = _validated_bom(stage1_intent, review_required=False)

    from src.intent.pipeline import run_intent_pipeline

    result_intent, _, _ = run_intent_pipeline(PROMPT, graph, config)

    assert any(
        "topology-library block" in description
        for description in result_intent.contradictions_detected
    )


@patch("src.intent.pipeline.validate_bom")
@patch("src.intent.pipeline.generate_bom")
@patch("src.intent.pipeline.query_graph")
@patch("src.intent.pipeline.run_completion_engine")
@patch("src.intent.pipeline.parse_intent")
def test_stage2_incomplete_flag_set_on_failure(
    mock_parse_intent,
    mock_run_completion_engine,
    mock_query_graph,
    mock_generate_bom,
    mock_validate_bom,
    config: Config,
    graph: KnowledgeGraph,
) -> None:
    intent = _intent()
    mock_parse_intent.return_value = intent
    mock_run_completion_engine.side_effect = CompletionEngineError("LLM timeout")
    mock_query_graph.return_value = _subgraph()
    mock_generate_bom.return_value = MagicMock()
    mock_validate_bom.return_value = _validated_bom(intent, review_required=False)

    from src.intent.pipeline import run_intent_pipeline, stage2_incomplete_from_bom

    _, validated_bom, _ = run_intent_pipeline(PROMPT, graph, config)

    assert stage2_incomplete_from_bom(validated_bom) is True
    assert "stage2_incomplete" in validated_bom.review_flags


@patch("src.intent.pipeline.validate_bom")
@patch("src.intent.pipeline.generate_bom")
@patch("src.intent.pipeline.query_graph")
@patch("src.intent.pipeline.run_completion_engine")
@patch("src.intent.pipeline.parse_intent")
def test_stage2_incomplete_triggers_review(
    mock_parse_intent,
    mock_run_completion_engine,
    mock_query_graph,
    mock_generate_bom,
    mock_validate_bom,
    config: Config,
    graph: KnowledgeGraph,
) -> None:
    intent = _intent()
    mock_parse_intent.return_value = intent
    mock_run_completion_engine.side_effect = CompletionEngineError("LLM timeout")
    mock_query_graph.return_value = _subgraph()
    mock_generate_bom.return_value = MagicMock()
    mock_validate_bom.return_value = _validated_bom(intent, review_required=False)

    from src.intent.pipeline import run_intent_pipeline

    _, validated_bom, _ = run_intent_pipeline(PROMPT, graph, config)

    assert validated_bom.review_required is True
    assert "stage2_incomplete" in validated_bom.review_flags

    item = get_review_item(validated_bom.design_id, GateStage.BOM, config)
    assert item is not None
    assert "stage2_incomplete" in item.flags


@patch("src.intent.pipeline.enqueue_bom")
@patch("src.intent.pipeline.validate_bom")
@patch("src.intent.pipeline.generate_bom")
@patch("src.intent.pipeline.query_graph")
@patch("src.intent.pipeline.run_completion_engine")
@patch("src.intent.pipeline.parse_intent")
def test_stage2_success_path_unchanged(
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

    from src.intent.pipeline import run_intent_pipeline, stage2_incomplete_from_bom

    result_intent, validated_bom, _ = run_intent_pipeline(PROMPT, graph, config)

    assert stage2_incomplete_from_bom(validated_bom) is False
    assert result_intent.contradictions_detected == intent.contradictions_detected
    mock_enqueue_bom.assert_called_once()
    enqueued_bom = mock_enqueue_bom.call_args[0][0]
    assert enqueued_bom.review_required is True
    assert "stage2_incomplete" not in enqueued_bom.review_flags
    assert any(
        flag.startswith("protection_unresolved:esd:")
        for flag in enqueued_bom.review_flags
    )
