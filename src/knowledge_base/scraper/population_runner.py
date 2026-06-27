"""KB population pipeline orchestrator with checkpoint/resume."""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.knowledge_base.scraper.adapters.adi_adapter import ADIAdapter
from src.knowledge_base.scraper.adapters.digikey_adapter import DigiKeyAdapter
from src.knowledge_base.scraper.adapters.nexar_adapter import NexarAdapter, NEXAR_BATCH_SIZE
from src.knowledge_base.scraper.adapters.ti_adapter import TIAdapter
from src.knowledge_base.scraper.app_note_fetcher import fetch_all_app_notes
from src.knowledge_base.scraper.mpn_discovery import discover_mpns
from src.knowledge_base.scraper.pdf_downloader import (
    PDF_URLS_PATH,
    build_fallback_chain,
    download_pdf,
    resolve_pdf_urls,
    write_to_documents_table,
)
from src.knowledge_base.scraper.request_tracker import RequestTracker

logger = logging.getLogger(__name__)

CHECKPOINT_PATH = Path("data/population_run/checkpoint.json")
CHECKPOINT_BATCH = 100


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_checkpoint() -> dict[str, Any]:
    return {
        "phase1_complete": False,
        "phase2_complete": False,
        "phase2_mpn_index": 0,
        "phase3_complete": False,
        "phase3_url_index": 0,
        "phase4_complete": False,
        "digikey_requests_today": 0,
        "digikey_budget_date": date.today().isoformat(),
        "started_at": _utc_now(),
        "last_updated": _utc_now(),
    }


def _load_checkpoint() -> dict[str, Any]:
    if CHECKPOINT_PATH.exists():
        try:
            return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return _default_checkpoint()


def _save_checkpoint(checkpoint: dict[str, Any], tracker: RequestTracker) -> None:
    checkpoint["digikey_requests_today"] = tracker.count
    checkpoint["digikey_budget_date"] = date.today().isoformat()
    checkpoint["last_updated"] = _utc_now()
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_PATH.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")


def run_population(
    phases: list[int] | None = None,
    force_refresh: bool = False,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Run the KB population pipeline with checkpoint/resume."""
    if phases is None:
        phases = [1, 2, 3, 4]

    db_url = db_url or os.environ.get("OPENFORGE_DATABASE_URL")
    checkpoint = _load_checkpoint()
    tracker = RequestTracker()

    nexar = NexarAdapter()
    ti = TIAdapter()
    adi = ADIAdapter()
    digikey = DigiKeyAdapter(tracker=tracker)
    fallback_chain = build_fallback_chain(nexar, ti, adi, digikey)

    summary: dict[str, Any] = {
        "phases_run": [],
        "mpns_discovered": 0,
        "pdf_urls_resolved": 0,
        "pdfs_downloaded": 0,
        "pdfs_skipped_dedup": 0,
        "pdfs_failed": 0,
        "manual_queue_entries": 0,
        "app_notes_downloaded": 0,
        "digikey_requests_used": tracker.count,
    }

    mpns: list[str] = []
    url_results: dict = {}

    if 1 in phases and not checkpoint.get("phase1_complete", False):
        mpns = discover_mpns(digikey, force_refresh=force_refresh)
        summary["mpns_discovered"] = len(mpns)
        checkpoint["phase1_complete"] = True
        _save_checkpoint(checkpoint, tracker)
        summary["phases_run"].append(1)
    elif checkpoint.get("phase1_complete"):
        from src.knowledge_base.scraper.mpn_discovery import MPN_LIST_PATH
        if MPN_LIST_PATH.exists():
            mpns = json.loads(MPN_LIST_PATH.read_text(encoding="utf-8"))
            summary["mpns_discovered"] = len(mpns)

    if 2 in phases and mpns and not checkpoint.get("phase2_complete", False):
        start_idx = checkpoint.get("phase2_mpn_index", 0)
        resolved: dict = {}
        if PDF_URLS_PATH.exists() and not force_refresh and start_idx > 0:
            try:
                resolved = json.loads(PDF_URLS_PATH.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                resolved = {}

        for idx in range(start_idx, len(mpns), CHECKPOINT_BATCH):
            batch_mpns = mpns[idx : idx + CHECKPOINT_BATCH]
            batch_results = resolve_pdf_urls(
                batch_mpns,
                nexar,
                fallback_chain,
                force_refresh=True,
                db_url=db_url,
            )
            for mpn, result in batch_results.items():
                resolved[mpn] = {"pdf_url": result.pdf_url, "source": result.source}
                if not result.pdf_url and db_url:
                    summary["manual_queue_entries"] += 1
            checkpoint["phase2_mpn_index"] = min(idx + CHECKPOINT_BATCH, len(mpns))
            _save_checkpoint(checkpoint, tracker)

        url_results = resolved
        summary["pdf_urls_resolved"] = sum(
            1 for v in resolved.values() if v.get("pdf_url")
        )
        checkpoint["phase2_complete"] = True
        _save_checkpoint(checkpoint, tracker)
        summary["phases_run"].append(2)
    elif checkpoint.get("phase2_complete") and PDF_URLS_PATH.exists():
        url_results = json.loads(PDF_URLS_PATH.read_text(encoding="utf-8"))
        summary["pdf_urls_resolved"] = sum(
            1 for v in url_results.values() if v.get("pdf_url")
        )

    if 3 in phases and url_results and not checkpoint.get("phase3_complete", False):
        items = [(m, v) for m, v in url_results.items() if v.get("pdf_url")]
        start_idx = checkpoint.get("phase3_url_index", 0)

        for idx in range(start_idx, len(items), CHECKPOINT_BATCH):
            batch = items[idx : idx + CHECKPOINT_BATCH]
            for mpn, entry in batch:
                pdf_url = entry.get("pdf_url")
                if not pdf_url:
                    continue
                result = download_pdf(pdf_url)
                if result is None:
                    summary["pdfs_failed"] += 1
                    continue
                local_path, content_hash = result
                if local_path.exists() and local_path.stat().st_size > 0:
                    from src.knowledge_base.scraper.pdf_downloader import PDF_STORE_PATH
                    expected = PDF_STORE_PATH / f"{content_hash}.pdf"
                    if expected.exists() and local_path == expected:
                        summary["pdfs_skipped_dedup"] += 1
                    else:
                        summary["pdfs_downloaded"] += 1
                if db_url:
                    write_to_documents_table(
                        mpn=mpn,
                        pdf_url=pdf_url,
                        local_path=local_path,
                        content_hash=content_hash,
                        source_adapter=entry.get("source", "unknown"),
                        document_type="ic_datasheet",
                        db_url=db_url,
                    )
            checkpoint["phase3_url_index"] = min(idx + CHECKPOINT_BATCH, len(items))
            _save_checkpoint(checkpoint, tracker)

        checkpoint["phase3_complete"] = True
        _save_checkpoint(checkpoint, tracker)
        summary["phases_run"].append(3)
    elif checkpoint.get("phase3_complete"):
        summary["phases_run"].append(3)

    if 4 in phases and not checkpoint.get("phase4_complete", False):
        app_summary = fetch_all_app_notes(db_url=db_url)
        summary["app_notes_downloaded"] = app_summary.get("downloaded", 0)
        checkpoint["phase4_complete"] = True
        _save_checkpoint(checkpoint, tracker)
        summary["phases_run"].append(4)
    elif checkpoint.get("phase4_complete"):
        summary["phases_run"].append(4)

    summary["digikey_requests_used"] = tracker.count
    return summary
