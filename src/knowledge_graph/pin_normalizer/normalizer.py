"""Pin normalization orchestrator.

Coordinates the three-tier normalization process:
1. Dictionary lookup (highest confidence)
2. Context resolution (medium confidence)
3. LLM fallback (variable confidence)

Normalizes the reset-state function into ``default_function`` / ``normalized_function``
and normalizes *every* ``AlternateFunction`` without collapsing multi-function pins.

Never mutates input objects. Always returns new ComponentDatasheets with
model_copy() applied to update pins.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Optional, Tuple

from src.knowledge_graph.pin_normalizer.context_resolver import resolve_with_context
from src.knowledge_graph.pin_normalizer.dictionary import normalize_from_dictionary
from src.knowledge_graph.pin_normalizer.llm_fallback import normalize_via_llm
from src.schemas.datasheet import (
    CANONICAL_TO_ROLE,
    AlternateFunction,
    ComponentDatasheet,
    PinDefinition,
    PinRole,
)

if TYPE_CHECKING:
    from src.config import Config

logger = logging.getLogger(__name__)

# Confidence levels for different tiers
DICTIONARY_CONFIDENCE = 1.0
CONTEXT_CONFIDENCE = 0.90

# Leading peripheral token on MCU AF names: SPI2_MOSI, TIM3_CH2, I2C1_SMBA, …
_PERIPHERAL_PREFIX_RE = re.compile(
    r"^(?P<periph>"
    r"(?:SPI|I2C|USART|UART|TIM|CAN|USB|ADC|DAC|SDIO|SAI|QUADSPI|LPUART)\d*"
    r")_",
    re.IGNORECASE,
)


def _infer_peripheral(af_name: str) -> Optional[str]:
    """Infer peripheral block from an AF name like ``SPI2_MOSI`` → ``SPI2``."""
    if not af_name:
        return None
    match = _PERIPHERAL_PREFIX_RE.match(af_name.strip())
    if match is None:
        return None
    return match.group("periph").upper()


def _normalize_name(
    raw_name: str,
    adjacent_pin_names: list[str],
    config: Config,
    *,
    allow_llm: bool = True,
) -> Tuple[Optional[str], float, str]:
    """Normalize a function name through dictionary → context → optional LLM.

    For AF-style names (``SPI2_MOSI``), also tries the trailing token after ``_``
    against the dictionary so multiplexed labels still map to canonical roles.
    """
    if not raw_name:
        return None, 0.0, "empty"

    canonical = normalize_from_dictionary(raw_name)
    if canonical is not None:
        return canonical, DICTIONARY_CONFIDENCE, "dictionary"

    if "_" in raw_name:
        suffix = raw_name.rsplit("_", 1)[-1]
        canonical = normalize_from_dictionary(suffix)
        if canonical is not None:
            return canonical, DICTIONARY_CONFIDENCE, "dictionary"

    canonical = resolve_with_context(raw_name, adjacent_pin_names)
    if canonical is not None:
        return canonical, CONTEXT_CONFIDENCE, "context"

    if allow_llm:
        return normalize_via_llm(raw_name, config)

    return None, 0.0, "unresolved"


def _normalize_single_pin(
    pin: PinDefinition,
    adjacent_pin_names: list[str],
    config: Config,
) -> Tuple[Optional[str], float, str]:
    """Normalize a pin's reset-state name (``raw_name``) through all three tiers.

    Args:
        pin: The PinDefinition to normalize
        adjacent_pin_names: Names of other pins in the same component
        config: Application configuration

    Returns:
        Tuple of (canonical, confidence, method)
    """
    return _normalize_name(pin.raw_name, adjacent_pin_names, config, allow_llm=True)


def _normalize_alternate_functions(
    alternate_functions: list[AlternateFunction],
    adjacent_pin_names: list[str],
    config: Config,
) -> list[AlternateFunction]:
    """Normalize every alternate function; never drop entries.

    When a name cannot be mapped to a canonical role, the original ``name`` is
    kept so multiplexed AF lists always flow through to the KG unchanged in
    cardinality.
    """
    normalized: list[AlternateFunction] = []
    for af in alternate_functions:
        canonical, _confidence, _method = _normalize_name(
            af.name,
            adjacent_pin_names,
            config,
            allow_llm=False,
        )
        resolved_name = canonical if canonical is not None else af.name
        peripheral = af.peripheral or _infer_peripheral(af.name)
        normalized.append(
            AlternateFunction(
                name=resolved_name,
                af_index=af.af_index,
                peripheral=peripheral,
            )
        )
    return normalized


def _normalize_pins_in_datasheet(
    datasheet: ComponentDatasheet,
    config: Config,
) -> ComponentDatasheet:
    """Normalize all pins in a single ComponentDatasheet.

    For each pin:
    - ``default_function`` = canonical reset-state (from ``raw_name``)
    - ``normalized_function`` = ``default_function`` (active function for downstream)
    - every ``alternate_functions`` entry is normalized; none are dropped
    Pins that fail reset-state normalization get ``default_function=None`` /
    ``normalized_function=None`` and a review flag.

    Args:
        datasheet: ComponentDatasheet to process
        config: Application configuration

    Returns:
        New ComponentDatasheet with normalized pins (never mutates input)
    """
    review_flags = list(datasheet.review_flags or [])
    normalized_pins: list[PinDefinition] = []

    # Collect all pin names for context resolution
    all_pin_names = [p.raw_name for p in datasheet.pins]

    for pin in datasheet.pins:
        # Get adjacent pins (all other pins)
        adjacent = [p for p in all_pin_names if p != pin.raw_name]

        # Normalize reset-state through all tiers
        canonical, confidence, method = _normalize_single_pin(pin, adjacent, config)

        normalized_afs = _normalize_alternate_functions(
            list(pin.alternate_functions or []),
            adjacent,
            config,
        )

        if canonical is not None:
            pin_role: Optional[PinRole] = CANONICAL_TO_ROLE.get(canonical)
            new_pin = pin.model_copy(
                update={
                    "default_function": canonical,
                    "normalized_function": canonical,
                    "normalization_confidence": confidence,
                    "normalization_method": method,
                    "pin_role": pin_role,
                    "alternate_functions": normalized_afs,
                }
            )
            normalized_pins.append(new_pin)
            logger.debug(
                f"Normalized pin {pin.pin_number} ({pin.raw_name}): "
                f"default={canonical} via {method}, "
                f"{len(normalized_afs)} alternate_functions preserved"
            )
        else:
            # Reset-state failed — still preserve / normalize AFs
            new_pin = pin.model_copy(
                update={
                    "default_function": None,
                    "normalized_function": None,
                    "normalization_confidence": confidence,  # Usually 0.0
                    "alternate_functions": normalized_afs,
                }
            )
            normalized_pins.append(new_pin)

            flag = f"Pin {pin.pin_number} ({pin.raw_name}): normalization failed"
            review_flags.append(flag)
            logger.warning(flag)

    return datasheet.model_copy(
        update={
            "pins": normalized_pins,
            "review_flags": review_flags,
        }
    )


def normalize_pins(
    datasheets: list[ComponentDatasheet],
    config: Config,
) -> list[ComponentDatasheet]:
    """Normalize pins across multiple ComponentDatasheets.

    Returns new list of ComponentDatasheets with ``default_function``,
    ``normalized_function``, ``normalization_confidence``, and normalized
    ``alternate_functions`` populated on every PinDefinition.
    Never raises. Pins that cannot be normalized get normalized_function=None
    and a review_flag added to the parent ComponentDatasheet.

    Three-tier normalization process per reset-state name:
    1. Dictionary lookup (confidence=1.0)
    2. Context resolution (confidence=0.90)
    3. LLM fallback (variable confidence)

    Alternate functions are normalized via dictionary/context only (no LLM)
    and are never dropped.

    Args:
        datasheets: List of ComponentDatasheets to process
        config: Application configuration

    Returns:
        New list of ComponentDatasheets with normalized pins.
        Never mutates input objects.

    Example:
        >>> from src.knowledge_graph.pin_normalizer import normalize_pins
        >>> from src.config import get_config
        >>> config = get_config()
        >>> normalized = normalize_pins([ds1, ds2], config)
        >>> normalized[0].pins[0].normalized_function
        'POWER_POSITIVE'
    """
    if not datasheets:
        return []

    logger.info(f"Normalizing pins for {len(datasheets)} datasheets")

    normalized_datasheets: list[ComponentDatasheet] = []
    total_pins = 0
    normalized_count = 0
    failed_count = 0

    for datasheet in datasheets:
        try:
            pin_count = len(datasheet.pins)
            total_pins += pin_count

            # Normalize this datasheet
            normalized = _normalize_pins_in_datasheet(datasheet, config)
            normalized_datasheets.append(normalized)

            # Count results
            for pin in normalized.pins:
                if pin.normalized_function is not None:
                    normalized_count += 1
                else:
                    failed_count += 1

        except Exception as e:
            # Should not happen given our design, but handle gracefully
            logger.error(
                f"Unexpected error normalizing datasheet "
                f"{datasheet.component_id}: {e}"
            )
            # Return original datasheet as fallback
            normalized_datasheets.append(datasheet)

    logger.info(
        f"Pin normalization complete: {normalized_count}/{total_pins} successful, "
        f"{failed_count} failed, {len(normalized_datasheets)} datasheets processed"
    )

    return normalized_datasheets
