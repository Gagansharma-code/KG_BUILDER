"""Gate tests for the weak-model netlist proposer
(src/schematic/llm_netlist_proposer.py).

The InstructorWrapper is never constructed for real here — _get_wrapper()
is patched at its source in every test, matching the "mocked DB, no live
PostgreSQL" convention used in tests/retrieval/test_retrieval.py. No GPU,
no model weights required to run this file.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.schemas.datasheet import (
    ComponentDatasheet,
    ExtractionMethod,
    PinDefinition,
    PinRole,
)
from src.schemas.intent import (
    BOMEntry,
    DesignMethodology,
    ImprovedIntentDict,
    ValidatedBOM,
)
from src.schematic._ref_mapper import build_ref_map
from src.schematic.llm_netlist_proposer import (
    ProposedNetlistResult,
    _LLMNetConnection,
    _LLMNetlistProposal,
    _LLMPinRef,
    propose_netlist_llm,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

CONFIG = MagicMock()


def _intent(goal: str = "3.3V LDO regulator") -> ImprovedIntentDict:
    return ImprovedIntentDict(
        goal=goal,
        application="test",
        design_methodology=DesignMethodology.STANDARD_SMD,
        board_type="standard_SMD",
        raw_prompt="test",
    )


def _pin_def(pin_number: str, raw_name: str, role: PinRole) -> PinDefinition:
    return PinDefinition(
        pin_number=pin_number,
        raw_name=raw_name,
        normalized_function=raw_name,
        pin_role=role,
        normalization_confidence=0.9,
        pin_type="power",
    )


def _datasheet(component_id: str, pins: list[PinDefinition]) -> ComponentDatasheet:
    return ComponentDatasheet(
        component_id=component_id,
        manufacturer="Test Inc",
        description="test IC",
        package="SOIC-8",
        source_pdf_hash="abc123",
        extraction_method=ExtractionMethod.P1_VECTOR,
        extraction_confidence=0.9,
        created_at="2026-01-01T00:00:00Z",
        pins=pins,
    )


def _bom_entry(ref: str, specific_part: str, component_type: str = "regulator") -> BOMEntry:
    return BOMEntry(
        ref=ref,
        component_type=component_type,
        specific_part=specific_part,
        justification="test",
        source="test",
        confidence=0.9,
    )


def _bom(entries: list[BOMEntry]) -> ValidatedBOM:
    return ValidatedBOM(
        design_id="design-1",
        intent=_intent(),
        components=entries,
        total_confidence=0.9,
        review_required=False,
        created_at="2026-01-01T00:00:00Z",
    )


def _one_ic_fixture() -> tuple[ValidatedBOM, ComponentDatasheet, dict]:
    ds = _datasheet("IC1", [
        _pin_def("1", "VCC", PinRole.POWER_IN),
        _pin_def("2", "GND", PinRole.GROUND),
        _pin_def("3", "VOUT", PinRole.POWER_OUT),
    ])
    bom = _bom([_bom_entry("U1", "IC1")])
    ref_map = build_ref_map(bom, [ds])
    return bom, ds, ref_map


def _fake_wrapper(extract_return=None, extract_side_effect=None) -> MagicMock:
    wrapper = MagicMock()
    if extract_side_effect is not None:
        wrapper.extract.side_effect = extract_side_effect
    else:
        wrapper.extract.return_value = extract_return
    return wrapper


# ── Well-formed response ─────────────────────────────────────────────────────

def test_well_formed_response_produces_netlist():
    bom, ds, ref_map = _one_ic_fixture()
    proposal = _LLMNetlistProposal(connections=[
        _LLMNetConnection(net_name="GND", net_type="power",
                           pins=[_LLMPinRef(ref="U1", pin_number="2")]),
        _LLMNetConnection(net_name="VCC_3V3", net_type="power",
                           pins=[_LLMPinRef(ref="U1", pin_number="1")]),
    ])
    wrapper = _fake_wrapper(extract_return=proposal)

    with patch("src.schematic.llm_netlist_proposer._get_wrapper", return_value=wrapper):
        result = propose_netlist_llm(bom, [ds], ref_map, CONFIG)

    assert isinstance(result, ProposedNetlistResult)
    assert result.parse_succeeded is True
    assert len(result.netlist) == 2
    assert {n.net_name for n in result.netlist} == {"GND", "VCC_3V3"}
    assert result.confidence > 0.0


def test_pin_name_resolved_from_datasheet_normalized_function():
    bom, ds, ref_map = _one_ic_fixture()
    proposal = _LLMNetlistProposal(connections=[
        _LLMNetConnection(net_name="GND", net_type="power",
                           pins=[_LLMPinRef(ref="U1", pin_number="2")]),
    ])
    wrapper = _fake_wrapper(extract_return=proposal)

    with patch("src.schematic.llm_netlist_proposer._get_wrapper", return_value=wrapper):
        result = propose_netlist_llm(bom, [ds], ref_map, CONFIG)

    assert result.netlist[0].connections[0].pin_name == "GND"


# ── Failure modes — never raises ────────────────────────────────────────────

def test_extraction_returns_none():
    bom, ds, ref_map = _one_ic_fixture()
    wrapper = _fake_wrapper(extract_return=None)

    with patch("src.schematic.llm_netlist_proposer._get_wrapper", return_value=wrapper):
        result = propose_netlist_llm(bom, [ds], ref_map, CONFIG)

    assert result.parse_succeeded is False
    assert result.netlist == []
    assert result.confidence == 0.0


def test_extraction_exception_never_raises():
    bom, ds, ref_map = _one_ic_fixture()
    wrapper = _fake_wrapper(extract_side_effect=RuntimeError("model OOM"))

    with patch("src.schematic.llm_netlist_proposer._get_wrapper", return_value=wrapper):
        result = propose_netlist_llm(bom, [ds], ref_map, CONFIG)

    assert result.parse_succeeded is False
    assert result.netlist == []


def test_unknown_ref_in_proposal_is_dropped():
    bom, ds, ref_map = _one_ic_fixture()  # BOM only has U1
    proposal = _LLMNetlistProposal(connections=[
        _LLMNetConnection(net_name="GND", net_type="power",
                           pins=[_LLMPinRef(ref="U99", pin_number="2")]),
    ])
    wrapper = _fake_wrapper(extract_return=proposal)

    with patch("src.schematic.llm_netlist_proposer._get_wrapper", return_value=wrapper):
        result = propose_netlist_llm(bom, [ds], ref_map, CONFIG)

    assert result.netlist == []
    assert result.parse_succeeded is False


def test_get_wrapper_raising_never_propagates():
    bom, ds, ref_map = _one_ic_fixture()

    with patch(
        "src.schematic.llm_netlist_proposer._get_wrapper",
        side_effect=OSError("model file not found"),
    ):
        result = propose_netlist_llm(bom, [ds], ref_map, CONFIG)

    assert isinstance(result, ProposedNetlistResult)
    assert result.parse_succeeded is False


# ── Prompt construction ──────────────────────────────────────────────────────

def test_feedback_appears_in_user_content():
    bom, ds, ref_map = _one_ic_fixture()
    wrapper = _fake_wrapper(extract_return=_LLMNetlistProposal(connections=[]))

    with patch("src.schematic.llm_netlist_proposer._get_wrapper", return_value=wrapper):
        propose_netlist_llm(
            bom, [ds], ref_map, CONFIG,
            feedback="Net GND has a driver conflict on pin 2",
        )

    _, kwargs = wrapper.extract.call_args
    assert "driver conflict" in kwargs["user_content"]


def test_no_feedback_on_first_round_is_omitted():
    bom, ds, ref_map = _one_ic_fixture()
    wrapper = _fake_wrapper(extract_return=_LLMNetlistProposal(connections=[]))

    with patch("src.schematic.llm_netlist_proposer._get_wrapper", return_value=wrapper):
        propose_netlist_llm(bom, [ds], ref_map, CONFIG, feedback=None)

    _, kwargs = wrapper.extract.call_args
    assert "previous attempt" not in kwargs["user_content"]


def test_prompt_includes_every_bom_ref():
    ds1 = _datasheet("IC1", [_pin_def("1", "VCC", PinRole.POWER_IN)])
    ds2 = _datasheet("IC2", [_pin_def("1", "GND", PinRole.GROUND)])
    bom = _bom([_bom_entry("U1", "IC1"), _bom_entry("U2", "IC2", "capacitor")])
    ref_map = build_ref_map(bom, [ds1, ds2])
    wrapper = _fake_wrapper(extract_return=_LLMNetlistProposal(connections=[]))

    with patch("src.schematic.llm_netlist_proposer._get_wrapper", return_value=wrapper):
        propose_netlist_llm(bom, [ds1, ds2], ref_map, CONFIG)

    _, kwargs = wrapper.extract.call_args
    assert "U1" in kwargs["user_content"]
    assert "U2" in kwargs["user_content"]


def test_temperature_and_model_used_recorded_on_result():
    bom, ds, ref_map = _one_ic_fixture()
    wrapper = _fake_wrapper(extract_return=_LLMNetlistProposal(connections=[]))

    with patch("src.schematic.llm_netlist_proposer._get_wrapper", return_value=wrapper):
        result = propose_netlist_llm(bom, [ds], ref_map, CONFIG, temperature=0.9)

    assert result.temperature == 0.9
    assert result.model_used == "weak_netlist_proposer"
    _, kwargs = wrapper.extract.call_args
    assert kwargs["temperature"] == 0.9
