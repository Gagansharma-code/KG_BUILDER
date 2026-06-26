"""Multi-candidate BOM generation for the unified search controller.

Provides generate_bom_candidates() which returns a BOMLadder —
a ranked list of up to 3 ValidatedBOM objects for the ASHA controller
to evaluate against the structural verifier.

The existing generate_bom() is called internally and unchanged.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, Field

from src.bom.generator import generate_bom
from src.schemas.intent import BOMEntry, IntentDict, ValidatedBOM

if TYPE_CHECKING:
    from src.config import Config
    from src.schemas.kg import DesignSubgraph

logger = logging.getLogger(__name__)


class BOMLadder(BaseModel):
    """Ranked list of BOM candidates for the ASHA search controller.

    candidates: Up to 3 ValidatedBOM objects ranked by total_confidence
                descending. candidate[0] is always the highest-confidence
                selection. May contain only 1 candidate if no alternatives
                are available.

    primary_varied_component: The component_type whose specific_part
                              was varied across candidates. None if only
                              1 candidate was generated.

    n_candidates: Actual number of candidates returned (1 to max_candidates).

    ladder_id: Unique identifier for this ladder, used by the ASHA controller
               to track which candidates have been evaluated.

    generation_metadata: Dict with keys:
        - "base_bom_design_id": design_id of the primary candidate
        - "varied_ref": ref of the component that was varied (or None)
        - "alternatives_available": int, how many alternatives were found
        - "created_at": ISO 8601 timestamp
    """

    candidates: list[ValidatedBOM] = Field(
        min_length=1,
        description="BOM candidates ranked by total_confidence descending",
    )
    primary_varied_component: Optional[str] = Field(
        default=None,
        description="component_type that was varied across candidates",
    )
    n_candidates: int = Field(
        ge=1,
        description="Actual number of candidates in this ladder",
    )
    ladder_id: str = Field(
        description="Unique identifier for this ladder",
    )
    generation_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Provenance and generation details",
    )

    def best(self) -> ValidatedBOM:
        """Return the highest-confidence BOM candidate."""
        return self.candidates[0]

    def scores(self) -> list[float]:
        """Return total_confidence for each candidate in order."""
        return [c.total_confidence for c in self.candidates]


# Component criticality weights — matches confidence_scorer.py logic.
# Higher weight = more impactful component = better candidate for variation.
_HIGH_WEIGHT_KEYWORDS: frozenset[str] = frozenset({
    "regulator", "ldo", "buck", "boost", "converter",
    "antenna", "rf",
    "microcontroller", "mcu", "processor", "fpga",
    "op_amp", "opamp", "amplifier",
    "adc", "dac",
})

_LOW_WEIGHT_KEYWORDS: frozenset[str] = frozenset({
    "capacitor", "cap",
    "resistor", "res",
    "inductor", "ind",
})


def _component_weight(component_type: str) -> float:
    """Return criticality weight for a component type.

    High-weight components (regulators, antennas, MCUs): 2.0
    Low-weight components (passives): 0.5
    Default: 1.0
    """
    lowered = component_type.lower()
    if any(kw in lowered for kw in _HIGH_WEIGHT_KEYWORDS):
        return 2.0
    if any(kw in lowered for kw in _LOW_WEIGHT_KEYWORDS):
        return 0.5
    return 1.0


def _find_highest_weight_entry(components: list[BOMEntry]) -> Optional[BOMEntry]:
    """Return the BOMEntry with the highest component weight.

    Used to identify which component's alternative should be tried
    when generating variant BOM candidates. Returns None if empty.
    """
    if not components:
        return None
    return max(components, key=lambda e: _component_weight(e.component_type))


def _build_variant_bom(
    base_bom: ValidatedBOM,
    target_ref: str,
    alternative_part: str,
) -> Optional[ValidatedBOM]:
    """Build a variant BOM by swapping one component's specific_part.

    Creates a new ValidatedBOM via model_copy. The variant has:
    - A new design_id (UUID)
    - The same components as base_bom, except target_ref has
      specific_part = alternative_part
    - total_confidence slightly penalised (alternatives are less
      well-characterised than primary selections): × 0.97
    - review_required preserved from base_bom

    Never raises — returns None on any failure.
    """
    try:
        new_components = []
        for entry in base_bom.components:
            if entry.ref == target_ref:
                new_entry = entry.model_copy(update={
                    "specific_part": alternative_part,
                    "justification": (
                        f"{entry.justification} [Variant: using {alternative_part} "
                        f"instead of {entry.specific_part}]"
                    ),
                    "confidence": round(entry.confidence * 0.97, 4),
                    "alternatives": [
                        p for p in entry.alternatives if p != alternative_part
                    ],
                })
                new_components.append(new_entry)
            else:
                new_components.append(entry)

        variant_confidence = round(base_bom.total_confidence * 0.97, 4)
        return base_bom.model_copy(update={
            "design_id": str(uuid.uuid4()),
            "components": new_components,
            "total_confidence": variant_confidence,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        logger.warning("Failed to build variant BOM: %s", exc)
        return None


def generate_bom_candidates(
    subgraph: DesignSubgraph,
    intent: IntentDict,
    config: Config,
    max_candidates: int = 3,
) -> BOMLadder:
    """Generate up to max_candidates ranked BOM candidates.

    Strategy:
    1. Call generate_bom() once to get the primary (highest-confidence) BOM.
    2. Find the highest-weight component entry in that BOM.
    3. If that entry has alternatives, build variant BOMs by swapping
       specific_part with each alternative (up to max_candidates - 1 variants).
    4. If no alternatives exist, return a BOMLadder with 1 candidate.
    5. Rank all candidates by total_confidence descending.
    6. Return BOMLadder.

    This function never raises. On any failure it returns a single-candidate
    BOMLadder containing the result of generate_bom().

    Args:
        subgraph: DesignSubgraph from knowledge graph query.
        intent: Original design intent.
        config: Application configuration.
        max_candidates: Maximum candidates to return (default 3, minimum 1).

    Returns:
        BOMLadder with 1 to max_candidates ValidatedBOM objects.
    """
    ladder_id = str(uuid.uuid4())
    max_candidates = max(1, min(max_candidates, 3))

    try:
        primary_bom = generate_bom(subgraph, intent, config)
    except Exception as exc:
        logger.error("generate_bom_candidates: primary BOM generation failed: %s", exc)
        empty_bom = ValidatedBOM(
            design_id=str(uuid.uuid4()),
            intent=intent,
            components=[],
            total_confidence=0.0,
            review_required=True,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        return BOMLadder(
            candidates=[empty_bom],
            primary_varied_component=None,
            n_candidates=1,
            ladder_id=ladder_id,
            generation_metadata={
                "error": str(exc),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    if max_candidates == 1 or not primary_bom.components:
        return BOMLadder(
            candidates=[primary_bom],
            primary_varied_component=None,
            n_candidates=1,
            ladder_id=ladder_id,
            generation_metadata={
                "base_bom_design_id": primary_bom.design_id,
                "varied_ref": None,
                "alternatives_available": 0,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    target_entry = _find_highest_weight_entry(primary_bom.components)
    alternatives_available = len(target_entry.alternatives) if target_entry else 0

    candidates: list[ValidatedBOM] = [primary_bom]

    if target_entry and target_entry.alternatives:
        for alt_part in target_entry.alternatives[: max_candidates - 1]:
            variant = _build_variant_bom(primary_bom, target_entry.ref, alt_part)
            if variant is not None:
                candidates.append(variant)

    candidates.sort(key=lambda b: b.total_confidence, reverse=True)

    return BOMLadder(
        candidates=candidates,
        primary_varied_component=(
            target_entry.component_type if target_entry and len(candidates) > 1
            else None
        ),
        n_candidates=len(candidates),
        ladder_id=ladder_id,
        generation_metadata={
            "base_bom_design_id": primary_bom.design_id,
            "varied_ref": target_entry.ref if target_entry else None,
            "alternatives_available": alternatives_available,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
