"""pdfplumber + Camelot vector table extraction backend."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from src.datasheet.phase1_dla._schemas import TableCrop
from src.parsing.backends._interfaces import VectorTableBackend
from src.parsing.backends._schemas import BoundingBox, GridCell, GridMatrix
from src.schemas.datasheet import TableSectionType

if TYPE_CHECKING:
    from src.config import Config

logger = logging.getLogger(__name__)

_extract_table_vector_path_impl = None


def extract_table_vector_path(*args, **kwargs):
    """Lazy proxy to path_a_vector.extract_table_vector_path (patchable in tests)."""
    global _extract_table_vector_path_impl
    if _extract_table_vector_path_impl is None:
        from src.datasheet.phase2_tsr.path_a_vector import (
            extract_table_vector_path as _impl,
        )

        _extract_table_vector_path_impl = _impl
    return _extract_table_vector_path_impl(*args, **kwargs)


class PdfplumberCamelotVectorTableBackend(VectorTableBackend):
    """Wraps Phase 2 Path A vector extraction for the pluggable parsing API."""

    def __init__(self, config: Config) -> None:
        self._config = config

    def _empty_grid(self) -> GridMatrix:
        return GridMatrix(
            cells=[],
            confidence=0.0,
            backend_used="pdfplumber_camelot",
            extraction_method="vector",
        )

    def extract(
        self, pdf_path: str, page_number: int, bbox: BoundingBox
    ) -> GridMatrix:
        """Extract table grid from vector PDF content."""
        try:
            table_crop = TableCrop(
                page_number=page_number,
                section_type=TableSectionType.OTHER,
                image_bytes=b"",
                bounding_box=(bbox.x1, bbox.y1, bbox.x2, bbox.y2),
                heading_text=None,
                is_multipage_continuation=False,
                detection_confidence=1.0,
            )
            internal_grid = extract_table_vector_path(
                pdf_path=Path(pdf_path),
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
                backend_used="pdfplumber_camelot",
                extraction_method="vector",
            )
        except Exception as exc:
            logger.debug(
                "PdfplumberCamelotVectorTableBackend.extract failed: %s", exc
            )
            return self._empty_grid()
