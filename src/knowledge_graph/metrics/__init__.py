"""Persisted, versioned per-design-run predicted metric nodes.

PREDICTED_METRIC nodes represent system-computed outputs (battery life, CMRR,
phase noise, etc.) with DERIVED_FROM edges tracing back to the inputs that
produced them — constraints, component instances, and topologies.

Each node is versioned against the KG state at creation time via
``knowledge_version(graph)`` from the constraints package (same tagging scheme
as DESIGN_CONSTRAINT nodes).

All graph access goes through the public GraphBackend interface.

Public API:
    persist_predicted_metric(...) -> KGNode | None
    get_predicted_metrics(graph, design_id, metric_kind=None) -> list[KGNode]
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from src.knowledge_graph.constraints import knowledge_version
from src.schemas.common import ConditionScope
from src.schemas.datasheet import ExtractionMethod
from src.schemas.kg import KGEdge, KGNode, KGNodeType, KGRelation

if TYPE_CHECKING:
    from src.knowledge_graph.backends import GraphBackend

logger = logging.getLogger(__name__)

_METRIC_LAYER = 5  # project-specific instances (same as DESIGN_CONSTRAINT)
_SOURCE = "openforge:predicted_metrics"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _metric_node(
    design_id: str,
    metric_kind: str,
    value: float,
    unit: str,
    method: str,
    version: str,
    condition: ConditionScope | None,
) -> KGNode:
    properties: dict[str, Any] = {
        "metric_kind": metric_kind,
        "value": value,
        "unit": unit,
        "method": method,
        "knowledge_version": version,
    }
    if condition is not None:
        properties["condition"] = condition.model_dump(exclude_none=True)

    return KGNode(
        id=f"predicted_metric:{design_id}:{metric_kind}:{method}",
        node_type=KGNodeType.PREDICTED_METRIC,
        layer=_METRIC_LAYER,
        label=f"Predicted {metric_kind} for design {design_id[:8]}",
        properties=properties,
        source=_SOURCE,
        confidence=1.0,
        extraction_method=ExtractionMethod.MANUAL,
        created_at=_now(),
        design_id=design_id,
    )


def persist_predicted_metric(
    graph: GraphBackend,
    design_id: str,
    metric_kind: str,
    value: float,
    unit: str,
    method: str,
    derived_from: list[tuple[str, dict[str, Any]]],
    condition: ConditionScope | None = None,
) -> KGNode | None:
    """Persist a predicted metric node and DERIVED_FROM edges to its inputs.

    ``derived_from`` is a list of ``(input_node_id, contribution_dict)`` pairs.
    Contribution data is stored directly on ``KGEdge.constraints`` (same
    ``dict[str, Any]`` pattern as ScalingLaw entries on PART_OF edges).

    Never raises — returns the metric node if written, else None.

    Idempotent per (design_id, metric_kind, method): re-running the same
    estimator overwrites the prior value; different methods coexist as
    separate nodes.
    """
    if not design_id or not metric_kind or not method:
        logger.warning("Skipping predicted metric persist: missing required fields")
        return None

    version = knowledge_version(graph)
    try:
        node = _metric_node(
            design_id, metric_kind, value, unit, method, version, condition
        )
        graph.add_node(node)
    except Exception as exc:
        logger.warning(f"Failed to persist predicted metric {metric_kind}: {exc}")
        return None

    for input_node_id, contribution in derived_from:
        if not input_node_id:
            continue
        try:
            edge = KGEdge(
                source_id=node.id,
                relation=KGRelation.DERIVED_FROM,
                target_id=input_node_id,
                constraints=dict(contribution),
                source_document=_SOURCE,
                confidence=1.0,
                layer=_METRIC_LAYER,
            )
            graph.add_edge(edge)
        except Exception as exc:
            logger.warning(
                f"Failed DERIVED_FROM edge {node.id} -> {input_node_id}: {exc}"
            )

    logger.info(
        f"Persisted predicted metric {metric_kind} for design {design_id} "
        f"({version})"
    )
    return node


def get_predicted_metrics(
    graph: GraphBackend,
    design_id: str,
    metric_kind: str | None = None,
) -> list[KGNode]:
    """Return PREDICTED_METRIC nodes scoped to design_id.

    When ``metric_kind`` is provided, only nodes of that metric category are
    returned (possibly multiple when different ``method`` values coexist).

    Uses only public GraphBackend methods (find_nodes_by_type + field
    filter), so it works identically on any backend.
    """
    nodes = [
        node
        for node in graph.find_nodes_by_type(KGNodeType.PREDICTED_METRIC)
        if node.design_id == design_id
    ]
    if metric_kind is None:
        return nodes
    return [node for node in nodes if node.properties.get("metric_kind") == metric_kind]
