"""Gate tests for the ASHA search controller (src/schematic/search_controller.py).

Style mirrors tests/unit/schematic/test_beam_search_escalation.py: MagicMock
for VerificationResult, patch() on the collaborators actually invoked, real
dataclasses/pydantic models only where cheap to construct.

synthesize_schematic is imported *inside* run_search_controller (a local
import, not module-level) — see the docstring in search_controller.py for
why. That means it must be patched at its source, "src.schematic.
synthesize_schematic", not at "src.schematic.search_controller.
synthesize_schematic".
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.schemas.intent import DesignMethodology, ImprovedIntentDict, ValidatedBOM
from src.schemas.kg import DesignSubgraph
from src.schemas.nir import NetlistEntry, PinRef
from src.schematic.beam_search_escalation import BeamSearchResult
from src.schematic.sa_polisher import SAPolishResult
from src.schematic.search_controller import (
    HUMAN_REVIEW_THRESHOLD,
    ASHAResult,
    run_search_controller,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _intent() -> ImprovedIntentDict:
    return ImprovedIntentDict(
        goal="test",
        application="test",
        design_methodology=DesignMethodology.STANDARD_SMD,
        board_type="standard_SMD",
        raw_prompt="test",
    )


def _bom(design_id: str, confidence: float = 0.9) -> ValidatedBOM:
    return ValidatedBOM(
        design_id=design_id,
        intent=_intent(),
        components=[],
        total_confidence=confidence,
        review_required=False,
        created_at="2026-01-01T00:00:00Z",
    )


class _FakeLadder:
    """Minimal duck-typed stand-in for BOMLadder.

    Only exercises the surface run_search_controller actually touches
    (.candidates, .ladder_id, .best()) so these tests do not depend on
    generate_bom_candidates() plumbing.
    """

    def __init__(self, candidates: list[ValidatedBOM], ladder_id: str = "ladder-1"):
        self.candidates = candidates
        self.ladder_id = ladder_id

    def best(self) -> ValidatedBOM:
        return self.candidates[0]


def _subgraph() -> DesignSubgraph:
    return DesignSubgraph(
        component_types=[],
        component_instances=[],
        design_rules=[],
        placement_rules=[],
        routing_hints=[],
        design_methodology="standard_SMD",
        path_confidences={},
        query_depth=0,
    )


def _pin(ref: str, name: str, number: str) -> PinRef:
    return PinRef(ref=ref, pin_name=name, pin_number=number)


def _net(name: str) -> NetlistEntry:
    return NetlistEntry(
        net_name=name,
        net_type="signal",
        connections=[_pin("U1", "A", "1")],
        source_rule="test",
        net_confidence=0.9,
    )


def _schematic_mock(netlist=None) -> MagicMock:
    m = MagicMock()
    m.netlist = netlist if netlist is not None else [_net("NET_0")]
    return m


def _verification(score: float) -> MagicMock:
    v = MagicMock()
    v.score = score
    v.critical_violations = []
    return v


CONFIG = MagicMock()  # run_search_controller never reads config attributes directly


# ── Single candidate, perfect score → no refinement needed ────────────────────

def test_single_candidate_perfect_score_returns_asha_only():
    ladder = _FakeLadder([_bom("d1")])
    with patch("src.schematic.synthesize_schematic", return_value=_schematic_mock()), \
         patch("src.schematic.search_controller.verify_schematic", return_value=_verification(1.0)):
        result = run_search_controller(ladder, [], _subgraph(), CONFIG)

    assert isinstance(result, ASHAResult)
    assert result.stage_used == "asha_only"
    assert result.final_score == 1.0
    assert result.sa_result is None
    assert result.beam_result is None
    assert result.routed_to_human_review is False


# ── Winner selection ────────────────────────────────────────────────────────

def test_winner_selection_picks_highest_scoring_candidate():
    boms = [_bom("low"), _bom("winner"), _bom("mid")]
    ladder = _FakeLadder(boms)
    scores = [0.4, 1.0, 0.6]  # winner scores 1.0 → asha_only, no SA/beam needed

    with patch("src.schematic.synthesize_schematic", return_value=_schematic_mock()), \
         patch(
             "src.schematic.search_controller.verify_schematic",
             side_effect=[_verification(s) for s in scores],
         ):
        result = run_search_controller(ladder, [], _subgraph(), CONFIG)

    assert result.winner_bom.design_id == "winner"
    assert result.candidate_scores == {"low": 0.4, "winner": 1.0, "mid": 0.6}


# ── Threshold routing ───────────────────────────────────────────────────────

def test_score_in_sa_range_triggers_sa_polish():
    ladder = _FakeLadder([_bom("d1")])
    sa_return = SAPolishResult(
        polished_netlist=[_net("POLISHED")],
        initial_score=0.85,
        final_score=0.97,
        steps_taken=3,
        accepted_moves=2,
        converged=False,
    )
    with patch("src.schematic.synthesize_schematic", return_value=_schematic_mock()), \
         patch("src.schematic.search_controller.verify_schematic", return_value=_verification(0.85)), \
         patch("src.schematic.search_controller.polish_schematic", return_value=sa_return) as mock_polish:
        result = run_search_controller(ladder, [], _subgraph(), CONFIG)

    mock_polish.assert_called_once()
    assert result.stage_used == "sa_polish"
    assert result.sa_result is sa_return
    assert result.final_score == 0.97
    assert result.beam_result is None


def test_score_below_trigger_calls_beam_search():
    ladder = _FakeLadder([_bom("d1")])
    beam_return = BeamSearchResult(
        best_netlist=[_net("BEAM")],
        best_score=0.90,
        initial_score=0.5,
        depth_reached=2,
        candidates_evaluated=6,
        converged=False,
        score_by_depth=[0.7, 0.90],
    )
    with patch("src.schematic.synthesize_schematic", return_value=_schematic_mock()), \
         patch("src.schematic.search_controller.verify_schematic", return_value=_verification(0.5)), \
         patch("src.schematic.search_controller.run_beam_search", return_value=beam_return) as mock_beam:
        result = run_search_controller(ladder, [], _subgraph(), CONFIG)

    mock_beam.assert_called_once()
    assert result.stage_used == "beam_search"
    assert result.beam_result is beam_return
    assert result.final_score == 0.90
    assert result.sa_result is None


def test_low_score_after_beam_search_routes_to_human_review():
    ladder = _FakeLadder([_bom("d1")])
    beam_return = BeamSearchResult(
        best_netlist=[],
        best_score=0.3,
        initial_score=0.2,
        depth_reached=4,
        candidates_evaluated=10,
        converged=False,
        score_by_depth=[0.25, 0.3],
    )
    assert beam_return.best_score < HUMAN_REVIEW_THRESHOLD
    with patch("src.schematic.synthesize_schematic", return_value=_schematic_mock()), \
         patch("src.schematic.search_controller.verify_schematic", return_value=_verification(0.2)), \
         patch("src.schematic.search_controller.run_beam_search", return_value=beam_return):
        result = run_search_controller(ladder, [], _subgraph(), CONFIG)

    assert result.routed_to_human_review is True


def test_high_score_after_beam_search_does_not_route_to_review():
    ladder = _FakeLadder([_bom("d1")])
    beam_return = BeamSearchResult(
        best_netlist=[],
        best_score=0.85,
        initial_score=0.5,
        depth_reached=2,
        candidates_evaluated=6,
        converged=False,
        score_by_depth=[0.6, 0.85],
    )
    with patch("src.schematic.synthesize_schematic", return_value=_schematic_mock()), \
         patch("src.schematic.search_controller.verify_schematic", return_value=_verification(0.5)), \
         patch("src.schematic.search_controller.run_beam_search", return_value=beam_return):
        result = run_search_controller(ladder, [], _subgraph(), CONFIG)

    assert result.routed_to_human_review is False


# ── TPE sampler integration ─────────────────────────────────────────────────

def test_sampler_receives_record_outcome_call():
    ladder = _FakeLadder([_bom("d1")])
    sampler = MagicMock()
    with patch("src.schematic.synthesize_schematic", return_value=_schematic_mock()), \
         patch("src.schematic.search_controller.verify_schematic", return_value=_verification(1.0)), \
         patch("src.schematic.search_controller.record_asha_outcome") as mock_record:
        result = run_search_controller(ladder, [], _subgraph(), CONFIG, sampler=sampler)

    mock_record.assert_called_once_with(sampler, result.winner_bom, result.final_score)


def test_no_sampler_does_not_call_record_outcome():
    ladder = _FakeLadder([_bom("d1")])
    with patch("src.schematic.synthesize_schematic", return_value=_schematic_mock()), \
         patch("src.schematic.search_controller.verify_schematic", return_value=_verification(1.0)), \
         patch("src.schematic.search_controller.record_asha_outcome") as mock_record:
        run_search_controller(ladder, [], _subgraph(), CONFIG, sampler=None)

    mock_record.assert_not_called()


# ── expected_topologies forwarding ──────────────────────────────────────────

def test_expected_topologies_forwarded_to_verify_schematic():
    ladder = _FakeLadder([_bom("d1")])
    with patch("src.schematic.synthesize_schematic", return_value=_schematic_mock()), \
         patch(
             "src.schematic.search_controller.verify_schematic",
             return_value=_verification(1.0),
         ) as mock_verify:
        run_search_controller(
            ladder, [], _subgraph(), CONFIG, expected_topologies=["ldo"]
        )

    _, kwargs = mock_verify.call_args
    assert kwargs["expected_topologies"] == ["ldo"]


# ── Never raises ─────────────────────────────────────────────────────────────

def test_never_raises_when_synthesize_schematic_always_fails():
    ladder = _FakeLadder([_bom("d1"), _bom("d2")])
    with patch("src.schematic.synthesize_schematic", side_effect=RuntimeError("boom")):
        result = run_search_controller(ladder, [], _subgraph(), CONFIG)

    assert isinstance(result, ASHAResult)
    assert result.final_score == 0.0
    assert result.routed_to_human_review is True
    assert result.candidate_scores == {}


def test_never_raises_on_unexpected_top_level_failure():
    class _BrokenLadder:
        ladder_id = "broken"

        @property
        def candidates(self):
            raise RuntimeError("ladder is corrupt")

        def best(self):
            return _bom("fallback")

    result = run_search_controller(_BrokenLadder(), [], _subgraph(), CONFIG)

    assert isinstance(result, ASHAResult)
    assert result.final_score == 0.0
    assert result.routed_to_human_review is True
    assert result.winner_bom.design_id == "fallback"
