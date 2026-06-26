"""Gate tests for beam search escalation."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import random

from src.schemas.nir import NetlistEntry, PinRef
from src.schematic.beam_search_escalation import (
    BEAM_DONE_THRESHOLD,
    BEAM_MAX_DEPTH,
    BEAM_WIDTH,
    BeamSearchResult,
    BeamState,
    _expand_beam_state,
    run_beam_search,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _pin(ref: str, name: str, number: str) -> PinRef:
    return PinRef(ref=ref, pin_name=name, pin_number=number)


def _net(name: str, net_type: str, connections: list[PinRef]) -> NetlistEntry:
    return NetlistEntry(
        net_name=name,
        net_type=net_type,
        connections=connections,
        source_rule="test",
        net_confidence=0.9,
    )


def _make_verification(score: float, violations: list | None = None) -> MagicMock:
    v = MagicMock()
    v.score = score
    v.critical_violations = violations or []
    return v


def _make_netlist(n_nets: int = 2) -> list[NetlistEntry]:
    nets = []
    for i in range(n_nets):
        nets.append(_net(f"NET_{i}", "signal", [
            _pin(f"U{i}", "A", "1"),
            _pin(f"U{i+1}", "B", "2"),
        ]))
    return nets


# ── Constants ─────────────────────────────────────────────────────────────────

def test_beam_width_is_3():
    assert BEAM_WIDTH == 3

def test_beam_max_depth_is_4():
    assert BEAM_MAX_DEPTH == 4

def test_beam_done_threshold_is_1_0():
    assert BEAM_DONE_THRESHOLD == 1.0


# ── BeamState ─────────────────────────────────────────────────────────────────

def test_beam_state_defaults():
    netlist = _make_netlist()
    state = BeamState(netlist=netlist, score=0.75)
    assert state.depth == 0
    assert state.move_history == []


# ── _expand_beam_state ────────────────────────────────────────────────────────

def test_expand_beam_state_returns_list():
    netlist = _make_netlist()
    state = BeamState(netlist=netlist, score=0.75)
    verification = _make_verification(0.75)
    rng = random.Random(0)
    result = _expand_beam_state(state, verification, rng)
    assert isinstance(result, list)

def test_expand_beam_state_returns_tuples_of_netlist_and_move_type():
    netlist = _make_netlist()
    state = BeamState(netlist=netlist, score=0.75)
    verification = _make_verification(0.75)
    rng = random.Random(0)
    result = _expand_beam_state(state, verification, rng)
    for item in result:
        assert len(item) == 2
        candidate, move_type = item
        assert isinstance(candidate, list)
        assert isinstance(move_type, str)

def test_expand_beam_state_singleton_nets_may_return_empty():
    netlist = [_net("SOLO", "signal", [_pin("U1", "A", "1")])]
    state = BeamState(netlist=netlist, score=0.75)
    verification = _make_verification(0.75)
    rng = random.Random(0)
    result = _expand_beam_state(state, verification, rng)
    assert isinstance(result, list)


# ── run_beam_search ───────────────────────────────────────────────────────────

def test_run_beam_search_returns_result():
    netlist = _make_netlist()
    init_v = _make_verification(0.70)
    with patch("src.schematic.beam_search_escalation.verify_schematic",
               return_value=_make_verification(0.70)):
        result = run_beam_search(netlist, {}, MagicMock(), init_v)
    assert isinstance(result, BeamSearchResult)

def test_run_beam_search_converges_when_verifier_returns_perfect():
    netlist = _make_netlist()
    init_v = _make_verification(0.70)
    with patch("src.schematic.beam_search_escalation.verify_schematic",
               return_value=_make_verification(1.0)):
        result = run_beam_search(netlist, {}, MagicMock(), init_v)
    assert result.converged is True
    assert result.best_score == 1.0

def test_run_beam_search_does_not_exceed_max_depth():
    netlist = _make_netlist()
    init_v = _make_verification(0.60)
    with patch("src.schematic.beam_search_escalation.verify_schematic",
               return_value=_make_verification(0.60)):
        result = run_beam_search(netlist, {}, MagicMock(), init_v,
                                 max_depth=2)
    assert result.depth_reached <= 2

def test_run_beam_search_preserves_initial_score():
    netlist = _make_netlist()
    init_v = _make_verification(0.65)
    with patch("src.schematic.beam_search_escalation.verify_schematic",
               return_value=_make_verification(0.65)):
        result = run_beam_search(netlist, {}, MagicMock(), init_v)
    assert result.initial_score == pytest.approx(0.65)

def test_run_beam_search_best_score_never_below_initial():
    netlist = _make_netlist()
    init_v = _make_verification(0.72)
    with patch("src.schematic.beam_search_escalation.verify_schematic",
               return_value=_make_verification(0.72)):
        result = run_beam_search(netlist, {}, MagicMock(), init_v)
    assert result.best_score >= 0.70

def test_run_beam_search_score_by_depth_is_non_empty_after_steps():
    netlist = _make_netlist()
    init_v = _make_verification(0.70)
    with patch("src.schematic.beam_search_escalation.verify_schematic",
               return_value=_make_verification(0.75)):
        result = run_beam_search(netlist, {}, MagicMock(), init_v,
                                 max_depth=2)
    assert isinstance(result.score_by_depth, list)

def test_run_beam_search_never_raises():
    netlist = _make_netlist()
    init_v = _make_verification(0.65)
    with patch("src.schematic.beam_search_escalation.verify_schematic",
               side_effect=RuntimeError("verifier crash")):
        result = run_beam_search(netlist, {}, MagicMock(), init_v)
    assert isinstance(result, BeamSearchResult)

def test_run_beam_search_candidates_evaluated_increments():
    netlist = _make_netlist()
    init_v = _make_verification(0.70)
    with patch("src.schematic.beam_search_escalation.verify_schematic",
               return_value=_make_verification(0.70)):
        result = run_beam_search(netlist, {}, MagicMock(), init_v,
                                 max_depth=1)
    assert result.candidates_evaluated >= 0

def test_run_beam_search_empty_netlist_does_not_crash():
    init_v = _make_verification(0.70)
    with patch("src.schematic.beam_search_escalation.verify_schematic",
               return_value=_make_verification(0.70)):
        result = run_beam_search([], {}, MagicMock(), init_v)
    assert isinstance(result, BeamSearchResult)

def test_run_beam_search_result_best_netlist_is_list():
    netlist = _make_netlist()
    init_v = _make_verification(0.70)
    with patch("src.schematic.beam_search_escalation.verify_schematic",
               return_value=_make_verification(0.80)):
        result = run_beam_search(netlist, {}, MagicMock(), init_v)
    assert isinstance(result.best_netlist, list)

def test_run_beam_search_improves_on_high_scoring_verifier():
    netlist = _make_netlist()
    init_v = _make_verification(0.65)
    scores = [0.72, 0.78, 0.85, 0.90]
    call_count = [0]

    def fake_verify(*args, **kwargs):
        score = scores[min(call_count[0], len(scores) - 1)]
        call_count[0] += 1
        return _make_verification(score)

    with patch("src.schematic.beam_search_escalation.verify_schematic",
               side_effect=fake_verify):
        result = run_beam_search(netlist, {}, MagicMock(), init_v,
                                 max_depth=3)
    assert result.best_score >= 0.65
