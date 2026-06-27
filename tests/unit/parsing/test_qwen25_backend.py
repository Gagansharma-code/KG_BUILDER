"""Gate tests for Qwen25LLMBackend."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from pydantic import create_model

from src.config import Config
from src.parsing.backends import BackendRegistry, LLMBackend, ParsingConfig
from src.parsing.backends.llm.qwen25_backend import Qwen25LLMBackend

PATCH_TARGET = "src.datasheet.phase3_extract.extractor.InstructorWrapper"


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


def test_qwen25_implements_llm_backend() -> None:
    backend = Qwen25LLMBackend(_make_config())
    assert isinstance(backend, LLMBackend)


def test_instructor_wrapper_is_none_at_construction() -> None:
    backend = Qwen25LLMBackend(_make_config())
    assert backend._instructor_wrapper is None


def test_extract_with_successful_instructor_response() -> None:
    backend = Qwen25LLMBackend(_make_config())
    extraction_model = create_model(
        "ExtractionResult",
        parameter=(str, "VCC"),
        value=(str, "3.3"),
    )
    mock_instance = MagicMock()
    mock_instance.extract.return_value = extraction_model()

    with patch(PATCH_TARGET, return_value=mock_instance):
        result = backend.extract(
            text="VCC 3.3V typical",
            system_prompt="Extract parameter and value",
            output_schema={
                "properties": {
                    "parameter": {"type": "string"},
                    "value": {"type": "string"},
                }
            },
        )

    assert result.backend_used == "qwen25_7b"
    assert result.parsed_json is not None
    assert result.parsed_json["parameter"] == "VCC"
    assert result.parsed_json["value"] == "3.3"
    assert result.confidence == 0.85


def test_extract_when_instructor_returns_none() -> None:
    backend = Qwen25LLMBackend(_make_config())
    mock_instance = MagicMock()
    mock_instance.extract.return_value = None

    with patch(PATCH_TARGET, return_value=mock_instance):
        result = backend.extract("text", "prompt", {"properties": {}})

    assert result.parsed_json is None
    assert result.confidence == 0.0
    assert result.backend_used == "qwen25_7b"


def test_extract_on_model_load_failure() -> None:
    backend = Qwen25LLMBackend(_make_config())

    with patch.object(
        Config,
        "get_model_path",
        side_effect=FileNotFoundError("missing model"),
    ):
        result = backend.extract("text", "prompt", {"properties": {}})

    assert result.confidence == 0.0


def test_extract_on_runtime_error() -> None:
    backend = Qwen25LLMBackend(_make_config())
    mock_instance = MagicMock()
    mock_instance.extract.side_effect = RuntimeError("inference failed")

    with patch(PATCH_TARGET, return_value=mock_instance):
        result = backend.extract("text", "prompt", {"properties": {}})

    assert result.confidence == 0.0


def test_registry_returns_qwen25_backend() -> None:
    registry = BackendRegistry(_make_config())
    backend = registry.get_llm()
    assert isinstance(backend, Qwen25LLMBackend)


def test_get_llm_returns_cached_instance() -> None:
    registry = BackendRegistry(_make_config())
    result1 = registry.get_llm()
    result2 = registry.get_llm()
    assert result1 is result2
