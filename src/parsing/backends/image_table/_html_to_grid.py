"""Parse PPStructure HTML table output into GridMatrix."""

from __future__ import annotations

import logging
from html.parser import HTMLParser

from src.parsing.backends._schemas import GridCell, GridMatrix

logger = logging.getLogger(__name__)

_OCR_CELL_CONFIDENCE = 0.85


def _empty_grid(backend_used: str) -> GridMatrix:
    return GridMatrix(
        cells=[],
        confidence=0.0,
        backend_used=backend_used,
        extraction_method="image",
    )


class _TableHTMLParser(HTMLParser):
    """Walk HTML table markup and collect GridCell objects."""

    def __init__(self) -> None:
        super().__init__()
        self.cells: list[GridCell] = []
        self.occupied: set[tuple[int, int]] = set()
        self._in_table = False
        self._in_row = False
        self._current_row = -1
        self._cell_attrs: dict[str, str] = {}
        self._cell_text_parts: list[str] = []
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k: v for k, v in attrs if v is not None}
        if tag == "table":
            self._in_table = True
        elif tag == "tr" and self._in_table:
            self._in_row = True
            self._current_row += 1
        elif tag in ("td", "th") and self._in_row:
            self._in_cell = True
            self._cell_attrs = attrs_dict
            self._cell_text_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._in_cell:
            colspan = int(self._cell_attrs.get("colspan", "1"))
            rowspan = int(self._cell_attrs.get("rowspan", "1"))

            col = 0
            while (self._current_row, col) in self.occupied:
                col += 1

            for r in range(rowspan):
                for c in range(colspan):
                    self.occupied.add((self._current_row + r, col + c))

            text = "".join(self._cell_text_parts).strip()
            self.cells.append(
                GridCell(
                    row=self._current_row,
                    col=col,
                    row_span=rowspan,
                    col_span=colspan,
                    text=text,
                    confidence=_OCR_CELL_CONFIDENCE,
                )
            )
            self._in_cell = False
        elif tag == "tr":
            self._in_row = False
        elif tag == "table":
            self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_text_parts.append(data)


def parse_html_to_grid(html: str, backend_used: str) -> GridMatrix:
    """Parse PPStructure HTML output into a structured table grid.

    Args:
        html: HTML table string from PPStructure.
        backend_used: Backend identifier for provenance.

    Returns:
        GridMatrix with parsed cells, or empty grid on failure.
    """
    try:
        if not html or not html.strip():
            return _empty_grid(backend_used)

        parser = _TableHTMLParser()
        parser.feed(html)

        if not parser.cells:
            return _empty_grid(backend_used)

        mean_confidence = sum(c.confidence for c in parser.cells) / len(parser.cells)
        return GridMatrix(
            cells=parser.cells,
            confidence=mean_confidence,
            backend_used=backend_used,
            extraction_method="image",
        )
    except Exception as exc:
        logger.error("Failed to parse HTML table: %s", exc)
        return _empty_grid(backend_used)
