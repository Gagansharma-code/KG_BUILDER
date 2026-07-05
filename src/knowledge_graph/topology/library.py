"""Formal topology library — LDO and Buck Converter.

Builds TOPOLOGY and FUNCTIONAL_BLOCK nodes (layer 4) plus PART_OF edges
carrying parameterized ScalingLaw data in edge constraints. All graph
writes go through the public GraphBackend interface — never through
networkx internals.

Node ID convention: "topology:<slug>" where <slug> matches the existing
informal topology vocabulary (goal_topology values, retrieval
topology_slugs, structural_verifier TOPOLOGY_TEMPLATES keys), so existing
string identifiers resolve to these nodes directly:

    graph.get_node(f"topology:{intent.goal_topology}")

Public API:
    install_topologies(graph) -> int      # nodes+edges created
    TOPOLOGY_SLUGS                        # slugs installed by this module
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.knowledge_graph.topology._schemas import SCALING_LAWS_KEY, ScalingLaw
from src.schemas.datasheet import ExtractionMethod
from src.schemas.kg import KGEdge, KGNode, KGNodeType, KGRelation

if TYPE_CHECKING:
    from src.knowledge_graph.backends import GraphBackend

logger = logging.getLogger(__name__)

# Layer assignment: topologies are reusable design knowledge — layer 4
# ("recipes" per the canonical KGNode docstring). See task summary for the
# documented layer-numbering collision and proposal.
_TOPOLOGY_LAYER = 4

TOPOLOGY_SLUGS = ("ldo", "buck_converter")

_SOURCE = "openforge:topology_library"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _topology_node(slug: str, label: str, description: str) -> KGNode:
    return KGNode(
        id=f"topology:{slug}",
        node_type=KGNodeType.TOPOLOGY,
        layer=_TOPOLOGY_LAYER,
        label=label,
        properties={"slug": slug, "description": description},
        source=_SOURCE,
        confidence=1.0,
        extraction_method=ExtractionMethod.MANUAL,
        created_at=_now(),
    )


def _block_node(topology_slug: str, block_slug: str, label: str, properties: dict) -> KGNode:
    return KGNode(
        id=f"functional_block:{topology_slug}:{block_slug}",
        node_type=KGNodeType.FUNCTIONAL_BLOCK,
        layer=_TOPOLOGY_LAYER,
        label=label,
        properties={"slug": block_slug, **properties},
        source=_SOURCE,
        confidence=1.0,
        extraction_method=ExtractionMethod.MANUAL,
        created_at=_now(),
    )


def _part_of_edge(
    block_id: str,
    topology_id: str,
    scaling_laws: list[ScalingLaw],
) -> KGEdge:
    constraints: dict = {}
    if scaling_laws:
        constraints[SCALING_LAWS_KEY] = [law.to_constraint_entry() for law in scaling_laws]
    return KGEdge(
        source_id=block_id,
        relation=KGRelation.PART_OF,
        target_id=topology_id,
        constraints=constraints,
        source_document=_SOURCE,
        confidence=1.0,
        layer=_TOPOLOGY_LAYER,
    )


# ── LDO ────────────────────────────────────────────────────────────────────
# Simple case — but uses the exact same schema pattern as the Buck Converter
# (blocks + PART_OF edges + scaling laws), no shortcuts.

_LDO_BLOCKS: list[tuple[str, str, dict, list[ScalingLaw]]] = [
    (
        "input_cap",
        "Input Capacitor",
        {"depends_on": ["supply_impedance_ohm", "transient_load_step_a"]},
        [
            ScalingLaw(
                parameter="transient_load_step_a",
                affects="capacitance_uf",
                direction="proportional",
                rationale="Larger load steps need more input charge storage to hold V_in",
            ),
        ],
    ),
    (
        "pass_element",
        "Pass Element",
        {"depends_on": ["dropout_voltage_v", "output_current_a"]},
        [
            ScalingLaw(
                parameter="output_current_a",
                affects="power_dissipation_w",
                direction="proportional",
                rationale="P_diss = (V_in - V_out) * I_out grows linearly with load current",
            ),
            ScalingLaw(
                parameter="dropout_voltage_v",
                affects="die_area_mm2",
                direction="inverse",
                rationale="Lower dropout requires a larger (lower R_dson) pass device",
            ),
        ],
    ),
    (
        "output_cap",
        "Output Capacitor",
        {"depends_on": ["load_transient_a", "esr_ohm"]},
        [
            ScalingLaw(
                parameter="esr_ohm",
                affects="loop_stability_margin_deg",
                direction="proportional",
                condition="ESR-zero-compensated LDO",
                rationale="Many LDOs rely on output cap ESR zero for phase margin",
            ),
        ],
    ),
    (
        "feedback",
        "Feedback Divider",
        {"depends_on": ["output_voltage_v", "reference_voltage_v"]},
        [
            ScalingLaw(
                parameter="divider_impedance_ohm",
                affects="output_noise_uvrms",
                direction="proportional",
                rationale="Higher divider impedance adds Johnson noise and error from FB bias current",
            ),
        ],
    ),
]

# ── Buck Converter ─────────────────────────────────────────────────────────

_BUCK_BLOCKS: list[tuple[str, str, dict, list[ScalingLaw]]] = [
    (
        "switching_loop",
        "Switching Loop",
        {"depends_on": ["switching_frequency_hz", "input_voltage_v"]},
        [
            ScalingLaw(
                parameter="switching_frequency_hz",
                affects="loop_area_mm2",
                direction="inverse",
                rationale="Higher f_sw allows smaller L/C, shrinking the hot loop area",
            ),
            ScalingLaw(
                parameter="switching_frequency_hz",
                affects="switching_loss_w",
                direction="proportional",
                rationale="Switching losses grow linearly with frequency",
            ),
        ],
    ),
    (
        "feedback_divider",
        "Feedback Divider",
        {"depends_on": ["output_voltage_v", "reference_voltage_v"]},
        [
            ScalingLaw(
                parameter="divider_impedance_ohm",
                affects="quiescent_current_ua",
                direction="inverse",
                rationale="Lower divider impedance burns more quiescent current",
            ),
        ],
    ),
    (
        "compensation_network",
        "Compensation Network",
        {"depends_on": ["output_cap_esr_ohm", "crossover_frequency_hz"]},
        [
            ScalingLaw(
                parameter="output_cap_esr_ohm",
                affects="component_count",
                direction="proportional",
                condition="voltage-mode control",
                rationale="High-ESR output caps introduce a zero that needs extra compensation parts",
            ),
            ScalingLaw(
                parameter="crossover_frequency_hz",
                affects="transient_response_us",
                direction="inverse",
                rationale="Higher loop crossover gives faster settling",
            ),
        ],
    ),
    (
        "bootstrap_circuit",
        "Bootstrap Circuit",
        {"depends_on": ["switching_frequency_hz", "gate_charge_nc"]},
        [
            ScalingLaw(
                parameter="gate_charge_nc",
                affects="bootstrap_capacitance_nf",
                direction="proportional",
                rationale="Bootstrap cap must supply high-side gate charge each cycle",
            ),
        ],
    ),
    (
        "output_filter",
        "Output Filter",
        {"depends_on": ["ripple_budget_mv", "switching_frequency_hz"]},
        [
            ScalingLaw(
                parameter="switching_frequency_hz",
                affects="inductance_uh",
                direction="inverse",
                rationale="L required for a given ripple current falls as 1/f_sw",
            ),
            ScalingLaw(
                parameter="ripple_budget_mv",
                affects="output_capacitance_uf",
                direction="inverse",
                rationale="Tighter ripple budget requires more output capacitance",
            ),
        ],
    ),
]

_TOPOLOGIES: dict[str, tuple[str, str, list[tuple[str, str, dict, list[ScalingLaw]]]]] = {
    "ldo": (
        "LDO Regulator",
        "Linear low-dropout voltage regulator topology",
        _LDO_BLOCKS,
    ),
    "buck_converter": (
        "Buck Converter",
        "Step-down switching regulator topology",
        _BUCK_BLOCKS,
    ),
}


def install_topologies(graph: GraphBackend) -> int:
    """Install the formal LDO and Buck Converter topologies into the graph.

    Idempotent: add_node upserts, and add_edge overwrites the single edge
    per (source, target) pair under NetworkX semantics.

    Args:
        graph: Any GraphBackend implementation.

    Returns:
        Total count of nodes + edges written.
    """
    written = 0
    for slug, (label, description, blocks) in _TOPOLOGIES.items():
        topo_node = _topology_node(slug, label, description)
        graph.add_node(topo_node)
        written += 1

        for block_slug, block_label, props, laws in blocks:
            block = _block_node(slug, block_slug, block_label, props)
            graph.add_node(block)
            written += 1
            graph.add_edge(_part_of_edge(block.id, topo_node.id, laws))
            written += 1

    logger.info(f"Installed {len(_TOPOLOGIES)} topologies ({written} nodes+edges)")
    return written


def link_component_implements(
    graph: GraphBackend,
    component_node_id: str,
    topology_slug: str,
    confidence: float = 1.0,
    source_document: str = _SOURCE,
) -> None:
    """Create an IMPLEMENTS edge: component realizes a topology.

    e.g. link_component_implements(graph, "component_instance:TPS5430",
    "buck_converter").

    Raises:
        NodeNotFoundError: If either node is absent from the graph.
    """
    graph.add_edge(
        KGEdge(
            source_id=component_node_id,
            relation=KGRelation.IMPLEMENTS,
            target_id=f"topology:{topology_slug}",
            constraints={},
            source_document=source_document,
            confidence=confidence,
            layer=_TOPOLOGY_LAYER,
        )
    )
