"""Goal mapper — converts an intent goal string to KG start nodes.

Applied in order, stopping at first strategy that returns results:
  Strategy 1: exact label match (case-insensitive)
  Strategy 2: all goal words present in node label
  Strategy 3: any goal word (len > 3) present — top 5 by match count
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.schemas.kg import KGNode, KGNodeType, KGRelation

if TYPE_CHECKING:
    from src.knowledge_graph import KnowledgeGraph

logger = logging.getLogger(__name__)

# Only these node types qualify as traversal start nodes
_START_NODE_TYPES = (
    KGNodeType.COMPONENT_TYPE,
    KGNodeType.DESIGN_RECIPE,
    KGNodeType.TOPOLOGY,
)


def _goal_words(goal: str) -> list[str]:
    """Split goal into deduped words using both '_' and ' ' as separators."""
    words: list[str] = []
    seen: set[str] = set()
    for part in goal.replace("_", " ").split():
        w = part.lower()
        if w not in seen:
            seen.add(w)
            words.append(w)
    return words


def _include_topology_blocks(
    start_nodes: list[KGNode],
    graph: KnowledgeGraph,
) -> list[KGNode]:
    """Include FUNCTIONAL_BLOCK children when a TOPOLOGY node is a start.

    PART_OF edges run block -> topology, so outbound BFS from a TOPOLOGY
    start cannot reach its blocks. Co-starting from those blocks keeps them
    in path_confidences without changing global traversal semantics.
    """
    if not start_nodes:
        return start_nodes

    expanded: list[KGNode] = []
    seen: set[str] = set()
    for node in start_nodes:
        if node.id not in seen:
            expanded.append(node)
            seen.add(node.id)
        if node.node_type != KGNodeType.TOPOLOGY:
            continue
        for edge in graph.get_edges_to(node.id, relation=KGRelation.PART_OF):
            block = graph.get_node(edge.source_id)
            if block is not None and block.id not in seen:
                expanded.append(block)
                seen.add(block.id)
    return expanded


def map_goal_to_nodes(goal: str, graph: KnowledgeGraph) -> list[KGNode]:
    """Find KG start nodes for a goal string.

    COMPONENT_TYPE, DESIGN_RECIPE, and TOPOLOGY nodes qualify as start nodes.
    When a TOPOLOGY node matches, its FUNCTIONAL_BLOCK children are included
    as co-start nodes (PART_OF edges are block -> topology).

    Three strategies applied in order; returns at first hit:
    - Strategy 1: exact label match (case-insensitive)
    - Strategy 2: all goal words present in node label
    - Strategy 3: any word (len > 3) present — top 5 by descending match count

    Returns [] and logs WARNING if all strategies yield nothing.

    Args:
        goal: Design goal from IntentDict (e.g. "patch_antenna", "5V buck converter")
        graph: KnowledgeGraph to search

    Returns:
        List of KGNode start nodes; may be empty.
    """
    candidates: list[KGNode] = []
    for node_type in _START_NODE_TYPES:
        candidates.extend(graph.find_nodes_by_type(node_type))

    if not candidates:
        logger.warning(
            f"No COMPONENT_TYPE, DESIGN_RECIPE, or TOPOLOGY nodes in graph for goal: {goal!r}"
        )
        return []

    goal_lower = goal.lower()
    words = _goal_words(goal)

    # ── Strategy 1: exact label match ────────────────────────────────────────
    exact = [n for n in candidates if n.label.lower() == goal_lower]
    if exact:
        logger.debug(f"Goal {goal!r}: Strategy 1 matched {len(exact)} node(s)")
        return _include_topology_blocks(exact, graph)

    # ── Strategy 2: all words present ────────────────────────────────────────
    all_words = [
        n for n in candidates
        if all(w in n.label.lower() for w in words)
    ]
    if all_words:
        logger.debug(f"Goal {goal!r}: Strategy 2 matched {len(all_words)} node(s)")
        return _include_topology_blocks(all_words, graph)

    # ── Strategy 3: any word (len > 3) present, ranked, top 5 ───────────────
    significant_words = [w for w in words if len(w) > 3]
    if significant_words:
        scored: list[tuple[int, KGNode]] = []
        for n in candidates:
            label_lower = n.label.lower()
            count = sum(1 for w in significant_words if w in label_lower)
            if count > 0:
                scored.append((count, n))
        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            top5 = [n for _, n in scored[:5]]
            logger.debug(
                f"Goal {goal!r}: Strategy 3 matched {len(scored)} node(s), returning top {len(top5)}"
            )
            return _include_topology_blocks(top5, graph)

    logger.warning(f"No KG nodes found for goal: {goal!r}")
    return []


def map_goal_topology_to_nodes(
    goal_topology: str | None,
    graph: KnowledgeGraph,
) -> list[KGNode]:
    """Resolve a topology classifier slug to TOPOLOGY start nodes.

    Uses the canonical node id ``topology:<slug>`` from the formal topology
    library. When found, FUNCTIONAL_BLOCK children are co-started via
    ``_include_topology_blocks``.

    Args:
        goal_topology: Slug from intent (e.g. ``buck_converter``), or None.
        graph: KnowledgeGraph to search.

    Returns:
        Start nodes for traversal; empty when slug is absent or unmatched.
    """
    if not goal_topology:
        return []

    slug = goal_topology.strip().lower()
    if not slug:
        return []

    node = graph.get_node(f"topology:{slug}")
    if node is None or node.node_type != KGNodeType.TOPOLOGY:
        logger.warning(f"No TOPOLOGY node for goal_topology={goal_topology!r}")
        return []

    logger.debug(f"goal_topology {goal_topology!r} matched {node.id}")
    return _include_topology_blocks([node], graph)


def merge_start_nodes(*groups: list[KGNode]) -> list[KGNode]:
    """Dedupe start nodes by id while preserving first-seen order."""
    merged: list[KGNode] = []
    seen: set[str] = set()
    for group in groups:
        for node in group:
            if node.id not in seen:
                merged.append(node)
                seen.add(node.id)
    return merged
