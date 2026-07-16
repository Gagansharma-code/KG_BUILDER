"""Unit tests for src/schemas/datasheet.py.

Tests all Pydantic models for correct instantiation, JSON round-tripping,
validation constraints, and helper methods.
"""

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.schemas.datasheet import (
    AbsoluteMaxRating,
    AlternateFunction,
    ComponentDatasheet,
    ElectricalParameter,
    ExtractionMethod,
    ExtractedValue,
    PinDefinition,
    PlacementConstraint,
    TableSectionType,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def valid_extracted_value() -> ExtractedValue:
    """Valid ExtractedValue instance."""
    return ExtractedValue(
        raw_text="3.3V",
        normalized_value=3.3,
        unit="V",
        typ_val=3.3,
        confidence=0.95,
    )


@pytest.fixture
def valid_electrical_parameter(valid_extracted_value: ExtractedValue) -> ElectricalParameter:
    """Valid ElectricalParameter instance."""
    return ElectricalParameter(
        parameter_name="V_CC",
        symbol="V_CC",
        conditions="T_A = 25°C",
        value=valid_extracted_value,
        section_type=TableSectionType.ELECTRICAL_CHARACTERISTICS,
        source_page=3,
        source_table_index=0,
        review_required=False,
    )


@pytest.fixture
def valid_absolute_max_rating(valid_extracted_value: ExtractedValue) -> AbsoluteMaxRating:
    """Valid AbsoluteMaxRating instance."""
    value = ExtractedValue(
        raw_text="7.0V",
        normalized_value=7.0,
        unit="V",
        max_val=7.0,
        confidence=0.92,
    )
    return AbsoluteMaxRating(
        parameter_name="V_CC_ABS",
        symbol="V_CC_MAX",
        value=value,
        note="Stresses beyond this may damage device",
        source_page=2,
        review_required=False,
    )


@pytest.fixture
def three_pin_component() -> ComponentDatasheet:
    """ComponentDatasheet with 3 pins for testing lookup methods."""
    now = datetime.now(timezone.utc).isoformat()
    return ComponentDatasheet(
        component_id="TEST123",
        manufacturer="Test Corp",
        description="Test 3-pin voltage regulator",
        package="SOT-23-5",
        source_pdf_hash="a1b2c3d4e5f6789012345678901234567890abcd",
        pins=[
            PinDefinition(
                pin_number="1",
                raw_name="VIN",
                pin_type="power",
                description="Input voltage",
                source_page=4,
            ),
            PinDefinition(
                pin_number="2",
                raw_name="GND",
                pin_type="ground",
                description="Ground reference",
                source_page=4,
            ),
            PinDefinition(
                pin_number="3",
                raw_name="VOUT",
                pin_type="output",
                description="Regulated output",
                source_page=4,
            ),
        ],
        extraction_method=ExtractionMethod.P1_VECTOR,
        extraction_confidence=0.94,
        created_at=now,
    )


# =============================================================================
# Model Instantiation and JSON Round-Trip Tests
# =============================================================================


class TestExtractedValue:
    """Tests for ExtractedValue model."""

    def test_valid_instantiation(self) -> None:
        """Test valid instantiation with all fields."""
        ev = ExtractedValue(
            raw_text="100mA",
            normalized_value=0.1,
            unit="A",
            min_val=0.05,
            typ_val=0.1,
            max_val=0.15,
            footnote="(1) Guaranteed by design",
            confidence=0.88,
        )
        assert ev.raw_text == "100mA"
        assert ev.normalized_value == 0.1
        assert ev.unit == "A"
        assert ev.confidence == 0.88

    def test_json_round_trip(self) -> None:
        """Test serialization to/from JSON preserves all data."""
        original = ExtractedValue(
            raw_text="3300mV",
            normalized_value=3.3,
            unit="V",
            typ_val=3.3,
            confidence=0.97,
        )
        json_str = original.model_dump_json()
        restored = ExtractedValue.model_validate_json(json_str)

        assert restored.raw_text == original.raw_text
        assert restored.normalized_value == original.normalized_value
        assert restored.unit == original.unit
        assert restored.confidence == original.confidence

    def test_python_dict_round_trip(self) -> None:
        """Test serialization to/from dict preserves all data."""
        original = ExtractedValue(
            raw_text="-40°C to +125°C",
            normalized_value=25.0,
            unit="°C",
            min_val=-40.0,
            max_val=125.0,
            confidence=0.91,
        )
        data_dict = original.model_dump()
        restored = ExtractedValue.model_validate(data_dict)

        assert restored.raw_text == original.raw_text
        assert restored.min_val == original.min_val
        assert restored.max_val == original.max_val

    def test_confidence_at_boundaries(self) -> None:
        """Test confidence values at exactly 0.0 and 1.0 are valid."""
        # Boundary: 0.0
        ev_min = ExtractedValue(raw_text="test", confidence=0.0)
        assert ev_min.confidence == 0.0

        # Boundary: 1.0
        ev_max = ExtractedValue(raw_text="test", confidence=1.0)
        assert ev_max.confidence == 1.0

    def test_confidence_rejects_negative(self) -> None:
        """Test that negative confidence raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ExtractedValue(raw_text="test", confidence=-0.1)

        assert "confidence" in str(exc_info.value).lower()

    def test_confidence_rejects_greater_than_one(self) -> None:
        """Test that confidence > 1.0 raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ExtractedValue(raw_text="test", confidence=1.01)

        assert "confidence" in str(exc_info.value).lower()

    def test_optional_fields_defaults(self) -> None:
        """Test that optional fields default to None."""
        ev = ExtractedValue(raw_text="test", confidence=0.5)
        assert ev.normalized_value is None
        assert ev.unit is None
        assert ev.footnote is None


class TestElectricalParameter:
    """Tests for ElectricalParameter model."""

    def test_valid_instantiation(self, valid_extracted_value: ExtractedValue) -> None:
        """Test valid instantiation with all fields."""
        ep = ElectricalParameter(
            parameter_name="I_Q",
            symbol="I_Q",
            conditions="V_IN = 3.3V, I_OUT = 0mA, T_A = 25°C",
            value=valid_extracted_value,
            section_type=TableSectionType.ELECTRICAL_CHARACTERISTICS,
            source_page=5,
            source_table_index=1,
            review_required=True,
        )
        assert ep.parameter_name == "I_Q"
        assert ep.conditions is not None
        assert ep.source_page == 5

    def test_json_round_trip(self, valid_electrical_parameter: ElectricalParameter) -> None:
        """Test serialization to/from JSON preserves all data."""
        json_str = valid_electrical_parameter.model_dump_json()
        restored = ElectricalParameter.model_validate_json(json_str)

        assert restored.parameter_name == valid_electrical_parameter.parameter_name
        assert restored.section_type == valid_electrical_parameter.section_type
        assert restored.value.confidence == valid_electrical_parameter.value.confidence

    def test_source_page_must_be_positive(self, valid_extracted_value: ExtractedValue) -> None:
        """Test that source_page must be >= 1."""
        with pytest.raises(ValidationError) as exc_info:
            ElectricalParameter(
                parameter_name="TEST",
                value=valid_extracted_value,
                section_type=TableSectionType.ELECTRICAL_CHARACTERISTICS,
                source_page=0,  # Invalid: must be >= 1
                source_table_index=0,
            )

        assert "source_page" in str(exc_info.value).lower()


class TestAbsoluteMaxRating:
    """Tests for AbsoluteMaxRating model."""

    def test_valid_instantiation(self) -> None:
        """Test valid instantiation."""
        value = ExtractedValue(raw_text="150°C", max_val=150.0, unit="°C", confidence=0.93)
        amr = AbsoluteMaxRating(
            parameter_name="T_J_MAX",
            symbol="T_J",
            value=value,
            note="Junction temperature must not exceed",
            source_page=2,
            review_required=False,
        )
        assert amr.parameter_name == "T_J_MAX"
        assert amr.value.unit == "°C"

    def test_json_round_trip(self, valid_absolute_max_rating: AbsoluteMaxRating) -> None:
        """Test serialization to/from JSON."""
        json_str = valid_absolute_max_rating.model_dump_json()
        restored = AbsoluteMaxRating.model_validate_json(json_str)

        assert restored.parameter_name == valid_absolute_max_rating.parameter_name
        assert restored.value.max_val == valid_absolute_max_rating.value.max_val


class TestAlternateFunction:
    """Tests for AlternateFunction model."""

    def test_alternate_function_model(self) -> None:
        """Instantiate AlternateFunction and assert field schema."""
        af = AlternateFunction(name="SPI2_MOSI", af_index=5, peripheral="SPI2")
        assert af.name == "SPI2_MOSI"
        assert af.af_index == 5
        assert af.peripheral == "SPI2"

        minimal = AlternateFunction(name="UART_TX")
        assert minimal.name == "UART_TX"
        assert minimal.af_index is None
        assert minimal.peripheral is None


class TestPinDefinition:
    """Tests for PinDefinition model."""

    def test_valid_instantiation(self) -> None:
        """Test valid instantiation with alternate functions."""
        pin = PinDefinition(
            pin_number="5",
            raw_name="GPIO0/UART_TX/SPI_MOSI",
            normalized_function="GPIO0",
            normalization_confidence=0.89,
            normalization_method="exact_match",
            pin_type="io",
            description="General purpose I/O with multiplexed functions",
            alternate_functions=[
                AlternateFunction(name="UART_TX"),
                AlternateFunction(name="SPI_MOSI"),
            ],
            source_page=8,
        )
        assert pin.pin_number == "5"
        assert len(pin.alternate_functions) == 2
        assert pin.alternate_functions[0].name == "UART_TX"
        assert pin.alternate_functions[1].name == "SPI_MOSI"
        assert pin.normalized_function == "GPIO0"

    def test_json_round_trip(self) -> None:
        """Test serialization to/from JSON."""
        original = PinDefinition(
            pin_number="A1",
            raw_name="VDD",
            pin_type="power",
            source_page=10,
        )
        json_str = original.model_dump_json()
        restored = PinDefinition.model_validate_json(json_str)

        assert restored.pin_number == original.pin_number
        assert restored.raw_name == original.raw_name
        assert restored.alternate_functions == []  # Default

    def test_normalization_confidence_bounds(self) -> None:
        """Test normalization_confidence must be in [0.0, 1.0]."""
        # Valid: within bounds
        pin_valid = PinDefinition(
            pin_number="1",
            raw_name="TEST",
            normalization_confidence=0.75,
            source_page=1,
        )
        assert pin_valid.normalization_confidence == 0.75

        # Invalid: too high
        with pytest.raises(ValidationError):
            PinDefinition(
                pin_number="1",
                raw_name="TEST",
                normalization_confidence=1.5,
                source_page=1,
            )

        # Invalid: negative
        with pytest.raises(ValidationError):
            PinDefinition(
                pin_number="1",
                raw_name="TEST",
                normalization_confidence=-0.1,
                source_page=1,
            )

    def test_default_source_page_zero(self) -> None:
        """Test that source_page defaults to 0."""
        pin = PinDefinition(pin_number="1", raw_name="TEST")
        assert pin.source_page == 0


class TestPlacementConstraint:
    """Tests for PlacementConstraint model."""

    def test_valid_instantiation(self) -> None:
        """Test valid instantiation with all fields."""
        pc = PlacementConstraint(
            constraint_type="proximity",
            subject="U1.VIN",
            relative_to="C1",
            relative_to_type="component",
            max_distance_mm=10.0,
            min_distance_mm=1.0,
            layer="top",
            hard=True,
            source_sentence="Place decoupling capacitor within 10mm of VIN pin",
            confidence=0.87,
        )
        assert pc.constraint_type == "proximity"
        assert pc.relative_to_type == "component"
        assert pc.max_distance_mm == 10.0
        assert pc.hard is True

    def test_json_round_trip(self) -> None:
        """Test serialization to/from JSON."""
        original = PlacementConstraint(
            constraint_type="keepout",
            subject="U1",
            relative_to="board_edge",
            relative_to_type="board_edge",
            min_distance_mm=3.0,
            hard=False,
            source_sentence="Keep clear of board edge",
            confidence=0.82,
        )
        json_str = original.model_dump_json()
        restored = PlacementConstraint.model_validate_json(json_str)

        assert restored.constraint_type == original.constraint_type
        assert restored.relative_to_type == original.relative_to_type
        assert restored.hard == original.hard

    def test_relative_to_type_valid_values(self) -> None:
        """Test that valid relative_to_type values are accepted."""
        valid_types = ["component", "pin", "board_edge"]

        for rtt in valid_types:
            pc = PlacementConstraint(
                constraint_type="proximity",
                subject="U1",
                relative_to="target",
                relative_to_type=rtt,
                source_sentence=f"Test constraint relative to {rtt}",
                confidence=0.8,
            )
            assert pc.relative_to_type == rtt

    def test_relative_to_type_rejects_invalid(self) -> None:
        """Test that invalid relative_to_type raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            PlacementConstraint(
                constraint_type="proximity",
                subject="U1",
                relative_to="target",
                relative_to_type="invalid_type",  # Not in valid set
                confidence=0.8,
            )

        assert "relative_to_type" in str(exc_info.value)
        assert "must be one of" in str(exc_info.value)

    def test_relative_to_type_rejects_empty(self) -> None:
        """Test that empty relative_to_type raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            PlacementConstraint(
                constraint_type="proximity",
                subject="U1",
                relative_to="target",
                relative_to_type="",  # Empty string
                confidence=0.8,
            )

        assert "relative_to_type" in str(exc_info.value)

    def test_distance_bounds_validation(self) -> None:
        """Test that distance fields must be non-negative."""
        # Valid: zero
        pc_zero = PlacementConstraint(
            constraint_type="proximity",
            subject="U1",
            relative_to="C1",
            relative_to_type="component",
            source_sentence="Test zero distance constraint",
            min_distance_mm=0.0,
            confidence=0.8,
        )
        assert pc_zero.min_distance_mm == 0.0

        # Invalid: negative max_distance
        with pytest.raises(ValidationError) as exc_info:
            PlacementConstraint(
                constraint_type="proximity",
                subject="U1",
                relative_to="C1",
                relative_to_type="component",
                source_sentence="Test negative distance constraint",
                max_distance_mm=-5.0,
                confidence=0.8,
            )

        assert "max_distance_mm" in str(exc_info.value)

    def test_confidence_bounds(self) -> None:
        """Test confidence field bounds [0.0, 1.0]."""
        with pytest.raises(ValidationError):
            PlacementConstraint(
                constraint_type="proximity",
                subject="U1",
                relative_to="C1",
                relative_to_type="component",
                confidence=-0.1,
            )

        with pytest.raises(ValidationError):
            PlacementConstraint(
                constraint_type="proximity",
                subject="U1",
                relative_to="C1",
                relative_to_type="component",
                confidence=1.5,
            )


class TestComponentDatasheet:
    """Tests for ComponentDatasheet model."""

    def test_valid_instantiation(
        self,
        valid_electrical_parameter: ElectricalParameter,
        valid_absolute_max_rating: AbsoluteMaxRating,
    ) -> None:
        """Test valid instantiation with all fields."""
        now = datetime.now(timezone.utc).isoformat()
        ds = ComponentDatasheet(
            component_id="TPS62933DRLR",
            manufacturer="Texas Instruments",
            description="3.8-V to 30-V, 3-A buck converter",
            package="SOT-23-5",
            datasheet_url="https://www.ti.com/lit/ds/symlink/tps62933.pdf",
            source_pdf_hash="abc123def4567890abcdef1234567890abcdef12",
            electrical_parameters=[valid_electrical_parameter],
            absolute_max_ratings=[valid_absolute_max_rating],
            pins=[
                PinDefinition(pin_number="1", raw_name="VIN", pin_type="power"),
                PinDefinition(pin_number="2", raw_name="GND", pin_type="ground"),
            ],
            extraction_method=ExtractionMethod.P1_VLM,
            extraction_confidence=0.91,
            review_required=False,
            review_flags=["low_confidence_pinout"],
            pipeline_version="1.0.1",
            created_at=now,
        )
        assert ds.component_id == "TPS62933DRLR"
        assert len(ds.electrical_parameters) == 1
        assert len(ds.pins) == 2
        assert ds.extraction_confidence == 0.91

    def test_json_round_trip(self, three_pin_component: ComponentDatasheet) -> None:
        """Test serialization to/from JSON preserves all data."""
        json_str = three_pin_component.model_dump_json()
        restored = ComponentDatasheet.model_validate_json(json_str)

        assert restored.component_id == three_pin_component.component_id
        assert restored.manufacturer == three_pin_component.manufacturer
        assert len(restored.pins) == len(three_pin_component.pins)
        assert restored.created_at == three_pin_component.created_at

    def test_json_file_round_trip(self, three_pin_component: ComponentDatasheet, tmp_path) -> None:
        """Test serialization to/from JSON file."""
        json_path = tmp_path / "test_datasheet.json"

        # Write to file
        with open(json_path, "w") as f:
            json.dump(three_pin_component.model_dump(), f, indent=2)

        # Read from file
        with open(json_path) as f:
            data = json.load(f)
        restored = ComponentDatasheet.model_validate(data)

        assert restored.component_id == three_pin_component.component_id

    def test_default_empty_lists(self) -> None:
        """Test that list fields default to empty lists."""
        now = datetime.now(timezone.utc).isoformat()
        ds = ComponentDatasheet(
            component_id="MINIMAL",
            manufacturer="Test",
            description="Minimal component",
            package="0402",
            source_pdf_hash="0000",
            extraction_method=ExtractionMethod.MANUAL,
            extraction_confidence=1.0,
            created_at=now,
        )
        assert ds.electrical_parameters == []
        assert ds.absolute_max_ratings == []
        assert ds.pins == []
        assert ds.layout_constraints == []
        assert ds.review_flags == []

    def test_default_pipeline_version(self) -> None:
        """Test that pipeline_version defaults to '2.0'."""
        now = datetime.now(timezone.utc).isoformat()
        ds = ComponentDatasheet(
            component_id="TEST",
            manufacturer="Test",
            description="Test",
            package="0603",
            source_pdf_hash="1111",
            extraction_method=ExtractionMethod.P1_VECTOR,
            extraction_confidence=0.95,
            created_at=now,
        )
        assert ds.pipeline_version == "2.0"

    def test_default_review_required_false(self) -> None:
        """Test that review_required defaults to False."""
        now = datetime.now(timezone.utc).isoformat()
        ds = ComponentDatasheet(
            component_id="TEST",
            manufacturer="Test",
            description="Test",
            package="0805",
            source_pdf_hash="2222",
            extraction_method=ExtractionMethod.P1_VECTOR,
            extraction_confidence=0.95,
            created_at=now,
        )
        assert ds.review_required is False

    def test_extraction_confidence_bounds(self) -> None:
        """Test extraction_confidence must be in [0.0, 1.0]."""
        now = datetime.now(timezone.utc).isoformat()

        # Valid bounds
        ds_valid = ComponentDatasheet(
            component_id="TEST",
            manufacturer="Test",
            description="Test",
            package="SOT-23-5",
            source_pdf_hash="3333",
            extraction_method=ExtractionMethod.P1_VECTOR,
            extraction_confidence=0.0,
            created_at=now,
        )
        assert ds_valid.extraction_confidence == 0.0

        # Invalid: too high
        with pytest.raises(ValidationError):
            ComponentDatasheet(
                component_id="TEST",
                manufacturer="Test",
                description="Test",
                package="SOT-23-5",
                source_pdf_hash="3333",
                extraction_method=ExtractionMethod.P1_VECTOR,
                extraction_confidence=1.5,
                created_at=now,
            )

    def test_has_layout_constraints_true(self) -> None:
        """Test has_layout_constraints returns True when constraints exist."""
        now = datetime.now(timezone.utc).isoformat()
        ds = ComponentDatasheet(
            component_id="TEST",
            manufacturer="Test",
            description="Test",
            package="SOT-23-5",
            source_pdf_hash="4444",
            layout_constraints=[
                PlacementConstraint(
                    constraint_type="proximity",
                    subject="U1",
                    relative_to="C1",
                    relative_to_type="component",
                    source_sentence="Place decoupling capacitor close to IC",
                    confidence=0.85,
                )
            ],
            extraction_method=ExtractionMethod.P1_PHASE5_NLP,
            extraction_confidence=0.85,
            created_at=now,
        )
        assert ds.has_layout_constraints() is True

    def test_has_layout_constraints_false(self) -> None:
        """Test has_layout_constraints returns False when no constraints."""
        now = datetime.now(timezone.utc).isoformat()
        ds = ComponentDatasheet(
            component_id="TEST",
            manufacturer="Test",
            description="Test",
            package="SOT-23-5",
            source_pdf_hash="5555",
            layout_constraints=[],
            extraction_method=ExtractionMethod.P1_VECTOR,
            extraction_confidence=0.95,
            created_at=now,
        )
        assert ds.has_layout_constraints() is False


class TestComponentDatasheetPinMethods:
    """Tests for ComponentDatasheet pin lookup helper methods."""

    def test_get_pin_by_number_found(self, three_pin_component: ComponentDatasheet) -> None:
        """Test get_pin_by_number returns correct pin when found."""
        pin = three_pin_component.get_pin_by_number("2")
        assert pin is not None
        assert pin.pin_number == "2"
        assert pin.raw_name == "GND"

    def test_get_pin_by_number_not_found(self, three_pin_component: ComponentDatasheet) -> None:
        """Test get_pin_by_number returns None when not found."""
        pin = three_pin_component.get_pin_by_number("99")
        assert pin is None

    def test_get_pin_by_number_empty_pins(self) -> None:
        """Test get_pin_by_number with empty pins list."""
        now = datetime.now(timezone.utc).isoformat()
        ds = ComponentDatasheet(
            component_id="EMPTY",
            manufacturer="Test",
            description="No pins",
            package="0402",
            source_pdf_hash="0000",
            pins=[],
            extraction_method=ExtractionMethod.P1_VECTOR,
            extraction_confidence=0.95,
            created_at=now,
        )
        assert ds.get_pin_by_number("1") is None

    def test_get_pin_by_raw_name_found(self, three_pin_component: ComponentDatasheet) -> None:
        """Test get_pin_by_raw_name returns correct pin when found."""
        pin = three_pin_component.get_pin_by_raw_name("VOUT")
        assert pin is not None
        assert pin.pin_number == "3"
        assert pin.raw_name == "VOUT"

    def test_get_pin_by_raw_name_not_found(self, three_pin_component: ComponentDatasheet) -> None:
        """Test get_pin_by_raw_name returns None when not found."""
        pin = three_pin_component.get_pin_by_raw_name("NONEXISTENT")
        assert pin is None

    def test_get_pin_by_raw_name_first_match(self, three_pin_component: ComponentDatasheet) -> None:
        """Test get_pin_by_raw_name returns first match when duplicates exist."""
        # Add duplicate raw_name
        three_pin_component.pins.append(
            PinDefinition(pin_number="4", raw_name="VIN", pin_type="power")
        )
        pin = three_pin_component.get_pin_by_raw_name("VIN")
        assert pin is not None
        assert pin.pin_number == "1"  # First match


class TestExtractionMethodEnum:
    """Tests for ExtractionMethod enum."""

    def test_all_values_exist(self) -> None:
        """Test all expected enum values exist."""
        assert ExtractionMethod.P1_VECTOR.value == "p1_vector"
        assert ExtractionMethod.P1_VLM.value == "p1_vlm"
        assert ExtractionMethod.P1_PHASE5_NLP.value == "p1_phase5_nlp"
        assert ExtractionMethod.MANUAL.value == "manual"
        assert ExtractionMethod.LLM_FALLBACK.value == "llm_fallback"

    def test_enum_in_datasheet(self) -> None:
        """Test enum can be used in ComponentDatasheet."""
        now = datetime.now(timezone.utc).isoformat()
        for method in ExtractionMethod:
            ds = ComponentDatasheet(
                component_id=f"TEST_{method.name}",
                manufacturer="Test",
                description="Test",
                package="0603",
                source_pdf_hash="hash",
                extraction_method=method,
                extraction_confidence=0.9,
                created_at=now,
            )
            assert ds.extraction_method == method


class TestTableSectionTypeEnum:
    """Tests for TableSectionType enum."""

    def test_all_values_exist(self) -> None:
        """Test all expected enum values exist."""
        assert TableSectionType.ELECTRICAL_CHARACTERISTICS.value == "electrical_characteristics"
        assert TableSectionType.ABSOLUTE_MAXIMUM_RATINGS.value == "absolute_maximum_ratings"
        assert TableSectionType.PINOUT.value == "pinout"
        assert TableSectionType.TIMING.value == "timing"
        assert TableSectionType.ORDERING.value == "ordering"
        assert TableSectionType.LAYOUT_RECOMMENDATIONS.value == "layout_recommendations"
        assert TableSectionType.OTHER.value == "other"


# =============================================================================
# Integration Tests
# =============================================================================


class TestFullDatasheetIntegration:
    """Integration tests with realistic full datasheet data."""

    def test_complete_ti_regulator_datasheet(self) -> None:
        """Test creating a complete TI regulator datasheet like TPS62933."""
        now = datetime.now(timezone.utc).isoformat()

        # Create extracted values
        v_in_range = ExtractedValue(
            raw_text="3.8V to 30V",
            normalized_value=3.8,
            unit="V",
            min_val=3.8,
            max_val=30.0,
            confidence=0.98,
        )

        i_out_range = ExtractedValue(
            raw_text="3A",
            normalized_value=3.0,
            unit="A",
            max_val=3.0,
            confidence=0.97,
        )

        # Create parameters
        v_in_param = ElectricalParameter(
            parameter_name="V_IN",
            conditions="-",
            value=v_in_range,
            section_type=TableSectionType.ELECTRICAL_CHARACTERISTICS,
            source_page=6,
            source_table_index=0,
        )

        i_out_param = ElectricalParameter(
            parameter_name="I_OUT",
            conditions="T_A = 25°C",
            value=i_out_range,
            section_type=TableSectionType.ELECTRICAL_CHARACTERISTICS,
            source_page=6,
            source_table_index=0,
        )

        # Create absolute max
        v_in_abs = ExtractedValue(
            raw_text="32V",
            normalized_value=32.0,
            unit="V",
            max_val=32.0,
            confidence=0.95,
        )

        abs_max = AbsoluteMaxRating(
            parameter_name="V_IN_ABS",
            value=v_in_abs,
            note="Absolute maximum input voltage",
            source_page=2,
        )

        # Create pins
        pins = [
            PinDefinition(
                pin_number="1",
                raw_name="VIN",
                normalized_function="VIN",
                normalization_confidence=1.0,
                pin_type="power",
                description="Input voltage supply",
            ),
            PinDefinition(
                pin_number="2",
                raw_name="GND",
                normalized_function="GND",
                normalization_confidence=1.0,
                pin_type="ground",
                description="Ground reference",
            ),
            PinDefinition(
                pin_number="3",
                raw_name="EN",
                normalized_function="EN",
                normalization_confidence=0.95,
                pin_type="input",
                description="Enable pin, active high",
            ),
            PinDefinition(
                pin_number="4",
                raw_name="FB",
                normalized_function="FB",
                normalization_confidence=0.90,
                pin_type="input",
                description="Feedback input for adjustable output",
            ),
            PinDefinition(
                pin_number="5",
                raw_name="VOUT",
                normalized_function="VOUT",
                normalization_confidence=1.0,
                pin_type="output",
                description="Regulated output voltage",
            ),
        ]

        # Create layout constraints
        constraints = [
            PlacementConstraint(
                constraint_type="proximity",
                subject="C_IN",
                relative_to="U1.VIN",
                relative_to_type="pin",
                max_distance_mm=5.0,
                hard=True,
                source_sentence="Place input capacitor within 5mm of VIN pin",
                confidence=0.88,
            ),
            PlacementConstraint(
                constraint_type="proximity",
                subject="C_OUT",
                relative_to="U1.VOUT",
                relative_to_type="pin",
                max_distance_mm=5.0,
                hard=True,
                source_sentence="Place output capacitor within 5mm of VOUT pin",
                confidence=0.87,
            ),
        ]

        # Create full datasheet
        datasheet = ComponentDatasheet(
            component_id="TPS62933DRLR",
            manufacturer="Texas Instruments",
            description="3.8-V to 30-V, 3-A synchronous buck converter with DCS-Control",
            package="SOT-23-5",
            datasheet_url="https://www.ti.com/lit/ds/symlink/tps62933.pdf",
            source_pdf_hash="a1b2c3d4e5f6789012345678901234567890abcd",
            electrical_parameters=[v_in_param, i_out_param],
            absolute_max_ratings=[abs_max],
            pins=pins,
            layout_constraints=constraints,
            extraction_method=ExtractionMethod.P1_VECTOR,
            extraction_confidence=0.94,
            review_required=False,
            created_at=now,
        )

        # Verify
        assert datasheet.component_id == "TPS62933DRLR"
        assert len(datasheet.pins) == 5
        assert len(datasheet.electrical_parameters) == 2
        assert len(datasheet.layout_constraints) == 2
        assert datasheet.has_layout_constraints() is True

        # Test pin lookup
        vout_pin = datasheet.get_pin_by_number("5")
        assert vout_pin is not None
        assert vout_pin.raw_name == "VOUT"

        vin_pin = datasheet.get_pin_by_raw_name("VIN")
        assert vin_pin is not None
        assert vin_pin.pin_number == "1"

        # Test JSON round-trip
        json_str = datasheet.model_dump_json()
        restored = ComponentDatasheet.model_validate_json(json_str)
        assert restored.component_id == datasheet.component_id
        assert len(restored.pins) == len(datasheet.pins)
