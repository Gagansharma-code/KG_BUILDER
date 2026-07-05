"""Internal schemas for review queue.

Pydantic models for review queue items and related data structures.
These types are used within the review system for tracking components
that require human review.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class GateStage(str, Enum):
    """Review-gated orchestration stages with resumable artifacts."""

    BOM = "bom_generation"
    NETLIST = "netlist_generation"
    LAYOUT = "layout_generation"
    NIR = "nir_validation"


class ReviewQueueItem(BaseModel):
    """A single item in the review queue.

    Represents a component that requires human review, capturing
the stage where review was triggered, severity, verdict, and
resolution tracking.

    Attributes:
        item_id: Unique UUID for this queue item
        stage: Pipeline stage that triggered review (e.g., "phase4_validation")
        component_id: Component identifier (e.g., "TPS62933DRLR")
        pdf_path: Path to the source PDF file
        severity: Review severity level (CRITICAL or WARNING)
        verdict: Validation verdict (BLOCK, WARN, PASS)
        flags: List of review flags from ComponentDatasheet
        created_at: ISO 8601 timestamp when item was created
        status: Current status (pending, approved, corrected, rejected)
        resolved_at: ISO 8601 timestamp when resolved (if applicable)
        resolution_notes: Human-entered notes about resolution
    """

    item_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique UUID for this queue item",
    )
    stage: str = Field(
        ...,
        description='Pipeline stage that triggered review (e.g., "phase4_validation")',
    )
    component_id: str = Field(
        ...,
        description='Component identifier (e.g., "TPS62933DRLR")',
    )
    pdf_path: str = Field(
        ...,
        description="Path to the source PDF file",
    )
    severity: Literal["CRITICAL", "WARNING"] = Field(
        ...,
        description="Review severity level (CRITICAL or WARNING)",
    )
    verdict: str = Field(
        ...,
        description="Validation verdict (BLOCK, WARN, PASS)",
    )
    flags: list[str] = Field(
        default_factory=list,
        description="List of review flags from ComponentDatasheet",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        description="ISO 8601 timestamp when item was created",
    )
    status: Literal["pending", "approved", "corrected", "rejected"] = Field(
        default="pending",
        description="Current status (pending, approved, corrected, rejected)",
    )
    resolved_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp when resolved (if applicable)",
    )
    resolution_notes: Optional[str] = Field(
        default=None,
        description="Human-entered notes about resolution",
    )
    bom_json: Optional[str] = Field(
        default=None,
        description=(
            "Deprecated compatibility mirror for bom_generation snapshots. "
            "New gates use artifact_json for every review-gated stage."
        ),
    )
    artifact_json: Optional[str] = Field(
        default=None,
        description=(
            "Full serialized review artifact snapshot at enqueue time. "
            "The approved design is resumed from exactly this snapshot — "
            "never regenerated."
        ),
    )
    artifact_type: Optional[str] = Field(
        default=None,
        description="Pydantic model name stored in artifact_json.",
    )
