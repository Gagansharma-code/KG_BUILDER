"""Internal schemas for knowledge graph triple extraction.

Pydantic models for representing extracted (subject, relation, object) triples
and ingestion results.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from src.schemas.datasheet import ExtractionMethod
from src.schemas.kg import KGRelation


class Triple(BaseModel):
    """An extracted (subject, relation, object) triple from engineering text.

    Represents a single engineering knowledge relationship extracted from
    a source document, with provenance tracking and confidence scoring.

    Attributes:
        subject: The subject entity of the relationship
        relation: The KGRelation type connecting subject to object
        object_text: The object entity (named object_text to avoid Python keyword)
        source_sentence: The original sentence from which this was extracted
        source_document: Document identifier (filename, etc.)
        source_url: URL or path to the source document
        confidence: Confidence score in [0.0, 1.0] for this extraction
        extraction_method: Method used to extract this triple
    """

    model_config = {"extra": "forbid"}

    subject: str = Field(
        description="The subject entity of the relationship",
    )
    relation: KGRelation = Field(
        description="The KGRelation type connecting subject to object",
    )
    object_text: str = Field(
        description="The object entity of the relationship",
    )
    source_sentence: str = Field(
        description="The original sentence from which this was extracted",
    )
    source_document: str = Field(
        description="Document identifier (filename, etc.)",
    )
    source_url: str = Field(
        description="URL or path to the source document",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score in [0.0, 1.0] for this extraction",
    )
    extraction_method: ExtractionMethod = Field(
        description="Method used to extract this triple",
    )


class IngestionResult(BaseModel):
    """Result of ingesting a source document into the knowledge graph.

    Aggregates statistics about the triple extraction and knowledge graph
    update process for a single source document.

    Attributes:
        source_document: The document that was processed
        triples_extracted: Number of triples successfully extracted
        nodes_created: Number of new KGNode objects created
        edges_created: Number of new KGEdge objects created
        skipped_low_confidence: Number of triples filtered for low confidence
        errors: List of error messages encountered
        success: True if ingestion completed without critical errors
    """

    model_config = {"extra": "forbid"}

    source_document: str = Field(
        description="The document that was processed",
    )
    content_hash: Optional[str] = Field(
        default=None,
        description="SHA-256 hash of the source document for deduplication",
    )
    document_type: Optional[str] = Field(
        default=None,
        description="DocumentType enum value as string (e.g., 'app_note', 'research_paper')",
    )
    ingestion_tier: Optional[int] = Field(
        default=None,
        ge=0,
        le=3,
        description="Which parser tier processed this document (0=structured, 1=heavy, 2=medium, 3=light)",
    )
    source_url: Optional[str] = Field(
        default=None,
        description="Original URL or file path of the source document",
    )
    triples_extracted: int = Field(
        default=0,
        ge=0,
        description="Number of triples successfully extracted",
    )
    nodes_created: int = Field(
        default=0,
        ge=0,
        description="Number of new KGNode objects created",
    )
    edges_created: int = Field(
        default=0,
        ge=0,
        description="Number of new KGEdge objects created",
    )
    skipped_low_confidence: int = Field(
        default=0,
        ge=0,
        description="Number of triples filtered for low confidence",
    )
    errors: list[str] = Field(
        default_factory=list,
        description="List of error messages encountered",
    )
    success: bool = Field(
        default=True,
        description="True if ingestion completed without critical errors",
    )


class ScrapedChapter(BaseModel):
    """A scraped chapter from All About Circuits textbook.

    Represents a single chapter from the AAC textbook volumes,
    containing cleaned text content and metadata for ingestion into KG-1.

    Attributes:
        volume: Volume number (1-3, 5)
        chapter_number: Chapter number within the volume
        chapter_title: Title of the chapter
        url: Full URL where the chapter was scraped from
        text: Cleaned plain text content (no HTML)
        content_hash: SHA-256 hash of text for cache checking
        word_count: Number of words in the cleaned text
        scraped_at: ISO 8601 timestamp of when chapter was scraped
    """

    model_config = {"extra": "forbid"}

    volume: int = Field(
        ge=1,
        le=6,
        description="Volume number (1-3, 5)",
    )
    chapter_number: int = Field(
        ge=1,
        description="Chapter number within the volume",
    )
    chapter_title: str = Field(
        description="Title of the chapter",
    )
    url: str = Field(
        description="Full URL where the chapter was scraped from",
    )
    text: str = Field(
        description="Cleaned plain text content (no HTML)",
    )
    content_hash: str = Field(
        description="SHA-256 hash of text for cache checking",
    )
    word_count: int = Field(
        ge=0,
        description="Number of words in the cleaned text",
    )
    scraped_at: str = Field(
        description="ISO 8601 timestamp of when chapter was scraped",
    )
