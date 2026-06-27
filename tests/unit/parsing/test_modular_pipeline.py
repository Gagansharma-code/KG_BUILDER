"""Gate tests for parse_datasheet_modular."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config import Config
from src.datasheet.phase1_dla._schemas import Phase1Output, TableCrop
from src.datasheet.phase2_tsr._schemas import Phase2Output
from src.datasheet.pipeline import DatasheetPipelineError
from src.parsing import parse_datasheet_modular
from src.parsing.backends import ParsingConfig
from src.parsing.backends._registry import BackendRegistry
from src.parsing.backends._schemas import GridMatrix as SharedGridMatrix
from src.parsing.modular_pipeline import _run_phase1, _run_phase2
from src.schemas.datasheet import (
    ComponentDatasheet,
    ExtractionMethod,
    TableSectionType,
)


def _make_config() -> Config:
    return Config(
        parsing=ParsingConfig(
            layout_detector="yolov8",
            vector_table="pdfplumber_camelot",
            image_table="paddleocr",
            vlm="qwen2_vl",
            llm="qwen25_7b",
            phase2_vector_confidence_min=0.80,
        )
    )


def _make_phase1_output(*, table_crops: list[TableCrop] | None = None) -> Phase1Output:
    return Phase1Output(
        pdf_path="test.pdf",
        source_pdf_hash="abc123",
        total_pages=1,
        table_crops=table_crops or [],
        footnote_maps=[],
        processing_time_ms=1.0,
    )


def _make_table_crop() -> TableCrop:
    return TableCrop(
        page_number=1,
        section_type=TableSectionType.OTHER,
        image_bytes=b"crop",
        bounding_box=(0, 0, 100, 100),
        detection_confidence=0.9,
    )


def _make_shared_grid(
    *,
    confidence: float,
    extraction_method: str,
) -> SharedGridMatrix:
    return SharedGridMatrix(
        cells=[],
        confidence=confidence,
        backend_used="stub",
        extraction_method=extraction_method,
    )


def _make_datasheet_stub() -> ComponentDatasheet:
    return ComponentDatasheet(
        component_id="TEST",
        manufacturer="Test",
        description="Test",
        package="SOIC-8",
        source_pdf_hash="hash",
        extraction_method=ExtractionMethod.P1_VLM,
        extraction_confidence=0.9,
        created_at="2026-01-01T00:00:00Z",
    )


def test_missing_pdf_raises_file_not_found(tmp_path: Path) -> None:
    missing = tmp_path / "missing.pdf"
    with patch.object(BackendRegistry, "__init__", return_value=None) as mock_init:
        with pytest.raises(FileNotFoundError):
            parse_datasheet_modular("COMP", missing, _make_config())
        mock_init.assert_not_called()


def test_layout_detector_called_once_per_page(tmp_path: Path) -> None:
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    mock_detector = MagicMock()
    mock_detector.detect.return_value = []

    fake_pages = [(0, b"page0"), (1, b"page1"), (2, b"page2")]
    phase1 = _make_phase1_output()
    phase2 = Phase2Output(
        grids=[],
        footnote_maps=[],
        source_pdf_hash="abc",
        processing_time_ms=1.0,
    )
    datasheet = _make_datasheet_stub()

    with patch(
        "src.parsing.modular_pipeline._rasterize_pdf",
        return_value=fake_pages,
    ):
        with patch.object(
            BackendRegistry,
            "get_layout_detector",
            return_value=mock_detector,
        ):
            with patch(
                "src.parsing.modular_pipeline._run_phase2",
                return_value=phase2,
            ):
                with patch(
                    "src.parsing.modular_pipeline._run_phase3",
                    return_value=datasheet,
                ):
                    with patch(
                        "src.datasheet.phase4_validate.validate",
                        return_value=MagicMock(verdict="PASS"),
                    ):
                        with patch(
                            "src.datasheet.phase4_validate.apply_verdict",
                            return_value=datasheet,
                        ):
                            parse_datasheet_modular("COMP", pdf_path, _make_config())

    assert mock_detector.detect.call_count == 3


def test_vector_backend_wins_when_confidence_above_threshold() -> None:
    config = _make_config()
    registry = MagicMock()
    vector_backend = MagicMock()
    image_backend = MagicMock()
    registry.get_vector_table.return_value = vector_backend
    registry.get_image_table.return_value = image_backend

    vector_backend.extract.return_value = _make_shared_grid(
        confidence=0.95,
        extraction_method="vector",
    )
    phase1 = _make_phase1_output(table_crops=[_make_table_crop()])

    result = _run_phase2(phase1, Path("test.pdf"), registry, config)

    image_backend.extract.assert_not_called()
    assert len(result.grids) == 1
    assert result.grids[0].extraction_path == "vector"
    assert result.grids[0].confidence == 0.95


def test_image_backend_used_when_vector_below_threshold() -> None:
    config = _make_config()
    registry = MagicMock()
    vector_backend = MagicMock()
    image_backend = MagicMock()
    registry.get_vector_table.return_value = vector_backend
    registry.get_image_table.return_value = image_backend

    vector_backend.extract.return_value = _make_shared_grid(
        confidence=0.60,
        extraction_method="vector",
    )
    image_backend.extract.return_value = _make_shared_grid(
        confidence=0.82,
        extraction_method="image",
    )
    phase1 = _make_phase1_output(table_crops=[_make_table_crop()])

    result = _run_phase2(phase1, Path("test.pdf"), registry, config)

    image_backend.extract.assert_called_once()
    assert result.grids[0].extraction_path == "vlm"
    assert result.grids[0].confidence == 0.82


def test_vector_wins_after_fallback_when_still_higher() -> None:
    config = _make_config()
    registry = MagicMock()
    vector_backend = MagicMock()
    image_backend = MagicMock()
    registry.get_vector_table.return_value = vector_backend
    registry.get_image_table.return_value = image_backend

    vector_backend.extract.return_value = _make_shared_grid(
        confidence=0.70,
        extraction_method="vector",
    )
    image_backend.extract.return_value = _make_shared_grid(
        confidence=0.65,
        extraction_method="image",
    )
    phase1 = _make_phase1_output(table_crops=[_make_table_crop()])

    result = _run_phase2(phase1, Path("test.pdf"), registry, config)

    image_backend.extract.assert_called_once()
    assert result.grids[0].extraction_path == "vector"
    assert result.grids[0].confidence == 0.70


def test_empty_detections_produce_empty_table_crops(tmp_path: Path) -> None:
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    mock_detector = MagicMock()
    mock_detector.detect.return_value = []
    registry = MagicMock()
    registry.get_layout_detector.return_value = mock_detector

    with patch(
        "src.parsing.modular_pipeline._rasterize_pdf",
        return_value=[(0, b"page0")],
    ):
        with patch(
            "src.parsing.modular_pipeline._compute_hash",
            return_value="hash",
        ):
            phase1_output = _run_phase1(pdf_path, registry, _make_config())

    assert phase1_output.table_crops == []


def test_phase1_failure_raises_datasheet_pipeline_error(tmp_path: Path) -> None:
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    with patch(
        "src.parsing.modular_pipeline._rasterize_pdf",
        side_effect=RuntimeError("poppler not found"),
    ):
        with pytest.raises(DatasheetPipelineError) as exc_info:
            parse_datasheet_modular("COMP", pdf_path, _make_config())

    assert exc_info.value.phase == "Phase 1"


def test_backend_registry_instantiated_once_per_call(tmp_path: Path) -> None:
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    datasheet = _make_datasheet_stub()

    with patch.object(BackendRegistry, "__init__", return_value=None) as mock_init:
        with patch.object(BackendRegistry, "get_layout_detector"):
            with patch(
                "src.parsing.modular_pipeline._run_phase1",
                return_value=_make_phase1_output(),
            ):
                with patch(
                    "src.parsing.modular_pipeline._run_phase2",
                    return_value=Phase2Output(
                        grids=[],
                        footnote_maps=[],
                        source_pdf_hash="abc",
                        processing_time_ms=1.0,
                    ),
                ):
                    with patch(
                        "src.parsing.modular_pipeline._run_phase3",
                        return_value=datasheet,
                    ):
                        with patch(
                            "src.datasheet.phase4_validate.validate",
                            return_value=MagicMock(verdict="PASS"),
                        ):
                            with patch(
                                "src.datasheet.phase4_validate.apply_verdict",
                                return_value=datasheet,
                            ):
                                parse_datasheet_modular(
                                    "COMP", pdf_path, _make_config()
                                )

    assert mock_init.call_count == 1


def test_parse_datasheet_modular_returns_component_datasheet(tmp_path: Path) -> None:
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    datasheet = _make_datasheet_stub()

    with patch(
        "src.parsing.modular_pipeline._run_phase1",
        return_value=_make_phase1_output(),
    ):
        with patch(
            "src.parsing.modular_pipeline._run_phase2",
            return_value=Phase2Output(
                grids=[],
                footnote_maps=[],
                source_pdf_hash="abc",
                processing_time_ms=1.0,
            ),
        ):
            with patch(
                "src.parsing.modular_pipeline._run_phase3",
                return_value=datasheet,
            ):
                with patch(
                    "src.datasheet.phase4_validate.validate",
                    return_value=MagicMock(verdict="PASS"),
                ):
                    with patch(
                        "src.datasheet.phase4_validate.apply_verdict",
                        return_value=datasheet,
                    ):
                        result = parse_datasheet_modular(
                            "COMP", pdf_path, _make_config()
                        )

    assert isinstance(result, ComponentDatasheet)
