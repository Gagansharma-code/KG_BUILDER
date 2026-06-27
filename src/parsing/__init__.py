"""Modular parsing pipeline entry point."""

from __future__ import annotations

__all__ = ["parse_datasheet_modular"]


def __getattr__(name: str):
    if name == "parse_datasheet_modular":
        from src.parsing.modular_pipeline import parse_datasheet_modular

        return parse_datasheet_modular
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
