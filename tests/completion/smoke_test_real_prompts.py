#!/usr/bin/env python3
"""Standalone smoke test: Stage 2 completion engine on real DRDO scientist prompts.

Run from open_forge root:
    python tests/completion/smoke_test_real_prompts.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.completion.engine import run_completion_engine
from src.completion.schemas import (
    DangerousAssumption,
    QuantifiedSpec,
    RequirementCompletionResult,
)
from src.schemas.common import Ambiguity, ImpliedRequirement, TopologyGuess
from src.schemas.intent import (
    ComponentPreference,
    DesignMethodology,
    ElectricalConstraints,
    ImprovedIntentDict,
    NoiseSpec,
    PerformanceRequirements,
    ProtectionRequirement,
    StabilitySpec,
    ThermalConstraints,
)

PROMPT_1_LLM_RESULT = RequirementCompletionResult(
    implied_requirements=[
        ImpliedRequirement(
            requirement="Precision voltage reference required for current setpoint",
            component_implication="precision_voltage_reference",
            reasoning="Libbrecht-Hall uses voltage reference to set output current. Reference accuracy = output accuracy.",
            confidence=0.98,
            source_constraint="libbrecht hall design + highly stable",
            priority="CRITICAL",
        ),
        ImpliedRequirement(
            requirement="Low-noise LDO for op-amp analog supply rail",
            component_implication="low_noise_ldo",
            reasoning="Supply noise on op-amp VCC appears at output via PSRR. Requires <10nV/rtHz LDO.",
            confidence=0.95,
            source_constraint="ultra low noise + zero drift opamps",
            priority="CRITICAL",
        ),
        ImpliedRequirement(
            requirement="Kelvin (4-wire) connection on sense resistor",
            component_implication="pcb_layout_constraint",
            reasoning="At 100mA, 1mΩ lead resistance = 100µV error. Kelvin sensing eliminates this.",
            confidence=0.97,
            source_constraint="ultra precision resistors + 100mA current range",
            priority="CRITICAL",
        ),
        ImpliedRequirement(
            requirement="Negative voltage rail generation from single DC input",
            component_implication="negative_rail_converter",
            reasoning="Zero-drift op-amps require bipolar supply. Single DC input requires inverting charge pump.",
            confidence=0.92,
            source_constraint="zero drift opamps + single dc input",
            priority="CRITICAL",
        ),
        ImpliedRequirement(
            requirement="Guard ring around sense resistor and op-amp input nodes",
            component_implication="pcb_layout_constraint",
            reasoning="PCB surface leakage can exceed sub-pA/rtHz noise floor without guard rings.",
            confidence=0.85,
            source_constraint="ultra low noise",
            priority="HIGH",
        ),
        ImpliedRequirement(
            requirement="Compensation capacitor network for loop stability",
            component_implication="passive_compensation_network",
            reasoning="High-gain feedback loop is conditionally stable without compensation.",
            confidence=0.94,
            source_constraint="libbrecht hall design",
            priority="HIGH",
        ),
    ],
    quantified_specs=[
        QuantifiedSpec(
            original_text="ultra low noise",
            quantified_value="< 1",
            unit="pA/rtHz at 1kHz",
            reasoning="Published Libbrecht-Hall implementations achieve 0.1-1 pA/rtHz.",
            confidence=0.75,
        ),
    ],
    missing_critical_specs=[
        "Output compliance voltage not specified",
        "Operating temperature range not specified",
        "Supply voltage level not specified",
        "Target current noise floor not specified quantitatively",
        "Current adjustment resolution not specified",
        "Load impedance range not specified",
    ],
    dangerous_assumptions=[
        DangerousAssumption(
            field="operating_environment",
            assumed_value="laboratory",
            reasoning="Libbrecht-Hall is predominantly used in AMO physics labs. No environment stated.",
            confidence=0.80,
        ),
        DangerousAssumption(
            field="supply_voltage",
            assumed_value="15V-24V",
            reasoning="100mA output with op-amp supply generation implies minimum ~12V.",
            confidence=0.65,
        ),
    ],
    contradictions=[],
)

EMPTY_LLM_RESULT = RequirementCompletionResult()


def _domain_knowledge_dir() -> Path:
    return ROOT / "data" / "domain_knowledge"


def _build_prompt_1_intent() -> ImprovedIntentDict:
    return ImprovedIntentDict(
        goal="current_source",
        application="precision_measurement",
        design_methodology=DesignMethodology.MIXED_SIGNAL,
        board_type="double_sided_SMD",
        raw_prompt=(
            "Design a Libbrecht-Hall precision current source. "
            "Output: 0-100mA, adjustable using a potentiometer. "
            "Ultra low noise, highly stable. "
            "Use zero drift opamps and ultra precision resistors. "
            "Single DC input, generate all required polarities."
        ),
        goal_topologies=[
            TopologyGuess(
                name="libbrecht_hall",
                confidence=0.95,
                evidence=["libbrecht hall", "precision current source"],
            ),
        ],
        component_preferences=[
            ComponentPreference(
                component_type="op_amp",
                required_attribute="zero_drift",
            ),
            ComponentPreference(
                component_type="resistor",
                required_attribute="ultra_precision",
            ),
        ],
        electrical=ElectricalConstraints(
            supply_topology="single_dc",
        ),
        protection_requirements=[
            ProtectionRequirement(
                kind="reverse_polarity",
                raw_text="reverse polarity protection",
            ),
        ],
        performance=PerformanceRequirements(
            noise=NoiseSpec(raw_text="ultra low noise"),
            stability=StabilitySpec(raw_text="highly stable"),
            output_current_ma=100.0,
            output_current_range=(0.0, 100.0),
            adjustability="potentiometer",
        ),
    )


def _build_prompt_2_intent() -> ImprovedIntentDict:
    return ImprovedIntentDict(
        goal="current_source",
        application="rf_test_equipment",
        design_methodology=DesignMethodology.MIXED_SIGNAL,
        board_type="double_sided_SMD",
        raw_prompt=(
            "Design an adjustable current source with VCO bias tee and USB-C power input. "
            "Current range 0-500mA, USB-C PD negotiation for supply, "
            "integrated bias tee for VCO RF port."
        ),
        goal_topologies=[
            TopologyGuess(
                name="libbrecht_hall",
                confidence=0.65,
                evidence=["adjustable current source"],
            ),
            TopologyGuess(
                name="bias_tee",
                confidence=0.80,
                evidence=["bias tee", "VCO RF port"],
            ),
        ],
        electrical=ElectricalConstraints(
            supply_topology="usb_c_pd",
        ),
    )


def _mock_llm_response(system_prompt, intent, config, output_schema):
    if intent.application == "precision_measurement":
        return PROMPT_1_LLM_RESULT
    return EMPTY_LLM_RESULT


def _record(results: list[tuple[str, bool, str | None]], label: str, passed: bool, reason: str = "") -> None:
    results.append((label, passed, reason or None))
    if passed:
        print(f"PASS: {label}")
    else:
        suffix = f" — {reason}" if reason else ""
        print(f"FAIL: {label}{suffix}")


def _assert(
    results: list[tuple[str, bool, str | None]],
    condition: bool,
    label: str,
    fail_reason: str = "",
) -> None:
    _record(results, label, bool(condition), fail_reason if not condition else "")


def _run_prompt_1_assertions(
    intent_1: ImprovedIntentDict,
    result_1: ImprovedIntentDict,
    results: list[tuple[str, bool, str | None]],
) -> None:
    # ASSERTION 1: AXIOM LOADING
    # Prove the axiom loader actually ran by inspecting the system prompt
    # that was built. We do this by patching build_system_prompt to capture
    # its return value, then re-running for a fresh intent.
    # Simpler approach: check that axiom_loader returns results directly.
    import src.completion.engine as engine_module
    from src.completion.axiom_loader import load_axioms_for_intent

    data_dir = Path(engine_module.__file__).parent.parent.parent / "data" / "domain_knowledge"
    loaded_axioms = load_axioms_for_intent(intent_1, data_dir)

    _assert(
        results,
        len(loaded_axioms) >= 5,
        "AXIOM LOADING",
        f"Expected >=5 axioms from libbrecht_hall.yaml, got {len(loaded_axioms)}",
    )

    inferred_ok = all(
        r.confidence >= 0.80
        for r in result_1.implied_requirements
        if r.requirement in result_1.inferred_constraints
    )
    _record(
        results,
        "All inferred_constraints have confidence >= 0.80",
        inferred_ok,
    )

    below_threshold = [
        req
        for req in result_1.inferred_constraints
        if next(
            (r.confidence for r in result_1.implied_requirements if r.requirement == req),
            1.0,
        )
        < 0.80
    ]
    _record(
        results,
        "No requirement below 0.80 confidence in inferred_constraints",
        not below_threshold,
        f"found {below_threshold!r}" if below_threshold else "",
    )

    blocking_ambiguities = [a for a in result_1.ambiguities if a.blocking]
    env_ambiguity = next(
        (a for a in blocking_ambiguities if a.field == "operating_environment"),
        None,
    )
    _record(
        results,
        "operating_environment dangerous assumption promoted to blocking Ambiguity",
        env_ambiguity is not None,
    )

    supply_ambiguity = next(
        (a for a in blocking_ambiguities if a.field == "supply_voltage"),
        None,
    )
    _record(
        results,
        "supply_voltage dangerous assumption promoted to blocking Ambiguity",
        supply_ambiguity is not None,
    )

    _record(
        results,
        "clarification_required=True when dangerous assumptions present",
        result_1.clarification_required is True,
    )

    _record(
        results,
        "At least 6 missing critical specs identified",
        len(result_1.missing_critical_specs) >= 6,
        f"got {len(result_1.missing_critical_specs)}",
    )

    critical_contradictions = [
        c for c in result_1.contradictions_detected if "negative rail" in c.lower()
    ]
    _record(
        results,
        "No spurious negative rail contradiction (axiom already covers it)",
        len(critical_contradictions) == 0,
        f"found {critical_contradictions!r}" if critical_contradictions else "",
    )

    bypass_warnings = [
        c
        for c in result_1.contradictions_detected
        if "bypass" in c.lower() or "decoupling" in c.lower()
    ]
    _record(
        results,
        "Bypass capacitor warning fired (low_noise_ldo present, no bypass inferred)",
        len(bypass_warnings) >= 1,
        f"got {len(bypass_warnings)} bypass/decoupling warnings",
    )


def _run_prompt_2_assertions(
    intent_2: ImprovedIntentDict,
    intent_low: ImprovedIntentDict,
    results: list[tuple[str, bool, str | None]],
) -> None:
    import io
    import logging

    import src.completion.engine as engine_module
    from src.completion.axiom_loader import load_axioms_for_intent

    data_dir = Path(engine_module.__file__).parent.parent.parent / "data" / "domain_knowledge"

    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setLevel(logging.WARNING)
    axiom_logger = logging.getLogger("src.completion.axiom_loader")
    axiom_logger.setLevel(logging.WARNING)
    axiom_logger.addHandler(handler)

    loaded_axioms_2 = load_axioms_for_intent(intent_2, data_dir)

    axiom_logger.removeHandler(handler)
    log_output = log_stream.getvalue()

    _assert(
        results,
        "bias_tee" in log_output,
        "MULTI-TOPOLOGY: MISSING YAML WARNED",
        "Expected WARNING for missing bias_tee.yaml. Log output: " + log_output,
    )
    _assert(
        results,
        len(loaded_axioms_2) >= 2,
        "MULTI-TOPOLOGY: PRESENT YAML LOADED",
        f"Expected libbrecht_hall axioms still loaded, got {len(loaded_axioms_2)}",
    )

    loaded_axioms_low = load_axioms_for_intent(intent_low, data_dir)

    _assert(
        results,
        len(loaded_axioms_low) == 0,
        "BELOW-THRESHOLD TOPOLOGY EXCLUDED",
        f"Expected 0 axioms for confidence=0.5, got {len(loaded_axioms_low)}",
    )


def main() -> int:
    config = SimpleNamespace(domain_knowledge_dir=_domain_knowledge_dir())
    results: list[tuple[str, bool, str | None]] = []

    intent_1 = _build_prompt_1_intent()
    intent_2 = _build_prompt_2_intent()
    intent_low = ImprovedIntentDict(
        goal="test",
        application="lab",
        design_methodology=DesignMethodology.MIXED_SIGNAL,
        board_type="single_sided_SMD",
        raw_prompt="test",
        goal_topologies=[
            TopologyGuess(name="libbrecht_hall", confidence=0.5, evidence=[]),
        ],
    )

    with patch("src.completion.engine.call_llm_with_instructor", side_effect=_mock_llm_response):
        result_1 = run_completion_engine(intent_1, config)
        _run_prompt_1_assertions(intent_1, result_1, results)

        run_completion_engine(intent_2, config)
        run_completion_engine(intent_low, config)
        _run_prompt_2_assertions(intent_2, intent_low, results)

    prompt_1_passed = sum(1 for _, ok, _ in results[:9] if ok)
    prompt_2_passed = sum(1 for _, ok, _ in results[9:] if ok)
    total_passed = sum(1 for _, ok, _ in results if ok)
    failed_labels = [label for label, ok, _ in results if not ok]

    print()
    print("================================")
    print("SMOKE TEST RESULTS")
    print("================================")
    print(f"Prompt 1 (Libbrecht-Hall): {prompt_1_passed}/9 assertions passed")
    print(f"Prompt 2 (VCO Bias Tee):   {prompt_2_passed}/3 assertions passed")
    print(f"Total: {total_passed}/12")
    print("================================")
    if total_passed == 12:
        print("PASS")
    else:
        print(f"FAIL — failed assertions: {failed_labels}")

    return 0 if total_passed == 12 else 1


if __name__ == "__main__":
    raise SystemExit(main())
