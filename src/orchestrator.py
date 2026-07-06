"""OpenForge E2E orchestrator — single prompt-to-files entry point."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from src.config import Config
from src.datasheet.pipeline import DatasheetPipelineError, parse_datasheet
from src.intent.pipeline import run_intent_pipeline
from src.knowledge_graph import query_graph
from src.knowledge_graph.graph import KnowledgeGraph
from src.knowledge_graph.pin_normalizer import normalize_pins
from src.layout import generate_layout_spec
from src.layout._schemas import LayoutSpec
from src.nir import build_nir
from src.output import OutputResult, run_output_pipeline
from src.review._schemas import GateStage, ReviewQueueItem
from src.review.queue import enqueue_for_review, get_review_item
from src.schemas.datasheet import ComponentDatasheet, ExtractionMethod
from src.schemas.intent import DesignMethodology, ImprovedIntentDict, ValidatedBOM
from src.schemas.kg import DesignSubgraph
from src.schemas.nir import NIR, ReviewFlag
from src.schematic import synthesize_schematic
from src.schematic._schemas import SchematicGraph
from src.synthesis.pipeline import _failure_nir

logger = logging.getLogger(__name__)

__all__ = ["E2EResult", "run_e2e", "resume_after_review"]


class E2EResult(BaseModel):
    design_id: str
    prompt: str
    validated_bom: ValidatedBOM
    datasheets_parsed: int
    datasheets_skipped: int
    nir: NIR
    output: OutputResult
    overall_success: bool
    # "completed": ran all stages; "pending_review": halted at the human
    # review gate (BOM enqueued, awaiting approval); "rejected": reviewer
    # rejected the design; "failed": internal failure.
    status: str = "completed"


def _resolve_pdf(component_id: str, config: Config) -> Optional[Path]:
    # Fallback Path("corpus") when config lacks corpus_dir (e.g. partial test mocks).
    corpus = getattr(config, "corpus_dir", Path("corpus"))
    candidates = (
        corpus / "datasheets" / f"{component_id}.pdf",
        corpus / "golden" / f"{component_id}.pdf",
    )
    for path in candidates:
        if path.exists():
            return path
    return None


def _skeleton_datasheet(component_id: str) -> ComponentDatasheet:
    return ComponentDatasheet(
        component_id=component_id,
        manufacturer="",
        description="Skeleton — no PDF available",
        package="",
        source_pdf_hash="",
        electrical_parameters=[],
        absolute_max_ratings=[],
        pins=[],
        layout_constraints=[],
        extraction_method=ExtractionMethod.LLM_FALLBACK,
        extraction_confidence=0.0,
        review_required=True,
        review_flags=[f"No datasheet PDF found for {component_id}"],
        pipeline_version="skeleton",
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def _empty_bom(prompt: str) -> ValidatedBOM:
    from src.schemas.common import Ambiguity

    intent = ImprovedIntentDict(
        goal="unknown",
        application="unknown",
        design_methodology=DesignMethodology.STANDARD_SMD,
        board_type="standard_SMD",
        raw_prompt=prompt or "(unknown prompt)",
        clarification_required=True,
        ambiguities=[
            Ambiguity(
                field="goal",
                description="Pipeline failure fallback — original intent unavailable",
                severity="ERROR",
                blocking=True,
            )
        ],
    )
    return ValidatedBOM(
        design_id=str(uuid.uuid4()),
        intent=intent,
        components=[],
        total_confidence=0.0,
        review_required=True,
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def _failure_result(
    prompt: str,
    validated_bom: ValidatedBOM | None,
    reason: str,
    status: str = "failed",
) -> E2EResult:
    bom = validated_bom or _empty_bom(prompt)
    nir = _failure_nir(bom, reason)
    output = OutputResult(
        design_id=nir.design_id,
        overall_success=False,
    )
    return E2EResult(
        design_id=nir.design_id,
        prompt=prompt,
        validated_bom=bom,
        datasheets_parsed=0,
        datasheets_skipped=0,
        nir=nir,
        output=output,
        overall_success=False,
        status=status,
    )


def _pending_review_result(
    prompt: str,
    validated_bom: ValidatedBOM,
    stage: GateStage = GateStage.BOM,
) -> E2EResult:
    """Blocked-at-gate result: artifact is enqueued, downstream stages not run."""
    return _failure_result(
        prompt,
        validated_bom,
        f"Human review required — design halted at the {stage.value} review gate. "
        "Approve via `python -m src.review.cli approve-design "
        f"{validated_bom.design_id} --stage {stage.value}` then call "
        "resume_after_review().",
        status="pending_review",
    )


def _review_flag_strings(flags: list[ReviewFlag]) -> list[str]:
    return [
        f"{flag.severity}: {flag.stage}: {flag.item_ref}: {flag.reason}"
        for flag in flags
    ]


def _netlist_review_required(schematic: SchematicGraph) -> bool:
    return (not schematic.erc_result.passed) or any(
        flag.severity == "CRITICAL" for flag in schematic.review_flags
    )


def _netlist_review_flags(schematic: SchematicGraph) -> list[str]:
    flags = _review_flag_strings(schematic.review_flags)
    flags.extend(
        f"{violation.severity}: erc: {violation.rule_name}: {violation.message}"
        for violation in schematic.erc_result.violations
    )
    if not flags and not schematic.erc_result.passed:
        flags.append("CRITICAL: erc: ERC failed without detailed violations")
    return flags


def _layout_review_flags(layout: LayoutSpec, config: Config) -> list[str]:
    # Placeholder pending real layout-review data: 0.85 has weak precedent
    # from BOM confidence gates, but no validated layout-specific calibration.
    # WHATS_LEFT.md tracks calibration as minor follow-up work.
    threshold = getattr(config, "confidence_thresholds", {}).get(
        "layout_constraint", 0.85
    )
    flags: list[str] = []
    for constraint in layout.placement_constraints:
        if constraint.hard and constraint.confidence < threshold:
            flags.append(
                "CRITICAL: layout_generation: "
                f"{constraint.ref}: hard {constraint.constraint_type} constraint "
                f"confidence {constraint.confidence:.2f} below {threshold:.2f}"
            )
    return flags


def _nir_review_flags(nir: NIR) -> list[str]:
    return _review_flag_strings(nir.review_flags)


def _snapshot_payload(item: ReviewQueueItem) -> dict:
    if item.artifact_json:
        payload = json.loads(item.artifact_json)
        if isinstance(payload, dict) and "artifact" in payload:
            return payload
        if item.bom_json:
            return {
                "stage": GateStage.BOM.value,
                "artifact_type": "ValidatedBOM",
                "artifact": payload,
                "resume_context": {},
            }
    if item.bom_json:
        return {
            "stage": GateStage.BOM.value,
            "artifact_type": "ValidatedBOM",
            "artifact": json.loads(item.bom_json),
            "resume_context": {},
        }
    raise ValueError(
        f"Review item {item.item_id} has no persisted artifact snapshot"
    )


def _bom_from_review_item(item: ReviewQueueItem) -> ValidatedBOM | None:
    try:
        payload = _snapshot_payload(item)
        if payload.get("artifact_type") == "ValidatedBOM":
            return ValidatedBOM.model_validate(payload["artifact"])
        context = payload.get("resume_context", {})
        if "validated_bom" in context:
            return ValidatedBOM.model_validate(context["validated_bom"])
    except Exception:
        logger.warning("Could not parse reviewed BOM snapshot", exc_info=True)
    return None


def run_e2e(
    prompt: str,
    graph: KnowledgeGraph,
    output_dir: Path,
    config: Config,
) -> E2EResult:
    """
    Single entry point: natural language prompt → fabrication files.

    Steps: intent → KG re-query → datasheet parsing → pin normalisation
           → synthesis → serialization.

    Never raises. Returns E2EResult with overall_success=False on any
    internal failure. All failures are logged at ERROR level.
    """
    validated_bom: ValidatedBOM | None = None
    try:
        logger.info("Step 1: running intent pipeline")
        intent, validated_bom, _retrieval_result = run_intent_pipeline(
            prompt, graph, config
        )
        if validated_bom.review_required:
            # Blocking human-review gate (OPENFORGE_ARCHITECTURE.md §8):
            # the BOM is already enqueued by run_intent_pipeline with its
            # full JSON snapshot. Downstream synthesis/serialization must
            # not run until a human approves; resume_after_review()
            # continues from the persisted snapshot.
            logger.warning(
                "BOM review_required=True for design %s — halting at review "
                "gate (pending human approval)",
                validated_bom.design_id,
            )
            # run_intent_pipeline enqueues on its normal paths, but its
            # exception-fallback BOM is not enqueued — ensure a queue item
            # with an artifact snapshot exists so approval/resume is possible.
            try:
                if (
                    get_review_item(
                        validated_bom.design_id, GateStage.BOM, config
                    )
                    is None
                ):
                    enqueue_for_review(
                        validated_bom,
                        GateStage.BOM,
                        validated_bom.design_id,
                        config,
                        flags=validated_bom.review_flags,
                    )
            except Exception as queue_exc:
                logger.error("Failed to ensure review queue item: %s", queue_exc)
            return _pending_review_result(prompt, validated_bom, GateStage.BOM)

        return _run_post_bom_stages(
            prompt, intent, validated_bom, graph, output_dir, config
        )

    except Exception as exc:
        logger.error("E2E pipeline failed: %s", exc, exc_info=True)
        return _failure_result(
            prompt,
            validated_bom,
            f"E2E pipeline failed: {exc}",
        )


def _run_post_bom_stages(
    prompt: str,
    intent: ImprovedIntentDict,
    validated_bom: ValidatedBOM,
    graph: KnowledgeGraph,
    output_dir: Path,
    config: Config,
) -> E2EResult:
    """Steps 2-6: subgraph re-query → datasheets → pins → Team D → output.

    Shared by run_e2e (unreviewed pass-through) and resume_after_review
    (post-BOM-approval continuation). Never raises.
    """
    try:
        logger.info("Step 2: re-querying knowledge graph for subgraph")
        # run_intent_pipeline computes a subgraph internally but does not expose it.
        # Re-querying is acceptable duplication for the first E2E pass.
        subgraph: DesignSubgraph = query_graph(intent, graph, config)

        logger.info("Step 3: parsing datasheets for BOM components")
        raw_datasheets: list[ComponentDatasheet] = []
        for entry in validated_bom.components:
            component_id = entry.specific_part or entry.component_type
            pdf_path = _resolve_pdf(component_id, config)
            if pdf_path is None:
                logger.warning(
                    "No datasheet PDF found for %s; using skeleton datasheet",
                    component_id,
                )
                raw_datasheets.append(_skeleton_datasheet(component_id))
                continue

            try:
                raw_datasheets.append(
                    parse_datasheet(component_id, pdf_path, config)
                )
            except (DatasheetPipelineError, FileNotFoundError) as exc:
                logger.warning(
                    "Datasheet parse failed for %s: %s",
                    component_id,
                    exc,
                )
                raw_datasheets.append(_skeleton_datasheet(component_id))

        datasheets_skipped = sum(
            1 for ds in raw_datasheets if ds.pipeline_version == "skeleton"
        )
        datasheets_parsed = len(raw_datasheets) - datasheets_skipped

        logger.info("Step 4: normalizing pins")
        datasheets = normalize_pins(raw_datasheets, config)

        logger.info("Step 5: running synthesis pipeline")
        schematic = synthesize_schematic(validated_bom, datasheets, subgraph, config)
        if _netlist_review_required(schematic):
            logger.warning(
                "Netlist review required for design %s — halting before layout",
                validated_bom.design_id,
            )
            enqueue_for_review(
                schematic,
                GateStage.NETLIST,
                validated_bom.design_id,
                config,
                flags=_netlist_review_flags(schematic),
                resume_context={
                    "validated_bom": validated_bom,
                    "datasheets": datasheets,
                    "subgraph": subgraph,
                },
            )
            return _pending_review_result(prompt, validated_bom, GateStage.NETLIST)

        return _run_post_netlist_stages(
            prompt,
            validated_bom,
            datasheets,
            schematic,
            subgraph,
            output_dir,
            config,
            datasheets_parsed=datasheets_parsed,
            datasheets_skipped=datasheets_skipped,
        )

    except Exception as exc:
        logger.error("E2E pipeline failed: %s", exc, exc_info=True)
        return _failure_result(
            prompt,
            validated_bom,
            f"E2E pipeline failed: {exc}",
        )


def _run_post_netlist_stages(
    prompt: str,
    validated_bom: ValidatedBOM,
    datasheets: list[ComponentDatasheet],
    schematic: SchematicGraph,
    subgraph: DesignSubgraph,
    output_dir: Path,
    config: Config,
    datasheets_parsed: int = 0,
    datasheets_skipped: int = 0,
) -> E2EResult:
    """Continue after the netlist gate: layout → NIR → output."""
    try:
        logger.info("Step 6: generating layout spec")
        layout = generate_layout_spec(schematic, datasheets, subgraph, config)
        layout_flags = _layout_review_flags(layout, config)
        if layout_flags:
            logger.warning(
                "Layout review required for design %s — halting before NIR",
                validated_bom.design_id,
            )
            enqueue_for_review(
                layout,
                GateStage.LAYOUT,
                validated_bom.design_id,
                config,
                flags=layout_flags,
                severity="CRITICAL",
                resume_context={
                    "validated_bom": validated_bom,
                    "datasheets": datasheets,
                    "schematic": schematic,
                },
            )
            return _pending_review_result(prompt, validated_bom, GateStage.LAYOUT)

        return _run_post_layout_stages(
            prompt,
            validated_bom,
            datasheets,
            schematic,
            layout,
            output_dir,
            config,
            datasheets_parsed=datasheets_parsed,
            datasheets_skipped=datasheets_skipped,
        )

    except Exception as exc:
        logger.error("E2E pipeline failed: %s", exc, exc_info=True)
        return _failure_result(
            prompt,
            validated_bom,
            f"E2E pipeline failed: {exc}",
        )


def _run_post_layout_stages(
    prompt: str,
    validated_bom: ValidatedBOM,
    datasheets: list[ComponentDatasheet],
    schematic: SchematicGraph,
    layout: LayoutSpec,
    output_dir: Path,
    config: Config,
    datasheets_parsed: int = 0,
    datasheets_skipped: int = 0,
) -> E2EResult:
    """Continue after the layout gate: NIR → output."""
    try:
        logger.info("Step 7: building NIR")
        nir = build_nir(validated_bom, datasheets, schematic, layout, config)
        if nir.is_review_required():
            logger.warning(
                "NIR review required for design %s — halting before output",
                validated_bom.design_id,
            )
            enqueue_for_review(
                nir,
                GateStage.NIR,
                validated_bom.design_id,
                config,
                flags=_nir_review_flags(nir),
                severity="CRITICAL",
                resume_context={"validated_bom": validated_bom},
            )
            return _pending_review_result(prompt, validated_bom, GateStage.NIR)

        return _run_output_stage(
            prompt,
            validated_bom,
            nir,
            output_dir,
            config,
            datasheets_parsed=datasheets_parsed,
            datasheets_skipped=datasheets_skipped,
        )

    except Exception as exc:
        logger.error("E2E pipeline failed: %s", exc, exc_info=True)
        return _failure_result(
            prompt,
            validated_bom,
            f"E2E pipeline failed: {exc}",
        )


def _run_output_stage(
    prompt: str,
    validated_bom: ValidatedBOM,
    nir: NIR,
    output_dir: Path,
    config: Config,
    datasheets_parsed: int = 0,
    datasheets_skipped: int = 0,
) -> E2EResult:
    """Run serializers after all review gates have passed."""
    try:
        logger.info("Step 8: running output pipeline")
        output = run_output_pipeline(nir, output_dir, config)

        result = E2EResult(
            design_id=nir.design_id,
            prompt=prompt,
            validated_bom=validated_bom,
            datasheets_parsed=datasheets_parsed,
            datasheets_skipped=datasheets_skipped,
            nir=nir,
            output=output,
            overall_success=output.overall_success,
        )
        logger.info(
            "E2E complete: design_id=%s parsed=%d skipped=%d success=%s",
            result.design_id,
            result.datasheets_parsed,
            result.datasheets_skipped,
            result.overall_success,
        )
        return result

    except Exception as exc:
        logger.error("E2E pipeline failed: %s", exc, exc_info=True)
        return _failure_result(
            prompt,
            validated_bom,
            f"E2E pipeline failed: {exc}",
        )

def resume_after_review(
    design_id: str,
    graph: KnowledgeGraph,
    output_dir: Path,
    config: Config,
    stage: GateStage | str = GateStage.BOM,
) -> E2EResult:
    """Continue a review-gated design after human approval.

    Checks the persisted review status for design_id + stage. If APPROVED,
    resumes the pipeline from the exact artifact snapshot stored at enqueue
    time — the reviewed artifact is deliberately NOT regenerated, because
    doing so could differ from what the human actually approved.

    Never raises. Returns E2EResult with status one of:
    "completed" / "pending_review" / "rejected" / "failed".
    """
    try:
        gate_stage = stage if isinstance(stage, GateStage) else GateStage(stage)
        item = get_review_item(design_id, gate_stage, config)
        if item is None:
            return _failure_result(
                "",
                None,
                f"No {gate_stage.value} review queue item found for design {design_id}",
            )

        if item.status == "pending":
            logger.info(
                "Design %s stage %s still pending review — not resuming",
                design_id,
                gate_stage.value,
            )
            bom = _bom_from_review_item(item)
            return _failure_result(
                bom.intent.raw_prompt if bom else "",
                bom,
                f"Design {design_id} stage {gate_stage.value} is still pending review",
                status="pending_review",
            )

        if item.status == "rejected":
            logger.info(
                "Design %s stage %s was rejected — not resuming",
                design_id,
                gate_stage.value,
            )
            bom = _bom_from_review_item(item)
            return _failure_result(
                bom.intent.raw_prompt if bom else "",
                bom,
                f"Design {design_id} stage {gate_stage.value} was rejected in review"
                + (f": {item.resolution_notes}" if item.resolution_notes else ""),
                status="rejected",
            )

        # approved (or corrected — a human-edited approval)
        if not item.artifact_json and not item.bom_json:
            return _failure_result(
                "",
                None,
                f"Design {design_id} stage {gate_stage.value} is {item.status} "
                "but has no stored artifact snapshot — "
                "re-run the pipeline instead of resuming",
            )

        payload = _snapshot_payload(item)
        context = payload.get("resume_context", {})

        if gate_stage == GateStage.BOM:
            validated_bom = ValidatedBOM.model_validate(payload["artifact"])
            logger.info(
                "Design %s approved — resuming from persisted BOM snapshot",
                design_id,
            )
            return _run_post_bom_stages(
                validated_bom.intent.raw_prompt,
                validated_bom.intent,
                validated_bom,
                graph,
                output_dir,
                config,
            )

        validated_bom = ValidatedBOM.model_validate(context["validated_bom"])
        prompt = validated_bom.intent.raw_prompt
        logger.info(
            "Design %s approved at %s — resuming from persisted artifact snapshot",
            design_id,
            gate_stage.value,
        )

        if gate_stage == GateStage.NETLIST:
            schematic = SchematicGraph.model_validate(payload["artifact"])
            datasheets = [
                ComponentDatasheet.model_validate(ds)
                for ds in context.get("datasheets", [])
            ]
            subgraph = DesignSubgraph.model_validate(context["subgraph"])
            return _run_post_netlist_stages(
                prompt,
                validated_bom,
                datasheets,
                schematic,
                subgraph,
                output_dir,
                config,
            )

        if gate_stage == GateStage.LAYOUT:
            layout = LayoutSpec.model_validate(payload["artifact"])
            datasheets = [
                ComponentDatasheet.model_validate(ds)
                for ds in context.get("datasheets", [])
            ]
            schematic = SchematicGraph.model_validate(context["schematic"])
            return _run_post_layout_stages(
                prompt,
                validated_bom,
                datasheets,
                schematic,
                layout,
                output_dir,
                config,
            )

        if gate_stage == GateStage.NIR:
            nir = NIR.model_validate(payload["artifact"])
            return _run_output_stage(prompt, validated_bom, nir, output_dir, config)

        return _failure_result(
            "",
            None,
            f"Unsupported review stage {gate_stage.value} for design {design_id}",
        )

    except Exception as exc:
        logger.error("resume_after_review failed: %s", exc, exc_info=True)
        return _failure_result("", None, f"resume_after_review failed: {exc}")
