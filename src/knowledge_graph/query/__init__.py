"""Knowledge graph query engine — primary Team B output.

The only function Team C calls is query_graph().  Everything else in this
package is internal implementation detail.

Public API:
    query_graph(intent, graph, config) -> DesignSubgraph

Example:
    >>> from src.knowledge_graph.query import query_graph
    >>> subgraph = query_graph(intent, graph, config)
    >>> for node in subgraph.component_types:
    ...     print(node.label)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.knowledge_graph.query import goal_mapper, result_builder, traversal
from src.schemas.intent import DesignMethodology, FrequencySpec, IntentDict
from src.schemas.kg import DesignSubgraph

if TYPE_CHECKING:
    from src.config import Config
    from src.knowledge_graph import KnowledgeGraph

logger = logging.getLogger(__name__)

# Unit multipliers for FrequencySpec → Hz conversion
_FREQ_UNIT_TO_HZ: dict[str, float] = {
    "Hz": 1.0,
    "kHz": 1e3,
    "MHz": 1e6,
    "GHz": 1e9,
}


def _convert_to_hz(freq: FrequencySpec) -> float:
    """Convert a FrequencySpec to Hz."""
    return float(freq.value * _FREQ_UNIT_TO_HZ[freq.unit])


def _apply_frequency_filter(
    path_confidences: dict[str, float],
    intent_frequency: FrequencySpec,
    graph: KnowledgeGraph,
) -> dict[str, float]:
    """Prune nodes whose frequency_hz property is outside ±20% of the target.

    Nodes that do not have a frequency_hz property are kept unchanged.

    Args:
        path_confidences: Mapping from bfs_traverse
        intent_frequency: FrequencySpec from IntentDict
        graph: KnowledgeGraph for node lookup

    Returns:
        Filtered path_confidences dict (mutates a copy, not the original).
    """
    target_hz = _convert_to_hz(intent_frequency)
    filtered = {}

    for node_id, confidence in path_confidences.items():
        node = graph.get_node(node_id)
        if node is None:
            filtered[node_id] = confidence
            continue

        node_freq = node.properties.get("frequency_hz")
        if node_freq is None:
            # No frequency constraint — keep unconditionally
            filtered[node_id] = confidence
            continue

        try:
            node_freq_f = float(node_freq)
        except (TypeError, ValueError):
            filtered[node_id] = confidence
            continue

        # Prune if outside ±20% tolerance
        if abs(node_freq_f - target_hz) / target_hz <= 0.20:
            filtered[node_id] = confidence
        else:
            logger.debug(
                f"Frequency filter pruned {node_id!r}: "
                f"node={node_freq_f:.0f}Hz target={target_hz:.0f}Hz"
            )

    return filtered


def _empty_subgraph(design_methodology: str) -> DesignSubgraph:
    """Return a fully-empty DesignSubgraph for the given methodology string."""
    return DesignSubgraph(
        component_types=[],
        component_instances=[],
        design_rules=[],
        placement_rules=[],
        routing_hints=[],
        topologies=[],
        functional_blocks=[],
        design_methodology=design_methodology,
        path_confidences={},
        query_depth=0,
        query_metadata={},
    )


def query_graph(
    intent: IntentDict,
    graph: KnowledgeGraph,
    config: Config,
) -> DesignSubgraph:
    """Traverse the KnowledgeGraph from a design intent and return a DesignSubgraph.

    Never raises. Returns an empty DesignSubgraph on any failure.

    Args:
        intent: Parsed design intent from Team A / intent parser
        graph: KnowledgeGraph populated by Team B ingestion pipeline
        config: Application configuration (provides traversal depth + confidence)

    Returns:
        DesignSubgraph containing component types, instances, placement rules,
        routing hints, and design rules relevant to the intent goal.

    Example:
        >>> subgraph = query_graph(intent, graph, config)
        >>> print(len(subgraph.component_types))
        3
    """
    methodology_str = intent.design_methodology.value

    try:
        max_depth = config.kg_traversal_max_depth
        min_confidence = config.kg_min_edge_confidence

        # Step 1: map intent goal and optional topology slug → start nodes
        goal_starts = goal_mapper.map_goal_to_nodes(intent.goal, graph)
        topology_starts = goal_mapper.map_goal_topology_to_nodes(
            intent.goal_topology,
            graph,
        )
        start_nodes = goal_mapper.merge_start_nodes(goal_starts, topology_starts)
        if not start_nodes:
            logger.warning(
                f"No KG nodes found for goal={intent.goal!r} "
                f"goal_topology={intent.goal_topology!r}"
            )
            return _empty_subgraph(methodology_str)

        # Step 2: load the active methodology node from KG-5
        methodology_node_id = f"design_methodology:{methodology_str}"
        methodology_node = graph.get_node(methodology_node_id)
        if methodology_node is None:
            logger.warning(
                f"No methodology node for {intent.design_methodology!r} "
                f"(id={methodology_node_id!r}); placement filter will be skipped"
            )

        # Step 3: BFS traversal (product path-confidence)
        path_confidences, traversed_edges = traversal.bfs_traverse(
            start_nodes,
            graph,
            max_depth=max_depth,
            min_edge_confidence=min_confidence,
        )

        # Step 4: optional frequency filter
        if intent.frequency is not None:
            path_confidences = _apply_frequency_filter(
                path_confidences, intent.frequency, graph
            )

        # Step 5: assemble DesignSubgraph
        return result_builder.build_subgraph(
            path_confidences=path_confidences,
            traversed_edges=traversed_edges,
            graph=graph,
            methodology_node=methodology_node,
            design_methodology=methodology_str,
            query_depth=max_depth,
        )

    except Exception as exc:  # noqa: BLE001
        logger.error(f"query_graph failed for goal {intent.goal!r}: {exc}", exc_info=True)
        return _empty_subgraph(methodology_str)


__all__ = ["query_graph"]
