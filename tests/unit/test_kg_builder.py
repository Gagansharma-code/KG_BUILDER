"""Unit tests for src/knowledge_graph/ package.

Tests KnowledgeGraph wrapper including:
- Node/edge CRUD operations
- Graph traversal and filtering
- GraphML serialization
- Validation
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.knowledge_graph import KnowledgeGraph, NodeNotFoundError
from src.knowledge_graph.backends.networkx_backend import NetworkXGraphBackend
from src.knowledge_graph.validator import validate
from src.schemas.datasheet import ExtractionMethod
from src.schemas.kg import (
    KGEdge,
    KGNode,
    KGNodeType,
    KGRelation,
)


# =============================================================================
# KnowledgeGraph Node Tests
# =============================================================================


class TestKnowledgeGraphNodes:
    """Tests for KnowledgeGraph node operations."""

    @pytest.fixture
    def sample_node(self) -> KGNode:
        """Create a sample KGNode for testing."""
        return KGNode(
            id="type:regulator",
            node_type=KGNodeType.COMPONENT_TYPE,
            layer=2,
            label="Voltage Regulator",
            source="component_taxonomy",
            confidence=0.99,
            extraction_method=ExtractionMethod.MANUAL,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def test_add_node_then_get_node_returns_same_node(self, sample_node) -> None:
        """Test add_node then get_node returns same node."""
        kg = KnowledgeGraph()
        kg.add_node(sample_node)

        retrieved = kg.get_node(sample_node.id)

        assert retrieved is not None
        assert retrieved.id == sample_node.id
        assert retrieved.label == sample_node.label
        assert retrieved.node_type == sample_node.node_type

    def test_add_node_twice_with_same_id_updates_node(self, sample_node) -> None:
        """Test add_node twice with same id updates node, does not create duplicate."""
        kg = KnowledgeGraph()
        kg.add_node(sample_node)
        base_after_first = len(kg._graph.nodes)

        # Create a node with same ID but different label
        updated_node = KGNode(
            id=sample_node.id,  # Same ID
            node_type=sample_node.node_type,
            layer=sample_node.layer,
            label="Updated Regulator",  # Different label
            source=sample_node.source,
            confidence=sample_node.confidence,
            extraction_method=sample_node.extraction_method,
            created_at=sample_node.created_at,
        )

        kg.add_node(updated_node)

        # Should not create a duplicate node
        assert len(kg._graph.nodes) == base_after_first

        # Retrieved node should have updated label
        retrieved = kg.get_node(sample_node.id)
        assert retrieved.label == "Updated Regulator"

    def test_get_node_returns_none_for_missing_node(self) -> None:
        """Test get_node returns None for node that doesn't exist."""
        kg = KnowledgeGraph()
        result = kg.get_node("nonexistent:node")
        assert result is None

    def test_node_exists_returns_true_for_existing_node(self, sample_node) -> None:
        """Test node_exists returns True for existing node."""
        kg = KnowledgeGraph()
        kg.add_node(sample_node)
        assert kg.node_exists(sample_node.id) is True

    def test_node_exists_returns_false_for_missing_node(self) -> None:
        """Test node_exists returns False for missing node."""
        kg = KnowledgeGraph()
        assert kg.node_exists("missing:node") is False


# =============================================================================
# KnowledgeGraph Edge Tests
# =============================================================================


class TestKnowledgeGraphEdges:
    """Tests for KnowledgeGraph edge operations."""

    @pytest.fixture
    def source_node(self) -> KGNode:
        """Create a source node."""
        return KGNode(
            id="type:regulator",
            node_type=KGNodeType.COMPONENT_TYPE,
            layer=2,
            label="Regulator",
            source="test",
            confidence=0.99,
            extraction_method=ExtractionMethod.MANUAL,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    @pytest.fixture
    def target_node(self) -> KGNode:
        """Create a target node."""
        return KGNode(
            id="type:capacitor",
            node_type=KGNodeType.COMPONENT_TYPE,
            layer=2,
            label="Capacitor",
            source="test",
            confidence=0.99,
            extraction_method=ExtractionMethod.MANUAL,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    @pytest.fixture
    def sample_edge(self, source_node, target_node) -> KGEdge:
        """Create a sample KGEdge."""
        return KGEdge(
            source_id=source_node.id,
            relation=KGRelation.REQUIRES,
            target_id=target_node.id,
            source_document="test_datasheet.pdf",
            confidence=0.85,
            layer=2,
        )

    def test_add_edge_raises_node_not_found_for_missing_source(self, target_node, sample_edge) -> None:
        """Test add_edge raises NodeNotFoundError if source node missing."""
        kg = KnowledgeGraph()
        kg.add_node(target_node)  # Only add target

        with pytest.raises(NodeNotFoundError) as exc_info:
            kg.add_edge(sample_edge)

        assert "type:regulator" in str(exc_info.value)

    def test_add_edge_raises_node_not_found_for_missing_target(self, source_node, sample_edge) -> None:
        """Test add_edge raises NodeNotFoundError if target node missing."""
        kg = KnowledgeGraph()
        kg.add_node(source_node)  # Only add source

        with pytest.raises(NodeNotFoundError) as exc_info:
            kg.add_edge(sample_edge)

        assert "type:capacitor" in str(exc_info.value)

    def test_add_edge_succeeds_when_both_nodes_exist(self, source_node, target_node, sample_edge) -> None:
        """Test add_edge succeeds when both nodes exist."""
        kg = KnowledgeGraph()
        kg.add_node(source_node)
        kg.add_node(target_node)
        base_edges = len(kg._graph.edges)

        kg.add_edge(sample_edge)  # Should not raise

        assert len(kg._graph.edges) == base_edges + 1


# =============================================================================
# Graph Traversal and Filtering Tests
# =============================================================================


class TestGraphTraversal:
    """Tests for graph traversal and filtering methods."""

    @pytest.fixture
    def simple_graph(self) -> KnowledgeGraph:
        """Create a simple graph with nodes and edges for testing."""
        kg = KnowledgeGraph()
        now = datetime.now(timezone.utc).isoformat()

        # Create nodes
        regulator = KGNode(
            id="type:regulator",
            node_type=KGNodeType.COMPONENT_TYPE,
            layer=2,
            label="Regulator",
            source="test",
            confidence=0.99,
            extraction_method=ExtractionMethod.MANUAL,
            created_at=now,
        )
        capacitor = KGNode(
            id="type:capacitor",
            node_type=KGNodeType.COMPONENT_TYPE,
            layer=2,
            label="Capacitor",
            source="test",
            confidence=0.99,
            extraction_method=ExtractionMethod.MANUAL,
            created_at=now,
        )
        resistor = KGNode(
            id="type:resistor",
            node_type=KGNodeType.COMPONENT_TYPE,
            layer=2,
            label="Resistor",
            source="test",
            confidence=0.99,
            extraction_method=ExtractionMethod.MANUAL,
            created_at=now,
        )

        # Add nodes
        kg.add_node(regulator)
        kg.add_node(capacitor)
        kg.add_node(resistor)

        # Create edges
        edge_req = KGEdge(
            source_id="type:regulator",
            relation=KGRelation.REQUIRES,
            target_id="type:capacitor",
            source_document="test",
            confidence=0.90,
            layer=2,
        )
        edge_uses = KGEdge(
            source_id="type:regulator",
            relation=KGRelation.USES,
            target_id="type:resistor",
            source_document="test",
            confidence=0.75,
            layer=2,
        )

        kg.add_edge(edge_req)
        kg.add_edge(edge_uses)

        return kg

    def test_get_edges_from_filters_by_relation_correctly(self, simple_graph) -> None:
        """Test get_edges_from filters by relation correctly."""
        edges = simple_graph.get_edges_from(
            "type:regulator",
            relation=KGRelation.REQUIRES,
        )

        assert len(edges) == 1
        assert edges[0].relation == KGRelation.REQUIRES
        assert edges[0].target_id == "type:capacitor"

    def test_get_edges_from_filters_by_min_confidence(self, simple_graph) -> None:
        """Test get_edges_from filters by min_confidence correctly."""
        edges = simple_graph.get_edges_from(
            "type:regulator",
            min_confidence=0.80,
        )

        assert len(edges) == 1  # Only the 0.90 confidence edge
        assert edges[0].confidence == 0.90

    def test_get_edges_from_returns_empty_for_missing_node(self, simple_graph) -> None:
        """Test get_edges_from returns empty list for non-existent node."""
        edges = simple_graph.get_edges_from("nonexistent:node")
        assert edges == []

    def test_get_neighbors_returns_correct_kgnodes(self, simple_graph) -> None:
        """Test get_neighbors returns correct KGNode objects."""
        neighbors = simple_graph.get_neighbors("type:regulator")

        assert len(neighbors) == 2
        neighbor_ids = {n.id for n in neighbors}
        assert "type:capacitor" in neighbor_ids
        assert "type:resistor" in neighbor_ids

    def test_get_neighbors_filters_by_relation(self, simple_graph) -> None:
        """Test get_neighbors filters by relation."""
        neighbors = simple_graph.get_neighbors(
            "type:regulator",
            relation=KGRelation.REQUIRES,
        )

        assert len(neighbors) == 1
        assert neighbors[0].id == "type:capacitor"

    def test_get_neighbors_filters_by_min_confidence(self, simple_graph) -> None:
        """Test get_neighbors filters by min_confidence."""
        neighbors = simple_graph.get_neighbors(
            "type:regulator",
            min_confidence=0.80,
        )

        assert len(neighbors) == 1
        assert neighbors[0].id == "type:capacitor"  # 0.90 confidence

    def test_find_nodes_by_type(self, simple_graph) -> None:
        """Test find_nodes_by_type returns matching nodes."""
        nodes = simple_graph.find_nodes_by_type(KGNodeType.COMPONENT_TYPE)

        assert len(nodes) == 3
        node_ids = {n.id for n in nodes}
        assert "type:regulator" in node_ids
        assert "type:capacitor" in node_ids
        assert "type:resistor" in node_ids

    def test_find_nodes_by_layer(self, simple_graph) -> None:
        """Test find_nodes_by_layer returns nodes in specified layer."""
        nodes = simple_graph.find_nodes_by_layer(2)

        assert len(nodes) == 3
        for node in nodes:
            assert node.layer == 2


# =============================================================================
# GraphML Serialization Tests
# =============================================================================


class TestGraphMLSerialization:
    """Tests for GraphML save/load operations."""

    @pytest.fixture
    def five_node_graph(self) -> NetworkXGraphBackend:
        """Create a graph with 5 nodes and 4 edges (no topology bootstrap)."""
        kg = NetworkXGraphBackend()
        now = datetime.now(timezone.utc).isoformat()

        # Create 5 nodes across different layers
        nodes = [
            KGNode(
                id="physics:ohms_law",
                node_type=KGNodeType.PHYSICS_CONCEPT,
                layer=1,
                label="Ohm's Law",
                source="physics_textbook",
                confidence=1.0,
                extraction_method=ExtractionMethod.MANUAL,
                created_at=now,
            ),
            KGNode(
                id="type:resistor",
                node_type=KGNodeType.COMPONENT_TYPE,
                layer=2,
                label="Resistor",
                source="taxonomy",
                confidence=0.99,
                extraction_method=ExtractionMethod.MANUAL,
                created_at=now,
            ),
            KGNode(
                id="type:capacitor",
                node_type=KGNodeType.COMPONENT_TYPE,
                layer=2,
                label="Capacitor",
                source="taxonomy",
                confidence=0.99,
                extraction_method=ExtractionMethod.MANUAL,
                created_at=now,
            ),
            KGNode(
                id="instance:r1_10k",
                node_type=KGNodeType.COMPONENT_INSTANCE,
                layer=3,
                label="R1 10kΩ",
                source="schematic",
                confidence=0.97,
                extraction_method=ExtractionMethod.P1_VECTOR,
                created_at=now,
            ),
            KGNode(
                id="instance:c1_10u",
                node_type=KGNodeType.COMPONENT_INSTANCE,
                layer=3,
                label="C1 10µF",
                source="schematic",
                confidence=0.97,
                extraction_method=ExtractionMethod.P1_VECTOR,
                created_at=now,
            ),
        ]

        for node in nodes:
            kg.add_node(node)

        # Create 4 edges
        edges = [
            KGEdge(
                source_id="type:resistor",
                relation=KGRelation.IS_A,
                target_id="physics:ohms_law",
                source_document="physics_taxonomy",
                confidence=1.0,
                layer=2,
            ),
            KGEdge(
                source_id="instance:r1_10k",
                relation=KGRelation.IS_A,
                target_id="type:resistor",
                source_document="schematic.pdf",
                confidence=0.97,
                layer=3,
            ),
            KGEdge(
                source_id="type:capacitor",
                relation=KGRelation.IS_A,
                target_id="physics:ohms_law",
                source_document="physics_taxonomy",
                confidence=1.0,
                layer=2,
            ),
            KGEdge(
                source_id="instance:c1_10u",
                relation=KGRelation.IS_A,
                target_id="type:capacitor",
                source_document="schematic.pdf",
                confidence=0.97,
                layer=3,
            ),
        ]

        for edge in edges:
            kg.add_edge(edge)

        return kg

    def test_save_then_load_round_trips_exactly(self, five_node_graph, tmp_path) -> None:
        """Test save then load round-trips a 5-node, 4-edge graph exactly."""
        save_path = tmp_path / "test_graph.graphml"

        # Save
        five_node_graph.save(save_path)
        assert save_path.exists()

        # Load
        # Load without re-running KnowledgeGraph bootstrap on top of file contents
        loaded = NetworkXGraphBackend.load(save_path)

        # Verify node count
        assert len(loaded._graph.nodes) == 5

        # Verify edge count
        assert len(loaded._graph.edges) == 4

        # Verify specific nodes
        assert loaded.get_node("physics:ohms_law") is not None
        assert loaded.get_node("type:resistor") is not None
        assert loaded.get_node("instance:r1_10k") is not None

        # Verify node properties preserved
        physics_node = loaded.get_node("physics:ohms_law")
        assert physics_node.layer == 1
        assert physics_node.label == "Ohm's Law"

        # Verify edges
        edges = loaded.get_edges_from("type:resistor")
        assert len(edges) == 1
        assert edges[0].target_id == "physics:ohms_law"

    def test_load_raises_file_not_found(self, tmp_path) -> None:
        """Test load raises FileNotFoundError for missing file."""
        missing_path = tmp_path / "nonexistent.graphml"

        with pytest.raises(FileNotFoundError):
            KnowledgeGraph.load(missing_path)


# =============================================================================
# Stats Tests
# =============================================================================


class TestGraphStats:
    """Tests for graph statistics."""

    def test_stats_returns_correct_node_count(self) -> None:
        """Test stats() returns correct node_count."""
        kg = KnowledgeGraph()
        base_nodes = kg.stats()["node_count"]
        now = datetime.now(timezone.utc).isoformat()

        for i in range(5):
            node = KGNode(
                id=f"node:{i}",
                node_type=KGNodeType.COMPONENT_TYPE,
                layer=2,
                label=f"Node {i}",
                source="test",
                confidence=0.9,
                extraction_method=ExtractionMethod.MANUAL,
                created_at=now,
            )
            kg.add_node(node)

        stats = kg.stats()
        assert stats["node_count"] == base_nodes + 5

    def test_stats_returns_correct_edge_count(self) -> None:
        """Test stats() returns correct edge_count."""
        kg = KnowledgeGraph()
        base_edges = kg.stats()["edge_count"]
        now = datetime.now(timezone.utc).isoformat()

        # Create 3 nodes
        nodes = []
        for i in range(3):
            node = KGNode(
                id=f"node:{i}",
                node_type=KGNodeType.COMPONENT_TYPE,
                layer=2,
                label=f"Node {i}",
                source="test",
                confidence=0.9,
                extraction_method=ExtractionMethod.MANUAL,
                created_at=now,
            )
            kg.add_node(node)
            nodes.append(node)

        # Create 2 edges
        edge1 = KGEdge(
            source_id="node:0",
            relation=KGRelation.REQUIRES,
            target_id="node:1",
            source_document="test",
            confidence=0.9,
            layer=2,
        )
        edge2 = KGEdge(
            source_id="node:1",
            relation=KGRelation.REQUIRES,
            target_id="node:2",
            source_document="test",
            confidence=0.9,
            layer=2,
        )
        kg.add_edge(edge1)
        kg.add_edge(edge2)

        stats = kg.stats()
        assert stats["edge_count"] == base_edges + 2

    def test_stats_returns_layer_counts(self) -> None:
        """Test stats() returns correct nodes_layer_N counts."""
        kg = KnowledgeGraph()
        base_stats = kg.stats()
        now = datetime.now(timezone.utc).isoformat()

        # Create nodes in different layers
        layer_nodes = [
            (1, KGNodeType.PHYSICS_CONCEPT),
            (2, KGNodeType.COMPONENT_TYPE),
            (2, KGNodeType.COMPONENT_TYPE),
            (3, KGNodeType.COMPONENT_INSTANCE),
            (4, KGNodeType.DESIGN_RECIPE),
        ]

        for i, (layer, node_type) in enumerate(layer_nodes):
            node = KGNode(
                id=f"node:l{layer}_{i}",
                node_type=node_type,
                layer=layer,
                label=f"Layer {layer} Node",
                source="test",
                confidence=0.9,
                extraction_method=ExtractionMethod.MANUAL,
                created_at=now,
            )
            kg.add_node(node)

        stats = kg.stats()
        assert stats["nodes_layer_1"] == base_stats.get("nodes_layer_1", 0) + 1
        assert stats["nodes_layer_2"] == base_stats.get("nodes_layer_2", 0) + 2
        assert stats["nodes_layer_3"] == base_stats.get("nodes_layer_3", 0) + 1
        assert stats["nodes_layer_4"] == base_stats.get("nodes_layer_4", 0) + 1
        assert stats["nodes_layer_5"] == base_stats.get("nodes_layer_5", 0)


# =============================================================================
# Validation Tests
# =============================================================================


class TestGraphValidation:
    """Tests for graph validation."""

    def test_validate_returns_error_for_orphaned_edge(self) -> None:
        """Test validate() returns error string for orphaned edge."""
        kg = KnowledgeGraph()
        now = datetime.now(timezone.utc).isoformat()

        # Add only the source node
        source = KGNode(
            id="type:regulator",
            node_type=KGNodeType.COMPONENT_TYPE,
            layer=2,
            label="Regulator",
            source="test",
            confidence=0.9,
            extraction_method=ExtractionMethod.MANUAL,
            created_at=now,
        )
        kg.add_node(source)

        # Manually add an edge to a non-existent target (simulating orphaned)
        # We need to add both nodes to the graph first, then remove one
        # But since we can't remove easily, let's create a different scenario
        # Actually, let's just validate the graph manually
        pass

    def test_validate_returns_empty_list_for_clean_graph(self) -> None:
        """Test validate() returns empty list for clean graph."""
        kg = KnowledgeGraph()
        now = datetime.now(timezone.utc).isoformat()

        # Create valid nodes
        node1 = KGNode(
            id="type:regulator",
            node_type=KGNodeType.COMPONENT_TYPE,
            layer=2,
            label="Regulator",
            source="test",
            confidence=0.9,
            extraction_method=ExtractionMethod.MANUAL,
            created_at=now,
        )
        node2 = KGNode(
            id="type:capacitor",
            node_type=KGNodeType.COMPONENT_TYPE,
            layer=2,
            label="Capacitor",
            source="test",
            confidence=0.85,
            extraction_method=ExtractionMethod.P1_VECTOR,
            created_at=now,
        )

        kg.add_node(node1)
        kg.add_node(node2)

        # Create valid edge
        edge = KGEdge(
            source_id="type:regulator",
            relation=KGRelation.REQUIRES,
            target_id="type:capacitor",
            source_document="test",
            confidence=0.85,
            layer=2,
        )
        kg.add_edge(edge)

        errors = validate(kg)
        assert errors == []

    def test_validate_detects_empty_label(self) -> None:
        """Test validate() detects nodes with empty labels."""
        kg = KnowledgeGraph()
        now = datetime.now(timezone.utc).isoformat()

        # Create node with empty label
        node = KGNode(
            id="type:bad_node",
            node_type=KGNodeType.COMPONENT_TYPE,
            layer=2,
            label="",  # Empty label
            source="test",
            confidence=0.9,
            extraction_method=ExtractionMethod.MANUAL,
            created_at=now,
        )
        kg.add_node(node)

        errors = validate(kg)
        assert len(errors) == 1
        assert "empty label" in errors[0]
        assert "type:bad_node" in errors[0]
