#!/usr/bin/env python3
"""Team E Gate - Output pipeline validation checks."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

results: list[tuple[int, str, bool, str]] = []


def check(num: int, name: str, passed: bool, error: str = "") -> None:
    results.append((num, name, passed, error))
    status = "PASS" if passed else "FAIL"
    print(f"CHECK {num} — {name}: {status}")
    if error:
        print(f"  Error: {error}")


print("=" * 60)
print("TEAM E GATE - Output Pipeline")
print("=" * 60)

from src.config import Config

config = Config()

# CHECK 1 — All Team E modules import without error
print("\n" + "-" * 60)
try:
    from src.output.tscircuit_serializer import serialize_to_tscircuit, TSCircuitOutput
    from src.output.tscircuit_footprint_map import resolve_footprint
    from src.output.tscircuit_element_map import get_element_type, get_pin_label
    from src.output.kicad_serializer import (
        serialize_to_kicad,
        KiCadOutput,
        MockKiCadMCPClient,
    )
    from src.output.kicad_symbol_map import resolve_kicad_symbol
    from src.output.kicad_footprint_map import resolve_kicad_footprint
    from src.output.doc_generator import generate_design_report
    from src.output import run_output_pipeline, OutputResult

    check(1, "All Team E modules import without error", True)
except Exception as e:
    check(1, "All Team E modules import without error", False, f"{type(e).__name__}: {e}")

# CHECK 2 — Power net uses global syntax
print("\n" + "-" * 60)
try:
    from src.output.tscircuit_serializer import _generate_tsx
    from src.schemas.nir import BoardSpec, ComponentRef, NIR, NetlistEntry, PinRef

    now = datetime.now(timezone.utc).isoformat()
    nir = NIR(
        design_id="GATE_POWER_NET",
        prompt="power net gate test",
        design_methodology="test_recipe_v1",
        components=[
            ComponentRef(
                ref="U1",
                component_id="TEST_IC",
                component_type="ldo_regulator",
                footprint="SOT-23-5",
                datasheet_confidence=0.9,
                justification="test IC",
            ),
        ],
        netlist=[
            NetlistEntry(
                net_name="VCC",
                net_type="power",
                connections=[PinRef(ref="U1", pin_name="VIN", pin_number="1")],
                source_rule="power_rule",
                net_confidence=0.95,
            ),
        ],
        placement_constraints=[],
        board_spec=BoardSpec(
            layers=2,
            material="FR-4",
            thickness_mm=1.6,
            min_trace_width_mm=0.15,
            min_clearance_mm=0.15,
        ),
        created_at=now,
    )

    tsx_content, _, _ = _generate_tsx(nir)
    errors = []
    if 'circuit.connect("U1.pin1", ".VCC")' not in tsx_content:
        errors.append('missing circuit.connect("U1.pin1", ".VCC")')
    if 'circuit.connect("U1.pin1", "U1.pin1")' in tsx_content:
        errors.append('found invalid self-connect circuit.connect("U1.pin1", "U1.pin1")')

    if errors:
        check(2, "Power net uses global syntax", False, "; ".join(errors))
    else:
        check(2, "Power net uses global syntax", True)
except Exception as e:
    check(2, "Power net uses global syntax", False, f"{type(e).__name__}: {e}")

# CHECK 3 — Capacitor pins use pos/neg not pin1/pin2
print("\n" + "-" * 60)
try:
    from src.output.tscircuit_element_map import get_pin_label

    errors = []
    if get_pin_label("capacitor", "1") != "pos":
        errors.append('get_pin_label("capacitor", "1") != "pos"')
    if get_pin_label("capacitor", "2") != "neg":
        errors.append('get_pin_label("capacitor", "2") != "neg"')

    if errors:
        check(3, "Capacitor pins use pos/neg not pin1/pin2", False, "; ".join(errors))
    else:
        check(3, "Capacitor pins use pos/neg not pin1/pin2", True)
except Exception as e:
    check(3, "Capacitor pins use pos/neg not pin1/pin2", False, f"{type(e).__name__}: {e}")

# CHECK 4 — Footprint resolution for passive types
print("\n" + "-" * 60)
try:
    from src.output.tscircuit_footprint_map import resolve_footprint

    errors = []
    result, needs_review = resolve_footprint("0402", "resistor")
    if result != "R_0402_1005Metric":
        errors.append(f'resistor 0402 result={result!r}')
    if needs_review:
        errors.append("resistor 0402 needs_review is True")

    result, needs_review = resolve_footprint("0402", "capacitor")
    if result != "C_0402_1005Metric":
        errors.append(f'capacitor 0402 result={result!r}')
    if needs_review:
        errors.append("capacitor 0402 needs_review is True")

    if errors:
        check(4, "Footprint resolution for passive types", False, "; ".join(errors))
    else:
        check(4, "Footprint resolution for passive types", True)
except Exception as e:
    check(4, "Footprint resolution for passive types", False, f"{type(e).__name__}: {e}")

# CHECK 5 — Unknown footprint sets needs_review=True
print("\n" + "-" * 60)
try:
    from src.output.tscircuit_footprint_map import resolve_footprint

    result, needs_review = resolve_footprint("UNKNOWN_XYZ", "chip")
    if needs_review is not True:
        check(
            5,
            "Unknown footprint sets needs_review=True",
            False,
            f"needs_review={needs_review!r}, result={result!r}",
        )
    else:
        check(5, "Unknown footprint sets needs_review=True", True)
except Exception as e:
    check(5, "Unknown footprint sets needs_review=True", False, f"{type(e).__name__}: {e}")

# CHECK 6 — KiCad call sequence is correct
print("\n" + "-" * 60)
try:
    from src.output.kicad_serializer import MockKiCadMCPClient, serialize_to_kicad
    from src.schemas.nir import BoardSpec, ComponentRef, NIR, NetlistEntry, PinRef

    now = datetime.now(timezone.utc).isoformat()
    nir = NIR(
        design_id="GATE_KICAD_SEQ",
        prompt="kicad sequence gate test",
        design_methodology="test_recipe_v1",
        components=[
            ComponentRef(
                ref="U1",
                component_id="IC1",
                component_type="ldo_regulator",
                footprint="SOT-23-5",
                datasheet_confidence=0.9,
                justification="test",
            ),
            ComponentRef(
                ref="C1",
                component_id="CAP1",
                component_type="capacitor",
                footprint="0402",
                value="1uF",
                datasheet_confidence=0.9,
                justification="test",
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
                net_confidence=0.9,
            ),
        ],
        placement_constraints=[],
        board_spec=BoardSpec(
            layers=2,
            material="FR-4",
            thickness_mm=1.6,
            min_trace_width_mm=0.15,
            min_clearance_mm=0.15,
        ),
        created_at=now,
    )

    mock_client = MockKiCadMCPClient()
    with tempfile.TemporaryDirectory() as tmp:
        serialize_to_kicad(nir, Path(tmp), config, mock_client)
        tool_names = [call[0] for call in mock_client.calls]

    errors = []
    if not tool_names:
        errors.append("no MCP calls recorded")
    elif tool_names[0] != "create_schematic":
        errors.append(f"first call={tool_names[0]!r}")
    if "run_erc" not in tool_names:
        errors.append("run_erc missing")
    if "run_drc" not in tool_names:
        errors.append("run_drc missing")
    if tool_names and tool_names[-1] != "save_all":
        errors.append(f"last call={tool_names[-1]!r}")
    if "run_erc" in tool_names and "create_pcb" in tool_names:
        if tool_names.index("run_erc") > tool_names.index("create_pcb"):
            errors.append("run_erc after create_pcb")

    if errors:
        check(6, "KiCad call sequence is correct", False, "; ".join(errors))
    else:
        check(6, "KiCad call sequence is correct", True)
except Exception as e:
    check(6, "KiCad call sequence is correct", False, f"{type(e).__name__}: {e}")

# CHECK 7 — run_output_pipeline never raises
print("\n" + "-" * 60)
try:
    from src.output import OutputResult, run_output_pipeline
    from src.output.kicad_serializer import MockKiCadMCPClient
    from src.schemas.nir import BoardSpec, ComponentRef, NIR

    now = datetime.now(timezone.utc).isoformat()
    nir = NIR(
        design_id="GATE_PIPELINE",
        prompt="pipeline gate test",
        design_methodology="test_recipe_v1",
        components=[
            ComponentRef(
                ref="R1",
                component_id="RC0402",
                component_type="resistor",
                footprint="0402",
                value="10k",
                datasheet_confidence=0.9,
                justification="test",
            ),
        ],
        netlist=[],
        placement_constraints=[],
        board_spec=BoardSpec(
            layers=2,
            material="FR-4",
            thickness_mm=1.6,
            min_trace_width_mm=0.15,
            min_clearance_mm=0.15,
        ),
        created_at=now,
    )

    with tempfile.TemporaryDirectory() as tmp:
        result = run_output_pipeline(
            nir, Path(tmp), config, MockKiCadMCPClient()
        )

    if isinstance(result, OutputResult):
        check(7, "run_output_pipeline never raises", True)
    else:
        check(
            7,
            "run_output_pipeline never raises",
            False,
            f"expected OutputResult, got {type(result).__name__}",
        )
except Exception as e:
    check(7, "run_output_pipeline never raises", False, f"{type(e).__name__}: {e}")

# CHECK 8 — NIR version mismatch raises before any serializer runs
print("\n" + "-" * 60)
try:
    from src.output.tscircuit_serializer import serialize_to_tscircuit
    from src.schemas.nir import BoardSpec, ComponentRef, NIR

    now = datetime.now(timezone.utc).isoformat()
    nir = NIR(
        design_id="GATE_VERSION",
        prompt="version gate test",
        design_methodology="test_recipe_v1",
        components=[
            ComponentRef(
                ref="R1",
                component_id="RC0402",
                component_type="resistor",
                footprint="0402",
                value="10k",
                datasheet_confidence=0.9,
                justification="test",
            ),
        ],
        netlist=[],
        placement_constraints=[],
        board_spec=BoardSpec(
            layers=2,
            material="FR-4",
            thickness_mm=1.6,
            min_trace_width_mm=0.15,
            min_clearance_mm=0.15,
        ),
        created_at=now,
        schema_version="99.0",
    )

    with tempfile.TemporaryDirectory() as tmp:
        try:
            serialize_to_tscircuit(nir, Path(tmp), config)
            check(
                8,
                "NIR version mismatch raises before any serializer runs",
                False,
                "expected ValueError, no exception raised",
            )
        except ValueError as exc:
            if "schema version" in str(exc).lower():
                check(8, "NIR version mismatch raises before any serializer runs", True)
            else:
                check(
                    8,
                    "NIR version mismatch raises before any serializer runs",
                    False,
                    f"ValueError without schema version message: {exc}",
                )
except Exception as e:
    check(
        8,
        "NIR version mismatch raises before any serializer runs",
        False,
        f"{type(e).__name__}: {e}",
    )

# CHECK 9 — doc generator produces a file
print("\n" + "-" * 60)
try:
    from src.output.doc_generator import generate_design_report
    from src.schemas.nir import BoardSpec, ComponentRef, NIR

    now = datetime.now(timezone.utc).isoformat()
    nir = NIR(
        design_id="GATE_REPORT",
        prompt="report gate test",
        design_methodology="test_recipe_v1",
        components=[
            ComponentRef(
                ref="R1",
                component_id="RC0402",
                component_type="resistor",
                footprint="0402",
                value="10k",
                datasheet_confidence=0.9,
                justification="test",
            ),
        ],
        netlist=[],
        placement_constraints=[],
        board_spec=BoardSpec(
            layers=2,
            material="FR-4",
            thickness_mm=1.6,
            min_trace_width_mm=0.15,
            min_clearance_mm=0.15,
        ),
        created_at=now,
    )

    with tempfile.TemporaryDirectory() as tmp:
        path = generate_design_report(nir, Path(tmp), config)

        errors = []
        if path is None:
            errors.append("path is None")
        elif not path.exists():
            errors.append(f"path does not exist: {path}")

    if errors:
        check(9, "doc generator produces a file", False, "; ".join(errors))
    else:
        check(9, "doc generator produces a file", True)
except Exception as e:
    check(9, "doc generator produces a file", False, f"{type(e).__name__}: {e}")

# CHECK 10 — mypy on src/output/
print("\n" + "-" * 60)
try:
    mypy_result = subprocess.run(
        ["mypy", "src/output/", "--ignore-missing-imports"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    output = (mypy_result.stdout + mypy_result.stderr).strip()
    error_lines = [
        line for line in output.split("\n") if line.strip() and "error:" in line.lower()
    ]

    if mypy_result.returncode != 0 or error_lines:
        for line in error_lines:
            print(f"  {line}")
        check(
            10,
            "mypy on src/output/",
            False,
            "\n  ".join([""] + error_lines[:25]),
        )
    else:
        check(10, "mypy on src/output/", True)
except Exception as e:
    check(10, "mypy on src/output/", False, f"{type(e).__name__}: {e}")

print("\n" + "=" * 60)
passed = sum(1 for _, _, p, _ in results if p)
total = len(results)

if passed == total:
    print(f"Team E: PASS ({passed}/{total} checks passed)")
else:
    print(f"Team E: FAIL ({passed}/{total} checks passed)")
    print("\nFailed checks:")
    for num, name, p, error in results:
        if not p:
            print(f"  CHECK {num} — {name}")
            if error:
                print(f"    {error}")

print("=" * 60)
sys.exit(0 if passed == total else 1)
