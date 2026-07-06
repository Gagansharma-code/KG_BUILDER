"""Unit tests for scripts/pilot_ingest.py.

Tests the local pilot batch ingestion script: batch continues past
per-MPN download/parse failures, the CRITICAL severity gate blocks KG
import while WARNING-only datasheets still import, and the final report
covers every input MPN with correct outcome counts.

No real network, PDF, or model calls -- every dependency the script calls
(download_pdf, parse_datasheet, import_datasheet, enqueue, resolve_pdf_urls)
is mocked.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config import Config
from src.datasheet.phase4_validate import ValidationResult
from src.datasheet.pipeline import DatasheetPipelineError
from src.knowledge_base.scraper.adapters.base import FetchResult
from src.knowledge_graph.importers._schemas import ImportResult
from src.schemas.datasheet import ComponentDatasheet, ExtractionMethod
from scripts.pilot_ingest import ingest_one, run_pilot

MODULE = "scripts.pilot_ingest"


def make_datasheet(review_required: bool = False, review_flags: list[str] | None = None) -> ComponentDatasheet:
    return ComponentDatasheet(
        component_id="LM358",
        manufacturer="Texas Instruments",
        description="Dual Op-Amp",
        package="SOIC-8",
        source_pdf_hash="deadbeef",
        extraction_method=ExtractionMethod.P1_VECTOR,
        extraction_confidence=0.97,
        review_required=review_required,
        review_flags=review_flags or [],
        created_at="2024-01-15T10:30:00Z",
    )


@pytest.fixture
def mock_config(tmp_path) -> Config:
    config = MagicMock(spec=Config)
    config.graph_path = tmp_path / "graph.graphml"
    config.review_queue_path = tmp_path / "review_queue.db"
    return config


@pytest.fixture
def mock_graph() -> MagicMock:
    return MagicMock()


@pytest.fixture
def fetch_result() -> FetchResult:
    return FetchResult(
        pdf_url="https://example.com/LM358.pdf",
        content_type="application/pdf",
        source="nexar",
        mpn="LM358",
    )


class TestIngestOneDownloadFailure:
    """A download failure for one MPN must not raise and must be recorded."""

    @patch(f"{MODULE}.download_pdf")
    def test_download_failure_is_recorded_not_raised(
        self, mock_download, mock_graph, mock_config, fetch_result
    ):
        mock_download.return_value = None

        record = ingest_one("LM358", fetch_result, mock_graph, mock_config)

        assert record["download_success"] is False
        assert record["parse_success"] is False
        assert record["outcome"] == "failed"
        assert record["error"] is not None

    @patch(f"{MODULE}.parse_datasheet")
    @patch(f"{MODULE}.download_pdf")
    def test_batch_continues_after_one_download_failure(
        self, mock_download, mock_parse, mock_graph, mock_config, fetch_result
    ):
        # First MPN fails to download, second succeeds all the way through.
        mock_download.side_effect = [
            None,
            (Path("/tmp/fake.pdf"), "hash2"),
        ]
        mock_parse.return_value = make_datasheet(review_required=False)

        with patch(f"{MODULE}.resolve_pdf_urls", return_value={
            "BAD": fetch_result,
            "GOOD": fetch_result,
        }), patch(f"{MODULE}.import_datasheet") as mock_import, patch(
            f"{MODULE}.KnowledgeGraph"
        ) as mock_kg_cls:
            mock_kg_cls.return_value = mock_graph
            mock_kg_cls.load.return_value = mock_graph
            mock_graph.stats.return_value = {"node_count": 0}
            mock_import.return_value = ImportResult(
                component_id="GOOD", nodes_created=3, edges_created=2, success=True
            )

            report = run_pilot(["BAD", "GOOD"], mock_config, mock_config.review_queue_path.parent / "report.json")

        assert report["mpn_count"] == 2
        by_mpn = {r["mpn"]: r for r in report["results"]}
        assert by_mpn["BAD"]["outcome"] == "failed"
        assert by_mpn["GOOD"]["outcome"] == "imported_clean"
        mock_import.assert_called_once()


class TestIngestOneParseFailure:
    """A DatasheetPipelineError for one MPN must not raise and must be recorded."""

    @patch(f"{MODULE}.parse_datasheet")
    @patch(f"{MODULE}.download_pdf")
    def test_parse_failure_records_phase_and_does_not_raise(
        self, mock_download, mock_parse, mock_graph, mock_config, fetch_result
    ):
        mock_download.return_value = (Path("/tmp/fake.pdf"), "hash1")
        mock_parse.side_effect = DatasheetPipelineError(
            "Phase 2", "LM358", ValueError("bad table")
        )

        record = ingest_one("LM358", fetch_result, mock_graph, mock_config)

        assert record["download_success"] is True
        assert record["parse_success"] is False
        assert record["failed_phase"] == "Phase 2"
        assert record["outcome"] == "failed"

    @patch(f"{MODULE}.parse_datasheet")
    @patch(f"{MODULE}.download_pdf")
    def test_batch_continues_after_one_parse_failure(
        self, mock_download, mock_parse, mock_graph, mock_config, fetch_result
    ):
        mock_download.return_value = (Path("/tmp/fake.pdf"), "hash1")
        mock_parse.side_effect = [
            DatasheetPipelineError("Phase 3", "BAD", RuntimeError("oops")),
            make_datasheet(review_required=False),
        ]

        with patch(f"{MODULE}.resolve_pdf_urls", return_value={
            "BAD": fetch_result,
            "GOOD": fetch_result,
        }), patch(f"{MODULE}.import_datasheet") as mock_import, patch(
            f"{MODULE}.KnowledgeGraph"
        ) as mock_kg_cls:
            mock_kg_cls.return_value = mock_graph
            mock_kg_cls.load.return_value = mock_graph
            mock_graph.stats.return_value = {"node_count": 0}
            mock_import.return_value = ImportResult(
                component_id="GOOD", nodes_created=1, edges_created=0, success=True
            )

            report = run_pilot(["BAD", "GOOD"], mock_config, mock_config.review_queue_path.parent / "report.json")

        by_mpn = {r["mpn"]: r for r in report["results"]}
        assert by_mpn["BAD"]["outcome"] == "failed"
        assert by_mpn["BAD"]["failed_phase"] == "Phase 3"
        assert by_mpn["GOOD"]["outcome"] == "imported_clean"


class TestCleanDatasheet:
    """A fully clean datasheet calls download -> parse -> import, in order."""

    @patch(f"{MODULE}.import_datasheet")
    @patch(f"{MODULE}.enqueue")
    @patch(f"{MODULE}.parse_datasheet")
    @patch(f"{MODULE}.download_pdf")
    def test_clean_datasheet_calls_steps_in_order_and_skips_enqueue(
        self, mock_download, mock_parse, mock_enqueue, mock_import,
        mock_graph, mock_config, fetch_result,
    ):
        manager = MagicMock()
        manager.attach_mock(mock_download, "download_pdf")
        manager.attach_mock(mock_parse, "parse_datasheet")
        manager.attach_mock(mock_import, "import_datasheet")

        mock_download.return_value = (Path("/tmp/fake.pdf"), "hash1")
        mock_parse.return_value = make_datasheet(review_required=False)
        mock_import.return_value = ImportResult(
            component_id="LM358", nodes_created=5, edges_created=4, success=True
        )

        record = ingest_one("LM358", fetch_result, mock_graph, mock_config)

        assert [c[0] for c in manager.mock_calls] == [
            "download_pdf",
            "parse_datasheet",
            "import_datasheet",
        ]
        assert record["download_success"] is True
        assert record["parse_success"] is True
        assert record["outcome"] == "imported_clean"
        mock_enqueue.assert_not_called()


class TestCriticalGate:
    """A CRITICAL-severity datasheet must never reach import_datasheet."""

    @patch(f"{MODULE}.import_datasheet")
    @patch(f"{MODULE}.enqueue")
    @patch(f"{MODULE}.validate")
    @patch(f"{MODULE}.parse_datasheet")
    @patch(f"{MODULE}.download_pdf")
    def test_critical_blocks_import_and_logs_to_review_queue(
        self, mock_download, mock_parse, mock_validate, mock_enqueue, mock_import,
        mock_graph, mock_config, fetch_result,
    ):
        mock_download.return_value = (Path("/tmp/fake.pdf"), "hash1")
        datasheet = make_datasheet(review_required=True, review_flags=["Low extraction confidence: 0.10"])
        mock_parse.return_value = datasheet
        mock_validate.return_value = ValidationResult(
            verdict="BLOCK", severity="CRITICAL", confidence=0.10,
            flags=["Low extraction confidence: 0.10"],
        )

        record = ingest_one("LM358", fetch_result, mock_graph, mock_config)

        assert record["outcome"] == "blocked_critical"
        mock_import.assert_not_called()
        mock_enqueue.assert_called_once_with(datasheet, mock_validate.return_value, mock_config)


class TestWarningGate:
    """A WARNING-only datasheet must import AND log to the review queue."""

    @patch(f"{MODULE}.import_datasheet")
    @patch(f"{MODULE}.enqueue")
    @patch(f"{MODULE}.validate")
    @patch(f"{MODULE}.parse_datasheet")
    @patch(f"{MODULE}.download_pdf")
    def test_warning_only_imports_and_logs_for_review(
        self, mock_download, mock_parse, mock_validate, mock_enqueue, mock_import,
        mock_graph, mock_config, fetch_result,
    ):
        mock_download.return_value = (Path("/tmp/fake.pdf"), "hash1")
        datasheet = make_datasheet(review_required=True, review_flags=["Missing manufacturer"])
        mock_parse.return_value = datasheet
        mock_validate.return_value = ValidationResult(
            verdict="WARN", severity="WARNING", confidence=0.65,
            flags=["Missing manufacturer"],
        )
        mock_import.return_value = ImportResult(
            component_id="LM358", nodes_created=5, edges_created=4, success=True
        )

        record = ingest_one("LM358", fetch_result, mock_graph, mock_config)

        assert record["outcome"] == "imported_with_warning"
        mock_import.assert_called_once_with(datasheet, mock_graph, mock_config)
        mock_enqueue.assert_called_once_with(datasheet, mock_validate.return_value, mock_config)


class TestReportCoverage:
    """The final report must cover every input MPN with correct outcome counts."""

    @patch(f"{MODULE}.import_datasheet")
    @patch(f"{MODULE}.enqueue")
    @patch(f"{MODULE}.validate")
    @patch(f"{MODULE}.parse_datasheet")
    @patch(f"{MODULE}.download_pdf")
    @patch(f"{MODULE}.resolve_pdf_urls")
    @patch(f"{MODULE}.KnowledgeGraph")
    def test_report_has_one_entry_per_mpn_and_correct_counts(
        self, mock_kg_cls, mock_resolve, mock_download, mock_parse, mock_validate,
        mock_enqueue, mock_import, mock_graph, mock_config, fetch_result,
    ):
        mpns = ["CLEAN", "WARNED", "BLOCKED", "NO_PDF", "PARSE_FAIL"]

        mock_kg_cls.return_value = mock_graph
        mock_kg_cls.load.return_value = mock_graph
        mock_graph.stats.return_value = {"node_count": 0}

        mock_resolve.return_value = {
            "CLEAN": fetch_result,
            "WARNED": fetch_result,
            "BLOCKED": fetch_result,
            "NO_PDF": FetchResult(pdf_url=None, content_type=None, source="none", mpn="NO_PDF"),
            "PARSE_FAIL": fetch_result,
        }

        mock_download.return_value = (Path("/tmp/fake.pdf"), "hash1")

        clean_ds = make_datasheet(review_required=False)
        warned_ds = make_datasheet(review_required=True, review_flags=["Missing manufacturer"])
        blocked_ds = make_datasheet(review_required=True, review_flags=["Low extraction confidence: 0.1"])

        mock_parse.side_effect = [
            clean_ds,
            warned_ds,
            blocked_ds,
            DatasheetPipelineError("Phase 1", "PARSE_FAIL", RuntimeError("boom")),
        ]
        mock_validate.side_effect = [
            ValidationResult(verdict="PASS", severity="WARNING", confidence=0.97, flags=[]),
            ValidationResult(verdict="WARN", severity="WARNING", confidence=0.65, flags=["Missing manufacturer"]),
            ValidationResult(verdict="BLOCK", severity="CRITICAL", confidence=0.1, flags=["Low extraction confidence: 0.1"]),
        ]
        mock_import.return_value = ImportResult(
            component_id="x", nodes_created=1, edges_created=0, success=True
        )

        report = run_pilot(mpns, mock_config, mock_config.review_queue_path.parent / "report.json")

        assert report["mpn_count"] == 5
        assert {r["mpn"] for r in report["results"]} == set(mpns)
        assert report["outcome_counts"] == {
            "imported_clean": 1,
            "imported_with_warning": 1,
            "blocked_critical": 1,
        }
        # NO_PDF and PARSE_FAIL both fall outside the 3 canonical outcomes.
        assert report["other_failures"] == 2
