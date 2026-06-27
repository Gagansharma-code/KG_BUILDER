"""Image table backend implementations."""

from __future__ import annotations

from src.parsing.backends.image_table.paddleocr_backend import (
    PaddleOCRImageTableBackend,
)
from src.parsing.backends.image_table.qwen2_vl_backend import (
    Qwen2VLImageTableBackend,
)

__all__ = ["PaddleOCRImageTableBackend", "Qwen2VLImageTableBackend"]
