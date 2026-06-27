"""Abstract base classes for pluggable parsing backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.parsing.backends._schemas import (
    BoundingBox,
    DetectedRegion,
    GridMatrix,
    LLMResponse,
    VLMResponse,
)


class LayoutDetectorBackend(ABC):
    """Finds regions (tables, figures, footnotes) on a rasterized page image."""

    @abstractmethod
    def detect(self, page_image: bytes, page_number: int) -> list[DetectedRegion]:
        """Detect layout regions on a rasterized page.

        Args:
            page_image: PNG bytes of one full page at 300 DPI
            page_number: 0-indexed page number

        Returns:
            List of DetectedRegion, one per found region.
            Empty list if nothing found — never raises.
        """


class VectorTableBackend(ABC):
    """Extracts table structure from vector PDF data (no image needed)."""

    @abstractmethod
    def extract(
        self, pdf_path: str, page_number: int, bbox: BoundingBox
    ) -> GridMatrix:
        """Extract table grid from vector PDF content.

        Args:
            pdf_path: Absolute path to source PDF
            page_number: 0-indexed page number
            bbox: Bounding box of the table region

        Returns:
            GridMatrix. On failure returns GridMatrix with empty cells and
            confidence=0.0
        """


class ImageTableBackend(ABC):
    """Extracts table structure from a cropped table image (OCR/VLM path)."""

    @abstractmethod
    def extract(self, crop_image: bytes) -> GridMatrix:
        """Extract table grid from a cropped table image.

        Args:
            crop_image: PNG bytes of the cropped table region

        Returns:
            GridMatrix. On failure returns GridMatrix with empty cells and
            confidence=0.0
        """


class VLMBackend(ABC):
    """Runs a vision-language model on an image with a text prompt."""

    @abstractmethod
    def query(self, image: bytes, prompt: str) -> VLMResponse:
        """Run a VLM query on an image.

        Args:
            image: PNG bytes of the image (figure, diagram, etc.)
            prompt: Instruction prompt for the VLM

        Returns:
            VLMResponse with raw text and optionally structured_data
        """


class LLMBackend(ABC):
    """Runs a language model for structured semantic extraction."""

    @abstractmethod
    def extract(
        self, text: str, system_prompt: str, output_schema: dict[str, Any]
    ) -> LLMResponse:
        """Extract structured data from text via an LLM.

        Args:
            text: Input text or grid to extract from
            system_prompt: Instruction for the model
            output_schema: JSON Schema dict describing expected output

        Returns:
            LLMResponse with parsed_json matching output_schema when possible
        """
