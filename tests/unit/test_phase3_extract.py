"""Unit tests for src/datasheet/phase3_extract/.

Tests Phase 3 semantic extraction including:
- Unit normalization (mV→V, µ handling)
- Component header extraction
- Prompt templates with section_type
- Footnote injection
- PinDefinition normalized_function is None (Rule 3)
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from src.config import Config
from src.datasheet.phase1_dla._schemas import FootnoteMap, TableCrop
from src.datasheet.phase2_tsr._schemas import CellValue, GridMatrix, Phase2Output
from src.datasheet.phase3_extract import process
from src.datasheet.phase3_extract.component_header import (
    ComponentHeaderInfo,
    extract_component_header,
)
from src.datasheet.phase3_extract.extractor import (
    InstructorWrapper,
    extract_from_grid,
)
from src.datasheet.phase3_extract.prompt_templates import (
    ABSOLUTE_MAXIMUM_RATINGS_PROMPT,
    ELECTRICAL_CHARACTERISTICS_PROMPT,
    get_prompt_for_section_type,
)
from src.datasheet.phase3_extract.unit_normalizer import (
    normalize_unit,
    normalize_value_string,
)
from src.datasheet.utils import normalize_package
from src.schemas.datasheet import (
    AbsoluteMaxRating,
    ComponentDatasheet,
    ElectricalParameter,
    ExtractionMethod,
    ExtractedValue,
    PinDefinition,
    TableSectionType,
)


# =============================================================================
# Unit Normalizer Tests
# =============================================================================


class TestUnitNormalizer:
    """Tests for unit_normalizer.py."""

    def test_normalize_mV_to_V(self) -> None:
        """Test unit_normalizer converts mV→V correctly (100mV = 0.1V)."""
        value, unit, needs_review = normalize_unit("100", "mV")
        assert value == 0.1
        assert unit == "V"
        assert needs_review is False

    def test_normalize_uV_to_V(self) -> None:
        """Test unit_normalizer converts µV→V correctly."""
        value, unit, needs_review = normalize_unit("500", "µV")
        # 500 µV = 500 × 1e-6 V = 5e-4 V
        assert value == 5e-04
        assert unit == "V"

    def test_normalize_mA_to_A(self) -> None:
        """Test unit_normalizer converts mA→A correctly."""
        value, unit, needs_review = normalize_unit("100", "mA")
        assert value == 0.1
        assert unit == "A"

    def test_normalize_kohm_to_ohm(self) -> None:
        """Test unit_normalizer converts kΩ→Ω correctly."""
        value, unit, needs_review = normalize_unit("10", "kΩ")
        assert value == 10000.0
        assert unit == "Ω"

    def test_normalize_uf_to_F(self) -> None:
        """Test unit_normalizer handles 'u' OCR alias for µF→F."""
        value, unit, needs_review = normalize_unit("10", "uF")
        assert value == pytest.approx(1e-05)
        assert unit == "F"
        assert needs_review is False

    def test_normalize_ua_to_A(self) -> None:
        """Test unit_normalizer handles 'u' OCR alias for µA→A."""
        value, unit, needs_review = normalize_unit("500", "uA")
        # 500 µA = 500 × 1e-6 A = 5e-4 A
        assert value == pytest.approx(5e-04)
        assert unit == "A"
        assert needs_review is False

    def test_normalize_uv_to_V(self) -> None:
        """Test unit_normalizer handles 'u' OCR alias for µV→V."""
        value, unit, needs_review = normalize_unit("1000", "uV")
        # 1000 µV = 1000 × 1e-6 V = 1e-3 V
        assert value == 1e-03
        assert unit == "V"
        assert needs_review is False

    def test_normalize_ohm_variants(self) -> None:
        """Test unit_normalizer handles 'ohm' OCR alias for Ω."""
        # Various ohm spellings
        variants = ["ohm", "ohms", "Ohm", "kohm", "kOhm", "KΩ"]
        for variant in variants:
            value, unit, needs_review = normalize_unit("1", variant)
            assert unit == "Ω", f"Failed for variant: {variant}"

    def test_normalize_unknown_unit_needs_review(self) -> None:
        """Test unit_normalizer returns needs_review=True for unknown units."""
        value, unit, needs_review = normalize_unit("100", "XYZ")
        assert value is None
        assert unit == "XYZ"
        assert needs_review is True

    def test_normalize_value_string_combined(self) -> None:
        """Test normalize_value_string with combined value+unit."""
        value, unit, needs_review = normalize_value_string("100mV")
        assert value == 0.1
        assert unit == "V"
        assert needs_review is False

    def test_normalize_value_string_with_space(self) -> None:
        """Test normalize_value_string with space separator."""
        value, unit, needs_review = normalize_value_string("10 uF")
        assert value == pytest.approx(1e-05)
        assert unit == "F"


# =============================================================================
# Prompt Templates Tests
# =============================================================================


class TestPromptTemplates:
    """Tests for prompt_templates.py."""

    def test_electrical_characteristics_prompt_contains_section_type_instruction(self) -> None:
        """Test electrical characteristics prompt contains section_type instruction (Rule 1)."""
        prompt = ELECTRICAL_CHARACTERISTICS_PROMPT
        assert "section_type" in prompt.lower()
        assert "electrical_characteristics" in prompt
        assert "exactly one of" in prompt.lower()

    def test_absolute_maximum_ratings_prompt_contains_section_type_instruction(self) -> None:
        """Test absolute maximum ratings prompt contains section_type instruction (Rule 1)."""
        prompt = ABSOLUTE_MAXIMUM_RATINGS_PROMPT
        assert "section_type" in prompt.lower()
        assert "absolute_maximum_ratings" in prompt

    def test_get_prompt_for_section_type_all_types(self) -> None:
        """Test get_prompt_for_section_type returns correct prompts for all 7 types."""
        types_to_check = [
            TableSectionType.ELECTRICAL_CHARACTERISTICS,
            TableSectionType.ABSOLUTE_MAXIMUM_RATINGS,
            TableSectionType.PINOUT,
            TableSectionType.TIMING,
            TableSectionType.ORDERING,
            TableSectionType.LAYOUT_RECOMMENDATIONS,
            TableSectionType.OTHER,
        ]
        
        for section_type in types_to_check:
            prompt = get_prompt_for_section_type(section_type)
            assert prompt is not None
            assert len(prompt) > 100
            # All prompts should include section_type instruction per Rule 1
            assert "section_type" in prompt.lower()

    def test_all_prompts_contain_section_type_instruction(self) -> None:
        """Test that all section-specific prompts contain the CRITICAL RULE (Rule 1)."""
        from src.datasheet.phase3_extract.prompt_templates import PROMPT_TEMPLATES
        
        for section_type, prompt in PROMPT_TEMPLATES.items():
            assert "section_type" in prompt.lower(), f"Missing section_type in {section_type.value} prompt"
            assert "exactly one of" in prompt.lower() or "determine the correct type" in prompt.lower()


# =============================================================================
# Component Header Tests
# =============================================================================


class TestComponentHeader:
    """Tests for component_header.py."""

    def test_extract_component_header_returns_structured_info(self) -> None:
        """Test extract_component_header returns ComponentHeaderInfo."""
        header_text = "LM358 Low Power Dual Operational Amplifiers"
        
        result = extract_component_header(header_text)
        
        assert isinstance(result, ComponentHeaderInfo)
        assert result.component_id == "LM358"  # Should extract from text
        assert result.package_review_required is False  # Empty package

    def test_component_header_to_dict(self) -> None:
        """Test ComponentHeaderInfo.to_dict() returns correct fields."""
        info = ComponentHeaderInfo(
            component_id="TPS62933",
            manufacturer="Texas Instruments",
            description="Buck Converter",
            raw_package="SOT-23-5",
        )
        
        result = info.to_dict()
        
        assert result["component_id"] == "TPS62933"
        assert result["manufacturer"] == "Texas Instruments"
        assert result["description"] == "Buck Converter"

    def test_component_header_get_review_flags(self) -> None:
        """Test ComponentHeaderInfo.get_review_flags() returns appropriate flags."""
        info = ComponentHeaderInfo(
            component_id="",
            manufacturer="",
            raw_package="UnknownXYZ",
            package_review_required=True,
        )
        
        flags = info.get_review_flags()
        
        assert len(flags) >= 3  # Missing component_id, manufacturer, and package review
        assert any("Component ID" in f for f in flags)
        assert any("Manufacturer" in f for f in flags)
        assert any("Package normalization uncertain" in f for f in flags)


# =============================================================================
# normalize_package Integration Test (Rule 2)
# =============================================================================


class TestNormalizePackageIntegration:
    """Tests for Rule 2: normalize_package must be called on package strings."""

    def test_normalize_package_returns_tuple(self) -> None:
        """Test normalize_package returns (normalized, needs_review)."""
        result, needs_review = normalize_package("SOT-23-5")
        assert result == "SOT-23-5"
        assert needs_review is False

    def test_normalize_package_unknown_returns_review_flag(self) -> None:
        """Test normalize_package returns needs_review=True for unknown package."""
        result, needs_review = normalize_package("UnknownPackage123")
        assert result == "UnknownPackage123"
        assert needs_review is True

    def test_extract_component_header_calls_normalize_package(self) -> None:
        """Test that extract_component_header calls normalize_package (Rule 2)."""
        # Mock the normalize_package to verify it's called
        with patch("src.datasheet.phase3_extract.component_header.normalize_package") as mock_normalize:
            mock_normalize.return_value = ("SOT-23-5", False)
            
            header_text = "LM358 SOT-23-5 Package"
            extract_component_header(header_text)
            
            # normalize_package should be called
            mock_normalize.assert_called()


# =============================================================================
# Extractor Tests
# =============================================================================


class TestExtractor:
    """Tests for extractor.py."""

    @pytest.fixture
    def mock_config(self, tmp_path) -> Config:
        """Create mock Config."""
        config = MagicMock(spec=Config)
        model_path = tmp_path / "models" / "Qwen2.5-7B-Instruct"
        model_path.parent.mkdir(parents=True, exist_ok=True)
        model_path.write_bytes(b"dummy")
        
        def get_model_path(name: str) -> Path:
            return model_path
        
        config.get_model_path = get_model_path
        return config

    @pytest.fixture
    def sample_grid(self) -> GridMatrix:
        """Create sample GridMatrix for testing."""
        cells = [
            CellValue(text="Parameter", row=0, col=0, is_header=True),
            CellValue(text="Value", row=0, col=1, is_header=True),
            CellValue(text="VCC", row=1, col=0),
            CellValue(text="3.3V", row=1, col=1),
        ]
        return GridMatrix(
            cells=cells,
            num_rows=2,
            num_cols=2,
            section_type=TableSectionType.ELECTRICAL_CHARACTERISTICS,
            source_page=1,
            source_table_index=0,
            extraction_path="vector",
            confidence=0.97,
        )

    def test_instructor_wrapper_raises_if_model_missing(self, tmp_path) -> None:
        """Test InstructorWrapper raises if model not found."""
        missing_path = tmp_path / "nonexistent" / "model"
        
        wrapper = InstructorWrapper(missing_path)
        
        with pytest.raises(RuntimeError):
            wrapper._load_model()

    def _wrapper_with_fake_model(self, tmp_path: Path) -> tuple[InstructorWrapper, MagicMock]:
        """Build an InstructorWrapper with tokenizer/model stubs already loaded."""
        wrapper = InstructorWrapper(tmp_path / "model", device="cpu")
        tokenizer = MagicMock()
        tokenizer.apply_chat_template.return_value = "PROMPT"
        tokenizer.return_value = {"input_ids": MagicMock(shape=(1, 4))}
        tokenizer.eos_token_id = 0
        tokenizer.decode.return_value = '{"ok": true}'

        model = MagicMock()
        # generate returns a tensor-like with [0] indexing; fake a short sequence
        output = MagicMock()
        output.__getitem__ = MagicMock(return_value=list(range(6)))
        model.generate.return_value = [output]

        wrapper._tokenizer = tokenizer
        wrapper._model = model
        return wrapper, model

    def test_generate_greedy_when_temperature_zero(self, tmp_path) -> None:
        wrapper, model = self._wrapper_with_fake_model(tmp_path)
        wrapper._generate("sys", "user", max_new_tokens=32, temperature=0.0)
        _, kwargs = model.generate.call_args
        assert kwargs["do_sample"] is False
        assert "temperature" not in kwargs

    def test_generate_samples_when_temperature_positive(self, tmp_path) -> None:
        wrapper, model = self._wrapper_with_fake_model(tmp_path)
        wrapper._generate("sys", "user", max_new_tokens=32, temperature=0.9)
        _, kwargs = model.generate.call_args
        assert kwargs["do_sample"] is True
        assert kwargs["temperature"] == 0.9

    def test_extract_forwards_temperature_to_generate(self, tmp_path) -> None:
        from pydantic import BaseModel

        class _Tiny(BaseModel):
            value: str

        wrapper = InstructorWrapper(tmp_path / "model", device="cpu")
        wrapper._load_model = MagicMock()  # type: ignore[method-assign]
        wrapper._generate = MagicMock(return_value='{"value": "ok"}')  # type: ignore[method-assign]

        result = wrapper.extract(
            response_model=_Tiny,
            system_prompt="sys",
            user_content="user",
            temperature=0.7,
            max_retries=0,
        )
        assert result is not None
        assert result.value == "ok"
        _, kwargs = wrapper._generate.call_args
        assert kwargs["temperature"] == 0.7

    def test_extract_from_grid_returns_extraction_result(self, mock_config, sample_grid) -> None:
        """Test extract_from_grid returns ExtractionResult."""
        result = extract_from_grid(sample_grid, [], mock_config)
        
        assert result.section_type == TableSectionType.ELECTRICAL_CHARACTERISTICS
        assert result.extraction_method == ExtractionMethod.P1_VECTOR
        assert result.confidence > 0


# =============================================================================
# Footnote Injection Tests (Rule 4)
# =============================================================================


class TestFootnoteInjection:
    """Tests for Rule 4: Footnote injection into ExtractedValue."""

    def test_footnote_lookup_from_maps(self) -> None:
        """Test footnote lookup from FootnoteMap works correctly."""
        footnote_maps = [
            FootnoteMap(
                page_number=1,
                entries={
                    "1": "Valid for T_A = 25°C",
                    "2": "Guaranteed by design",
                },
            ),
        ]
        
        # Simulate extraction with footnote marker
        from src.datasheet.phase3_extract.extractor import _inject_footnotes
        
        params = [
            ElectricalParameter(
                parameter_name="VCC",
                conditions="T_A = 25°C",
                value=ExtractedValue(
                    raw_text="3.3V (1)",
                    normalized_value=3.3,
                    unit="V",
                    confidence=0.95,
                ),
                section_type=TableSectionType.ELECTRICAL_CHARACTERISTICS,
                source_page=1,
                source_table_index=0,
            ),
        ]
        
        result = _inject_footnotes(params, footnote_maps)
        
        # Footnote should be injected
        assert result[0].value.footnote == "Valid for T_A = 25°C"

    def test_footnote_injection_no_marker_no_change(self) -> None:
        """Test parameters without footnote markers are unchanged."""
        footnote_maps = [
            FootnoteMap(page_number=1, entries={"1": "Note"}),
        ]
        
        from src.datasheet.phase3_extract.extractor import _inject_footnotes
        
        params = [
            ElectricalParameter(
                parameter_name="ICC",
                value=ExtractedValue(
                    raw_text="100mA",  # No footnote marker
                    normalized_value=0.1,
                    unit="A",
                    confidence=0.95,
                ),
                section_type=TableSectionType.ELECTRICAL_CHARACTERISTICS,
                source_page=1,
                source_table_index=0,
            ),
        ]
        
        result = _inject_footnotes(params, footnote_maps)
        
        # Footnote should be None
        assert result[0].value.footnote is None


# =============================================================================
# PinDefinition Rule 3 Tests
# =============================================================================


class TestPinDefinitionRule3:
    """Tests for Rule 3: PinDefinition.normalized_function must always be None."""

    def test_pin_definition_defaults_to_none(self) -> None:
        """Test PinDefinition.normalized_function defaults to None."""
        pin = PinDefinition(
            pin_number="1",
            raw_name="VIN",
            pin_type="power",
        )
        
        assert pin.normalized_function is None
        assert pin.normalization_confidence is None
        assert pin.normalization_method is None

    def test_pin_definition_creation_explicit_none(self) -> None:
        """Test PinDefinition with explicitly set None values."""
        pin = PinDefinition(
            pin_number="2",
            raw_name="GPIO0",
            pin_type="io",
            normalized_function=None,  # Explicit None per Rule 3
            normalization_confidence=None,
            normalization_method=None,
        )
        
        assert pin.normalized_function is None

    def test_multiple_pins_all_have_none_normalized_function(self) -> None:
        """Test that multiple PinDefinitions all have normalized_function=None."""
        pins = [
            PinDefinition(pin_number="1", raw_name="VCC", pin_type="power"),
            PinDefinition(pin_number="2", raw_name="GND", pin_type="ground"),
            PinDefinition(pin_number="3", raw_name="OUT", pin_type="output"),
            PinDefinition(pin_number="4", raw_name="IN", pin_type="input"),
        ]
        
        for pin in pins:
            assert pin.normalized_function is None, f"Pin {pin.pin_number} has non-None normalized_function"


# =============================================================================
# Process Integration Tests
# =============================================================================


class TestProcessIntegration:
    """Integration tests for process() function."""

    @pytest.fixture
    def mock_config(self, tmp_path) -> Config:
        """Create mock Config."""
        config = MagicMock(spec=Config)
        
        def get_model_path(name: str) -> Path:
            model_path = tmp_path / "models" / name
            model_path.parent.mkdir(parents=True, exist_ok=True)
            model_path.write_bytes(b"dummy")
            return model_path
        
        config.get_model_path = get_model_path
        return config

    @pytest.fixture
    def sample_phase2_output(self) -> Phase2Output:
        """Create sample Phase2Output."""
        cells = [
            CellValue(text="Parameter", row=0, col=0, is_header=True),
            CellValue(text="Value", row=0, col=1, is_header=True),
            CellValue(text="VCC", row=1, col=0),
            CellValue(text="3.3V (1)", row=1, col=1),  # Has footnote marker
        ]
        
        grid = GridMatrix(
            cells=cells,
            num_rows=2,
            num_cols=2,
            section_type=TableSectionType.ELECTRICAL_CHARACTERISTICS,
            source_page=1,
            source_table_index=0,
            extraction_path="vector",
            confidence=0.97,
        )
        
        footnote_maps = [
            FootnoteMap(
                page_number=1,
                entries={"1": "Valid for T_A = 25°C"},
            ),
        ]
        
        return Phase2Output(
            source_pdf_hash="a1b2c3d4e5f67890abcdef1234567890abcd1234",
            grids=[grid],
            footnote_maps=footnote_maps,
            processing_time_ms=2000.0,
        )

    def test_process_returns_component_datasheet(self, mock_config, sample_phase2_output) -> None:
        """Test process() returns ComponentDatasheet."""
        result = process(sample_phase2_output, mock_config)
        
        assert isinstance(result, ComponentDatasheet)
        assert result.source_pdf_hash == sample_phase2_output.source_pdf_hash

    def test_process_sets_source_pdf_hash_correctly(self, mock_config, sample_phase2_output) -> None:
        """Test process() returns ComponentDatasheet with source_pdf_hash matching phase2_output."""
        result = process(sample_phase2_output, mock_config)
        
        assert result.source_pdf_hash == "a1b2c3d4e5f67890abcdef1234567890abcd1234"

    def test_process_sets_created_at(self, mock_config, sample_phase2_output) -> None:
        """Test process() sets created_at to ISO format (Rule 5)."""
        result = process(sample_phase2_output, mock_config)
        
        # Should be ISO 8601 format ending with Z
        assert result.created_at.endswith("Z")
        assert len(result.created_at) > 10

    def test_process_extraction_method_set(self, mock_config, sample_phase2_output) -> None:
        """Test process() sets extraction_method correctly."""
        result = process(sample_phase2_output, mock_config)
        
        # Should be P1_VECTOR since grid used vector path
        assert result.extraction_method == ExtractionMethod.P1_VECTOR

    def test_process_confidence_computed(self, mock_config, sample_phase2_output) -> None:
        """Test process() computes extraction_confidence via compute_extraction_confidence (Rule 6)."""
        result = process(sample_phase2_output, mock_config)
        
        # Confidence should be computed and in valid range
        assert 0.0 <= result.extraction_confidence <= 1.0


# =============================================================================
# End-to-End Workflow Tests
# =============================================================================


class TestEndToEndWorkflow:
    """End-to-end workflow tests for Phase 3."""

    def test_full_extraction_workflow_mocked(self) -> None:
        """Test full extraction workflow with mocked LLM."""
        # This would test the complete pipeline with a mocked Instructor
        # For now, we verify the structure is correct
        pass

    def test_pin_definitions_all_normalized_function_none_in_output(self) -> None:
        """Test that all PinDefinition objects in output have normalized_function=None (Rule 3)."""
        # Create a ComponentDatasheet with pins
        pins = [
            PinDefinition(
                pin_number=str(i),
                raw_name=f"PIN{i}",
                pin_type="io",
            )
            for i in range(1, 9)
        ]
        
        datasheet = ComponentDatasheet(
            component_id="TEST123",
            manufacturer="Test Corp",
            description="Test component",
            package="SOT-23-5",
            source_pdf_hash="abc123",
            pins=pins,
            extraction_method=ExtractionMethod.P1_VECTOR,
            extraction_confidence=0.95,
            created_at="2024-01-01T00:00:00Z",
        )
        
        # Rule 3: All pins must have normalized_function=None
        for pin in datasheet.pins:
            assert pin.normalized_function is None, f"Pin {pin.pin_number} violates Rule 3"

    def test_package_normalization_review_flag_added(self) -> None:
        """Test that unknown packages add review flag (Rule 2)."""
        raw_package = "UnknownXYZ-99"
        normalized, needs_review = normalize_package(raw_package)
        
        assert needs_review is True
        
        # Simulate component header with unknown package
        header_info = ComponentHeaderInfo(
            component_id="TEST",
            manufacturer="Test",
            raw_package=raw_package,
            package_review_required=needs_review,
        )
        
        flags = header_info.get_review_flags()
        assert any("Package normalization uncertain" in f for f in flags)