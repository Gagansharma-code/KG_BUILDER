"""Local pilot batch ingestion: scrape -> parse -> severity gate -> KG import.

Wires together already-built pipeline pieces for a small (10-20 MPN) local
end-to-end pilot run, to prove the full path works before a larger
GPU-accelerated run. Builds no new parsing, scraping, or KG logic itself:

- src.knowledge_base.scraper.pdf_downloader.resolve_pdf_urls / download_pdf
- src.datasheet.pipeline.parse_datasheet
- src.datasheet.phase4_validate.validate
- src.review.queue.enqueue
- src.knowledge_graph.importers.p1_importer.import_datasheet

Every per-MPN step is wrapped so one failing or blocked MPN never stops the
rest of the batch.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Optional

from src.config import Config, get_config
from src.datasheet.phase4_validate import ValidationResult, validate
from src.datasheet.pipeline import DatasheetPipelineError, parse_datasheet
from src.knowledge_base.scraper.adapters.adi_adapter import ADIAdapter
from src.knowledge_base.scraper.adapters.base import FetchResult
from src.knowledge_base.scraper.adapters.digikey_adapter import DigiKeyAdapter
from src.knowledge_base.scraper.adapters.nexar_adapter import NexarAdapter
from src.knowledge_base.scraper.adapters.ti_adapter import TIAdapter
from src.knowledge_base.scraper.pdf_downloader import (
    build_fallback_chain,
    download_pdf,
    resolve_pdf_urls,
)
from src.knowledge_graph import KnowledgeGraph
from src.knowledge_graph.importers.p1_importer import import_datasheet
from src.review.queue import enqueue
from src.schemas.datasheet import ComponentDatasheet

logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent
DEFAULT_MPN_LIST = SCRIPT_DIR / "pilot_mpns.txt"
DEFAULT_REPORT_PATH = SCRIPT_DIR / "pilot_ingest_report.json"


def load_mpns(path: Path) -> list[str]:
    """Read one MPN per line from path, skipping blanks and '#' comments."""
    mpns = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            mpns.append(line)
    return mpns


def _severity_outcome(
    datasheet: ComponentDatasheet, config: Config
) -> tuple[str, ValidationResult]:
    """Classify a parsed datasheet as blocked/warning/clean.

    ComponentDatasheet only carries review_required (bool, conflates the
    BLOCK and WARN verdicts) and review_flags (plain description strings,
    not prefixed with severity in the current phase4_validate
    implementation) -- neither field alone distinguishes CRITICAL from
    WARNING severity. Re-derive the ValidationResult the same way
    src/datasheet/pipeline.py itself does when it queues a datasheet for
    review after Phase 4 ("Reconstruct validation_result for queue").
    """
    validation_result = validate(datasheet, config)
    if validation_result.severity == "CRITICAL":
        return "blocked_critical", validation_result
    if datasheet.review_required:
        return "imported_with_warning", validation_result
    return "imported_clean", validation_result


def ingest_one(
    mpn: str,
    fetch_result: Optional[FetchResult],
    graph: KnowledgeGraph,
    config: Config,
) -> dict:
    """Run download -> parse -> severity gate -> import for a single MPN.

    Every step below is wrapped so a failure or block on this MPN can never
    propagate out and stop the rest of the batch.
    """
    record: dict = {
        "mpn": mpn,
        "download_success": False,
        "parse_success": False,
        "failed_phase": None,
        "error": None,
        "outcome": "failed",
    }

    pdf_url = fetch_result.pdf_url if fetch_result else None
    if not pdf_url:
        record["error"] = "No PDF URL resolved for this MPN (all adapters missed)"
        return record

    try:
        downloaded = download_pdf(pdf_url)
    except Exception as exc:
        record["error"] = f"download_pdf raised: {exc}"
        return record

    if downloaded is None:
        record["error"] = "download_pdf failed (network error or non-PDF response)"
        return record

    pdf_path, content_hash = downloaded
    record["download_success"] = True
    record["pdf_path"] = str(pdf_path)
    record["content_hash"] = content_hash

    try:
        datasheet = parse_datasheet(mpn, pdf_path, config)
    except DatasheetPipelineError as exc:
        record["error"] = str(exc)
        record["failed_phase"] = exc.phase
        return record
    except Exception as exc:
        record["error"] = f"parse_datasheet raised unexpectedly: {exc}"
        return record

    record["parse_success"] = True
    record["review_flags"] = list(datasheet.review_flags)

    try:
        outcome, validation_result = _severity_outcome(datasheet, config)
    except Exception as exc:
        record["error"] = f"severity gate raised: {exc}"
        return record

    record["severity"] = validation_result.severity
    record["verdict"] = validation_result.verdict

    if outcome == "blocked_critical":
        try:
            enqueue(datasheet, validation_result, config)
        except Exception as exc:
            logger.warning(f"Failed to enqueue blocked datasheet {mpn}: {exc}")
        record["outcome"] = "blocked_critical"
        return record

    try:
        import_result = import_datasheet(datasheet, graph, config)
    except Exception as exc:
        record["error"] = f"import_datasheet raised: {exc}"
        return record

    record["import_success"] = import_result.success
    record["nodes_created"] = import_result.nodes_created
    record["edges_created"] = import_result.edges_created

    if outcome == "imported_with_warning":
        try:
            enqueue(datasheet, validation_result, config)
        except Exception as exc:
            logger.warning(f"Failed to enqueue warned datasheet {mpn} for review: {exc}")

    record["outcome"] = outcome
    return record


def run_pilot(mpns: list[str], config: Config, report_path: Path) -> dict:
    """Run the pilot batch over mpns and write/return the summary report."""
    logger.info(f"Starting pilot ingestion for {len(mpns)} MPNs")

    if config.graph_path.exists():
        graph = KnowledgeGraph.load(config.graph_path)
    else:
        graph = KnowledgeGraph()
    stats_before = graph.stats()

    nexar = NexarAdapter()
    fallback_chain = build_fallback_chain(nexar, TIAdapter(), ADIAdapter(), DigiKeyAdapter())

    # Batch the Nexar lookups for the whole list at once (resolve_pdf_urls
    # already chunks internally at NEXAR_BATCH_SIZE) instead of one MPN at a time.
    url_results = resolve_pdf_urls(mpns, nexar, fallback_chain)

    records: list[dict] = []
    for mpn in mpns:
        try:
            record = ingest_one(mpn, url_results.get(mpn), graph, config)
        except Exception as exc:
            # Backstop: ingest_one already catches everything it calls, but a
            # bug in ingest_one itself must still not kill the batch.
            logger.error(f"Unexpected error processing {mpn}: {exc}")
            record = {
                "mpn": mpn,
                "download_success": False,
                "parse_success": False,
                "failed_phase": None,
                "error": f"unexpected error: {exc}",
                "outcome": "failed",
            }
        records.append(record)

    graph.save(config.graph_path)
    stats_after = graph.stats()

    outcome_counts = {
        "imported_clean": sum(1 for r in records if r["outcome"] == "imported_clean"),
        "imported_with_warning": sum(
            1 for r in records if r["outcome"] == "imported_with_warning"
        ),
        "blocked_critical": sum(1 for r in records if r["outcome"] == "blocked_critical"),
    }
    other_failures = len(records) - sum(outcome_counts.values())

    report = {
        "mpn_count": len(mpns),
        "stats_before": stats_before,
        "stats_after": stats_after,
        "results": records,
        "outcome_counts": outcome_counts,
        "other_failures": other_failures,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    arg_parser = argparse.ArgumentParser(
        description="Local pilot batch ingestion (scrape -> parse -> KG import)"
    )
    arg_parser.add_argument("--mpn-list", type=Path, default=DEFAULT_MPN_LIST)
    arg_parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    args = arg_parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    config = get_config()

    mpns = load_mpns(args.mpn_list)
    print(f"Loaded {len(mpns)} MPNs from {args.mpn_list}")

    report = run_pilot(mpns, config, args.report)

    print(f"Graph stats before: {report['stats_before']}")
    print(f"Graph stats after:  {report['stats_after']}")
    counts = report["outcome_counts"]
    summary_line = (
        f"Outcomes: {counts['imported_clean']} clean, "
        f"{counts['imported_with_warning']} warning, "
        f"{counts['blocked_critical']} blocked"
    )
    if report["other_failures"]:
        summary_line += f", {report['other_failures']} failed (download/parse)"
    print(summary_line)
    print(f"Report written to {args.report}")


if __name__ == "__main__":
    main()
