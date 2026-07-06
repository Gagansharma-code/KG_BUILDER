"""Neo4j implementation of GraphBackend.

Provides self-hosted Neo4j storage while preserving the GraphBackend method
contracts and GraphML backup/export behavior of the default NetworkX backend.
The neo4j driver is imported lazily in __init__ so NetworkX-only deployments
do not require the driver to be importable at package load time.
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Optional

from src.knowledge_graph.backends._graphml_io import read_graphml, write_graphml
from src.knowledge_graph.backends._interfaces import GraphBackend, NodeNotFoundError
from src.knowledge_graph.backends._schemas import KnowledgeGraphConfig
from src.schemas.kg import KGEdge, KGNode, KGNodeType

if TYPE_CHECKING:
    from src.config import Config
    from src.schemas.kg import KGRelation

logger = logging.getLogger(__name__)

_BATCH_SIZE = 1000


class Neo4jGraphBackend(GraphBackend):
    """Neo4j storage backend for the knowledge graph.

    Example:
        >>> kg = Neo4jGraphBackend(config)
        >>> kg.add_node(node)
        >>> kg.add_edge(edge)
        >>> neighbors = kg.get_neighbors("component:tps62933")
        >>> kg.save(Path("graph.graphml"))
    """

    def __init__(self, config: Config) -> None:
        """Initialize Neo4j driver and idempotent schema constraints/indexes."""
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:
            raise ImportError(
                "neo4j is required for Neo4jGraphBackend. "
                "Install with: pip install neo4j"
            ) from exc

        kg_config = config.knowledge_graph
        default_kg_config = KnowledgeGraphConfig()
        neo4j_uri = kg_config.neo4j_uri
        legacy_uri = getattr(config, "neo4j_uri", None)
        if legacy_uri and neo4j_uri == default_kg_config.neo4j_uri:
            neo4j_uri = legacy_uri
        self._database = kg_config.neo4j_database

        username = (
            os.getenv("OPENFORGE_NEO4J_USER")
            or os.getenv("OPENFORGE_NEO4J_USERNAME")
            or kg_config.neo4j_username
        )
        password = os.getenv("OPENFORGE_NEO4J_PASSWORD") or kg_config.neo4j_password
        auth = (username, password) if username and password else None
        self._driver = GraphDatabase.driver(neo4j_uri, auth=auth)
        self._ensure_schema()

    def add_node(self, node: KGNode) -> None:
        """Add node to graph. If node_id already exists, update its properties.

        Never raises on duplicate — silently updates existing node.

        Args:
            node: KGNode to add to the graph

        Example:
            >>> node = KGNode(id="type:regulator", ...)
            >>> kg.add_node(node)
        """
        label = _node_label(node.node_type)
        query = f"""
        MERGE (n:KGNode {{id: $id}})
        SET n = $props
        REMOVE n:{_all_type_labels()}
        SET n:{label}
        RETURN n.id AS id
        """
        with self._session() as session:
            session.run(query, {"id": node.id, "props": _node_props(node)})
        logger.debug(f"Added/updated node: {node.id}")

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
        with self._session() as session:
            session.execute_write(self._add_edge_tx, edge)
        logger.debug(f"Added edge: {edge.source_id} -> {edge.target_id}")

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
        query = "MATCH (n:KGNode {id: $node_id}) RETURN n"
        with self._session() as session:
            data = _single_data(session.run(query, {"node_id": node_id}))
        if data is None:
            return None
        return _node_from_record(data["n"])

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
        query = """
        MATCH (s:KGNode {id: $node_id})-[r]->(t:KGNode)
        WHERE ($relation IS NULL OR r.relation = $relation)
          AND r.confidence >= $min_confidence
        RETURN s.id AS source_id, r, t.id AS target_id
        """
        params = {
            "node_id": node_id,
            "relation": relation.value if relation is not None else None,
            "min_confidence": min_confidence,
        }
        with self._session() as session:
            return [_edge_from_record(_record_data(record)) for record in session.run(query, params)]

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
        query = """
        MATCH (s:KGNode)-[r]->(t:KGNode {id: $node_id})
        WHERE ($relation IS NULL OR r.relation = $relation)
        RETURN s.id AS source_id, r, t.id AS target_id
        """
        params = {
            "node_id": node_id,
            "relation": relation.value if relation is not None else None,
        }
        with self._session() as session:
            return [_edge_from_record(_record_data(record)) for record in session.run(query, params)]

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
        query = """
        MATCH (s:KGNode {id: $node_id})-[r]->(t:KGNode)
        WHERE ($relation IS NULL OR r.relation = $relation)
          AND r.confidence >= $min_confidence
        RETURN t
        """
        params = {
            "node_id": node_id,
            "relation": relation.value if relation is not None else None,
            "min_confidence": min_confidence,
        }
        with self._session() as session:
            return [_node_from_record(_record_data(record)["t"]) for record in session.run(query, params)]

    def node_exists(self, node_id: str) -> bool:
        """Return True if node_id in graph.

        Args:
            node_id: Node ID to check

        Returns:
            True if node exists, False otherwise
        """
        query = "MATCH (n:KGNode {id: $node_id}) RETURN count(n) > 0 AS exists"
        with self._session() as session:
            data = _single_data(session.run(query, {"node_id": node_id}))
        return bool(data and data["exists"])

    def find_nodes_by_type(self, node_type: KGNodeType) -> list[KGNode]:
        """Return all nodes matching the given node_type.

        Args:
            node_type: KGNodeType to filter by

        Returns:
            List of KGNode objects with matching node_type
        """
        query = "MATCH (n:KGNode) WHERE n.node_type = $node_type RETURN n"
        with self._session() as session:
            return [
                _node_from_record(_record_data(record)["n"])
                for record in session.run(query, {"node_type": node_type.value})
            ]

    def find_nodes_by_layer(self, layer: int) -> list[KGNode]:
        """Return all nodes in the specified KG layer (1-5).

        Args:
            layer: Layer number (1-5)

        Returns:
            List of KGNode objects in the specified layer
        """
        query = "MATCH (n:KGNode) WHERE n.layer = $layer RETURN n"
        with self._session() as session:
            return [
                _node_from_record(_record_data(record)["n"])
                for record in session.run(query, {"layer": layer})
            ]

    def save(self, path: Path) -> None:
        """Serialize graph to GraphML file at path.

        KGNode and KGEdge objects are JSON-serialized into GraphML
        node/edge attributes under the 'data' key.

        Args:
            path: Path to write the GraphML file

        Example:
            >>> kg.save(Path("output/graph.graphml"))
        """
        nodes_query = "MATCH (n:KGNode) RETURN n"
        edges_query = """
        MATCH (s:KGNode)-[r]->(t:KGNode)
        RETURN s.id AS source_id, r, t.id AS target_id
        """
        with self._session() as session:
            nodes = [
                _node_from_record(_record_data(record)["n"])
                for record in session.run(nodes_query)
            ]
            edges = [
                _edge_from_record(_record_data(record))
                for record in session.run(edges_query)
            ]
        write_graphml(path, nodes, edges)
        logger.info(f"Saved graph with {len(nodes)} nodes to {path}")

    def load_into(self, path: Path) -> None:
        """Populate this instance from a GraphML file.

        Reconstructs KGNode and KGEdge objects from JSON attributes.

        Args:
            path: Path to the GraphML file

        Raises:
            FileNotFoundError: If path does not exist
        """
        nodes, edges = read_graphml(path)
        with self._session() as session:
            for label, node_batch in _grouped_node_batches(nodes):
                query = f"""
                UNWIND $nodes AS row
                MERGE (n:KGNode {{id: row.id}})
                SET n = row.props
                REMOVE n:{_all_type_labels()}
                SET n:{label}
                """
                session.run(query, {"nodes": node_batch})
            for rel_type, edge_batch in _grouped_edge_batches(edges):
                query = f"""
                UNWIND $edges AS row
                MATCH (s:KGNode {{id: row.source_id}}), (t:KGNode {{id: row.target_id}})
                OPTIONAL MATCH (s)-[existing]->(t)
                DELETE existing
                CREATE (s)-[r:{rel_type}]->(t)
                SET r = row.props
                """
                session.run(query, {"edges": edge_batch})
        logger.info(f"Loaded graph with {len(nodes)} nodes and {len(edges)} edges from {path}")

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
        node_query = """
        MATCH (n:KGNode)
        RETURN n.layer AS layer, count(n) AS node_count
        """
        edge_query = """
        MATCH (:KGNode)-[r]->(:KGNode)
        RETURN r.layer AS layer, count(r) AS edge_count
        """
        stats = {"node_count": 0, "edge_count": 0}
        for layer in range(1, 6):
            stats[f"nodes_layer_{layer}"] = 0
            stats[f"edges_layer_{layer}"] = 0

        with self._session() as session:
            for record in session.run(node_query):
                data = _record_data(record)
                layer = data["layer"]
                count = data["node_count"]
                stats["node_count"] += count
                stats[f"nodes_layer_{layer}"] = count
            for record in session.run(edge_query):
                data = _record_data(record)
                layer = data["layer"]
                count = data["edge_count"]
                stats["edge_count"] += count
                stats[f"edges_layer_{layer}"] = count
        return stats

    def _session(self):
        """Return a driver session, using the configured database when set."""
        if self._database:
            return self._driver.session(database=self._database)
        return self._driver.session()

    def _ensure_schema(self) -> None:
        """Create Community-edition-compatible constraints/indexes."""
        schema_queries = [
            """
            CREATE CONSTRAINT kgnode_id IF NOT EXISTS
            FOR (n:KGNode) REQUIRE n.id IS UNIQUE
            """,
            """
            CREATE INDEX kgnode_layer IF NOT EXISTS
            FOR (n:KGNode) ON (n.layer)
            """,
            """
            CREATE INDEX kgnode_node_type IF NOT EXISTS
            FOR (n:KGNode) ON (n.node_type)
            """,
            """
            CREATE TEXT INDEX kgnode_label IF NOT EXISTS
            FOR (n:KGNode) ON (n.label)
            """,
        ]
        with self._session() as session:
            for query in schema_queries:
                session.run(query)

    @staticmethod
    def _add_edge_tx(tx: Any, edge: KGEdge) -> None:
        for field_name, node_id in (
            ("source_id", edge.source_id),
            ("target_id", edge.target_id),
        ):
            query = f"MATCH (s:KGNode {{id: ${field_name}}}) RETURN count(s) AS found"
            data = _single_data(tx.run(query, {field_name: node_id}))
            if data is None or data["found"] == 0:
                raise NodeNotFoundError(node_id)

        # Deliberately delete any existing source->target relationship before
        # creating the new one to match NetworkX DiGraph's single-edge-per-pair
        # overwrite semantics. Parallel edges would be a separate future choice.
        delete_query = """
        MATCH (s:KGNode {id: $source_id})-[r]->(t:KGNode {id: $target_id})
        DELETE r
        """
        create_query = f"""
        MATCH (s:KGNode {{id: $source_id}}), (t:KGNode {{id: $target_id}})
        CREATE (s)-[r:{_relationship_type(edge.relation)} $props]->(t)
        """
        tx.run(delete_query, {"source_id": edge.source_id, "target_id": edge.target_id})
        tx.run(
            create_query,
            source_id=edge.source_id,
            target_id=edge.target_id,
            props=_edge_props(edge),
        )


def _node_label(node_type: KGNodeType) -> str:
    return "".join(word.capitalize() for word in node_type.value.split("_"))


def _all_type_labels() -> str:
    return ":".join(_node_label(node_type) for node_type in KGNodeType)


def _relationship_type(relation: KGRelation) -> str:
    return relation.value.upper()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def _node_props(node: KGNode) -> dict[str, Any]:
    props = node.model_dump(mode="json")
    nested_props = props.pop("properties")
    props["properties_json"] = _json_dumps(nested_props)
    props["frequency_hz"] = nested_props.get("frequency_hz")
    props["prop_component_type"] = nested_props.get("component_type")
    return props


def _edge_props(edge: KGEdge) -> dict[str, Any]:
    props = edge.model_dump(mode="json")
    props.pop("source_id")
    props.pop("target_id")
    constraints = props.pop("constraints")
    props["constraints_json"] = _json_dumps(constraints)
    return props


def _node_from_record(raw: Any) -> KGNode:
    data = dict(raw)
    properties_json = data.pop("properties_json", "{}")
    data["properties"] = json.loads(properties_json or "{}")
    data.pop("frequency_hz", None)
    data.pop("prop_component_type", None)
    return KGNode.model_validate(data)


def _edge_from_record(data: dict[str, Any]) -> KGEdge:
    rel_props = dict(data["r"])
    constraints_json = rel_props.pop("constraints_json", "{}")
    rel_props["constraints"] = json.loads(constraints_json or "{}")
    rel_props["source_id"] = data["source_id"]
    rel_props["target_id"] = data["target_id"]
    return KGEdge.model_validate(rel_props)


def _record_data(record: Any) -> dict[str, Any]:
    """Map record keys to their raw values (Node/Relationship/scalar).

    Deliberately not record.data(): the driver's .data() flattens
    Relationship values into a (start_props, type, end_props) tuple,
    discarding the relationship's own properties, which breaks
    _edge_from_record's dict(data["r"]) call. dict(record) preserves the
    raw Node/Relationship objects, which themselves support dict() to
    yield their properties correctly.
    """
    return dict(record)


def _single_data(result: Iterable[Any]) -> dict[str, Any] | None:
    if hasattr(result, "single"):
        record = result.single()
        return _record_data(record) if record is not None else None
    for record in result:
        return _record_data(record)
    return None


def _batched(items: list[dict[str, Any]]) -> Iterable[list[dict[str, Any]]]:
    for index in range(0, len(items), _BATCH_SIZE):
        yield items[index : index + _BATCH_SIZE]


def _grouped_node_batches(
    nodes: Iterable[KGNode],
) -> Iterable[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        grouped[_node_label(node.node_type)].append(
            {"id": node.id, "props": _node_props(node)}
        )
    for label, rows in grouped.items():
        for batch in _batched(rows):
            yield label, batch


def _grouped_edge_batches(
    edges: Iterable[KGEdge],
) -> Iterable[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        grouped[_relationship_type(edge.relation)].append(
            {
                "source_id": edge.source_id,
                "target_id": edge.target_id,
                "props": _edge_props(edge),
            }
        )
    for rel_type, rows in grouped.items():
        for batch in _batched(rows):
            yield rel_type, batch
