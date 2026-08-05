"""Gate tests for the weak-model self-improvement loop
(src/schematic/self_improvement_loop.py).

Style mirrors tests/unit/schematic/test_beam_search_escalation.py: every
collaborator (propose_netlist_llm, verify_schematic, polish_schematic,
run_beam_search) is patched at its reference inside self_improvement_loop.py,
scores are scripted via side_effect, no real model weights or GPU required.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.schematic.beam_search_escalation import BeamSearchResult
from src.schematic.sa_polisher import SAPolishResult, SA_TRIGGER_THRESHOLD
from src.schematic.self_improvement_loop import (
    SelfImprovementResult,
    run_self_improving_synthesis,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

BOM = MagicMock()
DATASHEETS: list[object] = []
REF_MAP: dict[str, object] = {}
CONFIG = MagicMock()


def _proposal(netlist: object | None = None) -> MagicMock:
    p = MagicMock()
    p.netlist = netlist if netlist is not None else []
    return p


def _verification(score: float, violation_count: int = 1) -> MagicMock:
    v = MagicMock()
    v.score = score
    v.critical_violations = [
        MagicMock(message=f"violation {i}") for i in range(violation_count)
    ]
    v.lowest_scoring_layer.return_value = None
    return v


_NOOP_SA = SAPolishResult(polished_netlist=[], initial_score=0.0, final_score=0.0)
_NOOP_BEAM = BeamSearchResult(
    best_netlist=[], best_score=0.0, initial_score=0.0,
)


def _patched(
    propose_side_effect: object | None = None,
    verify_side_effect: object | None = None,
    polish_return: SAPolishResult = _NOOP_SA,
    beam_return: BeamSearchResult = _NOOP_BEAM,
) -> tuple[object, object, object, object]:
    """Returns the four patch context managers this module always needs."""
    return (
        patch(
            "src.schematic.self_improvement_loop.propose_netlist_llm",
            side_effect=(
                propose_side_effect if propose_side_effect is not None
                else [_proposal()] * 20
            ),
        ),
        patch(
            "src.schematic.self_improvement_loop.verify_schematic",
            side_effect=verify_side_effect,
        ),
        patch(
            "src.schematic.self_improvement_loop.polish_schematic",
            return_value=polish_return,
        ),
        patch(
            "src.schematic.self_improvement_loop.run_beam_search",
            return_value=beam_return,
        ),
    )


# ── Convergence / round counting ────────────────────────────────────────────

def test_converges_early_stops_loop() -> None:
    p1, p2, p3, p4 = _patched(
        verify_side_effect=[_verification(0.3), _verification(0.3), _verification(1.0)],
    )
    with p1, p2, p3 as mock_polish, p4 as mock_beam:
        result = run_self_improving_synthesis(BOM, DATASHEETS, REF_MAP, CONFIG, max_rounds=5)

    assert isinstance(result, SelfImprovementResult)
    assert len(result.rounds) == 3
    assert result.converged is True
    assert result.final_score == 1.0
    assert result.weak_model_alone_score == 0.3
    assert result.stage_used == "asha_only"
    mock_polish.assert_not_called()  # 1.0 is not < SA_DONE_THRESHOLD
    mock_beam.assert_not_called()


def test_never_converges_runs_all_rounds() -> None:
    p1, p2, p3, p4 = _patched(verify_side_effect=[_verification(0.5)] * 5)
    with p1, p2, p3 as mock_polish, p4 as mock_beam:
        result = run_self_improving_synthesis(
            BOM, DATASHEETS, REF_MAP, CONFIG, max_rounds=5, score_threshold=0.95,
        )

    assert len(result.rounds) == 5
    assert result.converged is False
    assert result.stage_used == "asha_only"
    mock_polish.assert_not_called()  # 0.5 is below SA_TRIGGER_THRESHOLD
    mock_beam.assert_not_called()


def test_weak_model_alone_score_is_always_round_zero() -> None:
    p1, p2, p3, p4 = _patched(
        verify_side_effect=[_verification(0.2), _verification(0.9)],
        polish_return=SAPolishResult(
            polished_netlist=[], initial_score=0.9, final_score=0.95, converged=True,
        ),
    )
    with p1, p2, p3, p4:
        result = run_self_improving_synthesis(
            BOM, DATASHEETS, REF_MAP, CONFIG, max_rounds=2, score_threshold=0.95,
        )

    assert result.weak_model_alone_score == 0.2
    # best_score after round 2 (0.9) and SA polish (0.95) may differ — the
    # invariant under test is only that weak_model_alone_score never moves.


# ── SA polish composition ───────────────────────────────────────────────────

def test_sa_polish_applied_when_score_lands_in_range() -> None:
    sa_return = SAPolishResult(
        polished_netlist=[MagicMock()], initial_score=0.85, final_score=0.98,
    )
    p1, p2, p3, p4 = _patched(
        verify_side_effect=[_verification(0.85)],
        polish_return=sa_return,
    )
    with p1, p2, p3 as mock_polish, p4 as mock_beam:
        result = run_self_improving_synthesis(
            BOM, DATASHEETS, REF_MAP, CONFIG, max_rounds=1, score_threshold=0.95,
        )

    mock_polish.assert_called_once()
    mock_beam.assert_not_called()
    assert result.sa_polish_applied is True
    assert result.stage_used == "sa_polish"
    assert result.final_score == 0.98
    assert result.best_score == 0.98
    assert result.beam_result is None


def test_sa_polish_not_applied_below_trigger_threshold() -> None:
    p1, p2, p3, p4 = _patched(verify_side_effect=[_verification(0.5)])
    with p1, p2, p3 as mock_polish, p4 as mock_beam:
        result = run_self_improving_synthesis(
            BOM, DATASHEETS, REF_MAP, CONFIG, max_rounds=1, score_threshold=0.95,
        )

    mock_polish.assert_not_called()
    mock_beam.assert_not_called()
    assert result.sa_polish_applied is False
    assert result.stage_used == "asha_only"
    assert result.final_score == 0.5


def test_beam_search_after_sa_when_score_still_below_trigger() -> None:
    """SA polish that degrades below SA_TRIGGER_THRESHOLD escalates to beam."""
    polished = [MagicMock(name="polished_net")]
    beamed = [MagicMock(name="beamed_net")]
    sa_return = SAPolishResult(
        polished_netlist=polished,
        initial_score=0.85,
        final_score=SA_TRIGGER_THRESHOLD - 0.05,
    )
    beam_return = BeamSearchResult(
        best_netlist=beamed, best_score=0.88, initial_score=0.75,
    )
    # Round-0 verify (0.85) enters SA; post-SA re-verify feeds beam search.
    p1, p2, p3, p4 = _patched(
        verify_side_effect=[_verification(0.85), _verification(0.75)],
        polish_return=sa_return,
        beam_return=beam_return,
    )
    with p1, p2, p3 as mock_polish, p4 as mock_beam:
        result = run_self_improving_synthesis(
            BOM, DATASHEETS, REF_MAP, CONFIG, max_rounds=1, score_threshold=0.95,
        )

    mock_polish.assert_called_once()
    mock_beam.assert_called_once()
    assert result.sa_polish_applied is True
    assert result.stage_used == "beam_search"
    assert result.beam_result is beam_return
    assert result.final_score == 0.88
    assert result.best_netlist is beamed


def test_beam_search_not_called_when_sa_keeps_score_at_or_above_trigger() -> None:
    sa_return = SAPolishResult(
        polished_netlist=[MagicMock()],
        initial_score=0.85,
        final_score=SA_TRIGGER_THRESHOLD,
    )
    p1, p2, p3, p4 = _patched(
        verify_side_effect=[_verification(0.85)],
        polish_return=sa_return,
    )
    with p1, p2, p3 as mock_polish, p4 as mock_beam:
        result = run_self_improving_synthesis(
            BOM, DATASHEETS, REF_MAP, CONFIG, max_rounds=1, score_threshold=0.95,
        )

    mock_polish.assert_called_once()
    mock_beam.assert_not_called()
    assert result.stage_used == "sa_polish"
    assert result.beam_result is None
    assert result.final_score == SA_TRIGGER_THRESHOLD


# ── Feedback threading ───────────────────────────────────────────────────────

def test_feedback_given_none_on_round_zero_then_nonempty() -> None:
    p1, p2, p3, p4 = _patched(
        verify_side_effect=[
            _verification(0.3, violation_count=1),
            _verification(0.3, violation_count=1),
        ],
    )
    with p1, p2, p3, p4:
        result = run_self_improving_synthesis(
            BOM, DATASHEETS, REF_MAP, CONFIG, max_rounds=2, score_threshold=0.95,
        )

    assert result.rounds[0].feedback_given is None
    assert isinstance(result.rounds[1].feedback_given, str)
    assert len(result.rounds[1].feedback_given) > 0
    assert "violation 0" in result.rounds[1].feedback_given


# ── Never raises ─────────────────────────────────────────────────────────────

def test_round_exception_is_recorded_and_loop_continues() -> None:
    p1, p2, p3, p4 = _patched(
        propose_side_effect=[RuntimeError("gpu oom"), _proposal()],
        verify_side_effect=[_verification(0.9)],
    )
    with p1, p2, p3, p4:
        result = run_self_improving_synthesis(
            BOM, DATASHEETS, REF_MAP, CONFIG, max_rounds=2, score_threshold=0.95,
        )

    assert isinstance(result, SelfImprovementResult)
    assert len(result.rounds) == 2
    assert result.rounds[0].score == 0.0
    assert result.rounds[1].score == 0.9


def test_every_round_failing_never_raises() -> None:
    p1, p2, p3, p4 = _patched(propose_side_effect=RuntimeError("gpu oom"))
    with p1, p2, p3 as mock_polish, p4 as mock_beam:
        result = run_self_improving_synthesis(
            BOM, DATASHEETS, REF_MAP, CONFIG, max_rounds=3, score_threshold=0.95,
        )

    assert isinstance(result, SelfImprovementResult)
    assert result.final_score == 0.0
    assert result.converged is False
    assert result.sa_polish_applied is False
    assert result.stage_used == "asha_only"
    mock_polish.assert_not_called()  # last_verification never set
    mock_beam.assert_not_called()


# ── expected_topologies forwarding ──────────────────────────────────────────

def test_expected_topologies_forwarded_to_verify_schematic() -> None:
    p1, p2, p3, p4 = _patched(verify_side_effect=[_verification(1.0)])
    with p1, p2 as mock_verify, p3, p4:
        run_self_improving_synthesis(
            BOM, DATASHEETS, REF_MAP, CONFIG, max_rounds=1,
            expected_topologies=["ldo"],
        )

    _, kwargs = mock_verify.call_args
    assert kwargs["expected_topologies"] == ["ldo"]
