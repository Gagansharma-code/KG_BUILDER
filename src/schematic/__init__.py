"""Schematic synthesis — netlist generation from BOM and datasheets."""

from __future__ import annotations

import logging
from typing import Optional

from src.config import Config
from src.schemas.datasheet import ComponentDatasheet
from src.schemas.intent import ValidatedBOM
from src.schemas.kg import DesignSubgraph
from src.schemas.nir import NetlistEntry, PinRef, ReviewFlag

from src.schematic._ref_mapper import build_ref_map
from src.schematic._schemas import ERCResult, ERCViolation, SchematicGraph
from src.schematic.block_classifier import classify_blocks
from src.schematic.erc import check_erc
from src.schematic.net_assigner import assign_power_nets, assign_protocol_nets
from src.schematic.passive_assigner import assign_passives

logger = logging.getLogger(__name__)

__all__ = ["synthesize_schematic"]


def _empty_erc_result() -> ERCResult:
    return ERCResult(passed=True, violations=[], rules_checked=0)


def _build_review_flags(
    unresolved_pins: list[PinRef],
    erc_result: ERCResult,
) -> list[ReviewFlag]:
    flags: list[ReviewFlag] = []

    for pin in unresolved_pins:
        is_power = pin.pin_name in ("POWER_POSITIVE", "POWER_GROUND", "POWER_INPUT", "UNKNOWN")
        flags.append(
            ReviewFlag(
                item_ref=f"{pin.ref}.{pin.pin_number}",
                reason=f"Unresolved pin {pin.pin_name} on {pin.ref}",
                severity="CRITICAL" if is_power else "WARNING",
                stage="schematic_synthesis",
            )
        )

    for violation in erc_result.violations:
        if violation.severity == "CRITICAL":
            flags.append(
                ReviewFlag(
                    item_ref=",".join(violation.affected_refs) or violation.rule_name,
                    reason=violation.message,
                    severity="CRITICAL",
                    stage="schematic_synthesis",
                )
            )

    return flags


def _package_schematic_graph(
    bom: ValidatedBOM,
    netlist: list[NetlistEntry],
    ref_map: dict[str, tuple[str, Optional[ComponentDatasheet]]],
    unresolved_pins: Optional[list[PinRef]] = None,
) -> SchematicGraph:
    """Package an already-finalized netlist into a full SchematicGraph.

    Reruns only the packaging steps (block classification, ERC, review
    flags, confidence) — not net assignment. synthesize_schematic() below
    uses this for its own deterministic netlist. It's also the shared
    landing point for netlists produced outside net_assigner.py /
    passive_assigner.py: the ASHA search controller's winning/SA-polished/
    beam-searched netlist (search_controller.py) and the weak-model
    self-improvement loop's best netlist (self_improvement_loop.py) both
    call this directly, since neither goes through pin assignment — SA
    polish and beam search mutate an already-complete netlist, and the LLM
    proposer fills in a complete netlist itself. unresolved_pins therefore
    defaults to empty for those callers (pin resolution isn't meaningful
    for a netlist that didn't go through assign_power_nets/assign_protocol_nets).
    """
    resolved_unresolved_pins = unresolved_pins if unresolved_pins is not None else []
    blocks = classify_blocks(bom, netlist)
    erc_result = check_erc(netlist, ref_map)
    review_flags = _build_review_flags(resolved_unresolved_pins, erc_result)

    if netlist:
        synthesis_confidence = sum(n.net_confidence for n in netlist) / len(netlist)
    else:
        synthesis_confidence = 0.0

    return SchematicGraph(
        netlist=netlist,
        blocks=blocks,
        erc_result=erc_result,
        synthesis_confidence=synthesis_confidence,
        unresolved_pins=resolved_unresolved_pins,
        review_flags=review_flags,
    )


def synthesize_schematic(
    bom: ValidatedBOM,
    datasheets: list[ComponentDatasheet],
    subgraph: DesignSubgraph,
    config: Config,
) -> SchematicGraph:
    """
    Synthesize a complete netlist from BOM and component knowledge.
    Never raises. Returns SchematicGraph with review_flags on failure.
    """
    _ = subgraph
    _ = config

    try:
        unresolved_pins: list[PinRef] = []

        ref_map = build_ref_map(bom, datasheets)
        power_nets = assign_power_nets(ref_map, unresolved_pins)
        signal_nets = assign_protocol_nets(ref_map, power_nets, unresolved_pins)
        passive_nets = assign_passives(bom, ref_map, power_nets + signal_nets, unresolved_pins)
        full_netlist = power_nets + signal_nets + passive_nets

        return _package_schematic_graph(bom, full_netlist, ref_map, unresolved_pins)

    except Exception as exc:
        logger.error("Schematic synthesis failed: %s", exc, exc_info=True)
        return SchematicGraph(
            netlist=[],
            blocks=[],
            erc_result=_empty_erc_result(),
            synthesis_confidence=0.0,
            unresolved_pins=[],
            review_flags=[
                ReviewFlag(
                    item_ref=bom.design_id,
                    reason=f"Schematic synthesis failed: {exc}",
                    severity="CRITICAL",
                    stage="schematic_synthesis",
                )
            ],
        )
