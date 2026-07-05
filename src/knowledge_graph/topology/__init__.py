"""Formal topology layer — parameterized circuit patterns in the KG.

Public API:
    install_topologies(graph) -> int
    link_component_implements(graph, component_node_id, topology_slug)
    ScalingLaw, SCALING_LAWS_KEY
    TOPOLOGY_SLUGS
"""

from src.knowledge_graph.topology._schemas import SCALING_LAWS_KEY, ScalingLaw
from src.knowledge_graph.topology.library import (
    TOPOLOGY_SLUGS,
    install_topologies,
    link_component_implements,
)

__all__ = [
    "ScalingLaw",
    "SCALING_LAWS_KEY",
    "TOPOLOGY_SLUGS",
    "install_topologies",
    "link_component_implements",
]
