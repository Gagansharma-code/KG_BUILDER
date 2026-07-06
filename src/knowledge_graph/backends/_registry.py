"""Knowledge graph backend registry with lazy import and instance caching.

Mirrors src/parsing/backends/_registry.py (BackendRegistry).
"""

from __future__ import annotations

import importlib
import inspect
from typing import TYPE_CHECKING, Any

from src.knowledge_graph.backends._interfaces import GraphBackend
from src.knowledge_graph.backends._schemas import KnowledgeGraphConfig

if TYPE_CHECKING:
    from src.config import Config

GRAPH_BACKEND_REGISTRY: dict[str, str] = {
    "networkx": (
        "src.knowledge_graph.backends.networkx_backend.NetworkXGraphBackend"
    ),
    "neo4j": (
        "src.knowledge_graph.backends.neo4j_backend.Neo4jGraphBackend"
    ),
}


def _load_class(dotted_path: str) -> type:
    """Load a backend class from a fully-qualified module path.

    Args:
        dotted_path: e.g. "src.knowledge_graph.backends.networkx_backend.NetworkXGraphBackend"

    Returns:
        The backend class object.

    Raises:
        ImportError: If the module or class cannot be loaded.
    """
    module_path, class_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    cls: type = getattr(module, class_name)
    return cls


def _validate_backend_name(
    config_key: str,
    backend_name: str,
    registry: dict[str, str],
) -> None:
    """Raise ValueError if backend_name is not in registry."""
    if backend_name not in registry:
        valid = ", ".join(sorted(registry.keys()))
        raise ValueError(
            f"Unknown knowledge_graph.{config_key} backend '{backend_name}'. "
            f"Valid options: {valid}"
        )


def _instantiate_backend(cls: type, config: Config) -> Any:
    """Instantiate a backend class, passing config when required."""
    try:
        init = cls.__init__  # type: ignore[misc]
        params = inspect.signature(init).parameters
    except (TypeError, ValueError):
        return cls(config)
    if "config" in params:
        return cls(config)
    return cls()


class GraphBackendRegistry:
    """Lazy-loading registry for knowledge graph storage backends.

    Validates the backend name from config at construction time.
    Instantiates the backend on first getter call and caches the instance.
    """

    def __init__(self, config: Config) -> None:
        """Initialize registry from application config.

        Args:
            config: Application config with knowledge_graph backend selection.

        Raises:
            ValueError: If the configured backend name is unknown.
        """
        kg_config: KnowledgeGraphConfig = config.knowledge_graph
        _validate_backend_name("backend", kg_config.backend, GRAPH_BACKEND_REGISTRY)

        self._kg_config = kg_config
        self._config = config
        self._graph_backend: GraphBackend | None = None

    def get_graph_backend(self) -> GraphBackend:
        """Return the configured graph backend (cached)."""
        if self._graph_backend is not None:
            return self._graph_backend
        dotted_path = GRAPH_BACKEND_REGISTRY[self._kg_config.backend]
        cls = _load_class(dotted_path)
        self._graph_backend = _instantiate_backend(cls, self._config)
        return self._graph_backend
