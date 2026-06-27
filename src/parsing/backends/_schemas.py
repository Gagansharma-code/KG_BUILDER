"""Pydantic models that flow between parsing pipeline stages.

All backends consume and produce these types — never raw dicts.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class BoundingBox(BaseModel):
    """Pixel-space bounding box on a rasterized page."""

    x1: int
    y1: int
    x2: int
    y2: int
    page_number: int
    confidence: float = Field(ge=0.0, le=1.0)


class DetectedRegion(BaseModel):
    """One region detected on a page — table, figure, footnote, etc."""

    region_type: str  # "table", "figure", "footnote", "text_block"
    bbox: BoundingBox
    crop_image: Optional[bytes] = None  # PNG bytes of the cropped region


class GridCell(BaseModel):
    """One cell in an extracted table grid."""

    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    text: str
    confidence: float = Field(ge=0.0, le=1.0)


class GridMatrix(BaseModel):
    """Full structured grid from a table extraction backend."""

    cells: list[GridCell]
    confidence: float = Field(ge=0.0, le=1.0)
    backend_used: str  # which backend produced this
    extraction_method: str  # "vector" or "image"


class VLMResponse(BaseModel):
    """Free-form structured response from a VLM."""

    raw_text: str
    structured_data: Optional[dict[str, Any]] = None
    confidence: float = Field(ge=0.0, le=1.0)
    backend_used: str


class LLMResponse(BaseModel):
    """Structured JSON response from an LLM extraction call."""

    raw_text: str
    parsed_json: Optional[dict[str, Any]] = None
    confidence: float = Field(ge=0.0, le=1.0)
    backend_used: str


class LayoutDetectorConfig(BaseModel):
    """Backend-specific settings for the layout detector."""

    model_config = ConfigDict(extra="forbid")

    confidence_min: float = Field(default=0.55, ge=0.0, le=1.0)


class ImageTableConfig(BaseModel):
    """Backend-specific settings for image table extraction."""

    model_config = ConfigDict(extra="forbid")

    lang: str = "en"
    use_gpu: bool = False


class VectorTableConfig(BaseModel):
    """Backend-specific settings for vector table extraction."""

    model_config = ConfigDict(extra="forbid")

    flavor: str = "lattice"


class Qwen2VLConfig(BaseModel):
    """Backend-specific settings for Qwen2-VL image table extraction."""

    model_config = ConfigDict(extra="forbid")

    model_key: str = "qwen2_vl_7b"


class LLMConfig(BaseModel):
    """Backend-specific settings for LLM extraction."""

    model_config = ConfigDict(extra="forbid")

    model_key: str = "qwen25_7b"
    device: str = "cpu"
    max_tokens: int = 1024


class ParsingConfig(BaseModel):
    """Backend name selections for the parsing pipeline."""

    model_config = ConfigDict(extra="forbid")

    layout_detector: str = "yolov8"
    vector_table: str = "pdfplumber_camelot"
    image_table: str = "paddleocr"
    vlm: str = "qwen2_vl"
    llm: str = "qwen25_7b"
    layout_detector_config: LayoutDetectorConfig = Field(
        default_factory=LayoutDetectorConfig
    )
    image_table_config: ImageTableConfig = Field(default_factory=ImageTableConfig)
    vector_table_config: VectorTableConfig = Field(default_factory=VectorTableConfig)
    qwen2_vl_config: Qwen2VLConfig = Field(default_factory=Qwen2VLConfig)
    llm_config: LLMConfig = Field(default_factory=LLMConfig)
    phase2_vector_confidence_min: float = Field(default=0.80, ge=0.0, le=1.0)
