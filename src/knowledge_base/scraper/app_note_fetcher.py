"""App note downloader from static guided_app_notes manifest."""

from __future__ import annotations

import hashlib
import logging
import tempfile
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml

from src.knowledge_base.scraper.pdf_downloader import (
    CHUNK_SIZE,
    DOWNLOAD_TIMEOUT,
    write_to_documents_table,
)

logger = logging.getLogger(__name__)

APP_NOTES_STORE = Path("data/app_notes")
SOURCES_YAML = Path("configs/sources.yaml")
MANIFEST_KEY = "guided_app_notes"


def load_app_note_manifest(sources_path: Path = SOURCES_YAML) -> list[dict]:
    """Load guided_app_notes list from sources.yaml."""
    try:
        if not sources_path.exists():
            return []
        with open(sources_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            return []
        notes = data.get(MANIFEST_KEY) or []
        if not isinstance(notes, list):
            return []
        return [n for n in notes if isinstance(n, dict)]
    except Exception as exc:
        logger.debug("load_app_note_manifest failed: %s", exc)
        return []


def _download_app_note_pdf(
    url: str,
    dest_path: Path,
    timeout: int = DOWNLOAD_TIMEOUT,
) -> Optional[str]:
    """Stream download to dest_path; return SHA-256 hex or None."""
    try:
        hasher = hashlib.sha256()
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as response:
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            if "pdf" not in content_type.lower():
                return None
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                delete=False, dir=dest_path.parent, suffix=".tmp"
            ) as tmp:
                tmp_path = Path(tmp.name)
                for chunk in response.iter_bytes(CHUNK_SIZE):
                    hasher.update(chunk)
                    tmp.write(chunk)
        content_hash = hasher.hexdigest()
        tmp_path.rename(dest_path)
        return content_hash
    except Exception as exc:
        logger.debug("app note download failed %s: %s", url, exc)
        return None


def fetch_all_app_notes(
    store_path: Path = APP_NOTES_STORE,
    db_url: str | None = None,
) -> dict[str, int]:
    """Download all app notes from sources.yaml manifest."""
    manifest = load_app_note_manifest()
    summary = {"total": len(manifest), "downloaded": 0, "skipped_dedup": 0, "failed": 0}
    store_path.mkdir(parents=True, exist_ok=True)

    for entry in manifest:
        doc_number = entry.get("document_number", "unknown")
        url = entry.get("url")
        if not url:
            summary["failed"] += 1
            continue
        dest = store_path / f"{doc_number}.pdf"
        if dest.exists():
            summary["skipped_dedup"] += 1
            continue
        try:
            with httpx.Client(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
                head = client.head(url)
                if head.status_code >= 400:
                    summary["failed"] += 1
                    continue
        except Exception as exc:
            logger.debug("HEAD failed for %s: %s", url, exc)
            summary["failed"] += 1
            continue

        content_hash = _download_app_note_pdf(url, dest)
        if not content_hash:
            summary["failed"] += 1
            continue
        summary["downloaded"] += 1
        if db_url:
            write_to_documents_table(
                mpn=str(doc_number),
                pdf_url=str(url),
                local_path=dest,
                content_hash=content_hash,
                source_adapter="manifest",
                document_type="app_note",
                db_url=db_url,
            )

    return summary
