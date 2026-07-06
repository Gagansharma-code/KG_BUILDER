"""Config schema for knowledge graph backend selection.

Mirrors ParsingConfig in src/parsing/backends/_schemas.py.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeGraphConfig(BaseModel):
    """Backend selection and connection settings for the knowledge graph."""

    model_config = ConfigDict(extra="forbid")

    backend: str = "networkx"
    neo4j_uri: str = Field(
        default="bolt://localhost:7687",
        description="Self-hosted Neo4j Bolt URI",
    )
    neo4j_username: str | None = Field(
        default=None,
        description="Neo4j username; leave unset for unauthenticated local tests",
    )
    neo4j_password: str | None = Field(
        default=None,
        description="Neo4j password; never hardcode production credentials",
    )
    neo4j_database: str | None = Field(
        default=None,
        description="Optional Neo4j database name",
    )
