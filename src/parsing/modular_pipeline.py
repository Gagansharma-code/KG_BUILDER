"""Modular datasheet parsing pipeline using pluggable backends.

Parallel entry point to src.datasheet.pipeline.parse_datasheet — same output
contract (ComponentDatasheet), but phases 1–2 route through BackendRegistry.
"""

from __future__ import annotations

import hashlib
import io
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from src.datasheet.phase1_dla._schemas import Phase1Output, TableCrop
from src.datasheet.phase2_tsr._schemas import (
    CellValue,
    GridMatrix as InternalGridMatrix,
    Phase2Output,
)
from src.datasheet.phase3_extract import process as phase3_extract
from src.datasheet.phase5_layout import extract_layout_constraints
from src.datasheet.pipeline import DatasheetPipelineError, _has_layout_sections
from src.parsing.backends._registry import BackendRegistry
from src.parsing.backends._schemas import BoundingBox, GridMatrix as SharedGridMatrix
from src.review.queue import enqueue
from src.schemas.datasheet import ComponentDatasheet, TableSectionType

if TYPE_CHECKING:
    from src.config import Config

logger = logging.getLogger(__name__)


def _compute_hash(pdf_path: Path) -> str:
    """Return SHA-256 hex digest of raw PDF bytes."""
    return hashlib.sha256(pdf_path.read_bytes()).hexdigest()


def _rasterize_pdf(pdf_path: Path) -> list[tuple[int, bytes]]:
    """Rasterize PDF pages to PNG bytes at 300 DPI.

    Returns:
        List of (page_number, png_bytes) with 0-indexed page numbers.

    Raises:
        RuntimeError: If rasterization fails.
    """
    try:
        from pdf2image import convert_from_path

        images = convert_from_path(str(pdf_path), dpi=300)
        pages: list[tuple[int, bytes]] = []
        for page_number, image in enumerate(images):
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            pages.append((page_number, buffer.getvalue()))
        return pages
    except Exception as exc:
        raise RuntimeError(f"Failed to rasterize PDF {pdf_path}: {exc}") from exc


def _run_phase1(
    pdf_path: Path,
    registry: BackendRegistry,
    config: Config,
) -> Phase1Output:
    """Run layout detection via BackendRegistry and build Phase1Output."""
    start_time = time.time()
    pages = _rasterize_pdf(pdf_path)
    layout_detector = registry.get_layout_detector()
    table_crops: list[TableCrop] = []

    for page_number, png_bytes in pages:
        regions = layout_detector.detect(png_bytes, page_number)
        for region in regions:
            if region.region_type not in ("table", "caption"):
                continue
            table_crops.append(
                TableCrop(
                    page_number=region.bbox.page_number + 1,
                    section_type=TableSectionType.OTHER,
                    image_bytes=region.crop_image or b"",
                    bounding_box=(
                        region.bbox.x1,
                        region.bbox.y1,
                        region.bbox.x2,
                        region.bbox.y2,
                    ),
                    heading_text=None,
                    is_multipage_continuation=False,
                    detection_confidence=region.bbox.confidence,
                )
            )

    elapsed_ms = (time.time() - start_time) * 1000
    return Phase1Output(
        pdf_path=str(pdf_path),
        source_pdf_hash=_compute_hash(pdf_path),
        total_pages=max(len(pages), 1),
        table_crops=table_crops,
        footnote_maps=[],
        processing_time_ms=elapsed_ms,
    )


def _shared_to_internal_grid(
    winner: SharedGridMatrix,
    crop: TableCrop,
    table_index: int,
) -> InternalGridMatrix:
    """Translate shared backend GridMatrix to internal Phase 2 GridMatrix."""
    extraction_path = (
        "vlm" if winner.extraction_method == "image" else winner.extraction_method
    )
    return InternalGridMatrix(
        cells=[
            CellValue(
                text=cell.text,
                row=cell.row,
                col=cell.col,
                rowspan=cell.row_span,
                colspan=cell.col_span,
                is_header=(cell.row == 0),
            )
            for cell in winner.cells
        ],
        num_rows=max((cell.row for cell in winner.cells), default=0) + 1,
        num_cols=max((cell.col for cell in winner.cells), default=0) + 1,
        section_type=crop.section_type,
        source_page=crop.page_number,
        source_table_index=table_index,
        extraction_path=extraction_path,
        confidence=winner.confidence,
        has_merged_cells=any(
            cell.row_span > 1 or cell.col_span > 1 for cell in winner.cells
        ),
    )


def _run_phase2(
    phase1_output: Phase1Output,
    pdf_path: Path,
    registry: BackendRegistry,
    config: Config,
) -> Phase2Output:
    """Run table extraction via vector and image backends with fallback."""
    start_time = time.time()
    threshold = config.parsing.phase2_vector_confidence_min
    vector_backend = registry.get_vector_table()
    image_backend = registry.get_image_table()
    internal_grids: list[InternalGridMatrix] = []

    for idx, crop in enumerate(phase1_output.table_crops):
        bbox = BoundingBox(
            x1=crop.bounding_box[0],
            y1=crop.bounding_box[1],
            x2=crop.bounding_box[2],
            y2=crop.bounding_box[3],
            page_number=crop.page_number,
            confidence=crop.detection_confidence,
        )
        vector_result = vector_backend.extract(
            pdf_path=str(pdf_path),
            page_number=crop.page_number,
            bbox=bbox,
        )

        if vector_result.confidence >= threshold:
            winner = vector_result
        else:
            image_result = image_backend.extract(crop_image=crop.image_bytes)
            winner = (
                image_result
                if image_result.confidence >= vector_result.confidence
                else vector_result
            )

        internal_grids.append(
            _shared_to_internal_grid(winner, crop, table_index=idx)
        )

    elapsed_ms = (time.time() - start_time) * 1000
    return Phase2Output(
        grids=internal_grids,
        footnote_maps=[],
        source_pdf_hash=phase1_output.source_pdf_hash,
        processing_time_ms=elapsed_ms,
    )


def _run_phase3(
    phase2_output: Phase2Output,
    registry: BackendRegistry,
    config: Config,
) -> ComponentDatasheet:
    """Delegate semantic extraction to existing phase3_extract.

    Phase 3's Instructor-based extraction is tightly coupled to datasheet
    Pydantic schemas. LLMBackend is used for book parsing and app notes —
    not for the datasheet extraction schema path yet. Full decoupling is deferred
    until all backends are stable.
    """
    del registry  # reserved for future LLMBackend routing
    return phase3_extract(phase2_output, config)


def parse_datasheet_modular(
    component_id: str,
    pdf_path: Path,
    config: Config,
) -> ComponentDatasheet:
    """Orchestrate all 5 phases using pluggable backends for phases 1–2."""
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    logger.info(f"Starting datasheet pipeline for {component_id}: {pdf_path}")

    registry = BackendRegistry(config)
    phase1_output = None
    phase2_output = None
    datasheet = None

    try:
        phase_name = "Phase 1"
        logger.info(f"{phase_name}: starting for {component_id}")
        start_time = time.time()

        phase1_output = _run_phase1(pdf_path, registry, config)

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            f"{phase_name}: completed for {component_id} in {duration_ms:.1f}ms, "
            f"found {len(phase1_output.table_crops)} table crops"
        )

        phase_name = "Phase 2"
        logger.info(f"{phase_name}: starting for {component_id}")
        start_time = time.time()

        phase2_output = _run_phase2(phase1_output, pdf_path, registry, config)

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            f"{phase_name}: completed for {component_id} in {duration_ms:.1f}ms, "
            f"extracted {len(phase2_output.grids)} grids"
        )

        phase_name = "Phase 3"
        logger.info(f"{phase_name}: starting for {component_id}")
        start_time = time.time()

        datasheet = _run_phase3(phase2_output, registry, config)

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            f"{phase_name}: completed for {component_id} in {duration_ms:.1f}ms, "
            f"extracted {len(datasheet.electrical_parameters)} parameters, "
            f"{len(datasheet.pins)} pins"
        )

        phase_name = "Phase 4"
        logger.info(f"{phase_name}: starting for {component_id}")
        start_time = time.time()

        from src.datasheet.phase4_validate import apply_verdict, validate

        validation_result = validate(datasheet, config)
        datasheet = apply_verdict(datasheet, validation_result)

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            f"{phase_name}: completed for {component_id} in {duration_ms:.1f}ms, "
            f"verdict={validation_result.verdict}, "
            f"review_required={datasheet.review_required}"
        )

        if _has_layout_sections(phase1_output):
            phase_name = "Phase 5"
            logger.info(f"{phase_name}: starting for {component_id}")
            start_time = time.time()

            constraints = extract_layout_constraints(pdf_path, phase1_output, config)

            if constraints:
                datasheet = datasheet.model_copy(
                    update={"layout_constraints": constraints}
                )
                logger.info(
                    f"{phase_name}: completed for {component_id} in "
                    f"{duration_ms:.1f}ms, extracted {len(constraints)} constraints"
                )
            else:
                logger.info(
                    f"{phase_name}: completed for {component_id} in "
                    f"{duration_ms:.1f}ms, no constraints found"
                )

            duration_ms = (time.time() - start_time) * 1000
        else:
            logger.info(
                f"Phase 5: no layout sections detected, skipping for {component_id}"
            )

        datasheet = datasheet.model_copy(update={"component_id": component_id})

        if datasheet.review_required:
            logger.info(f"Queueing {component_id} for review (review_required=True)")
            from src.datasheet.phase4_validate import validate

            validation_result_for_queue = validate(datasheet, config)
            enqueue(datasheet, validation_result_for_queue, config)

        logger.info(
            f"Pipeline completed for {component_id}: "
            f"confidence={datasheet.extraction_confidence:.3f}, "
            f"review_required={datasheet.review_required}"
        )

        return datasheet

    except DatasheetPipelineError:
        raise
    except Exception as exc:
        logger.error(f"Pipeline failed at {phase_name} for {component_id}: {exc}")
        raise DatasheetPipelineError(phase_name, component_id, exc) from exc
