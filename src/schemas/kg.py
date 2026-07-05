"""Knowledge Graph schema — Team B owns.

All KGNode creation must use EXTRACTION_METHOD_CONFIDENCE to assign edge confidence.

This module defines the Pydantic models for the Neo4j-backed knowledge graph
that stores canonical design knowledge: physics concepts, component types,
design recipes, placement rules, and their relationships.

The knowledge graph is organized into 5 abstraction layers:
- Layer 1: Physics concepts (Ohm's law, thermal resistance)
- Layer 2: Component types (regulator, capacitor)
- Layer 3: Component instances (TPS62933DRLR, GRM155R71C104KA88D)
- Layer 4: Design recipes ("choose input cap based on ripple current")
- Layer 5: Project-specific placements (actual PCB designs)

Usage:
    from src.schemas.kg import KGNode, KGEdge, EXTRACTION_METHOD_CONFIDENCE
    from src.schemas.datasheet import ExtractionMethod

    confidence = EXTRACTION_METHOD_CONFIDENCE[ExtractionMethod.P1_VECTOR]
    node = KGNode(
        id="physics:ohms_law",
        node_type=KGNodeType.PHYSICS_CONCEPT,
        layer=1,
        label="Ohm's Law",
        source="textbook",
        confidence=confidence,
        extraction_method=ExtractionMethod.P1_VECTOR,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.schemas.datasheet import EXTRACTION_METHOD_CONFIDENCE, ExtractionMethod


class KGNodeType(str, Enum):
    """Classification of knowledge graph node types.

    Nodes represent entities in the design knowledge ontology,
    organized from abstract physics concepts to concrete instances.
    """

    PHYSICS_CONCEPT = "physics_concept"  # Layer 1: Ohm's law, thermal resistance
    COMPONENT_TYPE = "component_type"  # Layer 2: regulator, capacitor, resistor
    COMPONENT_INSTANCE = "component_instance"  # Layer 3: TPS62933DRLR
    DESIGN_RECIPE = "design_recipe"  # Layer 4: design patterns and recipes
    ELECTRICAL_PROPERTY = "electrical_property"  # V, I, R, C values
    PLACEMENT_RULE = "placement_rule"  # Physical placement constraints
    ROUTING_RULE = "routing_rule"  # PCB routing constraints
    DESIGN_METHODOLOGY = "design_methodology"  # Design approaches
    NET_TYPE = "net_type"  # Power, ground, signal classifications
    STANDARD = "standard"  # IPC, JEDEC, IEEE standards
    PIN = "pin"  # Individual pin entities
    TOPOLOGY = "topology"  # Layer 4: formal circuit pattern (ldo, buck_converter)
    FUNCTIONAL_BLOCK = "functional_block"  # Layer 4: block within a topology
    DESIGN_CONSTRAINT = "design_constraint"  # Layer 5: per-design-run constraint, design_id-scoped


class KGRelation(str, Enum):
    """Classification of knowledge graph edge (relationship) types.

    Relations connect nodes with semantic meaning, representing
    dependencies, requirements, and constraints in the design space.
    """

    REQUIRES = "requires"  # A requires B to function
    USES = "uses"  # A uses B in its implementation
    HAS_PROPERTY = "has_property"  # A has electrical/physical property B
    CONNECTS_TO = "connects_to"  # Electrical connection between pins/nets
    MUST_BE_NEAR = "must_be_near"  # Proximity placement constraint
    MUST_AVOID = "must_avoid"  # Exclusion zone constraint
    IS_A = "is_a"  # Taxonomic relationship (type hierarchy)
    GOVERNED_BY = "governed_by"  # Subject to a standard/rule
    REQUIRES_ROUTING = "requires_routing"  # Needs specific routing topology
    PART_OF = "part_of"  # Component relationship
    REPLACES = "replaces"  # Substitution relationship
    INCOMPATIBLE_WITH = "incompatible_with"  # Cannot be used together
    OVERRIDES = "overrides"  # Rule/method supersedes another
    IMPLEMENTS = "implements"  # ComponentType/Instance realizes a Topology
    CONSTRAINED_BY = "constrained_by"  # Design element subject to a DesignConstraint


class KGNode(BaseModel):
    """Knowledge graph node representing an entity in the design ontology.

    Nodes are organized into 5 abstraction layers, from physics concepts (1)
    to project-specific instances (5). Each node tracks provenance through
    its extraction_method and confidence scores.

    Attributes:
        id: Unique identifier for the node (URI format recommended)
        node_type: Classification of what this node represents
        layer: Abstraction layer (1=physics, 2=types, 3=instances, 4=recipes, 5=projects)
        label: Human-readable display name
        properties: Flexible key-value store for node-specific attributes
        source: Origin document or reference (e.g., datasheet URL, textbook)
        confidence: Confidence score in [0.0, 1.0] based on extraction method
        extraction_method: How this node was created
        created_at: ISO 8601 timestamp of node creation
    """

    id: str = Field(description="Unique node identifier (URI format recommended)")
    node_type: KGNodeType = Field(description="Classification of node entity type")
    layer: int = Field(
        ge=1, le=5, description="Abstraction layer (1-5, where 1=physics, 5=projects)"
    )
    label: str = Field(description="Human-readable display name for the node")
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Flexible key-value attributes for node-specific data",
    )
    source: str = Field(description="Origin document or reference (datasheet URL, etc.)")
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence score based on extraction method quality"
    )
    extraction_method: ExtractionMethod = Field(
        description="Method used to extract/create this node"
    )
    created_at: str = Field(description="ISO 8601 timestamp of node creation")
    design_id: Optional[str] = Field(
        default=None,
        description=(
            "Design run this node is scoped to (DESIGN_CONSTRAINT nodes only; "
            "None for global knowledge). Plain scalar per NEO4J_BACKEND_DESIGN.md §1.1."
        ),
    )

    def get_confidence_from_method(self) -> float:
        """Return the canonical confidence score for this node's extraction method.

        Returns:
            Base confidence score from EXTRACTION_METHOD_CONFIDENCE mapping.

        Example:
            >>> node.extraction_method = ExtractionMethod.MANUAL
            >>> node.get_confidence_from_method()
            1.0
        """
        return EXTRACTION_METHOD_CONFIDENCE.get(self.extraction_method, 0.5)


class KGEdge(BaseModel):
    """Knowledge graph edge representing a relationship between nodes.

    Edges connect KGNode entities with typed relationships, carrying
    confidence scores and provenance information. Edges can include
    constraint parameters for placement and routing rules.

    Attributes:
        source_id: ID of the source node (matches KGNode.id)
        relation: Type of relationship (from KGRelation enum)
        target_id: ID of the target node (matches KGNode.id)
        constraints: Optional parameters for rule edges (distance, layer, etc.)
        source_document: Document proving this relationship exists
        confidence: Confidence in the relationship's validity [0.0, 1.0]
        layer: Abstraction layer this edge belongs to (matches lowest node layer)
    """

    source_id: str = Field(description="ID of source node (matches KGNode.id)")
    relation: KGRelation = Field(description="Type of relationship between nodes")
    target_id: str = Field(description="ID of target node (matches KGNode.id)")
    constraints: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional constraint parameters (distance, layer, etc.)",
    )
    source_document: str = Field(
        description="Document reference proving this relationship"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence in relationship validity"
    )
    layer: int = Field(
        ge=1, le=5, description="Abstraction layer (must match participating nodes)"
    )


class DesignSubgraph(BaseModel):
    """Output of the KG query engine. Input to Team C's BOM generator.

    Schema version locked after B-1. Changes require Team C sign-off.

    This model encapsulates the result of a knowledge graph traversal/query,
    containing all relevant nodes and edges for generating a Bill of Materials
    and design recommendations for a specific component or design goal.

    Attributes:
        component_types: Component type nodes (Layer 2) needed for the design
        component_instances: Specific part recommendations (Layer 3), may be empty
        design_rules: Quantitative constraint edges with values and units
        placement_rules: PlacementRule nodes from KG-4 (proximity, keepout)
        routing_hints: RoutingRule nodes from KG-4 (topology requirements)
        design_methodology: Active design methodology identifier
        path_confidences: Mapping of node_id to traversal confidence along path
        query_depth: How deep the graph traversal went (hops from query node)
        query_metadata: Additional metadata about the query execution
    """

    model_config = {"extra": "forbid"}

    component_types: list[KGNode] = Field(
        default_factory=list,
        description="Component type nodes (Layer 2) needed for the design",
    )
    component_instances: list[KGNode] = Field(
        default_factory=list,
        description="Specific part recommendations (Layer 3), may be empty",
    )
    design_rules: list[KGEdge] = Field(
        default_factory=list,
        description="Quantitative constraint edges with values and units",
    )
    placement_rules: list[KGNode] = Field(
        default_factory=list,
        description="PlacementRule nodes from KG-4 (proximity, keepout rules)",
    )
    routing_hints: list[KGNode] = Field(
        default_factory=list,
        description="RoutingRule nodes from KG-4 (topology requirements)",
    )
    design_methodology: str = Field(
        description="Active design methodology identifier (e.g., 'power_regulation')",
    )
    path_confidences: dict[str, float] = Field(
        default_factory=dict,
        description="node_id → confidence score along the traversal path",
    )
    query_depth: int = Field(
        ge=0,
        description="Graph traversal depth (hops from query node)",
    )
    query_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata about query execution (timing, filters, etc.)",
    )

    def has_specific_parts(self) -> bool:
        """Check if the subgraph contains specific component instances.

        Returns True if component_instances list is non-empty, indicating
        that concrete part recommendations exist beyond just type-level
        knowledge.

        Returns:
            True if specific parts recommended, False if only type knowledge
        """
        return len(self.component_instances) > 0

    def min_path_confidence(self) -> float:
        """Return the minimum confidence score along the traversal path.

        This represents the weakest link in the knowledge chain from query
        node to result. Lower values indicate higher uncertainty in the
        reasoning path.

        Returns:
            Minimum confidence value in path_confidences dict, or 0.0 if empty
        """
        if not self.path_confidences:
            return 0.0
        return min(self.path_confidences.values())


class ComponentSearchResult(BaseModel):
    """Result of a similarity search for components in the knowledge graph.

    Represents a ranked match between a query and a KGNode, including
    the similarity score and which properties matched.

    Attributes:
        node: The matched KGNode (component type or instance)
        similarity_score: Overall match score [0.0, 1.0]
        matching_properties: Which node properties contributed to the match
    """

    model_config = {"extra": "forbid"}

    node: KGNode = Field(
        description="The matched KGNode (component type or instance)",
    )
    similarity_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Overall match score [0.0, 1.0]",
    )
    matching_properties: list[str] = Field(
        default_factory=list,
        description="Which node properties contributed to the similarity match",
    )


__all__ = [
    "KGNodeType",
    "KGRelation",
    "EXTRACTION_METHOD_CONFIDENCE",
    "KGNode",
    "KGEdge",
    "DesignSubgraph",
    "ComponentSearchResult",
]
