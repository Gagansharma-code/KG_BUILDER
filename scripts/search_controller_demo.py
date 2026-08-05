"""Idea 1 demo — watch the ASHA search controller evaluate two BOM
candidates for the same design and pick a winner.

Unlike Idea 2 (agent_maxing_benchmark.py), this needs no model weights and
no knowledge graph — synthesize_schematic() is fully deterministic, so this
runs instantly and offline. It builds a small two-candidate BOMLadder by
hand (mirroring what generate_bom_candidates() would produce from a real
KG query) and calls run_search_controller() directly, the same way
eval/gates/team_d_gate.py CHECK 9 does, but with a realistic non-empty BOM
so you can actually see scores, the winner, and (if triggered) SA-polish /
beam-search refinement happen.

Candidate 1 is a complete, correctly-labeled LDO datasheet. Candidate 2 is
a cheaper alternate part whose datasheet is missing the ground-pin role —
net_assigner.py can't place an unlabeled pin, so that candidate should
score lower and lose. This is meant to make the "search" part of ASHA
visible: it isn't just running synthesis once, it's evaluating multiple
options and picking the best one.

Usage:
    python -m scripts.search_controller_demo
"""

from __future__ import annotations

from src.bom import BOMLadder
from src.config import Config
from src.schemas.datasheet import ComponentDatasheet, ExtractionMethod, PinDefinition, PinRole
from src.schemas.intent import BOMEntry, DesignMethodology, ImprovedIntentDict, ValidatedBOM
from src.schemas.kg import DesignSubgraph
from src.schematic.search_controller import run_search_controller


def _intent(goal: str) -> ImprovedIntentDict:
    return ImprovedIntentDict(
        goal=goal,
        application="search_controller_demo",
        design_methodology=DesignMethodology.STANDARD_SMD,
        board_type="standard_SMD",
        raw_prompt=goal,
    )


def _pin(number: str, raw_name: str, role: PinRole | None) -> PinDefinition:
    return PinDefinition(
        pin_number=number,
        raw_name=raw_name,
        normalized_function=raw_name,
        pin_role=role,
        normalization_confidence=0.9,
        pin_type="power",
    )


def _datasheet(component_id: str, pins: list[PinDefinition]) -> ComponentDatasheet:
    return ComponentDatasheet(
        component_id=component_id,
        manufacturer="Fixture",
        description="search_controller_demo fixture",
        package="SOT-23",
        source_pdf_hash="fixture",
        extraction_method=ExtractionMethod.MANUAL,
        extraction_confidence=1.0,
        created_at="2026-01-01T00:00:00Z",
        pins=pins,
    )


def _bom(design_id: str, part: str, confidence: float) -> ValidatedBOM:
    return ValidatedBOM(
        design_id=design_id,
        intent=_intent("3.3V LDO linear voltage regulator"),
        components=[
            BOMEntry(
                ref="U1", component_type="ldo_regulator", specific_part=part,
                justification="demo", source="demo", confidence=confidence,
            ),
        ],
        total_confidence=confidence, review_required=False,
        created_at="2026-01-01T00:00:00Z",
    )


def main() -> None:
    # Candidate 1: complete, correct pinout.
    ds_good = _datasheet("LDO_GOOD", [
        _pin("1", "VIN", PinRole.POWER_IN),
        _pin("2", "GND", PinRole.GROUND),
        _pin("3", "VOUT", PinRole.POWER_OUT),
    ])
    bom_good = _bom("demo-ldo-primary", "LDO_GOOD", 0.92)

    # Candidate 2: cheaper alternate part, ground-pin role unresolved.
    ds_worse = _datasheet("LDO_ALT", [
        _pin("1", "VIN", PinRole.POWER_IN),
        _pin("2", "GND", None),
        _pin("3", "VOUT", PinRole.POWER_OUT),
    ])
    bom_worse = _bom("demo-ldo-alt", "LDO_ALT", 0.78)

    ladder = BOMLadder(
        candidates=[bom_good, bom_worse],
        primary_varied_component="U1",
        n_candidates=2,
        ladder_id="demo-ladder-001",
    )

    subgraph = DesignSubgraph(design_methodology="standard_SMD", query_depth=0)
    config = Config()

    print("Running ASHA search controller over 2 BOM candidates...\n")
    result = run_search_controller(ladder, [ds_good, ds_worse], subgraph, config)

    print("Candidate scores:  ", result.candidate_scores)
    print(
        "Winner:            ",
        result.winner_bom.design_id,
        "-> part", result.winner_bom.components[0].specific_part,
    )
    print("Refinement stage:  ", result.stage_used)
    print("Final score:       ", f"{result.final_score:.4f}")
    print("Routed to review:  ", result.routed_to_human_review)
    print("Final netlist nets:", [n.net_name for n in result.final_netlist])


if __name__ == "__main__":
    main()
