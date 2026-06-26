"""Gate tests for the SA graph polisher."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import random

from src.schemas.nir import NetlistEntry, PinRef
from src.schematic.sa_polisher import (
    SA_DONE_THRESHOLD,
    SA_TRIGGER_THRESHOLD,
    SAPolishResult,
    SMove,
    _apply_move,
    _generate_moves_from_violations,
    _generate_random_move,
    _metropolis_accept,
    polish_schematic,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _pin(ref: str, name: str, number: str) -> PinRef:
    return PinRef(ref=ref, pin_name=name, pin_number=number)


def _net(name: str, net_type: str, connections: list[PinRef]) -> NetlistEntry:
    return NetlistEntry(
        net_name=name,
        net_type=net_type,
        connections=connections,
        source_rule="test",
        net_confidence=0.9,
    )


def _make_verification(score: float, critical_violations: list | None = None) -> MagicMock:
    v = MagicMock()
    v.score = score
    v.critical_violations = critical_violations or []
    return v


# ── Constants ─────────────────────────────────────────────────────────────────

def test_sa_trigger_threshold_is_0_8():
    assert SA_TRIGGER_THRESHOLD == 0.80

def test_sa_done_threshold_is_1_0():
    assert SA_DONE_THRESHOLD == 1.00


# ── SMove ─────────────────────────────────────────────────────────────────────

def test_smove_creation():
    pin = _pin("U1", "NC", "4")
    move = SMove(move_type="disconnect_nc", net_name="VCC", pin_ref=pin)
    assert move.move_type == "disconnect_nc"
    assert move.pin_ref.ref == "U1"
    assert move.target_net_name is None


# ── _apply_move ───────────────────────────────────────────────────────────────

def test_apply_move_disconnect_nc_removes_pin_from_net():
    pin_nc = _pin("U1", "NC", "4")
    pin_vdd = _pin("U2", "VDD", "1")
    net = _net("VCC", "power", [pin_vdd, pin_nc])
    move = SMove(
        move_type="disconnect_nc",
        net_name="VCC",
        pin_ref=pin_nc,
        target_net_name="NC_U1_4",
    )
    result = _apply_move([net], move)
    vcc_net = next(n for n in result if n.net_name == "VCC")
    assert len(vcc_net.connections) == 1
    assert vcc_net.connections[0].ref == "U2"

def test_apply_move_creates_isolated_net_for_nc_pin():
    pin_nc = _pin("U1", "NC", "4")
    pin_vdd = _pin("U2", "VDD", "1")
    net = _net("VCC", "power", [pin_vdd, pin_nc])
    move = SMove(
        move_type="disconnect_nc",
        net_name="VCC",
        pin_ref=pin_nc,
        target_net_name="NC_U1_4",
    )
    result = _apply_move([net], move)
    nc_net = next((n for n in result if n.net_name == "NC_U1_4"), None)
    assert nc_net is not None
    assert len(nc_net.connections) == 1
    assert nc_net.connections[0].ref == "U1"

def test_apply_move_removes_empty_net():
    pin = _pin("U1", "NC", "4")
    net = _net("SOLO_NET", "signal", [pin])
    move = SMove(
        move_type="disconnect_nc",
        net_name="SOLO_NET",
        pin_ref=pin,
        target_net_name="NC_U1_4",
    )
    result = _apply_move([net], move)
    names = [n.net_name for n in result]
    assert "SOLO_NET" not in names
    assert "NC_U1_4" in names

def test_apply_move_reconnect_pin_moves_to_existing_net():
    pin = _pin("U1", "OUT", "3")
    source = _net("WRONG_NET", "signal", [pin])
    dest   = _net("VOUT", "power", [_pin("U2", "IN", "1")])
    move = SMove(
        move_type="reconnect_pin",
        net_name="WRONG_NET",
        pin_ref=pin,
        target_net_name="VOUT",
    )
    result = _apply_move([source, dest], move)
    vout = next(n for n in result if n.net_name == "VOUT")
    assert any(c.ref == "U1" for c in vout.connections)

def test_apply_move_reconnect_creates_new_net_if_missing():
    pin = _pin("U1", "OUT", "3")
    source = _net("WRONG_NET", "signal", [pin])
    move = SMove(
        move_type="reconnect_pin",
        net_name="WRONG_NET",
        pin_ref=pin,
        target_net_name="NEW_NET",
    )
    result = _apply_move([source], move)
    new_net = next((n for n in result if n.net_name == "NEW_NET"), None)
    assert new_net is not None

def test_apply_move_does_not_mutate_original():
    pin_nc = _pin("U1", "NC", "4")
    pin_vdd = _pin("U2", "VDD", "1")
    net = _net("VCC", "power", [pin_vdd, pin_nc])
    original_len = len(net.connections)
    move = SMove(
        move_type="disconnect_nc",
        net_name="VCC",
        pin_ref=pin_nc,
        target_net_name="NC_U1_4",
    )
    _apply_move([net], move)
    assert len(net.connections) == original_len

def test_apply_move_pin_not_found_returns_original():
    pin = _pin("U1", "OUT", "3")
    net = _net("VCC", "power", [pin])
    nonexistent_pin = _pin("U99", "X", "99")
    move = SMove(
        move_type="disconnect_nc",
        net_name="VCC",
        pin_ref=nonexistent_pin,
    )
    result = _apply_move([net], move)
    assert len(result) == 1
    assert result[0].net_name == "VCC"


# ── _metropolis_accept ────────────────────────────────────────────────────────

def test_metropolis_always_accepts_improvement():
    rng = random.Random(0)
    assert _metropolis_accept(0.05, 1.0, rng) is True

def test_metropolis_always_accepts_zero_delta():
    rng = random.Random(0)
    assert _metropolis_accept(0.0, 1.0, rng) is True

def test_metropolis_sometimes_rejects_degradation_at_low_temp():
    rng = random.Random(42)
    rejections = 0
    for _ in range(100):
        if not _metropolis_accept(-0.5, 0.01, rng):
            rejections += 1
    assert rejections > 90

def test_metropolis_often_accepts_small_degradation_at_high_temp():
    rng = random.Random(42)
    acceptances = 0
    for _ in range(100):
        if _metropolis_accept(-0.01, 2.0, rng):
            acceptances += 1
    assert acceptances > 90

def test_metropolis_zero_temperature_rejects_degradation():
    rng = random.Random(0)
    assert _metropolis_accept(-0.1, 0.0, rng) is False


# ── _generate_random_move ─────────────────────────────────────────────────────

def test_generate_random_move_returns_none_for_empty_netlist():
    rng = random.Random(0)
    result = _generate_random_move([], rng)
    assert result is None

def test_generate_random_move_returns_none_when_all_nets_singleton():
    nets = [_net("N1", "signal", [_pin("U1", "A", "1")])]
    rng = random.Random(0)
    result = _generate_random_move(nets, rng)
    assert result is None

def test_generate_random_move_returns_smove_for_eligible_net():
    nets = [
        _net("VCC", "power", [_pin("U1", "VDD", "1"), _pin("U2", "VDD", "1")]),
    ]
    rng = random.Random(0)
    result = _generate_random_move(nets, rng)
    assert result is not None
    assert isinstance(result, SMove)


# ── polish_schematic ──────────────────────────────────────────────────────────

def test_polish_skips_when_score_below_trigger():
    netlist = [_net("VCC", "power", [_pin("U1", "VDD", "1")])]
    verification = _make_verification(score=0.70)
    result = polish_schematic(netlist, {}, MagicMock(), verification)
    assert isinstance(result, SAPolishResult)
    assert result.steps_taken == 0
    assert result.polished_netlist is netlist

def test_polish_skips_when_score_already_done():
    netlist = [_net("VCC", "power", [_pin("U1", "VDD", "1")])]
    verification = _make_verification(score=1.0)
    result = polish_schematic(netlist, {}, MagicMock(), verification)
    assert result.steps_taken == 0
    assert result.converged is True

def test_polish_returns_ssa_polish_result():
    netlist = [_net("VCC", "power", [_pin("U1", "VDD", "1"), _pin("U2", "VDD", "2")])]
    init_v = _make_verification(score=0.85)
    done_v = _make_verification(score=1.0)

    with patch("src.schematic.sa_polisher.verify_schematic", return_value=done_v):
        result = polish_schematic(netlist, {}, MagicMock(), init_v)

    assert isinstance(result, SAPolishResult)

def test_polish_converges_when_verifier_returns_perfect():
    netlist = [_net("VCC", "power", [_pin("U1", "VDD", "1"), _pin("U2", "NC", "4")])]
    init_v = _make_verification(score=0.85)
    done_v = _make_verification(score=1.0)

    with patch("src.schematic.sa_polisher.verify_schematic", return_value=done_v):
        result = polish_schematic(netlist, {}, MagicMock(), init_v)

    assert result.converged is True
    assert result.final_score == 1.0

def test_polish_does_not_exceed_max_steps():
    netlist = [_net("VCC", "power", [_pin("U1", "VDD", "1"), _pin("U2", "VDD", "2")])]
    init_v = _make_verification(score=0.85)
    with patch("src.schematic.sa_polisher.verify_schematic",
               return_value=_make_verification(score=0.85)):
        result = polish_schematic(netlist, {}, MagicMock(), init_v)

    from src.schematic.sa_polisher import SA_MAX_STEPS
    assert result.steps_taken <= SA_MAX_STEPS

def test_polish_initial_score_preserved():
    netlist = [_net("VCC", "power", [_pin("U1", "VDD", "1"), _pin("U2", "VDD", "2")])]
    init_v = _make_verification(score=0.88)
    with patch("src.schematic.sa_polisher.verify_schematic",
               return_value=_make_verification(score=0.88)):
        result = polish_schematic(netlist, {}, MagicMock(), init_v)
    assert result.initial_score == pytest.approx(0.88)

def test_polish_never_raises():
    netlist = []
    init_v = _make_verification(score=0.82)
    with patch("src.schematic.sa_polisher.verify_schematic",
               side_effect=RuntimeError("verifier crash")):
        result = polish_schematic(netlist, {}, MagicMock(), init_v)
    assert isinstance(result, SAPolishResult)
