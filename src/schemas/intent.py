"""Intent and BOM schemas — Team C owns writes, Team D owns reads.

This module defines the schemas for design intent capture and Bill of Materials (BOM)
generation. It bridges the gap between natural language design goals and structured
component selections.

The IntentDict captures the user's design requirements including frequency specifications,
application context, and any ambiguities that require clarification.

The ValidatedBOM represents the output of the component selection process, where each
BOMEntry may have a specific part number (resolved) or None (requiring human selection).

Version History:
- Initial schema for intent-to-BOM pipeline
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .common import (
    AccuracySpec,
    Ambiguity,
    ConditionScope,
    DesignRequest,
    ImpliedRequirement,
    NoiseSpec,
    OutOfScopeRequest,
    ProductionVolume,
    SchemaVersionError,
    StabilitySpec,
    TopologyGuess,
)

MAX_PROMPT_TOKENS = 4000


class FrequencySpec(BaseModel):
    """Frequency specification: point OR range, never both.

    Point constraints: set ``value`` + ``unit``; leave ``min_hz``/``max_hz`` unset.
    Range constraints (e.g. "10 Hz–100 kHz selectable"): set ``min_hz`` and
    ``max_hz`` in absolute Hz only — do **not** set ``value``. When either range
    field is set, ``value`` is not authoritative and must not be set alongside
    a range (validation rejects that ambiguous construction).

    Attributes:
        value: Point-spec frequency value (unset for range-only specs)
        unit: Frequency unit for point specs (Hz, kHz, MHz, GHz)
        min_hz: Lower bound in Hz for selectable ranges
        max_hz: Upper bound in Hz for selectable ranges
    """

    value: Optional[float] = Field(
        default=None, gt=0.0, description="Point-spec numeric frequency value"
    )
    unit: Optional[Literal["Hz", "kHz", "MHz", "GHz"]] = Field(
        default=None, description="Unit for point-spec value"
    )
    min_hz: Optional[float] = Field(
        default=None, gt=0.0, description="Range lower bound in Hz"
    )
    max_hz: Optional[float] = Field(
        default=None, gt=0.0, description="Range upper bound in Hz"
    )

    @model_validator(mode="after")
    def validate_point_or_range(self) -> Self:
        has_range_field = self.min_hz is not None or self.max_hz is not None
        has_point = self.value is not None

        if has_point and has_range_field:
            raise ValueError(
                "FrequencySpec cannot set value together with min_hz/max_hz; "
                "use value+unit for a point or min_hz+max_hz for a range"
            )

        if has_point:
            if self.unit is None:
                raise ValueError("unit is required when value is set")
            return self

        if has_range_field:
            if self.min_hz is None or self.max_hz is None:
                raise ValueError("Both min_hz and max_hz are required for a range spec")
            if self.min_hz > self.max_hz:
                raise ValueError("min_hz must be <= max_hz")
            return self

        raise ValueError(
            "FrequencySpec requires either value+unit (point) or min_hz+max_hz (range)"
        )


class AmbiguityFlag(BaseModel):
    """Flag indicating ambiguity in design intent requiring resolution.

    Captures fields where the intent parser detected uncertainty or
    multiple valid interpretations. Severity indicates whether the
    ambiguity blocks progress (CRITICAL) or is advisory (WARNING).

    Attributes:
        field: The intent field with ambiguity
        description: Human-readable explanation of the ambiguity
        severity: Impact level (CRITICAL blocks progress, WARNING is advisory)
        options: List of possible valid interpretations
    """

    field: str = Field(description="The intent field with ambiguity")
    description: str = Field(description="Human-readable explanation of the ambiguity")
    severity: Literal["CRITICAL", "WARNING"] = Field(
        description="Impact level: CRITICAL blocks progress, WARNING is advisory"
    )
    options: list[str] = Field(
        default_factory=list,
        description="List of possible valid interpretations",
    )


class DesignMethodology(str, Enum):
    """Classification of design methodology based on application requirements.

    Determines the design rules, component selection criteria, and
    layout constraints applied during the design process.
    """

    RF_HIGHFREQ = "RF_highfreq"  # High-frequency RF designs (>100 MHz)
    POWER_MANAGEMENT = "power_management"  # Power supplies, regulators, converters
    MIXED_SIGNAL = "mixed_signal"  # Analog/digital mixed designs
    STANDARD_SMD = "standard_SMD"  # Standard surface-mount digital/analog
    THROUGH_HOLE = "through_hole"  # Through-hole designs (prototyping, high power)


class PerformanceRequirements(BaseModel):
    noise: Optional[NoiseSpec] = None
    component_noise_floor: Optional[NoiseSpec] = None
    accuracy: Optional[AccuracySpec] = None
    stability: Optional[StabilitySpec] = None
    output_current_ma: Optional[float] = None
    output_current_range: Optional[tuple[float, float]] = None
    adjustability: Optional[str] = None
    settling_time_us: Optional[float] = None
    bandwidth_hz: Optional[float] = None


class VoltageSpec(BaseModel):
    min_v: Optional[float] = None
    typ_v: Optional[float] = None
    max_v: Optional[float] = None
    raw_text: str


class CurrentSpec(BaseModel):
    min_ma: Optional[float] = None
    typ_ma: Optional[float] = None
    max_ma: Optional[float] = None
    raw_text: str


class ProtectionRequirement(BaseModel):
    """A single protection or safety behavior requested in the design prompt."""

    kind: str  # open vocabulary: reverse_current, esd, kelvin_sensing, ...
    params: Optional[dict[str, float]] = None
    raw_text: str


class ElectricalConstraints(BaseModel):
    supply_voltage: Optional[VoltageSpec] = None
    supply_topology: Optional[str] = None
    supply_current_budget: Optional[CurrentSpec] = None
    output_voltage_compliance: Optional[VoltageSpec] = None
    output_current: Optional[CurrentSpec] = None
    power_budget_mw: Optional[float] = None
    input_impedance_ohm: Optional[float] = None
    output_impedance_ohm: Optional[float] = None
    isolation_required: bool = False


class ThermalConstraints(BaseModel):
    operating_temp_min_c: Optional[float] = None
    operating_temp_max_c: Optional[float] = None
    storage_temp_min_c: Optional[float] = None
    storage_temp_max_c: Optional[float] = None
    thermal_matching_required: bool = False
    max_self_heating_c: Optional[float] = None
    thermal_resistance_target_c_per_w: Optional[float] = None


class ManufacturingConstraints(BaseModel):
    assembly_process: Optional[str] = None
    pcb_layers: Optional[int] = None
    board_dimensions_mm: Optional[tuple[float, float]] = None
    min_trace_width_mm: Optional[float] = None
    min_clearance_mm: Optional[float] = None
    surface_finish: Optional[str] = None
    ipc_class: Optional[str] = None


class ReliabilityRequirements(BaseModel):
    mtbf_hours: Optional[float] = None
    operating_environment: Optional[str] = None
    vibration_spec: Optional[str] = None
    shock_spec: Optional[str] = None
    humidity_range_percent: Optional[tuple[float, float]] = None
    altitude_m: Optional[float] = None
    radiation_tolerance: Optional[str] = None


class ComplianceRequirements(BaseModel):
    standards: list[str] = Field(default_factory=list)
    emc_class: Optional[str] = None
    safety_class: Optional[str] = None
    export_control: Optional[str] = None
    country_of_origin_restriction: Optional[str] = None


class CostConstraints(BaseModel):
    bom_budget_usd: Optional[float] = None
    per_unit_target_usd: Optional[float] = None
    production_volume: Optional[ProductionVolume] = None
    prefer_cots: bool = True
    avoid_obsolete: bool = True
    preferred_suppliers: list[str] = Field(default_factory=list)
    blacklisted_suppliers: list[str] = Field(default_factory=list)


class ComponentPreference(BaseModel):
    component_type: str
    preferred_series: Optional[str] = None
    preferred_manufacturer: Optional[str] = None
    required_attribute: Optional[str] = None
    exclusion: Optional[str] = None


class _IntentDictBase(BaseModel):
    """Structured design intent extracted from user prompt.

    Represents the parsed and interpreted design requirements from
    natural language input. Includes frequency requirements, application
    context, constraints, and any detected ambiguities.

    Attributes:
        goal: High-level design objective (e.g., "5V to 3.3V buck regulator")
        frequency: Operating frequency for RF/power designs, None if N/A
        application: Target application domain (e.g., "IoT sensor", "automotive")
        inferred_constraints: System-derived constraints from domain knowledge
        design_methodology: Selected methodology guiding design rules
        board_type: PCB classification (e.g., "2-layer FR4", "4-layer HDI")
        ambiguities: Detected ambiguities requiring clarification
        clarification_required: True if CRITICAL ambiguities exist
        raw_prompt: Original user input for provenance
    """

    model_config = ConfigDict(extra="forbid")

    goal: str = Field(description="High-level design objective")
    frequency: Optional[FrequencySpec] = Field(
        default=None, description="Operating frequency for RF/power designs, None if N/A"
    )
    application: str = Field(description="Target application domain")
    inferred_constraints: list[str] = Field(
        default_factory=list,
        description="System-derived constraints from domain knowledge",
    )
    design_methodology: DesignMethodology = Field(
        description="Selected methodology guiding design rules"
    )
    board_type: str = Field(description="PCB classification (e.g., '2-layer FR4')")
    ambiguities: list[AmbiguityFlag] = Field(
        default_factory=list, description="Detected ambiguities requiring clarification"
    )
    clarification_required: bool = Field(
        default=False,
        description="True if CRITICAL ambiguities exist requiring user input",
    )
    raw_prompt: str = Field(description="Original user input for provenance")


class ImprovedIntentDict(_IntentDictBase):
    """
    IntentDict v2. Extends v1 with typed requirement categories.
    All v1 fields inherited unchanged from _IntentDictBase.
    All new fields have defaults — v1 construction sites work without modification.

    Pipeline must halt before Stage 2 if clarification_required is True and
    any ambiguity has blocking=True. Caller is responsible for enforcement.
    """
    # New v2 fields — ALL have defaults so existing construction sites are unaffected
    goal_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    goal_topologies: list[TopologyGuess] = Field(default_factory=list)
    goal_topology: Optional[str] = None
    performance: Optional[PerformanceRequirements] = None
    electrical: Optional[ElectricalConstraints] = None
    thermal: Optional[ThermalConstraints] = None
    manufacturing: Optional[ManufacturingConstraints] = None
    reliability: Optional[ReliabilityRequirements] = None
    compliance: Optional[ComplianceRequirements] = None
    cost: Optional[CostConstraints] = None
    component_preferences: list[ComponentPreference] = Field(default_factory=list)
    protection_requirements: list[ProtectionRequirement] = Field(default_factory=list)
    implied_requirements: list[ImpliedRequirement] = Field(default_factory=list)
    missing_critical_specs: list[str] = Field(default_factory=list)
    contradictions_detected: list[str] = Field(default_factory=list)
    in_scope_requests: list[DesignRequest] = Field(default_factory=list)
    out_of_scope_requests: list[OutOfScopeRequest] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    parsed_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z"
    )
    parser_version: str = "2.0"
    schema_version: Literal["2.0"] = "2.0"

    @field_validator("raw_prompt")
    @classmethod
    def check_prompt_length(cls, v: str) -> str:
        estimated_tokens = len(v) // 4
        if estimated_tokens > MAX_PROMPT_TOKENS:
            raise ValueError(
                f"raw_prompt exceeds MAX_PROMPT_TOKENS ({MAX_PROMPT_TOKENS}). "
                f"Estimated tokens: {estimated_tokens}. Truncate before passing to parser."
            )
        return v

    @model_validator(mode="after")
    def populate_goal_topology_compat(self) -> Self:
        if self.goal_topologies and self.goal_topology is None:
            self.goal_topology = self.goal_topologies[0].name
        return self

    @model_validator(mode="after")
    def validate_clarification_protocol(self) -> Self:
        if self.clarification_required and not any(a.blocking for a in self.ambiguities):
            raise ValueError(
                "clarification_required=True but no blocking ambiguity found. Set at least "
                "one Ambiguity.blocking=True or set clarification_required=False."
            )
        return self


# Backward-compatibility alias.
# All existing imports of IntentDict continue to work unchanged.
# All existing construction sites IntentDict(...) now construct ImprovedIntentDict.
IntentDict = ImprovedIntentDict


SCHEMA_VERSION = "2.0"


def assert_schema_version(data: dict) -> None:
    version = data.get("schema_version", "1.0")
    if version != SCHEMA_VERSION:
        raise SchemaVersionError(
            f"IntentDict schema version mismatch: expected {SCHEMA_VERSION}, "
            f"got {version}. Re-run Stage 1 parser to upgrade."
        )


class BOMEntry(BaseModel):
    """Single entry in the Bill of Materials.

    Represents one component position in the design with selection
    status, constraints, and provenance. specific_part=None indicates
    the component requires human selection.

    Attributes:
        ref: Reference designator (e.g., "U1", "C3", "R12")
        component_type: Normalized component category (e.g., "regulator", "capacitor")
        specific_part: Selected part number or None if unresolved
        value_constraints: Electrical/physical constraints for selection
        justification: Design rationale for this component position
        source: Origin of this entry (rule, KG lookup, human)
        confidence: Confidence in component selection [0.0, 1.0]
        alternatives: Alternative part numbers if specific_part is set
        review_flag: True if human review recommended
    """

    ref: str = Field(description="Reference designator (e.g., 'U1', 'C3')")
    component_type: str = Field(
        description="Normalized component category (e.g., 'regulator', 'capacitor')"
    )
    specific_part: Optional[str] = Field(
        default=None, description="Selected part number or None if unresolved"
    )
    value_constraints: dict[str, Any] = Field(
        default_factory=dict,
        description="Electrical/physical constraints for selection",
    )
    justification: str = Field(description="Design rationale for this component position")
    source: str = Field(description="Origin of this entry (rule, KG lookup, human)")
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence in component selection [0.0, 1.0]"
    )
    alternatives: list[str] = Field(
        default_factory=list, description="Alternative part numbers if specific_part is set"
    )
    review_flag: bool = Field(
        default=False, description="True if human review recommended"
    )


class ValidatedBOM(BaseModel):
    """Complete Bill of Materials with validation status.

    Root container for the component selection output. Includes the
    design intent, all component entries, cross-component validation
    rules, and aggregated confidence metrics.

    Attributes:
        design_id: Unique identifier for this design
        intent: Parsed design intent that generated this BOM
        components: All component entries in the design
        cross_component_rules: Validation rules spanning multiple components
        total_confidence: Aggregate confidence across all selections
        review_flags: List of validation warning/info messages
        review_required: True if any component or rule needs review
        created_at: ISO 8601 timestamp of BOM creation
    """

    design_id: str = Field(description="Unique identifier for this design")
    intent: ImprovedIntentDict = Field(
        description="Parsed design intent that generated this BOM"
    )
    components: list[BOMEntry] = Field(
        description="All component entries in the design"
    )
    cross_component_rules: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Validation rules spanning multiple components",
    )
    total_confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Aggregate confidence across all selections [0.0, 1.0]",
    )
    review_flags: list[str] = Field(
        default_factory=list,
        description="Validation warning/info messages for human review",
    )
    review_required: bool = Field(
        default=False,
        description="True if any component or rule needs human review",
    )
    created_at: str = Field(description="ISO 8601 timestamp of BOM creation")

    def unresolved_components(self) -> list[BOMEntry]:
        """Return list of components requiring human part selection.

        Filters the components list to return only entries where
        specific_part is None, indicating unresolved selection.

        Returns:
            List of BOMEntry objects with specific_part=None.
        """
        return [c for c in self.components if c.specific_part is None]


__all__ = [
    "FrequencySpec",
    "AmbiguityFlag",
    "DesignMethodology",
    "ConditionScope",
    "NoiseSpec",
    "AccuracySpec",
    "StabilitySpec",
    "PerformanceRequirements",
    "VoltageSpec",
    "CurrentSpec",
    "ProtectionRequirement",
    "ElectricalConstraints",
    "ThermalConstraints",
    "ManufacturingConstraints",
    "ReliabilityRequirements",
    "ComplianceRequirements",
    "CostConstraints",
    "ComponentPreference",
    "ImpliedRequirement",
    "TopologyGuess",
    "DesignRequest",
    "OutOfScopeRequest",
    "ProductionVolume",
    "Ambiguity",
    "SchemaVersionError",
    "SCHEMA_VERSION",
    "MAX_PROMPT_TOKENS",
    "assert_schema_version",
    "ImprovedIntentDict",
    "IntentDict",
    "BOMEntry",
    "ValidatedBOM",
]
