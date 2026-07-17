#!/usr/bin/env python3
"""Validate all golden ground-truth JSON files against ComponentDatasheet schema.

Golden files use a nested annotation layout (``sections``, ``pin_name``, …).
This script maps that layout onto ``PinDefinition`` / ``AlternateFunction`` and
instantiates a ``ComponentDatasheet`` so AF shape and pin contracts are checked
against ``src/schemas/datasheet.py``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.schemas.datasheet import (  # noqa: E402
    ComponentDatasheet,
    ExtractionMethod,
    PinDefinition,
)

EXPECTED_GOLDEN_COUNT: int = 10

# Known corpus entries; missing files are reported but do not fail validation.
EXPECTED_GOLDEN_FILES: tuple[str, ...] = (
    "TI_SN74LVC1G04_v1_ground_truth.json",
    "TI_TLV7021_v1_ground_truth.json",
    "TI_INA219_v1_ground_truth.json",
    "TI_LM5176_v1_ground_truth.json",
    "TI_TPS62933_v1_ground_truth.json",
    "ST_STM32F030C8_v1_ground_truth.json",
    "RPI_RP2040_v1_ground_truth.json",
    "TI_CC1101_v1_ground_truth.json",
    "IR_IRLZ44N_v1_ground_truth.json",
    "TI_TLV755P_v1_ground_truth.json",
)


def discover_ground_truth_files(golden_dir: Path) -> list[Path]:
    """Return sorted paths matching the golden ground-truth glob pattern."""
    return sorted(golden_dir.glob("*_ground_truth.json"))


def load_json(path: Path) -> dict[str, Any]:
    """Load and parse a JSON file from disk."""
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_pin_dicts(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect pin objects from nested sections and optional top-level ``pins``."""
    pins: list[dict[str, Any]] = []
    for section in data.get("sections") or []:
        if isinstance(section, dict):
            for pin in section.get("pins") or []:
                if isinstance(pin, dict):
                    pins.append(pin)
    for pin in data.get("pins") or []:
        if isinstance(pin, dict):
            pins.append(pin)
    return pins


def _pin_dict_to_definition(pin: dict[str, Any], index: int) -> PinDefinition:
    """Map a golden pin record onto ``PinDefinition`` (validates AF schema)."""
    raw_name = pin.get("raw_name") or pin.get("pin_name")
    if not raw_name:
        raise ValueError(f"pin[{index}] missing raw_name/pin_name")
    if "pin_number" not in pin:
        raise ValueError(f"pin[{index}] missing pin_number")

    return PinDefinition(
        pin_number=str(pin["pin_number"]),
        raw_name=str(raw_name),
        pin_type=pin.get("pin_type"),
        description=pin.get("description"),
        default_function=pin.get("default_function"),
        alternate_functions=pin.get("alternate_functions") or [],
    )


def golden_to_datasheet(data: dict[str, Any]) -> ComponentDatasheet:
    """Build a ComponentDatasheet from nested golden annotation JSON."""
    for key in ("component_id", "manufacturer", "package"):
        if key not in data:
            raise ValueError(f"missing required field: {key}")

    pin_defs = [
        _pin_dict_to_definition(pin, i)
        for i, pin in enumerate(_iter_pin_dicts(data))
    ]

    created_at = (
        data.get("created_at")
        or data.get("extraction_timestamp")
        or "1970-01-01T00:00:00Z"
    )

    return ComponentDatasheet(
        component_id=str(data["component_id"]),
        manufacturer=str(data["manufacturer"]),
        description=str(data.get("description") or data["component_id"]),
        package=str(data["package"]),
        source_pdf_hash=str(data.get("source_pdf_hash") or "golden_corpus"),
        extraction_method=ExtractionMethod.MANUAL,
        extraction_confidence=float(data.get("extraction_confidence") or 1.0),
        pins=pin_defs,
        created_at=str(created_at),
        pipeline_version=str(data.get("pipeline_version") or "2.0"),
    )


def validate_ground_truth_file(path: Path) -> tuple[bool, str | None]:
    """
    Parse a ground-truth JSON file and validate pin/AF schema via ComponentDatasheet.

    Returns:
        A tuple of (success, error_detail). error_detail is None on success.
    """
    try:
        data = load_json(path)
    except json.JSONDecodeError as exc:
        return False, f"invalid JSON: {exc}"
    except OSError as exc:
        return False, f"could not read file: {exc}"

    try:
        golden_to_datasheet(data)
    except Exception as exc:
        return False, str(exc)

    return True, None


def print_missing_file_notice(filename: str) -> None:
    """Print a non-fatal notice for an expected but absent golden file."""
    print(f"[pending] {filename} not found (pending annotation)")


def main() -> int:
    """Validate golden corpus JSON files and print a pass/fail summary."""
    golden_dir = Path(__file__).parent
    discovered = {path.name: path for path in discover_ground_truth_files(golden_dir)}

    passed_count = 0
    failed_count = 0

    for filename in EXPECTED_GOLDEN_FILES:
        path = discovered.get(filename)
        if path is None:
            print_missing_file_notice(filename)
            continue

        success, error_detail = validate_ground_truth_file(path)
        if success:
            passed_count += 1
            print(f"[OK] {filename} validates")
        else:
            failed_count += 1
            print(f"[FAIL] {filename} failed: {error_detail}")

    # Report any unexpected ground-truth files not in the expected list.
    unexpected = sorted(set(discovered) - set(EXPECTED_GOLDEN_FILES))
    for filename in unexpected:
        path = discovered[filename]
        success, error_detail = validate_ground_truth_file(path)
        if success:
            passed_count += 1
            print(f"[OK] {filename} validates (unexpected file)")
        else:
            failed_count += 1
            print(f"[FAIL] {filename} failed: {error_detail}")

    print()
    pending = [name for name in EXPECTED_GOLDEN_FILES if name not in discovered]
    status_suffix = " OK" if failed_count == 0 else ""
    print(
        f"Summary: {passed_count}/{EXPECTED_GOLDEN_COUNT} golden datasheets "
        f"valid{status_suffix}"
    )
    if pending:
        pending_id = pending[0].replace("_v1_ground_truth.json", "")
        print(f"({pending_id} pending annotation)")

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
