"""Unit tests for src/schemas/intent.py.

Tests design intent parsing, BOM generation, and validation schemas.
"""

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.schemas.common import Ambiguity
from src.schemas.intent import (
    AmbiguityFlag,
    BOMEntry,
    DesignMethodology,
    FrequencySpec,
    IntentDict,
    ValidatedBOM,
)


# =============================================================================
# FrequencySpec Tests
# =============================================================================


class TestFrequencySpec:
    """Tests for FrequencySpec model."""

    def test_valid_instantiation_hz(self) -> None:
        """Test valid instantiation with Hz."""
        fs = FrequencySpec(value=60.0, unit="Hz")
        assert fs.value == 60.0
        assert fs.unit == "Hz"

    def test_valid_instantiation_khz(self) -> None:
        """Test valid instantiation with kHz."""
        fs = FrequencySpec(value=455.0, unit="kHz")
        assert fs.value == 455.0
        assert fs.unit == "kHz"

    def test_valid_instantiation_mhz(self) -> None:
        """Test valid instantiation with MHz."""
        fs = FrequencySpec(value=100.0, unit="MHz")
        assert fs.value == 100.0
        assert fs.unit == "MHz"

    def test_valid_instantiation_ghz(self) -> None:
        """Test valid instantiation with GHz."""
        fs = FrequencySpec(value=2.4, unit="GHz")
        assert fs.value == 2.4
        assert fs.unit == "GHz"

    def test_json_round_trip_ghz(self) -> None:
        """Test FrequencySpec round-trips correctly for GHz values."""
        original = FrequencySpec(value=5.8, unit="GHz")
        json_str = original.model_dump_json()
        restored = FrequencySpec.model_validate_json(json_str)

        assert restored.value == original.value
        assert restored.unit == original.unit

    def test_python_dict_round_trip(self) -> None:
        """Test FrequencySpec round-trips through Python dict."""
        original = FrequencySpec(value=915.0, unit="MHz")
        data_dict = original.model_dump()
        restored = FrequencySpec.model_validate(data_dict)

        assert restored.value == original.value
        assert restored.unit == original.unit

    def test_rejects_zero_frequency(self) -> None:
        """Test frequency value must be > 0."""
        with pytest.raises(ValidationError) as exc_info:
            FrequencySpec(value=0.0, unit="MHz")
        assert "value" in str(exc_info.value).lower()

    def test_rejects_negative_frequency(self) -> None:
        """Test frequency value must be positive."""
        with pytest.raises(ValidationError) as exc_info:
            FrequencySpec(value=-100.0, unit="MHz")
        assert "value" in str(exc_info.value).lower()

    def test_rejects_invalid_unit(self) -> None:
        """Test unit must be one of Hz, kHz, MHz, GHz."""
        with pytest.raises(ValidationError) as exc_info:
            FrequencySpec(value=100.0, unit="THz")  # type: ignore[arg-type]
        assert "unit" in str(exc_info.value).lower()


# =============================================================================
# AmbiguityFlag Tests
# =============================================================================


class TestAmbiguityFlag:
    """Tests for AmbiguityFlag model."""

    def test_valid_critical(self) -> None:
        """Test valid AmbiguityFlag with CRITICAL severity."""
        af = AmbiguityFlag(
            field="input_voltage",
            description="Input voltage not specified, assuming 5V",
            severity="CRITICAL",
            options=["3.3V", "5V", "12V"],
        )
        assert af.field == "input_voltage"
        assert af.severity == "CRITICAL"
        assert len(af.options) == 3

    def test_valid_warning(self) -> None:
        """Test valid AmbiguityFlag with WARNING severity."""
        af = AmbiguityFlag(
            field="package_preference",
            description="Multiple suitable package options available",
            severity="WARNING",
            options=["SOT-23-5", "SOT-23-3"],
        )
        assert af.severity == "WARNING"

    def test_rejects_invalid_severity(self) -> None:
        """Test AmbiguityFlag rejects severity outside CRITICAL/WARNING."""
        with pytest.raises(ValidationError) as exc_info:
            AmbiguityFlag(
                field="test",
                description="Test",
                severity="ERROR",  # type: ignore[arg-type]
            )
        assert "severity" in str(exc_info.value).lower()

    def test_rejects_info_severity(self) -> None:
        """Test AmbiguityFlag rejects INFO severity."""
        with pytest.raises(ValidationError) as exc_info:
            AmbiguityFlag(
                field="test",
                description="Test",
                severity="INFO",  # type: ignore[arg-type]
            )
        assert "severity" in str(exc_info.value).lower()

    def test_rejects_empty_severity(self) -> None:
        """Test AmbiguityFlag rejects empty severity."""
        with pytest.raises(ValidationError) as exc_info:
            AmbiguityFlag(
                field="test",
                description="Test",
                severity="",  # type: ignore[arg-type]
            )
        assert "severity" in str(exc_info.value).lower()

    def test_default_empty_options(self) -> None:
        """Test options defaults to empty list."""
        af = AmbiguityFlag(
            field="test",
            description="Test",
            severity="WARNING",
        )
        assert af.options == []

    def test_json_round_trip(self) -> None:
        """Test AmbiguityFlag round-trips JSON correctly."""
        original = AmbiguityFlag(
            field="output_current",
            description="Output current requirement unclear",
            severity="CRITICAL",
            options=["1A", "2A", "3A"],
        )
        json_str = original.model_dump_json()
        restored = AmbiguityFlag.model_validate_json(json_str)

        assert restored.field == original.field
        assert restored.severity == original.severity
        assert restored.options == original.options


# =============================================================================
# DesignMethodology Tests
# =============================================================================


class TestDesignMethodology:
    """Tests for DesignMethodology enum."""

    def test_all_values_exist(self) -> None:
        """Test all expected DesignMethodology values exist."""
        assert DesignMethodology.RF_HIGHFREQ.value == "RF_highfreq"
        assert DesignMethodology.POWER_MANAGEMENT.value == "power_management"
        assert DesignMethodology.MIXED_SIGNAL.value == "mixed_signal"
        assert DesignMethodology.STANDARD_SMD.value == "standard_SMD"
        assert DesignMethodology.THROUGH_HOLE.value == "through_hole"

    def test_total_count(self) -> None:
        """Test we have exactly 5 design methodologies."""
        assert len(list(DesignMethodology)) == 5

    def test_used_in_intent_dict(self) -> None:
        """Test DesignMethodology can be used in IntentDict."""
        for method in DesignMethodology:
            intent = IntentDict(
                goal=f"Test with {method.value}",
                application="test",
                design_methodology=method,
                board_type="2-layer FR4",
                raw_prompt=f"Design a {method.value} circuit",
            )
            assert intent.design_methodology == method


# =============================================================================
# IntentDict Tests
# =============================================================================


class TestIntentDict:
    """Tests for IntentDict model."""

    def test_valid_instantiation_minimal(self) -> None:
        """Test valid minimal IntentDict instantiation."""
        intent = IntentDict(
            goal="5V to 3.3V buck regulator",
            application="IoT sensor power supply",
            design_methodology=DesignMethodology.POWER_MANAGEMENT,
            board_type="2-layer FR4",
            raw_prompt="I need a 3.3V regulator from 5V input for my IoT device",
        )
        assert intent.goal == "5V to 3.3V buck regulator"
        assert intent.frequency is None
        assert intent.clarification_required is False

    def test_valid_instantiation_full(self) -> None:
        """Test valid IntentDict with all fields.

        IntentDict (=ImprovedIntentDict, the real v2 schema) has no
        explicit_constraints field and its ambiguities are Ambiguity (v2)
        instances, not AmbiguityFlag (v1) -- Ambiguity has no "options"
        field either, only candidate_resolutions.
        """
        intent = IntentDict(
            goal="2.4GHz RF transceiver",
            frequency=FrequencySpec(value=2.4, unit="GHz"),
            application="wireless sensor node",
            inferred_constraints=["impedance matched traces", "ground plane required"],
            design_methodology=DesignMethodology.RF_HIGHFREQ,
            board_type="4-layer HDI",
            ambiguities=[
                Ambiguity(
                    field="output_power",
                    description="Output power not specified",
                    severity="WARNING",
                    candidate_resolutions=["0dBm", "10dBm", "20dBm"],
                )
            ],
            clarification_required=False,
            raw_prompt="Design a 2.4GHz transceiver for my wireless sensor",
        )
        assert intent.frequency is not None
        assert intent.frequency.value == 2.4
        assert len(intent.inferred_constraints) == 2
        assert len(intent.ambiguities) == 1

    def test_defaults(self) -> None:
        """Test IntentDict default values.

        IntentDict (=ImprovedIntentDict) has no explicit_constraints field.
        """
        intent = IntentDict(
            goal="Test",
            application="test",
            design_methodology=DesignMethodology.STANDARD_SMD,
            board_type="2-layer",
            raw_prompt="test",
        )
        assert intent.frequency is None
        assert intent.inferred_constraints == []
        assert intent.ambiguities == []
        assert intent.clarification_required is False

    def test_serialize_design_methodology_as_string(self) -> None:
        """Test IntentDict serializes DesignMethodology as its string value."""
        intent = IntentDict(
            goal="Power supply",
            application="test",
            design_methodology=DesignMethodology.POWER_MANAGEMENT,
            board_type="2-layer",
            raw_prompt="Design a power supply",
        )

        # Serialize to dict
        data_dict = intent.model_dump()

        # Design methodology should be the string value, not the enum object
        assert data_dict["design_methodology"] == "power_management"
        assert isinstance(data_dict["design_methodology"], str)

    def test_json_serialize_design_methodology(self) -> None:
        """Test IntentDict JSON serialization uses string value for DesignMethodology."""
        intent = IntentDict(
            goal="RF design",
            frequency=FrequencySpec(value=915.0, unit="MHz"),
            application="telemetry",
            design_methodology=DesignMethodology.RF_HIGHFREQ,
            board_type="4-layer",
            raw_prompt="915 MHz telemetry transmitter",
        )

        json_str = intent.model_dump_json()
        parsed = json.loads(json_str)

        # Should be string value, not enum representation
        assert parsed["design_methodology"] == "RF_highfreq"
        assert isinstance(parsed["design_methodology"], str)

    def test_round_trip_preserves_design_methodology(self) -> None:
        """Test round-trip preserves DesignMethodology correctly."""
        original = IntentDict(
            goal="Mixed signal design",
            application="audio processing",
            design_methodology=DesignMethodology.MIXED_SIGNAL,
            board_type="4-layer",
            raw_prompt="Audio ADC with digital processing",
        )

        json_str = original.model_dump_json()
        restored = IntentDict.model_validate_json(json_str)

        assert restored.design_methodology == DesignMethodology.MIXED_SIGNAL
        assert restored.design_methodology.value == "mixed_signal"

    def test_clarification_required_with_critical_ambiguity(self) -> None:
        """Test clarification_required True when a blocking ambiguity exists.

        Ambiguity (v2) has no "CRITICAL" severity value; the equivalent of a
        blocking condition is severity="ERROR" combined with blocking=True.
        ImprovedIntentDict.validate_clarification_protocol() enforces that
        clarification_required=True requires at least one blocking=True
        ambiguity, so blocking=True must be set here for construction to
        succeed at all.
        """
        intent = IntentDict(
            goal="Regulator design",
            application="test",
            design_methodology=DesignMethodology.POWER_MANAGEMENT,
            board_type="2-layer",
            ambiguities=[
                Ambiguity(
                    field="input_voltage",
                    description="Input voltage not specified",
                    severity="ERROR",
                    candidate_resolutions=["5V", "12V"],
                    blocking=True,
                )
            ],
            clarification_required=True,
            raw_prompt="Design a regulator",
        )
        assert intent.clarification_required is True
        assert intent.ambiguities[0].severity == "ERROR"

    def test_json_round_trip(self) -> None:
        """Test IntentDict round-trips JSON correctly.

        IntentDict (=ImprovedIntentDict) has no explicit_constraints field,
        and ambiguities are Ambiguity (v2) instances, not AmbiguityFlag (v1).
        """
        original = IntentDict(
            goal="Complete test design",
            frequency=FrequencySpec(value=100.0, unit="MHz"),
            application="test",
            inferred_constraints=["inferred1"],
            design_methodology=DesignMethodology.RF_HIGHFREQ,
            board_type="4-layer HDI",
            ambiguities=[
                Ambiguity(
                    field="test_field",
                    description="Test ambiguity",
                    severity="WARNING",
                )
            ],
            clarification_required=False,
            raw_prompt="Complete test prompt with all fields",
        )

        json_str = original.model_dump_json()
        restored = IntentDict.model_validate_json(json_str)

        assert restored.goal == original.goal
        assert restored.frequency is not None
        assert restored.frequency.value == original.frequency.value
        assert restored.design_methodology == original.design_methodology
        assert restored.raw_prompt == original.raw_prompt


# =============================================================================
# BOMEntry Tests
# =============================================================================


class TestBOMEntry:
    """Tests for BOMEntry model."""

    def test_valid_instantiation_resolved(self) -> None:
        """Test valid BOMEntry with specific part resolved."""
        entry = BOMEntry(
            ref="U1",
            component_type="regulator",
            specific_part="TPS62933DRLR",
            value_constraints={"v_out": 3.3, "i_out_max": 3.0},
            justification="High efficiency buck converter for 3.3V rail",
            source="datasheet_parser_v1",
            confidence=0.97,
            alternatives=["TPS62203", "MP2143"],
            review_flag=False,
        )
        assert entry.ref == "U1"
        assert entry.specific_part == "TPS62933DRLR"
        assert entry.confidence == 0.97
        assert len(entry.alternatives) == 2

    def test_valid_instantiation_unresolved(self) -> None:
        """Test valid BOMEntry with specific_part=None (unresolved)."""
        entry = BOMEntry(
            ref="C1",
            component_type="capacitor",
            specific_part=None,
            value_constraints={"capacitance_uf": 10.0, "voltage_rating_v": 25.0},
            justification="Input decoupling capacitor per datasheet recommendation",
            source="design_rule_KG",
            confidence=0.85,
        )
        assert entry.ref == "C1"
        assert entry.specific_part is None
        assert entry.review_flag is False  # Default

    def test_defaults(self) -> None:
        """Test BOMEntry default values."""
        entry = BOMEntry(
            ref="R1",
            component_type="resistor",
            justification="Pull-up resistor",
            source="rule",
            confidence=0.95,
        )
        assert entry.specific_part is None
        assert entry.value_constraints == {}
        assert entry.alternatives == []
        assert entry.review_flag is False

    def test_confidence_bounds(self) -> None:
        """Test confidence must be in [0.0, 1.0]."""
        # Valid bounds
        BOMEntry(
            ref="U1",
            component_type="test",
            justification="test",
            source="test",
            confidence=0.0,
        )
        BOMEntry(
            ref="U2",
            component_type="test",
            justification="test",
            source="test",
            confidence=1.0,
        )

        # Invalid: negative
        with pytest.raises(ValidationError) as exc_info:
            BOMEntry(
                ref="U3",
                component_type="test",
                justification="test",
                source="test",
                confidence=-0.1,
            )
        assert "confidence" in str(exc_info.value).lower()

        # Invalid: > 1.0
        with pytest.raises(ValidationError) as exc_info:
            BOMEntry(
                ref="U4",
                component_type="test",
                justification="test",
                source="test",
                confidence=1.01,
            )
        assert "confidence" in str(exc_info.value).lower()

    def test_json_round_trip(self) -> None:
        """Test BOMEntry round-trips JSON correctly."""
        original = BOMEntry(
            ref="L1",
            component_type="inductor",
            specific_part="SRN6045-4R7M",
            value_constraints={"inductance_uh": 4.7, "current_rating_a": 4.0},
            justification="4.7uH inductor for buck converter",
            source="KG_lookup",
            confidence=0.94,
            alternatives=["LQH5BPB4R7M38L"],
            review_flag=True,
        )

        json_str = original.model_dump_json()
        restored = BOMEntry.model_validate_json(json_str)

        assert restored.ref == original.ref
        assert restored.specific_part == original.specific_part
        assert restored.value_constraints == original.value_constraints
        assert restored.confidence == original.confidence


# =============================================================================
# ValidatedBOM Tests
# =============================================================================


class TestValidatedBOM:
    """Tests for ValidatedBOM model."""

    @pytest.fixture
    def sample_intent(self) -> IntentDict:
        """Sample IntentDict for ValidatedBOM tests."""
        return IntentDict(
            goal="3.3V buck regulator",
            application="power supply",
            design_methodology=DesignMethodology.POWER_MANAGEMENT,
            board_type="2-layer FR4",
            raw_prompt="Design a 3.3V buck regulator",
        )

    @pytest.fixture
    def sample_components(self) -> list[BOMEntry]:
        """Sample components list with resolved and unresolved entries."""
        return [
            BOMEntry(
                ref="U1",
                component_type="regulator",
                specific_part="TPS62933DRLR",
                justification="Main regulator",
                source="parser",
                confidence=0.97,
            ),
            BOMEntry(
                ref="C1",
                component_type="capacitor",
                specific_part=None,  # Unresolved
                justification="Input cap",
                source="rule",
                confidence=0.85,
            ),
            BOMEntry(
                ref="C2",
                component_type="capacitor",
                specific_part="GRM188R71H105KA12D",
                justification="Output cap",
                source="parser",
                confidence=0.95,
            ),
            BOMEntry(
                ref="L1",
                component_type="inductor",
                specific_part=None,  # Unresolved
                justification="Inductor",
                source="rule",
                confidence=0.80,
            ),
        ]

    def test_valid_instantiation(
        self, sample_intent: IntentDict, sample_components: list[BOMEntry]
    ) -> None:
        """Test valid ValidatedBOM instantiation."""
        now = datetime.now(timezone.utc).isoformat()
        bom = ValidatedBOM(
            design_id="REG_3V3_001",
            intent=sample_intent,
            components=sample_components,
            total_confidence=0.89,
            review_required=False,
            created_at=now,
        )
        assert bom.design_id == "REG_3V3_001"
        assert len(bom.components) == 4
        assert bom.total_confidence == 0.89

    def test_defaults(self, sample_intent: IntentDict) -> None:
        """Test ValidatedBOM default values."""
        now = datetime.now(timezone.utc).isoformat()
        bom = ValidatedBOM(
            design_id="TEST",
            intent=sample_intent,
            components=[],
            total_confidence=0.5,
            created_at=now,
        )
        assert bom.cross_component_rules == []
        assert bom.review_required is False

    def test_unresolved_components_returns_only_unresolved(
        self, sample_intent: IntentDict, sample_components: list[BOMEntry]
    ) -> None:
        """Test unresolved_components() returns only entries where specific_part is None."""
        now = datetime.now(timezone.utc).isoformat()
        bom = ValidatedBOM(
            design_id="REG_3V3_001",
            intent=sample_intent,
            components=sample_components,
            total_confidence=0.89,
            created_at=now,
        )

        unresolved = bom.unresolved_components()

        # Should return only C1 and L1 (where specific_part is None)
        assert len(unresolved) == 2
        assert all(c.specific_part is None for c in unresolved)
        assert {c.ref for c in unresolved} == {"C1", "L1"}

    def test_unresolved_components_empty_when_all_resolved(
        self, sample_intent: IntentDict
    ) -> None:
        """Test unresolved_components() returns empty list when all resolved."""
        now = datetime.now(timezone.utc).isoformat()
        all_resolved = [
            BOMEntry(
                ref="U1",
                component_type="regulator",
                specific_part="TPS62933DRLR",
                justification="Regulator",
                source="parser",
                confidence=0.97,
            ),
            BOMEntry(
                ref="C1",
                component_type="capacitor",
                specific_part="GRM188R71H105KA12D",
                justification="Capacitor",
                source="parser",
                confidence=0.95,
            ),
        ]
        bom = ValidatedBOM(
            design_id="COMPLETE",
            intent=sample_intent,
            components=all_resolved,
            total_confidence=0.96,
            created_at=now,
        )

        assert bom.unresolved_components() == []

    def test_unresolved_components_empty_list(self, sample_intent: IntentDict) -> None:
        """Test unresolved_components() returns empty list when no components."""
        now = datetime.now(timezone.utc).isoformat()
        bom = ValidatedBOM(
            design_id="EMPTY",
            intent=sample_intent,
            components=[],
            total_confidence=0.0,
            created_at=now,
        )

        assert bom.unresolved_components() == []

    def test_total_confidence_bounds(self, sample_intent: IntentDict) -> None:
        """Test total_confidence must be in [0.0, 1.0]."""
        now = datetime.now(timezone.utc).isoformat()

        # Valid bounds
        ValidatedBOM(
            design_id="MIN",
            intent=sample_intent,
            components=[],
            total_confidence=0.0,
            created_at=now,
        )
        ValidatedBOM(
            design_id="MAX",
            intent=sample_intent,
            components=[],
            total_confidence=1.0,
            created_at=now,
        )

        # Invalid: negative
        with pytest.raises(ValidationError) as exc_info:
            ValidatedBOM(
                design_id="INVALID",
                intent=sample_intent,
                components=[],
                total_confidence=-0.1,
                created_at=now,
            )
        assert "total_confidence" in str(exc_info.value).lower()

        # Invalid: > 1.0
        with pytest.raises(ValidationError) as exc_info:
            ValidatedBOM(
                design_id="INVALID",
                intent=sample_intent,
                components=[],
                total_confidence=1.01,
                created_at=now,
            )
        assert "total_confidence" in str(exc_info.value).lower()

    def test_json_round_trip(
        self, sample_intent: IntentDict, sample_components: list[BOMEntry]
    ) -> None:
        """Test ValidatedBOM round-trips JSON correctly."""
        now = datetime.now(timezone.utc).isoformat()
        original = ValidatedBOM(
            design_id="REG_3V3_001",
            intent=sample_intent,
            components=sample_components,
            cross_component_rules=[{"type": "proximity", "refs": ["C1", "U1"]}],
            total_confidence=0.89,
            review_required=True,
            created_at=now,
        )

        json_str = original.model_dump_json()
        restored = ValidatedBOM.model_validate_json(json_str)

        assert restored.design_id == original.design_id
        assert restored.intent.goal == original.intent.goal
        assert len(restored.components) == len(original.components)
        assert restored.total_confidence == original.total_confidence
        assert restored.created_at == original.created_at


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntentBOMIntegration:
    """Integration tests for complete intent-to-BOM workflow."""

    def test_complete_rf_design_intent_to_bom(self) -> None:
        """Test complete RF design workflow from intent to validated BOM.

        IntentDict (=ImprovedIntentDict) has no explicit_constraints field,
        and ambiguities are Ambiguity (v2) instances, not AmbiguityFlag (v1).
        """
        now = datetime.now(timezone.utc).isoformat()

        # Step 1: Create intent with ambiguity
        intent = IntentDict(
            goal="915 MHz ISM band transmitter",
            frequency=FrequencySpec(value=915.0, unit="MHz"),
            application="remote sensor telemetry",
            inferred_constraints=["impedance control", "ground plane"],
            design_methodology=DesignMethodology.RF_HIGHFREQ,
            board_type="4-layer HDI",
            ambiguities=[
                Ambiguity(
                    field="output_power",
                    description="Transmit power not specified",
                    severity="WARNING",
                    candidate_resolutions=["0dBm", "10dBm"],
                )
            ],
            clarification_required=False,
            raw_prompt="Design a 915 MHz transmitter for my sensor node",
        )

        # Step 2: Create BOM entries
        components = [
            BOMEntry(
                ref="U1",
                component_type="rf_transceiver",
                specific_part="CC1101",
                value_constraints={"frequency_mhz": 915, "modulation": "FSK"},
                justification="Sub-GHz transceiver for 915 MHz ISM band",
                source="component_database",
                confidence=0.95,
                alternatives=["SI4463"],
            ),
            BOMEntry(
                ref="Y1",
                component_type="crystal",
                specific_part=None,  # Needs selection
                value_constraints={"frequency_mhz": 26.0, "tolerance_ppm": 10},
                justification="Crystal for RF synthesizer reference",
                source="datasheet_recommendation",
                confidence=0.80,
            ),
            BOMEntry(
                ref="L1",
                component_type="inductor",
                specific_part="LQW18AN15NG00D",
                value_constraints={"inductance_nh": 15, "q_factor_min": 50},
                justification="Matching network inductor",
                source="matching_calculator",
                confidence=0.88,
            ),
        ]

        # Step 3: Create validated BOM
        bom = ValidatedBOM(
            design_id="RF_TX_915_001",
            intent=intent,
            components=components,
            cross_component_rules=[
                {"type": "matching_network", "components": ["L1", "C1", "C2"]}
            ],
            total_confidence=0.87,
            review_required=True,
            created_at=now,
        )

        # Verify
        assert bom.design_id == "RF_TX_915_001"
        assert bom.intent.frequency is not None
        assert bom.intent.frequency.unit == "MHz"

        # Check unresolved components
        unresolved = bom.unresolved_components()
        assert len(unresolved) == 1
        assert unresolved[0].ref == "Y1"

        # JSON round-trip
        json_str = bom.model_dump_json()
        restored = ValidatedBOM.model_validate_json(json_str)

        assert restored.total_confidence == bom.total_confidence
        assert restored.intent.design_methodology == DesignMethodology.RF_HIGHFREQ
        assert restored.intent.frequency.value == 915.0
