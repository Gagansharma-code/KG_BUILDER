"""Parse KiCad .kicad_sym library files into KiCadSymbolEntry objects."""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sexpdata

from src.schemas.documents import DocumentType, KiCadPinDef, KiCadSymbolEntry

logger = logging.getLogger(__name__)

KICAD_PIN_TYPE_MAP: dict[str, str] = {
    "input": "input",
    "output": "output",
    "bidirectional": "bidirectional",
    "tristate": "bidirectional",
    "passive": "passive",
    "free": "passive",
    "unspecified": "passive",
    "power_in": "power_in",
    "power_out": "power_out",
    "open_collector": "output",
    "open_emitter": "output",
    "no_connect": "nc",
}


def _sym_match(element: Any, name: str) -> bool:
    """Return True if element is sexpdata.Symbol(name) or str(name)."""
    if isinstance(element, sexpdata.Symbol):
        return str(element) == name
    return str(element) == name


def _find_children(node: list, key: str) -> list[list]:
    """Find all direct child lists of node whose first element matches key."""
    children: list[list] = []
    for child in node:
        if isinstance(child, list) and child and _sym_match(child[0], key):
            children.append(child)
    return children


def _get_str(node: list, index: int = 1) -> str | None:
    """Return node[index] as a string, or None if missing or not stringifiable."""
    if index >= len(node):
        return None
    try:
        return str(node[index])
    except (IndexError, TypeError):
        return None


def _parse_pin(pin_node: list) -> KiCadPinDef | None:
    """Extract one pin from a (pin ...) s-expression node."""
    pin_type = KICAD_PIN_TYPE_MAP.get(str(pin_node[1]), "passive")

    at_nodes = _find_children(pin_node, "at")
    position_x = 0.0
    position_y = 0.0
    if at_nodes:
        at_node = at_nodes[0]
        try:
            position_x = float(at_node[1])
            position_y = float(at_node[2])
        except (IndexError, TypeError, ValueError):
            pass

    name_nodes = _find_children(pin_node, "name")
    number_nodes = _find_children(pin_node, "number")

    pin_name = _get_str(name_nodes[0]) if name_nodes else None
    pin_number = _get_str(number_nodes[0]) if number_nodes else None

    if not pin_name or not pin_number:
        logger.warning("Skipping pin with missing name or number")
        return None

    return KiCadPinDef(
        pin_number=pin_number,
        pin_name=pin_name,
        pin_type=pin_type,
        position_x=position_x,
        position_y=position_y,
    )


def _parse_symbol_node(
    sym_node: list,
    library_name: str,
    now: str,
) -> tuple[str, dict] | None:
    """Parse one (symbol "NAME" ...) top-level node."""
    symbol_name = _get_str(sym_node)
    if not symbol_name:
        return None

    extends_nodes = _find_children(sym_node, "extends")
    extends: str | None = None
    if extends_nodes:
        extends = _get_str(extends_nodes[0])

    properties: dict[str, str] = {}
    for prop_node in _find_children(sym_node, "property"):
        key = _get_str(prop_node)
        value = _get_str(prop_node, 2)
        if key is not None and value is not None:
            properties[key] = value

    pins: list[KiCadPinDef] = []
    prefix = f"{symbol_name}_"
    for child in sym_node:
        if not isinstance(child, list) or not child:
            continue
        if not _sym_match(child[0], "symbol"):
            continue
        sub_name = _get_str(child)
        if sub_name and sub_name.startswith(prefix):
            for pin_node in _find_children(child, "pin"):
                pin = _parse_pin(pin_node)
                if pin is not None:
                    pins.append(pin)

    return symbol_name, {
        "symbol_name": symbol_name,
        "library_name": library_name,
        "extends": extends,
        "properties": properties,
        "pins": pins,
        "now": now,
    }


def _find_top_level_symbols(tree: Any) -> list[list]:
    """Locate top-level (symbol ...) nodes under (kicad_symbol_lib ...)."""
    if not isinstance(tree, list):
        return []

    root = tree
    if not (tree and _sym_match(tree[0], "kicad_symbol_lib")):
        if (
            len(tree) == 1
            and isinstance(tree[0], list)
            and tree[0]
            and _sym_match(tree[0][0], "kicad_symbol_lib")
        ):
            root = tree[0]
        else:
            return []

    symbols: list[list] = []
    for child in root:
        if isinstance(child, list) and child and _sym_match(child[0], "symbol"):
            symbols.append(child)

    all_names = {_get_str(s) for s in symbols}
    all_names.discard(None)

    top_level: list[list] = []
    for sym in symbols:
        name = _get_str(sym)
        if not name:
            continue
        is_sub_unit = any(
            other_name != name and name.startswith(f"{other_name}_")
            for other_name in all_names
        )
        if not is_sub_unit:
            top_level.append(sym)

    return top_level


def parse_symbol_library(path: Path) -> list[KiCadSymbolEntry]:
    """
    Parse a .kicad_sym library file and return all symbols as KiCadSymbolEntry objects.

    Handles extends resolution in two passes.
    Skips malformed symbols with a logged warning (never raises).

    Args:
        path: Path to a .kicad_sym file

    Returns:
        List of KiCadSymbolEntry objects. May be empty if file is malformed.
    """
    library_name = path.stem
    now = datetime.now(timezone.utc).isoformat()

    try:
        file_text = path.read_text(encoding="utf-8")
        tree = sexpdata.loads(file_text)
    except Exception as exc:
        logger.warning("Failed to parse symbol library %s: %s", path, exc)
        return []

    try:
        sym_nodes = _find_top_level_symbols(tree)
    except Exception as exc:
        logger.warning("Failed to find symbols in %s: %s", path, exc)
        return []

    raw_symbols: dict[str, dict] = {}
    for sym_node in sym_nodes:
        try:
            result = _parse_symbol_node(sym_node, library_name, now)
            if result:
                name, raw = result
                raw_symbols[name] = raw
        except Exception as exc:
            sym_name = _get_str(sym_node) if isinstance(sym_node, list) else "unknown"
            logger.warning("Failed to parse symbol %s in %s: %s", sym_name, path, exc)

    entries: list[KiCadSymbolEntry] = []
    for name, raw in raw_symbols.items():
        try:
            pins = list(raw["pins"])
            review_required = False
            review_flags: list[str] = []

            if raw["extends"]:
                parent = raw_symbols.get(raw["extends"])
                if parent:
                    pins = list(parent["pins"]) + pins
                else:
                    review_required = True
                    review_flags.append(f"extends_parent_missing:{raw['extends']}")

            properties = raw["properties"]
            description = properties.get("Description") or properties.get(
                "ki_description"
            )
            datasheet_url = properties.get("Datasheet")
            keywords = properties.get("ki_keywords", "").split()

            symbol_name = raw["symbol_name"]
            content_hash = hashlib.sha256(
                f"{library_name}:{symbol_name}:{len(pins)}pins".encode()
            ).hexdigest()

            entry = KiCadSymbolEntry(
                document_id=str(
                    uuid.uuid5(
                        uuid.NAMESPACE_DNS,
                        f"{library_name}:{symbol_name}",
                    )
                ),
                document_type=DocumentType.KICAD_SYMBOL,
                source_url=f"file://{path.resolve()}",
                content_hash=content_hash,
                ingestion_tier=0,
                ingested_at=now,
                review_required=review_required,
                review_flags=review_flags,
                symbol_name=symbol_name,
                library_name=library_name,
                description=description,
                datasheet_url=datasheet_url,
                keywords=keywords,
                pins=pins,
                properties=properties,
            )
            entries.append(entry)
        except Exception as exc:
            logger.warning("Failed to build entry for symbol %s in %s: %s", name, path, exc)

    return entries
