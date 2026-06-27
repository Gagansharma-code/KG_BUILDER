"""PDF URL resolution, download, and documents table persistence."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

import httpx

from src.knowledge_base.scraper.adapters.adi_adapter import ADIAdapter
from src.knowledge_base.scraper.adapters.base import FetchResult, SourceAdapter
from src.knowledge_base.scraper.adapters.digikey_adapter import DigiKeyAdapter
from src.knowledge_base.scraper.adapters.nexar_adapter import NexarAdapter, NEXAR_BATCH_SIZE
from src.knowledge_base.scraper.adapters.ti_adapter import TIAdapter

logger = logging.getLogger(__name__)

PDF_STORE_PATH = Path("data/datasheets")
PDF_URLS_PATH = Path("data/population_run/pdf_urls.json")
DOWNLOAD_TIMEOUT = 30
CHUNK_SIZE = 65_536


def build_fallback_chain(
    nexar: NexarAdapter,
    ti: TIAdapter,
    adi: ADIAdapter,
    digikey: DigiKeyAdapter,
) -> list[SourceAdapter]:
    """Return ordered adapter list: Nexar → TI → ADI → DigiKey."""
    return [nexar, ti, adi, digikey]


def _write_manual_queue(mpn: str, db_url: str) -> None:
    try:
        import psycopg2

        conn = psycopg2.connect(db_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO review_queue (stage, severity, flags, status, priority)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        "manual_queue",
                        "MEDIUM",
                        json.dumps({"reason": "datasheet_not_found", "mpn": mpn}),
                        "pending",
                        "MEDIUM",
                    ),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("manual_queue insert failed for %s: %s", mpn, exc)


def resolve_pdf_urls(
    mpns: list[str],
    nexar: NexarAdapter,
    fallback_chain: list[SourceAdapter],
    pdf_urls_path: Path = PDF_URLS_PATH,
    force_refresh: bool = False,
    db_url: Optional[str] = None,
) -> dict[str, FetchResult]:
    """Resolve PDF URLs for all MPNs using batch Nexar first, then fallbacks."""
    try:
        if pdf_urls_path.exists() and not force_refresh:
            cached = json.loads(pdf_urls_path.read_text(encoding="utf-8"))
            return {
                mpn: FetchResult(
                    pdf_url=entry.get("pdf_url"),
                    content_type="application/pdf" if entry.get("pdf_url") else None,
                    source=entry.get("source", "unknown"),
                    mpn=mpn,
                )
                for mpn, entry in cached.items()
            }

        results: dict[str, FetchResult] = {}
        manual_count = 0

        for i in range(0, len(mpns), NEXAR_BATCH_SIZE):
            batch = mpns[i : i + NEXAR_BATCH_SIZE]
            batch_results = nexar.fetch_batch(batch)
            results.update(batch_results)

        fallback_adapters = [a for a in fallback_chain if a.name != "nexar"]
        for mpn in mpns:
            if results.get(mpn) and results[mpn].pdf_url:
                continue
            for adapter in fallback_adapters:
                try:
                    result = adapter.fetch(mpn)
                    if result.pdf_url:
                        results[mpn] = result
                        break
                except Exception as exc:
                    logger.debug("Fallback %s failed for %s: %s", adapter.name, mpn, exc)
            if mpn not in results:
                results[mpn] = FetchResult(
                    pdf_url=None, content_type=None, source="none", mpn=mpn
                )
            if not results[mpn].pdf_url:
                if db_url:
                    _write_manual_queue(mpn, db_url)
                    manual_count += 1

        pdf_urls_path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {
            mpn: {"pdf_url": r.pdf_url, "source": r.source}
            for mpn, r in results.items()
        }
        pdf_urls_path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")
        return results
    except Exception as exc:
        logger.debug("resolve_pdf_urls failed: %s", exc)
        return {}


def download_pdf(
    url: str,
    store_path: Path = PDF_STORE_PATH,
    timeout: int = DOWNLOAD_TIMEOUT,
) -> tuple[Path, str] | None:
    """Download one PDF from url, store at store_path/{sha256}.pdf."""
    try:
        store_path.mkdir(parents=True, exist_ok=True)
        hasher = hashlib.sha256()
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as response:
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            if "pdf" not in content_type.lower():
                return None
            with tempfile.NamedTemporaryFile(
                delete=False, dir=store_path, suffix=".tmp"
            ) as tmp:
                tmp_path = Path(tmp.name)
                for chunk in response.iter_bytes(CHUNK_SIZE):
                    hasher.update(chunk)
                    tmp.write(chunk)
        content_hash = hasher.hexdigest()
        final_path = store_path / f"{content_hash}.pdf"
        if final_path.exists():
            tmp_path.unlink(missing_ok=True)
            return final_path, content_hash
        tmp_path.rename(final_path)
        return final_path, content_hash
    except Exception as exc:
        logger.debug("download_pdf failed for %s: %s", url, exc)
        return None


def write_to_documents_table(
    mpn: str,
    pdf_url: str,
    local_path: Path,
    content_hash: str,
    source_adapter: str,
    document_type: str,
    db_url: str,
) -> None:
    """Insert a row into the documents table."""
    try:
        import psycopg2

        byte_size = local_path.stat().st_size
        conn = psycopg2.connect(db_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM document_files WHERE file_hash = %s
                    """,
                    (content_hash,),
                )
                if cur.fetchone():
                    return
                cur.execute(
                    """
                    INSERT INTO document_files (file_hash, storage_path, byte_size)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (file_hash) DO NOTHING
                    """,
                    (content_hash, str(local_path), byte_size),
                )
                cur.execute(
                    """
                    INSERT INTO documents (
                        title, doc_type, url, local_path, file_hash,
                        ingestion_status, file_size_bytes
                    )
                    VALUES (%s, %s, %s, %s, %s, 'pending', %s)
                    """,
                    (
                        mpn,
                        document_type,
                        pdf_url,
                        str(local_path),
                        content_hash,
                        byte_size,
                    ),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("write_to_documents_table failed for %s: %s", mpn, exc)
