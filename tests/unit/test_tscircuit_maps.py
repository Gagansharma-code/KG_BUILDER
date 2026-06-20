"""Unit tests for tscircuit footprint and element mapping modules."""

from __future__ import annotations

from src.output.tscircuit_element_map import get_element_type, get_pin_label
from src.output.tscircuit_footprint_map import resolve_footprint


def test_resolve_footprint_sot23_5() -> None:
    assert resolve_footprint("SOT-23-5", "chip") == ("SOT-23-5", False)


def test_resolve_footprint_resistor_0402() -> None:
    assert resolve_footprint("0402", "resistor") == ("R_0402_1005Metric", False)


def test_resolve_footprint_capacitor_0402() -> None:
    assert resolve_footprint("0402", "capacitor") == ("C_0402_1005Metric", False)


def test_resolve_footprint_unknown_pkg() -> None:
    assert resolve_footprint("UNKNOWN_PKG", "chip") == ("UNKNOWN_PKG", True)


def test_get_element_type_resistor() -> None:
    assert get_element_type("resistor") == ("resistor", False)


def test_get_element_type_ldo_regulator() -> None:
    assert get_element_type("ldo_regulator") == ("chip", False)


def test_get_element_type_unknown() -> None:
    assert get_element_type("unknown_thing") == ("chip", True)


def test_get_pin_label_capacitor_pos() -> None:
    assert get_pin_label("capacitor", "1") == "pos"


def test_get_pin_label_capacitor_neg() -> None:
    assert get_pin_label("capacitor", "2") == "neg"


def test_get_pin_label_chip_fallback() -> None:
    assert get_pin_label("chip", "3") == "pin3"
