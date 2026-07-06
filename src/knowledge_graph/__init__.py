"""Knowledge Graph package for Team B.

Provides a NetworkX DiGraph wrapper (GraphML-serialized) for storing and
querying the knowledge graph, plus the primary query engine used by Team C.
Storage is pluggable via src.knowledge_graph.backends.GraphBackendRegistry;
NetworkX remains the default backend, with Neo4j available for self-hosted
deployments.

Public API:
    KnowledgeGraph: NetworkX DiGraph wrapper for KG nodes and edges
    NodeNotFoundError: Raised when a referenced node does not exist
    query_graph(intent, graph, config) -> DesignSubgraph
    build_search_index(graph, index_path, config) -> int
    search_components(query, graph, index_path, ...) -> list[ComponentSearchResult]

Example:
    >>> from src.knowledge_graph import KnowledgeGraph, query_graph
    >>> kg = KnowledgeGraph()
    >>> kg.add_node(node)
    >>> kg.add_edge(edge)
    >>> subgraph = query_graph(intent, kg, config)
    >>>
    >>> # Semantic search
    >>> from src.knowledge_graph import build_search_index, search_components
    >>> count = build_search_index(kg, Path("index.faiss"), config)
    >>> results = search_components("3.3V LDO", kg, Path("index.faiss"), config=config)
"""

from __future__ import annotations

from src.knowledge_graph.graph import KnowledgeGraph, NodeNotFoundError
from src.knowledge_graph.query import query_graph
from src.knowledge_graph.semantic_search import (
    build_search_index,
    search_components,
)

__all__ = [
    "KnowledgeGraph",
    "NodeNotFoundError",
    "query_graph",
    "build_search_index",
    "search_components",
]
