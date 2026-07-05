"""Embedded interval-constraint solver — deductive feasibility pre-check.

Catches algebraic constraint violations *before* BOM generation or the
search stack starts sampling, so infeasible designs fail loudly in
milliseconds instead of failing slowly via search.

Scope (deliberately fixed — this is NOT a general-purpose solver):
  Rule 1: Voltage/dropout chain propagation
          required V_in(min) = V_out(max) + dropout; conflict if the
          declared supply maximum cannot reach it.
  Rule 2: Thermal/power budget allocation across sibling rails
          conflict if the sum of per-rail power requirements exceeds the
          declared total power budget; otherwise the remaining budget is
          propagated in the result.

Why a new module (Section 0E determination, summarized):
  - constraint_inferrer.py maps application keywords → constraint *strings*;
    it has no numeric model and its output feeds IntentDict.inferred_constraints.
  - contradiction_checker.py runs *inside* the Stage 2 completion engine on
    (intent + LLM implied requirements) and returns advisory Contradictions;
    it cannot gate the pipeline after Stage 2.5 retrieval, which is where
    this check must sit.
  Both are reused where possible: this module emits the existing
  completion.schemas.Contradiction model (detected_by="rule_checker") so
  reporting is uniform, and raises ConstraintConflictError for the loud path.

Public API:
    check_interval_constraints(intent) -> IntervalCheckResult
    assert_interval_feasible(intent)   -> None | raises ConstraintConflictError
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from src.completion.schemas import Contradiction

if TYPE_CHECKING:
    from src.schemas.intent import ImprovedIntentDict

logger = logging.getLogger(__name__)

# Conservative default LDO dropout when the intent does not specify one.
DEFAULT_LDO_DROPOUT_V = 0.3

# Topology slugs for Rule 1 (voltage/dropout chain). Each set is explicit so
# future topologies do not silently inherit a default treatment.
# Slugs match goal_topology vocabulary elsewhere (parser, TOPOLOGY_TEMPLATES,
# confidence_scorer, retrieval topology_slugs).
_DROPOUT_TOPOLOGIES = frozenset({"ldo"})
_BUCK_LIKE_TOPOLOGIES = frozenset({"buck_converter"})
# Step-up / step-up-down: V_in vs V_out is not constrained by this rule.
# boost_converter steps up (V_out > V_in is normal); buck_boost can operate
# with V_in above, below, or equal to V_out — skip rather than invert.
_VOLTAGE_CHAIN_SKIP_TOPOLOGIES = frozenset({"boost_converter", "buck_boost"})


class ConstraintConflictError(Exception):
    """Raised when the interval solver proves the constraint set infeasible.

    Attributes:
        conflicts: The CRITICAL Contradiction objects that prove infeasibility.
    """

    def __init__(self, conflicts: list[Contradiction]):
        self.conflicts = conflicts
        lines = [
            f"- {c.constraint_a} vs {c.constraint_b}: {c.description}"
            for c in conflicts
        ]
        super().__init__(
            "Infeasible constraint set detected before BOM generation:\n"
            + "\n".join(lines)
        )


@dataclass
class IntervalCheckResult:
    """Outcome of the deductive feasibility check.

    conflicts: All detected contradictions (CRITICAL entries prove infeasibility).
    derived: Propagated bounds computed along the way, e.g.
             {"min_input_voltage_v": 3.5, "remaining_power_budget_mw": 120.0}.
    """

    conflicts: list[Contradiction] = field(default_factory=list)
    derived: dict[str, float] = field(default_factory=dict)

    @property
    def feasible(self) -> bool:
        return not any(c.severity == "CRITICAL" for c in self.conflicts)


def _check_voltage_dropout_chain(
    intent: ImprovedIntentDict,
    result: IntervalCheckResult,
) -> None:
    """Rule 1: V_in(min required) = V_out(max) + dropout vs supply V_max."""
    electrical = getattr(intent, "electrical", None)
    if electrical is None:
        return

    supply = electrical.supply_voltage
    output = electrical.output_voltage_compliance
    if supply is None or output is None:
        return

    output_v = output.max_v if output.max_v is not None else output.typ_v
    if output_v is None:
        return

    topology = getattr(intent, "goal_topology", None)
    if topology in _VOLTAGE_CHAIN_SKIP_TOPOLOGIES:
        return
    if topology in _DROPOUT_TOPOLOGIES:
        dropout_v = DEFAULT_LDO_DROPOUT_V
    elif topology in _BUCK_LIKE_TOPOLOGIES:
        dropout_v = 0.0
    else:
        # Unknown or unlisted topology: Rule 1 does not apply.
        return

    required_min_input = round(output_v + dropout_v, 6)
    result.derived["min_input_voltage_v"] = required_min_input

    supply_max = supply.max_v if supply.max_v is not None else supply.typ_v
    if supply_max is None:
        return

    if supply_max < required_min_input:
        result.conflicts.append(
            Contradiction(
                constraint_a=(
                    f"Supply voltage max {supply_max}V "
                    f"(from '{supply.raw_text}')"
                ),
                constraint_b=(
                    f"Output {output_v}V + dropout {dropout_v}V "
                    f"requires input >= {required_min_input}V"
                ),
                description=(
                    "Voltage/dropout chain is infeasible: the declared supply "
                    "can never reach the minimum input the output requires"
                ),
                severity="CRITICAL",
                suggested_resolution=(
                    f"Raise supply above {required_min_input}V, lower the output "
                    "voltage, or switch to a boost/buck-boost topology"
                ),
                detected_by="rule_checker",
            )
        )


def _check_thermal_budget_allocation(
    intent: ImprovedIntentDict,
    result: IntervalCheckResult,
) -> None:
    """Rule 2: sum of per-rail power requirements vs total power budget."""
    electrical = getattr(intent, "electrical", None)
    if electrical is None:
        return

    budget_mw = electrical.power_budget_mw
    if budget_mw is None:
        return

    # Rail power requirements derivable by arithmetic from the intent:
    # primary output rail = V_out(typ|max) * I_out(max|typ).
    rails: list[tuple[str, float]] = []

    output_v_spec = electrical.output_voltage_compliance
    output_i_spec = electrical.output_current
    if output_v_spec is not None and output_i_spec is not None:
        v = output_v_spec.typ_v if output_v_spec.typ_v is not None else output_v_spec.max_v
        i_ma = output_i_spec.max_ma if output_i_spec.max_ma is not None else output_i_spec.typ_ma
        if v is not None and i_ma is not None:
            rails.append(("primary_output_rail", v * i_ma))  # V * mA = mW

    performance = getattr(intent, "performance", None)
    if performance is not None and performance.output_current_ma is not None:
        if not rails:  # avoid double counting the same rail
            v = None
            if output_v_spec is not None:
                v = output_v_spec.typ_v if output_v_spec.typ_v is not None else output_v_spec.max_v
            if v is not None:
                rails.append(("performance_output_rail", v * performance.output_current_ma))

    if not rails:
        return

    total_required_mw = sum(p for _, p in rails)
    remaining_mw = budget_mw - total_required_mw
    result.derived["required_rail_power_mw"] = total_required_mw
    result.derived["remaining_power_budget_mw"] = remaining_mw

    if total_required_mw > budget_mw:
        rail_desc = ", ".join(f"{name}={p:.0f}mW" for name, p in rails)
        result.conflicts.append(
            Contradiction(
                constraint_a=f"Total power budget {budget_mw:.0f}mW",
                constraint_b=(
                    f"Rail requirements sum to {total_required_mw:.0f}mW ({rail_desc})"
                ),
                description=(
                    "Thermal/power budget allocation is infeasible: rail power "
                    "requirements exceed the declared total budget by "
                    f"{total_required_mw - budget_mw:.0f}mW"
                ),
                severity="CRITICAL",
                suggested_resolution=(
                    "Raise the power budget, reduce output current, or lower "
                    "the rail voltage"
                ),
                detected_by="rule_checker",
            )
        )


def check_interval_constraints(intent: ImprovedIntentDict) -> IntervalCheckResult:
    """Run all scoped deductive checks. Never raises.

    Args:
        intent: The (Stage 2-completed) design intent.

    Returns:
        IntervalCheckResult with conflicts and derived bounds.
    """
    result = IntervalCheckResult()
    try:
        _check_voltage_dropout_chain(intent, result)
        _check_thermal_budget_allocation(intent, result)
    except Exception as exc:  # defensive: a solver bug must not kill the pipeline
        logger.error(f"Interval solver internal error (treated as no-conflict): {exc}")
    return result


def assert_interval_feasible(intent: ImprovedIntentDict) -> IntervalCheckResult:
    """Run checks and fail loudly on any CRITICAL conflict.

    Returns:
        The IntervalCheckResult when feasible.

    Raises:
        ConstraintConflictError: Listing exactly which constraints conflict
        and why, before any BOM generation or search sampling happens.
    """
    result = check_interval_constraints(intent)
    critical = [c for c in result.conflicts if c.severity == "CRITICAL"]
    if critical:
        raise ConstraintConflictError(critical)
    return result
