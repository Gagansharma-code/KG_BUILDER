"""Command-line interface for the review queue.

Provides CLI commands for managing and interacting with the review queue:
- list: Show pending review items
- review: View full details of a specific item
- approve: Mark an item as approved
- correct: Mark an item as corrected (with notes)
- export: Export corrected items for fine-tuning

Usage:
    python -m src.review.cli list
    python -m src.review.cli review <item_id>
    python -m src.review.cli approve <item_id> --notes "optional notes"
    python -m src.review.cli correct <item_id> --notes "correction description"
    python -m src.review.cli export --output data/corrections_export.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, NoReturn, cast

from src.config import get_config
from src.review._schemas import GateStage
from src.review.queue import (
    enqueue,
    export_corrections,
    get_item,
    list_pending,
    update_status,
)


def _format_timestamp(iso_timestamp: str) -> str:
    """Format ISO timestamp for display."""
    if not iso_timestamp:
        return "N/A"
    # Simple formatting: take first 19 chars (YYYY-MM-DDTHH:MM:SS)
    return iso_timestamp[:19].replace("T", " ")


def cmd_list(args: argparse.Namespace) -> int:
    """List pending review items.

    Prints a table with:
    - item_id (first 8 chars)
    - component_id
    - severity
    - verdict
    - flags count
    - created_at
    """
    config = get_config()
    pending = list_pending(config)

    if not pending:
        print("No pending review items in queue.")
        return 0

    # Header
    print(f"{'Item ID':<10} {'Component':<20} {'Severity':<10} {'Verdict':<8} {'Flags':<6} {'Created'}")
    print("-" * 80)

    for item in pending:
        item_id_short = item.item_id[:8]
        component = item.component_id[:19]  # Truncate long component IDs
        severity = item.severity
        verdict = item.verdict
        flags_count = len(item.flags)
        created = _format_timestamp(item.created_at)

        print(
            f"{item_id_short:<10} {component:<20} {severity:<10} "
            f"{verdict:<8} {flags_count:<6} {created}"
        )

    print(f"\nTotal pending: {len(pending)}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    """Review full details of a specific item.

    Prints the ReviewQueueItem as formatted JSON with indentation.
    """
    config = get_config()
    item_id = args.item_id

    item = get_item(item_id, config)

    if item is None:
        print(f"Item {item_id} not found in queue", file=sys.stderr)
        return 1

    # Print as formatted JSON
    print(json.dumps(item.model_dump(), indent=2))
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    """Approve a review item.

    Updates status to 'approved' and records resolution notes.
    """
    config = get_config()
    item_id = args.item_id
    notes = args.notes or "Approved by reviewer"

    try:
        item = update_status(item_id, "approved", notes, config)
        print(f"Approved item {item.item_id[:8]}... ({item.component_id})")
        return 0
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_approve_design(args: argparse.Namespace) -> int:
    """Approve a queued design by design_id and review stage.

    After approval, continue the pipeline via
    src.orchestrator.resume_after_review(design_id, ..., stage=...).
    """
    from src.review.queue import set_design_review_status

    config = get_config()
    notes = args.notes or "Approved by reviewer"
    try:
        item = set_design_review_status(
            args.design_id, "approved", notes, config, stage=args.stage
        )
        print(
            f"Approved design {item.component_id} stage {item.stage} "
            f"(item {item.item_id[:8]}...)"
        )
        print(
            "Resume with: "
            "src.orchestrator.resume_after_review(design_id, ..., stage=...)"
        )
        return 0
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_reject_design(args: argparse.Namespace) -> int:
    """Reject a queued design by design_id and review stage."""
    from src.review.queue import set_design_review_status

    config = get_config()
    notes = args.notes or "Rejected by reviewer"
    try:
        item = set_design_review_status(
            args.design_id, "rejected", notes, config, stage=args.stage
        )
        print(
            f"Rejected design {item.component_id} stage {item.stage} "
            f"(item {item.item_id[:8]}...)"
        )
        return 0
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_correct(args: argparse.Namespace) -> int:
    """Mark an item as corrected.

    Updates status to 'corrected' and requires resolution notes describing
the correction. The corrected data can be used for fine-tuning.
    """
    config = get_config()
    item_id = args.item_id
    notes = args.notes or ""

    if not notes:
        print("Error: --notes is required for corrections", file=sys.stderr)
        return 1

    try:
        item = update_status(item_id, "corrected", notes, config)
        print(f"Marked item {item.item_id[:8]}... as corrected ({item.component_id})")
        return 0
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_export(args: argparse.Namespace) -> int:
    """Export corrected items to JSONL.

    Exports all items with status='corrected' to the specified output path
    in JSON Lines format for fine-tuning corpus generation.
    """
    config = get_config()
    output_path = Path(args.output)

    count = export_corrections(output_path, config)
    print(f"Exported {count} items to {output_path}")
    return 0


def main() -> int:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog="python -m src.review.cli",
        description="Review queue management CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # list command
    list_parser = subparsers.add_parser(
        "list",
        help="List pending review items",
    )
    list_parser.set_defaults(func=cmd_list)

    # review command
    review_parser = subparsers.add_parser(
        "review",
        help="View full details of a specific item",
    )
    review_parser.add_argument(
        "item_id",
        help="UUID of the item to review",
    )
    review_parser.set_defaults(func=cmd_review)

    # approve command
    approve_parser = subparsers.add_parser(
        "approve",
        help="Approve a review item",
    )
    approve_parser.add_argument(
        "item_id",
        help="UUID of the item to approve",
    )
    approve_parser.add_argument(
        "--notes",
        help="Optional approval notes",
        default="",
    )
    approve_parser.set_defaults(func=cmd_approve)

    stage_choices = [stage.value for stage in GateStage]

    # approve-design command (blocking review gate, by design_id + stage)
    approve_design_parser = subparsers.add_parser(
        "approve-design",
        help="Approve a queued design by design_id and stage",
    )
    approve_design_parser.add_argument(
        "design_id",
        help="ValidatedBOM.design_id of the queued design",
    )
    approve_design_parser.add_argument(
        "--notes",
        help="Optional approval notes",
        default="",
    )
    approve_design_parser.add_argument(
        "--stage",
        help="Review gate stage to approve",
        choices=stage_choices,
        default=GateStage.BOM.value,
    )
    approve_design_parser.set_defaults(func=cmd_approve_design)

    # reject-design command
    reject_design_parser = subparsers.add_parser(
        "reject-design",
        help="Reject a queued design by design_id and stage",
    )
    reject_design_parser.add_argument(
        "design_id",
        help="ValidatedBOM.design_id of the queued design",
    )
    reject_design_parser.add_argument(
        "--notes",
        help="Optional rejection notes",
        default="",
    )
    reject_design_parser.add_argument(
        "--stage",
        help="Review gate stage to reject",
        choices=stage_choices,
        default=GateStage.BOM.value,
    )
    reject_design_parser.set_defaults(func=cmd_reject_design)

    # correct command
    correct_parser = subparsers.add_parser(
        "correct",
        help="Mark an item as corrected (with notes)",
    )
    correct_parser.add_argument(
        "item_id",
        help="UUID of the item to mark as corrected",
    )
    correct_parser.add_argument(
        "--notes",
        help="Correction description (required)",
        required=True,
    )
    correct_parser.set_defaults(func=cmd_correct)

    # export command
    export_parser = subparsers.add_parser(
        "export",
        help="Export corrected items to JSONL",
    )
    export_parser.add_argument(
        "--output",
        help="Output path for JSONL file",
        required=True,
    )
    export_parser.set_defaults(func=cmd_export)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 1

    handler = cast(Callable[[argparse.Namespace], int], args.func)
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
