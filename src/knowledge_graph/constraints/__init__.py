"""Persisted, versioned per-design-run constraint nodes.

DESIGN_CONSTRAINT nodes are scoped by KGNode.design_id (plain scalar, per
NEO4J_BACKEND_DESIGN.md §1.1), written at layer 5 (project-specific), and
never deleted by any synthesis step — they are the provenance audit trail
("why was this component chosen") queryable after the run completes.

Each node is versioned against the KG state at creation time via a
knowledge_version tag derived from graph.stats(), so historical constraint
graphs remain interpretable after the KG grows.

All graph access goes through the public GraphBackend interface.

Public API:
    persist_design_constraints(intent, design_id, graph) -> list[KGNode]
    get_design_constraints(graph, design_id) -> list[KGNode]
    knowledge_version(graph) -> str
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.schemas.datasheet import ExtractionMethod
from src.schemas.kg import KGNode, KGNodeType

if TYPE_CHECKING:
    from src.knowledge_graph.backends import GraphBackend
    from src.schemas.intent import ImprovedIntentDict

logger = logging.getLogger(__name__)

_CONSTRAINT_LAYER = 5  # project-specific instances (see layer proposal in docs)
_SOURCE = "openforge:design_constraints"


def knowledge_version(graph: GraphBackend) -> str:
    """Version tag for the KG state: 'kg-v<node_count>.<edge_count>'.

    Monotonic under the append-mostly ingestion model; cheap to compute via
    the backend-agnostic stats() interface method.
    """
    stats = graph.stats()
    return f"kg-v{stats.get('node_count', 0)}.{stats.get('edge_count', 0)}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _constraint_node(
    design_id: str,
    kind: str,
    label: str,
    value: dict,
    version: str,
) -> KGNode:
    return KGNode(
        id=f"design_constraint:{design_id}:{kind}",
        node_type=KGNodeType.DESIGN_CONSTRAINT,
        layer=_CONSTRAINT_LAYER,
        label=label,
        properties={
            "kind": kind,
            "knowledge_version": version,
            **value,
        },
        source=_SOURCE,
        confidence=1.0,
        extraction_method=ExtractionMethod.MANUAL,
        created_at=_now(),
        design_id=design_id,
    )


def persist_design_constraints(
    intent: ImprovedIntentDict,
    design_id: str,
    graph: GraphBackend,
) -> list[KGNode]:
    """Persist the intent's numeric constraints as DESIGN_CONSTRAINT nodes.

    Extracts the typed v2 constraint categories that carry numeric limits
    (electrical, thermal, performance) plus the constraint strings, and
    writes one node per populated category. Idempotent per (design_id, kind).

    Never raises — returns whatever was successfully written.

    Args:
        intent: The (Stage 2-completed) design intent.
        design_id: The ValidatedBOM.design_id this run is scoped to.
        graph: Any GraphBackend implementation.

    Returns:
        List of KGNode objects written to the graph.
    """
    version = knowledge_version(graph)
    written: list[KGNode] = []

    candidates: list[tuple[str, str, dict]] = []

    electrical = getattr(intent, "electrical", None)
    if electrical is not None:
        candidates.append(
            (
                "electrical",
                f"Electrical constraints for design {design_id[:8]}",
                {"spec": electrical.model_dump(exclude_none=True)},
            )
        )

    thermal = getattr(intent, "thermal", None)
    if thermal is not None:
        candidates.append(
            (
                "thermal",
                f"Thermal constraints for design {design_id[:8]}",
                {"spec": thermal.model_dump(exclude_none=True)},
            )
        )

    performance = getattr(intent, "performance", None)
    if performance is not None:
        candidates.append(
            (
                "performance",
                f"Performance requirements for design {design_id[:8]}",
                {"spec": performance.model_dump(exclude_none=True)},
            )
        )

    explicit = list(getattr(intent, "explicit_constraints", []) or [])
    inferred = list(getattr(intent, "inferred_constraints", []) or [])
    if explicit or inferred:
        candidates.append(
            (
                "declared",
                f"Declared constraints for design {design_id[:8]}",
                {"explicit": explicit, "inferred": inferred},
            )
        )

    for kind, label, value in candidates:
        try:
            node = _constraint_node(design_id, kind, label, value, version)
            graph.add_node(node)
            written.append(node)
        except Exception as exc:
            logger.warning(f"Failed to persist {kind} constraint node: {exc}")

    logger.info(
        f"Persisted {len(written)} constraint nodes for design {design_id} "
        f"({version})"
    )
    return written


def get_design_constraints(graph: GraphBackend, design_id: str) -> list[KGNode]:
    """Return all DESIGN_CONSTRAINT nodes scoped to design_id.

    Uses only public GraphBackend methods (find_nodes_by_type + field
    filter), so it works identically on any backend.
    """
    return [
        node
        for node in graph.find_nodes_by_type(KGNodeType.DESIGN_CONSTRAINT)
        if node.design_id == design_id
    ]
