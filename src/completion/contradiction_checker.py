"""Rule-based hard constraint checker for requirement completion."""

from __future__ import annotations

from src.completion.schemas import Contradiction, RequirementCompletionResult
from src.schemas.intent import ImprovedIntentDict


def run_rule_checker(
    intent: ImprovedIntentDict,
    result: RequirementCompletionResult,
) -> list[Contradiction]:
    """Run mechanical contradiction checks on intent + LLM implied requirements."""
    contradictions: list[Contradiction] = []

    # Rule 1 — Temperature range vs component rating
    if intent.thermal and intent.thermal.operating_temp_min_c is not None:
        temp = intent.thermal.operating_temp_min_c
        if temp < -40 and result.implied_requirements:
            contradictions.append(Contradiction(
                constraint_a=f"Operating temp min: {temp}°C",
                constraint_b="Commercial-grade components rated to -40°C minimum",
                description="Design may require industrial or military grade components",
                severity="WARNING",
                detected_by="rule_checker",
            ))

    # Rule 2 — Single supply + dual-rail op-amp without negative rail axiom
    supply_topology = (
        intent.electrical.supply_topology
        if intent.electrical
        else None
    )
    has_zero_drift = any(
        r.component_implication == "zero_drift_op_amp"
        for r in result.implied_requirements
    )
    has_negative_rail = any(
        r.component_implication == "negative_rail_converter"
        for r in result.implied_requirements
    )
    if supply_topology == "single_dc" and has_zero_drift and not has_negative_rail:
        contradictions.append(Contradiction(
            constraint_a="single_dc supply topology",
            constraint_b="zero_drift_op_amp requires bipolar supply",
            description=(
                "No negative rail generation inferred — op-amp supply will be incorrect"
            ),
            severity="CRITICAL",
            detected_by="rule_checker",
        ))

    # Rule 3 — Noise floor vs bypass capacitor absence
    has_low_noise_ldo = any(
        r.component_implication == "low_noise_ldo"
        for r in result.implied_requirements
    )
    if has_low_noise_ldo:
        mentions_bypass = any(
            "bypass" in (r.requirement + " " + r.reasoning).lower()
            or "decoupling" in (r.requirement + " " + r.reasoning).lower()
            for r in result.implied_requirements
        )
        if not mentions_bypass:
            contradictions.append(Contradiction(
                constraint_a="low_noise_ldo implied",
                constraint_b="No bypass capacitor requirement inferred",
                description=(
                    "LDO output noise is only effective with proper bypass at the load"
                ),
                severity="WARNING",
                detected_by="rule_checker",
            ))

    # Rule 4 — Protection requirements without a resolvable functional block
    for requirement in getattr(intent, "protection_requirements", []) or []:
        contradictions.append(Contradiction(
            constraint_a=f"Protection required: {requirement.kind}",
            constraint_b="No matching functional_block in topology library",
            description=(
                f"Protection ask recorded from prompt ({requirement.raw_text!r}) "
                "but no topology-library block is available to satisfy it yet"
            ),
            severity="WARNING",
            suggested_resolution=(
                "Add a matching functional block to the topology library or "
                "revise the protection requirement"
            ),
            detected_by="rule_checker",
        ))

    return contradictions
