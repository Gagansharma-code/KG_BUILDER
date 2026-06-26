"""Orchestrate the full Tier 0 KiCad library ingestion pipeline."""

from __future__ import annotations

import logging
from pathlib import Path

from src.knowledge_base.tier0.footprint_parser import parse_footprint_file
from src.knowledge_base.tier0.kicad_downloader import download_kicad_libraries
from src.knowledge_base.tier0.map_generator import (
    generate_footprint_map,
    generate_symbol_map,
)
from src.knowledge_base.tier0.symbol_parser import parse_symbol_library
from src.schemas.documents import KiCadFootprintEntry, KiCadSymbolEntry

logger = logging.getLogger(__name__)


def run_tier0_ingestion(
    repos_dir: Path = Path("data/kicad_repos"),
    maps_dir: Path = Path("data/kicad_maps"),
    fetch: bool = True,
) -> dict:
    """
    Full Tier 0 pipeline.

    If fetch=True, downloads/updates kicad-symbols and kicad-footprints repos.
    Always parses all .kicad_sym and .kicad_mod files found in repos_dir.
    Generates symbol_map.json and footprint_map.json in maps_dir.

    Returns summary dict with symbol/footprint counts and map entry counts.
    """
    if fetch:
        download_kicad_libraries(repos_dir)

    all_symbol_entries: list[KiCadSymbolEntry] = []
    symbol_files_found = 0
    symbol_files_failed = 0

    symbols_root = repos_dir / "kicad-symbols"
    if symbols_root.exists():
        sym_files = list(symbols_root.rglob("*.kicad_sym"))
        symbol_files_found = len(sym_files)
        for i, sym_path in enumerate(sym_files, start=1):
            if i % 500 == 0:
                logger.info("Processed %d symbol files", i)
            try:
                entries = parse_symbol_library(sym_path)
                all_symbol_entries.extend(entries)
            except Exception as exc:
                symbol_files_failed += 1
                logger.warning("Failed to parse symbol file %s: %s", sym_path, exc)

    all_footprint_entries: list[KiCadFootprintEntry] = []
    footprint_files_found = 0
    footprint_files_failed = 0

    footprints_root = repos_dir / "kicad-footprints"
    if footprints_root.exists():
        fp_files = list(footprints_root.rglob("*.kicad_mod"))
        footprint_files_found = len(fp_files)
        for i, fp_path in enumerate(fp_files, start=1):
            if i % 500 == 0:
                logger.info("Processed %d footprint files", i)
            try:
                entry = parse_footprint_file(fp_path)
                if entry is not None:
                    all_footprint_entries.append(entry)
            except Exception as exc:
                footprint_files_failed += 1
                logger.warning("Failed to parse footprint file %s: %s", fp_path, exc)

    symbol_map_entries = generate_symbol_map(
        all_symbol_entries,
        maps_dir / "symbol_map.json",
    )
    footprint_map_entries = generate_footprint_map(
        all_footprint_entries,
        maps_dir / "footprint_map.json",
    )

    return {
        "symbol_files_found": symbol_files_found,
        "symbol_files_failed": symbol_files_failed,
        "symbols_parsed": len(all_symbol_entries),
        "footprint_files_found": footprint_files_found,
        "footprint_files_failed": footprint_files_failed,
        "footprints_parsed": len(all_footprint_entries),
        "symbol_map_entries": symbol_map_entries,
        "footprint_map_entries": footprint_map_entries,
    }
