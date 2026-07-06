"""NetworkX DiGraph implementation of GraphBackend.

Provides local GraphML-based storage. All nodes stored as KGNode objects
under node attr 'data'; edges as KGEdge objects under edge attr 'data'.
Node keys in NetworkX = KGNode.id (string).

This is the code formerly in src/knowledge_graph/graph.py, unchanged in
behavior, now implementing the GraphBackend interface.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from src.knowledge_graph.backends._graphml_io import read_graphml, write_graphml
from src.knowledge_graph.backends._interfaces import GraphBackend, NodeNotFoundError
from src.schemas.kg import KGEdge, KGNode, KGNodeType

if TYPE_CHECKING:
    from src.schemas.kg import KGRelation

logger = logging.getLogger(__name__)


class NetworkXGraphBackend(GraphBackend):
    """NetworkX DiGraph storage backend for the knowledge graph.

    Example:
        >>> kg = NetworkXGraphBackend()
        >>> kg.add_node(node)
        >>> kg.add_edge(edge)
        >>> neighbors = kg.get_neighbors("component:tps62933")
        >>> kg.save(Path("graph.graphml"))
        >>> loaded = NetworkXGraphBackend.load(Path("graph.graphml"))
    """

    def __init__(self) -> None:
        """Initialize empty directed graph."""
        try:
            import networkx as nx
        except ImportError:
            raise ImportError(
                "networkx is required for KnowledgeGraph. "
                "Install with: pip install networkx"
            )
        self._graph = nx.DiGraph()

    def add_node(self, node: KGNode) -> None:
        """Add node to graph. If node_id already exists, update its properties.

        Never raises on duplicate — silently updates existing node.

        Args:
            node: KGNode to add to the graph

        Example:
            >>> node = KGNode(id="type:regulator", ...)
            >>> kg.add_node(node)
        """
        node_id = node.id
        self._graph.add_node(node_id, data=node)
        logger.debug(f"Added/updated node: {node_id}")

    def add_edge(self, edge: KGEdge) -> None:
        """Add directed edge. source_id and target_id must exist as nodes.

        Args:
            edge: KGEdge to add to the graph

        Raises:
            NodeNotFoundError: If source_id or target_id does not exist

        Example:
            >>> edge = KGEdge(
            ...     source_id="type:regulator",
            ...     relation=KGRelation.REQUIRES,
            ...     target_id="type:capacitor",
            ...     ...
            ... )
            >>> kg.add_edge(edge)
        """
        source_id = edge.source_id
        target_id = edge.target_id

        # Validate nodes exist
        if not self.node_exists(source_id):
            raise NodeNotFoundError(source_id)
        if not self.node_exists(target_id):
            raise NodeNotFoundError(target_id)

        self._graph.add_edge(source_id, target_id, data=edge)
        logger.debug(f"Added edge: {source_id} -> {target_id}")

    def get_node(self, node_id: str) -> Optional[KGNode]:
        """Return KGNode if exists, None otherwise. Never raises.

        Args:
            node_id: ID of the node to retrieve

        Returns:
            KGNode if found, None otherwise

        Example:
            >>> node = kg.get_node("type:regulator")
            >>> if node:
            ...     print(node.label)
        """
        if node_id not in self._graph:
            return None
        data = self._graph.nodes[node_id].get("data")
        if isinstance(data, KGNode):
            return data
        return None

    def get_edges_from(
        self,
        node_id: str,
        relation: Optional[KGRelation] = None,
        min_confidence: float = 0.0,
    ) -> list[KGEdge]:
        """Return all outgoing edges from node_id.

        Args:
            node_id: Source node ID
            relation: Optional filter by relation type
            min_confidence: Minimum confidence threshold (inclusive)

        Returns:
            List of KGEdge objects matching the criteria

        Example:
            >>> edges = kg.get_edges_from(
            ...     "type:regulator",
            ...     relation=KGRelation.REQUIRES,
            ...     min_confidence=0.8
            ... )
        """
        if node_id not in self._graph:
            return []

        edges = []
        for _, target, data in self._graph.out_edges(node_id, data=True):
            edge = data.get("data")
            if edge is None:
                continue

            # Filter by relation
            if relation is not None and edge.relation != relation:
                continue

            # Filter by confidence
            if edge.confidence < min_confidence:
                continue

            edges.append(edge)

        return edges

    def get_edges_to(
        self,
        node_id: str,
        relation: Optional[KGRelation] = None,
    ) -> list[KGEdge]:
        """Return all incoming edges to node_id.

        Args:
            node_id: Target node ID
            relation: Optional filter by relation type

        Returns:
            List of KGEdge objects pointing to this node

        Example:
            >>> edges = kg.get_edges_to("type:capacitor")
        """
        if node_id not in self._graph:
            return []

        edges = []
        for source, _, data in self._graph.in_edges(node_id, data=True):
            edge = data.get("data")
            if edge is None:
                continue

            # Filter by relation
            if relation is not None and edge.relation != relation:
                continue

            edges.append(edge)

        return edges

    def get_neighbors(
        self,
        node_id: str,
        relation: Optional[KGRelation] = None,
        min_confidence: float = 0.0,
    ) -> list[KGNode]:
        """Return KGNode objects for all nodes reachable from node_id via outgoing edges.

        Args:
            node_id: Source node ID
            relation: Optional filter by relation type
            min_confidence: Minimum confidence threshold for edges

        Returns:
            List of KGNode objects that are neighbors of node_id

        Example:
            >>> neighbors = kg.get_neighbors(
            ...     "type:regulator",
            ...     relation=KGRelation.REQUIRES,
            ...     min_confidence=0.9
            ... )
        """
        edges = self.get_edges_from(node_id, relation, min_confidence)
        neighbors = []

        for edge in edges:
            neighbor = self.get_node(edge.target_id)
            if neighbor is not None:
                neighbors.append(neighbor)

        return neighbors

    def node_exists(self, node_id: str) -> bool:
        """Return True if node_id in graph.

        Args:
            node_id: Node ID to check

        Returns:
            True if node exists, False otherwise
        """
        return node_id in self._graph

    def find_nodes_by_type(self, node_type: KGNodeType) -> list[KGNode]:
        """Return all nodes matching the given node_type.

        Args:
            node_type: KGNodeType to filter by

        Returns:
            List of KGNode objects with matching node_type
        """
        nodes: list[KGNode] = []
        for node_id in self._graph.nodes:
            node = self.get_node(node_id)
            if node is not None and node.node_type == node_type:
                nodes.append(node)
        return nodes

    def find_nodes_by_layer(self, layer: int) -> list[KGNode]:
        """Return all nodes in the specified KG layer (1-5).

        Args:
            layer: Layer number (1-5)

        Returns:
            List of KGNode objects in the specified layer
        """
        nodes = []
        for node_id in self._graph.nodes:
            node = self.get_node(node_id)
            if node is not None and node.layer == layer:
                nodes.append(node)
        return nodes

    def save(self, path: Path) -> None:
        """Serialize graph to GraphML file at path.

        KGNode and KGEdge objects are JSON-serialized into GraphML
        node/edge attributes under the 'data' key.

        Args:
            path: Path to write the GraphML file

        Example:
            >>> kg.save(Path("output/graph.graphml"))
        """
        nodes = [
            self._graph.nodes[node_id].get("data")
            for node_id in self._graph.nodes
            if self._graph.nodes[node_id].get("data")
        ]
        edges = [
            edge_data.get("data")
            for _, _, edge_data in self._graph.edges(data=True)
            if edge_data.get("data")
        ]
        write_graphml(path, nodes, edges)
        logger.info(f"Saved graph with {len(self._graph.nodes)} nodes to {path}")

    def load_into(self, path: Path) -> None:
        """Populate this instance from a GraphML file.

        Reconstructs KGNode and KGEdge objects from JSON attributes.

        Args:
            path: Path to the GraphML file

        Raises:
            FileNotFoundError: If path does not exist
        """
        nodes, edges = read_graphml(path)
        for node in nodes:
            self._graph.add_node(node.id, data=node)
        for edge in edges:
            self._graph.add_edge(edge.source_id, edge.target_id, data=edge)

        logger.info(
            f"Loaded graph with {len(self._graph.nodes)} nodes "
            f"and {len(self._graph.edges)} edges from {path}"
        )

    @classmethod
    def load(cls, path: Path) -> "NetworkXGraphBackend":
        """Deserialize graph from GraphML file.

        Args:
            path: Path to the GraphML file

        Returns:
            New backend instance with reconstructed nodes and edges

        Raises:
            FileNotFoundError: If path does not exist
            ImportError: If networkx is not installed

        Example:
            >>> kg = NetworkXGraphBackend.load(Path("input/graph.graphml"))
        """
        kg = cls()
        kg.load_into(path)
        return kg

    def stats(self) -> dict[str, int]:
        """Return graph statistics.

        Returns:
            Dict with keys:
            - node_count: Total number of nodes
            - edge_count: Total number of edges
            - nodes_layer_1..5: Node counts per layer
            - edges_layer_1..5: Edge counts per layer

        Example:
            >>> stats = kg.stats()
            >>> print(f"Nodes: {stats['node_count']}")
        """
        stats = {
            "node_count": len(self._graph.nodes),
            "edge_count": len(self._graph.edges),
        }

        # Count nodes per layer
        for layer in range(1, 6):
            layer_nodes = self.find_nodes_by_layer(layer)
            stats[f"nodes_layer_{layer}"] = len(layer_nodes)

        # Count edges per layer
        for layer in range(1, 6):
            layer_edges = [
                self._graph.edges[edge].get("data")
                for edge in self._graph.edges
                if self._graph.edges[edge].get("data")
                and self._graph.edges[edge]["data"].layer == layer
            ]
            stats[f"edges_layer_{layer}"] = len(layer_edges)

        return stats
