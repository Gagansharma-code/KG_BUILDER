"""ASHA search controller — closes the loop between BOM candidates, the
5-layer structural verifier, the SA polisher, and beam search escalation.

See documents/decisions/Search_controller_decision.md for the full design
and plan.md (repo root) for the implementation plan this file follows.

Because src/schematic/synthesize_schematic() is deterministic (rule-based
net assignment, no LLM), this first version evaluates each BOM candidate
exactly once — there is no point resampling a deterministic function.
Variance comes entirely from which BOM candidate is chosen (Layer 0 / TPE),
not from repeated netlist generation. That still delivers the point of
this module: TPE learning, SA polishing, and beam search escalation are
switched on for the first time via one orchestrator. See the module
docstring note in llm_netlist_proposer.py / self_improvement_loop.py for
the companion module that DOES introduce stochastic (LLM-based) netlist
generation, which is where multi-round ASHA becomes meaningful.

Never raises. On total failure, returns a degraded ASHAResult with
final_score=0.0 and routed_to_human_review=True, matching the "never
raises" contract used throughout src/schematic/ (see synthesize_schematic,
polish_schematic, run_beam_search).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, NamedTuple, Optional

from src.bom.tpe_sampler import TPEBOMSampler, record_asha_outcome
from src.schematic._ref_mapper import build_ref_map
from src.schematic.beam_search_escalation import run_beam_search
from src.schematic.sa_polisher import (
    SA_DONE_THRESHOLD,
    SA_TRIGGER_THRESHOLD,
    polish_schematic,
)
from src.schematic.structural_verifier import verify_schematic

if TYPE_CHECKING:
    from src.bom.candidates import BOMLadder
    from src.config import Config
    from src.schemas.datasheet import ComponentDatasheet
    from src.schemas.intent import ValidatedBOM
    from src.schemas.kg import DesignSubgraph
    from src.schemas.nir import NetlistEntry
    from src.schematic.beam_search_escalation import BeamSearchResult
    from src.schematic.sa_polisher import SAPolishResult
    from src.schematic.structural_verifier import VerificationResult

logger = logging.getLogger(__name__)

# Below this after beam search escalation, route the design to human review.
# Kept as a plain module constant (mirrors SA_TRIGGER_THRESHOLD /
# SA_DONE_THRESHOLD in sa_polisher.py) rather than reading from Config, so
# this module has no dependency on Config attribute shape at call time.
HUMAN_REVIEW_THRESHOLD: float = 0.80


class _EvaluatedCandidate(NamedTuple):
    """One successfully-evaluated BOM candidate — avoids a bare `tuple` under
    mypy strict mode (disallow_any_generics) and makes the max()-selection
    below self-documenting instead of magic-index tuple unpacking."""

    bom: "ValidatedBOM"
    netlist: list["NetlistEntry"]
    ref_map: dict[str, tuple[str, Optional["ComponentDatasheet"]]]
    verification: "VerificationResult"


@dataclass
class ASHAResult:
    """Result of one full search-controller run.

    winner_bom:            The BOM candidate that produced the best schematic.
    winner_ladder_id:       ladder_id of the BOMLadder this came from (traceability).
    initial_verification:   VerificationResult for winner_bom before any refinement.
    final_netlist:          Netlist after SA polish / beam search / neither.
    final_score:            Score after refinement.
    stage_used:             Which refinement path was taken.
    sa_result:              Populated only if stage_used == "sa_polish".
    beam_result:            Populated only if stage_used == "beam_search".
    candidate_scores:       {design_id: score} for every BOM candidate that
                            was successfully evaluated — the "before" data
                            for the Idea 2 benchmark comparison.
    routed_to_human_review: True if final_score < HUMAN_REVIEW_THRESHOLD after
                            beam search — the caller is responsible for actually
                            enqueuing the design; this function does not do it.
    """

    winner_bom: "ValidatedBOM"
    winner_ladder_id: str
    initial_verification: "VerificationResult"
    final_netlist: list["NetlistEntry"]
    final_score: float
    stage_used: Literal["asha_only", "sa_polish", "beam_search"]
    sa_result: Optional["SAPolishResult"] = None
    beam_result: Optional["BeamSearchResult"] = None
    candidate_scores: dict[str, float] = field(default_factory=dict)
    routed_to_human_review: bool = False


def run_search_controller(
    ladder: "BOMLadder",
    datasheets: list["ComponentDatasheet"],
    subgraph: "DesignSubgraph",
    config: "Config",
    sampler: Optional[TPEBOMSampler] = None,
    expected_topologies: Optional[list[str]] = None,
    human_review_threshold: float = HUMAN_REVIEW_THRESHOLD,
) -> ASHAResult:
    """Evaluate every BOM candidate in ladder, refine the winner, record outcome.

    Args:
        ladder:   BOMLadder from generate_bom_candidates(), optionally enriched
                  by TPEBOMSampler.enrich_bom_candidates().
        datasheets: All ComponentDatasheet objects available for ref_map building.
        subgraph: DesignSubgraph — passed through to synthesize_schematic()
                  unchanged (current implementation does not use it directly).
        config:   Application Config — passed through to synthesize_schematic().
        sampler:  Optional TPEBOMSampler. If provided, record_asha_outcome() is
                  called with the winning BOM and final score after refinement.
        human_review_threshold: Below this after beam search escalation, route
                  to human review. Defaults to the module constant; callers
                  that want config.search_controller.human_review_threshold
                  to actually take effect (e.g. the orchestrator) must pass it
                  explicitly — kept as an explicit parameter rather than read
                  from `config` internally so existing callers/tests that pass
                  a bare mock Config are unaffected.
        expected_topologies: Topology names from structural_verifier.TOPOLOGY_TEMPLATES
                  to check in Layer 4. Pass None (default) to auto-detect from the
                  winning BOM's component_type keywords — this keeps the search
                  controller independent of intent.goal_topology / KG topology
                  wiring, which are separate, already-tracked gaps (see
                  PROJECT_CONTEXT.md §9 items 5 and 7).

    Returns:
        ASHAResult. Never raises.
    """
    try:
        from src.schematic import synthesize_schematic

        evaluated: list[_EvaluatedCandidate] = []
        candidate_scores: dict[str, float] = {}

        for bom_candidate in ladder.candidates:
            try:
                schematic = synthesize_schematic(bom_candidate, datasheets, subgraph, config)
                ref_map = build_ref_map(bom_candidate, datasheets)
                verification = verify_schematic(
                    netlist=schematic.netlist,
                    ref_map=ref_map,
                    bom=bom_candidate,
                    expected_topologies=expected_topologies,
                )
            except Exception as exc:
                logger.warning(
                    "search_controller: evaluating BOM candidate %s failed: %s",
                    getattr(bom_candidate, "design_id", "<unknown>"), exc,
                )
                continue

            candidate_scores[bom_candidate.design_id] = verification.score
            evaluated.append(
                _EvaluatedCandidate(bom_candidate, schematic.netlist, ref_map, verification)
            )

        if not evaluated:
            logger.error("search_controller: no BOM candidate could be evaluated.")
            return ASHAResult(
                winner_bom=ladder.best(),
                winner_ladder_id=ladder.ladder_id,
                initial_verification=verify_schematic(netlist=[], ref_map={}),
                final_netlist=[],
                final_score=0.0,
                stage_used="asha_only",
                candidate_scores={},
                routed_to_human_review=True,
            )

        winner = max(evaluated, key=lambda item: item.verification.score)
        winner_bom = winner.bom
        winner_netlist = winner.netlist
        winner_ref_map = winner.ref_map
        winner_verification = winner.verification
        score = winner_verification.score

        sa_result: Optional["SAPolishResult"] = None
        beam_result: Optional["BeamSearchResult"] = None
        routed_to_human_review = False

        if score >= SA_DONE_THRESHOLD:
            stage_used: Literal["asha_only", "sa_polish", "beam_search"] = "asha_only"
            final_netlist = winner_netlist
            final_score = score

        elif score >= SA_TRIGGER_THRESHOLD:
            sa_result = polish_schematic(
                netlist=winner_netlist,
                ref_map=winner_ref_map,
                bom=winner_bom,
                verification=winner_verification,
                expected_topologies=expected_topologies,
            )
            stage_used = "sa_polish"
            final_netlist = sa_result.polished_netlist
            final_score = sa_result.final_score

        else:
            beam_result = run_beam_search(
                netlist=winner_netlist,
                ref_map=winner_ref_map,
                bom=winner_bom,
                verification=winner_verification,
                expected_topologies=expected_topologies,
            )
            stage_used = "beam_search"
            final_netlist = beam_result.best_netlist
            final_score = beam_result.best_score
            routed_to_human_review = final_score < human_review_threshold

        if sampler is not None:
            try:
                record_asha_outcome(sampler, winner_bom, final_score)
            except Exception as exc:
                logger.warning(
                    "search_controller: record_asha_outcome failed: %s", exc
                )

        logger.info(
            "search_controller: winner=%s stage=%s score=%.4f→%.4f review=%s",
            winner_bom.design_id, stage_used, score, final_score,
            routed_to_human_review,
        )

        return ASHAResult(
            winner_bom=winner_bom,
            winner_ladder_id=ladder.ladder_id,
            initial_verification=winner_verification,
            final_netlist=final_netlist,
            final_score=final_score,
            stage_used=stage_used,
            sa_result=sa_result,
            beam_result=beam_result,
            candidate_scores=candidate_scores,
            routed_to_human_review=routed_to_human_review,
        )

    except Exception as exc:
        logger.error(
            "search_controller: run_search_controller failed: %s", exc, exc_info=True
        )
        return ASHAResult(
            winner_bom=ladder.best(),
            winner_ladder_id=getattr(ladder, "ladder_id", ""),
            initial_verification=verify_schematic(netlist=[], ref_map={}),
            final_netlist=[],
            final_score=0.0,
            stage_used="asha_only",
            candidate_scores={},
            routed_to_human_review=True,
        )
