"""Gate tests for ConditionScope and condition-scoped constraint wiring."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from src.knowledge_graph import KnowledgeGraph
from src.knowledge_graph.backends.neo4j_backend import _node_props
from src.knowledge_graph.constraints import persist_design_constraints
from src.intent.interval_solver import check_interval_constraints
from src.schemas.common import ConditionScope, NoiseSpec
from src.schemas.intent import (
    DesignMethodology,
    FrequencySpec,
    ImprovedIntentDict,
    PerformanceRequirements,
)


class TestConditionScopeModel:
    def test_condition_scope_replaces_measurement_condition(self) -> None:
        assert "measurement_condition" not in NoiseSpec.model_fields
        assert "condition" in NoiseSpec.model_fields

        spec = NoiseSpec(
            target_value=50.0,
            unit="nV/√Hz",
            condition=ConditionScope(
                parameter="frequency_hz",
                at=1000.0,
                raw_text="at 1 kHz",
            ),
            raw_text="noise < 50 nV/√Hz at 1 kHz",
        )
        assert spec.condition is not None
        assert spec.condition.parameter == "frequency_hz"
        assert spec.condition.at == pytest.approx(1000.0)


class TestFrequencySpecRange:
    def test_frequency_spec_range_support(self) -> None:
        spec = FrequencySpec(min_hz=10.0, max_hz=100_000.0)
        assert spec.value is None
        assert spec.min_hz == pytest.approx(10.0)
        assert spec.max_hz == pytest.approx(100_000.0)

    def test_frequency_spec_range_rejects_inverted_bounds(self) -> None:
        with pytest.raises(ValidationError):
            FrequencySpec(min_hz=100_000.0, max_hz=10.0)

    def test_frequency_spec_rejects_value_and_range_together(self) -> None:
        with pytest.raises(ValidationError, match="cannot set value together"):
            FrequencySpec(value=10.0, unit="Hz", min_hz=10.0, max_hz=100_000.0)

    def test_frequency_spec_point_only_still_valid(self) -> None:
        spec = FrequencySpec(value=2.4, unit="GHz")
        assert spec.value == pytest.approx(2.4)
        assert spec.unit == "GHz"
        assert spec.min_hz is None
        assert spec.max_hz is None

    def test_frequency_spec_range_only_still_valid(self) -> None:
        spec = FrequencySpec(min_hz=10.0, max_hz=100_000.0)
        assert spec.value is None
        assert spec.min_hz == pytest.approx(10.0)
        assert spec.max_hz == pytest.approx(100_000.0)


class TestConditionScalarPromotion:
    def test_condition_promoted_as_scalar_on_constraint_node(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        graph = KnowledgeGraph()
        intent = ImprovedIntentDict(
            goal="instrumentation_amplifier",
            application="sensor",
            design_methodology=DesignMethodology.MIXED_SIGNAL,
            board_type="double_sided_SMD",
            raw_prompt="noise at 1 kHz",
            performance=PerformanceRequirements(
                noise=NoiseSpec(
                    target_value=50.0,
                    unit="nV/√Hz",
                    condition=ConditionScope(
                        parameter="frequency_hz",
                        at=1000.0,
                        raw_text="at 1 kHz",
                    ),
                    raw_text="noise < 50 nV/√Hz at 1 kHz",
                ),
            ),
        )
        nodes = persist_design_constraints(intent, "design-condition", graph)
        performance = next(
            n for n in nodes if n.properties.get("kind") == "performance"
        )

        assert performance.properties["condition_parameter"] == "frequency_hz"
        assert performance.properties["condition_at"] == pytest.approx(1000.0)
        assert performance.properties["spec"]["noise"]["condition"]["at"] == pytest.approx(
            1000.0
        )

        driver = MagicMock()
        session_cm = MagicMock()
        session = MagicMock()
        session_cm.__enter__.return_value = session
        driver.session.return_value = session_cm
        module = ModuleType("neo4j")
        module.GraphDatabase = MagicMock(driver=MagicMock(return_value=driver))
        monkeypatch.setitem(sys.modules, "neo4j", module)

        neo4j_props = _node_props(performance)
        assert neo4j_props["condition_parameter"] == "frequency_hz"
        assert neo4j_props["condition_at"] == pytest.approx(1000.0)


def _intent_with_noise_pair(
    requirement: NoiseSpec,
    available: NoiseSpec,
) -> ImprovedIntentDict:
    return ImprovedIntentDict(
        goal="instrumentation_amplifier",
        application="sensor",
        design_methodology=DesignMethodology.MIXED_SIGNAL,
        board_type="double_sided_SMD",
        raw_prompt="noise check",
        performance=PerformanceRequirements(
            noise=requirement,
            component_noise_floor=available,
        ),
    )


class TestIntervalSolverConditionGuards:
    def test_interval_solver_skips_mismatched_condition_comparison(self) -> None:
        requirement = NoiseSpec(
            target_value=50.0,
            unit="nV/√Hz",
            condition=ConditionScope(
                parameter="frequency_hz",
                at=1000.0,
                raw_text="at 1 kHz",
            ),
            raw_text="requirement",
        )
        available = NoiseSpec(
            target_value=80.0,
            unit="nV/√Hz",
            raw_text="datasheet typical",
        )
        result = check_interval_constraints(_intent_with_noise_pair(requirement, available))

        assert result.feasible
        assert result.derived.get("noise_comparison_skipped") == 1.0
        assert not result.conflicts

    def test_interval_solver_still_compares_matching_conditions(self) -> None:
        condition = ConditionScope(
            parameter="frequency_hz",
            at=1000.0,
            raw_text="at 1 kHz",
        )
        requirement = NoiseSpec(
            target_value=50.0,
            unit="nV/√Hz",
            condition=condition,
            raw_text="requirement",
        )
        available = NoiseSpec(
            target_value=80.0,
            unit="nV/√Hz",
            condition=condition,
            raw_text="component floor",
        )
        result = check_interval_constraints(_intent_with_noise_pair(requirement, available))

        assert not result.feasible
        assert result.conflicts[0].severity == "CRITICAL"
        assert "noise" in result.conflicts[0].description.lower()

        feasible_available = NoiseSpec(
            target_value=30.0,
            unit="nV/√Hz",
            condition=condition,
            raw_text="better component",
        )
        ok = check_interval_constraints(
            _intent_with_noise_pair(requirement, feasible_available)
        )
        assert ok.feasible
