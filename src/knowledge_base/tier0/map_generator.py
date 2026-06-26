"""Generate JSON lookup maps for KiCad symbol and footprint resolution."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from src.schemas.documents import KiCadFootprintEntry, KiCadSymbolEntry

logger = logging.getLogger(__name__)

SYMBOL_MAP_PATH = Path("data/kicad_maps/symbol_map.json")
FOOTPRINT_MAP_PATH = Path("data/kicad_maps/footprint_map.json")


def generate_symbol_map(
    entries: list[KiCadSymbolEntry],
    output_path: Path = SYMBOL_MAP_PATH,
) -> int:
    """
    Build and write symbol_map.json from a list of KiCadSymbolEntry objects.

    JSON format:
    {
        "OPA189": {"library": "Amplifier_Operational", "symbol": "OPA189"},
        ...
    }

    Key is symbol_name. Value is the KiCad library:symbol reference.
    Skips entries where library_name or symbol_name is empty.

    Returns number of entries written.
    """
    data: dict[str, dict[str, str]] = {}
    for entry in entries:
        if not entry.library_name or not entry.symbol_name:
            continue
        data[entry.symbol_name] = {
            "library": entry.library_name,
            "symbol": entry.symbol_name,
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info("Wrote %d symbol map entries to %s", len(data), output_path)
    return len(data)


def generate_footprint_map(
    entries: list[KiCadFootprintEntry],
    output_path: Path = FOOTPRINT_MAP_PATH,
) -> int:
    """
    Build and write footprint_map.json from a list of KiCadFootprintEntry objects.

    JSON format:
    {
        "SOT-23-5": "Package_TO_SOT_SMD:SOT-23-5",
        ...
    }

    Key is footprint_name. Value is "LibraryName:FootprintName".
    Returns number of entries written.
    """
    data: dict[str, str] = {}
    for entry in entries:
        if entry is None:
            continue
        if not entry.library_name or not entry.footprint_name:
            continue
        data[entry.footprint_name] = f"{entry.library_name}:{entry.footprint_name}"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info("Wrote %d footprint map entries to %s", len(data), output_path)
    return len(data)
