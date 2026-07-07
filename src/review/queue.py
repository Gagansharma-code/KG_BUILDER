"""SQLite-backed review queue implementation.

Provides persistent storage for review queue items using SQLite.
All functions open and close their own connections — no connection pooling.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional, cast

from pydantic import BaseModel
from src.datasheet.phase4_validate import ValidationResult
from src.review._schemas import GateStage, ReviewQueueItem
from src.config import Config
from src.schemas.datasheet import ComponentDatasheet
from src.schemas.intent import ValidatedBOM
from src.schemas.nir import NIR

logger = logging.getLogger(__name__)

# SQL schema for review queue table
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS review_queue (
    item_id TEXT PRIMARY KEY,
    stage TEXT NOT NULL,
    component_id TEXT NOT NULL,
    pdf_path TEXT NOT NULL,
    severity TEXT NOT NULL,
    verdict TEXT NOT NULL,
    flags TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    resolved_at TEXT,
    resolution_notes TEXT,
    bom_json TEXT,
    artifact_json TEXT,
    artifact_type TEXT
)
"""


def _get_db_path(config: Config) -> Path:
    """Get the SQLite database path from config.

    Args:
        config: Application configuration

    Returns:
        Path to the SQLite database file
    """
    # Use review_queue_path from config, or default to output_dir
    if hasattr(config, "review_queue_path") and config.review_queue_path:
        return config.review_queue_path

    # Default to output_dir/review_queue.db
    if hasattr(config, "output_dir") and config.output_dir:
        return Path(config.output_dir) / "review_queue.db"

    # Fallback to current directory
    return Path("review_queue.db")


def _init_db(db_path: Path) -> None:
    """Initialize the SQLite database with review queue table.

    Args:
        db_path: Path to the SQLite database file
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute(CREATE_TABLE_SQL)
        # Migrations: queues created before blocking gates lack snapshot
        # columns — add them in place (single source of truth, no file store).
        cursor.execute("PRAGMA table_info(review_queue)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        if "bom_json" not in existing_columns:
            cursor.execute("ALTER TABLE review_queue ADD COLUMN bom_json TEXT")
        if "artifact_json" not in existing_columns:
            cursor.execute("ALTER TABLE review_queue ADD COLUMN artifact_json TEXT")
        if "artifact_type" not in existing_columns:
            cursor.execute("ALTER TABLE review_queue ADD COLUMN artifact_type TEXT")
        conn.commit()
    finally:
        conn.close()


def _row_to_item(row: tuple) -> ReviewQueueItem:
    """Convert a database row to a ReviewQueueItem.

    Args:
        row: Database row tuple (11 columns pre-migration, then snapshot columns)

    Returns:
        ReviewQueueItem from the row data
    """
    return ReviewQueueItem(
        item_id=row[0],
        stage=row[1],
        component_id=row[2],
        pdf_path=row[3],
        severity=cast(Literal["CRITICAL", "WARNING"], row[4]),
        verdict=row[5],
        flags=json.loads(row[6]),
        created_at=row[7],
        status=cast(Literal["pending", "approved", "corrected", "rejected"], row[8]),
        resolved_at=row[9],
        resolution_notes=row[10],
        bom_json=row[11] if len(row) > 11 else None,
        # Deliberate compatibility duplication: old BOM review rows only had
        # bom_json, while multi-stage gates use artifact_json. artifact_json is
        # authoritative when both fields exist and differ; bom_json is a
        # backward-compatible BOM-only mirror tracked as minor tech debt in
        # WHATS_LEFT.md.
        artifact_json=(
            row[12] if len(row) > 12 and row[12] is not None
            else row[11] if len(row) > 11 else None
        ),
        artifact_type=row[13] if len(row) > 13 else None,
    )


def enqueue(
    datasheet: ComponentDatasheet,
    validation_result: ValidationResult,
    config: Config,
) -> ReviewQueueItem:
    """Write a pending review item to the SQLite queue.

    Creates a new ReviewQueueItem from the datasheet and validation result,
    persists it to the SQLite queue, and returns the created item.

    Args:
        datasheet: ComponentDatasheet with review flags
        validation_result: ValidationResult with verdict and severity
        config: Application configuration with queue database path

    Returns:
        The created ReviewQueueItem with generated item_id

    Example:
        >>> item = enqueue(datasheet, validation_result, config)
        >>> item.component_id
        'TPS62933DRLR'
        >>> item.status
        'pending'
    """
    db_path = _get_db_path(config)
    _init_db(db_path)

    # Create the queue item
    item = ReviewQueueItem(
        stage="phase4_validation",
        component_id=datasheet.component_id or "unknown",
        pdf_path=str(datasheet.source_pdf_hash),  # Using hash as identifier
        severity=cast(Literal["CRITICAL", "WARNING"], validation_result.severity),
        verdict=validation_result.verdict,
        flags=datasheet.review_flags,
    )

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO review_queue
            (item_id, stage, component_id, pdf_path, severity, verdict, flags, created_at, status, resolved_at, resolution_notes, bom_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.item_id,
                item.stage,
                item.component_id,
                item.pdf_path,
                item.severity,
                item.verdict,
                json.dumps(item.flags),
                item.created_at,
                item.status,
                item.resolved_at,
                item.resolution_notes,
                item.bom_json,
            ),
        )
        conn.commit()
        logger.info(f"Enqueued review item {item.item_id[:8]}... for {item.component_id}")
    finally:
        conn.close()

    return item


def _write_item(
    stage: str,
    component_id: str,
    pdf_path: str,
    severity: Literal["CRITICAL", "WARNING"],
    verdict: str,
    flags: list[str],
    config: Config,
    bom_json: Optional[str] = None,
    artifact_json: Optional[str] = None,
    artifact_type: Optional[str] = None,
) -> ReviewQueueItem:
    """Write a review queue item to SQLite."""
    db_path = _get_db_path(config)
    _init_db(db_path)

    item = ReviewQueueItem(
        stage=stage,
        component_id=component_id,
        pdf_path=pdf_path,
        severity=severity,
        verdict=verdict,
        flags=flags,
        bom_json=bom_json,
        artifact_json=artifact_json if artifact_json is not None else bom_json,
        artifact_type=artifact_type,
    )

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO review_queue
            (item_id, stage, component_id, pdf_path, severity, verdict, flags, created_at, status, resolved_at, resolution_notes, bom_json, artifact_json, artifact_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.item_id,
                item.stage,
                item.component_id,
                item.pdf_path,
                item.severity,
                item.verdict,
                json.dumps(item.flags),
                item.created_at,
                item.status,
                item.resolved_at,
                item.resolution_notes,
                item.bom_json,
                item.artifact_json,
                item.artifact_type,
            ),
        )
        conn.commit()
        logger.info(f"Enqueued review item {item.item_id[:8]}... for {item.component_id}")
    finally:
        conn.close()

    return item


def _stage_value(stage: GateStage | str) -> str:
    return stage.value if isinstance(stage, GateStage) else str(stage)


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_jsonable(val) for key, val in value.items()}
    return value


def _snapshot_json(
    artifact: BaseModel,
    stage: GateStage | str,
    resume_context: Optional[dict[str, Any]] = None,
) -> str:
    payload = {
        "stage": _stage_value(stage),
        "artifact_type": type(artifact).__name__,
        "artifact": artifact.model_dump(mode="json"),
        "resume_context": _to_jsonable(resume_context or {}),
    }
    return json.dumps(payload)


def enqueue_for_review(
    artifact: BaseModel,
    stage: GateStage | str,
    design_id: str,
    config: Config,
    *,
    flags: Optional[list[str]] = None,
    severity: Optional[Literal["CRITICAL", "WARNING"]] = None,
    verdict: str = "REVIEW_REQUIRED",
    resume_context: Optional[dict[str, Any]] = None,
) -> ReviewQueueItem:
    """Write any review-gated stage artifact to the queue.

    artifact_json stores an envelope with the reviewed artifact and the
    already-computed upstream context needed to resume without regeneration.
    """
    stage_value = _stage_value(stage)
    artifact_flags = flags or []
    resolved_severity: Literal["CRITICAL", "WARNING"] = severity or (
        "CRITICAL"
        if any("CRITICAL" in flag or flag.startswith("critical:") for flag in artifact_flags)
        else "WARNING"
    )
    artifact_json = _snapshot_json(artifact, stage, resume_context)
    # BOM keeps a redundant bom_json mirror for pre-artifact_json consumers.
    # artifact_json is the generic resume snapshot and remains authoritative.
    bom_json = artifact.model_dump_json() if stage_value == GateStage.BOM.value else None

    return _write_item(
        stage=stage_value,
        component_id=design_id,
        pdf_path="N/A",
        severity=resolved_severity,
        verdict=verdict,
        flags=artifact_flags,
        config=config,
        bom_json=bom_json,
        artifact_json=artifact_json,
        artifact_type=type(artifact).__name__,
    )


def enqueue_unresolved_protection(
    intent: BaseModel,
    design_id: str,
    unresolved: list[Any],
    config: Config,
) -> ReviewQueueItem:
    """Enqueue review when protection requirements lack topology-library blocks."""
    flags = [
        f"protection_unresolved:{req.kind}:{getattr(req, 'raw_text', '')[:80]}"
        for req in unresolved
    ]
    return enqueue_for_review(
        intent,
        GateStage.BOM,
        design_id,
        config,
        flags=flags,
        severity="WARNING",
        verdict="PROTECTION_UNRESOLVED",
    )


def enqueue_bom(bom: ValidatedBOM, config: Config) -> ReviewQueueItem:
    """Write BOM review item to queue with stage='bom_generation'.

    Stores the full serialized ValidatedBOM on the same record (bom_json
    column) so an approved design can later be resumed from the exact
    snapshot that was reviewed — never a regenerated one.
    """
    severity: Literal["CRITICAL", "WARNING"] = (
        "CRITICAL" if any("CRITICAL" in f for f in bom.review_flags) else "WARNING"
    )
    return enqueue_for_review(
        bom,
        GateStage.BOM,
        bom.design_id,
        config,
        severity=severity,
        flags=bom.review_flags,
    )


def get_review_item(
    design_id: str,
    stage: GateStage | str,
    config: Config,
) -> Optional[ReviewQueueItem]:
    """Fetch the newest review queue item for a design_id and gate stage.

    Args:
        design_id: Design id used as component_id at enqueue.
        stage: Review-gated stage.
        config: Application configuration with queue database path.

    Returns:
        Newest matching ReviewQueueItem, or None if the design was never queued.
    """
    db_path = _get_db_path(config)
    if not db_path.exists():
        return None

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM review_queue
            WHERE component_id = ? AND stage = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (design_id, _stage_value(stage)),
        )
        row = cursor.fetchone()
        return _row_to_item(row) if row is not None else None
    finally:
        conn.close()


def get_bom_review_item(design_id: str, config: Config) -> Optional[ReviewQueueItem]:
    """Fetch the newest bom_generation queue item for a design_id."""
    return get_review_item(design_id, GateStage.BOM, config)


def set_design_review_status(
    design_id: str,
    status: Literal["approved", "rejected"],
    resolution_notes: str,
    config: Config,
    stage: GateStage | str = GateStage.BOM,
) -> ReviewQueueItem:
    """Mark a queued design APPROVED or REJECTED by design_id and stage.

    Thin wrapper over update_status() (the existing item_id-level mechanism),
    resolving the newest stage-specific item for the design first.

    Raises:
        ValueError: If no matching queue item exists for design_id and stage.
    """
    stage_value = _stage_value(stage)
    item = get_review_item(design_id, stage_value, config)
    if item is None:
        raise ValueError(f"No {stage_value} review item found for design {design_id}")
    return update_status(item.item_id, status, resolution_notes, config)


def enqueue_nir(nir: NIR, config: Config) -> ReviewQueueItem:
    """Write NIR review item to queue with stage='nir_validation'."""
    severity: Literal["CRITICAL", "WARNING"] = (
        "CRITICAL" if nir.is_review_required() else "WARNING"
    )
    flags = [f"{flag.severity}: {flag.reason}" for flag in nir.review_flags]
    return enqueue_for_review(
        nir,
        GateStage.NIR,
        nir.design_id,
        config,
        severity=severity,
        flags=flags,
    )


def list_pending(config: Config) -> list[ReviewQueueItem]:
    """Return all items with status == 'pending', ordered by created_at desc.

    Args:
        config: Application configuration with queue database path

    Returns:
        List of pending ReviewQueueItem objects, newest first

    Example:
        >>> pending = list_pending(config)
        >>> len(pending)
        5
        >>> pending[0].status
        'pending'
    """
    db_path = _get_db_path(config)

    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM review_queue
            WHERE status = 'pending'
            ORDER BY created_at DESC
            """
        )
        rows = cursor.fetchall()
        return [_row_to_item(row) for row in rows]
    finally:
        conn.close()


def get_item(item_id: str, config: Config) -> Optional[ReviewQueueItem]:
    """Fetch a single item by item_id.

    Args:
        item_id: Unique UUID of the item to fetch
        config: Application configuration with queue database path

    Returns:
        ReviewQueueItem if found, None otherwise

    Example:
        >>> item = get_item("550e8400-e29b-41d4-a716-446655440000", config)
        >>> item.component_id if item else "not found"
        'TPS62933DRLR'
    """
    db_path = _get_db_path(config)

    if not db_path.exists():
        return None

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM review_queue WHERE item_id = ?", (item_id,))
        row = cursor.fetchone()

        if row is None:
            return None

        return _row_to_item(row)
    finally:
        conn.close()


def update_status(
    item_id: str,
    status: str,
    resolution_notes: str,
    config: Config,
) -> ReviewQueueItem:
    """Update item status and set resolved_at = now().

    Args:
        item_id: Unique UUID of the item to update
        status: New status (approved, corrected, rejected)
        resolution_notes: Human-entered notes about the resolution
        config: Application configuration with queue database path

    Returns:
        Updated ReviewQueueItem

    Raises:
        ValueError: If item_id not found in queue

    Example:
        >>> item = update_status(item_id, "approved", "Looks good", config)
        >>> item.status
        'approved'
        >>> item.resolved_at is not None
        True
    """
    db_path = _get_db_path(config)

    if not db_path.exists():
        raise ValueError(f"Item {item_id} not found in queue")

    resolved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()

        # First check if item exists
        cursor.execute("SELECT 1 FROM review_queue WHERE item_id = ?", (item_id,))
        if cursor.fetchone() is None:
            raise ValueError(f"Item {item_id} not found in queue")

        cursor.execute(
            """
            UPDATE review_queue
            SET status = ?, resolved_at = ?, resolution_notes = ?
            WHERE item_id = ?
            """,
            (status, resolved_at, resolution_notes, item_id),
        )
        conn.commit()

        # Fetch and return the updated item
        cursor.execute("SELECT * FROM review_queue WHERE item_id = ?", (item_id,))
        row = cursor.fetchone()
        item = _row_to_item(row)

        logger.info(f"Updated review item {item_id[:8]}... status to {status}")
        return item
    finally:
        conn.close()


def export_corrections(output_path: Path, config: Config) -> int:
    """Export all items with status='corrected' to JSONL at output_path.

    Used for fine-tuning corpus generation. Each line is a JSON object
    with the correction data.

    Args:
        output_path: Path to write the JSONL file
        config: Application configuration with queue database path

    Returns:
        Count of exported items

    Example:
        >>> count = export_corrections(Path("corrections.jsonl"), config)
        >>> print(f"Exported {count} corrections")
        Exported 42 items to data/corrections_export.jsonl
    """
    db_path = _get_db_path(config)

    if not db_path.exists():
        return 0

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM review_queue
            WHERE status = 'corrected'
            ORDER BY created_at DESC
            """
        )
        rows = cursor.fetchall()

        items = [_row_to_item(row) for row in rows]
    finally:
        conn.close()

    # Write to JSONL
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        for item in items:
            # Write as JSON lines format
            f.write(item.model_dump_json() + "\n")

    logger.info(f"Exported {len(items)} corrected items to {output_path}")
    return len(items)
