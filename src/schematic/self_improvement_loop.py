"""Weak-model + verifier self-improvement loop — the "agent maxing"
centerpiece of Idea 2.

Round 0 is the 'before' number for the AMD-submission benchmark
(eval/benchmarks/agent_maxing_benchmark.py): one weak-model attempt, no
feedback. Every subsequent round feeds the previous round's
critical_violations back into the prompt. This module never trains
anything — all improvement comes from retrying against verify_schematic(),
the same deterministic scorer Idea 1's search controller
(search_controller.py) uses. No LLM ever scores its own output.

Never raises. Returns the best result seen even on total failure
(best_score=0.0, empty netlist, converged=False) — same "never raises"
contract as every other module in src/schematic/.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Optional

from src.schematic.beam_search_escalation import run_beam_search
from src.schematic.llm_netlist_proposer import propose_netlist_llm
from src.schematic.sa_polisher import (
    SA_DONE_THRESHOLD,
    SA_TRIGGER_THRESHOLD,
    polish_schematic,
)
from src.schematic.structural_verifier import verify_schematic

if TYPE_CHECKING:
    from src.config import Config
    from src.schemas.datasheet import ComponentDatasheet
    from src.schemas.intent import ValidatedBOM
    from src.schemas.nir import NetlistEntry
    from src.schematic.beam_search_escalation import BeamSearchResult
    from src.schematic.structural_verifier import VerificationResult

logger = logging.getLogger(__name__)

StageUsed = Literal["asha_only", "sa_polish", "beam_search"]

DEFAULT_MAX_ROUNDS: int = 5
DEFAULT_SCORE_THRESHOLD: float = 0.95
# Later rounds run hotter (more exploration) if still stuck, then cool down
# for a final precise pass — same adaptive-temperature intuition PCBSchemaGen
# used with a Beta distribution (Search_controller_decision.md Part 2),
# applied here per-round instead.
DEFAULT_TEMPERATURE_SCHEDULE: list[float] = [0.7, 0.7, 0.9, 0.9, 0.5]
MAX_VIOLATIONS_IN_FEEDBACK: int = 5


@dataclass
class RoundRecord:
    """One round of the self-improvement loop.

    feedback_given: The feedback string passed INTO this round's prompt
                    (None for round 0; a violation summary for round 1+).
    """
    round_index: int
    temperature: float
    score: float
    critical_violation_count: int
    feedback_given: Optional[str]


@dataclass
class SelfImprovementResult:
    """rounds: every RoundRecord, in order — the full trace for the benchmark.

    weak_model_alone_score: round 0's score. The "before" bar.
    final_score:            best_score after the loop (and SA polish / beam
                            search if either ran). The "after" bar.
    stage_used:             Which post-loop refinement path ran — mirrors
                            ASHAResult.stage_used for Idea 1 / Idea 2 parity.
    beam_result:            Populated only if stage_used == "beam_search".
    """
    rounds: list[RoundRecord] = field(default_factory=list)
    best_netlist: list["NetlistEntry"] = field(default_factory=list)
    best_score: float = 0.0
    weak_model_alone_score: float = 0.0
    final_score: float = 0.0
    converged: bool = False
    sa_polish_applied: bool = False
    stage_used: StageUsed = "asha_only"
    beam_result: Optional["BeamSearchResult"] = None


def _schedule_for(max_rounds: int, provided: Optional[list[float]]) -> list[float]:
    """Pad or truncate a temperature schedule to exactly max_rounds entries."""
    base = list(provided) if provided else list(DEFAULT_TEMPERATURE_SCHEDULE)
    if not base:
        base = [0.7]
    if len(base) >= max_rounds:
        return base[:max_rounds]
    return base + [base[-1]] * (max_rounds - len(base))


def _summarize_violations(verification: "VerificationResult") -> str:
    """Build the feedback string fed into the next round's prompt.

    Caps at MAX_VIOLATIONS_IN_FEEDBACK critical_violations to keep the
    prompt short — this is a small model, long prompts hurt more than help.
    """
    lines = [
        v.message for v in verification.critical_violations[:MAX_VIOLATIONS_IN_FEEDBACK]
    ]
    lowest = verification.lowest_scoring_layer()
    if lowest is not None:
        lines.append(f"Weakest area overall: {lowest.layer.value} (score {lowest.score:.2f}).")
    return "\n".join(lines)


def run_self_improving_synthesis(
    bom: "ValidatedBOM",
    datasheets: list["ComponentDatasheet"],
    ref_map: dict[str, tuple[str, Optional["ComponentDatasheet"]]],
    config: "Config",
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    temperature_schedule: Optional[list[float]] = None,
    expected_topologies: Optional[list[str]] = None,
) -> SelfImprovementResult:
    """Run up to max_rounds weak-model proposal+verify rounds, then a free
    SA-polish pass if the best result lands in the polish range.

    Args:
        bom, datasheets, ref_map: Same meaning as propose_netlist_llm() /
            verify_schematic().
        config:               Application Config.
        max_rounds:           Hard cap on LLM proposal attempts.
        score_threshold:      Stop early once a round's score reaches this.
        temperature_schedule: Per-round sampling temperature. Padded/
                              truncated to max_rounds if a shorter/longer
                              list is provided.
        expected_topologies:  Forwarded to verify_schematic() Layer 4.

    Returns:
        SelfImprovementResult. Never raises.
    """
    try:
        schedule = _schedule_for(max_rounds, temperature_schedule)

        rounds: list[RoundRecord] = []
        best_netlist: list["NetlistEntry"] = []
        best_score = 0.0
        weak_model_alone_score = 0.0
        converged = False
        feedback: Optional[str] = None
        last_verification: Optional["VerificationResult"] = None

        for i in range(max_rounds):
            temperature = schedule[i]

            try:
                proposal = propose_netlist_llm(
                    bom, datasheets, ref_map, config,
                    temperature=temperature, feedback=feedback,
                )
                verification = verify_schematic(
                    netlist=proposal.netlist,
                    ref_map=ref_map,
                    bom=bom,
                    expected_topologies=expected_topologies,
                )
            except Exception as exc:
                logger.warning(
                    "self_improvement_loop: round %d raised: %s", i, exc
                )
                rounds.append(RoundRecord(
                    round_index=i, temperature=temperature, score=0.0,
                    critical_violation_count=0, feedback_given=feedback,
                ))
                feedback = (
                    "Your previous attempt failed to produce a valid netlist "
                    "at all. Respond with the connections list only."
                )
                continue

            score = verification.score
            rounds.append(RoundRecord(
                round_index=i,
                temperature=temperature,
                score=score,
                critical_violation_count=len(verification.critical_violations),
                feedback_given=feedback,
            ))

            if i == 0:
                weak_model_alone_score = score

            if score > best_score:
                best_score = score
                best_netlist = proposal.netlist
                last_verification = verification

            if score >= score_threshold:
                converged = True
                logger.info(
                    "self_improvement_loop: converged at round %d, score %.4f",
                    i, score,
                )
                break

            feedback = _summarize_violations(verification)

        sa_polish_applied = False
        stage_used: StageUsed = "asha_only"
        beam_result: Optional["BeamSearchResult"] = None

        if (
            last_verification is not None
            and SA_TRIGGER_THRESHOLD <= best_score < SA_DONE_THRESHOLD
        ):
            sa_result = polish_schematic(
                netlist=best_netlist,
                ref_map=ref_map,
                bom=bom,
                verification=last_verification,
                expected_topologies=expected_topologies,
            )
            best_netlist = sa_result.polished_netlist
            best_score = sa_result.final_score
            sa_polish_applied = True
            stage_used = "sa_polish"
            converged = converged or best_score >= score_threshold

            # Narrow Idea 1 composition: if SA polish still leaves the score
            # below the SA trigger, escalate to beam search the same way
            # search_controller.run_search_controller() does for low scores.
            if best_score < SA_TRIGGER_THRESHOLD:
                try:
                    post_sa_verification = verify_schematic(
                        netlist=best_netlist,
                        ref_map=ref_map,
                        bom=bom,
                        expected_topologies=expected_topologies,
                    )
                except Exception as exc:
                    logger.warning(
                        "self_improvement_loop: post-SA re-verify failed: %s; "
                        "using pre-SA verification for beam search",
                        exc,
                    )
                    post_sa_verification = last_verification

                beam_result = run_beam_search(
                    netlist=best_netlist,
                    ref_map=ref_map,
                    bom=bom,
                    verification=post_sa_verification,
                    expected_topologies=expected_topologies,
                )
                best_netlist = beam_result.best_netlist
                best_score = beam_result.best_score
                stage_used = "beam_search"
                converged = converged or best_score >= score_threshold

        return SelfImprovementResult(
            rounds=rounds,
            best_netlist=best_netlist,
            best_score=best_score,
            weak_model_alone_score=weak_model_alone_score,
            final_score=best_score,
            converged=converged,
            sa_polish_applied=sa_polish_applied,
            stage_used=stage_used,
            beam_result=beam_result,
        )

    except Exception as exc:
        logger.error(
            "run_self_improving_synthesis failed: %s", exc, exc_info=True
        )
        return SelfImprovementResult()
