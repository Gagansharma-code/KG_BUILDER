"""Unit tests for src/knowledge_graph/importers/p1_importer.py.

Tests ComponentDatasheet to KnowledgeGraph import including:
- ComponentInstance node creation
- Pin node creation
- ElectricalProperty node creation
- PlacementRule node creation
- Edge creation
- Idempotency (duplicate handling)
- Batch import with failure handling
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from src.config import Config
from src.knowledge_graph import KnowledgeGraph
from src.knowledge_graph.importers.p1_importer import (
    import_batch,
    import_datasheet,
)
from src.schemas.datasheet import (
    ComponentDatasheet,
    ElectricalParameter,
    ExtractionMethod,
    ExtractedValue,
    PinDefinition,
    PlacementConstraint,
    TableSectionType,
)
from src.schemas.kg import KGNodeType, KGRelation


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_config() -> Config:
    """Create mock Config for testing."""
    return MagicMock(spec=Config)


@pytest.fixture
def minimal_datasheet() -> ComponentDatasheet:
    """Create a minimal ComponentDatasheet fixture."""
    return ComponentDatasheet(
        component_id="TPS62933DRLR",
        manufacturer="Texas Instruments",
        description="3A Buck Converter",
        package="SOT-23-5",
        source_pdf_hash="abc123hash456",
        extraction_method=ExtractionMethod.P1_VECTOR,
        extraction_confidence=0.97,
        created_at="2024-01-15T10:30:00Z",
    )


@pytest.fixture
def datasheet_with_pins() -> ComponentDatasheet:
    """Create a ComponentDatasheet with 3 pins."""
    return ComponentDatasheet(
        component_id="LM358",
        manufacturer="Texas Instruments",
        description="Dual Op-Amp",
        package="DIP-8",
        source_pdf_hash="def456hash789",
        extraction_method=ExtractionMethod.P1_VECTOR,
        extraction_confidence=0.95,
        pins=[
            PinDefinition(
                pin_number="1",
                raw_name="OUT1",
                pin_type="output",
                description="Output 1",
            ),
            PinDefinition(
                pin_number="2",
                raw_name="IN1-",
                pin_type="input",
                description="Inverting Input 1",
            ),
            PinDefinition(
                pin_number="3",
                raw_name="IN1+",
                pin_type="input",
                description="Non-Inverting Input 1",
            ),
        ],
        created_at="2024-01-15T10:30:00Z",
    )


@pytest.fixture
def datasheet_with_electrical_params() -> ComponentDatasheet:
    """Create a ComponentDatasheet with electrical parameters."""
    return ComponentDatasheet(
        component_id="LM7805",
        manufacturer="ST Microelectronics",
        description="5V Linear Regulator",
        package="TO-220",
        source_pdf_hash="ghi789hash012",
        extraction_method=ExtractionMethod.P1_VLM,
        extraction_confidence=0.88,
        electrical_parameters=[
            ElectricalParameter(
                parameter_name="Output Voltage",
                symbol="VOUT",
                conditions="I_OUT = 500mA, T_J = 25°C",
                value=ExtractedValue(
                    raw_text="5.0V",
                    normalized_value=5.0,
                    unit="V",
                    typ_val=5.0,
                    min_val=4.8,
                    max_val=5.2,
                    confidence=0.95,
                ),
                section_type=TableSectionType.ELECTRICAL_CHARACTERISTICS,
                source_page=3,
                source_table_index=0,
            ),
            ElectricalParameter(
                parameter_name="Dropout Voltage",
                symbol="VDROPOUT",
                conditions="I_OUT = 1A",
                value=ExtractedValue(
                    raw_text="2.0V",
                    normalized_value=2.0,
                    unit="V",
                    max_val=2.0,
                    confidence=0.92,
                ),
                section_type=TableSectionType.ELECTRICAL_CHARACTERISTICS,
                source_page=3,
                source_table_index=0,
            ),
        ],
        created_at="2024-01-15T10:30:00Z",
    )


@pytest.fixture
def datasheet_with_placement_constraints() -> ComponentDatasheet:
    """Create a ComponentDatasheet with 2 placement constraints."""
    return ComponentDatasheet(
        component_id="TPS62933DRLR",
        manufacturer="Texas Instruments",
        description="3A Buck Converter",
        package="SOT-23-5",
        source_pdf_hash="abc123hash456",
        extraction_method=ExtractionMethod.P1_VECTOR,
        extraction_confidence=0.97,
        layout_constraints=[
            PlacementConstraint(
                constraint_type="proximity",
                subject="C1",
                relative_to="U1.VIN",
                relative_to_type="pin",
                max_distance_mm=5.0,
                hard=True,
                source_sentence="Place input capacitor C1 within 5mm of VIN pin",
                confidence=0.95,
            ),
            PlacementConstraint(
                constraint_type="keepout",
                subject="L1",
                relative_to="C2",
                relative_to_type="component",
                min_distance_mm=3.0,
                hard=False,
                source_sentence="Keep inductor L1 at least 3mm from output capacitor",
                confidence=0.88,
            ),
        ],
        created_at="2024-01-15T10:30:00Z",
    )


# =============================================================================
# Import Single Datasheet Tests
# =============================================================================


class TestImportSingleDatasheet:
    """Tests for import_datasheet function."""

    def test_import_minimal_datasheet_returns_success(
        self, minimal_datasheet, mock_config
    ) -> None:
        """Import a minimal ComponentDatasheet fixture — verify ImportResult.success=True."""
        graph = KnowledgeGraph()
        result = import_datasheet(minimal_datasheet, graph, mock_config)

        assert result.success is True
        assert result.component_id == "TPS62933DRLR"
        assert result.nodes_created >= 1  # At least the component node

    def test_import_creates_component_instance_node(
        self, minimal_datasheet, mock_config
    ) -> None:
        """Verify ComponentInstance node exists in graph after import."""
        graph = KnowledgeGraph()
        import_datasheet(minimal_datasheet, graph, mock_config)

        node = graph.get_node("component_instance:TPS62933DRLR")
        assert node is not None
        assert node.node_type == KGNodeType.COMPONENT_INSTANCE
        assert node.layer == 3
        assert node.label == "TPS62933DRLR"
        assert node.properties["manufacturer"] == "Texas Instruments"
        assert node.properties["package"] == "SOT-23-5"

    def test_import_creates_correct_number_of_pin_nodes(
        self, datasheet_with_pins, mock_config
    ) -> None:
        """Verify correct number of Pin nodes created (one per pin in fixture)."""
        graph = KnowledgeGraph()
        result = import_datasheet(datasheet_with_pins, graph, mock_config)

        # Should create component + 3 pin nodes = 4 nodes
        assert result.nodes_created == 4

        # Verify each pin node exists
        for i in range(1, 4):
            pin_node = graph.get_node(f"pin:LM358:{i}")
            assert pin_node is not None
            assert pin_node.node_type == KGNodeType.PIN
            assert pin_node.layer == 3

    def test_import_creates_pin_node_with_correct_properties(
        self, datasheet_with_pins, mock_config
    ) -> None:
        """Verify Pin nodes have correct properties including pin_type and raw_name."""
        graph = KnowledgeGraph()
        import_datasheet(datasheet_with_pins, graph, mock_config)

        pin1 = graph.get_node("pin:LM358:1")
        assert pin1 is not None
        assert pin1.properties["pin_number"] == "1"
        assert pin1.properties["raw_name"] == "OUT1"
        assert pin1.properties["pin_type"] == "output"
        assert pin1.label == "OUT1"

    def test_import_creates_correct_number_of_electrical_property_nodes(
        self, datasheet_with_electrical_params, mock_config
    ) -> None:
        """Verify correct number of ElectricalProperty nodes created."""
        graph = KnowledgeGraph()
        result = import_datasheet(datasheet_with_electrical_params, graph, mock_config)

        # Component + 2 electrical properties = 3 nodes
        assert result.nodes_created == 3

        # Verify electrical property nodes exist
        prop1 = graph.get_node(
            f"property:LM7805:VOUT:{TableSectionType.ELECTRICAL_CHARACTERISTICS.value}"
        )
        assert prop1 is not None
        assert prop1.node_type == KGNodeType.ELECTRICAL_PROPERTY

        prop2 = graph.get_node(
            f"property:LM7805:VDROPOUT:{TableSectionType.ELECTRICAL_CHARACTERISTICS.value}"
        )
        assert prop2 is not None

    def test_import_creates_electrical_property_with_values(
        self, datasheet_with_electrical_params, mock_config
    ) -> None:
        """Verify ElectricalProperty nodes have correct value properties."""
        graph = KnowledgeGraph()
        import_datasheet(datasheet_with_electrical_params, graph, mock_config)

        vout_node = graph.get_node(
            f"property:LM7805:VOUT:{TableSectionType.ELECTRICAL_CHARACTERISTICS.value}"
        )
        assert vout_node is not None
        assert vout_node.properties["min_val"] == 4.8
        assert vout_node.properties["typ_val"] == 5.0
        assert vout_node.properties["max_val"] == 5.2
        assert vout_node.properties["unit"] == "V"
        assert vout_node.properties["symbol"] == "VOUT"

    def test_import_creates_edges_from_component_to_pins(
        self, datasheet_with_pins, mock_config
    ) -> None:
        """Verify HAS_PROPERTY edges created from ComponentInstance to Pin nodes."""
        graph = KnowledgeGraph()
        result = import_datasheet(datasheet_with_pins, graph, mock_config)

        # Should have 3 edges (component → each pin)
        assert result.edges_created >= 3

        # Verify edges exist
        edges = graph.get_edges_from("component_instance:LM358")
        pin_edges = [e for e in edges if e.relation == KGRelation.HAS_PROPERTY]
        assert len(pin_edges) == 3

        # Verify edge targets are pins
        target_ids = {e.target_id for e in pin_edges}
        assert "pin:LM358:1" in target_ids
        assert "pin:LM358:2" in target_ids
        assert "pin:LM358:3" in target_ids

    def test_import_creates_edges_from_component_to_properties(
        self, datasheet_with_electrical_params, mock_config
    ) -> None:
        """Verify HAS_PROPERTY edges created from ComponentInstance to ElectricalProperty nodes."""
        graph = KnowledgeGraph()
        result = import_datasheet(datasheet_with_electrical_params, graph, mock_config)

        # Should have 2 edges (component → each property)
        assert result.edges_created == 2

        edges = graph.get_edges_from("component_instance:LM7805")
        assert len(edges) == 2
        assert all(e.relation == KGRelation.HAS_PROPERTY for e in edges)

    def test_import_creates_placement_rule_nodes(
        self, datasheet_with_placement_constraints, mock_config
    ) -> None:
        """Import datasheet with 2 PlacementConstraints — verify 2 PlacementRule nodes + 2 GOVERNED_BY edges."""
        graph = KnowledgeGraph()
        result = import_datasheet(
            datasheet_with_placement_constraints, graph, mock_config
        )

        # Should have 1 component + 2 placement rules = 3 nodes
        assert result.nodes_created == 3
        assert result.placement_rules_imported == 2

        # Verify placement rule nodes exist (Layer 4)
        rule0 = graph.get_node("placement_rule:TPS62933DRLR:0")
        assert rule0 is not None
        assert rule0.node_type == KGNodeType.PLACEMENT_RULE
        assert rule0.layer == 4
        assert rule0.properties["constraint_type"] == "proximity"
        assert rule0.properties["subject"] == "C1"

        rule1 = graph.get_node("placement_rule:TPS62933DRLR:1")
        assert rule1 is not None
        assert rule1.properties["constraint_type"] == "keepout"
        assert rule1.properties["hard"] is False

    def test_import_creates_governed_by_edges_for_placement_rules(
        self, datasheet_with_placement_constraints, mock_config
    ) -> None:
        """Verify GOVERNED_BY edges created from ComponentInstance to PlacementRule nodes."""
        graph = KnowledgeGraph()
        result = import_datasheet(
            datasheet_with_placement_constraints, graph, mock_config
        )

        # Should have 2 edges (component → each placement rule)
        assert result.edges_created == 2

        edges = graph.get_edges_from("component_instance:TPS62933DRLR")
        assert len(edges) == 2
        assert all(e.relation == KGRelation.GOVERNED_BY for e in edges)

        # Verify edge targets are placement rules
        target_ids = {e.target_id for e in edges}
        assert "placement_rule:TPS62933DRLR:0" in target_ids
        assert "placement_rule:TPS62933DRLR:1" in target_ids

    def test_import_idempotent_duplicate_handling(
        self, minimal_datasheet, mock_config
    ) -> None:
        """Import same datasheet twice — verify skipped_duplicates > 0, no duplicate nodes."""
        graph = KnowledgeGraph()
        base_nodes = graph.stats()["node_count"]

        # First import
        result1 = import_datasheet(minimal_datasheet, graph, mock_config)
        initial_nodes = base_nodes + result1.nodes_created
        assert result1.skipped_duplicates == 0

        # Second import (same datasheet)
        result2 = import_datasheet(minimal_datasheet, graph, mock_config)

        # Should mark as duplicates
        assert result2.skipped_duplicates > 0
        # Only component node exists, so 1 duplicate
        assert result2.skipped_duplicates == 1

        # Total nodes in graph should not increase
        stats = graph.stats()
        assert stats["node_count"] == initial_nodes

    def test_import_preserves_confidence_values(self, minimal_datasheet, mock_config) -> None:
        """Verify confidence values from datasheet are preserved in nodes."""
        graph = KnowledgeGraph()
        import_datasheet(minimal_datasheet, graph, mock_config)

        node = graph.get_node("component_instance:TPS62933DRLR")
        assert node is not None
        assert node.confidence == 0.97
        assert node.extraction_method == ExtractionMethod.P1_VECTOR

    def test_import_handles_empty_datasheet_gracefully(
        self, mock_config
    ) -> None:
        """Test import handles datasheet with minimal fields."""
        datasheet = ComponentDatasheet(
            component_id="TEST123",
            manufacturer="",
            description="",
            package="",
            source_pdf_hash="test_hash",
            extraction_method=ExtractionMethod.P1_VECTOR,
            extraction_confidence=0.5,
            created_at="2024-01-15T10:30:00Z",
        )

        graph = KnowledgeGraph()
        result = import_datasheet(datasheet, graph, mock_config)

        assert result.success is True
        assert result.nodes_created == 1  # Just the component node

        node = graph.get_node("component_instance:TEST123")
        assert node is not None
        assert node.properties["manufacturer"] == ""


# =============================================================================
# Batch Import Tests
# =============================================================================


class TestImportBatch:
    """Tests for import_batch function."""

    def test_import_batch_processes_multiple_datasheets(
        self, minimal_datasheet, datasheet_with_pins, mock_config
    ) -> None:
        """Test import_batch processes multiple datasheets."""
        graph = KnowledgeGraph()
        datasheets = [minimal_datasheet, datasheet_with_pins]

        result = import_batch(datasheets, graph, mock_config)

        assert result.total_datasheets == 2
        assert result.successful == 2
        assert result.failed == 0
        assert len(result.results) == 2

    def test_import_batch_continues_on_failure(
        self, minimal_datasheet, datasheet_with_pins, mock_config
    ) -> None:
        """Test that import_batch continues when one datasheet raises internally."""
        graph = KnowledgeGraph()

        # Create a datasheet that might cause issues (None component_id)
        bad_datasheet = ComponentDatasheet(
            component_id="",  # Empty ID might cause issues
            manufacturer="Bad",
            description="Bad Component",
            package="NONE",
            source_pdf_hash="bad_hash",
            extraction_method=ExtractionMethod.P1_VECTOR,
            extraction_confidence=0.5,
            created_at="2024-01-15T10:30:00Z",
        )

        datasheets = [minimal_datasheet, bad_datasheet, datasheet_with_pins]

        result = import_batch(datasheets, graph, mock_config)

        # Should process all 3
        assert result.total_datasheets == 3
        # At least the first one should succeed
        assert result.successful >= 1
        # Should have results for all
        assert len(result.results) == 3

    def test_import_batch_aggregates_node_counts(
        self, minimal_datasheet, datasheet_with_pins, mock_config
    ) -> None:
        """Verify graph.stats() reflects correct node count after batch import."""
        graph = KnowledgeGraph()
        base_nodes = graph.stats()["node_count"]
        datasheets = [minimal_datasheet, datasheet_with_pins]

        result = import_batch(datasheets, graph, mock_config)

        # minimal: 1 node (component)
        # with_pins: 4 nodes (component + 3 pins)
        # Total: 5 nodes
        expected_nodes = 1 + 4

        # Check batch result totals
        assert result.total_nodes_created == expected_nodes

        # Verify with graph stats
        stats = graph.stats()
        assert stats["node_count"] == base_nodes + expected_nodes

    def test_import_batch_tracks_edges_correctly(
        self, datasheet_with_pins, datasheet_with_electrical_params, mock_config
    ) -> None:
        """Verify batch import tracks total edges created correctly."""
        graph = KnowledgeGraph()
        base_edges = graph.stats()["edge_count"]
        datasheets = [datasheet_with_pins, datasheet_with_electrical_params]

        result = import_batch(datasheets, graph, mock_config)

        # pins: 3 edges (component → each pin)
        # electrical: 2 edges (component → each property)
        expected_edges = 3 + 2

        assert result.total_edges_created == expected_edges

        # Verify with graph stats
        stats = graph.stats()
        assert stats["edge_count"] == base_edges + expected_edges

    def test_batch_result_includes_individual_results(
        self, minimal_datasheet, datasheet_with_pins, mock_config
    ) -> None:
        """Verify BatchImportResult includes individual ImportResult objects."""
        graph = KnowledgeGraph()
        datasheets = [minimal_datasheet, datasheet_with_pins]

        result = import_batch(datasheets, graph, mock_config)

        assert len(result.results) == 2

        # Check first result
        assert result.results[0].component_id == "TPS62933DRLR"
        assert result.results[0].success is True

        # Check second result
        assert result.results[1].component_id == "LM358"
        assert result.results[1].success is True


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestImportEdgeCases:
    """Tests for edge cases and error handling."""

    def test_import_handles_datasheet_with_many_pins(self, mock_config) -> None:
        """Test import handles component with many pins (e.g., 48-pin QFP)."""
        pins = [
            PinDefinition(
                pin_number=str(i),
                raw_name=f"PIN{i}",
                pin_type="io",
            )
            for i in range(1, 49)
        ]

        datasheet = ComponentDatasheet(
            component_id="MCU48PIN",
            manufacturer="STMicro",
            description="48-pin MCU",
            package="LQFP-48",
            source_pdf_hash="mcu_hash",
            extraction_method=ExtractionMethod.P1_VECTOR,
            extraction_confidence=0.96,
            pins=pins,
            created_at="2024-01-15T10:30:00Z",
        )

        graph = KnowledgeGraph()
        result = import_datasheet(datasheet, graph, mock_config)

        # 1 component + 48 pins = 49 nodes
        assert result.nodes_created == 49
        assert result.edges_created == 48  # 48 edges to pins

        # Verify all pins exist
        for i in range(1, 49):
            assert graph.get_node(f"pin:MCU48PIN:{i}") is not None

    def test_import_handles_duplicate_pins_idempotently(
        self, datasheet_with_pins, mock_config
    ) -> None:
        """Test re-importing same datasheet doesn't create duplicate pin nodes."""
        graph = KnowledgeGraph()

        # First import
        import_datasheet(datasheet_with_pins, graph, mock_config)
        initial_count = graph.stats()["node_count"]

        # Second import
        result2 = import_datasheet(datasheet_with_pins, graph, mock_config)

        # Should have tracked duplicates
        assert result2.skipped_duplicates >= 4  # component + 3 pins

        # Count should not increase
        final_count = graph.stats()["node_count"]
        assert final_count == initial_count

    def test_import_preserves_pin_normalized_function_none(
        self, mock_config
    ) -> None:
        """Test that pins with normalized_function=None are handled correctly."""
        datasheet = ComponentDatasheet(
            component_id="TESTCHIP",
            manufacturer="Test",
            description="Test chip",
            package="SOT-23",
            source_pdf_hash="test_hash",
            extraction_method=ExtractionMethod.P1_VECTOR,
            extraction_confidence=0.95,
            pins=[
                PinDefinition(
                    pin_number="1",
                    raw_name="GPIO1",
                    pin_type="io",
                    normalized_function=None,  # Explicitly None per Rule 3
                    normalization_confidence=None,
                ),
            ],
            created_at="2024-01-15T10:30:00Z",
        )

        graph = KnowledgeGraph()
        import_datasheet(datasheet, graph, mock_config)

        pin_node = graph.get_node("pin:TESTCHIP:1")
        assert pin_node is not None
        # normalized_function should not be in properties when None
        # or should be None if present
        if "normalized_function" in pin_node.properties:
            assert pin_node.properties["normalized_function"] is None
