"""Unit tests for src/output/doc_generator.py."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config import Config
from src.output.doc_generator import generate_design_report
from src.schemas.nir import (
    BoardSpec,
    ComponentRef,
    NIR,
    ReviewFlag,
)


def _board_spec() -> BoardSpec:
    return BoardSpec(
        layers=2,
        material="FR-4",
        thickness_mm=1.6,
        min_trace_width_mm=0.15,
        min_clearance_mm=0.15,
    )


def _sample_nir(**overrides: object) -> NIR:
    now = datetime.now(timezone.utc).isoformat()
    defaults = {
        "design_id": "REPORT_TEST_001",
        "prompt": "Design a test circuit",
        "design_methodology": "test_recipe_v1",
        "components": [
            ComponentRef(
                ref="U1",
                component_id="TPS62933DRLR",
                component_type="ldo_regulator",
                footprint="SOT-23-5",
                datasheet_confidence=0.97,
                justification="Regulator IC",
            ),
            ComponentRef(
                ref="C1",
                component_id="GRM188R71H105KA12D",
                component_type="capacitor",
                footprint="0402",
                value="1uF",
                datasheet_confidence=0.95,
                justification="Decoupling capacitor",
            ),
        ],
        "netlist": [],
        "placement_constraints": [],
        "review_flags": [
            ReviewFlag(
                item_ref="U1",
                reason="Critical issue",
                severity="CRITICAL",
                stage="validation",
            ),
            ReviewFlag(
                item_ref="C1",
                reason="Warning issue",
                severity="WARNING",
                stage="extraction",
            ),
        ],
        "justifications": {"U1": "Selected for efficiency"},
        "source_citations": {"U1": "TPS62933 datasheet"},
        "board_spec": _board_spec(),
        "created_at": now,
    }
    defaults.update(overrides)
    return NIR(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def config() -> Config:
    return Config()


def test_report_contains_design_id_in_summary(
    config: Config, tmp_path: Path
) -> None:
    nir = _sample_nir()
    report_dir = tmp_path / "report"

    path = generate_design_report(nir, report_dir, config)
    content = path.read_text(encoding="utf-8")

    assert "REPORT_TEST_001" in content
    assert "## 1. Design Summary" in content
    assert path.parent == report_dir


def test_report_contains_one_row_per_bom_component(
    config: Config, tmp_path: Path
) -> None:
    nir = _sample_nir()
    path = generate_design_report(nir, tmp_path / "report", config)
    content = path.read_text(encoding="utf-8")

    assert "| U1 | TPS62933DRLR |" in content
    assert "| C1 | GRM188R71H105KA12D |" in content
    assert content.count("| U1 |") >= 1
    assert content.count("| C1 |") >= 1


def test_critical_review_flags_before_warning(
    config: Config, tmp_path: Path
) -> None:
    nir = _sample_nir()
    path = generate_design_report(nir, tmp_path / "report", config)
    content = path.read_text(encoding="utf-8")

    critical_pos = content.index("| U1 | CRITICAL |")
    warning_pos = content.index("| C1 | WARNING |")
    assert critical_pos < warning_pos


def test_report_saved_to_report_directory(
    config: Config, tmp_path: Path
) -> None:
    nir = _sample_nir()
    report_dir = tmp_path / "report"

    path = generate_design_report(nir, report_dir, config)

    assert path.parent == report_dir
    assert path.exists()


def test_generate_design_report_never_raises_with_empty_fields(
    config: Config, tmp_path: Path
) -> None:
    nir = _sample_nir(
        components=[],
        netlist=[],
        placement_constraints=[],
        routing_hints=[],
        review_flags=[],
        justifications={},
        source_citations={},
    )

    path = generate_design_report(nir, tmp_path / "report", config)

    assert path.exists()
    assert "REPORT_TEST_001" in path.read_text(encoding="utf-8")


def test_falls_back_to_md_when_pandoc_unavailable(
    config: Config, tmp_path: Path
) -> None:
    nir = _sample_nir()

    with (
        patch(
            "src.output.doc_generator._try_pandoc",
            return_value=False,
        ),
        patch(
            "src.output.doc_generator._try_weasyprint",
            return_value=False,
        ),
    ):
        path = generate_design_report(nir, tmp_path / "report", config)

    assert path.suffix == ".md"
    assert path.name == "REPORT_TEST_001_report.md"
