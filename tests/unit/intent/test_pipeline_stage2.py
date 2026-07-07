"""Gate tests for Stage 2 wiring in run_intent_pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.completion.engine import CompletionEngineError
from src.config import Config
from src.knowledge_graph.graph import KnowledgeGraph
from src.schemas.common import Ambiguity
from src.schemas.intent import (
    BOMEntry,
    DesignMethodology,
    ImprovedIntentDict,
    ValidatedBOM,
)
from src.schemas.kg import DesignSubgraph

PROMPT = "test prompt"

blocking_ambiguity = Ambiguity(
    field="f",
    description="d",
    blocking=True,
    severity="ERROR",
)


def make_intent(
    clarification_required: bool = False,
    ambiguities: list[Ambiguity] | None = None,
) -> ImprovedIntentDict:
    return ImprovedIntentDict(
        goal="test",
        application="test",
        design_methodology=DesignMethodology.STANDARD_SMD,
        board_type="standard_SMD",
        raw_prompt=PROMPT,
        clarification_required=clarification_required,
        ambiguities=ambiguities or [],
    )


def _mock_subgraph() -> DesignSubgraph:
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


def _mock_validated_bom(
    intent: ImprovedIntentDict,
    *,
    review_required: bool = False,
) -> ValidatedBOM:
    return ValidatedBOM(
        design_id="d1",
        intent=intent,
        components=[
            BOMEntry(
                ref="U1",
                component_type="regulator",
                specific_part="TPS62933",
                justification="test",
                source="rule",
                confidence=0.9,
            ),
        ],
        total_confidence=0.9,
        review_required=review_required,
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


@pytest.fixture
def config() -> Config:
    return Config()


@pytest.fixture
def mock_graph() -> KnowledgeGraph:
    return MagicMock(spec=KnowledgeGraph)


@patch("src.intent.pipeline.run_completion_engine")
@patch("src.intent.pipeline.parse_intent")
def test_stage2_called_when_stage1_passes(
    mock_parse_intent,
    mock_run_completion_engine,
    config: Config,
    mock_graph: KnowledgeGraph,
) -> None:
    intent = make_intent(clarification_required=False)
    mock_parse_intent.return_value = intent
    mock_run_completion_engine.return_value = intent

    with (
        patch("src.intent.pipeline.query_graph", return_value=_mock_subgraph()),
        patch("src.intent.pipeline.generate_bom") as mock_generate_bom,
        patch("src.intent.pipeline.validate_bom") as mock_validate_bom,
    ):
        mock_bom = MagicMock()
        mock_validated = _mock_validated_bom(intent)
        mock_generate_bom.return_value = mock_bom
        mock_validate_bom.return_value = mock_validated

        from src.intent.pipeline import run_intent_pipeline

        run_intent_pipeline(PROMPT, mock_graph, config)

    mock_run_completion_engine.assert_called_once_with(intent, config)


@patch("src.intent.pipeline.run_completion_engine")
@patch("src.intent.pipeline.parse_intent")
def test_stage2_not_called_when_stage1_blocks(
    mock_parse_intent,
    mock_run_completion_engine,
    config: Config,
    mock_graph: KnowledgeGraph,
) -> None:
    intent = make_intent(
        clarification_required=True,
        ambiguities=[blocking_ambiguity],
    )
    mock_parse_intent.return_value = intent

    from src.intent.pipeline import run_intent_pipeline

    # run_intent_pipeline returns (intent, bom, retrieval_result) -- a
    # triple, per src/intent/pipeline.py's Stage 2.5 retrieval addition.
    _, validated_bom, _ = run_intent_pipeline(PROMPT, mock_graph, config)

    mock_run_completion_engine.assert_not_called()
    assert validated_bom.review_required is True


@patch("src.intent.pipeline.query_graph")
@patch("src.intent.pipeline.run_completion_engine")
@patch("src.intent.pipeline.parse_intent")
def test_pipeline_halts_at_gate2_when_stage2_blocks(
    mock_parse_intent,
    mock_run_completion_engine,
    mock_query_graph,
    config: Config,
    mock_graph: KnowledgeGraph,
) -> None:
    intent_v1 = make_intent(clarification_required=False)
    intent_v2 = make_intent(
        clarification_required=True,
        ambiguities=[blocking_ambiguity],
    )
    mock_parse_intent.return_value = intent_v1
    mock_run_completion_engine.return_value = intent_v2

    from src.intent.pipeline import run_intent_pipeline

    _, validated_bom, _ = run_intent_pipeline(PROMPT, mock_graph, config)

    mock_query_graph.assert_not_called()
    assert validated_bom.review_required is True


@patch("src.intent.pipeline.validate_bom")
@patch("src.intent.pipeline.generate_bom")
@patch("src.intent.pipeline.query_graph")
@patch("src.intent.pipeline.run_completion_engine")
@patch("src.intent.pipeline.parse_intent")
def test_completion_engine_error_continues_with_stage1_intent(
    mock_parse_intent,
    mock_run_completion_engine,
    mock_query_graph,
    mock_generate_bom,
    mock_validate_bom,
    config: Config,
    mock_graph: KnowledgeGraph,
) -> None:
    intent = make_intent(clarification_required=False)
    mock_parse_intent.return_value = intent
    mock_run_completion_engine.side_effect = CompletionEngineError("LLM timeout")
    mock_query_graph.return_value = _mock_subgraph()
    mock_bom = MagicMock()
    mock_validated = _mock_validated_bom(intent)
    mock_generate_bom.return_value = mock_bom
    mock_validate_bom.return_value = mock_validated

    from src.intent.pipeline import run_intent_pipeline

    _, validated_bom, _ = run_intent_pipeline(PROMPT, mock_graph, config)

    mock_query_graph.assert_called_once()
    assert validated_bom is not None


@patch("src.intent.pipeline.validate_bom")
@patch("src.intent.pipeline.generate_bom")
@patch("src.intent.pipeline.query_graph")
@patch("src.intent.pipeline.run_completion_engine")
@patch("src.intent.pipeline.parse_intent")
def test_unexpected_stage2_error_continues_pipeline(
    mock_parse_intent,
    mock_run_completion_engine,
    mock_query_graph,
    mock_generate_bom,
    mock_validate_bom,
    config: Config,
    mock_graph: KnowledgeGraph,
) -> None:
    intent = make_intent(clarification_required=False)
    mock_parse_intent.return_value = intent
    mock_run_completion_engine.side_effect = RuntimeError("unexpected")
    mock_query_graph.return_value = _mock_subgraph()
    mock_generate_bom.return_value = MagicMock()
    mock_validate_bom.return_value = _mock_validated_bom(intent)

    from src.intent.pipeline import run_intent_pipeline

    run_intent_pipeline(PROMPT, mock_graph, config)

    mock_query_graph.assert_called_once()


@patch("src.intent.pipeline.validate_bom")
@patch("src.intent.pipeline.generate_bom")
@patch("src.intent.pipeline.query_graph")
@patch("src.intent.pipeline.run_completion_engine")
@patch("src.intent.pipeline.parse_intent")
def test_stage2_enriched_intent_passed_to_query_graph(
    mock_parse_intent,
    mock_run_completion_engine,
    mock_query_graph,
    mock_generate_bom,
    mock_validate_bom,
    config: Config,
    mock_graph: KnowledgeGraph,
) -> None:
    intent_v1 = make_intent(clarification_required=False)
    intent_v2 = make_intent(clarification_required=False)
    mock_parse_intent.return_value = intent_v1
    mock_run_completion_engine.return_value = intent_v2
    mock_query_graph.return_value = _mock_subgraph()
    mock_generate_bom.return_value = MagicMock()
    mock_validate_bom.return_value = _mock_validated_bom(intent_v2)

    from src.intent.pipeline import run_intent_pipeline

    run_intent_pipeline(PROMPT, mock_graph, config)

    mock_query_graph.assert_called_once()
    call_args = mock_query_graph.call_args
    assert call_args[0][0] is intent_v2
    assert call_args[0][0] is not intent_v1


@patch("src.intent.pipeline.validate_bom")
@patch("src.intent.pipeline.generate_bom")
@patch("src.intent.pipeline.query_graph")
@patch("src.intent.pipeline.run_completion_engine")
@patch("src.intent.pipeline.parse_intent")
def test_full_happy_path_returns_enriched_intent_and_bom(
    mock_parse_intent,
    mock_run_completion_engine,
    mock_query_graph,
    mock_generate_bom,
    mock_validate_bom,
    config: Config,
    mock_graph: KnowledgeGraph,
) -> None:
    intent_v1 = make_intent(clarification_required=False)
    intent_v2 = make_intent(clarification_required=False)
    mock_parse_intent.return_value = intent_v1
    mock_run_completion_engine.return_value = intent_v2
    mock_subgraph = _mock_subgraph()
    mock_bom = MagicMock()
    mock_validated = _mock_validated_bom(intent_v2, review_required=False)
    mock_query_graph.return_value = mock_subgraph
    mock_generate_bom.return_value = mock_bom
    mock_validate_bom.return_value = mock_validated

    from src.intent.pipeline import run_intent_pipeline

    result_intent, result_bom, _ = run_intent_pipeline(PROMPT, mock_graph, config)

    assert result_intent is intent_v2
    assert result_bom is mock_validated
    assert result_bom.review_required is False
