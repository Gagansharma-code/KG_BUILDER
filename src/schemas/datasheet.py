"""ComponentDatasheet schema — Team A output contract.

Team B, D consume this. Do not modify without sign-off from all consumers.

This module defines the Pydantic models for the extracted datasheet output.
These schemas represent the structured data extracted from PDF datasheets
and serve as the output contract between the extraction pipeline (Team A)
and downstream consumers including the knowledge graph builder (Team B)
and PCB design automation systems (Team D).

Changes to these models require:
1. Update to all consuming code
2. Update to ground truth annotation format
3. Version bump in pipeline_version field
4. Sign-off from all team leads
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TableSectionType(str, Enum):
    """Classification of datasheet table sections.

    Used by Phase 1 to label extracted table crops based on
    section heading text and positional heuristics.
    """

    ELECTRICAL_CHARACTERISTICS = "electrical_characteristics"
    ABSOLUTE_MAXIMUM_RATINGS = "absolute_maximum_ratings"
    PINOUT = "pinout"
    TIMING = "timing"
    ORDERING = "ordering"
    LAYOUT_RECOMMENDATIONS = "layout_recommendations"
    OTHER = "other"


class ExtractionMethod(str, Enum):
    """Method used to extract data from the datasheet.

    Tracked for provenance, debugging, and confidence weighting.
    """

    P1_VECTOR = "p1_vector"  # pdfplumber/Camelot deterministic
    P1_VLM = "p1_vlm"  # Qwen2-VL
    P1_PHASE5_NLP = "p1_phase5_nlp"  # layout section NLP extraction
    MANUAL = "manual"
    LLM_FALLBACK = "llm_fallback"
    NOUGAT = "nougat"                        # equation/text extraction from academic PDFs
    HTML_PARSE = "html_parse"                # HTML stripping for community content
    SEXPRESSION_PARSE = "sexpression_parse"  # KiCad .kicad_sym / .kicad_mod parser
    PDF_TEXT_EXTRACT = "pdf_text_extract"    # pdfplumber direct text extraction (Tier 2)
    KICAD_LIBRARY = "kicad_library"          # KiCad official library ingestion


# Maps extraction method to base confidence score for KG edges/nodes
EXTRACTION_METHOD_CONFIDENCE: dict[ExtractionMethod, float] = {
    ExtractionMethod.MANUAL: 1.0,
    ExtractionMethod.P1_VECTOR: 0.97,
    ExtractionMethod.P1_VLM: 0.85,
    ExtractionMethod.P1_PHASE5_NLP: 0.80,
    ExtractionMethod.LLM_FALLBACK: 0.72,
    ExtractionMethod.NOUGAT: 0.88,
    ExtractionMethod.HTML_PARSE: 0.90,
    ExtractionMethod.SEXPRESSION_PARSE: 0.99,
    ExtractionMethod.PDF_TEXT_EXTRACT: 0.82,
    ExtractionMethod.KICAD_LIBRARY: 0.99,
}


class ExtractedValue(BaseModel):
    """Atomic value with full provenance from datasheet extraction.

    Represents a single extracted value with its raw text, normalized form,
    unit, and confidence metadata. Used as a building block for parameters
    and ratings.
    """

    model_config = ConfigDict(strict=False)

    raw_text: str = Field(
        description="Original cell text exactly as extracted from datasheet"
    )
    normalized_value: Optional[float] = Field(
        default=None, description="Normalized numeric value after unit conversion"
    )
    unit: Optional[str] = Field(
        default=None,
        description="Canonical unit from conversion (V, A, Ω, Hz, °C, etc.)",
    )
    min_val: Optional[float] = Field(
        default=None, description="Minimum value in the range, if specified"
    )
    typ_val: Optional[float] = Field(
        default=None, description="Typical value in the range, if specified"
    )
    max_val: Optional[float] = Field(
        default=None, description="Maximum value in the range, if specified"
    )
    footnote: Optional[str] = Field(
        default=None,
        description="Linked footnote text if superscript reference detected",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score from extraction phase [0.0, 1.0]",
    )

    @field_validator("confidence")
    @classmethod
    def validate_confidence_range(cls, v: float) -> float:
        """Ensure confidence is within valid range [0.0, 1.0].

        Args:
            v: Confidence value to validate.

        Returns:
            Validated confidence value.

        Raises:
            ValueError: If confidence is outside [0.0, 1.0].
        """
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Confidence must be in [0.0, 1.0], got {v}")
        return v


class ElectricalParameter(BaseModel):
    """Single electrical characteristic parameter from datasheet.

    Represents one row from an electrical characteristics table,
    including parameter name, test conditions, and measured values
    (min, typ, max) with full provenance.
    """

    parameter_name: str = Field(
        description="Parameter name as printed in datasheet (e.g., 'V_CC', 'I_Q')"
    )
    symbol: Optional[str] = Field(
        default=None,
        description="Standard symbol for the parameter if different from name",
    )
    conditions: Optional[str] = Field(
        default=None,
        description="Test conditions (e.g., 'T_A = 25°C, V_CC = 3.3V')",
    )
    value: ExtractedValue = Field(
        description="Extracted value with normalized form and confidence"
    )
    section_type: TableSectionType = Field(
        description="Classification of the section this parameter came from"
    )
    source_page: int = Field(
        ge=1, description="Page number in source PDF (1-indexed)"
    )
    source_table_index: int = Field(
        ge=0,
        description="Index of the table on this page (0-indexed within page)",
    )
    review_required: bool = Field(
        default=False,
        description="True if confidence below threshold or validation failed",
    )


class AbsoluteMaxRating(BaseModel):
    """Absolute maximum rating constraint from datasheet.

    Represents a single absolute maximum rating that must not be exceeded
    to prevent permanent damage to the device. Phase 4 validation ensures
    these always exceed recommended operating maximums.
    """

    parameter_name: str = Field(
        description="Parameter name (e.g., 'V_CC_ABS', 'T_J_MAX')"
    )
    symbol: Optional[str] = Field(
        default=None, description="Standard symbol if different from name"
    )
    value: ExtractedValue = Field(
        description="Extracted value (max_val is the absolute ceiling)"
    )
    note: Optional[str] = Field(
        default=None,
        description="Additional note or warning text from datasheet",
    )
    source_page: int = Field(ge=1, description="Page number in source PDF")
    review_required: bool = Field(
        default=False,
        description="True if confidence below threshold",
    )


class PinDefinition(BaseModel):
    """Single pin definition from pinout table.

    Represents one row from a pinout/pin configuration table,
    including pin number, name, type, and alternate functions.
    Normalized function names are set by Phase 2 (Problem 2 pipeline).
    """

    pin_number: str = Field(
        description="Pin identifier (e.g., '1', 'A3', 'GND_PAD', 'VSS')"
    )
    raw_name: str = Field(
        description="Pin name exactly as printed in datasheet (e.g., 'V_CC', 'GPIO0/UART_TX')"
    )
    normalized_function: Optional[str] = Field(
        default=None,
        description="Normalized net name set by P2 Phase 2 — None until normalized",
    )
    normalization_confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence in the normalization mapping [0.0, 1.0]",
    )
    normalization_method: Optional[str] = Field(
        default=None,
        description="Method used for normalization (e.g., 'exact_match', 'llm_map')",
    )
    pin_type: Optional[str] = Field(
        default=None,
        description="Pin type: input, output, power, ground, io, nc, clock, reset",
    )
    description: Optional[str] = Field(
        default=None, description="Additional description from datasheet"
    )
    alternate_functions: list[str] = Field(
        default_factory=list,
        description="Alternate functions for multiplexed pins (e.g., ['UART_TX', 'SPI_MOSI'])",
    )
    source_page: int = Field(
        default=0, ge=0, description="Page number where this pin was defined"
    )


class PlacementConstraint(BaseModel):
    """Phase 5 output — layout section extraction constraint.

    Represents a placement or routing constraint extracted from layout
    recommendations sections of the datasheet. Used by PCB auto-placement
    to ensure compliance with manufacturer guidelines.
    """

    constraint_type: str = Field(
        description="Type of constraint: proximity, keepout, layer, orientation"
    )
    subject: str = Field(
        description="Component or pin this constraint applies to"
    )
    relative_to: str = Field(
        description="What the constraint is measured against"
    )
    relative_to_type: str = Field(
        description="Type of relative_to target: component, pin, board_edge — BS-2 fix"
    )
    max_distance_mm: Optional[float] = Field(
        default=None, ge=0.0, description="Maximum allowed distance in millimeters"
    )
    min_distance_mm: Optional[float] = Field(
        default=None, ge=0.0, description="Minimum required distance in millimeters"
    )
    layer: Optional[str] = Field(
        default=None,
        description="Layer constraint applies to: top, bottom, any, specific_layer",
    )
    hard: bool = Field(
        default=True,
        description="True if constraint is mandatory, False if recommendation",
    )
    source_sentence: str = Field(
        description="Original text this constraint was extracted from"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in extraction accuracy [0.0, 1.0]",
    )

    @field_validator("relative_to_type")
    @classmethod
    def validate_relative_to_type(cls, v: str) -> str:
        """Validate that relative_to_type is one of the three valid types.

        Args:
            v: The relative_to_type value to validate.

        Returns:
            The validated value.

        Raises:
            ValueError: If the value is not one of: component, pin, board_edge.
        """
        valid_types = {"component", "pin", "board_edge"}
        if v not in valid_types:
            raise ValueError(
                f"relative_to_type must be one of {valid_types}, got '{v}'"
            )
        return v


class ComponentDatasheet(BaseModel):
    """Complete extracted datasheet — root output schema.

    This is the primary output contract from the datasheet extraction
    pipeline. Contains all extracted data from a single component datasheet
    including electrical parameters, absolute maximum ratings, pinouts,
    and layout constraints with full provenance metadata.
    """

    model_config = ConfigDict(strict=False)

    # Identity fields
    component_id: str = Field(
        description="Unique component identifier (e.g., 'TPS62933DRLR', 'LM358')"
    )
    manufacturer: str = Field(
        description="Manufacturer name (e.g., 'Texas Instruments', 'Analog Devices')"
    )
    description: str = Field(
        description="Component description from datasheet header"
    )
    package: str = Field(
        description="IPC-7351 normalized footprint name. Must be one of: "
        "SOT-23-5, SOT-23-3, SOIC-8, SOIC-16, QFN-16, 0402, 0603, 0805, "
        "DIP-8, TO-220, TSSOP-8, etc. Never store raw datasheet text here."  # BS-1 fix
    )
    datasheet_url: Optional[str] = Field(
        default=None, description="URL to original datasheet if available"
    )
    source_pdf_hash: str = Field(
        description="SHA-256 hash of source PDF for provenance tracking"
    )

    # Extracted data
    electrical_parameters: list[ElectricalParameter] = Field(
        default_factory=list,
        description="All extracted electrical characteristics",
    )
    absolute_max_ratings: list[AbsoluteMaxRating] = Field(
        default_factory=list,
        description="All extracted absolute maximum ratings",
    )
    pins: list[PinDefinition] = Field(
        default_factory=list, description="All extracted pin definitions"
    )
    layout_constraints: list[PlacementConstraint] = Field(
        default_factory=list,
        description="Phase 5: layout recommendation constraints",
    )

    # Metadata
    extraction_method: ExtractionMethod = Field(
        description="Primary method used for extraction"
    )
    extraction_confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Overall confidence in extraction [0.0, 1.0]",
    )
    review_required: bool = Field(
        default=False,
        description="True if any field requires human review",
    )
    review_flags: list[str] = Field(
        default_factory=list,
        description="List of specific flags indicating review reasons",
    )
    pipeline_version: str = Field(
        default="1.0",
        description="Version of extraction pipeline that produced this output",
    )
    created_at: str = Field(
        description="ISO 8601 timestamp of extraction completion"
    )

    def has_layout_constraints(self) -> bool:
        """Check if this datasheet has any layout constraints.

        Returns:
            True if layout_constraints list is non-empty, False otherwise.
        """
        return len(self.layout_constraints) > 0

    def get_pin_by_number(self, pin_number: str) -> Optional[PinDefinition]:
        """Retrieve a pin definition by its pin number.

        Args:
            pin_number: The pin identifier to search for (e.g., '1', 'A3').

        Returns:
            PinDefinition matching the pin_number, or None if not found.
        """
        return next((p for p in self.pins if p.pin_number == pin_number), None)

    def get_pin_by_raw_name(self, raw_name: str) -> Optional[PinDefinition]:
        """Retrieve a pin definition by its raw name.

        Args:
            raw_name: The raw pin name to search for (e.g., 'V_CC', 'GPIO0').

        Returns:
            PinDefinition matching the raw_name, or None if not found.
        """
        return next((p for p in self.pins if p.raw_name == raw_name), None)


__all__ = [
    "TableSectionType",
    "ExtractionMethod",
    "EXTRACTION_METHOD_CONFIDENCE",
    "ExtractedValue",
    "ElectricalParameter",
    "AbsoluteMaxRating",
    "PinDefinition",
    "PlacementConstraint",
    "ComponentDatasheet",
]
