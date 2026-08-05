"""LLM-based netlist proposer — the 'weak model' half of Idea 2's
self-improvement loop (see documents/decisions/Search_controller_decision.md
and plan.md).

Nothing in src/schematic/ calls an LLM today — synthesize_schematic() is
fully deterministic (net_assigner.py, passive_assigner.py). This module is
the first LLM in that path. Structured-output generation only; scoring is
always verify_schematic(), never the LLM's own opinion of itself.

Follows the same calling convention as src/parsing/backends/llm/
qwen25_backend.py: lazily construct src.datasheet.phase3_extract.extractor.
InstructorWrapper, call .extract(response_model=..., system_prompt=...,
user_content=...) -> Optional[T].

Never raises. On any failure (model load, parse, timeout) returns
ProposedNetlistResult with parse_succeeded=False and an empty netlist — the
caller (self_improvement_loop.run_self_improving_synthesis) treats that as
a score-0.0 round and continues, matching the "never raises" contract used
throughout src/schematic/.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional

from pydantic import BaseModel, Field

from src.schemas.nir import NetlistEntry, PinRef

if TYPE_CHECKING:
    from src.config import Config
    from src.datasheet.phase3_extract.extractor import InstructorWrapper
    from src.schemas.datasheet import ComponentDatasheet, PinDefinition
    from src.schemas.intent import ValidatedBOM

logger = logging.getLogger(__name__)

# One InstructorWrapper per (model_path, device) — loading a model per call
# would make every round of the self-improvement loop reload weights from
# disk, which defeats the point of the loop. Mirrors the lazy-singleton
# pattern in src/parsing/backends/llm/qwen25_backend.py (Qwen25LLMBackend
# caches its own InstructorWrapper on self; this module has no instance to
# hang it off, so it caches at module scope instead).
_WRAPPER_CACHE: dict[str, "InstructorWrapper"] = {}

NET_TYPES = Literal["power", "signal", "RF", "clock", "differential", "analog"]


# ── LLM structured-output schema ────────────────────────────────────────────

class _LLMPinRef(BaseModel):
    ref: str = Field(description="Component reference designator, e.g. 'U1'")
    pin_number: str = Field(description="Physical pin number, e.g. '3'")


class _LLMNetConnection(BaseModel):
    net_name: str = Field(description="Net name, e.g. 'GND', 'VCC_3V3', 'FB'")
    net_type: NET_TYPES = Field(
        description="One of: power, signal, RF, clock, differential, analog. "
        "Ground nets use 'power'."
    )
    pins: list[_LLMPinRef] = Field(
        description="Every pin connected to this net.", min_length=1,
    )


class _LLMNetlistProposal(BaseModel):
    connections: list[_LLMNetConnection]


# ── Result type ──────────────────────────────────────────────────────────────

@dataclass
class ProposedNetlistResult:
    """Result of one weak-model netlist proposal attempt.

    netlist:         Mapped NetlistEntry objects. Empty if parsing failed or
                      every proposed net referenced only unknown refs/pins.
    raw_response:     str(proposal) for debugging/logging — not re-parsed.
    confidence:       0.6 if any net was produced, else 0.0. Heuristic, not
                      the model's own self-reported confidence (Qwen2.5 at
                      this size does not reliably calibrate that).
    model_used:       Config.model_paths key used for this attempt.
    temperature:      Sampling temperature this attempt used.
    parse_succeeded:  True iff at least one valid net was produced.
    """
    netlist: list["NetlistEntry"]
    raw_response: str
    confidence: float
    model_used: str
    temperature: float
    parse_succeeded: bool


# ── Prompt construction ──────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are an electronics netlist assistant. Given a bill \
of materials and, for each component, its pins with their electrical roles, \
propose a complete netlist connecting every pin into named nets.

Rules:
- Every GROUND-role pin across all components goes on one net named "GND". \
Use net_type "power" for this net.
- Every POWER_IN/POWER_OUT pin for the same supply rail shares one net \
(e.g. "VCC_3V3"); use a distinct net per distinct voltage rail.
- Signal, clock, and analog pins that logically connect given the \
component's function share a net. Do not leave a required pin unconnected.
- net_type must be exactly one of: power, signal, RF, clock, differential, \
analog.
- Only use component refs and pin numbers that were listed. Do not invent \
components or pins.
- Respond with the connections list only — no prose."""


def _build_pin_lookup(
    ref_map: dict[str, tuple[str, Optional["ComponentDatasheet"]]],
) -> dict[tuple[str, str], "PinDefinition"]:
    """Build (ref, pin_number) -> PinDefinition, mirroring the equivalent
    lookup structural_verifier._build_pin_role_lookup() builds internally —
    duplicated locally (not imported) because that helper is module-private
    to structural_verifier.py.
    """
    lookup: dict[tuple[str, str], "PinDefinition"] = {}
    for _component_id, (ref, datasheet) in ref_map.items():
        if datasheet is None:
            continue
        for pin in datasheet.pins:
            lookup[(ref, pin.pin_number)] = pin
    return lookup


def _describe_components(
    bom: "ValidatedBOM",
    pin_lookup: dict[tuple[str, str], "PinDefinition"],
) -> str:
    lines: list[str] = []
    for entry in bom.components:
        lines.append(
            f"- {entry.ref} ({entry.component_type}, "
            f"part={entry.specific_part or 'unresolved'}):"
        )
        pins_for_ref = sorted(
            (
                (pin_number, pin)
                for (ref, pin_number), pin in pin_lookup.items()
                if ref == entry.ref
            ),
            key=lambda item: item[0],
        )
        if not pins_for_ref:
            lines.append("    (no pin data available for this component)")
            continue
        for pin_number, pin in pins_for_ref:
            role = pin.pin_role.value if pin.pin_role else "unknown"
            name = pin.normalized_function or pin.raw_name
            lines.append(f"    pin {pin_number}: {name} (role={role})")
    return "\n".join(lines)


def _build_prompt(
    bom: "ValidatedBOM",
    ref_map: dict[str, tuple[str, Optional["ComponentDatasheet"]]],
    feedback: Optional[str],
) -> tuple[str, str]:
    pin_lookup = _build_pin_lookup(ref_map)
    component_block = _describe_components(bom, pin_lookup)
    user_content = (
        f"Design goal: {bom.intent.goal}\n\nComponents and pins:\n{component_block}\n"
    )
    if feedback:
        user_content += (
            "\nYour previous attempt had these problems — fix them in this "
            f"attempt:\n{feedback}\n"
        )
    return _SYSTEM_PROMPT, user_content


def _pin_display_name(pin_def: Optional["PinDefinition"]) -> str:
    if pin_def is None:
        return "UNKNOWN"
    return pin_def.normalized_function or pin_def.raw_name


def _to_netlist_entries(
    proposal: "_LLMNetlistProposal",
    bom: "ValidatedBOM",
    pin_lookup: dict[tuple[str, str], "PinDefinition"],
) -> list[NetlistEntry]:
    valid_refs = {c.ref for c in bom.components}
    netlist: list[NetlistEntry] = []

    for conn in proposal.connections:
        pin_refs: list[PinRef] = []
        for p in conn.pins:
            if p.ref not in valid_refs:
                logger.debug(
                    "propose_netlist_llm: dropping pin for unknown ref %s", p.ref
                )
                continue
            pin_def = pin_lookup.get((p.ref, p.pin_number))
            pin_refs.append(
                PinRef(
                    ref=p.ref,
                    pin_name=_pin_display_name(pin_def),
                    pin_number=p.pin_number,
                )
            )

        if not pin_refs:
            logger.debug(
                "propose_netlist_llm: net '%s' had no valid pins, dropping",
                conn.net_name,
            )
            continue

        try:
            netlist.append(
                NetlistEntry(
                    net_name=conn.net_name,
                    net_type=conn.net_type,
                    connections=pin_refs,
                    source_rule="llm_proposal",
                    net_confidence=0.6,
                )
            )
        except Exception as exc:
            logger.debug(
                "propose_netlist_llm: dropping malformed net '%s': %s",
                conn.net_name, exc,
            )

    return netlist


def _get_wrapper(config: "Config", device: str) -> "InstructorWrapper":
    """Lazily construct (and cache) the InstructorWrapper for the weak model."""
    from src.datasheet.phase3_extract.extractor import InstructorWrapper

    model_path = config.get_model_path("weak_netlist_proposer")
    key = f"{model_path}:{device}"
    if key not in _WRAPPER_CACHE:
        _WRAPPER_CACHE[key] = InstructorWrapper(model_path=model_path, device=device)
    return _WRAPPER_CACHE[key]


def propose_netlist_llm(
    bom: "ValidatedBOM",
    datasheets: list["ComponentDatasheet"],
    ref_map: dict[str, tuple[str, Optional["ComponentDatasheet"]]],
    config: "Config",
    temperature: float = 0.7,
    feedback: Optional[str] = None,
    device: str = "cpu",
) -> ProposedNetlistResult:
    """Ask the configured weak model to propose a complete netlist.

    Args:
        bom:        The BOM to wire up (specific_part per ref).
        datasheets: Full datasheet list — currently unused directly (all pin
                    data needed comes through ref_map); kept for signature
                    consistency with synthesize_schematic() and to leave room
                    for richer prompts (electrical_parameters, etc.) later.
        ref_map:    From src.schematic._ref_mapper.build_ref_map(bom, datasheets).
        config:     Application Config — used only for get_model_path().
        temperature: Sampling temperature for this attempt.
        feedback:   Plain-language summary of the previous attempt's
                    critical_violations (see self_improvement_loop.py). None
                    on the first round.
        device:     "cpu" | "cuda" | ROCm device string — passed straight to
                    InstructorWrapper. Left as a plain parameter (not read
                    from Config) so the ROCm port (Idea 6) can set it per
                    call without a config schema change here.

    Returns:
        ProposedNetlistResult. Never raises.
    """
    _ = datasheets  # see docstring — not used directly today
    model_used = "weak_netlist_proposer"

    try:
        system_prompt, user_content = _build_prompt(bom, ref_map, feedback)
        wrapper = _get_wrapper(config, device)

        proposal = wrapper.extract(
            response_model=_LLMNetlistProposal,
            system_prompt=system_prompt,
            user_content=user_content,
            temperature=temperature,
        )

        if proposal is None:
            logger.warning("propose_netlist_llm: extraction returned None.")
            return ProposedNetlistResult(
                netlist=[], raw_response="", confidence=0.0,
                model_used=model_used, temperature=temperature,
                parse_succeeded=False,
            )

        pin_lookup = _build_pin_lookup(ref_map)
        netlist = _to_netlist_entries(proposal, bom, pin_lookup)

        return ProposedNetlistResult(
            netlist=netlist,
            raw_response=str(proposal),
            confidence=0.6 if netlist else 0.0,
            model_used=model_used,
            temperature=temperature,
            parse_succeeded=bool(netlist),
        )

    except Exception as exc:
        logger.error("propose_netlist_llm failed: %s", exc, exc_info=True)
        return ProposedNetlistResult(
            netlist=[], raw_response="", confidence=0.0,
            model_used=model_used, temperature=temperature,
            parse_succeeded=False,
        )
