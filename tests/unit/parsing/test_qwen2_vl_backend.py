"""Gate tests for Qwen2VLImageTableBackend."""
from __future__ import annotations

from unittest.mock import patch

from src.config import Config
from src.datasheet.phase2_tsr._schemas import CellValue, GridMatrix as InternalGridMatrix
from src.parsing.backends import BackendRegistry, ImageTableBackend, ParsingConfig
from src.parsing.backends.image_table.paddleocr_backend import (
    PaddleOCRImageTableBackend,
)
from src.parsing.backends.image_table.qwen2_vl_backend import (
    Qwen2VLImageTableBackend,
)
from src.schemas.datasheet import TableSectionType

PATCH_TARGET = (
    "src.parsing.backends.image_table.qwen2_vl_backend.extract_table_vlm_path"
)


def _make_config(*, image_table: str = "qwen2_vl") -> Config:
    return Config(
        parsing=ParsingConfig(
            layout_detector="yolov8",
            vector_table="pdfplumber_camelot",
            image_table=image_table,
            vlm="qwen2_vl",
            llm="qwen25_7b",
        )
    )


def _make_internal_grid(
    cells: list[CellValue],
    confidence: float = 0.95,
) -> InternalGridMatrix:
    return InternalGridMatrix(
        cells=cells,
        num_rows=max((c.row for c in cells), default=0) + 1,
        num_cols=max((c.col for c in cells), default=0) + 1,
        section_type=TableSectionType.OTHER,
        source_page=1,
        source_table_index=0,
        extraction_path="vlm",
        confidence=confidence,
    )


def test_qwen2_vl_implements_image_table_backend() -> None:
    backend = Qwen2VLImageTableBackend(_make_config())
    assert isinstance(backend, ImageTableBackend)


def test_extract_returns_empty_grid_when_internal_returns_none() -> None:
    backend = Qwen2VLImageTableBackend(_make_config())
    with patch(PATCH_TARGET, return_value=None):
        result = backend.extract(b"fake_png")

    assert result.cells == []
    assert result.confidence == 0.0
    assert result.backend_used == "qwen2_vl"
    assert result.extraction_method == "image"


def test_extract_translates_cell_value_list() -> None:
    backend = Qwen2VLImageTableBackend(_make_config())
    internal = _make_internal_grid(
        [
            CellValue(text="Min", row=0, col=0, rowspan=1, colspan=1, is_header=True),
            CellValue(text="1.8", row=1, col=0, rowspan=1, colspan=1, is_header=False),
        ]
    )
    with patch(PATCH_TARGET, return_value=internal):
        result = backend.extract(b"fake_png")

    assert len(result.cells) == 2
    assert result.cells[0].text == "Min"
    assert result.cells[1].text == "1.8"
    assert result.backend_used == "qwen2_vl"
    assert result.extraction_method == "image"


def test_extract_on_exception_returns_empty_grid() -> None:
    backend = Qwen2VLImageTableBackend(_make_config())
    with patch(PATCH_TARGET, side_effect=RuntimeError("vlm failed")):
        result = backend.extract(b"fake_png")

    assert result.cells == []
    assert result.confidence == 0.0


def test_table_crop_passed_to_extract_has_correct_image_bytes() -> None:
    backend = Qwen2VLImageTableBackend(_make_config())
    input_bytes = b"real_table_image_data"
    with patch(PATCH_TARGET, return_value=None) as mock_extract:
        backend.extract(input_bytes)

    table_crop = mock_extract.call_args.kwargs["table_crop"]
    assert table_crop.image_bytes == input_bytes


def test_registry_returns_qwen2_vl_backend() -> None:
    registry = BackendRegistry(_make_config(image_table="qwen2_vl"))
    backend = registry.get_image_table()
    assert isinstance(backend, Qwen2VLImageTableBackend)


def test_swap_paddleocr_and_qwen2_vl_backends() -> None:
    registry_paddle = BackendRegistry(_make_config(image_table="paddleocr"))
    registry_qwen = BackendRegistry(_make_config(image_table="qwen2_vl"))

    paddle_backend = registry_paddle.get_image_table()
    qwen_backend = registry_qwen.get_image_table()

    assert isinstance(paddle_backend, PaddleOCRImageTableBackend)
    assert isinstance(qwen_backend, Qwen2VLImageTableBackend)
    assert isinstance(paddle_backend, ImageTableBackend)
    assert isinstance(qwen_backend, ImageTableBackend)
