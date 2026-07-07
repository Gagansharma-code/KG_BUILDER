"""Unit tests for src/schemas/kg.py.

Tests knowledge graph schema models, enums, confidence mapping,
and validation constraints.
"""

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.schemas.datasheet import ExtractionMethod
from src.schemas.kg import (
    EXTRACTION_METHOD_CONFIDENCE,
    ComponentSearchResult,
    DesignSubgraph,
    KGEdge,
    KGNode,
    KGNodeType,
    KGRelation,
)


# =============================================================================
# EXTRACTION_METHOD_CONFIDENCE Tests
# =============================================================================


class TestExtractionMethodConfidenceMapping:
    """Tests for EXTRACTION_METHOD_CONFIDENCE mapping."""

    def test_has_all_extraction_method_values(self) -> None:
        """Test that EXTRACTION_METHOD_CONFIDENCE has entries for all ExtractionMethod values."""
        for method in ExtractionMethod:
            assert method in EXTRACTION_METHOD_CONFIDENCE, (
                f"Missing confidence mapping for {method.value}"
            )

    def test_manual_has_max_confidence(self) -> None:
        """Test that MANUAL extraction has highest confidence (1.0)."""
        assert EXTRACTION_METHOD_CONFIDENCE[ExtractionMethod.MANUAL] == 1.0

    def test_confidence_decreases_with_reliability(self) -> None:
        """Test confidence decreases as extraction method becomes less reliable."""
        manual = EXTRACTION_METHOD_CONFIDENCE[ExtractionMethod.MANUAL]
        vector = EXTRACTION_METHOD_CONFIDENCE[ExtractionMethod.P1_VECTOR]
        vlm = EXTRACTION_METHOD_CONFIDENCE[ExtractionMethod.P1_VLM]
        nlp = EXTRACTION_METHOD_CONFIDENCE[ExtractionMethod.P1_PHASE5_NLP]
        fallback = EXTRACTION_METHOD_CONFIDENCE[ExtractionMethod.LLM_FALLBACK]

        assert manual > vector > vlm > nlp > fallback

    def test_p1_vector_confidence_value(self) -> None:
        """Test P1_VECTOR has expected confidence of 0.97."""
        assert EXTRACTION_METHOD_CONFIDENCE[ExtractionMethod.P1_VECTOR] == 0.97

    def test_p1_vlm_confidence_value(self) -> None:
        """Test P1_VLM has expected confidence of 0.85."""
        assert EXTRACTION_METHOD_CONFIDENCE[ExtractionMethod.P1_VLM] == 0.85

    def test_p1_phase5_nlp_confidence_value(self) -> None:
        """Test P1_PHASE5_NLP has expected confidence of 0.80."""
        assert EXTRACTION_METHOD_CONFIDENCE[ExtractionMethod.P1_PHASE5_NLP] == 0.80

    def test_llm_fallback_confidence_value(self) -> None:
        """Test LLM_FALLBACK has expected confidence of 0.72."""
        assert EXTRACTION_METHOD_CONFIDENCE[ExtractionMethod.LLM_FALLBACK] == 0.72

    def test_confidence_values_in_valid_range(self) -> None:
        """Test all confidence values are in [0.0, 1.0]."""
        for method, confidence in EXTRACTION_METHOD_CONFIDENCE.items():
            assert 0.0 <= confidence <= 1.0, (
                f"Confidence for {method.value} ({confidence}) outside [0.0, 1.0]"
            )


# =============================================================================
# KGNodeType Enum Tests
# =============================================================================


class TestKGNodeTypeEnum:
    """Tests for KGNodeType enum."""

    def test_all_expected_values_exist(self) -> None:
        """Test all expected node type values exist."""
        assert KGNodeType.PHYSICS_CONCEPT.value == "physics_concept"
        assert KGNodeType.COMPONENT_TYPE.value == "component_type"
        assert KGNodeType.COMPONENT_INSTANCE.value == "component_instance"
        assert KGNodeType.DESIGN_RECIPE.value == "design_recipe"
        assert KGNodeType.ELECTRICAL_PROPERTY.value == "electrical_property"
        assert KGNodeType.PLACEMENT_RULE.value == "placement_rule"
        assert KGNodeType.ROUTING_RULE.value == "routing_rule"
        assert KGNodeType.DESIGN_METHODOLOGY.value == "design_methodology"
        assert KGNodeType.NET_TYPE.value == "net_type"
        assert KGNodeType.STANDARD.value == "standard"
        assert KGNodeType.PIN.value == "pin"

    def test_total_count_of_node_types(self) -> None:
        """Test we have exactly 15 node types (11 original + TOPOLOGY,
        FUNCTIONAL_BLOCK, DESIGN_CONSTRAINT, PREDICTED_METRIC)."""
        assert len(list(KGNodeType)) == 15


# =============================================================================
# KGRelation Enum Tests
# =============================================================================


class TestKGRelationEnum:
    """Tests for KGRelation enum."""

    def test_all_expected_values_exist(self) -> None:
        """Test all expected relation values exist."""
        assert KGRelation.REQUIRES.value == "requires"
        assert KGRelation.USES.value == "uses"
        assert KGRelation.HAS_PROPERTY.value == "has_property"
        assert KGRelation.CONNECTS_TO.value == "connects_to"
        assert KGRelation.MUST_BE_NEAR.value == "must_be_near"
        assert KGRelation.MUST_AVOID.value == "must_avoid"
        assert KGRelation.IS_A.value == "is_a"
        assert KGRelation.GOVERNED_BY.value == "governed_by"
        assert KGRelation.REQUIRES_ROUTING.value == "requires_routing"
        assert KGRelation.PART_OF.value == "part_of"
        assert KGRelation.REPLACES.value == "replaces"
        assert KGRelation.INCOMPATIBLE_WITH.value == "incompatible_with"
        assert KGRelation.OVERRIDES.value == "overrides"

    def test_total_count_of_relations(self) -> None:
        """Test we have exactly 16 relation types (13 original + IMPLEMENTS,
        CONSTRAINED_BY, DERIVED_FROM)."""
        assert len(list(KGRelation)) == 16


# =============================================================================
# KGNode Tests
# =============================================================================


class TestKGNode:
    """Tests for KGNode model."""

    def test_valid_instantiation_all_fields(self) -> None:
        """Test valid instantiation with all fields populated."""
        now = datetime.now(timezone.utc).isoformat()
        node = KGNode(
            id="physics:ohms_law",
            node_type=KGNodeType.PHYSICS_CONCEPT,
            layer=1,
            label="Ohm's Law",
            properties={"formula": "V = I * R", "units": "V, A, Ω"},
            source="physics_textbook_v2023",
            confidence=1.0,
            extraction_method=ExtractionMethod.MANUAL,
            created_at=now,
        )
        assert node.id == "physics:ohms_law"
        assert node.node_type == KGNodeType.PHYSICS_CONCEPT
        assert node.layer == 1
        assert node.label == "Ohm's Law"
        assert node.properties["formula"] == "V = I * R"
        assert node.confidence == 1.0

    def test_json_round_trip(self) -> None:
        """Test KGNode round-trips JSON correctly."""
        now = datetime.now(timezone.utc).isoformat()
        original = KGNode(
            id="component:tps62933",
            node_type=KGNodeType.COMPONENT_INSTANCE,
            layer=3,
            label="TPS62933DRLR",
            properties={
                "manufacturer": "Texas Instruments",
                "package": "SOT-23-5",
                "v_in_max": 30.0,
            },
            source="https://www.ti.com/lit/ds/symlink/tps62933.pdf",
            confidence=0.97,
            extraction_method=ExtractionMethod.P1_VECTOR,
            created_at=now,
        )

        # Serialize to JSON
        json_str = original.model_dump_json()

        # Deserialize from JSON
        restored = KGNode.model_validate_json(json_str)

        # Verify all fields preserved
        assert restored.id == original.id
        assert restored.node_type == original.node_type
        assert restored.layer == original.layer
        assert restored.label == original.label
        assert restored.properties == original.properties
        assert restored.source == original.source
        assert restored.confidence == original.confidence
        assert restored.extraction_method == original.extraction_method
        assert restored.created_at == original.created_at

    def test_python_dict_round_trip(self) -> None:
        """Test KGNode round-trips through Python dict correctly."""
        now = datetime.now(timezone.utc).isoformat()
        original = KGNode(
            id="recipe:buck_regulator_design",
            node_type=KGNodeType.DESIGN_RECIPE,
            layer=4,
            label="Buck Regulator Component Selection",
            properties={"input_voltage_range": "3.8V-30V", "output_current": "3A"},
            source="ti_app_note_slvae12",
            confidence=0.85,
            extraction_method=ExtractionMethod.P1_VLM,
            created_at=now,
        )

        # Convert to dict
        data_dict = original.model_dump()

        # Restore from dict
        restored = KGNode.model_validate(data_dict)

        assert restored.id == original.id
        assert restored.properties == original.properties

    def test_layer_boundary_valid(self) -> None:
        """Test layer field accepts valid boundaries 1 and 5."""
        now = datetime.now(timezone.utc).isoformat()

        # Layer 1 (physics)
        node_1 = KGNode(
            id="physics:kirchhoff_voltage",
            node_type=KGNodeType.PHYSICS_CONCEPT,
            layer=1,
            label="Kirchhoff's Voltage Law",
            source="physics_textbook",
            confidence=1.0,
            extraction_method=ExtractionMethod.MANUAL,
            created_at=now,
        )
        assert node_1.layer == 1

        # Layer 5 (project)
        node_5 = KGNode(
            id="project:evb_v1_c1",
            node_type=KGNodeType.COMPONENT_INSTANCE,
            layer=5,
            label="C1 on EVB_v1",
            source="project_evb_v1.kicad_pcb",
            confidence=0.80,
            extraction_method=ExtractionMethod.P1_PHASE5_NLP,
            created_at=now,
        )
        assert node_5.layer == 5

    def test_layer_rejects_zero(self) -> None:
        """Test layer field rejects value 0 (below minimum)."""
        now = datetime.now(timezone.utc).isoformat()
        with pytest.raises(ValidationError) as exc_info:
            KGNode(
                id="test:invalid",
                node_type=KGNodeType.PHYSICS_CONCEPT,
                layer=0,  # Invalid: must be >= 1
                label="Invalid Layer Node",
                source="test",
                confidence=0.5,
                extraction_method=ExtractionMethod.P1_VECTOR,
                created_at=now,
            )
        assert "layer" in str(exc_info.value).lower()

    def test_layer_rejects_six(self) -> None:
        """Test layer field rejects value 6 (above maximum)."""
        now = datetime.now(timezone.utc).isoformat()
        with pytest.raises(ValidationError) as exc_info:
            KGNode(
                id="test:invalid",
                node_type=KGNodeType.PHYSICS_CONCEPT,
                layer=6,  # Invalid: must be <= 5
                label="Invalid Layer Node",
                source="test",
                confidence=0.5,
                extraction_method=ExtractionMethod.P1_VECTOR,
                created_at=now,
            )
        assert "layer" in str(exc_info.value).lower()

    def test_confidence_rejects_negative(self) -> None:
        """Test confidence field rejects negative values."""
        now = datetime.now(timezone.utc).isoformat()
        with pytest.raises(ValidationError) as exc_info:
            KGNode(
                id="test:invalid",
                node_type=KGNodeType.PHYSICS_CONCEPT,
                layer=1,
                label="Invalid Confidence",
                source="test",
                confidence=-0.1,  # Invalid
                extraction_method=ExtractionMethod.P1_VECTOR,
                created_at=now,
            )
        assert "confidence" in str(exc_info.value).lower()

    def test_confidence_rejects_greater_than_one(self) -> None:
        """Test confidence field rejects values > 1.0."""
        now = datetime.now(timezone.utc).isoformat()
        with pytest.raises(ValidationError) as exc_info:
            KGNode(
                id="test:invalid",
                node_type=KGNodeType.PHYSICS_CONCEPT,
                layer=1,
                label="Invalid Confidence",
                source="test",
                confidence=1.01,  # Invalid
                extraction_method=ExtractionMethod.P1_VECTOR,
                created_at=now,
            )
        assert "confidence" in str(exc_info.value).lower()

    def test_confidence_at_boundaries(self) -> None:
        """Test confidence accepts exactly 0.0 and 1.0."""
        now = datetime.now(timezone.utc).isoformat()

        node_min = KGNode(
            id="test:min_conf",
            node_type=KGNodeType.PHYSICS_CONCEPT,
            layer=1,
            label="Min Confidence",
            source="test",
            confidence=0.0,
            extraction_method=ExtractionMethod.LLM_FALLBACK,
            created_at=now,
        )
        assert node_min.confidence == 0.0

        node_max = KGNode(
            id="test:max_conf",
            node_type=KGNodeType.PHYSICS_CONCEPT,
            layer=1,
            label="Max Confidence",
            source="test",
            confidence=1.0,
            extraction_method=ExtractionMethod.MANUAL,
            created_at=now,
        )
        assert node_max.confidence == 1.0

    def test_properties_defaults_to_empty_dict(self) -> None:
        """Test properties field defaults to empty dict."""
        now = datetime.now(timezone.utc).isoformat()
        node = KGNode(
            id="test:default_props",
            node_type=KGNodeType.NET_TYPE,
            layer=2,
            label="Power Net",
            source="test",
            confidence=0.9,
            extraction_method=ExtractionMethod.P1_VECTOR,
            created_at=now,
        )
        assert node.properties == {}

    def test_get_confidence_from_method_returns_correct_value(self) -> None:
        """Test get_confidence_from_method helper returns correct value."""
        now = datetime.now(timezone.utc).isoformat()

        node_manual = KGNode(
            id="test:manual",
            node_type=KGNodeType.STANDARD,
            layer=1,
            label="IPC Standard",
            source="ipc_7351",
            confidence=1.0,
            extraction_method=ExtractionMethod.MANUAL,
            created_at=now,
        )
        assert node_manual.get_confidence_from_method() == 1.0

        node_vector = KGNode(
            id="test:vector",
            node_type=KGNodeType.COMPONENT_TYPE,
            layer=2,
            label="Regulator",
            source="datasheet",
            confidence=0.97,
            extraction_method=ExtractionMethod.P1_VECTOR,
            created_at=now,
        )
        assert node_vector.get_confidence_from_method() == 0.97

    def test_all_extraction_methods_in_kgnode(self) -> None:
        """Test KGNode accepts all ExtractionMethod values."""
        now = datetime.now(timezone.utc).isoformat()

        for method in ExtractionMethod:
            node = KGNode(
                id=f"test:{method.value}",
                node_type=KGNodeType.COMPONENT_TYPE,
                layer=2,
                label=f"Test {method.value}",
                source="test",
                confidence=EXTRACTION_METHOD_CONFIDENCE[method],
                extraction_method=method,
                created_at=now,
            )
            assert node.extraction_method == method


# =============================================================================
# KGEdge Tests
# =============================================================================


class TestKGEdge:
    """Tests for KGEdge model."""

    def test_valid_instantiation_all_fields(self) -> None:
        """Test valid instantiation with all fields populated."""
        edge = KGEdge(
            source_id="component:tps62933",
            relation=KGRelation.REQUIRES,
            target_id="component:input_capacitor",
            constraints={"min_capacitance_uf": 10.0, "esr_max_mohm": 100},
            source_document="TI_TPS62933_datasheet.pdf",
            confidence=0.85,
            layer=3,
        )
        assert edge.source_id == "component:tps62933"
        assert edge.relation == KGRelation.REQUIRES
        assert edge.target_id == "component:input_capacitor"
        assert edge.constraints["min_capacitance_uf"] == 10.0
        assert edge.confidence == 0.85

    def test_json_round_trip(self) -> None:
        """Test KGEdge round-trips JSON correctly."""
        original = KGEdge(
            source_id="pin:tps62933_vin",
            relation=KGRelation.CONNECTS_TO,
            target_id="net:vcc_3v3",
            constraints={"max_impedance_mohm": 50},
            source_document="schematic_v1.pdf",
            confidence=0.95,
            layer=4,
        )

        json_str = original.model_dump_json()
        restored = KGEdge.model_validate_json(json_str)

        assert restored.source_id == original.source_id
        assert restored.relation == original.relation
        assert restored.target_id == original.target_id
        assert restored.constraints == original.constraints
        assert restored.source_document == original.source_document
        assert restored.confidence == original.confidence
        assert restored.layer == original.layer

    def test_constraints_defaults_to_empty_dict(self) -> None:
        """Test constraints field defaults to empty dict."""
        edge = KGEdge(
            source_id="type:regulator",
            relation=KGRelation.IS_A,
            target_id="type:power_ic",
            source_document="ontology_v1",
            confidence=0.99,
            layer=2,
        )
        assert edge.constraints == {}

    def test_layer_rejects_zero(self) -> None:
        """Test KGEdge layer field rejects value 0 (below minimum)."""
        with pytest.raises(ValidationError) as exc_info:
            KGEdge(
                source_id="test:source",
                relation=KGRelation.REQUIRES,
                target_id="test:target",
                source_document="test",
                confidence=0.5,
                layer=0,  # Invalid: must be >= 1
            )
        assert "layer" in str(exc_info.value).lower()

    def test_layer_rejects_six(self) -> None:
        """Test KGEdge layer field rejects value 6 (above maximum)."""
        with pytest.raises(ValidationError) as exc_info:
            KGEdge(
                source_id="test:source",
                relation=KGRelation.REQUIRES,
                target_id="test:target",
                source_document="test",
                confidence=0.5,
                layer=6,  # Invalid: must be <= 5
            )
        assert "layer" in str(exc_info.value).lower()

    def test_layer_boundary_valid(self) -> None:
        """Test KGEdge layer field accepts valid boundaries 1 and 5."""
        # Layer 1
        edge_1 = KGEdge(
            source_id="concept:ohms_law",
            relation=KGRelation.GOVERNED_BY,
            target_id="standard:physics_fundamentals",
            source_document="physics_textbook",
            confidence=1.0,
            layer=1,
        )
        assert edge_1.layer == 1

        # Layer 5
        edge_5 = KGEdge(
            source_id="project:c1_placement",
            relation=KGRelation.MUST_BE_NEAR,
            target_id="project:u1_vin",
            constraints={"max_distance_mm": 5.0},
            source_document="layout_recommendations.pdf",
            confidence=0.80,
            layer=5,
        )
        assert edge_5.layer == 5

    def test_confidence_rejects_negative(self) -> None:
        """Test KGEdge confidence field rejects negative values."""
        with pytest.raises(ValidationError) as exc_info:
            KGEdge(
                source_id="test:source",
                relation=KGRelation.REQUIRES,
                target_id="test:target",
                source_document="test",
                confidence=-0.1,  # Invalid
                layer=3,
            )
        assert "confidence" in str(exc_info.value).lower()

    def test_confidence_rejects_greater_than_one(self) -> None:
        """Test KGEdge confidence field rejects values > 1.0."""
        with pytest.raises(ValidationError) as exc_info:
            KGEdge(
                source_id="test:source",
                relation=KGRelation.REQUIRES,
                target_id="test:target",
                source_document="test",
                confidence=1.01,  # Invalid
                layer=3,
            )
        assert "confidence" in str(exc_info.value).lower()

    def test_all_relations_valid_in_kgedge(self) -> None:
        """Test KGEdge accepts all KGRelation values."""
        for relation in KGRelation:
            edge = KGEdge(
                source_id=f"test:source_{relation.value}",
                relation=relation,
                target_id=f"test:target_{relation.value}",
                source_document="test",
                confidence=0.9,
                layer=3,
            )
            assert edge.relation == relation


# =============================================================================
# Integration Tests
# =============================================================================


class TestKnowledgeGraphIntegration:
    """Integration tests for building a knowledge graph with nodes and edges."""

    def test_build_simple_knowledge_graph(self) -> None:
        """Test building a simple knowledge graph with nodes and edges."""
        now = datetime.now(timezone.utc).isoformat()

        # Create layer 1 node: physics concept
        ohms_law = KGNode(
            id="physics:ohms_law",
            node_type=KGNodeType.PHYSICS_CONCEPT,
            layer=1,
            label="Ohm's Law",
            properties={"formula": "V = I * R"},
            source="physics_textbook",
            confidence=1.0,
            extraction_method=ExtractionMethod.MANUAL,
            created_at=now,
        )

        # Create layer 2 node: component type
        resistor = KGNode(
            id="type:resistor",
            node_type=KGNodeType.COMPONENT_TYPE,
            layer=2,
            label="Resistor",
            properties={"category": "passive"},
            source="component_taxonomy",
            confidence=0.99,
            extraction_method=ExtractionMethod.MANUAL,
            created_at=now,
        )

        # Create layer 3 node: component instance
        r1 = KGNode(
            id="instance:r1_10k",
            node_type=KGNodeType.COMPONENT_INSTANCE,
            layer=3,
            label="R1 (10kΩ)",
            properties={"resistance_ohm": 10000, "tolerance": "1%"},
            source="schematic_v1.pdf",
            confidence=0.97,
            extraction_method=ExtractionMethod.P1_VECTOR,
            created_at=now,
        )

        # Create edges
        edge_is_a = KGEdge(
            source_id="type:resistor",
            relation=KGRelation.IS_A,
            target_id="physics:ohms_law",
            source_document="physics_taxonomy",
            confidence=1.0,
            layer=2,
        )

        edge_instance_of = KGEdge(
            source_id="instance:r1_10k",
            relation=KGRelation.IS_A,
            target_id="type:resistor",
            source_document="schematic_v1.pdf",
            confidence=0.97,
            layer=3,
        )

        # Verify graph structure
        assert ohms_law.layer == 1
        assert resistor.layer == 2
        assert r1.layer == 3
        assert edge_is_a.source_id == resistor.id
        assert edge_is_a.target_id == ohms_law.id
        assert edge_instance_of.source_id == r1.id

    def test_full_graph_serialization(self) -> None:
        """Test serializing a complete knowledge graph to JSON."""
        now = datetime.now(timezone.utc).isoformat()

        # Build a buck regulator design recipe
        v_in_range = KGNode(
            id="property:v_in_range",
            node_type=KGNodeType.ELECTRICAL_PROPERTY,
            layer=2,
            label="Input Voltage Range",
            properties={"min_v": 3.8, "max_v": 30.0},
            source="TPS62933_datasheet",
            confidence=0.97,
            extraction_method=ExtractionMethod.P1_VECTOR,
            created_at=now,
        )

        tps62933 = KGNode(
            id="component:tps62933",
            node_type=KGNodeType.COMPONENT_INSTANCE,
            layer=3,
            label="TPS62933DRLR",
            properties={"manufacturer": "TI", "package": "SOT-23-5"},
            source="https://www.ti.com/lit/ds/symlink/tps62933.pdf",
            confidence=0.97,
            extraction_method=ExtractionMethod.P1_VECTOR,
            created_at=now,
        )

        edge_has_property = KGEdge(
            source_id="component:tps62933",
            relation=KGRelation.HAS_PROPERTY,
            target_id="property:v_in_range",
            source_document="TPS62933_datasheet",
            confidence=0.97,
            layer=3,
        )

        # Serialize and verify
        nodes_json = [v_in_range.model_dump(), tps62933.model_dump()]
        edges_json = [edge_has_property.model_dump()]

        # Verify JSON structure
        assert nodes_json[0]["id"] == "property:v_in_range"
        assert edges_json[0]["relation"] == "has_property"

        # Deserialize and verify
        restored_vin = KGNode.model_validate(nodes_json[0])
        restored_edge = KGEdge.model_validate(edges_json[0])

        assert restored_vin.properties["min_v"] == 3.8
        assert restored_edge.relation == KGRelation.HAS_PROPERTY

    def test_use_confidence_mapping_in_nodes(self) -> None:
        """Test using EXTRACTION_METHOD_CONFIDENCE to set node confidence."""
        now = datetime.now(timezone.utc).isoformat()

        # Create node using the confidence mapping
        method = ExtractionMethod.P1_VLM
        expected_confidence = EXTRACTION_METHOD_CONFIDENCE[method]

        node = KGNode(
            id="test:confidence_mapping",
            node_type=KGNodeType.PLACEMENT_RULE,
            layer=4,
            label="Decoupling Capacitor Placement",
            properties={"max_distance_mm": 5.0},
            source="layout_recommendations.pdf",
            confidence=expected_confidence,
            extraction_method=method,
            created_at=now,
        )

        assert node.confidence == 0.85
        assert node.get_confidence_from_method() == expected_confidence


# =============================================================================
# DesignSubgraph Tests
# =============================================================================


class TestDesignSubgraph:
    """Tests for DesignSubgraph model."""

    def test_has_specific_parts_returns_false_when_empty(self) -> None:
        """Test DesignSubgraph.has_specific_parts() returns False when component_instances is empty."""
        subgraph = DesignSubgraph(
            component_types=[],
            component_instances=[],
            design_rules=[],
            placement_rules=[],
            routing_hints=[],
            design_methodology="power_regulation",
            query_depth=3,
        )
        assert subgraph.has_specific_parts() is False

    def test_has_specific_parts_returns_true_with_instances(self) -> None:
        """Test has_specific_parts returns True when component_instances is non-empty."""
        now = datetime.now(timezone.utc).isoformat()
        instance_node = KGNode(
            id="component:tps62933",
            node_type=KGNodeType.COMPONENT_INSTANCE,
            layer=3,
            label="TPS62933DRLR",
            source="ti.com",
            confidence=0.97,
            extraction_method=ExtractionMethod.P1_VECTOR,
            created_at=now,
        )
        subgraph = DesignSubgraph(
            component_types=[],
            component_instances=[instance_node],
            design_rules=[],
            placement_rules=[],
            routing_hints=[],
            design_methodology="power_regulation",
            query_depth=3,
        )
        assert subgraph.has_specific_parts() is True

    def test_min_path_confidence_returns_zero_for_empty_dict(self) -> None:
        """Test DesignSubgraph.min_path_confidence() returns 0.0 for empty dict."""
        subgraph = DesignSubgraph(
            component_types=[],
            component_instances=[],
            design_rules=[],
            placement_rules=[],
            routing_hints=[],
            design_methodology="analog_filter",
            path_confidences={},
            query_depth=2,
        )
        assert subgraph.min_path_confidence() == 0.0

    def test_min_path_confidence_returns_minimum_value(self) -> None:
        """Test min_path_confidence returns the minimum confidence value."""
        subgraph = DesignSubgraph(
            component_types=[],
            component_instances=[],
            design_rules=[],
            placement_rules=[],
            routing_hints=[],
            design_methodology="adc_interface",
            path_confidences={
                "node_1": 0.95,
                "node_2": 0.72,
                "node_3": 0.88,
            },
            query_depth=4,
        )
        assert subgraph.min_path_confidence() == 0.72

    def test_design_subgraph_json_round_trip(self) -> None:
        """Test DesignSubgraph round-trips to JSON correctly."""
        now = datetime.now(timezone.utc).isoformat()

        component_type = KGNode(
            id="type:buck_regulator",
            node_type=KGNodeType.COMPONENT_TYPE,
            layer=2,
            label="Buck Regulator",
            source="ontology",
            confidence=0.99,
            extraction_method=ExtractionMethod.MANUAL,
            created_at=now,
        )

        design_rule = KGEdge(
            source_id="type:buck_regulator",
            relation=KGRelation.REQUIRES,
            target_id="type:input_capacitor",
            constraints={"min_capacitance_uf": 10.0},
            source_document="design_rules.pdf",
            confidence=0.85,
            layer=3,
        )

        original = DesignSubgraph(
            component_types=[component_type],
            component_instances=[],
            design_rules=[design_rule],
            placement_rules=[],
            routing_hints=[],
            design_methodology="power_supply_design",
            path_confidences={"type:buck_regulator": 0.99, "type:input_capacitor": 0.85},
            query_depth=2,
            query_metadata={"execution_time_ms": 150},
        )

        # Serialize to JSON
        json_str = original.model_dump_json()

        # Deserialize
        restored = DesignSubgraph.model_validate_json(json_str)

        # Verify
        assert restored.design_methodology == original.design_methodology
        assert restored.query_depth == original.query_depth
        assert restored.path_confidences == original.path_confidences
        assert len(restored.component_types) == 1
        assert len(restored.design_rules) == 1
        assert restored.has_specific_parts() == original.has_specific_parts()
        assert restored.min_path_confidence() == original.min_path_confidence()

    def test_design_subgraph_validates_query_depth_constraint(self) -> None:
        """Test query_depth field rejects negative values."""
        with pytest.raises(ValidationError) as exc_info:
            DesignSubgraph(
                component_types=[],
                component_instances=[],
                design_rules=[],
                placement_rules=[],
                routing_hints=[],
                design_methodology="test",
                query_depth=-1,  # Invalid: must be >= 0
            )
        assert "query_depth" in str(exc_info.value).lower()

    def test_design_subgraph_empty_lists_default(self) -> None:
        """Test DesignSubgraph lists default to empty."""
        subgraph = DesignSubgraph(
            design_methodology="test_methodology",
            query_depth=1,
        )
        assert subgraph.component_types == []
        assert subgraph.component_instances == []
        assert subgraph.design_rules == []
        assert subgraph.placement_rules == []
        assert subgraph.routing_hints == []


# =============================================================================
# ComponentSearchResult Tests
# =============================================================================


class TestComponentSearchResult:
    """Tests for ComponentSearchResult model."""

    def test_valid_instantiation(self) -> None:
        """Test valid instantiation of ComponentSearchResult."""
        now = datetime.now(timezone.utc).isoformat()
        node = KGNode(
            id="component:lm358",
            node_type=KGNodeType.COMPONENT_INSTANCE,
            layer=3,
            label="LM358 Dual Op-Amp",
            source="datasheet.pdf",
            confidence=0.95,
            extraction_method=ExtractionMethod.P1_VECTOR,
            created_at=now,
        )
        result = ComponentSearchResult(
            node=node,
            similarity_score=0.92,
            matching_properties=["manufacturer", "package"],
        )
        assert result.node.id == "component:lm358"
        assert result.similarity_score == 0.92
        assert result.matching_properties == ["manufacturer", "package"]

    def test_similarity_score_bounds(self) -> None:
        """Test similarity_score must be in [0.0, 1.0]."""
        now = datetime.now(timezone.utc).isoformat()
        node = KGNode(
            id="test:node",
            node_type=KGNodeType.COMPONENT_TYPE,
            layer=2,
            label="Test",
            source="test",
            confidence=0.9,
            extraction_method=ExtractionMethod.MANUAL,
            created_at=now,
        )

        # Valid boundaries
        result_0 = ComponentSearchResult(node=node, similarity_score=0.0)
        assert result_0.similarity_score == 0.0

        result_1 = ComponentSearchResult(node=node, similarity_score=1.0)
        assert result_1.similarity_score == 1.0

        # Invalid: negative
        with pytest.raises(ValidationError):
            ComponentSearchResult(node=node, similarity_score=-0.1)

        # Invalid: > 1.0
        with pytest.raises(ValidationError):
            ComponentSearchResult(node=node, similarity_score=1.01)

    def test_matching_properties_defaults_to_empty(self) -> None:
        """Test matching_properties defaults to empty list."""
        now = datetime.now(timezone.utc).isoformat()
        node = KGNode(
            id="component:test",
            node_type=KGNodeType.COMPONENT_TYPE,
            layer=2,
            label="Test Component",
            source="test",
            confidence=0.9,
            extraction_method=ExtractionMethod.MANUAL,
            created_at=now,
        )
        result = ComponentSearchResult(node=node, similarity_score=0.75)
        assert result.matching_properties == []

    def test_component_search_result_json_round_trip(self) -> None:
        """Test ComponentSearchResult round-trips to JSON correctly."""
        now = datetime.now(timezone.utc).isoformat()
        node = KGNode(
            id="component:tps62933",
            node_type=KGNodeType.COMPONENT_INSTANCE,
            layer=3,
            label="TPS62933DRLR",
            properties={"manufacturer": "TI", "package": "SOT-23-5"},
            source="ti.com/datasheet",
            confidence=0.97,
            extraction_method=ExtractionMethod.P1_VECTOR,
            created_at=now,
        )
        original = ComponentSearchResult(
            node=node,
            similarity_score=0.88,
            matching_properties=["voltage_rating", "current_rating", "package"],
        )

        json_str = original.model_dump_json()
        restored = ComponentSearchResult.model_validate_json(json_str)

        assert restored.node.id == original.node.id
        assert restored.node.node_type == original.node.node_type
        assert restored.node.properties == original.node.properties
        assert restored.similarity_score == original.similarity_score
        assert restored.matching_properties == original.matching_properties
