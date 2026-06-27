"""Pluggable parsing backend interfaces and registry."""

from __future__ import annotations

from src.parsing.backends._interfaces import (
    ImageTableBackend,
    LayoutDetectorBackend,
    LLMBackend,
    VectorTableBackend,
    VLMBackend,
)
from src.parsing.backends._registry import BackendRegistry
from src.parsing.backends._schemas import (
    BoundingBox,
    DetectedRegion,
    GridCell,
    GridMatrix,
    LLMResponse,
    ParsingConfig,
    VLMResponse,
)

__all__ = [
    "LayoutDetectorBackend",
    "VectorTableBackend",
    "ImageTableBackend",
    "VLMBackend",
    "LLMBackend",
    "BackendRegistry",
    "BoundingBox",
    "DetectedRegion",
    "GridCell",
    "GridMatrix",
    "VLMResponse",
    "LLMResponse",
    "ParsingConfig",
]
