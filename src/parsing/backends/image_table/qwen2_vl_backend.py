"""Qwen2-VL image table extraction backend."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from src.datasheet.phase1_dla._schemas import TableCrop
from src.parsing.backends._interfaces import ImageTableBackend
from src.parsing.backends._schemas import GridCell, GridMatrix
from src.schemas.datasheet import TableSectionType

if TYPE_CHECKING:
    from src.config import Config

logger = logging.getLogger(__name__)

_extract_table_vlm_path_impl = None


def extract_table_vlm_path(*args, **kwargs):
    """Lazy proxy to path_b_vlm.extract_table_vlm_path (patchable in tests)."""
    global _extract_table_vlm_path_impl
    if _extract_table_vlm_path_impl is None:
        from src.datasheet.phase2_tsr.path_b_vlm import (
            extract_table_vlm_path as _impl,
        )

        _extract_table_vlm_path_impl = _impl
    return _extract_table_vlm_path_impl(*args, **kwargs)


class Qwen2VLImageTableBackend(ImageTableBackend):
    """Wraps Phase 2 Path B VLM extraction for the pluggable parsing API."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._model_key = config.parsing.qwen2_vl_config.model_key

    def _empty_grid(self) -> GridMatrix:
        return GridMatrix(
            cells=[],
            confidence=0.0,
            backend_used="qwen2_vl",
            extraction_method="image",
        )

    def extract(self, crop_image: bytes) -> GridMatrix:
        """Extract table grid from a cropped table image via Qwen2-VL."""
        try:
            table_crop = TableCrop.model_construct(
                page_number=0,
                section_type=TableSectionType.OTHER,
                image_bytes=crop_image,
                bounding_box=(0, 0, 0, 0),
                heading_text=None,
                is_multipage_continuation=False,
                detection_confidence=1.0,
            )
            internal_grid = extract_table_vlm_path(
                pdf_path=Path(""),
                table_crop=table_crop,
                table_index=0,
                config=self._config,
            )
            if internal_grid is None:
                return self._empty_grid()

            translated_cells = [
                GridCell(
                    row=cell.row,
                    col=cell.col,
                    row_span=cell.rowspan,
                    col_span=cell.colspan,
                    text=cell.text,
                    confidence=internal_grid.confidence,
                )
                for cell in internal_grid.cells
            ]
            return GridMatrix(
                cells=translated_cells,
                confidence=internal_grid.confidence,
                backend_used="qwen2_vl",
                extraction_method="image",
            )
        except Exception as exc:
            logger.error("Qwen2VLImageTableBackend.extract failed: %s", exc)
            return self._empty_grid()
