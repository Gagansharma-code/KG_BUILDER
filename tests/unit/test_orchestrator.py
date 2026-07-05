"""Unit tests for src/orchestrator.py E2E pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config import Config
from src.datasheet.pipeline import DatasheetPipelineError
from src.knowledge_graph.graph import KnowledgeGraph
from src.layout._schemas import LayoutSpec
from src.output import OutputResult
from src.schemas.datasheet import ComponentDatasheet, ExtractionMethod
from src.schemas.intent import (
    BOMEntry,
    DesignMethodology,
    ImprovedIntentDict,
    ValidatedBOM,
)
from src.schemas.kg import DesignSubgraph
from src.schemas.nir import BoardSpec, NIR
from src.schematic._schemas import ERCResult, SchematicGraph


PROMPT = "Design a 3.3V buck regulator for battery input"


def _intent() -> ImprovedIntentDict:
    return ImprovedIntentDict(
        goal="buck regulator",
        application="battery",
        design_methodology=DesignMethodology.STANDARD_SMD,
        board_type="standard_SMD",
        raw_prompt=PROMPT,
    )


def _bom_entry(
    *,
    ref: str = "U1",
    specific_part: str | None = "TPS62933",
    component_type: str = "regulator",
) -> BOMEntry:
    return BOMEntry(
        ref=ref,
        component_type=component_type,
        specific_part=specific_part,
        justification="test",
        source="rule",
        confidence=0.9,
    )


def _validated_bom(
    components: list[BOMEntry] | None = None,
    *,
    review_required: bool = False,
    design_id: str = "d1",
) -> ValidatedBOM:
    return ValidatedBOM(
        design_id=design_id,
        intent=_intent(),
        components=components if components is not None else [_bom_entry()],
        total_confidence=0.9,
        review_required=review_required,
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def _mock_datasheet(
    component_id: str = "TPS62933",
    *,
    pipeline_version: str = "1.0",
) -> ComponentDatasheet:
    return ComponentDatasheet(
        component_id=component_id,
        manufacturer="Texas Instruments",
        description="Test regulator",
        package="SOT-23-5",
        source_pdf_hash="abc123",
        extraction_method=ExtractionMethod.P1_VECTOR,
        extraction_confidence=0.95,
        review_required=False,
        pipeline_version=pipeline_version,
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def _mock_nir(design_id: str = "d1") -> NIR:
    return NIR(
        design_id=design_id,
        prompt=PROMPT,
        design_methodology="standard_SMD",
        components=[],
        netlist=[],
        placement_constraints=[],
        board_spec=BoardSpec(
            layers=2,
            material="FR4",
            thickness_mm=1.6,
            min_trace_width_mm=0.15,
            min_clearance_mm=0.15,
        ),
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def _mock_schematic() -> SchematicGraph:
    return SchematicGraph(
        netlist=[],
        blocks=[],
        erc_result=ERCResult(passed=True, violations=[], rules_checked=1),
        synthesis_confidence=0.95,
        unresolved_pins=[],
        review_flags=[],
    )


def _mock_layout() -> LayoutSpec:
    return LayoutSpec(
        placement_constraints=[],
        component_groups=[],
        routing_hints=[],
        board_spec=BoardSpec(
            layers=2,
            material="FR4",
            thickness_mm=1.6,
            min_trace_width_mm=0.15,
            min_clearance_mm=0.15,
        ),
    )


def _configure_team_d_mocks(
    mock_schematic,
    mock_layout,
    mock_build_nir,
    nir: NIR,
) -> None:
    mock_schematic.return_value = _mock_schematic()
    mock_layout.return_value = _mock_layout()
    mock_build_nir.return_value = nir


@pytest.fixture
def config() -> Config:
    return Config()


@pytest.fixture
def mock_graph() -> KnowledgeGraph:
    return MagicMock(spec=KnowledgeGraph)


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    return tmp_path / "output"


def _happy_path_mocks(
    mock_bom: ValidatedBOM | None = None,
    mock_datasheet: ComponentDatasheet | None = None,
    mock_nir: NIR | None = None,
):
    bom = mock_bom or _validated_bom()
    datasheet = mock_datasheet or _mock_datasheet()
    nir = mock_nir or _mock_nir(bom.design_id)
    subgraph = DesignSubgraph(
        component_types=[],
        component_instances=[],
        design_rules=[],
        placement_rules=[],
        routing_hints=[],
        design_methodology="standard_SMD",
        path_confidences={},
        query_depth=0,
        query_metadata={},
    )
    output = OutputResult(
        design_id=nir.design_id,
        overall_success=True,
    )
    return bom, datasheet, nir, subgraph, output


@patch("src.orchestrator.run_output_pipeline")
@patch("src.orchestrator.build_nir")
@patch("src.orchestrator.generate_layout_spec")
@patch("src.orchestrator.synthesize_schematic")
@patch("src.orchestrator.normalize_pins")
@patch("src.orchestrator.parse_datasheet")
@patch("src.orchestrator._resolve_pdf")
@patch("src.orchestrator.query_graph")
@patch("src.orchestrator.run_intent_pipeline")
def test_happy_path_all_pdfs_found(
    mock_intent_pipeline,
    mock_query_graph,
    mock_resolve_pdf,
    mock_parse_datasheet,
    mock_normalize_pins,
    mock_schematic,
    mock_layout,
    mock_build_nir,
    mock_output_pipeline,
    config: Config,
    mock_graph: KnowledgeGraph,
    output_dir: Path,
) -> None:
    bom, datasheet, nir, subgraph, output = _happy_path_mocks()
    mock_intent_pipeline.return_value = (bom.intent, bom, None)
    mock_query_graph.return_value = subgraph
    mock_resolve_pdf.return_value = Path("corpus/datasheets/TPS62933.pdf")
    mock_parse_datasheet.return_value = datasheet
    mock_normalize_pins.return_value = [datasheet]
    _configure_team_d_mocks(mock_schematic, mock_layout, mock_build_nir, nir)
    mock_output_pipeline.return_value = output

    from src.orchestrator import run_e2e

    result = run_e2e(PROMPT, mock_graph, output_dir, config)

    assert result.overall_success is True
    assert result.datasheets_parsed == 1
    assert result.datasheets_skipped == 0


@patch("src.orchestrator.run_output_pipeline")
@patch("src.orchestrator.build_nir")
@patch("src.orchestrator.generate_layout_spec")
@patch("src.orchestrator.synthesize_schematic")
@patch("src.orchestrator.normalize_pins")
@patch("src.orchestrator.parse_datasheet")
@patch("src.orchestrator._resolve_pdf")
@patch("src.orchestrator.query_graph")
@patch("src.orchestrator.run_intent_pipeline")
def test_pdf_not_found_uses_skeleton(
    mock_intent_pipeline,
    mock_query_graph,
    mock_resolve_pdf,
    mock_parse_datasheet,
    mock_normalize_pins,
    mock_schematic,
    mock_layout,
    mock_build_nir,
    mock_output_pipeline,
    config: Config,
    mock_graph: KnowledgeGraph,
    output_dir: Path,
) -> None:
    bom, datasheet, nir, subgraph, output = _happy_path_mocks()
    mock_intent_pipeline.return_value = (bom.intent, bom, None)
    mock_query_graph.return_value = subgraph
    mock_resolve_pdf.return_value = None
    mock_normalize_pins.side_effect = lambda datasheets, _config: datasheets
    _configure_team_d_mocks(mock_schematic, mock_layout, mock_build_nir, nir)
    mock_output_pipeline.return_value = output

    from src.orchestrator import run_e2e

    result = run_e2e(PROMPT, mock_graph, output_dir, config)

    assert result.datasheets_parsed == 0
    assert result.datasheets_skipped == 1
    assert result.overall_success is True
    mock_parse_datasheet.assert_not_called()


@patch("src.orchestrator.run_output_pipeline")
@patch("src.orchestrator.build_nir")
@patch("src.orchestrator.generate_layout_spec")
@patch("src.orchestrator.synthesize_schematic")
@patch("src.orchestrator.normalize_pins")
@patch("src.orchestrator.parse_datasheet")
@patch("src.orchestrator._resolve_pdf")
@patch("src.orchestrator.query_graph")
@patch("src.orchestrator.run_intent_pipeline")
def test_parse_datasheet_error_uses_skeleton(
    mock_intent_pipeline,
    mock_query_graph,
    mock_resolve_pdf,
    mock_parse_datasheet,
    mock_normalize_pins,
    mock_schematic,
    mock_layout,
    mock_build_nir,
    mock_output_pipeline,
    config: Config,
    mock_graph: KnowledgeGraph,
    output_dir: Path,
) -> None:
    bom, _, nir, subgraph, output = _happy_path_mocks()
    mock_intent_pipeline.return_value = (bom.intent, bom, None)
    mock_query_graph.return_value = subgraph
    mock_resolve_pdf.return_value = Path("corpus/datasheets/TPS62933.pdf")
    mock_parse_datasheet.side_effect = DatasheetPipelineError(
        "Phase 1",
        "TPS62933",
        RuntimeError("x"),
    )
    mock_normalize_pins.side_effect = lambda datasheets, _config: datasheets
    _configure_team_d_mocks(mock_schematic, mock_layout, mock_build_nir, nir)
    mock_output_pipeline.return_value = output

    from src.orchestrator import run_e2e

    result = run_e2e(PROMPT, mock_graph, output_dir, config)

    assert result.datasheets_skipped == 1
    assert result.overall_success is True


@patch("src.orchestrator.run_output_pipeline")
@patch("src.orchestrator.build_nir")
@patch("src.orchestrator.generate_layout_spec")
@patch("src.orchestrator.synthesize_schematic")
@patch("src.orchestrator.normalize_pins")
@patch("src.orchestrator.parse_datasheet")
@patch("src.orchestrator._resolve_pdf")
@patch("src.orchestrator.query_graph")
@patch("src.orchestrator.run_intent_pipeline")
def test_review_required_bom_blocks_at_gate(
    mock_intent_pipeline,
    mock_query_graph,
    mock_resolve_pdf,
    mock_parse_datasheet,
    mock_normalize_pins,
    mock_schematic,
    mock_layout,
    mock_build_nir,
    mock_output_pipeline,
    config: Config,
    mock_graph: KnowledgeGraph,
    output_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """review_required=True halts at the human-review gate: no downstream
    stage runs (OPENFORGE_ARCHITECTURE.md §8 blocking behavior)."""
    bom, datasheet, nir, subgraph, output = _happy_path_mocks(
        mock_bom=_validated_bom(review_required=True),
    )
    mock_intent_pipeline.return_value = (bom.intent, bom, None)

    from src.orchestrator import run_e2e

    with (
        caplog.at_level("WARNING"),
        patch("src.review.queue.get_bom_review_item", return_value=MagicMock()),
    ):
        result = run_e2e(PROMPT, mock_graph, output_dir, config)

    mock_query_graph.assert_not_called()
    mock_schematic.assert_not_called()
    mock_layout.assert_not_called()
    mock_build_nir.assert_not_called()
    mock_output_pipeline.assert_not_called()
    assert result.overall_success is False
    assert result.status == "pending_review"
    assert any("review" in record.message for record in caplog.records)


@patch("src.orchestrator.run_output_pipeline")
@patch("src.orchestrator.build_nir")
@patch("src.orchestrator.generate_layout_spec")
@patch("src.orchestrator.synthesize_schematic")
@patch("src.orchestrator.normalize_pins")
@patch("src.orchestrator.parse_datasheet")
@patch("src.orchestrator._resolve_pdf")
@patch("src.orchestrator.query_graph")
@patch("src.orchestrator.run_intent_pipeline")
def test_catastrophic_synthesis_failure(
    mock_intent_pipeline,
    mock_query_graph,
    mock_resolve_pdf,
    mock_parse_datasheet,
    mock_normalize_pins,
    mock_schematic,
    mock_layout,
    mock_build_nir,
    mock_output_pipeline,
    config: Config,
    mock_graph: KnowledgeGraph,
    output_dir: Path,
) -> None:
    bom, datasheet, _, subgraph, _ = _happy_path_mocks()
    mock_intent_pipeline.return_value = (bom.intent, bom, None)
    mock_query_graph.return_value = subgraph
    mock_resolve_pdf.return_value = Path("corpus/datasheets/TPS62933.pdf")
    mock_parse_datasheet.return_value = datasheet
    mock_normalize_pins.return_value = [datasheet]
    mock_schematic.side_effect = RuntimeError("synthesis exploded")

    from src.orchestrator import run_e2e

    result = run_e2e(PROMPT, mock_graph, output_dir, config)

    assert result.overall_success is False
    assert result.datasheets_parsed >= 0
    mock_output_pipeline.assert_not_called()


@patch("src.orchestrator.run_output_pipeline")
@patch("src.orchestrator.build_nir")
@patch("src.orchestrator.generate_layout_spec")
@patch("src.orchestrator.synthesize_schematic")
@patch("src.orchestrator.normalize_pins")
@patch("src.orchestrator.parse_datasheet")
@patch("src.orchestrator._resolve_pdf")
@patch("src.orchestrator.query_graph")
@patch("src.orchestrator.run_intent_pipeline")
def test_empty_bom_still_runs_pipeline(
    mock_intent_pipeline,
    mock_query_graph,
    mock_resolve_pdf,
    mock_parse_datasheet,
    mock_normalize_pins,
    mock_schematic,
    mock_layout,
    mock_build_nir,
    mock_output_pipeline,
    config: Config,
    mock_graph: KnowledgeGraph,
    output_dir: Path,
) -> None:
    bom, _, nir, subgraph, output = _happy_path_mocks(
        mock_bom=_validated_bom(components=[]),
    )
    mock_intent_pipeline.return_value = (bom.intent, bom, None)
    mock_query_graph.return_value = subgraph
    mock_normalize_pins.return_value = []
    _configure_team_d_mocks(mock_schematic, mock_layout, mock_build_nir, nir)
    mock_output_pipeline.return_value = output

    from src.orchestrator import run_e2e

    result = run_e2e(PROMPT, mock_graph, output_dir, config)

    assert result.datasheets_parsed == 0
    assert result.datasheets_skipped == 0
    mock_normalize_pins.assert_called_once_with([], config)
    mock_schematic.assert_called_once()
    mock_layout.assert_called_once()
    mock_build_nir.assert_called_once()
    mock_parse_datasheet.assert_not_called()
    mock_resolve_pdf.assert_not_called()


@patch("src.orchestrator.run_output_pipeline")
@patch("src.orchestrator.build_nir")
@patch("src.orchestrator.generate_layout_spec")
@patch("src.orchestrator.synthesize_schematic")
@patch("src.orchestrator.normalize_pins")
@patch("src.orchestrator.parse_datasheet")
@patch("src.orchestrator._resolve_pdf")
@patch("src.orchestrator.query_graph")
@patch("src.orchestrator.run_intent_pipeline")
def test_multiple_components_mixed_pdf_resolution(
    mock_intent_pipeline,
    mock_query_graph,
    mock_resolve_pdf,
    mock_parse_datasheet,
    mock_normalize_pins,
    mock_schematic,
    mock_layout,
    mock_build_nir,
    mock_output_pipeline,
    config: Config,
    mock_graph: KnowledgeGraph,
    output_dir: Path,
) -> None:
    components = [
        _bom_entry(ref="U1", specific_part="TPS62933"),
        _bom_entry(ref="U2", specific_part="LM358", component_type="op_amp"),
    ]
    bom, _, nir, subgraph, output = _happy_path_mocks(
        mock_bom=_validated_bom(components=components),
    )
    parsed = _mock_datasheet("TPS62933")
    mock_intent_pipeline.return_value = (bom.intent, bom, None)
    mock_query_graph.return_value = subgraph

    def resolve_pdf(component_id: str, _config: Config) -> Path | None:
        if component_id == "TPS62933":
            return Path("corpus/datasheets/TPS62933.pdf")
        return None

    mock_resolve_pdf.side_effect = resolve_pdf
    mock_parse_datasheet.return_value = parsed
    mock_normalize_pins.side_effect = lambda datasheets, _config: datasheets
    _configure_team_d_mocks(mock_schematic, mock_layout, mock_build_nir, nir)
    mock_output_pipeline.return_value = output

    from src.orchestrator import run_e2e

    result = run_e2e(PROMPT, mock_graph, output_dir, config)

    assert result.datasheets_parsed == 1
    assert result.datasheets_skipped == 1


@patch("src.orchestrator.run_output_pipeline")
@patch("src.orchestrator.build_nir")
@patch("src.orchestrator.generate_layout_spec")
@patch("src.orchestrator.synthesize_schematic")
@patch("src.orchestrator.normalize_pins")
@patch("src.orchestrator.parse_datasheet")
@patch("src.orchestrator._resolve_pdf")
@patch("src.orchestrator.query_graph")
@patch("src.orchestrator.run_intent_pipeline")
def test_e2e_result_fields_populated(
    mock_intent_pipeline,
    mock_query_graph,
    mock_resolve_pdf,
    mock_parse_datasheet,
    mock_normalize_pins,
    mock_schematic,
    mock_layout,
    mock_build_nir,
    mock_output_pipeline,
    config: Config,
    mock_graph: KnowledgeGraph,
    output_dir: Path,
) -> None:
    bom, datasheet, nir, subgraph, output = _happy_path_mocks()
    mock_intent_pipeline.return_value = (bom.intent, bom, None)
    mock_query_graph.return_value = subgraph
    mock_resolve_pdf.return_value = Path("corpus/datasheets/TPS62933.pdf")
    mock_parse_datasheet.return_value = datasheet
    mock_normalize_pins.return_value = [datasheet]
    _configure_team_d_mocks(mock_schematic, mock_layout, mock_build_nir, nir)
    mock_output_pipeline.return_value = output

    from src.orchestrator import run_e2e

    result = run_e2e(PROMPT, mock_graph, output_dir, config)

    assert result.design_id == nir.design_id
    assert result.prompt == PROMPT
    assert result.nir is nir
    assert result.output.overall_success is True
