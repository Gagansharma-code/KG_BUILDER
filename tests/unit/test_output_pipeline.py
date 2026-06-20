"""Unit tests for src/output/__init__.py pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config import Config
from src.output import OutputResult, run_output_pipeline
from src.output.kicad_serializer import KiCadOutput
from src.output.tscircuit_serializer import TSCircuitOutput
from src.schemas.nir import BoardSpec, ComponentRef, NIR


def _board_spec() -> BoardSpec:
    return BoardSpec(
        layers=2,
        material="FR-4",
        thickness_mm=1.6,
        min_trace_width_mm=0.15,
        min_clearance_mm=0.15,
    )


def _minimal_nir() -> NIR:
    now = datetime.now(timezone.utc).isoformat()
    return NIR(
        design_id="PIPELINE_TEST_001",
        prompt="Test pipeline",
        design_methodology="test_recipe_v1",
        components=[
            ComponentRef(
                ref="R1",
                component_id="RC0402",
                component_type="resistor",
                footprint="0402",
                value="10k",
                datasheet_confidence=0.9,
                justification="Test resistor",
            ),
        ],
        netlist=[],
        placement_constraints=[],
        board_spec=_board_spec(),
        created_at=now,
    )


@pytest.fixture
def config() -> Config:
    return Config()


@pytest.fixture
def nir() -> NIR:
    return _minimal_nir()


def test_run_output_pipeline_returns_output_result(
    nir: NIR, config: Config, tmp_path: Path
) -> None:
    with (
        patch(
            "src.output.serialize_to_tscircuit",
            return_value=TSCircuitOutput(success=True),
        ),
        patch(
            "src.output.serialize_to_kicad",
            return_value=KiCadOutput(success=True),
        ),
        patch(
            "src.output.generate_design_report",
            return_value=tmp_path / "report" / "PIPELINE_TEST_001_report.md",
        ),
    ):
        result = run_output_pipeline(nir, tmp_path, config)

    assert isinstance(result, OutputResult)
    assert result.design_id == "PIPELINE_TEST_001"


def test_tscircuit_failure_does_not_block_kicad(
    nir: NIR, config: Config, tmp_path: Path
) -> None:
    kicad_output = KiCadOutput(success=True)

    with (
        patch(
            "src.output.serialize_to_tscircuit",
            side_effect=RuntimeError("tscircuit crashed"),
        ),
        patch(
            "src.output.serialize_to_kicad",
            return_value=kicad_output,
        ) as mock_kicad,
        patch(
            "src.output.generate_design_report",
            return_value=tmp_path / "report" / "report.md",
        ),
    ):
        result = run_output_pipeline(nir, tmp_path, config)

    mock_kicad.assert_called_once()
    assert result.kicad == kicad_output
    assert result.tscircuit is None


def test_kicad_failure_does_not_block_doc_generator(
    nir: NIR, config: Config, tmp_path: Path
) -> None:
    report_path = tmp_path / "report" / "PIPELINE_TEST_001_report.md"

    with (
        patch(
            "src.output.serialize_to_tscircuit",
            return_value=TSCircuitOutput(success=False),
        ),
        patch(
            "src.output.serialize_to_kicad",
            side_effect=RuntimeError("kicad crashed"),
        ),
        patch(
            "src.output.generate_design_report",
            return_value=report_path,
        ) as mock_report,
    ):
        result = run_output_pipeline(nir, tmp_path, config)

    mock_report.assert_called_once()
    assert result.kicad is None
    assert result.report_path == report_path


def test_overall_success_true_when_one_serializer_succeeds(
    nir: NIR, config: Config, tmp_path: Path
) -> None:
    with (
        patch(
            "src.output.serialize_to_tscircuit",
            return_value=TSCircuitOutput(success=False, cli_error="failed"),
        ),
        patch(
            "src.output.serialize_to_kicad",
            return_value=KiCadOutput(success=False, error="failed"),
        ),
        patch(
            "src.output.generate_design_report",
            return_value=tmp_path / "report" / "report.md",
        ),
    ):
        result = run_output_pipeline(nir, tmp_path, config)

    assert result.overall_success is True


def test_overall_success_false_when_all_fail(
    nir: NIR, config: Config, tmp_path: Path
) -> None:
    with (
        patch(
            "src.output.serialize_to_tscircuit",
            return_value=TSCircuitOutput(success=False),
        ),
        patch(
            "src.output.serialize_to_kicad",
            return_value=KiCadOutput(success=False),
        ),
        patch(
            "src.output.generate_design_report",
            side_effect=RuntimeError("report failed"),
        ),
    ):
        result = run_output_pipeline(nir, tmp_path, config)

    assert result.overall_success is False
    assert result.report_path is None


def test_run_output_pipeline_never_raises(
    nir: NIR, config: Config, tmp_path: Path
) -> None:
    with (
        patch(
            "src.output.serialize_to_tscircuit",
            side_effect=RuntimeError("boom"),
        ),
        patch(
            "src.output.serialize_to_kicad",
            side_effect=RuntimeError("boom"),
        ),
        patch(
            "src.output.generate_design_report",
            side_effect=RuntimeError("boom"),
        ),
    ):
        result = run_output_pipeline(nir, tmp_path, config)

    assert isinstance(result, OutputResult)
    assert result.overall_success is False
