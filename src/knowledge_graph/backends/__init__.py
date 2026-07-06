"""Pluggable storage backends for the knowledge graph.

Public API:
    GraphBackend            — abstract interface (see _interfaces.py)
    NodeNotFoundError       — raised by add_edge for missing endpoints
    NetworkXGraphBackend    — default in-memory/GraphML implementation
    GraphBackendRegistry    — config-driven backend selection
    KnowledgeGraphConfig    — config sub-model (knowledge_graph.*)

Example:
    >>> from src.knowledge_graph.backends import GraphBackendRegistry
    >>> from src.config import get_config
    >>> registry = GraphBackendRegistry(get_config())
    >>> graph = registry.get_graph_backend()
"""

from src.knowledge_graph.backends._interfaces import GraphBackend, NodeNotFoundError
from src.knowledge_graph.backends._registry import (
    GRAPH_BACKEND_REGISTRY,
    GraphBackendRegistry,
)
from src.knowledge_graph.backends._schemas import KnowledgeGraphConfig
from src.knowledge_graph.backends.networkx_backend import NetworkXGraphBackend

__all__ = [
    "GraphBackend",
    "NodeNotFoundError",
    "NetworkXGraphBackend",
    "GraphBackendRegistry",
    "GRAPH_BACKEND_REGISTRY",
    "KnowledgeGraphConfig",
]
