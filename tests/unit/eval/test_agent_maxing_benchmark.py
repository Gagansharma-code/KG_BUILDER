"""Smoke test for eval/benchmarks/agent_maxing_benchmark.py.

Fully mocked: propose_netlist_llm, run_self_improving_synthesis, and
verify_schematic never touch a real model, GPU, or the model registry.
Must run in plain CI — the real (unmocked) script requires the
weak_netlist_proposer weights and is run manually, not in this suite.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from eval.benchmarks.agent_maxing_benchmark import (
    AGENT_MAXING_TASKS,
    _FIXTURES,
    _fixture_for,
    generate_comparison_report,
    run_comparison,
)
from eval.benchmarks.task_schema import BenchmarkTask


def _proposal(netlist: object | None = None) -> MagicMock:
    p = MagicMock()
    p.netlist = netlist if netlist is not None else []
    return p


def _verification(score: float) -> MagicMock:
    v = MagicMock()
    v.score = score
    v.critical_violations = []
    return v


def _self_improvement_result(final_score: float) -> MagicMock:
    r = MagicMock()
    r.final_score = final_score
    return r


def _patched(baseline_score: float, treatment_score: float) -> tuple[object, object, object]:
    return (
        patch(
            "eval.benchmarks.agent_maxing_benchmark.propose_netlist_llm",
            return_value=_proposal(),
        ),
        patch(
            "eval.benchmarks.agent_maxing_benchmark.verify_schematic",
            return_value=_verification(baseline_score),
        ),
        patch(
            "eval.benchmarks.agent_maxing_benchmark.run_self_improving_synthesis",
            return_value=_self_improvement_result(treatment_score),
        ),
    )


# ── Fixture registry ─────────────────────────────────────────────────────────

def test_all_agentmax_tasks_have_registered_fixtures() -> None:
    assert len(AGENT_MAXING_TASKS) >= 7
    assert set(_FIXTURES) == {t.task_id for t in AGENT_MAXING_TASKS}


def test_new_fixtures_build_without_error() -> None:
    """AGENTMAX_004–007 must construct ValidatedBOM + datasheets hand-built."""
    for task_id in ("AGENTMAX_004", "AGENTMAX_005", "AGENTMAX_006", "AGENTMAX_007"):
        task = next(t for t in AGENT_MAXING_TASKS if t.task_id == task_id)
        bom, datasheets = _fixture_for(task)
        assert bom.design_id
        assert len(bom.components) >= 1
        assert len(datasheets) >= 1
        parts = {c.specific_part for c in bom.components}
        ds_ids = {d.component_id for d in datasheets}
        assert parts <= ds_ids


# ── run_comparison ────────────────────────────────────────────────────────────

def test_run_comparison_produces_two_reports() -> None:
    tasks = AGENT_MAXING_TASKS[:2]  # 2 tasks is enough for a smoke test

    p1, p2, p3 = _patched(baseline_score=0.4, treatment_score=0.9)
    with p1, p2, p3:
        baseline, treatment = run_comparison(config=MagicMock(), tasks=tasks)

    assert baseline.tasks_run == 2
    assert treatment.tasks_run == 2
    assert baseline.mean_erc_score == 0.4
    assert treatment.mean_erc_score == 0.9
    assert baseline.pipeline_label == "weak_model_alone"
    assert treatment.pipeline_label == "weak_model_plus_self_improvement_loop"


def test_treatment_beats_baseline_on_mocked_scores() -> None:
    """Sanity check on the comparison itself, not a claim about the real
    model — real numbers come from an actual GPU run of main()."""
    tasks = AGENT_MAXING_TASKS[:1]
    p1, p2, p3 = _patched(baseline_score=0.35, treatment_score=0.92)
    with p1, p2, p3:
        baseline, treatment = run_comparison(config=MagicMock(), tasks=tasks)

    assert treatment.mean_erc_score > baseline.mean_erc_score


def test_run_comparison_covers_expanded_fixture_set() -> None:
    """Mocked full-suite run — ensures AGENTMAX_004+ are wired into the harness."""
    p1, p2, p3 = _patched(baseline_score=0.5, treatment_score=0.7)
    with p1, p2, p3:
        baseline, treatment = run_comparison(
            config=MagicMock(), tasks=AGENT_MAXING_TASKS,
        )

    assert baseline.tasks_run == len(AGENT_MAXING_TASKS)
    assert treatment.tasks_run == len(AGENT_MAXING_TASKS)
    assert {r.task_id for r in baseline.task_results} == {
        t.task_id for t in AGENT_MAXING_TASKS
    }


# ── generate_comparison_report ───────────────────────────────────────────────

def test_generate_comparison_report_contains_expected_content(tmp_path) -> None:
    tasks = AGENT_MAXING_TASKS[:1]
    p1, p2, p3 = _patched(baseline_score=0.30, treatment_score=0.95)
    with p1, p2, p3:
        baseline, treatment = run_comparison(config=MagicMock(), tasks=tasks)

    output = tmp_path / "report.md"
    markdown = generate_comparison_report(baseline, treatment, output_path=output)

    assert output.exists()
    assert "Agent Maxing Benchmark" in markdown
    assert "AGENTMAX_001" in markdown
    assert "0.3000" in markdown
    assert "0.9500" in markdown
    assert "Baseline score" in markdown
    assert "Treatment score" in markdown


def test_generate_comparison_report_without_output_path_does_not_write_file() -> None:
    tasks = AGENT_MAXING_TASKS[:1]
    p1, p2, p3 = _patched(baseline_score=0.5, treatment_score=0.6)
    with p1, p2, p3:
        baseline, treatment = run_comparison(config=MagicMock(), tasks=tasks)

    markdown = generate_comparison_report(baseline, treatment, output_path=None)
    assert isinstance(markdown, str)
    assert len(markdown) > 0


# ── Never crashes on a missing fixture ──────────────────────────────────────

def test_unregistered_task_id_fails_gracefully_via_runner() -> None:
    bogus_task = BenchmarkTask(
        task_id="AGENTMAX_999", prompt="no fixture registered", difficulty="simple",
    )
    p1, p2, p3 = _patched(baseline_score=1.0, treatment_score=1.0)
    with p1, p2, p3:
        baseline, _ = run_comparison(config=MagicMock(), tasks=[bogus_task])

    # _fixture_for() raises KeyError before ever calling the mocked
    # collaborators; eval.benchmarks.runner._run_single_attempt() catches
    # it and records a failed TaskResult rather than propagating — this
    # asserts that "never raises" contract holds through the benchmark
    # script too, not just inside src/schematic/.
    assert baseline.tasks_run == 1
    assert baseline.task_results[0].passed is False
    assert baseline.task_results[0].error is not None
