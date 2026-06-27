"""Gate tests for PaddleOCRImageTableBackend."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import numpy as np

from src.config import Config
from src.parsing.backends import ImageTableBackend, ParsingConfig
from src.parsing.backends._registry import BackendRegistry
from src.parsing.backends.image_table._html_to_grid import parse_html_to_grid
from src.parsing.backends.image_table.paddleocr_backend import (
    PaddleOCRImageTableBackend,
)

FAKE_PNG_BYTES = b"\x89PNG\r\n\x1a\nfake"
FAKE_IMAGE_ARRAY = np.zeros((10, 10, 3), dtype=np.uint8)


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


def test_paddleocr_implements_image_table_backend() -> None:
    backend = PaddleOCRImageTableBackend(_make_config())
    assert isinstance(backend, ImageTableBackend)


def test_engine_is_none_at_construction() -> None:
    backend = PaddleOCRImageTableBackend(_make_config())
    assert backend._engine is None


def test_parse_html_to_grid_simple_2x2() -> None:
    html = (
        "<table><tr><td>A</td><td>B</td></tr>"
        "<tr><td>C</td><td>D</td></tr></table>"
    )
    result = parse_html_to_grid(html, "paddleocr")

    assert len(result.cells) == 4
    assert result.cells[0].text == "A"
    assert result.cells[0].row == 0
    assert result.cells[0].col == 0
    assert result.cells[1].text == "B"
    assert result.cells[1].row == 0
    assert result.cells[1].col == 1
    assert result.cells[2].text == "C"
    assert result.cells[2].row == 1
    assert result.cells[2].col == 0
    assert result.cells[3].text == "D"
    assert result.cells[3].row == 1
    assert result.cells[3].col == 1
    assert result.extraction_method == "image"
    assert result.backend_used == "paddleocr"


def test_parse_html_to_grid_colspan() -> None:
    html = (
        "<table><tr><td colspan='2'>MERGED</td></tr>"
        "<tr><td>X</td><td>Y</td></tr></table>"
    )
    result = parse_html_to_grid(html, "paddleocr")
    merged = next(c for c in result.cells if c.text == "MERGED")

    assert merged.col_span == 2
    assert merged.row == 0
    assert merged.col == 0


def test_parse_html_to_grid_empty_html() -> None:
    result = parse_html_to_grid("", "paddleocr")
    assert result.cells == []
    assert result.confidence == 0.0


def _mock_paddleocr_engine(
    return_value: list[dict[str, object]],
) -> tuple[MagicMock, MagicMock]:
    mock_engine = MagicMock()
    mock_engine.return_value = return_value
    mock_paddleocr = MagicMock()
    mock_paddleocr.PPStructure = MagicMock(return_value=mock_engine)
    return mock_paddleocr, mock_engine


def test_extract_with_mocked_ppstructure() -> None:
    mock_paddleocr, _mock_engine = _mock_paddleocr_engine(
        [
            {
                "type": "table",
                "res": {"html": "<table><tr><td>V</td></tr></table>"},
            }
        ]
    )

    with (
        patch.dict(sys.modules, {"paddleocr": mock_paddleocr}),
        patch("cv2.imdecode", return_value=FAKE_IMAGE_ARRAY),
    ):
        backend = PaddleOCRImageTableBackend(_make_config())
        result = backend.extract(FAKE_PNG_BYTES)

    assert len(result.cells) == 1
    assert result.cells[0].text == "V"


def test_extract_no_table_region_returns_empty() -> None:
    mock_paddleocr, _mock_engine = _mock_paddleocr_engine(
        [{"type": "figure", "res": {}}]
    )

    with (
        patch.dict(sys.modules, {"paddleocr": mock_paddleocr}),
        patch("cv2.imdecode", return_value=FAKE_IMAGE_ARRAY),
    ):
        backend = PaddleOCRImageTableBackend(_make_config())
        result = backend.extract(FAKE_PNG_BYTES)

    assert result.cells == []
    assert result.confidence == 0.0


def test_extract_engine_load_failure_returns_empty() -> None:
    mock_paddleocr = MagicMock()
    mock_paddleocr.PPStructure = MagicMock(
        side_effect=ImportError("paddleocr not installed")
    )

    with patch.dict(sys.modules, {"paddleocr": mock_paddleocr}):
        backend = PaddleOCRImageTableBackend(_make_config())
        result = backend.extract(FAKE_PNG_BYTES)

    assert result.cells == []


def test_registry_returns_paddleocr_image_table_backend() -> None:
    registry = BackendRegistry(_make_config())
    backend = registry.get_image_table()
    assert isinstance(backend, PaddleOCRImageTableBackend)
