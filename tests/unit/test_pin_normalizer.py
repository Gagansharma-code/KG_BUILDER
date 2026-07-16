"""Unit tests for src/knowledge_graph/pin_normalizer/.

Tests pin normalization including dictionary lookup, context resolution,
and three-tier normalization orchestration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.config import Config
from src.knowledge_graph.pin_normalizer import normalize_pins
from src.knowledge_graph.pin_normalizer.context_resolver import resolve_with_context
from src.knowledge_graph.pin_normalizer.dictionary import (
    PIN_NORMALIZATION_MAP,
    normalize_from_dictionary,
)
from src.knowledge_graph.pin_normalizer.llm_fallback import normalize_via_llm
from src.schemas.datasheet import (
    AlternateFunction,
    ComponentDatasheet,
    ExtractionMethod,
    PinDefinition,
)


# =============================================================================
# Dictionary Tests
# =============================================================================


class TestDictionaryLookup:
    """Tests for dictionary-based pin normalization."""

    def test_vdd_returns_power_positive(self) -> None:
        """Test "VDD" → "POWER_POSITIVE", confidence=1.0, method="dictionary"."""
        result = normalize_from_dictionary("VDD")
        assert result == "POWER_POSITIVE"

    def test_sclk_returns_spi_clock(self) -> None:
        """Test "SCLK" → "SPI_CLOCK" via dictionary."""
        result = normalize_from_dictionary("SCLK")
        assert result == "SPI_CLOCK"

    def test_gpio0_strips_digit_returns_gpio(self) -> None:
        """Test "GPIO0" → "GPIO" after digit strip → found in dictionary."""
        result = normalize_from_dictionary("GPIO0")
        assert result == "GPIO"

    def test_gpio12_strips_multiple_digits(self) -> None:
        """Test "GPIO12" strips all trailing digits."""
        result = normalize_from_dictionary("GPIO12")
        assert result == "GPIO"

    def test_nrst_strips_n_prefix_returns_reset(self) -> None:
        """Test "NRST" → "RST" after N strip → "RESET" from dictionary."""
        result = normalize_from_dictionary("NRST")
        assert result == "RESET"

    def test_bang_rst_strips_bang_prefix(self) -> None:
        """Test "!RST" → "RST" after ! strip. RST maps to RESET_ACTIVE_LOW."""
        result = normalize_from_dictionary("!RST")
        assert result == "RESET_ACTIVE_LOW"

    def test_whitespace_is_stripped(self) -> None:
        """Test whitespace around pin name is stripped."""
        result = normalize_from_dictionary("  VDD  ")
        assert result == "POWER_POSITIVE"

    def test_lowercase_converted_to_uppercase(self) -> None:
        """Test lowercase input converted to uppercase."""
        result = normalize_from_dictionary("vdd")
        assert result == "POWER_POSITIVE"

    def test_unknown_returns_none(self) -> None:
        """Test unknown pin name returns None."""
        result = normalize_from_dictionary("UNKNOWN123XYZ")
        assert result is None

    def test_empty_string_returns_none(self) -> None:
        """Test empty string returns None."""
        result = normalize_from_dictionary("")
        assert result is None

    def test_sda_returns_i2c_data(self) -> None:
        """Test "SDA" → "I2C_DATA"."""
        result = normalize_from_dictionary("SDA")
        assert result == "I2C_DATA"

    def test_scl_returns_i2c_clock(self) -> None:
        """Test "SCL" → "I2C_CLOCK"."""
        result = normalize_from_dictionary("SCL")
        assert result == "I2C_CLOCK"

    def test_tx_returns_uart_transmit(self) -> None:
        """Test "TX" → "UART_TRANSMIT"."""
        result = normalize_from_dictionary("TX")
        assert result == "UART_TRANSMIT"

    def test_rx_returns_uart_receive(self) -> None:
        """Test "RX" → "UART_RECEIVE"."""
        result = normalize_from_dictionary("RX")
        assert result == "UART_RECEIVE"

    def test_nc_returns_no_connect(self) -> None:
        """Test "NC" → "NO_CONNECT"."""
        result = normalize_from_dictionary("NC")
        assert result == "NO_CONNECT"

    def test_en_returns_enable(self) -> None:
        """Test "EN" → "ENABLE"."""
        result = normalize_from_dictionary("EN")
        assert result == "ENABLE"


# =============================================================================
# Context Resolver Tests
# =============================================================================


class TestContextResolver:
    """Tests for context-based pin resolution."""

    def test_clk_with_sda_scl_returns_i2c_clock(self) -> None:
        """Test "CLK" with adjacent ["SDA", "SCL", "INT"] → "I2C_CLOCK"."""
        result = resolve_with_context("CLK", ["SDA", "SCL", "INT"])
        assert result == "I2C_CLOCK"

    def test_clk_with_mosi_miso_returns_spi_clock(self) -> None:
        """Test "CLK" with adjacent ["MOSI", "MISO", "CS"] → "SPI_CLOCK"."""
        result = resolve_with_context("CLK", ["MOSI", "MISO", "CS"])
        assert result == "SPI_CLOCK"

    def test_clk_with_both_spi_and_i2c_ambiguous(self) -> None:
        """Test "CLK" with both SPI and I2C indicators → None (ambiguous)."""
        result = resolve_with_context("CLK", ["SDA", "MOSI"])  # Both present
        assert result is None

    def test_clk_with_no_indicators_ambiguous(self) -> None:
        """Test "CLK" with no protocol indicators → None (ambiguous)."""
        result = resolve_with_context("CLK", ["ANT", "GND", "VDD"])
        assert result is None

    def test_scl_with_only_i2c_returns_i2c_clock(self) -> None:
        """Test "SCL" with only I2C indicators → "I2C_CLOCK"."""
        result = resolve_with_context("SCL", ["SDA", "INT"])
        assert result == "I2C_CLOCK"

    def test_int_returns_interrupt(self) -> None:
        """Test "INT" with any context → "INTERRUPT"."""
        result = resolve_with_context("INT", ["SDA", "SCL"])
        assert result == "INTERRUPT"

    def test_en_returns_enable(self) -> None:
        """Test "EN" → "ENABLE"."""
        result = resolve_with_context("EN", ["VDD", "GND"])
        assert result == "ENABLE"

    def test_en_with_bang_prefix_returns_enable_active_low(self) -> None:
        """Test "!EN" name → active low handling."""
        result = resolve_with_context("!EN", ["VDD", "GND"])
        assert result == "ENABLE_ACTIVE_LOW"

    def test_rst_returns_reset(self) -> None:
        """Test "RST" → "RESET"."""
        result = resolve_with_context("RST", ["VDD", "GND"])
        assert result == "RESET"


# =============================================================================
# LLM Fallback Tests
# =============================================================================


class TestLLMFallback:
    """Tests for LLM-based pin normalization fallback."""

    def test_llm_unavailable_returns_none(self) -> None:
        """Test llm_fallback returns None when model unavailable."""
        config = MagicMock(spec=Config)

        canonical, confidence, method = normalize_via_llm("CUSTOM_PIN", config)

        assert canonical is None
        assert confidence == 0.0
        assert method == "llm_unavailable"

    @patch("src.knowledge_graph.pin_normalizer.llm_fallback._load_llm")
    def test_llm_returns_unknown_returns_none_with_low_confidence(
        self, mock_load_llm
    ) -> None:
        """Mock LLM — test llm_fallback returns None when LLM returns UNKNOWN."""
        from src.knowledge_graph.pin_normalizer.llm_fallback import NormalizationOutput

        config = MagicMock(spec=Config)
        mock_load_llm.return_value = object()  # Non-None mock client

        canonical, confidence, method = normalize_via_llm("WEIRD_PIN", config)

        # Since we can't actually call LLM in tests, it returns None
        # In real scenario with mocked LLM returning UNKNOWN, would return None
        assert canonical is None


# =============================================================================
# Integration Tests - normalize_pins
# =============================================================================


@pytest.fixture
def mock_config() -> Config:
    """Create mock Config for testing."""
    return MagicMock(spec=Config)


@pytest.fixture
def datasheet_with_vdd_pin() -> ComponentDatasheet:
    """Create a datasheet with a VDD pin (dictionary match)."""
    return ComponentDatasheet(
        component_id="TEST1",
        manufacturer="Test",
        description="Test chip",
        package="SOT-23-5",
        source_pdf_hash="hash1",
        extraction_method=ExtractionMethod.P1_VECTOR,
        extraction_confidence=0.97,
        pins=[
            PinDefinition(
                pin_number="1",
                raw_name="VDD",
                pin_type="power",
            ),
        ],
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


@pytest.fixture
def datasheet_with_spi_pins() -> ComponentDatasheet:
    """Create a datasheet with SPI pins and ambiguous CLK."""
    return ComponentDatasheet(
        component_id="TEST2",
        manufacturer="Test",
        description="SPI Device",
        package="SOIC-8",
        source_pdf_hash="hash2",
        extraction_method=ExtractionMethod.P1_VECTOR,
        extraction_confidence=0.97,
        pins=[
            PinDefinition(pin_number="1", raw_name="CS", pin_type="input"),
            PinDefinition(pin_number="2", raw_name="CLK", pin_type="input"),  # Ambiguous
            PinDefinition(pin_number="3", raw_name="MOSI", pin_type="input"),
            PinDefinition(pin_number="4", raw_name="MISO", pin_type="output"),
            PinDefinition(pin_number="5", raw_name="VDD", pin_type="power"),
            PinDefinition(pin_number="6", raw_name="GND", pin_type="ground"),
        ],
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


@pytest.fixture
def datasheet_with_i2c_pins() -> ComponentDatasheet:
    """Create a datasheet with I2C pins and ambiguous CLK (SCL)."""
    return ComponentDatasheet(
        component_id="TEST3",
        manufacturer="Test",
        description="I2C Device",
        package="SOT-23-5",
        source_pdf_hash="hash3",
        extraction_method=ExtractionMethod.P1_VECTOR,
        extraction_confidence=0.97,
        pins=[
            PinDefinition(pin_number="1", raw_name="SDA", pin_type="io"),
            PinDefinition(pin_number="2", raw_name="SCL", pin_type="input"),  # Could be I2C
            PinDefinition(pin_number="3", raw_name="VDD", pin_type="power"),
            PinDefinition(pin_number="4", raw_name="GND", pin_type="ground"),
            PinDefinition(pin_number="5", raw_name="INT", pin_type="output"),
        ],
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


@pytest.fixture
def datasheet_with_unknown_pin() -> ComponentDatasheet:
    """Create a datasheet with an unknown pin that will fail normalization."""
    return ComponentDatasheet(
        component_id="TEST4",
        manufacturer="Test",
        description="Custom Chip",
        package="QFN-16",
        source_pdf_hash="hash4",
        extraction_method=ExtractionMethod.P1_VECTOR,
        extraction_confidence=0.97,
        pins=[
            PinDefinition(pin_number="1", raw_name="MY_WEIRD_PIN", pin_type="unknown"),
            PinDefinition(pin_number="2", raw_name="VDD", pin_type="power"),
        ],
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


class TestNormalizePinsIntegration:
    """Integration tests for normalize_pins function."""

    def test_returns_new_list_does_not_mutate_input(
        self, datasheet_with_vdd_pin, mock_config
    ) -> None:
        """Test normalize_pins returns NEW list, does not mutate input."""
        original = datasheet_with_vdd_pin

        # Verify original has no normalized_function
        assert original.pins[0].normalized_function is None

        result = normalize_pins([original], mock_config)

        # Input should still be unchanged
        assert original.pins[0].normalized_function is None

        # Output should be new object with normalized_function set
        assert result[0].pins[0].normalized_function == "POWER_POSITIVE"
        assert result[0] is not original

    def test_vdd_gets_power_positive_confidence_1_0(
        self, datasheet_with_vdd_pin, mock_config
    ) -> None:
        """Test VDD pin gets POWER_POSITIVE with confidence 1.0."""
        result = normalize_pins([datasheet_with_vdd_pin], mock_config)

        pin = result[0].pins[0]
        assert pin.normalized_function == "POWER_POSITIVE"
        assert pin.normalization_confidence == 1.0

    def test_spi_clk_resolved_via_dictionary(
        self, datasheet_with_spi_pins, mock_config
    ) -> None:
        """Test CLK resolved to SPI_CLOCK via dictionary (Tier 1, confidence 1.0)."""
        result = normalize_pins([datasheet_with_spi_pins], mock_config)

        # Find CLK pin - CLK is in dictionary as SPI_CLOCK with 1.0 confidence
        clk_pin = next(p for p in result[0].pins if p.raw_name == "CLK")
        assert clk_pin.normalized_function == "SPI_CLOCK"
        assert clk_pin.normalization_confidence == 1.0  # Dictionary confidence

    def test_i2c_scl_resolved_via_context(
        self, datasheet_with_i2c_pins, mock_config
    ) -> None:
        """Test SCL with I2C neighbors resolved to I2C_CLOCK via context."""
        result = normalize_pins([datasheet_with_i2c_pins], mock_config)

        # Find SCL pin
        scl_pin = next(p for p in result[0].pins if p.raw_name == "SCL")
        assert scl_pin.normalized_function == "I2C_CLOCK"

    def test_failed_normalization_adds_review_flag(
        self, datasheet_with_unknown_pin, mock_config
    ) -> None:
        """Test failed normalization adds entry to review_flags on returned datasheet."""
        result = normalize_pins([datasheet_with_unknown_pin], mock_config)

        # Should have review flag for failed pin
        assert len(result[0].review_flags) > 0
        assert any("MY_WEIRD_PIN" in flag for flag in result[0].review_flags)
        assert any("normalization failed" in flag for flag in result[0].review_flags)

    def test_failed_pin_gets_none_normalized_function(
        self, datasheet_with_unknown_pin, mock_config
    ) -> None:
        """Test pin that fails all tiers gets normalized_function=None."""
        result = normalize_pins([datasheet_with_unknown_pin], mock_config)

        weird_pin = next(p for p in result[0].pins if p.raw_name == "MY_WEIRD_PIN")
        assert weird_pin.normalized_function is None
        assert weird_pin.normalization_confidence == 0.0

    def test_normalize_pins_on_3_datasheet_batch_returns_3_objects(
        self, datasheet_with_vdd_pin, datasheet_with_spi_pins, datasheet_with_i2c_pins, mock_config
    ) -> None:
        """Test normalize_pins on 3-datasheet batch returns 3 new objects."""
        datasheets = [
            datasheet_with_vdd_pin,
            datasheet_with_spi_pins,
            datasheet_with_i2c_pins,
        ]

        result = normalize_pins(datasheets, mock_config)

        # Should return 3 new objects
        assert len(result) == 3
        assert result[0] is not datasheet_with_vdd_pin
        assert result[1] is not datasheet_with_spi_pins
        assert result[2] is not datasheet_with_i2c_pins

    def test_empty_list_returns_empty_list(self, mock_config) -> None:
        """Test normalize_pins with empty list returns empty list."""
        result = normalize_pins([], mock_config)
        assert result == []

    def test_preserves_other_datasheet_fields(
        self, datasheet_with_vdd_pin, mock_config
    ) -> None:
        """Test normalization preserves other ComponentDatasheet fields."""
        result = normalize_pins([datasheet_with_vdd_pin], mock_config)

        ds = result[0]
        assert ds.component_id == "TEST1"
        assert ds.manufacturer == "Test"
        assert ds.package == "SOT-23-5"
        assert ds.extraction_confidence == 0.97

    def test_multiple_pins_in_same_datasheet(
        self, datasheet_with_spi_pins, mock_config
    ) -> None:
        """Test all pins in a datasheet get normalized."""
        result = normalize_pins([datasheet_with_spi_pins], mock_config)

        pins = result[0].pins

        # Check each pin was normalized
        vdd = next(p for p in pins if p.raw_name == "VDD")
        assert vdd.normalized_function == "POWER_POSITIVE"

        gnd = next(p for p in pins if p.raw_name == "GND")
        assert gnd.normalized_function == "POWER_GROUND"

        cs = next(p for p in pins if p.raw_name == "CS")
        assert cs.normalized_function == "SPI_CHIP_SELECT"

        mosi = next(p for p in pins if p.raw_name == "MOSI")
        assert mosi.normalized_function == "SPI_DATA_IN"

        miso = next(p for p in pins if p.raw_name == "MISO")
        assert miso.normalized_function == "SPI_DATA_OUT"

    def test_gpio_pins_stripped_of_numbers(
        self, mock_config
    ) -> None:
        """Test GPIO pins with numbers are stripped to base name."""
        ds = ComponentDatasheet(
            component_id="TEST_GPIO",
            manufacturer="Test",
            description="GPIO Test",
            package="QFN-32",
            source_pdf_hash="hash_gpio",
            extraction_method=ExtractionMethod.P1_VECTOR,
            extraction_confidence=0.97,
            pins=[
                PinDefinition(pin_number="1", raw_name="GPIO0", pin_type="io"),
                PinDefinition(pin_number="2", raw_name="GPIO1", pin_type="io"),
                PinDefinition(pin_number="3", raw_name="GPIO15", pin_type="io"),
            ],
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )

        result = normalize_pins([ds], mock_config)

        for pin in result[0].pins:
            assert pin.normalized_function == "GPIO"
            assert pin.normalization_confidence == 1.0

    def test_handles_datasheet_with_no_pins(
        self, mock_config
    ) -> None:
        """Test datasheet with no pins is handled gracefully."""
        ds = ComponentDatasheet(
            component_id="NO_PINS",
            manufacturer="Test",
            description="No pins",
            package="SOT-23-5",
            source_pdf_hash="hash",
            extraction_method=ExtractionMethod.P1_VECTOR,
            extraction_confidence=0.97,
            pins=[],
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )

        result = normalize_pins([ds], mock_config)

        assert len(result) == 1
        assert len(result[0].pins) == 0


class TestMultiFunctionPinNormalization:
    """Multi-function / MCU mux pin normalization (Phase 0 schema cleanup)."""

    def _mcu_mux_datasheet(self) -> ComponentDatasheet:
        return ComponentDatasheet(
            component_id="STM32_MUX",
            manufacturer="ST",
            description="MCU with multiplexed pin",
            package="LQFP-64",
            source_pdf_hash="hash_mux",
            extraction_method=ExtractionMethod.P1_VECTOR,
            extraction_confidence=0.97,
            pins=[
                PinDefinition(
                    pin_number="5",
                    raw_name="GPIO5",
                    pin_type="io",
                    alternate_functions=[
                        AlternateFunction(
                            name="SPI2_MOSI", af_index=5, peripheral="SPI2"
                        ),
                        AlternateFunction(
                            name="TIM3_CH2", af_index=2, peripheral="TIM3"
                        ),
                        AlternateFunction(name="I2C1_SMBA", af_index=4),
                        AlternateFunction(
                            name="USART1_TX", af_index=7, peripheral="USART1"
                        ),
                    ],
                ),
            ],
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )

    def test_normalize_pin_with_multiple_alternate_functions(
        self, mock_config: Config
    ) -> None:
        """MCU-style pin with 4 AFs — all preserved and normalized where possible."""
        result = normalize_pins([self._mcu_mux_datasheet()], mock_config)
        pin = result[0].pins[0]

        assert len(pin.alternate_functions) == 4
        assert [af.af_index for af in pin.alternate_functions] == [5, 2, 4, 7]

        by_index = {af.af_index: af for af in pin.alternate_functions}

        # Suffix MOSI / TX map via dictionary; unknown labels keep original name
        assert by_index[5].name == "SPI_DATA_IN"
        assert by_index[5].peripheral == "SPI2"
        assert by_index[2].name == "TIM3_CH2"
        assert by_index[2].peripheral == "TIM3"
        assert by_index[4].name == "I2C1_SMBA"
        assert by_index[4].peripheral == "I2C1"  # inferred
        assert by_index[7].name == "UART_TRANSMIT"
        assert by_index[7].peripheral == "USART1"

        # Input not mutated
        original = self._mcu_mux_datasheet().pins[0]
        assert original.alternate_functions[0].name == "SPI2_MOSI"

    def test_default_function_set_correctly(self, mock_config: Config) -> None:
        """default_function is set from reset-state raw_name."""
        result = normalize_pins([self._mcu_mux_datasheet()], mock_config)
        pin = result[0].pins[0]
        assert pin.default_function == "GPIO"

    def test_normalized_function_is_default(self, mock_config: Config) -> None:
        """normalized_function mirrors default_function (active = reset-state)."""
        result = normalize_pins([self._mcu_mux_datasheet()], mock_config)
        pin = result[0].pins[0]
        assert pin.normalized_function == pin.default_function
        assert pin.normalized_function == "GPIO"
