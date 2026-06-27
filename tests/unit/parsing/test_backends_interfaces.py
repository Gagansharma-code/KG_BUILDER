"""Gate tests for pluggable parsing backend interfaces and registry."""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from src.config import Config
from src.parsing.backends import (
    BackendRegistry,
    BoundingBox,
    DetectedRegion,
    GridMatrix,
    ImageTableBackend,
    LayoutDetectorBackend,
    LLMBackend,
    LLMResponse,
    ParsingConfig,
    VectorTableBackend,
    VLMBackend,
    VLMResponse,
)


# ── Stub implementations (no heavy dependencies) ─────────────────────────────


class StubLayoutDetector(LayoutDetectorBackend):
    def detect(self, page_image: bytes, page_number: int) -> list[DetectedRegion]:
        return []


class StubVectorTable(VectorTableBackend):
    def extract(
        self, pdf_path: str, page_number: int, bbox: BoundingBox
    ) -> GridMatrix:
        return GridMatrix(
            cells=[],
            confidence=0.0,
            backend_used="stub",
            extraction_method="vector",
        )


class StubImageTable(ImageTableBackend):
    def extract(self, crop_image: bytes) -> GridMatrix:
        return GridMatrix(
            cells=[],
            confidence=0.0,
            backend_used="stub",
            extraction_method="image",
        )


class StubVLM(VLMBackend):
    def query(self, image: bytes, prompt: str) -> VLMResponse:
        return VLMResponse(
            raw_text="",
            confidence=0.0,
            backend_used="stub",
        )


class StubLLM(LLMBackend):
    def extract(
        self, text: str, system_prompt: str, output_schema: dict[str, Any]
    ) -> LLMResponse:
        return LLMResponse(
            raw_text="",
            confidence=0.0,
            backend_used="stub",
        )


_STUB_MAP: dict[str, type] = {
    "src.parsing.backends.layout.yolov8_backend.YOLOv8LayoutDetector": StubLayoutDetector,
    "src.parsing.backends.layout.surya_backend.SuryaLayoutDetector": StubLayoutDetector,
    "src.parsing.backends.vector.pdfplumber_camelot_backend.PdfPlumberCamelotBackend": StubVectorTable,
    "src.parsing.backends.vector_table.pdfplumber_camelot_backend.PdfplumberCamelotVectorTableBackend": StubVectorTable,
    "src.parsing.backends.image_table.paddleocr_backend.PaddleOCRImageTableBackend": StubImageTable,
    "src.parsing.backends.vlm.qwen2_vl_backend.Qwen2VLBackend": StubVLM,
    "src.parsing.backends.llm.qwen25_backend.Qwen25LLMBackend": StubLLM,
}


def _stub_load_class(dotted_path: str) -> type:
    if dotted_path in _STUB_MAP:
        return _STUB_MAP[dotted_path]
    raise ImportError(f"No stub for {dotted_path}")


def _default_parsing_config() -> ParsingConfig:
    return ParsingConfig(
        layout_detector="yolov8",
        vector_table="pdfplumber_camelot",
        image_table="paddleocr",
        vlm="qwen2_vl",
        llm="qwen25_7b",
    )


def _config_with_parsing(parsing: ParsingConfig | None = None) -> Config:
    return Config(parsing=parsing or _default_parsing_config())


# ── Test 1: ABC enforcement ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "backend_cls",
    [
        LayoutDetectorBackend,
        VectorTableBackend,
        ImageTableBackend,
        VLMBackend,
        LLMBackend,
    ],
)
def test_interfaces_are_abstract(backend_cls: type) -> None:
    with pytest.raises(TypeError):
        backend_cls()  # type: ignore[abstract]


# ── Test 2: Stub implementations instantiate ───────────────────────────────────


def test_stub_implementations_instantiate() -> None:
    layout = StubLayoutDetector()
    assert layout.detect(b"", 0) == []

    bbox = BoundingBox(x1=0, y1=0, x2=10, y2=10, page_number=0, confidence=1.0)
    vector = StubVectorTable()
    assert vector.extract("/tmp/test.pdf", 0, bbox).confidence == 0.0

    image = StubImageTable()
    assert image.extract(b"").extraction_method == "image"

    vlm = StubVLM()
    assert vlm.query(b"", "prompt").backend_used == "stub"

    llm = StubLLM()
    assert llm.extract("text", "system", {}).backend_used == "stub"


# ── Test 3: Unknown backend raises ValueError ─────────────────────────────────


def test_registry_raises_on_unknown_backend() -> None:
    config = _config_with_parsing(
        ParsingConfig(
            layout_detector="bogus",
            vector_table="pdfplumber_camelot",
            image_table="paddleocr",
            vlm="qwen2_vl",
            llm="qwen25_7b",
        )
    )
    with pytest.raises(ValueError, match="layout_detector"):
        BackendRegistry(config)


# ── Test 4: Lazy cache returns same instance ─────────────────────────────────


@patch("src.parsing.backends._registry._load_class", side_effect=_stub_load_class)
def test_registry_caches_instances(_mock_load: object) -> None:
    registry = BackendRegistry(_config_with_parsing())
    first = registry.get_layout_detector()
    second = registry.get_layout_detector()
    assert first is second


# ── Test 5: Config keys map to registry without error ────────────────────────


@patch("src.parsing.backends._registry._load_class", side_effect=_stub_load_class)
def test_config_keys_map_to_registry(_mock_load: object) -> None:
    registry = BackendRegistry(_config_with_parsing())
    registry.get_layout_detector()
    registry.get_vector_table()
    registry.get_image_table()
    registry.get_vlm()
    registry.get_llm()
