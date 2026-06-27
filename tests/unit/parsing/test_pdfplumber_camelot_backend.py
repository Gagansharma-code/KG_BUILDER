"""Gate tests for PdfplumberCamelotVectorTableBackend."""
from __future__ import annotations

from unittest.mock import patch

from src.config import Config
from src.datasheet.phase2_tsr._schemas import CellValue, GridMatrix as InternalGridMatrix
from src.parsing.backends import (
    BackendRegistry,
    BoundingBox,
    ParsingConfig,
    VectorTableBackend,
)
from src.parsing.backends.vector_table.pdfplumber_camelot_backend import (
    PdfplumberCamelotVectorTableBackend,
)
from src.schemas.datasheet import TableSectionType


def _make_config() -> Config:
    return Config(
        parsing=ParsingConfig(
            layout_detector="yolov8",
            vector_table="pdfplumber_camelot",
            image_table="paddleocr",
            vlm="qwen2_vl",
            llm="qwen25_7b",
        )
    )


def _make_internal_grid(
    cells: list[CellValue],
    confidence: float = 0.97,
) -> InternalGridMatrix:
    return InternalGridMatrix(
        cells=cells,
        num_rows=max((c.row for c in cells), default=0) + 1,
        num_cols=max((c.col for c in cells), default=0) + 1,
        section_type=TableSectionType.OTHER,
        source_page=1,
        source_table_index=0,
        extraction_path="vector",
        confidence=confidence,
    )


def test_pdfplumber_camelot_implements_vector_table_backend() -> None:
    backend = PdfplumberCamelotVectorTableBackend(_make_config())
    assert isinstance(backend, VectorTableBackend)


def test_extract_returns_empty_grid_when_internal_returns_none() -> None:
    backend = PdfplumberCamelotVectorTableBackend(_make_config())
    bbox = BoundingBox(x1=0, y1=0, x2=100, y2=100, page_number=1, confidence=0.9)
    with patch(
        "src.parsing.backends.vector_table.pdfplumber_camelot_backend."
        "extract_table_vector_path",
        return_value=None,
    ):
        result = backend.extract("fake.pdf", 1, bbox)

    assert result.cells == []
    assert result.confidence == 0.0
    assert result.backend_used == "pdfplumber_camelot"
    assert result.extraction_method == "vector"


def test_extract_translates_cell_value_list() -> None:
    backend = PdfplumberCamelotVectorTableBackend(_make_config())
    internal = _make_internal_grid(
        [
            CellValue(
                text="Parameter", row=0, col=0, rowspan=1, colspan=1, is_header=True
            ),
            CellValue(text="3.3V", row=1, col=0, rowspan=1, colspan=1, is_header=False),
        ]
    )
    bbox = BoundingBox(x1=0, y1=0, x2=200, y2=200, page_number=1, confidence=0.9)
    with patch(
        "src.parsing.backends.vector_table.pdfplumber_camelot_backend."
        "extract_table_vector_path",
        return_value=internal,
    ):
        result = backend.extract("fake.pdf", 1, bbox)

    assert len(result.cells) == 2
    assert result.cells[0].text == "Parameter"
    assert result.cells[0].row == 0
    assert result.cells[1].text == "3.3V"
    assert result.confidence == internal.confidence
    assert result.extraction_method == "vector"


def test_extract_propagates_rowspan_and_colspan() -> None:
    backend = PdfplumberCamelotVectorTableBackend(_make_config())
    internal = _make_internal_grid(
        [
            CellValue(
                text="MERGED", row=0, col=0, rowspan=2, colspan=3, is_header=True
            ),
        ]
    )
    bbox = BoundingBox(x1=0, y1=0, x2=200, y2=200, page_number=1, confidence=0.9)
    with patch(
        "src.parsing.backends.vector_table.pdfplumber_camelot_backend."
        "extract_table_vector_path",
        return_value=internal,
    ):
        result = backend.extract("fake.pdf", 1, bbox)

    assert result.cells[0].row_span == 2
    assert result.cells[0].col_span == 3


def test_extract_on_exception_returns_empty_grid() -> None:
    backend = PdfplumberCamelotVectorTableBackend(_make_config())
    bbox = BoundingBox(x1=0, y1=0, x2=100, y2=100, page_number=1, confidence=0.9)
    with patch(
        "src.parsing.backends.vector_table.pdfplumber_camelot_backend."
        "extract_table_vector_path",
        side_effect=RuntimeError("camelot failed"),
    ):
        result = backend.extract("fake.pdf", 1, bbox)

    assert result.cells == []
    assert result.confidence == 0.0


def test_registry_returns_pdfplumber_camelot_backend() -> None:
    registry = BackendRegistry(_make_config())
    backend = registry.get_vector_table()
    assert isinstance(backend, PdfplumberCamelotVectorTableBackend)


def test_table_crop_page_number_matches_extract_argument() -> None:
    backend = PdfplumberCamelotVectorTableBackend(_make_config())
    bbox = BoundingBox(x1=0, y1=0, x2=100, y2=100, page_number=1, confidence=0.9)
    with patch(
        "src.parsing.backends.vector_table.pdfplumber_camelot_backend."
        "extract_table_vector_path",
        return_value=None,
    ) as mock_extract:
        backend.extract("fake.pdf", 1, bbox)

    table_crop = mock_extract.call_args.kwargs["table_crop"]
    assert table_crop.page_number == 1
