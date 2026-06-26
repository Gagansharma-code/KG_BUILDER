"""Ingested document schemas for tiered knowledge base ingestion."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class DocumentType(str, Enum):
    IC_DATASHEET = "ic_datasheet"
    APP_NOTE = "app_note"
    RESEARCH_PAPER = "research_paper"
    STANDARD = "standard"
    REFERENCE_DESIGN = "reference_design"
    KICAD_SYMBOL = "kicad_symbol"
    KICAD_FOOTPRINT = "kicad_footprint"
    COMMUNITY_POST = "community_post"


class IngestedDocument(BaseModel):
    model_config = ConfigDict(strict=False)

    document_id: str
    document_type: DocumentType
    source_url: str
    content_hash: str
    ingestion_tier: int
    pipeline_version: str = "1.0"
    ingested_at: str
    review_required: bool = False
    review_flags: list[str] = Field(default_factory=list)


class KiCadPinDef(BaseModel):
    pin_number: str
    pin_name: str
    pin_type: str
    position_x: float
    position_y: float


class KiCadSymbolEntry(IngestedDocument):
    document_type: DocumentType = DocumentType.KICAD_SYMBOL
    symbol_name: str
    library_name: str
    description: Optional[str] = None
    datasheet_url: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)
    pins: list[KiCadPinDef] = Field(default_factory=list)
    properties: dict[str, str] = Field(default_factory=dict)


class KiCadFootprintEntry(IngestedDocument):
    document_type: DocumentType = DocumentType.KICAD_FOOTPRINT
    footprint_name: str
    library_name: str
    description: Optional[str] = None
    pad_count: int
    courtyard_x_mm: float
    courtyard_y_mm: float
    ipc_name: Optional[str] = None


class AppNoteDocument(IngestedDocument):
    document_type: DocumentType = DocumentType.APP_NOTE
    title: str
    document_number: Optional[str] = None
    manufacturer: Optional[str] = None
    topics: list[str] = Field(default_factory=list)
    design_recipes_extracted: int = 0
    placement_rules_extracted: int = 0


class ResearchPaperDocument(IngestedDocument):
    document_type: DocumentType = DocumentType.RESEARCH_PAPER
    title: str
    authors: list[str] = Field(default_factory=list)
    doi: Optional[str] = None
    year: Optional[int] = None
    journal: Optional[str] = None
    equations_extracted: int = 0
    figures_extracted: int = 0


class StandardDocument(IngestedDocument):
    document_type: DocumentType = DocumentType.STANDARD
    standard_body: str
    standard_number: str
    title: str
    revision: Optional[str] = None
    clauses_extracted: int = 0
    tables_extracted: int = 0


class ReferenceDesignDocument(IngestedDocument):
    document_type: DocumentType = DocumentType.REFERENCE_DESIGN
    title: str
    manufacturer: Optional[str] = None
    related_components: list[str] = Field(default_factory=list)
    bom_rows_extracted: int = 0


class CommunityPostDocument(IngestedDocument):
    document_type: DocumentType = DocumentType.COMMUNITY_POST
    title: str
    tags: list[str] = Field(default_factory=list)
    vote_score: int = 0
    is_accepted: bool = False
    post_type: str = "question"
    platform: str = "stack_exchange"


__all__ = [
    "DocumentType",
    "IngestedDocument",
    "KiCadPinDef",
    "KiCadSymbolEntry",
    "KiCadFootprintEntry",
    "AppNoteDocument",
    "ResearchPaperDocument",
    "StandardDocument",
    "ReferenceDesignDocument",
    "CommunityPostDocument",
]
