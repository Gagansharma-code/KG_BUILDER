"""Gate tests for YOLOv8LayoutDetector backend wrapper."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.config import Config
from src.parsing.backends import LayoutDetectorBackend, ParsingConfig
from src.parsing.backends._registry import BackendRegistry
from src.parsing.backends.layout.yolov8_backend import YOLOv8LayoutDetector

FAKE_PNG_BYTES = b"\x89PNG\r\n\x1a\nfake"
SENTINEL_MODEL = object()


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


def test_yolov8_implements_layout_detector_backend() -> None:
    detector = YOLOv8LayoutDetector(_make_config())
    assert isinstance(detector, LayoutDetectorBackend)


def test_model_not_loaded_at_construction() -> None:
    detector = YOLOv8LayoutDetector(_make_config())
    assert detector._model is None


@patch("src.parsing.backends.layout.yolov8_backend.Image.open")
@patch("src.parsing.backends.layout.yolov8_backend._crop_region", return_value=b"fake_png")
@patch("src.parsing.backends.layout.yolov8_backend._detect_tables")
@patch("src.parsing.backends.layout.yolov8_backend._load_yolo_model")
def test_detect_returns_correct_detected_regions(
    mock_load: MagicMock,
    mock_detect: MagicMock,
    mock_crop: MagicMock,
    mock_image_open: MagicMock,
) -> None:
    mock_load.return_value = SENTINEL_MODEL
    mock_image_open.return_value = MagicMock()
    mock_detect.return_value = [
        {
            "bounding_box": (10, 20, 100, 200),
            "confidence": 0.9,
            "class_id": 3,
        },
        {
            "bounding_box": (5, 5, 50, 50),
            "confidence": 0.8,
            "class_id": 4,
        },
    ]

    detector = YOLOv8LayoutDetector(_make_config())
    regions = detector.detect(FAKE_PNG_BYTES, page_number=0)

    assert len(regions) == 2
    assert regions[0].region_type == "table"
    assert regions[1].region_type == "footnote"
    assert regions[0].bbox.page_number == 0
    assert regions[1].bbox.page_number == 0
    assert regions[0].crop_image == b"fake_png"
    assert regions[1].crop_image == b"fake_png"
    mock_load.assert_called_once()
    mock_detect.assert_called_once()


@patch("src.parsing.backends.layout.yolov8_backend._load_yolo_model")
def test_detect_returns_empty_on_model_load_failure(mock_load: MagicMock) -> None:
    mock_load.side_effect = FileNotFoundError("model missing")

    detector = YOLOv8LayoutDetector(_make_config())
    result = detector.detect(FAKE_PNG_BYTES, 0)

    assert result == []


@patch("src.parsing.backends.layout.yolov8_backend._detect_tables")
@patch("src.parsing.backends.layout.yolov8_backend._load_yolo_model")
def test_detect_returns_empty_on_detection_failure(
    mock_load: MagicMock,
    mock_detect: MagicMock,
) -> None:
    mock_load.return_value = SENTINEL_MODEL
    mock_detect.side_effect = RuntimeError("inference failed")

    detector = YOLOv8LayoutDetector(_make_config())
    result = detector.detect(FAKE_PNG_BYTES, 0)

    assert result == []


def test_registry_returns_yolov8_layout_detector() -> None:
    registry = BackendRegistry(_make_config())
    detector = registry.get_layout_detector()
    assert isinstance(detector, YOLOv8LayoutDetector)


def test_registry_caches_yolov8_layout_detector() -> None:
    registry = BackendRegistry(_make_config())
    first = registry.get_layout_detector()
    second = registry.get_layout_detector()
    assert first is second
