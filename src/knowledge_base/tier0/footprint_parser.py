"""Parse KiCad .kicad_mod footprint files into KiCadFootprintEntry objects."""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sexpdata

from src.schemas.documents import DocumentType, KiCadFootprintEntry

logger = logging.getLogger(__name__)

_IPC_NAME_PATTERN = re.compile(r"^[A-Z0-9]+[-_][0-9]")


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


def _has_layer(node: list, layer_name: str) -> bool:
    """Check if node has a (layer "...") child matching layer_name."""
    for layer_node in _find_children(node, "layer"):
        layer_val = _get_str(layer_node)
        if layer_val == layer_name:
            return True
    return False


def _collect_xy_from_node(node: list, xs: list[float], ys: list[float]) -> None:
    """Collect x/y coordinates from start/end or xy children."""
    for start_node in _find_children(node, "start"):
        try:
            xs.append(float(start_node[1]))
            ys.append(float(start_node[2]))
        except (IndexError, TypeError, ValueError):
            pass
    for end_node in _find_children(node, "end"):
        try:
            xs.append(float(end_node[1]))
            ys.append(float(end_node[2]))
        except (IndexError, TypeError, ValueError):
            pass
    for pts_node in _find_children(node, "pts"):
        for xy_node in _find_children(pts_node, "xy"):
            try:
                xs.append(float(xy_node[1]))
                ys.append(float(xy_node[2]))
            except (IndexError, TypeError, ValueError):
                pass


def _compute_courtyard(fp_node: list) -> tuple[float, float]:
    """
    Compute courtyard dimensions from F.CrtYd layer lines and polygons.

    Returns (courtyard_x_mm, courtyard_y_mm) as bounding box dimensions.
    Returns (0.0, 0.0) if no courtyard geometry found.
    """
    xs: list[float] = []
    ys: list[float] = []

    for line_node in _find_children(fp_node, "fp_line"):
        if _has_layer(line_node, "F.CrtYd"):
            _collect_xy_from_node(line_node, xs, ys)

    for poly_node in _find_children(fp_node, "fp_poly"):
        if _has_layer(poly_node, "F.CrtYd"):
            _collect_xy_from_node(poly_node, xs, ys)

    if not xs:
        return (0.0, 0.0)

    return (max(xs) - min(xs), max(ys) - min(ys))


def _find_footprint_node(tree: Any) -> list | None:
    """Locate the (footprint ...) node in parsed S-expression tree."""
    if not isinstance(tree, list):
        return None

    if tree and _sym_match(tree[0], "footprint"):
        return tree

    if (
        len(tree) == 1
        and isinstance(tree[0], list)
        and tree[0]
        and _sym_match(tree[0][0], "footprint")
    ):
        return tree[0]

    for child in tree:
        if isinstance(child, list) and child and _sym_match(child[0], "footprint"):
            return child

    return None


def parse_footprint_file(path: Path) -> KiCadFootprintEntry | None:
    """
    Parse one .kicad_mod file and return a KiCadFootprintEntry.

    Returns None if the file is malformed or cannot be parsed.
    Logs a warning on failure; never raises.
    """
    try:
        file_text = path.read_text(encoding="utf-8")
        tree = sexpdata.loads(file_text)
        fp_node = _find_footprint_node(tree)
        if fp_node is None:
            logger.warning("No footprint node found in %s", path)
            return None

        footprint_name = _get_str(fp_node)
        if not footprint_name:
            logger.warning("Missing footprint name in %s", path)
            return None

        library_name = path.parent.name

        descr_nodes = _find_children(fp_node, "descr")
        description = _get_str(descr_nodes[0]) if descr_nodes else None

        pad_nodes = _find_children(fp_node, "pad")
        pad_count = len(pad_nodes)

        crtyd_x, crtyd_y = _compute_courtyard(fp_node)
        review_required = crtyd_x == 0.0 and crtyd_y == 0.0

        ipc_name = (
            footprint_name
            if _IPC_NAME_PATTERN.match(footprint_name)
            else None
        )

        now = datetime.now(timezone.utc).isoformat()
        content_hash = hashlib.sha256(
            f"{library_name}:{footprint_name}:{pad_count}pads".encode()
        ).hexdigest()

        return KiCadFootprintEntry(
            document_id=str(
                uuid.uuid5(
                    uuid.NAMESPACE_DNS,
                    f"{library_name}:{footprint_name}",
                )
            ),
            document_type=DocumentType.KICAD_FOOTPRINT,
            source_url=f"file://{path.resolve()}",
            content_hash=content_hash,
            ingestion_tier=0,
            ingested_at=now,
            review_required=review_required,
            footprint_name=footprint_name,
            library_name=library_name,
            description=description,
            pad_count=pad_count,
            courtyard_x_mm=crtyd_x,
            courtyard_y_mm=crtyd_y,
            ipc_name=ipc_name,
        )
    except Exception as exc:
        logger.warning("Failed to parse footprint %s: %s", path, exc)
        return None
