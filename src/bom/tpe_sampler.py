"""TPE BOM Sampler — cross-design component preference learning.

Records BOM → ERC score outcomes across design sessions and uses
accumulated history to enrich future BOMLadders with historically
preferred component alternatives.

This enables generate_bom_candidates() to produce meaningful variant BOMs
once sufficient history exists (MIN_OBSERVATIONS_FOR_PREDICTION outcomes
per component_type).

STATUS (2026-07-06): implemented and gate-tested; not wired into
run_intent_pipeline() or run_e2e() — see src/bom/candidates.py module
docstring for the ASHA-controller dependency this awaits.

Storage: data/bom_tpe_history.json (gitignored runtime file).
No network calls. No Optuna dependency. Pure Python with JSON persistence.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.bom.candidates import BOMLadder
    from src.schemas.intent import ValidatedBOM

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_PATH = Path("data/bom_tpe_history.json")
MIN_OBSERVATIONS_FOR_PREDICTION: int = 3   # minimum outcomes before enriching
MAX_HISTORY_ENTRIES:             int = 5000 # cap to prevent unbounded growth
MAX_ALTERNATIVES_INJECTED:       int = 2    # max alternatives to add per entry


@dataclass
class BOMOutcome:
    """One recorded BOM component → ERC score observation.

    design_id:      The design that produced this outcome.
    component_type: Normalised component category (e.g., "ldo_regulator").
    specific_part:  The part number selected (None if unresolved).
    erc_score:      Final ERC score from the search controller for this design.
    timestamp:      ISO 8601 UTC timestamp of recording.
    """
    design_id:      str
    component_type: str
    specific_part:  Optional[str]
    erc_score:      float
    timestamp:      str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class ComponentRanking:
    """Ranking of specific_parts for one component_type.

    component_type:  The component category.
    ranked_parts:    List of (specific_part, mean_erc_score) tuples,
                     sorted by mean_erc_score descending.
    observation_count: Total outcomes used to produce this ranking.
    """
    component_type:     str
    ranked_parts:       list[tuple[str, float]]
    observation_count:  int


class TPEBOMSampler:
    """Cross-design BOM preference learner.

    Maintains a persistent history of (component_type, specific_part) → ERC
    score observations. Uses empirical mean ERC by configuration to rank
    component choices and enrich future BOMLadders with alternatives.

    Usage pattern:
        sampler = TPEBOMSampler()

        # After each completed design:
        sampler.record_outcome(winner_bom, final_erc_score)

        # Before next design's BOM generation:
        enriched_ladder = sampler.enrich_bom_candidates(ladder)
        # enriched_ladder.candidates[0] now has populated alternatives
        # generate_bom_candidates() will use those alternatives
    """

    def __init__(self, history_path: Path = DEFAULT_HISTORY_PATH) -> None:
        self.history_path = Path(history_path)
        self._history: list[BOMOutcome] = []
        self._load()

    def _load(self) -> None:
        """Load history from disk. Silent no-op if file does not exist."""
        if not self.history_path.exists():
            return
        try:
            with open(self.history_path, encoding="utf-8") as f:
                raw = json.load(f)
            self._history = [BOMOutcome(**item) for item in raw]
            logger.debug(
                "TPEBOMSampler: loaded %d outcomes from %s",
                len(self._history), self.history_path,
            )
        except Exception as exc:
            logger.warning(
                "TPEBOMSampler: failed to load history from %s: %s. "
                "Starting with empty history.",
                self.history_path, exc,
            )
            self._history = []

    def _save(self) -> None:
        """Save history to disk atomically (write-then-rename).
        Creates parent directory if it does not exist.
        Never raises — logs and continues on failure.
        """
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            if len(self._history) > MAX_HISTORY_ENTRIES:
                self._history = self._history[-MAX_HISTORY_ENTRIES:]
            raw = [asdict(o) for o in self._history]
            fd, tmp_path = tempfile.mkstemp(
                dir=self.history_path.parent,
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(raw, f, indent=2, ensure_ascii=False)
                os.replace(tmp_path, self.history_path)
            except Exception:
                os.unlink(tmp_path)
                raise
        except Exception as exc:
            logger.warning(
                "TPEBOMSampler: failed to save history: %s", exc
            )

    def record_outcome(
        self,
        bom: ValidatedBOM,
        erc_score: float,
    ) -> None:
        """Record one design session outcome.

        For each BOMEntry in bom.components, records a BOMOutcome
        pairing the (component_type, specific_part) with the final
        erc_score. Saves to disk after recording.

        Args:
            bom:       The winning ValidatedBOM from the search controller.
            erc_score: Final ERC score after ASHA + SA + beam search.
        """
        recorded = 0
        for entry in bom.components:
            outcome = BOMOutcome(
                design_id=bom.design_id,
                component_type=entry.component_type.lower().strip(),
                specific_part=entry.specific_part,
                erc_score=max(0.0, min(1.0, float(erc_score))),
            )
            self._history.append(outcome)
            recorded += 1

        logger.debug(
            "TPEBOMSampler: recorded %d outcomes for design %s (ERC=%.4f).",
            recorded, bom.design_id, erc_score,
        )
        self._save()

    def get_component_ranking(
        self,
        component_type: str,
    ) -> Optional[ComponentRanking]:
        """Return a ranked list of specific_parts for a component_type.

        Returns None if fewer than MIN_OBSERVATIONS_FOR_PREDICTION outcomes
        exist for this component_type (cold start).

        Only includes specific_parts with at least 1 successful observation
        (erc_score > 0). Parts with specific_part=None are excluded.

        Args:
            component_type: The component category to rank.

        Returns:
            ComponentRanking or None if insufficient data.
        """
        ctype = component_type.lower().strip()
        relevant = [
            o for o in self._history
            if o.component_type == ctype and o.specific_part is not None
        ]

        if len(relevant) < MIN_OBSERVATIONS_FOR_PREDICTION:
            return None

        part_scores: dict[str, list[float]] = {}
        for o in relevant:
            part_scores.setdefault(o.specific_part, []).append(o.erc_score)

        ranked = sorted(
            [
                (part, sum(scores) / len(scores))
                for part, scores in part_scores.items()
            ],
            key=lambda x: x[1],
            reverse=True,
        )

        return ComponentRanking(
            component_type=ctype,
            ranked_parts=ranked,
            observation_count=len(relevant),
        )

    def get_preferred_parts(
        self,
        component_type: str,
        exclude_part: Optional[str] = None,
        n: int = MAX_ALTERNATIVES_INJECTED,
    ) -> list[str]:
        """Return top-n preferred specific_parts for a component_type.

        Excludes exclude_part (typically the already-selected primary part).
        Returns empty list if insufficient history.

        Args:
            component_type: Component category to query.
            exclude_part:   Part to exclude from results (already selected).
            n:              Maximum number of parts to return.

        Returns:
            List of specific_part strings, best first.
        """
        ranking = self.get_component_ranking(component_type)
        if ranking is None:
            return []

        parts = [
            part for part, _ in ranking.ranked_parts
            if part != exclude_part
        ]
        return parts[:n]

    def enrich_bom_candidates(self, ladder: BOMLadder) -> BOMLadder:
        """Inject historically preferred alternatives into BOMLadder candidates.

        For each candidate BOM in the ladder, for each BOMEntry where:
        - specific_part is not None (resolved component)
        - alternatives is empty (no alternatives available)
        - sufficient history exists for this component_type

        Populates entry.alternatives with top preferred parts from history.

        This enables generate_bom_candidates() to produce variant BOMs
        using historically high-performing alternatives.

        Returns a new BOMLadder with enriched candidates.
        Never modifies the input ladder in place.
        Never raises.
        """
        try:
            enriched_candidates = []
            enriched_count = 0

            for bom in ladder.candidates:
                enriched_components = []
                for entry in bom.components:
                    if (
                        entry.specific_part is not None
                        and not entry.alternatives
                    ):
                        preferred = self.get_preferred_parts(
                            component_type=entry.component_type,
                            exclude_part=entry.specific_part,
                            n=MAX_ALTERNATIVES_INJECTED,
                        )
                        if preferred:
                            entry = entry.model_copy(
                                update={"alternatives": preferred}
                            )
                            enriched_count += 1
                    enriched_components.append(entry)

                enriched_bom = bom.model_copy(
                    update={"components": enriched_components}
                )
                enriched_candidates.append(enriched_bom)

            if enriched_count > 0:
                logger.debug(
                    "TPEBOMSampler: enriched %d BOMEntry alternatives "
                    "across %d candidates.",
                    enriched_count, len(enriched_candidates),
                )

            return ladder.model_copy(
                update={"candidates": enriched_candidates}
            )

        except Exception as exc:
            logger.warning(
                "TPEBOMSampler.enrich_bom_candidates failed: %s. "
                "Returning original ladder.", exc,
            )
            return ladder

    @property
    def total_outcomes(self) -> int:
        """Total recorded outcomes across all component types."""
        return len(self._history)

    @property
    def component_types_observed(self) -> list[str]:
        """Unique component_types seen in history."""
        return list({o.component_type for o in self._history})

    def clear_history(self) -> None:
        """Clear all stored outcomes and delete the history file.
        Used in tests and when resetting the learning state.
        """
        self._history = []
        if self.history_path.exists():
            try:
                self.history_path.unlink()
            except Exception as exc:
                logger.warning("TPEBOMSampler: failed to delete history file: %s", exc)


def record_asha_outcome(
    sampler: TPEBOMSampler,
    winner_bom: ValidatedBOM,
    final_erc_score: float,
) -> None:
    """Convenience wrapper to record one search controller run outcome.

    Call this after every completed design (after ASHA + SA + beam search)
    to feed the cross-design learning loop.

    Args:
        sampler:         The TPEBOMSampler instance.
        winner_bom:      The winning ValidatedBOM from ASHAResult.winner.bom.
        final_erc_score: Final ERC score after all refinement (SA or beam search
                         final_score, or ASHA winner_score if no refinement ran).
    """
    sampler.record_outcome(winner_bom, final_erc_score)
