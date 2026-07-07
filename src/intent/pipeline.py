"""Team C intent-to-BOM pipeline orchestration."""

from __future__ import annotations

import logging
from typing import Optional

from src.bom.generator import generate_bom
from src.bom.validator import validate_bom
from src.completion import CompletionEngineError, run_completion_engine
from src.completion.contradiction_checker import run_rule_checker
from src.completion.engine import protection_review_flags_for_intent
from src.completion.schemas import RequirementCompletionResult
from src.config import Config
from src.intent.interval_solver import (
    ConstraintConflictError,
    assert_interval_feasible,
)
from src.intent.parser import parse_intent
from src.knowledge_graph import query_graph
from src.knowledge_graph.constraints import persist_design_constraints
from src.knowledge_graph.graph import KnowledgeGraph
from src.retrieval import RetrievalEngine
from src.retrieval.schemas import RetrievalResult
from src.review.queue import enqueue_bom
from src.schemas.intent import (
    DesignMethodology,
    ImprovedIntentDict,
    IntentDict,
    ValidatedBOM,
)

logger = logging.getLogger(__name__)

STAGE2_INCOMPLETE_REVIEW_FLAG = "stage2_incomplete"


def _run_stage2(
    intent: ImprovedIntentDict,
    config: Config,
) -> tuple[ImprovedIntentDict, bool]:
    """
    Run Stage 2 requirement completion engine.

    Returns ``(intent, stage2_incomplete)``. On failure, returns the Stage 1
    intent unchanged with ``stage2_incomplete=True``. Never raises.
    """
    try:
        return run_completion_engine(intent, config), False
    except CompletionEngineError as exc:
        logger.warning(
            "Stage 2 completion engine failed — proceeding with Stage 1 output: %s",
            exc,
        )
        return intent, True
    except Exception as exc:
        logger.warning(
            "Stage 2 unexpected error — proceeding with Stage 1 output: %s",
            exc,
        )
        return intent, True


def _apply_rule_checker(intent: ImprovedIntentDict) -> ImprovedIntentDict:
    """Run mechanical rule checks against a Stage 1 intent."""
    rule_contradictions = run_rule_checker(intent, RequirementCompletionResult())
    if not rule_contradictions:
        return intent
    return intent.model_copy(
        update={
            "contradictions_detected": list(intent.contradictions_detected)
            + [c.description for c in rule_contradictions],
        }
    )


def _run_retrieval(intent: ImprovedIntentDict, config: Config) -> Optional[RetrievalResult]:
    """
    Run Stage 2.5 KB retrieval. Returns None if database_url is absent or on any error.
    Never raises.
    """
    database_url = getattr(config, "database_url", None)
    if not database_url:
        logger.info("Stage 2.5: skipping KB retrieval — no database_url configured")
        return None

    try:
        logger.info("Stage 2.5: running KB retrieval")
        engine = RetrievalEngine(db_url=database_url, config=config)
        result = engine.run_retrieval(intent)
        logger.info(
            "Stage 2.5: retrieval complete — %d candidates, %d missing",
            len(result.component_candidates),
            len(result.missing_components),
        )
        return result
    except Exception as exc:
        logger.warning("Stage 2.5 retrieval failed — proceeding without KB results: %s", exc)
        return None


def run_intent_pipeline(
    prompt: str,
    graph: KnowledgeGraph,
    config: Config,
) -> tuple[IntentDict, ValidatedBOM, Optional[RetrievalResult]]:
    """
    Full Team C pipeline: prompt -> IntentDict -> KG query -> ValidatedBOM.
    Never raises. Returns review_required=True BOM on any internal failure.
    """
    try:
        intent = parse_intent(prompt, config)

        if intent.clarification_required:
            logger.warning(f"Clarification required for prompt: {prompt!r}")
            empty_bom = _empty_bom(intent)
            return intent, empty_bom, None

        logger.info("Stage 2: running requirement completion engine")
        intent, stage2_incomplete = _run_stage2(intent, config)
        if stage2_incomplete:
            intent = _apply_rule_checker(intent)
        logger.info(
            "Stage 2: complete — clarification_required=%s stage2_incomplete=%s",
            intent.clarification_required,
            stage2_incomplete,
        )

        if intent.clarification_required:
            logger.warning("Stage 2 set clarification_required=True — halting pipeline")
            empty_bom = _empty_bom(intent)
            return intent, empty_bom, None

        logger.info("Stage 2.5: running KB retrieval")
        retrieval_result = _run_retrieval(intent, config)

        # Stage 2.75: deductive feasibility pre-check (interval solver).
        # Fails loudly — an infeasible constraint set halts the pipeline
        # here with named conflicts instead of failing slowly downstream.
        try:
            assert_interval_feasible(intent)
        except ConstraintConflictError as exc:
            logger.error("Stage 2.75: infeasible constraints — halting: %s", exc)
            conflict_bom = _empty_bom(intent)
            conflict_bom = conflict_bom.model_copy(
                update={
                    "review_flags": [
                        f"CRITICAL: {c.constraint_a} vs {c.constraint_b} — {c.description}"
                        for c in exc.conflicts
                    ],
                }
            )
            persist_design_constraints(
                intent, conflict_bom.design_id, graph, config=config
            )
            enqueue_bom(conflict_bom, config)
            return intent, conflict_bom, retrieval_result

        subgraph = query_graph(intent, graph, config)
        bom = generate_bom(subgraph, intent, config, retrieval_result=retrieval_result)
        validated_bom = validate_bom(bom, config)
        validated_bom = _apply_review_flags(
            validated_bom,
            intent=intent,
            stage2_incomplete=stage2_incomplete,
        )

        # Persist this run's constraints as DESIGN_CONSTRAINT nodes —
        # the provenance audit trail, scoped by design_id, never discarded.
        persist_design_constraints(
            intent, validated_bom.design_id, graph, config=config
        )

        if validated_bom.review_required:
            enqueue_bom(validated_bom, config)

        return intent, validated_bom, retrieval_result

    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        fallback_intent = ImprovedIntentDict(
            goal="unknown",
            application="unknown",
            design_methodology=DesignMethodology.STANDARD_SMD,
            board_type="standard_SMD",
            raw_prompt=prompt,
            clarification_required=True,
        )
        return fallback_intent, _empty_bom(fallback_intent), None


def _protection_review_flags(intent: ImprovedIntentDict) -> list[str]:
    """Return protection review flags when unresolved requirements are present."""
    if not intent.protection_requirements:
        return []
    return protection_review_flags_for_intent(intent)


def _apply_review_flags(
    validated_bom: ValidatedBOM,
    *,
    intent: ImprovedIntentDict,
    stage2_incomplete: bool = False,
) -> ValidatedBOM:
    """Merge stage2-incomplete and protection flags onto the validated BOM."""
    existing_flags = list(getattr(validated_bom, "review_flags", []) or [])
    flags = list(existing_flags)
    if stage2_incomplete:
        flags.append(STAGE2_INCOMPLETE_REVIEW_FLAG)
    flags.extend(_protection_review_flags(intent))
    if flags == existing_flags:
        return validated_bom
    return validated_bom.model_copy(
        update={
            "review_required": validated_bom.review_required or bool(flags),
            "review_flags": flags,
        }
    )


def stage2_incomplete_from_bom(validated_bom: ValidatedBOM) -> bool:
    """Return True when the BOM was produced without a completed Stage 2 run."""
    return STAGE2_INCOMPLETE_REVIEW_FLAG in validated_bom.review_flags


def _empty_bom(intent: IntentDict) -> ValidatedBOM:
    import uuid
    from datetime import datetime

    return ValidatedBOM(
        design_id=str(uuid.uuid4()),
        intent=intent,
        components=[],
        total_confidence=0.0,
        review_required=True,
        created_at=datetime.utcnow().isoformat() + "Z",
    )
