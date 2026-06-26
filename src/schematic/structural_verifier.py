"""Structural verifier for schematic netlists (Layers 1-5).

Produces a continuous score in [0.0, 1.0] for the unified search controller.
Separate from src/schematic/erc.py — does not replace existing ERC.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import networkx as nx

from src.schemas.datasheet import ComponentDatasheet, PinRole
from src.schemas.intent import ValidatedBOM
from src.schemas.nir import NetlistEntry, PinRef
from src.schematic.erc import check_erc

logger = logging.getLogger(__name__)


class VerifierLayer(str, Enum):
    ELECTRICAL_INVARIANTS = "electrical_invariants"   # Layer 1
    PIN_ROLE_COMPATIBILITY = "pin_role_compatibility"  # Layer 2
    SUBCATEGORY_TEMPLATES = "subcategory_templates"   # Layer 3
    TOPOLOGY_SIGNATURES = "topology_signatures"     # Layer 4 — Prompt 3
    POWER_INVARIANTS = "power_invariants"        # Layer 5 — Prompt 3


@dataclass
class LayerViolation:
    layer: VerifierLayer
    severity: str              # "CRITICAL" | "WARNING"
    net_name: Optional[str]    # net where violation occurred, None if N/A
    ref: Optional[str]         # component ref, None if N/A
    pin_number: Optional[str]  # pin number, None if N/A
    message: str


@dataclass
class LayerResult:
    layer: VerifierLayer
    score: float           # 0.0 = all constraints failed, 1.0 = all passed
    constraints_checked: int
    constraints_passed: int
    violations: list[LayerViolation] = field(default_factory=list)
    skipped: bool = False    # True if layer could not run (missing data)
    skip_reason: Optional[str] = None


@dataclass
class VerificationResult:
    """Continuous scoring result from the structural verifier.

    score: float in [0.0, 1.0] — weighted mean of implemented layer scores.
           0.0 means all constraints failed. 1.0 means all constraints passed.
           Layers marked skipped=True contribute their weight at 0.5 (neutral).

    layer_results: per-layer breakdown for targeted error feedback.
                   The search controller uses this to decide which layer
                   to target in the next refinement prompt.

    critical_violations: flat list of CRITICAL severity violations across
                         all layers. Used by the SA polisher to identify
                         which connections to swap.
    """
    score: float
    layer_results: list[LayerResult]
    critical_violations: list[LayerViolation]
    total_constraints_checked: int
    total_constraints_passed: int

    def get_layer(self, layer: VerifierLayer) -> Optional[LayerResult]:
        for lr in self.layer_results:
            if lr.layer == layer:
                return lr
        return None

    def lowest_scoring_layer(self) -> Optional[LayerResult]:
        """Return the non-skipped layer with the lowest score."""
        candidates = [lr for lr in self.layer_results if not lr.skipped]
        if not candidates:
            return None
        return min(candidates, key=lambda lr: lr.score)


# Roles that actively drive a net (sources of signal or power)
_DRIVER_ROLES: frozenset[PinRole] = frozenset({
    PinRole.POWER_OUT,
    PinRole.SIGNAL_OUT,
    PinRole.ANALOG_OUT,
})

# Roles that are passive receivers (sinks)
_RECEIVER_ROLES: frozenset[PinRole] = frozenset({
    PinRole.POWER_IN,
    PinRole.SIGNAL_IN,
    PinRole.ANALOG_IN,
    PinRole.ENABLE,
    PinRole.ENABLE_N,
    PinRole.RESET,
    PinRole.CHIP_SELECT,
    PinRole.INTERRUPT,
    PinRole.FEEDBACK,
    PinRole.ADJUST,
})

# Roles that are bidirectional or shared
_SHARED_ROLES: frozenset[PinRole] = frozenset({
    PinRole.BIDIRECTIONAL,
    PinRole.GROUND,
    PinRole.REFERENCE,
    PinRole.SENSE_POS,
    PinRole.SENSE_NEG,
    PinRole.DIFFERENTIAL_POS,
    PinRole.DIFFERENTIAL_NEG,
    PinRole.CLOCK,
    PinRole.EXPOSED_PAD,
})

# Roles that must never appear on a connected net
_UNCONNECTABLE_ROLES: frozenset[PinRole] = frozenset({PinRole.NC})

# Maps component_type substring → set of PinRole that MUST appear in that
# component's connected pins. All roles in the set must be present.
_SUBCATEGORY_TEMPLATES: dict[str, frozenset[PinRole]] = {
    "op_amp": frozenset({PinRole.POWER_IN, PinRole.SIGNAL_OUT}),
    "opamp": frozenset({PinRole.POWER_IN, PinRole.SIGNAL_OUT}),
    "comparator": frozenset({PinRole.POWER_IN, PinRole.SIGNAL_OUT}),
    "ldo": frozenset({PinRole.POWER_IN, PinRole.GROUND, PinRole.POWER_OUT}),
    "ldo_regulator": frozenset({PinRole.POWER_IN, PinRole.GROUND, PinRole.POWER_OUT}),
    "buck": frozenset({PinRole.POWER_IN, PinRole.GROUND, PinRole.POWER_OUT}),
    "boost": frozenset({PinRole.POWER_IN, PinRole.GROUND, PinRole.POWER_OUT}),
    "adc": frozenset({PinRole.POWER_IN, PinRole.GROUND, PinRole.ANALOG_IN}),
    "dac": frozenset({PinRole.POWER_IN, PinRole.GROUND, PinRole.ANALOG_OUT}),
    "microcontroller": frozenset({PinRole.POWER_IN, PinRole.GROUND}),
    "mcu": frozenset({PinRole.POWER_IN, PinRole.GROUND}),
    "mosfet": frozenset({PinRole.ENABLE}),          # gate must be driven
    "gate_driver": frozenset({PinRole.POWER_IN, PinRole.SIGNAL_IN}),
    "current_source": frozenset({PinRole.POWER_IN, PinRole.GROUND}),
}


def _build_topology_templates() -> dict[str, nx.Graph]:
    """Build hardcoded topology template graphs.

    Returns a dict mapping topology_name → NetworkX Graph.
    These are the reference patterns the VF2 matcher checks the
    generated netlist against.
    """
    templates: dict[str, nx.Graph] = {}

    # ── LDO topology ─────────────────────────────────────────────────────────
    g = nx.Graph()
    g.add_node("src", keyword="")
    g.add_node("ldo", keyword="ldo")
    g.add_node("load", keyword="")
    g.add_node("gnd", keyword="")
    g.add_edge("src", "ldo", net_type="power")
    g.add_edge("ldo", "load", net_type="power")
    g.add_edge("ldo", "gnd", net_type="ground")
    g.add_edge("load", "gnd", net_type="ground")
    templates["ldo"] = g

    # ── Buck converter topology ───────────────────────────────────────────────
    g = nx.Graph()
    g.add_node("src", keyword="")
    g.add_node("buck", keyword="buck")
    g.add_node("ind", keyword="inductor")
    g.add_node("load", keyword="")
    g.add_node("gnd", keyword="")
    g.add_edge("src", "buck", net_type="power")
    g.add_edge("buck", "ind", net_type=None)
    g.add_edge("ind", "load", net_type="power")
    g.add_edge("load", "gnd", net_type="ground")
    g.add_edge("buck", "gnd", net_type="ground")
    templates["buck_converter"] = g

    # ── Op-amp inverting amplifier ────────────────────────────────────────────
    g = nx.Graph()
    g.add_node("amp", keyword="op_amp")
    g.add_node("r_in", keyword="resistor")
    g.add_node("r_fb", keyword="resistor")
    g.add_node("vcc", keyword="")
    g.add_node("gnd", keyword="")
    g.add_edge("amp", "r_in", net_type=None)
    g.add_edge("amp", "r_fb", net_type=None)
    g.add_edge("amp", "vcc", net_type="power")
    g.add_edge("amp", "gnd", net_type="ground")
    templates["inverting_amplifier"] = g

    # ── Voltage divider ───────────────────────────────────────────────────────
    g = nx.Graph()
    g.add_node("r_top", keyword="resistor")
    g.add_node("r_bot", keyword="resistor")
    g.add_node("vcc", keyword="")
    g.add_node("gnd", keyword="")
    g.add_edge("vcc", "r_top", net_type="power")
    g.add_edge("r_top", "r_bot", net_type=None)
    g.add_edge("r_bot", "gnd", net_type="ground")
    templates["voltage_divider"] = g

    # ── RC low-pass filter ────────────────────────────────────────────────────
    g = nx.Graph()
    g.add_node("r", keyword="resistor")
    g.add_node("c", keyword="capacitor")
    g.add_node("src", keyword="")
    g.add_node("gnd", keyword="")
    g.add_edge("src", "r", net_type=None)
    g.add_edge("r", "c", net_type=None)
    g.add_edge("c", "gnd", net_type="ground")
    templates["rc_lowpass"] = g

    # ── Current source (basic) ────────────────────────────────────────────────
    g = nx.Graph()
    g.add_node("amp", keyword="op_amp")
    g.add_node("r_set", keyword="resistor")
    g.add_node("vcc", keyword="")
    g.add_node("gnd", keyword="")
    g.add_edge("amp", "r_set", net_type=None)
    g.add_edge("amp", "vcc", net_type="power")
    g.add_edge("r_set", "gnd", net_type="ground")
    templates["current_source"] = g

    return templates


TOPOLOGY_TEMPLATES: dict[str, nx.Graph] = _build_topology_templates()

# Layer weights for weighted mean score computation.
_LAYER_WEIGHTS: dict[VerifierLayer, float] = {
    VerifierLayer.ELECTRICAL_INVARIANTS: 0.35,
    VerifierLayer.PIN_ROLE_COMPATIBILITY: 0.30,
    VerifierLayer.SUBCATEGORY_TEMPLATES: 0.20,
    VerifierLayer.TOPOLOGY_SIGNATURES: 0.10,  # Prompt 3
    VerifierLayer.POWER_INVARIANTS: 0.05,  # Prompt 3
}


def _build_pin_role_lookup(
    ref_map: dict[str, tuple[str, Optional[ComponentDatasheet]]],
) -> dict[tuple[str, str], Optional[PinRole]]:
    """Build lookup: (ref, pin_number) → PinRole | None.

    Returns PinRole if the pin has one set (from Prompt 1 normalizer).
    Returns None if the datasheet is missing or pin has no role.
    """
    lookup: dict[tuple[str, str], Optional[PinRole]] = {}
    for _component_id, (ref, datasheet) in ref_map.items():
        if datasheet is None:
            continue
        for pin in datasheet.pins:
            lookup[(ref, pin.pin_number)] = pin.pin_role
    return lookup


def _run_layer1(
    netlist: list[NetlistEntry],
    ref_map: dict[str, tuple[str, Optional[ComponentDatasheet]]],
) -> LayerResult:
    """Layer 1: Electrical invariants via existing ERC.

    Score = (rules_checked - critical_violations) / rules_checked
    Each CRITICAL violation reduces the score by 1/rules_checked.
    WARNING violations reduce by 0.5/rules_checked.
    """
    erc_result = check_erc(netlist, ref_map)

    rules_checked = max(erc_result.rules_checked, 1)
    critical_count = sum(
        1 for v in erc_result.violations if v.severity == "CRITICAL"
    )
    warning_count = sum(
        1 for v in erc_result.violations if v.severity == "WARNING"
    )

    penalty = critical_count * 1.0 + warning_count * 0.5
    raw_score = max(0.0, rules_checked - penalty) / rules_checked
    score = round(max(0.0, min(1.0, raw_score)), 4)

    violations = [
        LayerViolation(
            layer=VerifierLayer.ELECTRICAL_INVARIANTS,
            severity=v.severity,
            net_name=None,
            ref=v.affected_refs[0] if v.affected_refs else None,
            pin_number=None,
            message=v.message,
        )
        for v in erc_result.violations
    ]

    return LayerResult(
        layer=VerifierLayer.ELECTRICAL_INVARIANTS,
        score=score,
        constraints_checked=rules_checked,
        constraints_passed=rules_checked - critical_count,
        violations=violations,
    )


def _run_layer2(
    netlist: list[NetlistEntry],
    ref_map: dict[str, tuple[str, Optional[ComponentDatasheet]]],
) -> LayerResult:
    """Layer 2: Pin-role compatibility checking."""
    pin_role_lookup = _build_pin_role_lookup(ref_map)

    violations: list[LayerViolation] = []
    constraints_checked = 0
    constraints_passed = 0

    for net in netlist:
        if not net.connections:
            continue

        # Collect roles for all connected pins
        roles_on_net: list[tuple[PinRef, Optional[PinRole]]] = []
        for conn in net.connections:
            role = pin_role_lookup.get((conn.ref, conn.pin_number))
            roles_on_net.append((conn, role))

        known_roles = [r for _, r in roles_on_net if r is not None]

        # Rule 2.1 — driver conflict
        constraints_checked += 1
        driver_roles_present = [r for r in known_roles if r in _DRIVER_ROLES]
        driver_type_counts: dict[PinRole, int] = {}
        for r in driver_roles_present:
            driver_type_counts[r] = driver_type_counts.get(r, 0) + 1

        conflict_found = any(c > 1 for c in driver_type_counts.values())
        if conflict_found:
            for role, count in driver_type_counts.items():
                if count > 1:
                    violations.append(LayerViolation(
                        layer=VerifierLayer.PIN_ROLE_COMPATIBILITY,
                        severity="CRITICAL",
                        net_name=net.net_name,
                        ref=None,
                        pin_number=None,
                        message=(
                            f"Net '{net.net_name}' has {count} pins with role "
                            f"'{role.value}' — driver conflict (short circuit risk)"
                        ),
                    ))
        else:
            constraints_passed += 1

        # Rule 2.2 — NC pins must not be connected
        constraints_checked += 1
        nc_pins = [conn for conn, r in roles_on_net if r == PinRole.NC]
        if nc_pins and len(net.connections) > 1:
            for conn in nc_pins:
                violations.append(LayerViolation(
                    layer=VerifierLayer.PIN_ROLE_COMPATIBILITY,
                    severity="CRITICAL",
                    net_name=net.net_name,
                    ref=conn.ref,
                    pin_number=conn.pin_number,
                    message=(
                        f"NC pin {conn.ref}.{conn.pin_number} is connected on "
                        f"net '{net.net_name}' — NC pins must not be connected"
                    ),
                ))
        else:
            constraints_passed += 1

        # Rule 2.3 — power nets need a driver
        if net.net_type == "power":
            constraints_checked += 1
            power_drivers = {PinRole.POWER_OUT, PinRole.GROUND}
            has_driver = any(r in power_drivers for r in known_roles)
            if not has_driver and known_roles:
                violations.append(LayerViolation(
                    layer=VerifierLayer.PIN_ROLE_COMPATIBILITY,
                    severity="WARNING",
                    net_name=net.net_name,
                    ref=None,
                    pin_number=None,
                    message=(
                        f"Power net '{net.net_name}' has no POWER_OUT or GROUND "
                        f"driver pin — net may be undriven"
                    ),
                ))
            else:
                constraints_passed += 1

    if constraints_checked == 0:
        return LayerResult(
            layer=VerifierLayer.PIN_ROLE_COMPATIBILITY,
            score=1.0,
            constraints_checked=0,
            constraints_passed=0,
            skipped=True,
            skip_reason="No nets with connections found",
        )

    critical_count = sum(1 for v in violations if v.severity == "CRITICAL")
    warning_count = sum(1 for v in violations if v.severity == "WARNING")
    penalty = critical_count * 1.0 + warning_count * 0.5
    score = round(
        max(0.0, min(1.0, (constraints_checked - penalty) / constraints_checked)),
        4,
    )

    return LayerResult(
        layer=VerifierLayer.PIN_ROLE_COMPATIBILITY,
        score=score,
        constraints_checked=constraints_checked,
        constraints_passed=constraints_passed,
        violations=violations,
    )


def _run_layer3(
    netlist: list[NetlistEntry],
    ref_map: dict[str, tuple[str, Optional[ComponentDatasheet]]],
    bom: Optional[ValidatedBOM],
) -> LayerResult:
    """Layer 3: Subcategory template checks.

    Verifies that each component has its mandatory pin roles connected.
    Skipped if ValidatedBOM is not provided.
    """
    if bom is None:
        return LayerResult(
            layer=VerifierLayer.SUBCATEGORY_TEMPLATES,
            score=1.0,
            constraints_checked=0,
            constraints_passed=0,
            skipped=True,
            skip_reason="ValidatedBOM not provided — Layer 3 skipped",
        )

    # Build set of (ref, pin_number) pairs that are actually connected
    connected_pins: set[tuple[str, str]] = set()
    for net in netlist:
        for conn in net.connections:
            connected_pins.add((conn.ref, conn.pin_number))

    # Build ref → component_type mapping from BOM
    ref_to_type: dict[str, str] = {}
    for component in bom.components:
        ref_to_type[component.ref] = component.component_type.lower()

    violations: list[LayerViolation] = []
    constraints_checked = 0
    constraints_passed = 0

    for _component_id, (ref, datasheet) in ref_map.items():
        if datasheet is None:
            continue

        component_type = ref_to_type.get(ref, "").lower()
        if not component_type:
            continue

        # Find matching template(s) by substring
        required_roles: set[PinRole] = set()
        for keyword, roles in _SUBCATEGORY_TEMPLATES.items():
            if keyword in component_type:
                required_roles |= roles

        if not required_roles:
            continue  # no template applies to this component type

        # For each required role, check if a connected pin of this ref has it
        for required_role in required_roles:
            constraints_checked += 1

            # Find all pins of this component that have this role
            pins_with_role = [
                pin for pin in datasheet.pins
                if pin.pin_role == required_role
            ]

            # Check if at least one of them is connected
            is_connected = any(
                (ref, pin.pin_number) in connected_pins
                for pin in pins_with_role
            )

            if not pins_with_role:
                # No pin with this role exists — could be normalization miss
                violations.append(LayerViolation(
                    layer=VerifierLayer.SUBCATEGORY_TEMPLATES,
                    severity="WARNING",
                    net_name=None,
                    ref=ref,
                    pin_number=None,
                    message=(
                        f"{ref} ({component_type}): no pin with required role "
                        f"'{required_role.value}' found — normalization may have failed"
                    ),
                ))
            elif not is_connected:
                violations.append(LayerViolation(
                    layer=VerifierLayer.SUBCATEGORY_TEMPLATES,
                    severity="CRITICAL",
                    net_name=None,
                    ref=ref,
                    pin_number=None,
                    message=(
                        f"{ref} ({component_type}): required role "
                        f"'{required_role.value}' pin is not connected in the netlist"
                    ),
                ))
            else:
                constraints_passed += 1

    if constraints_checked == 0:
        return LayerResult(
            layer=VerifierLayer.SUBCATEGORY_TEMPLATES,
            score=1.0,
            constraints_checked=0,
            constraints_passed=0,
            skipped=True,
            skip_reason="No component types matched any template",
        )

    critical_count = sum(1 for v in violations if v.severity == "CRITICAL")
    warning_count = sum(1 for v in violations if v.severity == "WARNING")
    penalty = critical_count * 1.0 + warning_count * 0.5
    score = round(
        max(0.0, min(1.0, (constraints_checked - penalty) / constraints_checked)),
        4,
    )

    return LayerResult(
        layer=VerifierLayer.SUBCATEGORY_TEMPLATES,
        score=score,
        constraints_checked=constraints_checked,
        constraints_passed=constraints_passed,
        violations=violations,
    )


def _build_netlist_graph(
    netlist: list[NetlistEntry],
    bom: Optional[ValidatedBOM],
) -> nx.Graph:
    """Build a component-connectivity graph from the netlist.

    Nodes: component refs (e.g. "U1", "C1")
    Node attribute "keyword": component_type from BOM (lowercased), or ""
    Edges: two components share at least one net
    Edge attribute "net_types": set of net_type strings for all shared nets
    """
    g = nx.Graph()

    ref_to_type: dict[str, str] = {}
    if bom is not None:
        for component in bom.components:
            ref_to_type[component.ref] = component.component_type.lower()

    all_refs: set[str] = set()
    for net in netlist:
        for conn in net.connections:
            all_refs.add(conn.ref)

    for ref in all_refs:
        g.add_node(ref, keyword=ref_to_type.get(ref, ""))

    for net in netlist:
        refs_on_net = [conn.ref for conn in net.connections]
        net_type = net.net_type or "signal"

        for i in range(len(refs_on_net)):
            for j in range(i + 1, len(refs_on_net)):
                r1, r2 = refs_on_net[i], refs_on_net[j]
                if g.has_edge(r1, r2):
                    g[r1][r2]["net_types"].add(net_type)
                else:
                    g.add_edge(r1, r2, net_types={net_type})

    return g


def _node_match_fn(schematic_attrs: dict, template_attrs: dict) -> bool:
    """VF2 node matcher: checks keyword substring match."""
    keyword = template_attrs.get("keyword", "")
    if not keyword:
        return True
    comp_type = schematic_attrs.get("keyword", "")
    return keyword in comp_type


def _edge_match_fn(schematic_attrs: dict, template_attrs: dict) -> bool:
    """VF2 edge matcher: checks net_type compatibility."""
    required_type = template_attrs.get("net_type")
    if required_type is None:
        return True
    actual_types: set = schematic_attrs.get("net_types", set())
    if required_type == "ground":
        return "ground" in actual_types or "power" in actual_types
    return required_type in actual_types


def _get_primary_keyword(template: nx.Graph) -> str:
    """Return the first non-empty keyword in the template's nodes."""
    for _, attrs in template.nodes(data=True):
        kw = attrs.get("keyword", "")
        if kw:
            return kw
    return ""


def _run_layer4(
    netlist: list[NetlistEntry],
    ref_map: dict[str, tuple[str, Optional[ComponentDatasheet]]],
    bom: Optional[ValidatedBOM],
    expected_topologies: Optional[list[str]] = None,
) -> LayerResult:
    """Layer 4: Topology signature verification via VF2 subgraph isomorphism."""
    if bom is None and expected_topologies is None:
        return LayerResult(
            layer=VerifierLayer.TOPOLOGY_SIGNATURES,
            score=1.0,
            constraints_checked=0,
            constraints_passed=0,
            skipped=True,
            skip_reason="No BOM and no expected_topologies — Layer 4 skipped",
        )

    schematic_graph = _build_netlist_graph(netlist, bom)

    if expected_topologies is not None:
        templates_to_check = {
            name: TOPOLOGY_TEMPLATES[name]
            for name in expected_topologies
            if name in TOPOLOGY_TEMPLATES
        }
    else:
        bom_types = " ".join(
            c.component_type.lower() for c in bom.components
        ) if bom else ""
        templates_to_check = {
            name: tmpl
            for name, tmpl in TOPOLOGY_TEMPLATES.items()
            if _get_primary_keyword(tmpl) and _get_primary_keyword(tmpl) in bom_types
        }

    if not templates_to_check:
        return LayerResult(
            layer=VerifierLayer.TOPOLOGY_SIGNATURES,
            score=1.0,
            constraints_checked=0,
            constraints_passed=0,
            skipped=True,
            skip_reason="No matching topology templates for this BOM",
        )

    violations: list[LayerViolation] = []
    constraints_checked = 0
    constraints_passed = 0

    for topo_name, template in templates_to_check.items():
        constraints_checked += 1

        if schematic_graph.number_of_nodes() < template.number_of_nodes():
            violations.append(LayerViolation(
                layer=VerifierLayer.TOPOLOGY_SIGNATURES,
                severity="WARNING",
                net_name=None,
                ref=None,
                pin_number=None,
                message=(
                    f"Topology '{topo_name}': schematic has fewer components "
                    f"({schematic_graph.number_of_nodes()}) than template requires "
                    f"({template.number_of_nodes()}) — cannot match"
                ),
            ))
            continue

        try:
            gm = nx.algorithms.isomorphism.GraphMatcher(
                schematic_graph,
                template,
                node_match=_node_match_fn,
                edge_match=_edge_match_fn,
            )
            if gm.subgraph_is_isomorphic():
                constraints_passed += 1
            else:
                violations.append(LayerViolation(
                    layer=VerifierLayer.TOPOLOGY_SIGNATURES,
                    severity="CRITICAL",
                    net_name=None,
                    ref=None,
                    pin_number=None,
                    message=(
                        f"Topology '{topo_name}' not found in generated schematic — "
                        f"expected circuit pattern is missing or malformed"
                    ),
                ))
        except Exception as exc:
            logger.warning("VF2 match failed for topology '%s': %s", topo_name, exc)
            constraints_checked -= 1

    if constraints_checked == 0:
        return LayerResult(
            layer=VerifierLayer.TOPOLOGY_SIGNATURES,
            score=1.0,
            constraints_checked=0,
            constraints_passed=0,
            skipped=True,
            skip_reason="All topology checks were skipped",
        )

    critical_count = sum(1 for v in violations if v.severity == "CRITICAL")
    warning_count = sum(1 for v in violations if v.severity == "WARNING")
    penalty = critical_count * 1.0 + warning_count * 0.5
    score = round(
        max(0.0, min(1.0, (constraints_checked - penalty) / constraints_checked)),
        4,
    )

    return LayerResult(
        layer=VerifierLayer.TOPOLOGY_SIGNATURES,
        score=score,
        constraints_checked=constraints_checked,
        constraints_passed=constraints_passed,
        violations=violations,
    )


_ANALOG_KEYWORDS: frozenset[str] = frozenset({
    "op_amp", "opamp", "adc", "dac", "comparator",
    "instrumentation", "current_source",
})

_DIGITAL_KEYWORDS: frozenset[str] = frozenset({
    "mcu", "microcontroller", "fpga", "processor",
    "digital", "logic",
})


def _run_layer5(
    netlist: list[NetlistEntry],
    ref_map: dict[str, tuple[str, Optional[ComponentDatasheet]]],
    bom: Optional[ValidatedBOM],
) -> LayerResult:
    """Layer 5: Power invariant checks."""
    pin_role_lookup = _build_pin_role_lookup(ref_map)

    ref_nets: dict[str, set[str]] = {}
    net_roles: dict[str, list[tuple[str, Optional[PinRole]]]] = {}

    for net in netlist:
        for conn in net.connections:
            ref_nets.setdefault(conn.ref, set()).add(net.net_name)
            role = pin_role_lookup.get((conn.ref, conn.pin_number))
            net_roles.setdefault(net.net_name, []).append((conn.ref, role))

    violations: list[LayerViolation] = []
    constraints_checked = 0
    constraints_passed = 0

    # Check 5.1: Star ground
    constraints_checked += 1
    ground_nets: set[str] = set()
    for net_name, role_list in net_roles.items():
        if any(role == PinRole.GROUND for _, role in role_list):
            ground_nets.add(net_name)

    if len(ground_nets) > 3:
        violations.append(LayerViolation(
            layer=VerifierLayer.POWER_INVARIANTS,
            severity="WARNING",
            net_name=None,
            ref=None,
            pin_number=None,
            message=(
                f"Found {len(ground_nets)} separate ground nets "
                f"({', '.join(sorted(ground_nets)[:5])}"
                f"{'...' if len(ground_nets) > 5 else ''}) "
                f"— verify star-ground topology is intentional"
            ),
        ))
    else:
        constraints_passed += 1

    # Check 5.2: Kelvin sensing separation
    for _component_id, (ref, datasheet) in ref_map.items():
        if datasheet is None:
            continue

        sense_pos_pins = [
            p for p in datasheet.pins if p.pin_role == PinRole.SENSE_POS
        ]
        sense_neg_pins = [
            p for p in datasheet.pins if p.pin_role == PinRole.SENSE_NEG
        ]

        if not sense_pos_pins and not sense_neg_pins:
            continue

        constraints_checked += 1

        sense_nets: set[str] = set()
        for net_name, role_list in net_roles.items():
            for r, role in role_list:
                if r == ref and role in (PinRole.SENSE_POS, PinRole.SENSE_NEG):
                    sense_nets.add(net_name)

        power_out_nets: set[str] = set()
        for net_name, role_list in net_roles.items():
            for r, role in role_list:
                if r == ref and role == PinRole.POWER_OUT:
                    power_out_nets.add(net_name)

        shared = sense_nets & power_out_nets
        if shared:
            violations.append(LayerViolation(
                layer=VerifierLayer.POWER_INVARIANTS,
                severity="CRITICAL",
                net_name=next(iter(shared)),
                ref=ref,
                pin_number=None,
                message=(
                    f"{ref}: SENSE pin is on the same net as POWER_OUT pin "
                    f"({', '.join(shared)}) — Kelvin sensing is shorted out"
                ),
            ))
        else:
            constraints_passed += 1

    # Check 5.3: Analog/digital ground separation
    if bom is not None:
        analog_refs: set[str] = set()
        digital_refs: set[str] = set()
        for component in bom.components:
            ctype = component.component_type.lower()
            if any(kw in ctype for kw in _ANALOG_KEYWORDS):
                analog_refs.add(component.ref)
            if any(kw in ctype for kw in _DIGITAL_KEYWORDS):
                digital_refs.add(component.ref)

        if analog_refs and digital_refs:
            constraints_checked += 1

            analog_gnd_nets: set[str] = set()
            digital_gnd_nets: set[str] = set()

            for net_name, role_list in net_roles.items():
                for r, role in role_list:
                    if role == PinRole.GROUND:
                        if r in analog_refs:
                            analog_gnd_nets.add(net_name)
                        if r in digital_refs:
                            digital_gnd_nets.add(net_name)

            shared_gnd = analog_gnd_nets & digital_gnd_nets
            if shared_gnd:
                violations.append(LayerViolation(
                    layer=VerifierLayer.POWER_INVARIANTS,
                    severity="WARNING",
                    net_name=next(iter(shared_gnd)),
                    ref=None,
                    pin_number=None,
                    message=(
                        f"Analog and digital components share ground net(s) "
                        f"({', '.join(sorted(shared_gnd))}) — consider separate "
                        f"AGND/DGND planes for precision designs"
                    ),
                ))
            else:
                constraints_passed += 1

    if constraints_checked == 0:
        return LayerResult(
            layer=VerifierLayer.POWER_INVARIANTS,
            score=1.0,
            constraints_checked=0,
            constraints_passed=0,
            skipped=True,
            skip_reason="No power invariant checks applicable to this design",
        )

    critical_count = sum(1 for v in violations if v.severity == "CRITICAL")
    warning_count = sum(1 for v in violations if v.severity == "WARNING")
    penalty = critical_count * 1.0 + warning_count * 0.5
    score = round(
        max(0.0, min(1.0, (constraints_checked - penalty) / constraints_checked)),
        4,
    )

    return LayerResult(
        layer=VerifierLayer.POWER_INVARIANTS,
        score=score,
        constraints_checked=constraints_checked,
        constraints_passed=constraints_passed,
        violations=violations,
    )


def verify_schematic(
    netlist: list[NetlistEntry],
    ref_map: dict[str, tuple[str, Optional[ComponentDatasheet]]],
    bom: Optional[ValidatedBOM] = None,
    expected_topologies: Optional[list[str]] = None,
) -> VerificationResult:
    """Run the structural verifier on a schematic netlist.

    Args:
        netlist:  List of NetlistEntry objects from the schematic synthesizer.
        ref_map:  Maps component_id → (ref, ComponentDatasheet | None).
                  Datasheets must have pin_role populated (requires Prompt 1
                  pin normalizer to have run).
        bom:      Optional ValidatedBOM. Required for Layer 3 subcategory checks.
                  If None, Layer 3 is skipped.
        expected_topologies: Optional list of topology names from TOPOLOGY_TEMPLATES
            to check in Layer 4. If None, templates are auto-detected from BOM.

    Returns:
        VerificationResult with continuous score in [0.0, 1.0] and per-layer
        breakdown. Never raises — skips layers gracefully on missing data.
    """
    layer_results: list[LayerResult] = []

    # Layer 1 — Electrical Invariants
    try:
        layer_results.append(_run_layer1(netlist, ref_map))
    except Exception as exc:
        logger.error("Layer 1 (electrical invariants) failed: %s", exc)
        layer_results.append(LayerResult(
            layer=VerifierLayer.ELECTRICAL_INVARIANTS,
            score=0.5, constraints_checked=0, constraints_passed=0,
            skipped=True, skip_reason=str(exc),
        ))

    # Layer 2 — Pin-Role Compatibility
    try:
        layer_results.append(_run_layer2(netlist, ref_map))
    except Exception as exc:
        logger.error("Layer 2 (pin-role compatibility) failed: %s", exc)
        layer_results.append(LayerResult(
            layer=VerifierLayer.PIN_ROLE_COMPATIBILITY,
            score=0.5, constraints_checked=0, constraints_passed=0,
            skipped=True, skip_reason=str(exc),
        ))

    # Layer 3 — Subcategory Templates
    try:
        layer_results.append(_run_layer3(netlist, ref_map, bom))
    except Exception as exc:
        logger.error("Layer 3 (subcategory templates) failed: %s", exc)
        layer_results.append(LayerResult(
            layer=VerifierLayer.SUBCATEGORY_TEMPLATES,
            score=0.5, constraints_checked=0, constraints_passed=0,
            skipped=True, skip_reason=str(exc),
        ))

    # Layer 4 — Topology Signatures
    try:
        layer_results.append(_run_layer4(netlist, ref_map, bom, expected_topologies))
    except Exception as exc:
        logger.error("Layer 4 (topology signatures) failed: %s", exc)
        layer_results.append(LayerResult(
            layer=VerifierLayer.TOPOLOGY_SIGNATURES,
            score=0.5, constraints_checked=0, constraints_passed=0,
            skipped=True, skip_reason=str(exc),
        ))

    # Layer 5 — Power Invariants
    try:
        layer_results.append(_run_layer5(netlist, ref_map, bom))
    except Exception as exc:
        logger.error("Layer 5 (power invariants) failed: %s", exc)
        layer_results.append(LayerResult(
            layer=VerifierLayer.POWER_INVARIANTS,
            score=0.5, constraints_checked=0, constraints_passed=0,
            skipped=True, skip_reason=str(exc),
        ))

    # Compute weighted mean score across all implemented layers
    implemented_layers = {
        VerifierLayer.ELECTRICAL_INVARIANTS,
        VerifierLayer.PIN_ROLE_COMPATIBILITY,
        VerifierLayer.SUBCATEGORY_TEMPLATES,
        VerifierLayer.TOPOLOGY_SIGNATURES,
        VerifierLayer.POWER_INVARIANTS,
    }
    total_weight = sum(
        _LAYER_WEIGHTS[lr.layer]
        for lr in layer_results
        if lr.layer in implemented_layers
    )
    if total_weight == 0:
        weighted_score = 0.5
    else:
        weighted_score = sum(
            lr.score * _LAYER_WEIGHTS[lr.layer]
            for lr in layer_results
            if lr.layer in implemented_layers
        ) / total_weight

    # Collect all critical violations
    critical_violations = [
        v
        for lr in layer_results
        for v in lr.violations
        if v.severity == "CRITICAL"
    ]

    total_checked = sum(lr.constraints_checked for lr in layer_results)
    total_passed = sum(lr.constraints_passed for lr in layer_results)

    return VerificationResult(
        score=round(max(0.0, min(1.0, weighted_score)), 4),
        layer_results=layer_results,
        critical_violations=critical_violations,
        total_constraints_checked=total_checked,
        total_constraints_passed=total_passed,
    )
