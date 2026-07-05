"""Unit tests for src/intent/interval_solver.py and its pipeline wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.intent.interval_solver import (
    ConstraintConflictError,
    assert_interval_feasible,
    check_interval_constraints,
)
from src.schemas.intent import (
    CurrentSpec,
    DesignMethodology,
    ElectricalConstraints,
    ImprovedIntentDict,
    VoltageSpec,
)


def _intent(**overrides) -> ImprovedIntentDict:
    defaults = dict(
        goal="ldo_regulator",
        application="iot",
        design_methodology=DesignMethodology.POWER_MANAGEMENT,
        board_type="double_sided_SMD",
        raw_prompt="test prompt",
        goal_topology="ldo",
    )
    defaults.update(overrides)
    return ImprovedIntentDict(**defaults)


class TestVoltageDropoutChain:
    def test_valid_chain_passes(self) -> None:
        intent = _intent(
            electrical=ElectricalConstraints(
                supply_voltage=VoltageSpec(min_v=4.5, max_v=5.5, raw_text="5V"),
                output_voltage_compliance=VoltageSpec(max_v=3.3, raw_text="3.3V"),
            )
        )
        result = check_interval_constraints(intent)
        assert result.feasible
        assert result.derived["min_input_voltage_v"] == pytest.approx(3.6)

    def test_infeasible_chain_detected(self) -> None:
        """3.3V out + 0.3V dropout needs >= 3.6V, but supply max is 3.5V."""
        intent = _intent(
            electrical=ElectricalConstraints(
                supply_voltage=VoltageSpec(max_v=3.5, raw_text="3.5V max"),
                output_voltage_compliance=VoltageSpec(max_v=3.3, raw_text="3.3V"),
            )
        )
        result = check_interval_constraints(intent)
        assert not result.feasible
        conflict = result.conflicts[0]
        assert conflict.severity == "CRITICAL"
        assert "3.5" in conflict.constraint_a
        assert "3.6" in conflict.constraint_b

    def test_non_ldo_topology_uses_zero_dropout(self) -> None:
        intent = _intent(
            goal_topology="buck_converter",
            electrical=ElectricalConstraints(
                supply_voltage=VoltageSpec(max_v=3.4, raw_text="3.4V"),
                output_voltage_compliance=VoltageSpec(max_v=3.3, raw_text="3.3V"),
            ),
        )
        result = check_interval_constraints(intent)
        assert result.feasible  # 3.4 >= 3.3 + 0.0

    def test_missing_specs_skip_rule(self) -> None:
        assert check_interval_constraints(_intent()).feasible
        assert check_interval_constraints(_intent(electrical=None)).feasible


class TestThermalBudgetAllocation:
    def test_within_budget_passes_and_propagates_remainder(self) -> None:
        intent = _intent(
            electrical=ElectricalConstraints(
                power_budget_mw=2000.0,
                output_voltage_compliance=VoltageSpec(typ_v=3.3, raw_text="3.3V"),
                output_current=CurrentSpec(max_ma=300, raw_text="300mA"),
            )
        )
        result = check_interval_constraints(intent)
        assert result.feasible
        assert result.derived["required_rail_power_mw"] == pytest.approx(990.0)
        assert result.derived["remaining_power_budget_mw"] == pytest.approx(1010.0)

    def test_over_budget_detected(self) -> None:
        """3.3V * 500mA = 1650mW rail exceeds a 1000mW budget."""
        intent = _intent(
            electrical=ElectricalConstraints(
                power_budget_mw=1000.0,
                output_voltage_compliance=VoltageSpec(typ_v=3.3, raw_text="3.3V"),
                output_current=CurrentSpec(max_ma=500, raw_text="500mA"),
            )
        )
        result = check_interval_constraints(intent)
        assert not result.feasible
        conflict = result.conflicts[0]
        assert conflict.severity == "CRITICAL"
        assert "1000" in conflict.constraint_a
        assert "1650" in conflict.constraint_b

    def test_no_budget_skips_rule(self) -> None:
        intent = _intent(
            electrical=ElectricalConstraints(
                output_voltage_compliance=VoltageSpec(typ_v=3.3, raw_text="3.3V"),
                output_current=CurrentSpec(max_ma=500, raw_text="500mA"),
            )
        )
        assert check_interval_constraints(intent).feasible


class TestAssertInterfaceFeasible:
    def test_raises_with_named_conflicts(self) -> None:
        intent = _intent(
            electrical=ElectricalConstraints(
                supply_voltage=VoltageSpec(max_v=3.5, raw_text="3.5V"),
                output_voltage_compliance=VoltageSpec(max_v=3.3, raw_text="3.3V"),
            )
        )
        with pytest.raises(ConstraintConflictError) as exc_info:
            assert_interval_feasible(intent)
        assert len(exc_info.value.conflicts) == 1
        assert "Infeasible constraint set" in str(exc_info.value)

    def test_feasible_returns_result(self) -> None:
        result = assert_interval_feasible(_intent())
        assert result.feasible


class TestPipelineWiring:
    """Solver runs in run_intent_pipeline after Stage 2.5, before generate_bom."""

    @patch("src.intent.pipeline.persist_design_constraints")
    @patch("src.intent.pipeline.generate_bom")
    @patch("src.intent.pipeline._run_retrieval", return_value=None)
    @patch("src.intent.pipeline._run_stage2", side_effect=lambda i, c: i)
    @patch("src.intent.pipeline.parse_intent")
    def test_conflict_halts_before_generate_bom(
        self, mock_parse, mock_stage2, mock_retrieval, mock_generate, mock_persist
    ) -> None:
        from src.intent.pipeline import run_intent_pipeline

        mock_parse.return_value = _intent(
            electrical=ElectricalConstraints(
                supply_voltage=VoltageSpec(max_v=3.5, raw_text="3.5V"),
                output_voltage_compliance=VoltageSpec(max_v=3.3, raw_text="3.3V"),
            )
        )
        intent, bom, _ = run_intent_pipeline("prompt", MagicMock(), MagicMock())

        mock_generate.assert_not_called()
        assert bom.review_required is True
        assert any("CRITICAL" in flag for flag in bom.review_flags)
        mock_persist.assert_called_once()  # constraints persisted even on halt

    @patch("src.intent.pipeline.enqueue_bom")
    @patch("src.intent.pipeline.persist_design_constraints")
    @patch("src.intent.pipeline.validate_bom")
    @patch("src.intent.pipeline.generate_bom")
    @patch("src.intent.pipeline.query_graph")
    @patch("src.intent.pipeline._run_retrieval", return_value=None)
    @patch("src.intent.pipeline._run_stage2", side_effect=lambda i, c: i)
    @patch("src.intent.pipeline.parse_intent")
    def test_feasible_path_persists_constraints(
        self, mock_parse, mock_stage2, mock_retrieval, mock_query,
        mock_generate, mock_validate, mock_persist, mock_enqueue
    ) -> None:
        from src.intent.pipeline import run_intent_pipeline

        mock_parse.return_value = _intent()
        validated = MagicMock()
        validated.review_required = False
        validated.design_id = "design-123"
        mock_validate.return_value = validated

        _, bom, _ = run_intent_pipeline("prompt", MagicMock(), MagicMock())

        mock_generate.assert_called_once()
        mock_persist.assert_called_once()
        assert mock_persist.call_args[0][1] == "design-123"


class TestCandidatesHook:
    """Solver pre-check at the top of generate_bom_candidates (future path)."""

    def test_conflict_raises_before_sampling(self) -> None:
        from src.bom.candidates import generate_bom_candidates

        intent = _intent(
            electrical=ElectricalConstraints(
                supply_voltage=VoltageSpec(max_v=3.5, raw_text="3.5V"),
                output_voltage_compliance=VoltageSpec(max_v=3.3, raw_text="3.3V"),
            )
        )
        with patch("src.bom.candidates.generate_bom") as mock_generate:
            with pytest.raises(ConstraintConflictError):
                generate_bom_candidates(MagicMock(), intent, MagicMock())
            mock_generate.assert_not_called()
