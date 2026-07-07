"""Result builder — assemble DesignSubgraph from BFS traversal output.

Steps:
  1. Retrieve all visited nodes from the graph by their IDs.
  2. Categorize by node_type into component_types, component_instances,
     placement_rules, routing_hints.
  3. Apply methodology_filter to placement_rules.
  4. Collect design_rules: traversed edges whose constraints dict is non-empty
     (i.e. quantitative constraint edges with values/units attached).
  5. Return DesignSubgraph.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from src.knowledge_graph.query.methodology_filter import apply_methodology_filter
from src.schemas.kg import DesignSubgraph, KGEdge, KGNode, KGNodeType

if TYPE_CHECKING:
    from src.knowledge_graph import KnowledgeGraph

logger = logging.getLogger(__name__)


def build_subgraph(
    path_confidences: dict[str, float],
    traversed_edges: list[KGEdge],
    graph: KnowledgeGraph,
    methodology_node: Optional[KGNode],
    design_methodology: str,
    query_depth: int,
) -> DesignSubgraph:
    """Assemble DesignSubgraph from BFS traversal results.

    Args:
        path_confidences: node_id → product path-confidence from bfs_traverse
        traversed_edges: KGEdge list from bfs_traverse
        graph: KnowledgeGraph (used to retrieve node objects)
        methodology_node: Active KG-5 DESIGN_METHODOLOGY node, or None
        design_methodology: String identifier for the active methodology
        query_depth: Traversal depth used (passed through to DesignSubgraph)

    Returns:
        Assembled DesignSubgraph ready for Team C consumption.
    """
    component_types: list[KGNode] = []
    component_instances: list[KGNode] = []
    raw_placement_rules: list[KGNode] = []
    routing_hints: list[KGNode] = []
    topologies: list[KGNode] = []
    functional_blocks: list[KGNode] = []

    # Step 1 + 2: retrieve and categorize every visited node
    for node_id in path_confidences:
        node = graph.get_node(node_id)
        if node is None:
            logger.warning(f"Node {node_id!r} in path_confidences but absent from graph")
            continue

        if node.node_type == KGNodeType.COMPONENT_TYPE:
            component_types.append(node)
        elif node.node_type == KGNodeType.COMPONENT_INSTANCE:
            component_instances.append(node)
        elif node.node_type == KGNodeType.PLACEMENT_RULE:
            raw_placement_rules.append(node)
        elif node.node_type == KGNodeType.ROUTING_RULE:
            routing_hints.append(node)
        elif node.node_type == KGNodeType.TOPOLOGY:
            topologies.append(node)
        elif node.node_type == KGNodeType.FUNCTIONAL_BLOCK:
            functional_blocks.append(node)
        else:
            # PHYSICS_CONCEPT, ELECTRICAL_PROPERTY, DESIGN_RECIPE, etc.
            # silently skipped — they are not part of the DesignSubgraph payload
            logger.debug(
                f"Skipping node {node_id!r} of type {node.node_type} during subgraph assembly"
            )

    # Step 3: apply methodology filter to placement rules
    placement_rules = apply_methodology_filter(raw_placement_rules, methodology_node)

    # Step 4: design_rules = edges that carry quantitative constraint data
    design_rules: list[KGEdge] = [
        edge for edge in traversed_edges if edge.constraints
    ]

    return DesignSubgraph(
        component_types=component_types,
        component_instances=component_instances,
        design_rules=design_rules,
        placement_rules=placement_rules,
        routing_hints=routing_hints,
        topologies=topologies,
        functional_blocks=functional_blocks,
        design_methodology=design_methodology,
        path_confidences=path_confidences,
        query_depth=query_depth,
        query_metadata={},
    )
