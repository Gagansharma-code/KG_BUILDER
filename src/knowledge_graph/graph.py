"""KnowledgeGraph — the default knowledge graph storage class.

The implementation now lives in src/knowledge_graph/backends/ behind the
GraphBackend interface (see backends/_interfaces.py). KnowledgeGraph is the
NetworkX-backed default and remains the class every existing caller uses;
its public API and behavior are unchanged.

To select a backend via config instead of constructing KnowledgeGraph
directly, use:

    >>> from src.knowledge_graph.backends import GraphBackendRegistry
    >>> graph = GraphBackendRegistry(config).get_graph_backend()

with config key knowledge_graph.backend (default: "networkx").
"""

from __future__ import annotations

from src.knowledge_graph.backends._interfaces import NodeNotFoundError
from src.knowledge_graph.backends.networkx_backend import NetworkXGraphBackend

__all__ = ["KnowledgeGraph", "NodeNotFoundError"]


class KnowledgeGraph(NetworkXGraphBackend):
    """NetworkX-backed knowledge graph (default backend).

    Behavior-identical subclass of NetworkXGraphBackend, kept so that all
    existing imports (`from src.knowledge_graph import KnowledgeGraph`) and
    isinstance checks continue to work unchanged.
    """
