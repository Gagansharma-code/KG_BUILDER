"""Programmatic SA Graph Polisher — zero-LLM schematic refinement.

Activated when the ASHA controller produces a candidate with ERC score
in [SA_TRIGGER_THRESHOLD, SA_DONE_THRESHOLD). Applies deterministic graph
mutations guided by structural verifier violations and accepts/rejects each
mutation via the Metropolis criterion. No LLM tokens consumed.
"""

from __future__ import annotations

import copy
import logging
import math
import random
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from src.schemas.nir import NetlistEntry, PinRef
from src.schematic.structural_verifier import verify_schematic

if TYPE_CHECKING:
    from src.schemas.datasheet import ComponentDatasheet
    from src.schemas.intent import ValidatedBOM
    from src.schematic.structural_verifier import VerificationResult

logger = logging.getLogger(__name__)

SA_DONE_THRESHOLD:    float = 1.00
SA_TRIGGER_THRESHOLD: float = 0.80
SA_MAX_STEPS:         int   = 50
SA_T_INITIAL:         float = 1.0
SA_T_MIN:             float = 0.01
SA_ALPHA:             float = 0.90
SA_RANDOM_SEED:       int   = 42


@dataclass
class SMove:
    """A candidate graph mutation for the SA polisher.

    move_type:
        "disconnect_nc"  — remove a NC-role pin from a net it should not be on;
                           place it on a new isolated net.
        "split_driver"   — remove one of two conflicting POWER_OUT/SIGNAL_OUT
                           pins from a net; place it on a new named net.
        "reconnect_pin"  — move a pin from one net to the net whose name
                           is target_net_name.

    net_name:        The net the pin is currently on.
    pin_ref:         The PinRef being moved.
    target_net_name: New net name for the pin. None means create a fresh
                     isolated net with a generated UUID name.
    """
    move_type: str
    net_name: str
    pin_ref: PinRef
    target_net_name: Optional[str] = None


@dataclass
class SAPolishResult:
    """Result of one SA polishing run.

    polished_netlist: The (possibly improved) netlist after SA terminates.
    initial_score:    VerificationResult.score when SA started.
    final_score:      VerificationResult.score when SA terminated.
    steps_taken:      Total SA iterations executed.
    accepted_moves:   How many mutations were accepted.
    converged:        True if final_score >= SA_DONE_THRESHOLD.
    temperature_final:Temperature at the last step.
    """
    polished_netlist: list[NetlistEntry]
    initial_score: float
    final_score: float
    steps_taken: int = 0
    accepted_moves: int = 0
    converged: bool = False
    temperature_final: float = SA_T_INITIAL


def _apply_move(
    netlist: list[NetlistEntry],
    move: SMove,
) -> list[NetlistEntry]:
    """Apply a graph mutation to the netlist, returning a new netlist.

    Never mutates the input list. Uses model_copy() for all modifications.

    For "disconnect_nc" and "split_driver":
        - Find the net matching move.net_name.
        - Remove move.pin_ref from its connections list.
        - If the net now has 0 connections, remove it from the netlist.
        - Create a new net (move.target_net_name or a fresh UUID name)
          with exactly move.pin_ref as its only connection.

    For "reconnect_pin":
        - Remove move.pin_ref from move.net_name.
        - Add move.pin_ref to move.target_net_name.
        - If move.target_net_name does not exist, create it as a "signal" net.

    On any error (net not found, pin not found), return the original netlist
    unchanged and log a warning.
    """
    try:
        new_netlist: list[NetlistEntry] = []
        pin_moved = False

        for net in netlist:
            if net.net_name != move.net_name:
                new_netlist.append(net)
                continue

            new_connections = [
                c for c in net.connections
                if not (c.ref == move.pin_ref.ref
                        and c.pin_number == move.pin_ref.pin_number)
            ]

            if len(new_connections) == len(net.connections):
                logger.warning(
                    "SA move: pin %s.%s not found on net '%s'",
                    move.pin_ref.ref, move.pin_ref.pin_number, move.net_name,
                )
                new_netlist.append(net)
                continue

            pin_moved = True

            if new_connections:
                new_netlist.append(net.model_copy(update={"connections": new_connections}))
            else:
                logger.debug("SA move: net '%s' is now empty, removing.", move.net_name)

        if not pin_moved:
            return netlist

        if move.move_type == "reconnect_pin" and move.target_net_name:
            target_found = False
            updated_netlist = []
            for net in new_netlist:
                if net.net_name == move.target_net_name:
                    updated_connections = list(net.connections) + [move.pin_ref]
                    updated_netlist.append(
                        net.model_copy(update={"connections": updated_connections})
                    )
                    target_found = True
                else:
                    updated_netlist.append(net)

            if not target_found:
                updated_netlist.append(NetlistEntry(
                    net_name=move.target_net_name,
                    net_type="signal",
                    connections=[move.pin_ref],
                    source_rule="sa_polisher_reconnect",
                    net_confidence=0.70,
                ))
            return updated_netlist

        iso_name = move.target_net_name or f"SA_ISO_{uuid.uuid4().hex[:8].upper()}"
        new_netlist.append(NetlistEntry(
            net_name=iso_name,
            net_type="signal",
            connections=[move.pin_ref],
            source_rule="sa_polisher_isolate",
            net_confidence=0.50,
        ))
        return new_netlist

    except Exception as exc:
        logger.warning("SA _apply_move failed: %s. Returning original netlist.", exc)
        return netlist


def _generate_moves_from_violations(
    netlist: list[NetlistEntry],
    verification: VerificationResult,
) -> list[SMove]:
    """Generate targeted SA moves from structural verifier critical violations.

    Produces one candidate move per critical violation. Moves are ordered
    by expected impact (NC violations first, then driver conflicts, then others).

    Returns empty list if no critical violations exist.
    """
    from src.schematic.structural_verifier import VerifierLayer

    moves: list[SMove] = []
    net_by_name: dict[str, NetlistEntry] = {n.net_name: n for n in netlist}

    for violation in verification.critical_violations:
        layer = violation.layer
        net_name = violation.net_name
        ref = violation.ref

        if net_name is None or net_name not in net_by_name:
            continue

        net = net_by_name[net_name]

        if layer == VerifierLayer.PIN_ROLE_COMPATIBILITY and "NC pin" in violation.message:
            for conn in net.connections:
                if conn.ref == ref:
                    moves.append(SMove(
                        move_type="disconnect_nc",
                        net_name=net_name,
                        pin_ref=conn,
                        target_net_name=f"NC_{conn.ref}_{conn.pin_number}",
                    ))
                    break

        elif (layer == VerifierLayer.PIN_ROLE_COMPATIBILITY
              and "driver conflict" in violation.message):
            if len(net.connections) >= 2:
                offender = net.connections[-1]
                moves.append(SMove(
                    move_type="split_driver",
                    net_name=net_name,
                    pin_ref=offender,
                    target_net_name=f"SPLIT_{offender.ref}_{offender.pin_number}",
                ))

        elif (layer == VerifierLayer.SUBCATEGORY_TEMPLATES
              and "not connected" in violation.message):
            for conn in net.connections:
                if conn.ref == ref:
                    target = "GND" if "GND" in net_by_name else None
                    moves.append(SMove(
                        move_type="reconnect_pin",
                        net_name=net_name,
                        pin_ref=conn,
                        target_net_name=target,
                    ))
                    break

    return moves


def _generate_random_move(netlist: list[NetlistEntry], rng: random.Random) -> Optional[SMove]:
    """Generate a random graph mutation when no targeted moves are available.

    Randomly selects a net and a pin on that net, then disconnects the pin
    to an isolated net. Used as fallback when no critical violations exist
    but score is still < 1.0 (WARNING violations remain).

    Returns None if netlist is empty or all nets have only one connection
    (cannot disconnect without losing connectivity).
    """
    eligible_nets = [n for n in netlist if len(n.connections) >= 2]
    if not eligible_nets:
        return None

    net = rng.choice(eligible_nets)
    pin_ref = rng.choice(net.connections)

    return SMove(
        move_type="disconnect_nc",
        net_name=net.net_name,
        pin_ref=pin_ref,
        target_net_name=None,
    )


def _metropolis_accept(
    delta_score: float,
    temperature: float,
    rng: random.Random,
) -> bool:
    """Standard Metropolis acceptance criterion.

    Always accepts improvements (delta_score > 0).
    Probabilistically accepts degradations with probability exp(delta/T).

    Args:
        delta_score: new_score - current_score. Positive = improvement.
        temperature: Current SA temperature. Higher = more exploration.
        rng:         Seeded random instance for reproducibility.

    Returns:
        True if the move should be accepted.
    """
    if delta_score > 0:
        return True
    if temperature <= 0:
        return False
    return rng.random() < math.exp(delta_score / temperature)


def polish_schematic(
    netlist: list[NetlistEntry],
    ref_map: dict,
    bom: ValidatedBOM,
    verification: VerificationResult,
    expected_topologies: Optional[list[str]] = None,
    seed: int = SA_RANDOM_SEED,
) -> SAPolishResult:
    """Run SA polishing on a schematic that scored >= SA_TRIGGER_THRESHOLD.

    If verification.score < SA_TRIGGER_THRESHOLD, returns immediately with
    the original netlist unchanged (SA is not appropriate below 0.8).

    If verification.score >= SA_DONE_THRESHOLD, returns immediately
    (no polishing needed).

    Algorithm:
        T = SA_T_INITIAL
        current_netlist = netlist
        current_score = verification.score

        for step in range(SA_MAX_STEPS):
            1. Generate candidate moves from critical_violations.
               If none, use _generate_random_move().
               If no moves possible, break.
            2. Pick one move randomly.
            3. Apply move → candidate_netlist.
            4. Score candidate_netlist with verify_schematic().
            5. Metropolis accept/reject.
            6. If accepted: current_netlist = candidate_netlist
            7. If current_score >= SA_DONE_THRESHOLD: break
            8. T = max(SA_T_MIN, T * SA_ALPHA)

    Args:
        netlist:             Input netlist from ASHA winner schematic.
        ref_map:             Component ref map (for verify_schematic).
        bom:                 ValidatedBOM (for verify_schematic Layer 3).
        verification:        Initial VerificationResult from ASHA evaluation.
        expected_topologies: Topology names for Layer 4 verification.
        seed:                Random seed for reproducibility.

    Returns:
        SAPolishResult. Never raises.
    """
    initial_score = verification.score

    if initial_score < SA_TRIGGER_THRESHOLD:
        logger.debug(
            "SA polisher: score %.4f below trigger threshold %.2f. Skipping.",
            initial_score, SA_TRIGGER_THRESHOLD,
        )
        return SAPolishResult(
            polished_netlist=netlist,
            initial_score=initial_score,
            final_score=initial_score,
            converged=False,
        )

    if initial_score >= SA_DONE_THRESHOLD:
        logger.debug("SA polisher: score already 1.0. Nothing to polish.")
        return SAPolishResult(
            polished_netlist=netlist,
            initial_score=initial_score,
            final_score=initial_score,
            converged=True,
        )

    rng = random.Random(seed)
    current_netlist = list(netlist)
    current_score = initial_score
    current_verification = verification

    temperature = SA_T_INITIAL
    steps_taken = 0
    accepted_moves = 0

    logger.info(
        "SA polisher starting. Initial score: %.4f. Max steps: %d.",
        initial_score, SA_MAX_STEPS,
    )

    for step in range(SA_MAX_STEPS):
        steps_taken += 1

        moves = _generate_moves_from_violations(current_netlist, current_verification)
        if not moves:
            random_move = _generate_random_move(current_netlist, rng)
            if random_move is None:
                logger.debug("SA step %d: no moves possible. Terminating.", step)
                break
            moves = [random_move]

        chosen_move = rng.choice(moves)
        candidate_netlist = _apply_move(current_netlist, chosen_move)

        try:
            candidate_verification = verify_schematic(
                netlist=candidate_netlist,
                ref_map=ref_map,
                bom=bom,
                expected_topologies=expected_topologies,
            )
            candidate_score = candidate_verification.score
        except Exception as exc:
            logger.debug("SA step %d: verification failed: %s. Rejecting.", step, exc)
            temperature = max(SA_T_MIN, temperature * SA_ALPHA)
            continue

        delta = candidate_score - current_score
        accept = _metropolis_accept(delta, temperature, rng)

        if accept:
            current_netlist = candidate_netlist
            current_score = candidate_score
            current_verification = candidate_verification
            accepted_moves += 1
            logger.debug(
                "SA step %d: accepted move '%s' (score %.4f → %.4f, T=%.4f)",
                step, chosen_move.move_type, current_score - delta,
                current_score, temperature,
            )

            if current_score >= SA_DONE_THRESHOLD:
                logger.info(
                    "SA polisher converged at step %d. Final score: %.4f.",
                    step, current_score,
                )
                return SAPolishResult(
                    polished_netlist=current_netlist,
                    initial_score=initial_score,
                    final_score=current_score,
                    steps_taken=steps_taken,
                    accepted_moves=accepted_moves,
                    converged=True,
                    temperature_final=temperature,
                )
        else:
            logger.debug(
                "SA step %d: rejected move '%s' (delta=%.4f, T=%.4f)",
                step, chosen_move.move_type, delta, temperature,
            )

        temperature = max(SA_T_MIN, temperature * SA_ALPHA)

    logger.info(
        "SA polisher terminated. Steps: %d, Accepted: %d, "
        "Initial: %.4f, Final: %.4f.",
        steps_taken, accepted_moves, initial_score, current_score,
    )

    return SAPolishResult(
        polished_netlist=current_netlist,
        initial_score=initial_score,
        final_score=current_score,
        steps_taken=steps_taken,
        accepted_moves=accepted_moves,
        converged=current_score >= SA_DONE_THRESHOLD,
        temperature_final=temperature,
    )
