"""Stage 2 requirement completion engine — main entry point."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Type

from src.completion.axiom_loader import (
    detect_axiom_conflicts,
    load_axioms_for_intent,
)
from src.completion.contradiction_checker import run_rule_checker
from src.completion.schemas import Contradiction, RequirementCompletionResult
from src.completion.system_prompt import build_system_prompt
from src.schemas.common import Ambiguity
from src.schemas.intent import ImprovedIntentDict

if TYPE_CHECKING:
    from pydantic import BaseModel

    from src.config import Config

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.80
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (1, 2, 4)


class CompletionEngineError(Exception):
    """Raised when the completion engine cannot produce a result after retries."""
    pass


PROTECTION_RULE_CONSTRAINT_B = (
    "No matching functional_block in topology library"
)


def is_protection_contradiction(contradiction: Contradiction) -> bool:
    """Return True for Stage 2 Rule 4 protection-library gaps."""
    return (
        contradiction.detected_by == "rule_checker"
        and contradiction.constraint_b == PROTECTION_RULE_CONSTRAINT_B
        and contradiction.constraint_a.startswith("Protection required:")
    )


def protection_review_flags_from_contradictions(
    contradictions: list[Contradiction],
    *,
    intent: ImprovedIntentDict,
) -> list[str]:
    """Build review-queue flags for unresolved protection Rule 4 contradictions."""
    flags: list[str] = []
    for contradiction in contradictions:
        if not is_protection_contradiction(contradiction):
            continue
        kind = contradiction.constraint_a.removeprefix("Protection required: ").strip()
        raw_text = ""
        for requirement in intent.protection_requirements:
            if requirement.kind == kind:
                raw_text = getattr(requirement, "raw_text", "")[:80]
                break
        flags.append(f"protection_unresolved:{kind}:{raw_text}")
    return flags


def protection_review_flags_for_intent(intent: ImprovedIntentDict) -> list[str]:
    """Derive protection review flags by re-running Rule 4 checks.

    Callers should only apply these when Stage 2 completed and populated
    ``contradictions_detected`` — not on the CompletionEngineError fallback path.
    """
    contradictions = run_rule_checker(intent, RequirementCompletionResult())
    return protection_review_flags_from_contradictions(
        contradictions,
        intent=intent,
    )


def _resolve_completion_config(config: "Config") -> tuple[Path, str, str]:
    project_root = Path(__file__).resolve().parents[2]
    data_dir = getattr(config, "domain_knowledge_dir", None) or (
        project_root / "data" / "domain_knowledge"
    )
    base_url = getattr(config, "llm_base_url", "http://localhost:8000/v1")
    model = getattr(config, "llm_model", "Qwen/Qwen2.5-7B-Instruct")
    return Path(data_dir), base_url, model


def call_llm_with_instructor(
    system_prompt: str,
    intent: ImprovedIntentDict,
    config: "Config",
    output_schema: Type["BaseModel"],
    max_attempts: int = MAX_ATTEMPTS,
) -> RequirementCompletionResult:
    """Call LLM via Instructor with retries and exponential backoff.

    max_attempts defaults to MAX_ATTEMPTS (Stage 2's pipeline-gating call —
    worth retrying transient failures against). Callers whose failure mode
    is a soft degrade-to-None rather than a pipeline gate (e.g. optional
    enrichment extractions) should pass max_attempts=1 so a genuinely
    unavailable LLM fails in one attempt instead of paying the full
    backoff schedule for no benefit.
    """
    _, base_url, model = _resolve_completion_config(config)
    api_key = getattr(config, "llm_api_key", "not-needed")

    try:
        import instructor
        from openai import OpenAI
    except ImportError as exc:
        raise CompletionEngineError(
            "instructor or openai package not installed"
        ) from exc

    client = OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=60.0,
    )
    instructor_client = instructor.from_openai(client)

    user_message = (
        f"Analyze this PCB design intent:\n\n{intent.model_dump_json(indent=2)}"
    )

    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            result = instructor_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                response_model=output_schema,
                max_retries=0,
            )
            return result  # type: ignore[return-value]
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Completion LLM attempt %d/%d failed: %s",
                attempt + 1,
                max_attempts,
                exc,
            )
            if attempt < max_attempts - 1:
                time.sleep(BACKOFF_SECONDS[attempt])

    raise CompletionEngineError(str(last_exc))


def run_completion_engine(
    intent: ImprovedIntentDict,
    config: "Config",
) -> ImprovedIntentDict:
    """Run Stage 2 requirement completion and merge results into the intent dict."""
    data_dir, _, _ = _resolve_completion_config(config)

    # 1. Load and evaluate axioms from all topologies >= 0.6 confidence
    axioms = load_axioms_for_intent(intent, data_dir)
    axiom_conflicts = detect_axiom_conflicts(axioms)

    # 2. Build system prompt
    system_prompt = build_system_prompt(intent, axioms, axiom_conflicts)

    # 3. Call LLM via Instructor — RequirementCompletionResult enforced
    result: RequirementCompletionResult = call_llm_with_instructor(
        system_prompt=system_prompt,
        intent=intent,
        config=config,
        output_schema=RequirementCompletionResult,
    )

    # 4. Run rule-based contradiction checker — appends to result.contradictions
    rule_contradictions = run_rule_checker(intent, result)
    result = result.model_copy(update={
        "contradictions": result.contradictions + rule_contradictions,
    })

    # 5. Escalate dangerous assumptions to blocking Ambiguity entries
    new_ambiguities = list(intent.ambiguities)
    for da in result.dangerous_assumptions:
        new_ambiguities.append(Ambiguity(
            field=da.field,
            description=(
                f"Stage 2 would have assumed {da.field}={da.assumed_value!r} "
                f"({da.reasoning}). Must be confirmed by engineer before proceeding."
            ),
            severity="ERROR",
            candidate_resolutions=[
                f"Specify {da.field} explicitly in the prompt",
                f"Accept assumed value: {da.assumed_value}",
            ],
            blocking=True,
        ))

    clarification_required = intent.clarification_required or any(
        a.blocking for a in new_ambiguities
    )

    # 6. Merge result back into ImprovedIntentDict
    return intent.model_copy(update={
        "implied_requirements": result.implied_requirements,
        "missing_critical_specs": result.missing_critical_specs,
        "contradictions_detected": [c.description for c in result.contradictions],
        "inferred_constraints": [
            r.requirement for r in result.implied_requirements
            if r.confidence >= CONFIDENCE_THRESHOLD
        ],
        "ambiguities": new_ambiguities,
        "clarification_required": clarification_required,
    })
