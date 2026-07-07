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
    persist_protection_requirements(intent, design_id, graph) -> list[ProtectionRequirement]
    get_design_constraints(graph, design_id) -> list[KGNode]
    knowledge_version(graph) -> str
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.schemas.datasheet import ExtractionMethod
from src.schemas.intent import ProtectionRequirement
from src.schemas.kg import KGEdge, KGNode, KGNodeType, KGRelation

if TYPE_CHECKING:
    from src.config import Config
    from src.knowledge_graph.backends import GraphBackend
    from src.schemas.intent import ImprovedIntentDict

logger = logging.getLogger(__name__)

_CONSTRAINT_LAYER = 5  # project-specific instances (see layer proposal in docs)
_SOURCE = "openforge:design_constraints"

# Maps protection requirement kind -> functional_block slug suffix in the topology library.
_PROTECTION_BLOCK_SLUGS: dict[str, str] = {
    "reverse_current": "reverse_current_protection",
    "reverse_polarity": "reverse_polarity_protection",
    "esd": "esd_protection",
    "thermal_shutdown": "thermal_shutdown",
    "soft_start": "soft_start",
    "emi_input_filter": "emi_input_filter",
    "kelvin_sensing": "kelvin_sensing",
}


def knowledge_version(graph: GraphBackend) -> str:
    """Version tag for the KG state: 'kg-v<node_count>.<edge_count>'.

    Monotonic under the append-mostly ingestion model; cheap to compute via
    the backend-agnostic stats() interface method.
    """
    stats = graph.stats()
    return f"kg-v{stats.get('node_count', 0)}.{stats.get('edge_count', 0)}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _flatten_spec_scalars(spec: dict, *, prefix: str = "") -> dict:
    """Promote queryable scalars from a nested constraint spec dict."""
    out: dict = {}
    for key, val in spec.items():
        if val is None or key == "raw_text":
            continue
        name = f"{prefix}{key}" if prefix else key
        if isinstance(val, (int, float, bool, str)):
            out[name] = val
        elif isinstance(val, dict):
            child_prefix = "condition_" if key == "condition" else f"{name}_"
            out.update(_flatten_spec_scalars(val, prefix=child_prefix))
    return out


def _promoted_scalars_from_value(value: dict) -> dict:
    """Scalar fields promoted alongside the full spec blob for queryability."""
    if "spec" not in value:
        return {}
    return _flatten_spec_scalars(value["spec"])


def _constraint_node(
    design_id: str,
    kind: str,
    label: str,
    value: dict,
    version: str,
    scope: str = "default",
) -> KGNode:
    return KGNode(
        id=f"design_constraint:{design_id}:{kind}:{scope}",
        node_type=KGNodeType.DESIGN_CONSTRAINT,
        layer=_CONSTRAINT_LAYER,
        label=label,
        properties={
            "kind": kind,
            "scope": scope,
            "knowledge_version": version,
            **value,
            **_promoted_scalars_from_value(value),
        },
        source=_SOURCE,
        confidence=1.0,
        extraction_method=ExtractionMethod.MANUAL,
        created_at=_now(),
        design_id=design_id,
    )


def _find_functional_block_for_protection(
    graph: GraphBackend,
    kind: str,
) -> KGNode | None:
    """Return a FUNCTIONAL_BLOCK node matching a protection kind, if any."""
    block_slug = _PROTECTION_BLOCK_SLUGS.get(kind, kind)
    for node in graph.find_nodes_by_type(KGNodeType.FUNCTIONAL_BLOCK):
        if node.properties.get("slug") == block_slug:
            return node
        if node.id.endswith(f":{block_slug}"):
            return node
    return None


def persist_protection_requirements(
    intent: ImprovedIntentDict,
    design_id: str,
    graph: GraphBackend,
) -> list[ProtectionRequirement]:
    """Persist protection asks as scoped DESIGN_CONSTRAINT nodes.

    Each requirement is written as ``kind="protection"`` with ``scope`` equal
    to the requirement's ``kind`` value. Attempts a ``REQUIRES`` edge to a
    matching ``FUNCTIONAL_BLOCK`` when one exists in the graph.

    Returns requirements that could not be resolved to a functional block.
    """
    requirements = list(getattr(intent, "protection_requirements", []) or [])
    if not requirements:
        return []

    version = knowledge_version(graph)
    unresolved: list[ProtectionRequirement] = []

    for requirement in requirements:
        try:
            spec_data = requirement.model_dump(exclude_none=True)
            spec_data["requirement_kind"] = spec_data.pop("kind")
            node = _constraint_node(
                design_id,
                "protection",
                f"Protection ({requirement.kind}) for design {design_id[:8]}",
                {"spec": spec_data},
                version,
                scope=requirement.kind,
            )
            graph.add_node(node)

            block = _find_functional_block_for_protection(graph, requirement.kind)
            if block is None:
                unresolved.append(requirement)
                continue

            edge = KGEdge(
                source_id=node.id,
                relation=KGRelation.REQUIRES,
                target_id=block.id,
                constraints={},
                source_document=_SOURCE,
                confidence=1.0,
                layer=_CONSTRAINT_LAYER,
            )
            graph.add_edge(edge)
        except Exception as exc:
            logger.warning(
                f"Failed to persist protection requirement {requirement.kind}: {exc}"
            )
            unresolved.append(requirement)

    if unresolved:
        logger.warning(
            f"{len(unresolved)} protection requirement(s) unresolved for design "
            f"{design_id}: {[r.kind for r in unresolved]}"
        )
    return unresolved


def persist_design_constraints(
    intent: ImprovedIntentDict,
    design_id: str,
    graph: GraphBackend,
    scope: str = "default",
    *,
    config: Config | None = None,
) -> list[KGNode]:
    """Persist the intent's numeric constraints as DESIGN_CONSTRAINT nodes.

    Extracts the typed v2 constraint categories that carry numeric limits
    (electrical, thermal, performance) plus the constraint strings, and
    writes one node per populated category. Idempotent per
    (design_id, kind, scope).

    Never raises — returns whatever was successfully written.

    Args:
        intent: The (Stage 2-completed) design intent.
        design_id: The ValidatedBOM.design_id this run is scoped to.
        graph: Any GraphBackend implementation.
        scope: Block/rail identity for this write batch (default ``"default"``
            preserves one-node-per-kind behavior for unscoped callers).

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
            node = _constraint_node(
                design_id, kind, label, value, version, scope=scope
            )
            graph.add_node(node)
            written.append(node)
        except Exception as exc:
            logger.warning(f"Failed to persist {kind} constraint node: {exc}")

    logger.info(
        f"Persisted {len(written)} constraint nodes for design {design_id} "
        f"({version})"
    )

    unresolved = persist_protection_requirements(intent, design_id, graph)
    if unresolved and config is not None:
        from src.review.queue import enqueue_unresolved_protection

        enqueue_unresolved_protection(intent, design_id, unresolved, config)

    return written


def get_design_constraints(
    graph: GraphBackend,
    design_id: str,
    kind: str | None = None,
) -> list[KGNode]:
    """Return DESIGN_CONSTRAINT nodes scoped to design_id.

    When ``kind`` is provided, only nodes of that constraint category are
    returned (possibly multiple when different ``scope`` values coexist).

    Uses only public GraphBackend methods (find_nodes_by_type + field
    filter), so it works identically on any backend.
    """
    nodes = [
        node
        for node in graph.find_nodes_by_type(KGNodeType.DESIGN_CONSTRAINT)
        if node.design_id == design_id
    ]
    if kind is None:
        return nodes
    return [node for node in nodes if node.properties.get("kind") == kind]
