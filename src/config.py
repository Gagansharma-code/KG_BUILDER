"""Configuration management for OpenForge PCB Builder.

This module provides a centralized configuration system using Pydantic Settings.
Configuration values are loaded from:
1. Environment variables (highest priority, prefixed with OPENFORGE_)
2. configs/default.yaml file
3. Default values defined in the schema (lowest priority)

All paths are resolved as absolute pathlib.Path objects for consistency.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.parsing.backends._schemas import ParsingConfig


class Config(BaseSettings):
    """Root configuration class for OpenForge PCB Builder.

    This class serves as the single source of truth for all application settings.
    It loads configuration from YAML files and environment variables, with
    environment variables taking precedence.

    Attributes:
        model_paths: Dictionary mapping model names to their file system paths.
            Contains paths for Qwen LLMs, YOLO detection models, and SAM variants.
        corpus_dir: Root directory containing golden and test datasets.
        output_dir: Directory for all generated outputs (schematics, layouts, reports).
        confidence_thresholds: Thresholds for triggering human review at various stages.
        review_queue_path: File path for the JSON review queue.
        neo4j_uri: Connection URI for the Neo4j knowledge graph database.
        log_level: Python logging level (DEBUG, INFO, WARNING, ERROR).

    Example:
        >>> from src.config import Config
        >>> config = Config.from_yaml("configs/default.yaml")
        >>> print(config.corpus_dir)
        PosixPath('/absolute/path/to/corpus')
        >>> print(config.confidence_thresholds["bom_total"])
        0.95
    """

    model_config = SettingsConfigDict(
        env_prefix="OPENFORGE_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    model_paths: dict[str, Path] = Field(
        default_factory=lambda: {
            "qwen25_7b": Path("models/Qwen2.5-7B-Instruct"),
            "qwen2_vl_7b": Path("models/Qwen2-VL-7B-Instruct"),
            "yolov8n_doclaynet": Path("models/yolov8_doclaynets.pt"),
            "locateanything_3b": Path("models/locateanything-3b"),
        },
        description="Mapping of model identifiers to filesystem paths",
    )

    corpus_dir: Path = Field(
        default=Path("corpus"),
        description="Root directory for golden and test datasets",
    )

    output_dir: Path = Field(
        default=Path("output"),
        description="Directory for all generated outputs",
    )

    confidence_thresholds: dict[str, float] = Field(
        default_factory=lambda: {
            "bom_total": 0.95,
            "bom_component": 0.90,
            "pin_normalization": 0.85,
        },
        description="Confidence thresholds for triggering human review",
    )

    review_queue_path: Path = Field(
        default=Path("output/review_queue.json"),
        description="Path to the JSON review queue file",
    )

    neo4j_uri: str = Field(
        default="bolt://localhost:7687",
        description="Neo4j knowledge graph connection URI",
    )

    graph_path: Path = Field(
        default=Path("output/knowledge_graph.graphml"),
        description="Path to the GraphML knowledge graph file",
    )

    supplier_cache_path: Path = Field(
        default=Path("data/supplier_cache.db"),
        description="Path to the SQLite supplier availability cache",
    )

    canonical_functions_path: Path = Field(
        default=Path("configs/canonical_functions.yaml"),
        description="Path to canonical pin function vocabulary YAML",
    )

    kg_traversal_max_depth: int = Field(
        default=4,
        description="Maximum BFS traversal depth for KG queries",
    )

    kg_min_edge_confidence: float = Field(
        default=0.60,
        ge=0.0,
        le=1.0,
        description="Minimum edge confidence threshold during BFS traversal",
    )

    log_level: str = Field(
        default="INFO",
        description="Python logging level (DEBUG, INFO, WARNING, ERROR)",
    )

    kicad_mcp_url: str = Field(
        default="http://localhost:3000",
        description="KiCad MCP server base URL",
    )

    parsing: ParsingConfig = Field(
        default_factory=ParsingConfig,
        description="Pluggable parsing backend name selections",
    )

    @field_validator("model_paths", mode="before")
    @classmethod
    def _resolve_model_paths(cls, v: Any) -> dict[str, Path]:
        """Ensure all model paths are resolved Path objects.

        Args:
            v: Input value, either a dict of strings/Paths or None.

        Returns:
            Dictionary with all values converted to resolved Path objects.
        """
        if v is None:
            return {}
        return {k: Path(v).resolve() if not Path(v).is_absolute() else Path(v) for k, v in v.items()}

    @field_validator("corpus_dir", "output_dir", "review_queue_path", "graph_path", "supplier_cache_path", "canonical_functions_path", mode="before")
    @classmethod
    def _resolve_path(cls, v: Any) -> Path:
        """Resolve relative paths to absolute paths from project root.

        Args:
            v: Input path as string or Path object.

        Returns:
            Absolute Path object.
        """
        if isinstance(v, str):
            v = Path(v)
        if not v.is_absolute():
            # Resolve relative to project root (where pyproject.toml lives)
            project_root = Path(__file__).parent.parent.resolve()
            v = (project_root / v).resolve()
        return v

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        """Validate that the log level is a recognized Python logging level.

        Args:
            v: Log level string.

        Returns:
            Uppercase log level string.

        Raises:
            ValueError: If the log level is not recognized.
        """
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"Invalid log level: {v}. Must be one of {valid_levels}")
        return v_upper

    @classmethod
    def from_yaml(cls, yaml_path: Path | str) -> "Config":
        """Load configuration from a YAML file with environment variable override.

        This factory method loads configuration values from a YAML file,
        then allows environment variables to override any setting.

        Args:
            yaml_path: Path to the YAML configuration file.

        Returns:
            Config instance with merged settings.

        Raises:
            FileNotFoundError: If the YAML file does not exist.
            ValueError: If the YAML file is malformed.

        Example:
            >>> config = Config.from_yaml("configs/default.yaml")
            >>> print(config.neo4j_uri)
            'bolt://localhost:7687'
        """
        yaml_path = Path(yaml_path)
        if not yaml_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {yaml_path}")

        with open(yaml_path, "r", encoding="utf-8") as f:
            try:
                yaml_data = yaml.safe_load(f) or {}
            except yaml.YAMLError as e:
                raise ValueError(f"Failed to parse YAML configuration: {e}") from e

        # Convert snake_case YAML keys to match field names
        config_data = {}
        field_mapping = {
            "model_paths": "model_paths",
            "corpus_dir": "corpus_dir",
            "output_dir": "output_dir",
            "confidence_thresholds": "confidence_thresholds",
            "review_queue_path": "review_queue_path",
            "neo4j_uri": "neo4j_uri",
            "graph_path": "graph_path",
            "kg_traversal_max_depth": "kg_traversal_max_depth",
            "kg_min_edge_confidence": "kg_min_edge_confidence",
            "log_level": "log_level",
            "supplier_cache_path": "supplier_cache_path",
            "canonical_functions_path": "canonical_functions_path",
            "kicad_mcp_url": "kicad_mcp_url",
            "parsing": "parsing",
        }

        for yaml_key, field_name in field_mapping.items():
            if yaml_key in yaml_data:
                config_data[field_name] = yaml_data[yaml_key]

        return cls(**config_data)

    def get_model_path(self, model_name: str) -> Path:
        """Get the resolved path for a named model.

        Args:
            model_name: Key in model_paths (e.g., 'qwen25_7b', 'yolov8n_doclaynet').

        Returns:
            Absolute Path to the model.

        Raises:
            KeyError: If the model name is not defined in configuration.
        """
        if model_name not in self.model_paths:
            raise KeyError(f"Model '{model_name}' not found in configuration. "
                          f"Available: {list(self.model_paths.keys())}")
        return self.model_paths[model_name]

    def ensure_directories(self) -> None:
        """Create all configured directories if they don't exist.

        This ensures the corpus, output, and model directories are present
        before the application begins processing.
        """
        self.corpus_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.review_queue_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Ensure model directory exists (parent of model paths)
        for model_path in self.model_paths.values():
            model_path.parent.mkdir(parents=True, exist_ok=True)


# Global config instance (lazy-loaded via get_config)
_config_instance: Config | None = None


def get_config(config_path: Path | str | None = None) -> Config:
    """Get or create the global configuration instance.

    This function provides a singleton-style access to the configuration,
    loading it on first call and returning the cached instance thereafter.

    Args:
        config_path: Optional path to YAML config. Uses 'configs/default.yaml'
            relative to project root if not provided.

    Returns:
        The global Config instance.

    Example:
        >>> from src.config import get_config
        >>> config = get_config()
        >>> print(config.log_level)
        'INFO'
    """
    global _config_instance
    if _config_instance is None:
        if config_path is None:
            project_root = Path(__file__).parent.parent.resolve()
            config_path = project_root / "configs" / "default.yaml"
        _config_instance = Config.from_yaml(config_path)
    return _config_instance


def reset_config() -> None:
    """Reset the global configuration instance.

    This is primarily useful for testing scenarios where a fresh
    configuration instance is required between test cases.
    """
    global _config_instance
    _config_instance = None