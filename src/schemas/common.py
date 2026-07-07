"""Shared schema types used across intent parsing and downstream stages."""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class SchemaVersionError(Exception):
    """Raised when a consumer receives an IntentDict with wrong schema version."""
    pass


class Ambiguity(BaseModel):
    field: str
    description: str
    severity: Literal["INFO", "WARNING", "ERROR"]
    candidate_resolutions: list[str] = Field(default_factory=list)
    blocking: bool = False


class ConditionScope(BaseModel):
    """Structured qualifier for a condition-bearing quantity.

    Shared across NoiseSpec and future spec types. Replaces opaque
    measurement_condition strings — raw_text preserves the source phrase.
    """

    parameter: str  # "frequency_hz", "offset_hz", "temp_c"
    at: Optional[float] = None  # point condition ("at 1 kHz")
    min: Optional[float] = None  # range condition ("10 Hz–100 kHz")
    max: Optional[float] = None
    raw_text: str


class NoiseSpec(BaseModel):
    target_value: Optional[float] = None
    unit: Optional[str] = None
    bandwidth_hz: Optional[float] = None
    condition: Optional[ConditionScope] = None
    raw_text: str
    quantification_source: Optional[str] = None


class AccuracySpec(BaseModel):
    absolute_ppm: Optional[float] = None
    relative_percent: Optional[float] = None
    drift_ppm_per_C: Optional[float] = None
    raw_text: str
    quantification_source: Optional[str] = None


class StabilitySpec(BaseModel):
    short_term_ppm: Optional[float] = None
    long_term_ppm_per_year: Optional[float] = None
    thermal_stability_ppm_per_C: Optional[float] = None
    raw_text: str
    quantification_source: Optional[str] = None


class ProductionVolume(str, Enum):
    PROTOTYPE = "prototype"      # 1–5 units
    SMALL_BATCH = "small_batch"  # 6–100 units
    PILOT = "pilot"              # 101–1000 units
    PRODUCTION = "production"    # 1001–100000 units
    FIELDED = "fielded"          # >100000 units, deployed


class ImpliedRequirement(BaseModel):
    requirement: str
    component_implication: Optional[str] = None
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_constraint: str
    priority: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = "MEDIUM"


class TopologyGuess(BaseModel):
    name: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str]


class DesignRequest(BaseModel):
    request_type: Literal[
        "bom", "schematic", "pcb_layout", "noise_analysis",
        "simulation", "spice_netlist", "design_report",
    ]
    in_scope: bool
    out_of_scope_reason: Optional[str] = None


class OutOfScopeRequest(BaseModel):
    request_type: str
    reason: str
    suggested_tool: Optional[str] = None
