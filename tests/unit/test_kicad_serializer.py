"""Unit tests for src/output/kicad_serializer.py."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.config import Config
from src.output.kicad_serializer import (
    KiCadMCPError,
    KiCadOutput,
    _compute_initial_positions,
    serialize_to_kicad,
)
from src.schemas.nir import (
    BoardSpec,
    ComponentGroup,
    ComponentRef,
    NIR,
    NetlistEntry,
    PinRef,
    PlacementConstraint,
    RoutingHint,
)


class MockKiCadMCPClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def call(self, tool: str, params: dict) -> dict:
        self.calls.append((tool, params))
        if tool == "run_erc":
            return {"passed": True, "violations": []}
        if tool == "run_drc":
            return {"passed": True, "violations": []}
        return {}


def _board_spec() -> BoardSpec:
    return BoardSpec(
        layers=2,
        material="FR-4",
        thickness_mm=1.6,
        min_trace_width_mm=0.15,
        min_clearance_mm=0.15,
    )


def _sample_nir() -> NIR:
    now = datetime.now(timezone.utc).isoformat()
    return NIR(
        design_id="BUCK_001",
        prompt="Design a 3.3V buck regulator",
        design_methodology="buck_regulator_recipe_v1",
        components=[
            ComponentRef(
                ref="U1",
                component_id="TPS62933DRLR",
                component_type="ldo_regulator",
                footprint="SOT-23-5",
                datasheet_confidence=0.97,
                justification="Buck regulator IC",
            ),
            ComponentRef(
                ref="C1",
                component_id="GRM188R71H105KA12D",
                component_type="capacitor",
                footprint="0402",
                value="1uF",
                datasheet_confidence=0.95,
                justification="Input decoupling",
            ),
            ComponentRef(
                ref="R1",
                component_id="RC0402FR-0710KL",
                component_type="resistor",
                footprint="0402",
                value="10k",
                datasheet_confidence=0.95,
                justification="Feedback resistor",
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
                source_rule="power_entry_rule",
                net_confidence=0.95,
            ),
            NetlistEntry(
                net_name="GND",
                net_type="power",
                connections=[
                    PinRef(ref="U1", pin_name="GND", pin_number="2"),
                    PinRef(ref="C1", pin_name="P2", pin_number="2"),
                ],
                source_rule="ground_rule",
                net_confidence=0.98,
            ),
            NetlistEntry(
                net_name="FB",
                net_type="signal",
                connections=[
                    PinRef(ref="U1", pin_name="FB", pin_number="3"),
                    PinRef(ref="R1", pin_name="P1", pin_number="1"),
                    PinRef(ref="C1", pin_name="P1", pin_number="1"),
                ],
                source_rule="feedback_rule",
                net_confidence=0.9,
            ),
        ],
        placement_constraints=[
            PlacementConstraint(
                ref="C1",
                constraint_type="keepout",
                relative_to="U1",
                relative_to_type="component",
                min_distance_mm=2.0,
                hard=True,
                source="layout_rule",
                confidence=0.85,
            ),
        ],
        component_groups=[
            ComponentGroup(
                name="Power_Stage",
                refs=["U1", "C1"],
            ),
        ],
        routing_hints=[
            RoutingHint(
                nets=["FB"],
                hint_type="impedance_controlled",
                value=0.2,
                unit="mm",
                note="Feedback trace width",
            ),
        ],
        board_spec=_board_spec(),
        created_at=now,
    )


@pytest.fixture
def config() -> Config:
    return Config()


@pytest.fixture
def mock_client() -> MockKiCadMCPClient:
    return MockKiCadMCPClient()


@pytest.fixture
def sample_nir() -> NIR:
    return _sample_nir()


def _tool_names(calls: list[tuple[str, dict]]) -> list[str]:
    return [tool for tool, _ in calls]


def test_create_schematic_is_first_call(
    config: Config,
    mock_client: MockKiCadMCPClient,
    sample_nir: NIR,
    tmp_path: Path,
) -> None:
    serialize_to_kicad(sample_nir, tmp_path, config, mcp_client=mock_client)

    assert mock_client.calls[0][0] == "create_schematic"
    assert mock_client.calls[0][1] == {"name": "BUCK_001"}


def test_add_symbol_called_per_component(
    config: Config,
    mock_client: MockKiCadMCPClient,
    sample_nir: NIR,
    tmp_path: Path,
) -> None:
    serialize_to_kicad(sample_nir, tmp_path, config, mcp_client=mock_client)

    add_symbol_calls = [c for c in mock_client.calls if c[0] == "add_symbol"]
    assert len(add_symbol_calls) == len(sample_nir.components)
    refs = {call[1]["reference"] for call in add_symbol_calls}
    assert refs == {"U1", "C1", "R1"}


def test_add_power_symbol_called_for_power_nets(
    config: Config,
    mock_client: MockKiCadMCPClient,
    sample_nir: NIR,
    tmp_path: Path,
) -> None:
    serialize_to_kicad(sample_nir, tmp_path, config, mcp_client=mock_client)

    power_calls = [c for c in mock_client.calls if c[0] == "add_power_symbol"]
    power_net_names = {call[1]["net_name"] for call in power_calls}
    assert power_net_names == {"VCC", "GND"}


def test_add_wire_called_for_each_connection_pair(
    config: Config,
    mock_client: MockKiCadMCPClient,
    sample_nir: NIR,
    tmp_path: Path,
) -> None:
    serialize_to_kicad(sample_nir, tmp_path, config, mcp_client=mock_client)

    wire_calls = [c for c in mock_client.calls if c[0] == "add_wire"]
    expected_wires = sum(
        max(0, len(net.connections) - 1) for net in sample_nir.netlist
    )
    assert len(wire_calls) == expected_wires


def test_run_erc_called_before_create_pcb(
    config: Config,
    mock_client: MockKiCadMCPClient,
    sample_nir: NIR,
    tmp_path: Path,
) -> None:
    serialize_to_kicad(sample_nir, tmp_path, config, mcp_client=mock_client)

    tools = _tool_names(mock_client.calls)
    assert "run_erc" in tools
    assert "create_pcb" in tools
    assert tools.index("run_erc") < tools.index("create_pcb")


def test_run_drc_called_before_export_gerbers(
    config: Config,
    mock_client: MockKiCadMCPClient,
    sample_nir: NIR,
    tmp_path: Path,
) -> None:
    serialize_to_kicad(sample_nir, tmp_path, config, mcp_client=mock_client)

    tools = _tool_names(mock_client.calls)
    assert "run_drc" in tools
    assert "export_gerbers" in tools
    assert tools.index("run_drc") < tools.index("export_gerbers")


def test_save_all_called_last(
    config: Config,
    mock_client: MockKiCadMCPClient,
    sample_nir: NIR,
    tmp_path: Path,
) -> None:
    serialize_to_kicad(sample_nir, tmp_path, config, mcp_client=mock_client)

    assert mock_client.calls[-1][0] == "save_all"


def test_kicad_mcp_error_returns_failed_output(
    config: Config,
    sample_nir: NIR,
    tmp_path: Path,
) -> None:
    class FailingClient(MockKiCadMCPClient):
        def call(self, tool: str, params: dict) -> dict:
            if tool == "add_symbol":
                raise KiCadMCPError("MCP tool 'add_symbol' failed: symbol not found")
            return super().call(tool, params)

    output = serialize_to_kicad(
        sample_nir, tmp_path, config, mcp_client=FailingClient()
    )

    assert output.success is False
    assert output.error is not None
    assert "add_symbol" in output.error


def test_serialize_never_raises(
    config: Config,
    sample_nir: NIR,
    tmp_path: Path,
) -> None:
    class FailingClient(MockKiCadMCPClient):
        def call(self, tool: str, params: dict) -> dict:
            raise KiCadMCPError("server unavailable")

    output = serialize_to_kicad(
        sample_nir, tmp_path, config, mcp_client=FailingClient()
    )

    assert isinstance(output, KiCadOutput)
    assert output.success is False


def test_compute_initial_positions_covers_all_refs(sample_nir: NIR) -> None:
    positions = _compute_initial_positions(sample_nir)

    for component in sample_nir.components:
        assert component.ref in positions
        pos = positions[component.ref]
        assert "x" in pos
        assert "y" in pos
        assert pos["layer"] == "top"
        assert pos["rotation"] == 0


def test_successful_serialization_returns_paths(
    config: Config,
    mock_client: MockKiCadMCPClient,
    sample_nir: NIR,
    tmp_path: Path,
) -> None:
    output = serialize_to_kicad(
        sample_nir, tmp_path, config, mcp_client=mock_client
    )

    assert output.success is True
    assert output.erc_passed is True
    assert output.drc_passed is True
    assert output.schematic_path == tmp_path / "BUCK_001.kicad_sch"
    assert output.pcb_path == tmp_path / "BUCK_001.kicad_pcb"
    assert output.gerber_dir == tmp_path / "gerbers"
    assert output.bom_path == tmp_path / "bom.csv"
