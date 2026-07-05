"""Integration tests proving topology classification actually reaches the
interval solver through the real pipeline stages (closes DOC_DRIFT_AUDIT.md
finding N4).

Unlike test_topology_classifier.py (isolated classifier unit tests) and
test_interval_solver.py (isolated Rule 1 unit tests with goal_topology set
by hand), these tests run the REAL src.intent.parser.parse_intent() —
meaning the real classify_topology() call inside it — and, for the
run_intent_pipeline() tests, the real Stage 1 -> Stage 2.75 wiring in
src/intent/pipeline.py, with only Stage 2 (completion engine) and
everything after Stage 2.75 mocked.

Why Stage 2 completion is mocked rather than run for real: Stage 2's LLM
call requires a live model backend not available in unit tests (same
convention as tests/unit/intent/test_pipeline_stage2.py). The rule-based
Stage 1 fallback that actually executes in this test environment does not
extract numeric electrical values from prompt text — that is Stage 2's job
in production. The mock below stands in for "Stage 2 already ran" by
injecting electrical constraints via intent.model_copy(), which preserves
every field Stage 1 populated (goal_topologies, goal_topology) unchanged —
proving the real value survives from Stage 1 through Stage 2.75 exactly as
it would in production.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.config import Config
from src.intent.parser import parse_intent
from src.schemas.intent import CurrentSpec, ElectricalConstraints, VoltageSpec


@pytest.fixture
def config() -> Config:
    return Config()


class TestRealParserPopulatesGoalTopology:
    """Stage 1 in isolation: the real parse_intent() call, no mocking."""

    def test_ldo_prompt_classifies_as_ldo(self, config: Config) -> None:
        intent = parse_intent("design a 3.3V LDO regulator for an IoT sensor", config)
        assert intent.goal_topology == "ldo"
        assert intent.goal_topologies
        assert intent.goal_topologies[0].name == "ldo"

    def test_boost_prompt_classifies_as_boost_converter(self, config: Config) -> None:
        intent = parse_intent("build a boost converter for a battery-powered wearable", config)
        assert intent.goal_topology == "boost_converter"

    def test_buck_boost_prompt_classifies_as_buck_boost(self, config: Config) -> None:
        intent = parse_intent("design a buck-boost converter for a variable input rail", config)
        assert intent.goal_topology == "buck_boost"

    def test_unrelated_prompt_leaves_goal_topology_none(self, config: Config) -> None:
        intent = parse_intent("design a 2.4GHz patch antenna for a drone", config)
        assert intent.goal_topology is None
        assert intent.goal_topologies == []


class TestRealParserThroughIntervalSolver:
    """Stage 1 (real) -> Stage 2.75 (real), no pipeline orchestration.

    Simulates Stage 2 having populated electrical constraints via
    model_copy — see module docstring for why this is necessary and what
    it does and does not mock.
    """

    def test_ldo_topology_applies_dropout_rule(self, config: Config) -> None:
        from src.intent.interval_solver import check_interval_constraints

        intent = parse_intent("design a 3.3V LDO regulator for an IoT sensor", config)
        assert intent.goal_topology == "ldo"

        # Simulate Stage 2: supply cannot reach output + LDO dropout (0.3V).
        intent = intent.model_copy(update={
            "electrical": ElectricalConstraints(
                supply_voltage=VoltageSpec(max_v=3.5, raw_text="3.5V max"),
                output_voltage_compliance=VoltageSpec(max_v=3.3, raw_text="3.3V"),
            )
        })

        result = check_interval_constraints(intent)
        assert not result.feasible
        assert result.derived["min_input_voltage_v"] == pytest.approx(3.6)

    def test_boost_topology_skips_voltage_chain(self, config: Config) -> None:
        from src.intent.interval_solver import check_interval_constraints

        intent = parse_intent("build a boost converter for a wearable", config)
        assert intent.goal_topology == "boost_converter"

        # Same numbers that would CRITICAL-conflict for an LDO/buck design —
        # legitimate for a boost converter (steps up).
        intent = intent.model_copy(update={
            "electrical": ElectricalConstraints(
                supply_voltage=VoltageSpec(max_v=3.3, raw_text="3.3V"),
                output_voltage_compliance=VoltageSpec(max_v=5.0, raw_text="5V"),
            )
        })

        result = check_interval_constraints(intent)
        assert result.feasible
        assert "min_input_voltage_v" not in result.derived

    def test_buck_boost_topology_skips_voltage_chain(self, config: Config) -> None:
        from src.intent.interval_solver import check_interval_constraints

        intent = parse_intent("design a buck-boost converter for a variable rail", config)
        assert intent.goal_topology == "buck_boost"

        intent = intent.model_copy(update={
            "electrical": ElectricalConstraints(
                supply_voltage=VoltageSpec(max_v=3.3, raw_text="3.3V"),
                output_voltage_compliance=VoltageSpec(max_v=5.0, raw_text="5V"),
            )
        })

        result = check_interval_constraints(intent)
        assert result.feasible
        assert "min_input_voltage_v" not in result.derived


class TestRealPipelineThroughStage275:
    """Full run_intent_pipeline() with only Stage 2 completion + everything
    after Stage 2.75 mocked — Stage 1 (parse_intent, classify_topology) and
    Stage 2.75 (assert_interval_feasible) execute for real."""

    def _stage2_injecting_electrical(self, electrical: ElectricalConstraints):
        """Build a run_completion_engine replacement that preserves the
        real Stage-1 intent (goal_topologies included) and merges in
        electrical constraints, standing in for Stage 2's LLM output."""

        def _fake_stage2(intent, config):
            return intent.model_copy(update={"electrical": electrical})

        return _fake_stage2

    @patch("src.intent.pipeline.enqueue_bom")
    @patch("src.intent.pipeline.persist_design_constraints")
    @patch("src.intent.pipeline.generate_bom")
    @patch("src.intent.pipeline.query_graph")
    @patch("src.intent.pipeline.run_completion_engine")
    def test_ldo_prompt_halts_at_gate_with_named_conflict(
        self,
        mock_stage2,
        mock_query_graph,
        mock_generate_bom,
        mock_persist,
        mock_enqueue,
        config: Config,
    ) -> None:
        mock_stage2.side_effect = self._stage2_injecting_electrical(
            ElectricalConstraints(
                supply_voltage=VoltageSpec(max_v=3.5, raw_text="3.5V max"),
                output_voltage_compliance=VoltageSpec(max_v=3.3, raw_text="3.3V"),
            )
        )

        from src.intent.pipeline import run_intent_pipeline

        intent, bom, _ = run_intent_pipeline(
            "design a 3.3V LDO regulator for an IoT sensor", MagicMock(), config
        )

        assert intent.goal_topology == "ldo"
        mock_query_graph.assert_not_called()
        mock_generate_bom.assert_not_called()
        assert bom.review_required is True
        assert any("dropout" in flag.lower() or "voltage" in flag.lower() for flag in bom.review_flags)

    @patch("src.intent.pipeline.enqueue_bom")
    @patch("src.intent.pipeline.persist_design_constraints")
    @patch("src.intent.pipeline.validate_bom")
    @patch("src.intent.pipeline.generate_bom")
    @patch("src.intent.pipeline.query_graph")
    @patch("src.intent.pipeline.run_completion_engine")
    def test_boost_prompt_proceeds_past_gate(
        self,
        mock_stage2,
        mock_query_graph,
        mock_generate_bom,
        mock_validate_bom,
        mock_persist,
        mock_enqueue,
        config: Config,
    ) -> None:
        mock_stage2.side_effect = self._stage2_injecting_electrical(
            ElectricalConstraints(
                supply_voltage=VoltageSpec(max_v=3.3, raw_text="3.3V"),
                output_voltage_compliance=VoltageSpec(max_v=5.0, raw_text="5V"),
            )
        )
        validated = MagicMock()
        validated.review_required = False
        validated.design_id = "design-boost"
        mock_validate_bom.return_value = validated

        from src.intent.pipeline import run_intent_pipeline

        intent, bom, _ = run_intent_pipeline(
            "build a boost converter for a wearable", MagicMock(), config
        )

        assert intent.goal_topology == "boost_converter"
        mock_query_graph.assert_called_once()
        mock_generate_bom.assert_called_once()
        mock_enqueue.assert_not_called()

    @patch("src.intent.pipeline.enqueue_bom")
    @patch("src.intent.pipeline.persist_design_constraints")
    @patch("src.intent.pipeline.validate_bom")
    @patch("src.intent.pipeline.generate_bom")
    @patch("src.intent.pipeline.query_graph")
    @patch("src.intent.pipeline.run_completion_engine")
    def test_buck_boost_prompt_proceeds_past_gate(
        self,
        mock_stage2,
        mock_query_graph,
        mock_generate_bom,
        mock_validate_bom,
        mock_persist,
        mock_enqueue,
        config: Config,
    ) -> None:
        mock_stage2.side_effect = self._stage2_injecting_electrical(
            ElectricalConstraints(
                supply_voltage=VoltageSpec(max_v=3.3, raw_text="3.3V"),
                output_voltage_compliance=VoltageSpec(max_v=5.0, raw_text="5V"),
            )
        )
        validated = MagicMock()
        validated.review_required = False
        validated.design_id = "design-buckboost"
        mock_validate_bom.return_value = validated

        from src.intent.pipeline import run_intent_pipeline

        intent, bom, _ = run_intent_pipeline(
            "design a buck-boost converter for a variable input rail", MagicMock(), config
        )

        assert intent.goal_topology == "buck_boost"
        mock_query_graph.assert_called_once()
        mock_generate_bom.assert_called_once()
