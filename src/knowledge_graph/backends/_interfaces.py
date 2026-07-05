"""Abstract base class for pluggable knowledge graph storage backends.

Mirrors the pattern established by src/parsing/backends/_interfaces.py:
one interface, multiple swappable implementations, selected via a config key
(knowledge_graph.backend).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from src.schemas.kg import KGEdge, KGNode, KGNodeType, KGRelation


class NodeNotFoundError(Exception):
    """Raised when a referenced node does not exist in the graph.

    Attributes:
        node_id: The ID of the missing node that was referenced
    """

    def __init__(self, node_id: str):
        """Initialize with the missing node ID."""
        self.node_id = node_id
        super().__init__(f"Node '{node_id}' does not exist in graph")


class GraphBackend(ABC):
    """Storage backend for the knowledge graph.

    All node/edge payloads are the canonical KGNode/KGEdge Pydantic models
    from src.schemas.kg — backends must not define their own node schema.
    Implementations must be usable interchangeably by every current caller
    of KnowledgeGraph (query engine, ingestion, importers, admin, search).
    """

    @abstractmethod
    def add_node(self, node: KGNode) -> None:
        """Add node to graph. If node.id already exists, update it in place.

        Never raises on duplicate — silently upserts.
        """

    @abstractmethod
    def add_edge(self, edge: KGEdge) -> None:
        """Add directed edge. source_id and target_id must exist as nodes.

        Raises:
            NodeNotFoundError: If source_id or target_id does not exist.
        """

    @abstractmethod
    def get_node(self, node_id: str) -> Optional[KGNode]:
        """Return KGNode if exists, None otherwise. Never raises."""

    @abstractmethod
    def get_edges_from(
        self,
        node_id: str,
        relation: Optional[KGRelation] = None,
        min_confidence: float = 0.0,
    ) -> list[KGEdge]:
        """Return outgoing edges from node_id, optionally filtered by
        relation type and minimum confidence (inclusive).

        Returns empty list for unknown node_id — never raises.
        """

    @abstractmethod
    def get_edges_to(
        self,
        node_id: str,
        relation: Optional[KGRelation] = None,
    ) -> list[KGEdge]:
        """Return incoming edges to node_id, optionally filtered by relation.

        Returns empty list for unknown node_id — never raises.
        """

    @abstractmethod
    def get_neighbors(
        self,
        node_id: str,
        relation: Optional[KGRelation] = None,
        min_confidence: float = 0.0,
    ) -> list[KGNode]:
        """Return KGNode objects reachable from node_id via outgoing edges,
        with optional relation and confidence filters.
        """

    @abstractmethod
    def node_exists(self, node_id: str) -> bool:
        """Return True if node_id is present in the graph."""

    @abstractmethod
    def find_nodes_by_type(self, node_type: KGNodeType) -> list[KGNode]:
        """Return all nodes matching node_type.

        Must accept any KGNodeType member, including ones added after this
        backend was written — implementations must not hardcode the set of
        known types.
        """

    @abstractmethod
    def find_nodes_by_layer(self, layer: int) -> list[KGNode]:
        """Return all nodes in the specified KG layer."""

    @abstractmethod
    def save(self, path: Path) -> None:
        """Persist the graph to path (format is backend-specific)."""

    @abstractmethod
    def load_into(self, path: Path) -> None:
        """Populate this (empty) backend instance from persisted data at path.

        Raises:
            FileNotFoundError: If path does not exist.
        """

    @abstractmethod
    def stats(self) -> dict[str, int]:
        """Return graph statistics: node_count, edge_count, and per-layer
        counts (nodes_layer_N / edges_layer_N for layers 1-5).
        """
