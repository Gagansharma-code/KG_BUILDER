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

from pathlib import Path

from src.knowledge_graph.backends._interfaces import NodeNotFoundError
from src.knowledge_graph.backends.networkx_backend import NetworkXGraphBackend

__all__ = ["KnowledgeGraph", "NodeNotFoundError"]


class KnowledgeGraph(NetworkXGraphBackend):
    """NetworkX-backed knowledge graph (default backend).

    Behavior-identical subclass of NetworkXGraphBackend, kept so that all
    existing imports (`from src.knowledge_graph import KnowledgeGraph`) and
    isinstance checks continue to work unchanged.
    """

    def __init__(self) -> None:
        """Initialize graph and install formal topology layer (idempotent)."""
        super().__init__()
        from src.knowledge_graph.topology.library import install_topologies

        install_topologies(self)

    @classmethod
    def load(cls, path: Path) -> "KnowledgeGraph":
        """Load GraphML then ensure topology layer is present (idempotent)."""
        kg = cls.__new__(cls)
        NetworkXGraphBackend.__init__(kg)
        kg.load_into(path)
        from src.knowledge_graph.topology.library import install_topologies

        install_topologies(kg)
        return kg
