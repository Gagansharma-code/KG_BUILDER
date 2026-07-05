"""Beam Search Escalation — systematic multi-chain schematic repair.

Designed to activate when ASHAResult.escalate_to_mcts is True. Replaces the
originally proposed LLM-guided MCTS. See
documents/architecture/MCTS_DECISION.md.

Uses programmatic graph mutations (same move types as SA polisher) but
maintains beam_width parallel repair chains and evaluates all candidates
at each depth step, keeping the top beam_width by ERC score.

No LLM inference is used. Zero GPU cost. All mutations are deterministic
graph operations on list[NetlistEntry].

STATUS (2026-07-06): implemented and gate-tested. `ASHAResult` is not a
defined type anywhere in this codebase, and no ASHA search controller
(search_controller.py) exists to call this module — it is not reachable
from run_intent_pipeline() or run_e2e(). See src/bom/candidates.py module
docstring and documents/architecture/PROJECT_CONTEXT.md §9.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from src.schemas.nir import NetlistEntry
from src.schematic.sa_polisher import (
    SA_DONE_THRESHOLD,
    _apply_move,
    _generate_moves_from_violations,
    _generate_random_move,
)
from src.schematic.structural_verifier import verify_schematic

if TYPE_CHECKING:
    from src.schemas.datasheet import ComponentDatasheet
    from src.schemas.intent import ValidatedBOM

logger = logging.getLogger(__name__)

BEAM_WIDTH:           int   = 3
BEAM_MAX_DEPTH:       int   = 4
BEAM_MAX_ACTIONS:     int   = 5    # max moves to generate per beam state per step
BEAM_DONE_THRESHOLD:  float = SA_DONE_THRESHOLD
BEAM_RANDOM_SEED:     int   = 7


@dataclass
class BeamState:
    """One candidate in the beam at a given depth.

    netlist:      Current netlist for this beam state.
    score:        Most recent ERC score for this netlist.
    depth:        How many repair steps have been applied.
    move_history: Ordered list of move_type strings applied so far.
    """
    netlist: list[NetlistEntry]
    score: float
    depth: int = 0
    move_history: list[str] = field(default_factory=list)


@dataclass
class BeamSearchResult:
    """Result of one beam search escalation run.

    best_netlist:          Highest-scoring netlist found.
    best_score:            ERC score of best_netlist.
    initial_score:         ERC score when beam search started.
    depth_reached:         Deepest step completed.
    candidates_evaluated:  Total (state, move) pairs scored.
    converged:             True if best_score >= BEAM_DONE_THRESHOLD.
    score_by_depth:        Best score achieved at each depth step.
    """
    best_netlist: list[NetlistEntry]
    best_score: float
    initial_score: float
    depth_reached: int = 0
    candidates_evaluated: int = 0
    converged: bool = False
    score_by_depth: list[float] = field(default_factory=list)


def _expand_beam_state(
    state: BeamState,
    verification,
    rng: random.Random,
    max_actions: int = BEAM_MAX_ACTIONS,
) -> list[tuple[list[NetlistEntry], str]]:
    """Generate all candidate mutations from one beam state.

    Returns list of (candidate_netlist, move_type) pairs.
    If no targeted moves from violations, falls back to one random move.
    Limits to max_actions candidates to bound computational cost.
    """
    moves = _generate_moves_from_violations(state.netlist, verification)

    if not moves:
        random_move = _generate_random_move(state.netlist, rng)
        if random_move is None:
            return []
        moves = [random_move]

    seen = set()
    unique_moves = []
    for m in moves:
        key = (m.move_type, m.net_name, m.pin_ref.ref, m.pin_ref.pin_number)
        if key not in seen:
            seen.add(key)
            unique_moves.append(m)

    limited_moves = unique_moves[:max_actions]
    candidates = []
    for move in limited_moves:
        candidate = _apply_move(state.netlist, move)
        candidates.append((candidate, move.move_type))

    return candidates


def run_beam_search(
    netlist: list[NetlistEntry],
    ref_map: dict,
    bom,
    verification,
    expected_topologies: Optional[list[str]] = None,
    beam_width: int = BEAM_WIDTH,
    max_depth: int = BEAM_MAX_DEPTH,
    seed: int = BEAM_RANDOM_SEED,
) -> BeamSearchResult:
    """Run beam search escalation on a schematic that scored < SA_TRIGGER_THRESHOLD.

    Algorithm:
        beam = [BeamState(netlist, initial_score)]

        for depth in range(max_depth):
            candidates = []
            for state in beam:
                re-verify state to get fresh violations
                expand → N candidate (netlist, move_type) pairs
                score each candidate with verify_schematic()
                candidates.extend(...)

            keep top beam_width by score → new beam
            record best score at this depth
            if best score >= BEAM_DONE_THRESHOLD: stop

        return best candidate across all depths

    Args:
        netlist:              Input netlist (ASHA winner with low ERC score).
        ref_map:              Component ref map for verify_schematic.
        bom:                  ValidatedBOM for Layer 3 verification.
        verification:         Initial VerificationResult from ASHA.
        expected_topologies:  Topology names for Layer 4 verification.
        beam_width:           Number of candidates to maintain per step.
        max_depth:            Maximum repair steps.
        seed:                 Random seed for reproducibility.

    Returns:
        BeamSearchResult. Never raises.
    """
    initial_score = verification.score
    rng = random.Random(seed)

    beam: list[BeamState] = [
        BeamState(netlist=list(netlist), score=initial_score)
    ]

    best_overall = BeamState(netlist=list(netlist), score=initial_score)
    score_by_depth: list[float] = []
    candidates_evaluated = 0

    logger.info(
        "Beam search starting. Initial score: %.4f. "
        "Width: %d, Depth: %d.",
        initial_score, beam_width, max_depth,
    )

    for depth in range(max_depth):
        next_candidates: list[BeamState] = []

        for state in beam:
            try:
                current_verification = verify_schematic(
                    netlist=state.netlist,
                    ref_map=ref_map,
                    bom=bom,
                    expected_topologies=expected_topologies,
                )
                state.score = current_verification.score
            except Exception as exc:
                logger.debug(
                    "Beam depth %d: re-verification failed: %s", depth, exc
                )
                current_verification = verification

            expansions = _expand_beam_state(
                state, current_verification, rng
            )

            for candidate_netlist, move_type in expansions:
                try:
                    cand_verification = verify_schematic(
                        netlist=candidate_netlist,
                        ref_map=ref_map,
                        bom=bom,
                        expected_topologies=expected_topologies,
                    )
                    cand_score = cand_verification.score
                except Exception as exc:
                    logger.debug(
                        "Beam depth %d: candidate scoring failed: %s", depth, exc
                    )
                    cand_score = 0.0

                candidates_evaluated += 1
                next_candidates.append(BeamState(
                    netlist=candidate_netlist,
                    score=cand_score,
                    depth=depth + 1,
                    move_history=state.move_history + [move_type],
                ))

                if cand_score > best_overall.score:
                    best_overall = BeamState(
                        netlist=candidate_netlist,
                        score=cand_score,
                        depth=depth + 1,
                        move_history=state.move_history + [move_type],
                    )

        if not next_candidates:
            logger.debug("Beam search: no expansions at depth %d. Stopping.", depth)
            score_by_depth.append(best_overall.score)
            break

        next_candidates.sort(key=lambda s: s.score, reverse=True)
        beam = next_candidates[:beam_width]

        best_at_depth = beam[0].score
        score_by_depth.append(best_at_depth)

        logger.debug(
            "Beam depth %d complete. Best: %.4f. Candidates evaluated: %d.",
            depth + 1, best_at_depth, candidates_evaluated,
        )

        if best_at_depth >= BEAM_DONE_THRESHOLD:
            logger.info(
                "Beam search converged at depth %d. Score: %.4f.",
                depth + 1, best_at_depth,
            )
            return BeamSearchResult(
                best_netlist=beam[0].netlist,
                best_score=best_at_depth,
                initial_score=initial_score,
                depth_reached=depth + 1,
                candidates_evaluated=candidates_evaluated,
                converged=True,
                score_by_depth=score_by_depth,
            )

    logger.info(
        "Beam search terminated. Best: %.4f (initial: %.4f). "
        "Depth: %d, Candidates evaluated: %d.",
        best_overall.score, initial_score,
        len(score_by_depth), candidates_evaluated,
    )

    return BeamSearchResult(
        best_netlist=best_overall.netlist,
        best_score=best_overall.score,
        initial_score=initial_score,
        depth_reached=len(score_by_depth),
        candidates_evaluated=candidates_evaluated,
        converged=best_overall.score >= BEAM_DONE_THRESHOLD,
        score_by_depth=score_by_depth,
    )
