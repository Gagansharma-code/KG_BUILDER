"""Gate tests for typed constraint population (electrical/thermal/performance).

Proves the wiring gap documented in SCHEMA_ARCHITECTURE_REVIEW_2026-07.md §0
(ground-truth fact 1) is closed: parse_intent() now sources these fields from
a real (mocked-in-tests) LLM extraction call, and the two downstream
consumers (interval_solver, persist_design_constraints) receive and act on
non-None data — not just theoretically capable of it.

No live LLM/API calls are made in any test here — call_llm_with_instructor
is mocked at its import site in src.intent.parser.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.completion.engine import CompletionEngineError
from src.intent.interval_solver import ConstraintConflictError, assert_interval_feasible
from src.intent.parser import TypedConstraintExtraction, parse_intent
from src.knowledge_graph import KnowledgeGraph
from src.knowledge_graph.constraints import persist_design_constraints
from src.schemas.intent import (
    CurrentSpec,
    ElectricalConstraints,
    VoltageSpec,
)

MODULE = "src.intent.parser"


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.model_paths = {"qwen25_7b": "/tmp/mock_model"}
    return config


def _entry004_prompt1_extraction() -> TypedConstraintExtraction:
    """Modeled on Entry 004 Prompt 1: <250uA total, offset <5uV, noise
    <50nV/rtHz at 1kHz (SCIENTIFIC_PROMPT_ANALYSIS_LOG.md Entry 004)."""
    return TypedConstraintExtraction(
        electrical=ElectricalConstraints(
            supply_voltage=VoltageSpec(
                min_v=3.0, max_v=4.2, raw_text="single Li-ion battery (3.0-4.2V)"
            ),
            supply_current_budget=CurrentSpec(
                max_ma=0.25, raw_text="less than 250 uA total current"
            ),
        ),
        thermal=None,
        performance=None,
    )


class TestElectricalConstraintsPopulatedFromMockedLLM:
    def test_supply_current_budget_and_voltage_populated(self, mock_config):
        prompt = (
            "Design an ultra-low-power instrumentation amplifier consuming "
            "less than 250 uA total current from a single Li-ion battery "
            "(3.0-4.2V)."
        )
        with patch(f"{MODULE}.call_llm_with_instructor") as mock_llm:
            mock_llm.return_value = _entry004_prompt1_extraction()
            intent = parse_intent(prompt, mock_config)

        assert intent.electrical is not None
        assert intent.electrical.supply_current_budget is not None
        assert intent.electrical.supply_current_budget.max_ma == pytest.approx(0.25)
        assert intent.electrical.supply_voltage is not None
        assert intent.electrical.supply_voltage.max_v == pytest.approx(4.2)
        # Field not the hardcoded None the stub previously always produced.
        assert intent.electrical.supply_voltage.raw_text != ""

    def test_llm_called_with_typed_constraint_schema(self, mock_config):
        """The extraction call must request the real typed schema, not some
        ad hoc intermediate format (per the task's explicit requirement)."""
        with patch(f"{MODULE}.call_llm_with_instructor") as mock_llm:
            mock_llm.return_value = TypedConstraintExtraction()
            parse_intent("design a buck converter", mock_config)

        assert mock_llm.called
        _, kwargs = mock_llm.call_args
        assert kwargs["output_schema"] is TypedConstraintExtraction
        # Soft-degrade call: must not inherit Stage 2's 3-attempt backoff.
        assert kwargs["max_attempts"] == 1


class TestIntervalSolverFiresOnPopulatedIntent:
    def test_infeasible_voltage_dropout_detected_on_real_parse_output(
        self, mock_config
    ):
        """First proof the solver detects a conflict on intent data that
        flowed through the real parse_intent() pipeline (mocked only at the
        LLM boundary), not on a hand-built ImprovedIntentDict bypassing
        parse_intent() entirely (already covered by test_interval_solver.py).
        """
        extraction = TypedConstraintExtraction(
            electrical=ElectricalConstraints(
                supply_voltage=VoltageSpec(max_v=3.5, raw_text="3.5V max supply"),
                output_voltage_compliance=VoltageSpec(max_v=3.3, raw_text="3.3V output"),
            ),
        )
        with patch(f"{MODULE}.call_llm_with_instructor") as mock_llm:
            mock_llm.return_value = extraction
            intent = parse_intent(
                "design an ldo regulator with 3.3V output from a 3.5V max supply",
                mock_config,
            )

        assert intent.electrical is not None
        assert intent.electrical.supply_voltage.max_v == pytest.approx(3.5)

        with pytest.raises(ConstraintConflictError) as exc_info:
            assert_interval_feasible(intent)
        assert "3.5" in str(exc_info.value)


class TestPersistDesignConstraintsWritesRealElectricalNode:
    def test_electrical_node_written_with_nonempty_spec(self, mock_config):
        extraction = _entry004_prompt1_extraction()
        with patch(f"{MODULE}.call_llm_with_instructor") as mock_llm:
            mock_llm.return_value = extraction
            intent = parse_intent(
                "ultra-low-power instrumentation amp under 250uA", mock_config
            )

        graph = KnowledgeGraph()
        nodes = persist_design_constraints(intent, "design-typed-001", graph)

        electrical_nodes = [n for n in nodes if n.properties.get("kind") == "electrical"]
        assert len(electrical_nodes) == 1
        node = electrical_nodes[0]
        assert node.design_id == "design-typed-001"
        assert node.properties["spec"]  # non-empty, not skipped as None
        assert node.properties["spec"]["supply_current_budget"]["max_ma"] == pytest.approx(0.25)
        assert graph.node_exists(node.id)


class TestLLMExtractionFailureDoesNotRaise:
    def test_malformed_response_leaves_fields_none_and_logs_warning(
        self, mock_config, caplog
    ):
        with patch(f"{MODULE}.call_llm_with_instructor") as mock_llm:
            mock_llm.side_effect = CompletionEngineError("malformed JSON, validation failed")
            with caplog.at_level("WARNING"):
                intent = parse_intent("design a patch antenna", mock_config)

        assert intent.electrical is None
        assert intent.thermal is None
        assert intent.performance is None
        assert any(
            "Typed constraint extraction failed" in record.message
            for record in caplog.records
        )

    def test_generic_exception_does_not_propagate(self, mock_config):
        with patch(f"{MODULE}.call_llm_with_instructor") as mock_llm:
            mock_llm.side_effect = RuntimeError("connection refused")
            # Must not raise.
            intent = parse_intent("design a boost converter", mock_config)

        assert intent.electrical is None
