"""MPN discovery from KiCad symbol map and DigiKey category sweep."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from src.knowledge_base.scraper.adapters.digikey_adapter import DIGIKEY_CATEGORY_IDS

if TYPE_CHECKING:
    from src.knowledge_base.scraper.adapters.digikey_adapter import DigiKeyAdapter

logger = logging.getLogger(__name__)

SYMBOL_MAP_PATH = Path("data/kicad_maps/symbol_map.json")
MPN_LIST_PATH = Path("data/population_run/mpn_list.json")
MAX_PER_CATEGORY = 100


def _category_keyword(category_key: str) -> str:
    return category_key.replace("_", " ")


def discover_mpns(
    digikey_adapter: "DigiKeyAdapter",
    force_refresh: bool = False,
) -> list[str]:
    """Discover MPNs from KiCad symbol map and DigiKey category sweep."""
    try:
        if MPN_LIST_PATH.exists() and not force_refresh:
            return json.loads(MPN_LIST_PATH.read_text(encoding="utf-8"))

        if force_refresh:
            digikey_adapter._verify_category_ids()

        kicad_mpns: list[str] = []
        if SYMBOL_MAP_PATH.exists():
            symbol_map = json.loads(SYMBOL_MAP_PATH.read_text(encoding="utf-8"))
            kicad_mpns = list(symbol_map.keys())

        seen_lower: dict[str, str] = {}
        for mpn in kicad_mpns:
            seen_lower[mpn.lower()] = mpn

        for category_key, category_id in DIGIKEY_CATEGORY_IDS.items():
            keyword = _category_keyword(category_key)
            try:
                dk_mpns = digikey_adapter.keyword_search_by_category(
                    keyword, category_id, limit=MAX_PER_CATEGORY
                )
                for mpn in dk_mpns:
                    key = mpn.lower()
                    if key not in seen_lower:
                        seen_lower[key] = mpn
            except Exception as exc:
                logger.debug(
                    "DigiKey sweep failed for %s: %s", category_key, exc
                )

        result = list(seen_lower.values())
        MPN_LIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MPN_LIST_PATH.write_text(json.dumps(result), encoding="utf-8")
        return result
    except Exception as exc:
        logger.debug("discover_mpns failed: %s", exc)
        return []
