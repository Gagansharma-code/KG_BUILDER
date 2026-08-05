"""Idea 2 benchmark — weak model alone vs. weak model + self-improvement loop.

This is the AMD-submission deliverable described in plan.md §2.5: run a
small set of design tasks through (a) one weak-model attempt with no
retries and (b) run_self_improving_synthesis(), then report the score
delta. That delta table is the "one chart" the pitch deck promises.

Fixture scope (read before extending): ships with 7 hand-built, small
fixtures (AGENTMAX_001-007) — NOT the canonical 15-task suite in
eval/benchmarks/tasks.py. Those 15 tasks assume a full pipeline (intent
parsing -> KG BOM selection) this benchmark does not run; this benchmark
exercises propose_netlist_llm() / run_self_improving_synthesis() directly
against a fixed BOM + datasheets, a narrower and cheaper scope. Extend
_FIXTURES (and AGENT_MAXING_TASKS) with more entries as more get hand-built
— see plan.md §5 open question #2 for which of the 15 canonical tasks are
realistic to adapt.

Usage:
    python -m eval.benchmarks.agent_maxing_benchmark --output report.md

Requires the weak_netlist_proposer model weights to be present locally
(config/model_versions.yaml) — this is NOT a CI-safe script; it makes real
model calls. For CI, see tests/unit/eval/test_agent_maxing_benchmark.py,
which mocks propose_netlist_llm() end to end.
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from eval.benchmarks.task_schema import BenchmarkReport, BenchmarkTask
from src.config import Config, get_config
from src.schemas.datasheet import ComponentDatasheet, ExtractionMethod, PinDefinition, PinRole
from src.schemas.intent import BOMEntry, DesignMethodology, ImprovedIntentDict, ValidatedBOM
from src.schematic._ref_mapper import build_ref_map
from src.schematic.llm_netlist_proposer import propose_netlist_llm
from src.schematic.self_improvement_loop import run_self_improving_synthesis
from src.schematic.structural_verifier import verify_schematic

logger = logging.getLogger(__name__)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _intent(goal: str) -> ImprovedIntentDict:
    return ImprovedIntentDict(
        goal=goal,
        application="agent_maxing_benchmark",
        design_methodology=DesignMethodology.STANDARD_SMD,
        board_type="standard_SMD",
        raw_prompt=goal,
    )


def _pin(number: str, raw_name: str, role: Optional[PinRole]) -> PinDefinition:
    return PinDefinition(
        pin_number=number,
        raw_name=raw_name,
        normalized_function=raw_name,
        pin_role=role,
        normalization_confidence=0.9,
        pin_type="power",
    )


def _datasheet(component_id: str, pins: list[PinDefinition]) -> ComponentDatasheet:
    return ComponentDatasheet(
        component_id=component_id,
        manufacturer="Fixture",
        description="benchmark fixture",
        package="SOIC-8",
        source_pdf_hash="fixture",
        extraction_method=ExtractionMethod.MANUAL,
        extraction_confidence=1.0,
        created_at="2026-01-01T00:00:00Z",
        pins=pins,
    )


def _ldo_fixture() -> tuple[ValidatedBOM, list[ComponentDatasheet]]:
    ds = _datasheet("LDO1", [
        _pin("1", "VIN", PinRole.POWER_IN),
        _pin("2", "GND", PinRole.GROUND),
        _pin("3", "VOUT", PinRole.POWER_OUT),
    ])
    bom = ValidatedBOM(
        design_id="agentmax-ldo",
        intent=_intent("3.3V LDO linear voltage regulator"),
        components=[
            BOMEntry(ref="U1", component_type="ldo_regulator", specific_part="LDO1",
                     justification="fixture", source="fixture", confidence=0.9),
        ],
        total_confidence=0.9, review_required=False, created_at="2026-01-01T00:00:00Z",
    )
    return bom, [ds]


def _rc_lowpass_fixture() -> tuple[ValidatedBOM, list[ComponentDatasheet]]:
    ds_r = _datasheet("RES1", [_pin("1", "P1", None), _pin("2", "P2", None)])
    ds_c = _datasheet("CAP1", [_pin("1", "P1", None), _pin("2", "P2", None)])
    bom = ValidatedBOM(
        design_id="agentmax-rc",
        intent=_intent("RC low-pass filter, 1kHz cutoff"),
        components=[
            BOMEntry(ref="R1", component_type="resistor", specific_part="RES1",
                     justification="fixture", source="fixture", confidence=0.9),
            BOMEntry(ref="C1", component_type="capacitor", specific_part="CAP1",
                     justification="fixture", source="fixture", confidence=0.9),
        ],
        total_confidence=0.9, review_required=False, created_at="2026-01-01T00:00:00Z",
    )
    return bom, [ds_r, ds_c]


def _voltage_divider_fixture() -> tuple[ValidatedBOM, list[ComponentDatasheet]]:
    ds_r1 = _datasheet("RES1", [_pin("1", "P1", None), _pin("2", "P2", None)])
    ds_r2 = _datasheet("RES2", [_pin("1", "P1", None), _pin("2", "P2", None)])
    bom = ValidatedBOM(
        design_id="agentmax-divider",
        intent=_intent("5V to 3.3V resistive voltage divider"),
        components=[
            BOMEntry(ref="R1", component_type="resistor", specific_part="RES1",
                     justification="fixture", source="fixture", confidence=0.9),
            BOMEntry(ref="R2", component_type="resistor", specific_part="RES2",
                     justification="fixture", source="fixture", confidence=0.9),
        ],
        total_confidence=0.9, review_required=False, created_at="2026-01-01T00:00:00Z",
    )
    return bom, [ds_r1, ds_r2]


def _decoupling_caps_fixture() -> tuple[ValidatedBOM, list[ComponentDatasheet]]:
    """Adapted from TASK_005 — MCU decoupling network (two caps on 3.3V)."""
    ds_c1 = _datasheet("CAP100N", [_pin("1", "P1", None), _pin("2", "P2", None)])
    ds_c2 = _datasheet("CAP10U", [_pin("1", "P1", None), _pin("2", "P2", None)])
    bom = ValidatedBOM(
        design_id="agentmax-decoupling",
        intent=_intent("Decoupling capacitor network for a 3.3V microcontroller"),
        components=[
            BOMEntry(ref="C1", component_type="capacitor", specific_part="CAP100N",
                     justification="fixture", source="fixture", confidence=0.9),
            BOMEntry(ref="C2", component_type="capacitor", specific_part="CAP10U",
                     justification="fixture", source="fixture", confidence=0.9),
        ],
        total_confidence=0.9, review_required=False, created_at="2026-01-01T00:00:00Z",
    )
    return bom, [ds_c1, ds_c2]


def _inverting_opamp_fixture() -> tuple[ValidatedBOM, list[ComponentDatasheet]]:
    """Adapted from TASK_002 — inverting op-amp with gain-setting resistors."""
    ds_amp = _datasheet("OPA1", [
        _pin("1", "IN-", PinRole.SIGNAL_IN),
        _pin("2", "IN+", PinRole.SIGNAL_IN),
        _pin("3", "VCC", PinRole.POWER_IN),
        _pin("4", "GND", PinRole.GROUND),
        _pin("5", "OUT", PinRole.SIGNAL_OUT),
    ])
    ds_rin = _datasheet("RES_IN", [_pin("1", "P1", None), _pin("2", "P2", None)])
    ds_rf = _datasheet("RES_FB", [_pin("1", "P1", None), _pin("2", "P2", None)])
    bom = ValidatedBOM(
        design_id="agentmax-opamp",
        intent=_intent("Inverting op-amp amplifier with gain of -10"),
        components=[
            BOMEntry(ref="U1", component_type="op_amp", specific_part="OPA1",
                     justification="fixture", source="fixture", confidence=0.9),
            BOMEntry(ref="R1", component_type="resistor", specific_part="RES_IN",
                     justification="fixture", source="fixture", confidence=0.9),
            BOMEntry(ref="R2", component_type="resistor", specific_part="RES_FB",
                     justification="fixture", source="fixture", confidence=0.9),
        ],
        total_confidence=0.9, review_required=False, created_at="2026-01-01T00:00:00Z",
    )
    return bom, [ds_amp, ds_rin, ds_rf]


def _ldo_crystal_fixture() -> tuple[ValidatedBOM, list[ComponentDatasheet]]:
    """Adapted from TASK_007 — 3.3V LDO plus a 16MHz crystal (no full MCU BOM)."""
    ds_ldo = _datasheet("LDO1", [
        _pin("1", "VIN", PinRole.POWER_IN),
        _pin("2", "GND", PinRole.GROUND),
        _pin("3", "VOUT", PinRole.POWER_OUT),
    ])
    ds_xtal = _datasheet("XTAL16", [
        _pin("1", "X1", PinRole.CLOCK),
        _pin("2", "X2", PinRole.CLOCK),
    ])
    ds_c = _datasheet("CAP_LOAD", [_pin("1", "P1", None), _pin("2", "P2", None)])
    bom = ValidatedBOM(
        design_id="agentmax-ldo-crystal",
        intent=_intent("3.3V LDO power supply with a 16MHz crystal oscillator"),
        components=[
            BOMEntry(ref="U1", component_type="ldo_regulator", specific_part="LDO1",
                     justification="fixture", source="fixture", confidence=0.9),
            BOMEntry(ref="Y1", component_type="crystal", specific_part="XTAL16",
                     justification="fixture", source="fixture", confidence=0.9),
            BOMEntry(ref="C1", component_type="capacitor", specific_part="CAP_LOAD",
                     justification="fixture", source="fixture", confidence=0.9),
        ],
        total_confidence=0.9, review_required=False, created_at="2026-01-01T00:00:00Z",
    )
    return bom, [ds_ldo, ds_xtal, ds_c]


def _led_current_limit_fixture() -> tuple[ValidatedBOM, list[ComponentDatasheet]]:
    """Simple LED + series resistor — different topology from 001–003 passives."""
    ds_led = _datasheet("LED1", [
        _pin("1", "A", PinRole.POWER_IN),
        _pin("2", "K", PinRole.GROUND),
    ])
    ds_r = _datasheet("RES_LED", [_pin("1", "P1", None), _pin("2", "P2", None)])
    bom = ValidatedBOM(
        design_id="agentmax-led",
        intent=_intent("LED indicator with series current-limiting resistor on 3.3V"),
        components=[
            BOMEntry(ref="D1", component_type="led", specific_part="LED1",
                     justification="fixture", source="fixture", confidence=0.9),
            BOMEntry(ref="R1", component_type="resistor", specific_part="RES_LED",
                     justification="fixture", source="fixture", confidence=0.9),
        ],
        total_confidence=0.9, review_required=False, created_at="2026-01-01T00:00:00Z",
    )
    return bom, [ds_led, ds_r]


_FIXTURES: dict[str, Callable[[], tuple[ValidatedBOM, list[ComponentDatasheet]]]] = {
    "AGENTMAX_001": _ldo_fixture,
    "AGENTMAX_002": _rc_lowpass_fixture,
    "AGENTMAX_003": _voltage_divider_fixture,
    "AGENTMAX_004": _decoupling_caps_fixture,
    "AGENTMAX_005": _inverting_opamp_fixture,
    "AGENTMAX_006": _ldo_crystal_fixture,
    "AGENTMAX_007": _led_current_limit_fixture,
}

AGENT_MAXING_TASKS: list[BenchmarkTask] = [
    BenchmarkTask(
        task_id="AGENTMAX_001",
        prompt="Design a 3.3V LDO linear voltage regulator",
        difficulty="simple",
        expected_component_types=["ldo_regulator"],
        min_erc_score=0.90,
        source="manual",
        notes="Idea 2 benchmark fixture — see agent_maxing_benchmark.py",
    ),
    BenchmarkTask(
        task_id="AGENTMAX_002",
        prompt="Design an RC low-pass filter with cutoff frequency of 1kHz",
        difficulty="simple",
        expected_component_types=["resistor", "capacitor"],
        min_erc_score=0.85,
        source="manual",
        notes="Idea 2 benchmark fixture — see agent_maxing_benchmark.py",
    ),
    BenchmarkTask(
        task_id="AGENTMAX_003",
        prompt="Design a voltage divider to step down 5V to 3.3V",
        difficulty="simple",
        expected_component_types=["resistor"],
        min_erc_score=0.85,
        source="manual",
        notes="Idea 2 benchmark fixture — see agent_maxing_benchmark.py",
    ),
    BenchmarkTask(
        task_id="AGENTMAX_004",
        prompt="Design the decoupling capacitor network for a 3.3V microcontroller",
        difficulty="simple",
        expected_component_types=["capacitor"],
        min_erc_score=0.85,
        source="manual",
        notes="Adapted from TASK_005 — hand-built BOM, no KG",
    ),
    BenchmarkTask(
        task_id="AGENTMAX_005",
        prompt="Design an inverting op-amp amplifier with gain of -10",
        difficulty="simple",
        expected_component_types=["op_amp", "resistor"],
        min_erc_score=0.80,
        source="manual",
        notes="Adapted from TASK_002 — hand-built BOM, no KG",
    ),
    BenchmarkTask(
        task_id="AGENTMAX_006",
        prompt="Design a 3.3V LDO with a 16MHz crystal oscillator section",
        difficulty="medium",
        expected_component_types=["ldo_regulator", "crystal", "capacitor"],
        expected_topologies=["ldo"],
        min_erc_score=0.80,
        source="manual",
        notes="Adapted from TASK_007 (LDO+crystal subset) — hand-built BOM, no KG",
    ),
    BenchmarkTask(
        task_id="AGENTMAX_007",
        prompt="Design an LED indicator with a series current-limiting resistor",
        difficulty="simple",
        expected_component_types=["led", "resistor"],
        min_erc_score=0.85,
        source="manual",
        notes="New fixture — distinct topology from AGENTMAX_001-003",
    ),
]


def _fixture_for(task: BenchmarkTask) -> tuple[ValidatedBOM, list[ComponentDatasheet]]:
    factory = _FIXTURES.get(task.task_id)
    if factory is None:
        raise KeyError(
            f"No fixture registered for task {task.task_id}. Add one to "
            f"_FIXTURES in eval/benchmarks/agent_maxing_benchmark.py."
        )
    return factory()


# ── Pipeline functions — match runner.PipelineFn exactly ────────────────────
# PipelineFn = Callable[[BenchmarkTask], tuple[float, list[str], list[str]]]

def make_baseline_pipeline_fn(
    config: "Config",
) -> Callable[[BenchmarkTask], tuple[float, list[str], list[str]]]:
    """Weak model, one attempt, no retries, no feedback. The 'before' arm."""

    def _run(task: BenchmarkTask) -> tuple[float, list[str], list[str]]:
        bom, datasheets = _fixture_for(task)
        ref_map = build_ref_map(bom, datasheets)
        proposal = propose_netlist_llm(bom, datasheets, ref_map, config, temperature=0.7)
        verification = verify_schematic(
            netlist=proposal.netlist,
            ref_map=ref_map,
            bom=bom,
            expected_topologies=task.expected_topologies or None,
        )
        component_types_found = [c.component_type for c in bom.components]
        return verification.score, component_types_found, []

    return _run


def make_treatment_pipeline_fn(
    config: "Config",
) -> Callable[[BenchmarkTask], tuple[float, list[str], list[str]]]:
    """Weak model + run_self_improving_synthesis(). The 'after' arm."""

    def _run(task: BenchmarkTask) -> tuple[float, list[str], list[str]]:
        bom, datasheets = _fixture_for(task)
        ref_map = build_ref_map(bom, datasheets)
        result = run_self_improving_synthesis(
            bom, datasheets, ref_map, config,
            expected_topologies=task.expected_topologies or None,
        )
        component_types_found = [c.component_type for c in bom.components]
        return result.final_score, component_types_found, []

    return _run


# ── Comparison run + report ──────────────────────────────────────────────────

def run_comparison(
    config: "Config",
    tasks: Optional[list[BenchmarkTask]] = None,
) -> tuple[BenchmarkReport, BenchmarkReport]:
    """Run both arms with n_attempts=1 — the self-improvement loop's own
    max_rounds IS the treatment arm's retrying; the baseline arm is
    deliberately a single shot for a clean before/after comparison.

    Returns (baseline_report, treatment_report).
    """
    from eval.benchmarks.runner import run_benchmark

    tasks = tasks if tasks is not None else AGENT_MAXING_TASKS

    baseline_report = run_benchmark(
        tasks, make_baseline_pipeline_fn(config),
        n_attempts=1, pipeline_label="weak_model_alone", stop_on_pass=False,
    )
    treatment_report = run_benchmark(
        tasks, make_treatment_pipeline_fn(config),
        n_attempts=1, pipeline_label="weak_model_plus_self_improvement_loop",
        stop_on_pass=False,
    )
    return baseline_report, treatment_report


def generate_comparison_report(
    baseline: BenchmarkReport,
    treatment: BenchmarkReport,
    output_path: Optional[Path] = None,
) -> str:
    """The AMD-submission chart, as a Markdown table."""
    baseline_by_task = {r.task_id: r for r in baseline.task_results}
    treatment_by_task = {r.task_id: r for r in treatment.task_results}

    lines = [
        "# Idea 2 — Agent Maxing Benchmark",
        "",
        "Weak model alone vs. weak model + verifier-scored self-improvement loop.",
        "",
        f"**Run timestamp:** {datetime.now(timezone.utc).isoformat()}  ",
        f"**Tasks:** {len(baseline_by_task)}  ",
        "",
        "## Summary",
        "",
        "| Metric | Weak model alone | + self-improvement loop | Delta |",
        "|---|---|---|---|",
        (
            f"| Mean score | {baseline.mean_erc_score:.4f} | "
            f"{treatment.mean_erc_score:.4f} | "
            f"{treatment.mean_erc_score - baseline.mean_erc_score:+.4f} |"
        ),
        (
            f"| Pass@1 | {baseline.pass_at_1 * 100:.1f}% | "
            f"{treatment.pass_at_1 * 100:.1f}% | "
            f"{(treatment.pass_at_1 - baseline.pass_at_1) * 100:+.1f}pp |"
        ),
        "",
        "## Per-task",
        "",
        "| Task | Baseline score | Treatment score | Delta |",
        "|---|---|---|---|",
    ]

    for task_id in sorted(baseline_by_task):
        b = baseline_by_task[task_id]
        t = treatment_by_task.get(task_id)
        t_score = t.erc_score if t is not None else float("nan")
        delta = (t_score - b.erc_score) if t is not None else float("nan")
        lines.append(f"| {task_id} | {b.erc_score:.4f} | {t_score:.4f} | {delta:+.4f} |")

    lines += ["", "---", "*Generated by eval/benchmarks/agent_maxing_benchmark.py*"]
    markdown = "\n".join(lines)

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")

    return markdown


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("agent_maxing_report.md"),
        help="Path to write the Markdown comparison report.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    config = get_config()

    baseline_report, treatment_report = run_comparison(config)
    markdown = generate_comparison_report(baseline_report, treatment_report, args.output)
    print(markdown)
    print(f"\nReport written to {args.output}")


if __name__ == "__main__":
    main()
