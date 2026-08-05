"""Config schemas for the ASHA search controller (Idea 1) and the
weak-model self-improvement loop (Idea 2).

Lives under src/schemas/ (not src/schematic/) deliberately: src/config.py
needs to import these at module level, and src/schematic/__init__.py itself
imports `from src.config import Config` — importing a src.schematic
submodule from src/config.py would trigger that package __init__ and create
a circular import. src/schemas/ has no such back-reference (see
src/schemas/__init__.py, intentionally empty) and is already the
established home for shared Pydantic contracts consumed across teams.

Both configs are opt-in (enabled=False by default) so existing pipelines
and gate tests are unaffected until a caller explicitly turns them on.
See documents/decisions/Search_controller_decision.md and plan.md.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class SearchControllerConfig(BaseModel):
    """Settings for run_search_controller() (src/schematic/search_controller.py)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False,
        description="Master switch. Off by default — existing pipelines unaffected.",
    )
    max_bom_candidates: int = Field(
        default=3, ge=1, le=3,
        description="Upper bound on BOM candidates evaluated per design (BOMLadder cap).",
    )
    human_review_threshold: float = Field(
        default=0.80, ge=0.0, le=1.0,
        description=(
            "Final score below this after beam search escalation routes the "
            "design to human review. Matches sa_polisher.SA_TRIGGER_THRESHOLD "
            "by default — kept as a separate, overridable setting."
        ),
    )
    sampler_path: Path = Field(
        default=Path("data/bom_tpe_history.json"),
        description=(
            "Persistent JSON path for TPEBOMSampler history. Loaded before "
            "each search_controller run and saved after record_asha_outcome(). "
            "Matches src.bom.tpe_sampler.DEFAULT_HISTORY_PATH by default."
        ),
    )


class SelfImprovementConfig(BaseModel):
    """Settings for run_self_improving_synthesis() (src/schematic/self_improvement_loop.py)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False,
        description="Master switch. Off by default.",
    )
    max_rounds: int = Field(
        default=5, ge=1, le=10,
        description="Maximum weak-model proposal rounds before giving up.",
    )
    score_threshold: float = Field(
        default=0.95, ge=0.0, le=1.0,
        description="verify_schematic() score at/above which the loop stops early.",
    )
    temperature_schedule: list[float] = Field(
        default_factory=lambda: [0.7, 0.7, 0.9, 0.9, 0.5],
        description=(
            "Per-round sampling temperature for propose_netlist_llm(). Padded/"
            "truncated to max_rounds at call time if lengths differ."
        ),
    )
