"""Config schema for knowledge graph backend selection.

Mirrors ParsingConfig in src/parsing/backends/_schemas.py.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class KnowledgeGraphConfig(BaseModel):
    """Backend name selection for the knowledge graph storage layer."""

    model_config = ConfigDict(extra="forbid")

    backend: str = "networkx"
