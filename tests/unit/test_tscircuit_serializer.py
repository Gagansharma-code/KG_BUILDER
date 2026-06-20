"""Unit tests for src/output/tscircuit_serializer.py."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config import Config
from src.output.tscircuit_serializer import (
    TSCircuitOutput,
    _format_pin_ref,
    _format_power_net,
    _generate_connections,
    _generate_tsx,
    serialize_to_tscircuit,
)
from src.schemas.nir import (
    BoardSpec,
    ComponentRef,
    NIR,
    NetlistEntry,
    PinRef,
)


def _board_spec() -> BoardSpec:
    return BoardSpec(
        layers=2,
        material="FR-4",
        thickness_mm=1.6,
        min_trace_width_mm=0.15,
        min_clearance_mm=0.15,
    )


def _minimal_nir(**overrides: object) -> NIR:
    now = datetime.now(timezone.utc).isoformat()
    defaults = {
        "design_id": "TEST_DESIGN_001",
        "prompt": "Test buck regulator",
        "design_methodology": "buck_regulator_recipe_v1",
        "components": [],
        "netlist": [],
        "placement_constraints": [],
        "board_spec": _board_spec(),
        "created_at": now,
    }
    defaults.update(overrides)
    return NIR(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def config() -> Config:
    return Config()


def test_power_net_generates_global_syntax() -> None:
    nir = _minimal_nir(
        components=[
            ComponentRef(
                ref="U1",
                component_id="TPS62933DRLR",
                component_type="ldo_regulator",
                footprint="SOT-23-5",
                datasheet_confidence=0.9,
                justification="Regulator IC",
            ),
            ComponentRef(
                ref="C1",
                component_id="GRM188R71H105KA12D",
                component_type="capacitor",
                footprint="0402",
                value="1uF",
                datasheet_confidence=0.9,
                justification="Decoupling",
            ),
        ],
        netlist=[
            NetlistEntry(
                net_name="VCC",
                net_type="power",
                connections=[
                    PinRef(ref="U1", pin_name="VIN", pin_number="1"),
                    PinRef(ref="C1", pin_name="P1", pin_number="1"),
                ],
                source_rule="power_rule",
                net_confidence=0.95,
            ),
        ],
    )

    component_map = {"U1": "chip", "C1": "capacitor"}
    lines = _generate_connections(nir, component_map)

    assert len(lines) == 2
    assert 'circuit.connect("U1.pin1", ".VCC")' in lines
    assert 'circuit.connect("C1.pos", ".VCC")' in lines
    assert not any("C1.neg" in line for line in lines)


def test_signal_net_generates_pairwise_connections() -> None:
    nir = _minimal_nir(
        components=[
            ComponentRef(
                ref="R1",
                component_id="RC0402",
                component_type="resistor",
                footprint="0402",
                value="10k",
                datasheet_confidence=0.9,
                justification="Pull-up",
            ),
            ComponentRef(
                ref="R2",
                component_id="RC0402",
                component_type="resistor",
                footprint="0402",
                value="10k",
                datasheet_confidence=0.9,
                justification="Pull-up",
            ),
            ComponentRef(
                ref="U1",
                component_id="MCU",
                component_type="microcontroller",
                footprint="QFN-32",
                datasheet_confidence=0.9,
                justification="MCU",
            ),
        ],
        netlist=[
            NetlistEntry(
                net_name="I2C_SDA",
                net_type="signal",
                connections=[
                    PinRef(ref="R1", pin_name="P2", pin_number="2"),
                    PinRef(ref="R2", pin_name="P2", pin_number="2"),
                    PinRef(ref="U1", pin_name="SDA", pin_number="3"),
                ],
                source_rule="signal_rule",
                net_confidence=0.9,
            ),
        ],
    )

    component_map = {"R1": "resistor", "R2": "resistor", "U1": "chip"}
    lines = _generate_connections(nir, component_map)

    assert lines == [
        'circuit.connect("R1.pin2", "R2.pin2")',
        'circuit.connect("R2.pin2", "U1.pin3")',
    ]


def test_capacitor_pin_labels_use_pos_neg() -> None:
    pin1 = PinRef(ref="C1", pin_name="P1", pin_number="1")
    pin2 = PinRef(ref="C1", pin_name="P2", pin_number="2")

    assert _format_pin_ref("C1", pin1, "capacitor") == "C1.pos"
    assert _format_pin_ref("C1", pin2, "capacitor") == "C1.neg"


def test_chip_pin_label_fallback() -> None:
    pin = PinRef(ref="U1", pin_name="GPIO3", pin_number="3")
    assert _format_pin_ref("U1", pin, "chip") == "U1.pin3"


def test_resistor_value_prop_uses_resistance() -> None:
    nir = _minimal_nir(
        components=[
            ComponentRef(
                ref="R1",
                component_id="RC0402",
                component_type="resistor",
                footprint="0402",
                value="10k",
                datasheet_confidence=0.9,
                justification="Pull-up",
            ),
        ],
    )

    tsx_content, _, _ = _generate_tsx(nir)

    assert 'resistance="10k"' in tsx_content
    assert 'value="10k"' not in tsx_content


def test_unresolved_footprint_reported(config: Config, tmp_path: Path) -> None:
    nir = _minimal_nir(
        components=[
            ComponentRef(
                ref="U1",
                component_id="MYSTERY_PART",
                component_type="ldo_regulator",
                footprint="UNKNOWN_PKG",
                datasheet_confidence=0.9,
                justification="Unknown package",
            ),
        ],
    )

    with patch(
        "src.output.tscircuit_serializer._run_cli",
        return_value=(None, "cli unavailable"),
    ):
        output = serialize_to_tscircuit(nir, tmp_path, config)

    assert output.unresolved_footprints == ["U1 (UNKNOWN_PKG)"]


def test_unresolved_element_reported(config: Config, tmp_path: Path) -> None:
    nir = _minimal_nir(
        components=[
            ComponentRef(
                ref="X1",
                component_id="WEIRD_PART",
                component_type="unknown_thing",
                footprint="SOT-23-5",
                datasheet_confidence=0.9,
                justification="Unknown type",
            ),
        ],
    )

    with patch(
        "src.output.tscircuit_serializer._run_cli",
        return_value=(None, "cli unavailable"),
    ):
        output = serialize_to_tscircuit(nir, tmp_path, config)

    assert output.unresolved_elements == ["X1 (unknown_thing)"]


def test_serialize_never_raises_on_cli_failure(config: Config, tmp_path: Path) -> None:
    nir = _minimal_nir(
        components=[
            ComponentRef(
                ref="R1",
                component_id="RC0402",
                component_type="resistor",
                footprint="0402",
                value="10k",
                datasheet_confidence=0.9,
                justification="Pull-up",
            ),
        ],
    )

    with patch(
        "src.output.tscircuit_serializer._run_cli",
        return_value=(None, "tscircuit CLI not found"),
    ):
        output = serialize_to_tscircuit(nir, tmp_path, config)

    assert isinstance(output, TSCircuitOutput)
    assert output.cli_error == "tscircuit CLI not found"
    assert output.tsx_path is not None
    assert output.success is True


def test_wrong_nir_version_raises_value_error(config: Config, tmp_path: Path) -> None:
    nir = _minimal_nir(schema_version="0.9")

    with pytest.raises(ValueError, match="NIR schema version mismatch"):
        serialize_to_tscircuit(nir, tmp_path, config)


def test_check_version_called(config: Config, tmp_path: Path) -> None:
    nir = _minimal_nir()

    with (
        patch("src.output.tscircuit_serializer.check_version") as mock_check,
        patch(
            "src.output.tscircuit_serializer._run_cli",
            return_value=(None, None),
        ),
    ):
        serialize_to_tscircuit(nir, tmp_path, config)

    mock_check.assert_called_once_with(nir)


def test_tsx_written_to_design_id_path(config: Config, tmp_path: Path) -> None:
    nir = _minimal_nir(
        design_id="MY_DESIGN_42",
        components=[
            ComponentRef(
                ref="R1",
                component_id="RC0402",
                component_type="resistor",
                footprint="0402",
                value="10k",
                datasheet_confidence=0.9,
                justification="Pull-up",
            ),
        ],
    )

    with patch(
        "src.output.tscircuit_serializer._run_cli",
        return_value=(None, None),
    ):
        output = serialize_to_tscircuit(nir, tmp_path, config)

    expected_path = tmp_path / "MY_DESIGN_42.tsx"
    assert output.tsx_path == expected_path
    assert expected_path.exists()
    assert "MY_DESIGN_42" in expected_path.read_text(encoding="utf-8")


def test_format_power_net() -> None:
    assert _format_power_net("VCC") == ".VCC"
