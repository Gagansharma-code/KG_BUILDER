"""Re-exports the search-controller / self-improvement config schemas.

Canonical definitions live in src/schemas/search_controller.py — src/schemas/
has no import back to src/config.py, so it is the safe home for classes
src/config.py needs at module level. src/schematic/__init__.py itself
imports `from src.config import Config`, so src/config.py cannot import
anything from inside the src.schematic package without creating a circular
import; this module exists purely so code already inside src/schematic/
can `from src.schematic._search_controller_schemas import ...` using the
same local-relative style as its sibling _schemas.py / _ref_mapper.py.
"""

from __future__ import annotations

from src.schemas.search_controller import SearchControllerConfig, SelfImprovementConfig

__all__ = ["SearchControllerConfig", "SelfImprovementConfig"]
