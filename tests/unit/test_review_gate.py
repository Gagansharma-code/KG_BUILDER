"""Unit tests for the blocking human-review gate (orchestrator level).

Covers: the gate halting downstream stages, BOM snapshot persistence in the
SQLite review queue, design-level approve/reject, and resume_after_review
continuing from the persisted snapshot (never regenerating).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.orchestrator import E2EResult, resume_after_review, run_e2e
from src.output import OutputResult
from src.layout._schemas import LayoutSpec
from src.review._schemas import GateStage
from src.schemas.kg import DesignSubgraph
from src.schemas.nir import (
    NIR,
    BoardSpec,
    NetlistEntry,
    PinRef,
    PlacementConstraint,
    ReviewFlag,
)
from src.review.queue import (
    enqueue_bom,
    enqueue_for_review,
    get_bom_review_item,
    get_review_item,
    set_design_review_status,
)
from src.schematic._schemas import ERCResult, ERCViolation, SchematicGraph
from src.schemas.intent import (
    BOMEntry,
    DesignMethodology,
    ImprovedIntentDict,
    ValidatedBOM,
)

PROMPT = "Design a 3.3V LDO regulator"


def _intent() -> ImprovedIntentDict:
    return ImprovedIntentDict(
        goal="ldo_regulator",
        application="iot",
        design_methodology=DesignMethodology.POWER_MANAGEMENT,
        board_type="double_sided_SMD",
        raw_prompt=PROMPT,
    )


def _validated_bom(*, review_required: bool, design_id: str | None = None) -> ValidatedBOM:
    return ValidatedBOM(
        design_id=design_id or str(uuid.uuid4()),
        intent=_intent(),
        components=[
            BOMEntry(
                ref="U1",
                component_type="ldo_regulator",
                specific_part="TPS7A20",
                justification="test",
                source="rule",
                confidence=0.9,
            )
        ],
        total_confidence=0.5 if review_required else 0.95,
        review_required=review_required,
        review_flags=["CRITICAL: low confidence"] if review_required else [],
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def _config(tmp_path: Path) -> MagicMock:
    config = MagicMock()
    config.review_queue_path = tmp_path / "review_queue.db"
    config.confidence_thresholds = {"layout_constraint": 0.85}
    return config


def _subgraph() -> DesignSubgraph:
    return DesignSubgraph(
        component_types=[],
        component_instances=[],
        design_rules=[],
        placement_rules=[],
        routing_hints=[],
        design_methodology="power_management",
        path_confidences={},
        query_depth=0,
        query_metadata={},
    )


def _schematic(*, review_required: bool = False, marker: str = "reviewed_net") -> SchematicGraph:
    violations = (
        [
            ERCViolation(
                severity="CRITICAL",
                rule_name="no_output_conflict",
                affected_refs=["U1"],
                message="Output conflict on U1",
            )
        ]
        if review_required
        else []
    )
    flags = (
        [
            ReviewFlag(
                item_ref="U1",
                reason="Output conflict on U1",
                severity="CRITICAL",
                stage="schematic_synthesis",
            )
        ]
        if review_required
        else []
    )
    return SchematicGraph(
        netlist=[
            NetlistEntry(
                net_name=marker,
                net_type="signal",
                connections=[
                    PinRef(ref="U1", pin_name="OUT", pin_number="1"),
                    PinRef(ref="U2", pin_name="IN", pin_number="2"),
                ],
                source_rule="test",
                net_confidence=0.91,
            )
        ],
        blocks=[],
        erc_result=ERCResult(
            passed=not review_required,
            violations=violations,
            rules_checked=1,
        ),
        synthesis_confidence=0.91,
        unresolved_pins=[],
        review_flags=flags,
    )


def _layout(*, review_required: bool = False, marker: str = "reviewed_layout") -> LayoutSpec:
    confidence = 0.5 if review_required else 0.95
    return LayoutSpec(
        placement_constraints=[
            PlacementConstraint(
                ref=marker,
                constraint_type="proximity",
                relative_to="U2",
                relative_to_type="component",
                max_distance_mm=2.0,
                hard=True,
                source="test",
                confidence=confidence,
            )
        ],
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


def _nir(
    design_id: str = "d1",
    *,
    review_required: bool = False,
    marker: str = "reviewed_nir",
) -> NIR:
    flags = (
        [
            ReviewFlag(
                item_ref=marker,
                reason="NIR validation failed",
                severity="CRITICAL",
                stage="nir_validation",
            )
        ]
        if review_required
        else []
    )
    return NIR(
        design_id=design_id,
        prompt=PROMPT,
        design_methodology="power_management",
        components=[],
        netlist=[
            NetlistEntry(
                net_name=marker,
                net_type="signal",
                connections=[],
                source_rule="test",
                net_confidence=0.93,
            )
        ],
        placement_constraints=[],
        board_spec=BoardSpec(
            layers=2,
            material="FR4",
            thickness_mm=1.6,
            min_trace_width_mm=0.15,
            min_clearance_mm=0.15,
        ),
        review_flags=flags,
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


class TestOrchestratorGateBlocks:
    """review_required=True must not reach synthesis/output stages."""

    @patch("src.orchestrator.run_output_pipeline")
    @patch("src.orchestrator.build_nir")
    @patch("src.orchestrator.generate_layout_spec")
    @patch("src.orchestrator.synthesize_schematic")
    @patch("src.orchestrator.query_graph")
    @patch("src.orchestrator.run_intent_pipeline")
    def test_gate_blocks_downstream_stages(
        self,
        mock_intent,
        mock_query,
        mock_schematic,
        mock_layout,
        mock_nir,
        mock_output,
        tmp_path: Path,
    ) -> None:
        bom = _validated_bom(review_required=True)
        mock_intent.return_value = (_intent(), bom, None)
        config = _config(tmp_path)

        result = run_e2e(PROMPT, MagicMock(), tmp_path, config)

        mock_schematic.assert_not_called()
        mock_layout.assert_not_called()
        mock_nir.assert_not_called()
        mock_output.assert_not_called()
        mock_query.assert_not_called()
        assert result.status == "pending_review"
        assert result.overall_success is False
        assert result.validated_bom.design_id == bom.design_id

    @patch("src.orchestrator.run_output_pipeline")
    @patch("src.orchestrator.build_nir")
    @patch("src.orchestrator.generate_layout_spec")
    @patch("src.orchestrator.synthesize_schematic")
    @patch("src.orchestrator.query_graph")
    @patch("src.orchestrator.run_intent_pipeline")
    def test_gate_enqueues_snapshot_if_missing(
        self,
        mock_intent,
        mock_query,
        mock_schematic,
        mock_layout,
        mock_nir,
        mock_output,
        tmp_path: Path,
    ) -> None:
        """The fallback path (never enqueued by intent pipeline) gets enqueued."""
        bom = _validated_bom(review_required=True)
        mock_intent.return_value = (_intent(), bom, None)
        config = _config(tmp_path)

        run_e2e(PROMPT, MagicMock(), tmp_path, config)

        item = get_bom_review_item(bom.design_id, config)
        assert item is not None
        assert item.status == "pending"
        assert item.bom_json is not None
        restored = ValidatedBOM.model_validate_json(item.bom_json)
        assert restored.design_id == bom.design_id

    @patch("src.orchestrator.run_output_pipeline")
    @patch("src.orchestrator.build_nir")
    @patch("src.orchestrator.generate_layout_spec")
    @patch("src.orchestrator.synthesize_schematic")
    @patch("src.orchestrator.query_graph")
    @patch("src.orchestrator.run_intent_pipeline")
    def test_clean_bom_passes_gate(
        self,
        mock_intent,
        mock_query,
        mock_schematic,
        mock_layout,
        mock_nir,
        mock_output,
        tmp_path: Path,
    ) -> None:
        bom = _validated_bom(review_required=False)
        mock_intent.return_value = (_intent(), bom, None)
        mock_query.return_value = _subgraph()
        mock_schematic.return_value = _schematic()
        mock_layout.return_value = _layout()
        mock_nir.return_value = _nir(bom.design_id)
        mock_output.return_value = OutputResult(
            design_id=bom.design_id, overall_success=True
        )

        result = run_e2e(PROMPT, MagicMock(), tmp_path, _config(tmp_path))

        mock_schematic.assert_called_once()
        mock_layout.assert_called_once()
        mock_nir.assert_called_once()
        mock_output.assert_called_once()
        assert result.status == "completed"

    @patch("src.orchestrator.run_output_pipeline")
    @patch("src.orchestrator.build_nir")
    @patch("src.orchestrator.generate_layout_spec")
    @patch("src.orchestrator.synthesize_schematic")
    @patch("src.orchestrator.normalize_pins")
    @patch("src.orchestrator.query_graph")
    @patch("src.orchestrator.run_intent_pipeline")
    def test_netlist_gate_blocks_layout_nir_and_output(
        self,
        mock_intent,
        mock_query,
        mock_normalize,
        mock_schematic,
        mock_layout,
        mock_nir,
        mock_output,
        tmp_path: Path,
    ) -> None:
        bom = _validated_bom(review_required=False)
        config = _config(tmp_path)
        mock_intent.return_value = (_intent(), bom, None)
        mock_query.return_value = _subgraph()
        mock_normalize.return_value = []
        mock_schematic.return_value = _schematic(review_required=True)

        result = run_e2e(PROMPT, MagicMock(), tmp_path, config)

        mock_layout.assert_not_called()
        mock_nir.assert_not_called()
        mock_output.assert_not_called()
        assert result.status == "pending_review"
        item = get_review_item(bom.design_id, GateStage.NETLIST, config)
        assert item is not None
        assert item.artifact_json is not None
        assert "reviewed_net" in item.artifact_json

    @patch("src.orchestrator.run_output_pipeline")
    @patch("src.orchestrator.build_nir")
    @patch("src.orchestrator.generate_layout_spec")
    @patch("src.orchestrator.synthesize_schematic")
    @patch("src.orchestrator.normalize_pins")
    @patch("src.orchestrator.query_graph")
    @patch("src.orchestrator.run_intent_pipeline")
    def test_layout_gate_blocks_nir_and_output(
        self,
        mock_intent,
        mock_query,
        mock_normalize,
        mock_schematic,
        mock_layout,
        mock_nir,
        mock_output,
        tmp_path: Path,
    ) -> None:
        bom = _validated_bom(review_required=False)
        config = _config(tmp_path)
        mock_intent.return_value = (_intent(), bom, None)
        mock_query.return_value = _subgraph()
        mock_normalize.return_value = []
        mock_schematic.return_value = _schematic()
        mock_layout.return_value = _layout(review_required=True)

        result = run_e2e(PROMPT, MagicMock(), tmp_path, config)

        mock_nir.assert_not_called()
        mock_output.assert_not_called()
        assert result.status == "pending_review"
        item = get_review_item(bom.design_id, GateStage.LAYOUT, config)
        assert item is not None
        assert item.artifact_json is not None
        assert "reviewed_layout" in item.artifact_json

    @patch("src.orchestrator.run_output_pipeline")
    @patch("src.orchestrator.build_nir")
    @patch("src.orchestrator.generate_layout_spec")
    @patch("src.orchestrator.synthesize_schematic")
    @patch("src.orchestrator.normalize_pins")
    @patch("src.orchestrator.query_graph")
    @patch("src.orchestrator.run_intent_pipeline")
    def test_nir_gate_blocks_output(
        self,
        mock_intent,
        mock_query,
        mock_normalize,
        mock_schematic,
        mock_layout,
        mock_nir,
        mock_output,
        tmp_path: Path,
    ) -> None:
        bom = _validated_bom(review_required=False)
        config = _config(tmp_path)
        mock_intent.return_value = (_intent(), bom, None)
        mock_query.return_value = _subgraph()
        mock_normalize.return_value = []
        mock_schematic.return_value = _schematic()
        mock_layout.return_value = _layout()
        mock_nir.return_value = _nir(bom.design_id, review_required=True)

        result = run_e2e(PROMPT, MagicMock(), tmp_path, config)

        mock_output.assert_not_called()
        assert result.status == "pending_review"
        item = get_review_item(bom.design_id, GateStage.NIR, config)
        assert item is not None
        assert item.artifact_json is not None
        assert "reviewed_nir" in item.artifact_json


class TestQueueSnapshotPersistence:
    def test_enqueue_bom_stores_full_snapshot(self, tmp_path: Path) -> None:
        bom = _validated_bom(review_required=True)
        config = _config(tmp_path)
        item = enqueue_bom(bom, config)

        assert item.bom_json is not None
        stored = get_bom_review_item(bom.design_id, config)
        assert stored is not None
        restored = ValidatedBOM.model_validate_json(stored.bom_json)
        assert restored == bom  # exact roundtrip — same BOM the human reviews

    def test_migration_adds_column_to_old_db(self, tmp_path: Path) -> None:
        """A pre-gate DB without bom_json gets migrated in place."""
        import sqlite3

        db_path = tmp_path / "review_queue.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """
            CREATE TABLE review_queue (
                item_id TEXT PRIMARY KEY, stage TEXT NOT NULL,
                component_id TEXT NOT NULL, pdf_path TEXT NOT NULL,
                severity TEXT NOT NULL, verdict TEXT NOT NULL,
                flags TEXT NOT NULL, created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                resolved_at TEXT, resolution_notes TEXT
            )
            """
        )
        conn.commit()
        conn.close()

        config = _config(tmp_path)
        bom = _validated_bom(review_required=True)
        enqueue_bom(bom, config)  # triggers _init_db migration
        stored = get_bom_review_item(bom.design_id, config)
        assert stored is not None
        assert stored.bom_json is not None


class TestDesignReviewStatus:
    def test_approve_by_design_id(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        bom = _validated_bom(review_required=True)
        enqueue_bom(bom, config)

        item = set_design_review_status(bom.design_id, "approved", "LGTM", config)
        assert item.status == "approved"
        assert item.resolved_at is not None
        assert get_bom_review_item(bom.design_id, config).status == "approved"

    def test_reject_by_design_id(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        bom = _validated_bom(review_required=True)
        enqueue_bom(bom, config)

        item = set_design_review_status(bom.design_id, "rejected", "bad part", config)
        assert item.status == "rejected"

    def test_unknown_design_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="No bom_generation review item"):
            set_design_review_status("ghost", "approved", "", _config(tmp_path))


class TestResumeAfterReview:
    @patch("src.orchestrator._run_post_bom_stages")
    def test_approved_resumes_with_persisted_bom(
        self, mock_stages, tmp_path: Path
    ) -> None:
        config = _config(tmp_path)
        bom = _validated_bom(review_required=True)
        enqueue_bom(bom, config)
        set_design_review_status(bom.design_id, "approved", "ok", config)

        expected = MagicMock(spec=E2EResult)
        mock_stages.return_value = expected

        result = resume_after_review(bom.design_id, MagicMock(), tmp_path, config)

        assert result is expected
        mock_stages.assert_called_once()
        # The BOM passed downstream is the deserialized persisted snapshot,
        # not a regenerated one.
        passed_bom = mock_stages.call_args[0][2]
        assert isinstance(passed_bom, ValidatedBOM)
        assert passed_bom == bom

    @patch("src.orchestrator._run_post_bom_stages")
    def test_pending_does_not_proceed(self, mock_stages, tmp_path: Path) -> None:
        config = _config(tmp_path)
        bom = _validated_bom(review_required=True)
        enqueue_bom(bom, config)

        result = resume_after_review(bom.design_id, MagicMock(), tmp_path, config)

        mock_stages.assert_not_called()
        assert result.status == "pending_review"
        assert result.overall_success is False

    @patch("src.orchestrator._run_post_bom_stages")
    def test_rejected_does_not_proceed(self, mock_stages, tmp_path: Path) -> None:
        config = _config(tmp_path)
        bom = _validated_bom(review_required=True)
        enqueue_bom(bom, config)
        set_design_review_status(bom.design_id, "rejected", "nope", config)

        result = resume_after_review(bom.design_id, MagicMock(), tmp_path, config)

        mock_stages.assert_not_called()
        assert result.status == "rejected"

    @patch("src.orchestrator._run_post_bom_stages")
    def test_unknown_design_fails_cleanly(self, mock_stages, tmp_path: Path) -> None:
        result = resume_after_review("ghost", MagicMock(), tmp_path, _config(tmp_path))
        mock_stages.assert_not_called()
        assert result.status == "failed"
        assert result.overall_success is False

    @patch("src.orchestrator.run_output_pipeline")
    @patch("src.orchestrator.build_nir")
    @patch("src.orchestrator.generate_layout_spec")
    @patch("src.orchestrator.synthesize_schematic")
    def test_approved_netlist_resumes_from_persisted_netlist(
        self,
        mock_schematic,
        mock_layout,
        mock_nir,
        mock_output,
        tmp_path: Path,
    ) -> None:
        config = _config(tmp_path)
        bom = _validated_bom(review_required=False)
        reviewed = _schematic(marker="persisted_netlist")
        layout = _layout()
        nir = _nir(bom.design_id)
        enqueue_for_review(
            reviewed,
            GateStage.NETLIST,
            bom.design_id,
            config,
            resume_context={
                "validated_bom": bom,
                "datasheets": [],
                "subgraph": _subgraph(),
            },
        )
        set_design_review_status(
            bom.design_id, "approved", "ok", config, stage=GateStage.NETLIST
        )
        mock_layout.return_value = layout
        mock_nir.return_value = nir
        mock_output.return_value = OutputResult(design_id=bom.design_id, overall_success=True)

        result = resume_after_review(
            bom.design_id, MagicMock(), tmp_path, config, stage=GateStage.NETLIST
        )

        mock_schematic.assert_not_called()
        passed_schematic = mock_layout.call_args[0][0]
        assert isinstance(passed_schematic, SchematicGraph)
        assert passed_schematic.netlist[0].net_name == "persisted_netlist"
        assert result.status == "completed"

    @patch("src.orchestrator.run_output_pipeline")
    @patch("src.orchestrator.build_nir")
    @patch("src.orchestrator.generate_layout_spec")
    def test_approved_layout_resumes_from_persisted_layout(
        self,
        mock_layout_stage,
        mock_nir,
        mock_output,
        tmp_path: Path,
    ) -> None:
        config = _config(tmp_path)
        bom = _validated_bom(review_required=False)
        reviewed = _layout(marker="persisted_layout")
        nir = _nir(bom.design_id)
        enqueue_for_review(
            reviewed,
            GateStage.LAYOUT,
            bom.design_id,
            config,
            resume_context={
                "validated_bom": bom,
                "datasheets": [],
                "schematic": _schematic(),
            },
        )
        set_design_review_status(
            bom.design_id, "approved", "ok", config, stage=GateStage.LAYOUT
        )
        mock_nir.return_value = nir
        mock_output.return_value = OutputResult(design_id=bom.design_id, overall_success=True)

        result = resume_after_review(
            bom.design_id, MagicMock(), tmp_path, config, stage=GateStage.LAYOUT
        )

        mock_layout_stage.assert_not_called()
        passed_layout = mock_nir.call_args[0][3]
        assert isinstance(passed_layout, LayoutSpec)
        assert passed_layout.placement_constraints[0].ref == "persisted_layout"
        assert result.status == "completed"

    @patch("src.orchestrator.run_output_pipeline")
    @patch("src.orchestrator.build_nir")
    def test_approved_nir_resumes_from_persisted_nir(
        self,
        mock_nir_stage,
        mock_output,
        tmp_path: Path,
    ) -> None:
        config = _config(tmp_path)
        bom = _validated_bom(review_required=False)
        reviewed = _nir(bom.design_id, marker="persisted_nir")
        enqueue_for_review(
            reviewed,
            GateStage.NIR,
            bom.design_id,
            config,
            resume_context={"validated_bom": bom},
        )
        set_design_review_status(
            bom.design_id, "approved", "ok", config, stage=GateStage.NIR
        )
        mock_output.return_value = OutputResult(design_id=bom.design_id, overall_success=True)

        result = resume_after_review(
            bom.design_id, MagicMock(), tmp_path, config, stage=GateStage.NIR
        )

        mock_nir_stage.assert_not_called()
        passed_nir = mock_output.call_args[0][0]
        assert isinstance(passed_nir, NIR)
        assert passed_nir.netlist[0].net_name == "persisted_nir"
        assert result.status == "completed"
