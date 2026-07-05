"""Intent parser — extract structured IntentDict from natural language prompts.

Uses Instructor with Qwen2.5-7B-Instruct to parse design prompts into
structured ParsedIntent, then enriches with methodology classification,
constraint inference, and ambiguity detection.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, Field

from src.schemas.intent import DesignMethodology, FrequencySpec, ImprovedIntentDict

if TYPE_CHECKING:
    from src.config import Config
    from src.schemas.intent import IntentDict

logger = logging.getLogger(__name__)

# System prompt for the LLM intent extraction
SYSTEM_PROMPT = """
You are a PCB design intent extractor. Parse the user's design description
and return a structured JSON object.

Fields to extract:
- goal: the primary component or circuit to build (snake_case noun, e.g. "patch_antenna", 
  "ldo_regulator", "motor_driver", "buck_converter")
- frequency: if a frequency is mentioned, extract value and unit.
  unit must be exactly one of: Hz, kHz, MHz, GHz
- application: the end application (e.g. "drone", "IoT sensor", "industrial motor control")
- explicit_constraints: list of constraints directly stated in the prompt
- design_methodology: classify into exactly one of these values:
    "RF_highfreq"       — any mention of antenna, RF, Bluetooth, WiFi, LoRa, GHz frequencies
    "power_management"  — buck, boost, LDO, regulator, battery, charger, SMPS
    "mixed_signal"      — ADC, DAC, op-amp, analog, sensor, precision measurement
    "standard_SMD"      — general digital, microcontroller, IoT, control systems
    "through_hole"      — prototype, hand-solder, THT, DIP packages
- board_type: one of "double_sided_SMD", "4_layer", "through_hole", "single_sided"
- ambiguities: list any fields you could not confidently extract

Rules:
- goal must be a snake_case string with no spaces
- design_methodology must be exactly one of the five values listed above
- If frequency is not mentioned, omit the frequency field entirely
- If you cannot determine a field with confidence > 0.75, add it to ambiguities
"""


class ParsedIntent(BaseModel):
    """Output model for LLM intent parsing.

    This is the structured output expected from the Instructor call.
    It is then enriched and converted to IntentDict.
    """

    goal: str = Field(description="Primary component or circuit to build (snake_case)")
    frequency: Optional[FrequencySpec] = Field(
        default=None, description="Operating frequency if specified"
    )
    application: str = Field(default="unspecified", description="End application domain")
    explicit_constraints: list[str] = Field(
        default_factory=list, description="User-specified constraints"
    )
    design_methodology: DesignMethodology = Field(description="Selected design methodology")
    board_type: str = Field(default="double_sided_SMD", description="PCB classification")
    ambiguities: list[str] = Field(
        default_factory=list, description="Fields that could not be confidently extracted"
    )


GOAL_STOPWORDS = {
    "a", "an", "the", "i", "my", "our", "some", "this", "that",
    "for", "of", "to", "need", "want", "build", "design", "create",
    "make", "get", "use",
}

COMPONENT_TYPE_NORMALIZATION: dict[str, str] = {
    "ldo":        "ldo_regulator",
    "buck":       "buck_converter",
    "boost":      "boost_converter",
    "inverting":  "inverting_converter",
    "patch":      "patch_antenna",
    "antenna":    "antenna",
    "dipole":     "dipole_antenna",
    "loop":       "loop_antenna",
    "mcu":        "microcontroller",
    "adc":        "adc_converter",
    "dac":        "dac_converter",
    "opamp":      "op_amp",
    "op":         "op_amp",
    "mosfet":     "mosfet",
    "bjt":        "transistor",
    "smps":       "switching_regulator",
    "driver":     "gate_driver",
    "comparator": "voltage_comparator",
    "regulator":  "voltage_regulator",
    "oscillator": "crystal_oscillator",
    "filter":     "passive_filter",
    "bridge":     "h_bridge_driver",
    "charger":    "battery_charger",
}


def clean_goal(raw_goal: str) -> str:
    """
    Strip articles, prepositions, and filler words from LLM-generated goal strings.
    Input:  "a_3_3v_ldo"  Output: "ldo_regulator"
    Input:  "a_2_4ghz_patch" Output: "patch_antenna"

    Simple cleaning:
    1. Split on underscores and hyphens
    2. Remove leading and trailing parts that are in GOAL_STOPWORDS
    3. Remove purely numeric parts (e.g. "3", "5")
    4. Normalize the last meaningful part via COMPONENT_TYPE_NORMALIZATION
    5. Return lowercase result
    """
    parts = raw_goal.replace("-", "_").lower().split("_")
    while parts and parts[0] in GOAL_STOPWORDS:
        parts.pop(0)
    while parts and parts[-1] in GOAL_STOPWORDS:
        parts.pop()
    parts = [p for p in parts if any(c.isalpha() for c in p)]
    if not parts:
        return "unknown"

    # Apply component type normalization to the last meaningful part.
    # The last part is usually the core noun ("ldo", "patch", "buck").
    last = parts[-1]
    if last in COMPONENT_TYPE_NORMALIZATION:
        if len(parts) == 1 or any(any(c.isdigit() for c in p) for p in parts[:-1]):
            # Replace the last part with the canonical name.
            parts[-1] = COMPONENT_TYPE_NORMALIZATION[last]
            # If canonical name already contains the full phrase, use it alone.
            return COMPONENT_TYPE_NORMALIZATION[last]

    return "_".join(parts[:4])


def _typed_constraints_as_strings(parsed: ParsedIntent) -> list[str]:
    """
    Converts populated typed v2 fields back into canonical string tokens
    so constraint_inferrer can deduplicate against them.
    Falls back to parsed.explicit_constraints for any string that did not
    map to a typed field.
    """
    typed: list[str] = []

    electrical = getattr(parsed, "electrical", None)
    if electrical and electrical.power_budget_mw is not None:
        typed.append("low_power")
    thermal = getattr(parsed, "thermal", None)
    if thermal and thermal.operating_temp_min_c is not None:
        typed.append("wide_temperature")
    reliability = getattr(parsed, "reliability", None)
    if reliability and reliability.operating_environment in (
        "military", "industrial"
    ):
        typed.append("high_reliability")
    manufacturing = getattr(parsed, "manufacturing", None)
    if manufacturing and manufacturing.board_dimensions_mm is not None:
        typed.append("compact")

    remainder = [
        c for c in (parsed.explicit_constraints or [])
        if c not in typed
    ]
    return typed + remainder


def _to_snake_case(text: str) -> str:
    """Convert text to snake_case."""
    # Replace spaces and hyphens with underscores
    normalized = text.replace(" ", "_").replace("-", "_")
    # Remove multiple underscores
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    # Lowercase
    return normalized.lower().strip("_")


def _call_llm_with_instructor(
    prompt: str,
    config: Config,
) -> Optional[ParsedIntent]:
    """Call Qwen2.5-7B via Instructor to parse the intent.

    This is a placeholder implementation. In production, this would:
    1. Load the Qwen2.5-7B-Instruct model from config.model_paths["qwen25_7b"]
    2. Use Instructor to get structured ParsedIntent output
    3. Handle retries and error cases

    Args:
        prompt: The user's natural language design prompt
        config: Application configuration with model paths

    Returns:
        ParsedIntent on success, None on failure
    """
    try:
        # Placeholder: try to import instructor (optional dependency)
        try:
            import instructor
            from openai import OpenAI
        except ImportError:
            logger.warning("instructor or openai not installed, using mock parsing")
            return None

        # This would be the real implementation:
        # client = OpenAI(base_url="...", api_key="...")
        # instructor_client = instructor.from_openai(client)
        # result = instructor_client.chat.completions.create(
        #     model="Qwen/Qwen2.5-7B-Instruct",
        #     messages=[
        #         {"role": "system", "content": SYSTEM_PROMPT},
        #         {"role": "user", "content": prompt},
        #     ],
        #     response_model=ParsedIntent,
        # )

        # For now, return None to trigger rule-based fallback
        logger.debug("Instructor LLM call not implemented, using fallback")
        return None

    except Exception as e:
        logger.error(f"LLM parsing failed: {e}")
        return None


def _rule_based_parse(prompt: str) -> ParsedIntent:
    """Fallback rule-based parser when LLM is unavailable.

    Uses simple keyword matching to extract intent fields.
    """
    from src.schemas.intent import DesignMethodology, FrequencySpec

    prompt_lower = prompt.lower()

    # Extract goal (look for action words)
    goal = "circuit"  # default
    action_indicators = ["build", "design", "create", "make", "need", "want"]
    for indicator in action_indicators:
        if indicator in prompt_lower:
            # Extract text after the indicator
            idx = prompt_lower.find(indicator) + len(indicator)
            remainder = prompt[idx:].strip()
            # Take first few words as goal
            words = remainder.replace(",", " ").replace(".", " ").split()[:4]
            if words:
                goal = "_".join(words)
                break

    # Clean up goal
    goal = _to_snake_case(goal)

    # Extract frequency
    frequency: Optional[FrequencySpec] = None
    import re
    freq_patterns = [
        (r'(\d+\.?\d*)\s*(GHz)', "GHz"),
        (r'(\d+\.?\d*)\s*(MHz)', "MHz"),
        (r'(\d+\.?\d*)\s*(kHz)', "kHz"),
        (r'(\d+\.?\d*)\s*(Hz)', "Hz"),
    ]
    for pattern, unit in freq_patterns:
        match = re.search(pattern, prompt_lower)
        if match:
            try:
                value = float(match.group(1))
                frequency = FrequencySpec(value=value, unit=unit)  # type: ignore
                break
            except (ValueError, TypeError):
                pass

    # Determine methodology via keyword matching
    from src.intent.methodology_classifier import METHODOLOGY_TRIGGERS

    methodology = DesignMethodology.STANDARD_SMD
    for meth_name, keywords in METHODOLOGY_TRIGGERS.items():
        for keyword in keywords:
            if keyword in prompt_lower:
                methodology = DesignMethodology(meth_name)
                break
        if methodology != DesignMethodology.STANDARD_SMD:
            break

    # Extract application context
    application = "unspecified"
    app_keywords = {
        "drone": "drone",
        "drones": "drone",
        "iot": "iot sensor",
        "sensor": "iot sensor",
        "industrial": "industrial",
        "medical": "medical",
        "automotive": "automotive",
        "wearable": "wearable",
        "prototype": "prototype",
        "handheld": "handheld",
        "portable": "portable",
    }
    for keyword, app_name in app_keywords.items():
        if keyword in prompt_lower:
            application = app_name
            break

    # Extract explicit constraints
    explicit_constraints: list[str] = []
    constraint_keywords = [
        "low power", "low-power", "ultra low power",
        "compact", "small", "lightweight", "light weight",
        "high reliability", "robust", "waterproof",
        "high temperature", "wide temperature",
    ]
    for keyword in constraint_keywords:
        if keyword in prompt_lower:
            normalized = keyword.replace(" ", "_").replace("-", "_")
            explicit_constraints.append(normalized)

    # Determine board type
    board_type = "double_sided_SMD"
    if "through hole" in prompt_lower or "tht" in prompt_lower or "dip" in prompt_lower:
        board_type = "through_hole"
    elif "4 layer" in prompt_lower or "four layer" in prompt_lower:
        board_type = "4_layer"
    elif "single sided" in prompt_lower or "single layer" in prompt_lower:
        board_type = "single_sided"

    # Detect ambiguities
    ambiguities: list[str] = []
    if goal in ["circuit", "board", "pcb", "device"]:
        ambiguities.append("Goal is too generic - need more specific design objective")
    if application == "unspecified":
        ambiguities.append("Application context not clear")
    if methodology == DesignMethodology.RF_HIGHFREQ and frequency is None:
        ambiguities.append("RF design requires frequency specification")

    return ParsedIntent(
        goal=goal,
        frequency=frequency,
        application=application,
        explicit_constraints=explicit_constraints,
        design_methodology=methodology,
        board_type=board_type,
        ambiguities=ambiguities,
    )


def parse_intent(
    prompt: str,
    config: Config,
) -> IntentDict:
    """Parse a natural language PCB design prompt into a structured IntentDict.

    Never raises. On model failure, returns IntentDict with
    clarification_required=True and one AmbiguityFlag explaining the failure.

    Pipeline:
    1. Try LLM parsing with Instructor + Qwen2.5-7B
    2. Fall back to rule-based parsing if LLM fails
    3. Validate/enrich methodology classification
    4. Infer constraints from application context
    5. Detect ambiguities
    6. Construct final IntentDict

    Args:
        prompt: The user's natural language design prompt
        config: Application configuration

    Returns:
        IntentDict with parsed intent, never raises

    Example:
        >>> intent = parse_intent("build a 2.4GHz patch antenna for a drone", config)
        >>> intent.goal
        'patch_antenna'
        >>> intent.design_methodology.value
        'RF_highfreq'
    """
    from src.intent.ambiguity_detector import detect_ambiguities
    from src.intent.constraint_inferrer import infer_constraints
    from src.intent.methodology_classifier import validate_methodology
    from src.intent.topology_classifier import classify_topology
    from src.schemas.common import Ambiguity
    from src.schemas.intent import (
        DesignMethodology,
    )

    # Step 1: Parse with LLM or fallback
    parsed: ParsedIntent | None = _call_llm_with_instructor(prompt, config)

    if parsed is None:
        # LLM failed or not available - use rule-based fallback
        logger.info("Using rule-based parser (LLM unavailable)")
        parsed = _rule_based_parse(prompt)

    cleaned_goal = clean_goal(parsed.goal)

    # Step 1b: Classify topology (closes DOC_DRIFT_AUDIT.md N4). Matched
    # against the raw prompt independently of goal cleaning — see
    # topology_classifier.py's vocabulary reconciliation note for why.
    topology_guesses = classify_topology(prompt)

    # Step 2: Validate/enrich methodology
    validated_methodology, was_overridden = validate_methodology(
        parsed.design_methodology, prompt
    )
    if was_overridden:
        logger.info(f"Methodology overridden: {parsed.design_methodology.value} -> {validated_methodology.value}")

    # Step 3: Infer constraints from application context
    inferred_constraints = infer_constraints(
        parsed.application, _typed_constraints_as_strings(parsed)
    )

    # Step 4: Detect ambiguities
    draft_intent = ImprovedIntentDict(
        goal=cleaned_goal,
        frequency=parsed.frequency,
        application=parsed.application,
        inferred_constraints=inferred_constraints,
        design_methodology=validated_methodology,
        board_type=parsed.board_type,
        goal_topologies=topology_guesses,
        ambiguities=[],
        clarification_required=False,
        raw_prompt=prompt,
    )
    ambiguity_flags = detect_ambiguities(draft_intent, prompt)
    for ambiguity in parsed.ambiguities:
        ambiguity_flags.append(
            Ambiguity(
                field="unknown",
                description=ambiguity,
                severity="WARNING",
            )
        )

    # Step 5: Determine if clarification is required
    clarification_required = any(
        flag.blocking for flag in ambiguity_flags
    )

    # Step 6: Construct ImprovedIntentDict
    return ImprovedIntentDict(
        goal=cleaned_goal,
        frequency=parsed.frequency,
        application=parsed.application,
        inferred_constraints=inferred_constraints,
        design_methodology=validated_methodology,
        board_type=parsed.board_type,
        goal_topologies=topology_guesses,
        ambiguities=ambiguity_flags,
        clarification_required=clarification_required,
        raw_prompt=prompt,
    )


def get_clarification_questions(
    intent: IntentDict,
) -> list[dict[str, Any]]:
    """Convert intent.ambiguities into human-readable question dicts.

    Returns: [{"question": str, "field": str, "options": list[str]}]
    Returns empty list if intent.clarification_required is False.

    Only includes CRITICAL ambiguities - WARNING-level issues don't block progress.

    Args:
        intent: The parsed intent with ambiguities

    Returns:
        List of question dicts for user clarification, or empty list

    Example:
        >>> intent = parse_intent("I need something", config)
        >>> questions = get_clarification_questions(intent)
        >>> len(questions) > 0
        True
        >>> questions[0]["field"]
        'goal'
    """
    if not intent.clarification_required:
        return []

    questions: list[dict[str, Any]] = []

    for flag in intent.ambiguities:
        if not flag.blocking:
            continue

        # Generate human-friendly question based on field
        question_text = flag.description
        if flag.field == "goal":
            question_text = "What specific component or circuit do you want to build? (e.g., '3.3V LDO regulator', '2.4GHz patch antenna')"
        elif flag.field == "frequency":
            question_text = "What is the target operating frequency?"
        elif flag.field == "application":
            question_text = "What is the end application? (e.g., drone, IoT sensor, industrial control)"

        questions.append({
            "question": question_text,
            "field": flag.field,
            "options": flag.candidate_resolutions,
        })

    return questions
