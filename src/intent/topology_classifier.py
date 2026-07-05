"""Topology classifier — deterministic keyword-based topology guess for Stage 1.

Closes DOC_DRIFT_AUDIT.md finding N4: src/intent/interval_solver.py's Rule 1
(voltage/dropout chain) branches on intent.goal_topology, but nothing in the
real pipeline ever set it — src/intent/parser.py never populated
goal_topology or goal_topologies, so the topology-aware branch was dead code
on every real prompt.

Why a keyword classifier, not a new LLM call (Section 1A determination):
parser.py's _call_llm_with_instructor() is an unimplemented placeholder that
always returns None — _rule_based_parse() (keyword matching) is what
actually runs in production today, for both `goal` (via
COMPONENT_TYPE_NORMALIZATION) and `design_methodology` (via
methodology_classifier.METHODOLOGY_TRIGGERS). Adding a new LLM-backed
topology classifier would not actually execute; this module mirrors the
existing, functioning pattern instead.

Threshold (Section 1B determination): 0.60. This is not a new arbitrary
value — it matches the confidence cutoff already hardcoded in
src/completion/axiom_loader.py (CONFIDENCE_THRESHOLD) and
src/retrieval/planner.py (topology_slugs filter), both of which already
consume intent.goal_topologies at >= 0.6. Guesses below threshold are
omitted entirely (not just left unpromoted), so
ImprovedIntentDict.populate_goal_topology_compat() — which unconditionally
promotes goal_topologies[0].name to goal_topology whenever the list is
non-empty — never promotes a low-confidence guess.

Vocabulary reconciliation (Section 0B determination — documented, not
silently resolved):
  - src/intent/interval_solver.py Rule 1 branches on exactly four slugs:
    "ldo", "buck_converter" (dropout/buck-like), "boost_converter",
    "buck_boost" (voltage-chain-skip). Any other value of goal_topology,
    including None, makes Rule 1 return early without checking anything
    (src/intent/interval_solver.py line ~122: "Unknown or unlisted
    topology: Rule 1 does not apply") — this is "no check performed", not
    "safe default assumed."
  - src/schematic/structural_verifier.py TOPOLOGY_TEMPLATES has six keys:
    "ldo", "buck_converter", "inverting_amplifier", "voltage_divider",
    "rc_lowpass", "current_source" — notably NO "boost_converter" or
    "buck_boost" entries. A prompt correctly classified into either slug
    has no post-synthesis structural template to verify against today.
    That gap lives in structural_verifier.py, out of scope for this task.
  - src/knowledge_graph/topology/library.py's formal KG TOPOLOGY_SLUGS is
    the smallest set ("ldo", "buck_converter" only) — this classifier's
    vocabulary is intentionally broader, per task scope: classification
    vocabulary may exceed the formalized KG set.
  - src/intent/parser.py's clean_goal() normalizes goal strings via
    COMPONENT_TYPE_NORMALIZATION, e.g. "ldo" -> "ldo_regulator". That is a
    GOAL string, not a topology slug, and "ldo_regulator" != this module's
    "ldo" slug. Do not assume intent.goal equals intent.goal_topology, and
    do not derive one from the other — this module matches directly
    against the raw prompt text, independent of goal cleaning.
  - "buck" and "boost" are both substrings of "buck-boost"/"buck boost",
    and this collision is not limited to bare words: the phrase "boost
    regulator" is itself a literal substring of "buck-boost regulator",
    and "boost converter" a literal substring of "buck boost converter".
    A naive match would misclassify every buck-boost prompt as ALSO
    matching buck_converter and/or boost_converter. See
    _contains_buck_boost() and the masking step in classify_topology()
    below for the explicit mutual-exclusion rule this module applies to
    avoid that collision: any buck-boost phrase found in the prompt is
    stripped out of the text before buck_converter/boost_converter
    keywords are scanned, so no overlapping substring can match.

Public API:
    classify_topology(prompt: str) -> list[TopologyGuess]
"""

from __future__ import annotations

import logging

from src.schemas.common import TopologyGuess

logger = logging.getLogger(__name__)

# Matches src/completion/axiom_loader.py's CONFIDENCE_THRESHOLD and
# src/retrieval/planner.py's topology_slugs filter — see module docstring.
TOPOLOGY_CLASSIFICATION_THRESHOLD = 0.60

# Keyword triggers per topology slug (lowercase for matching). Slug
# vocabulary reconciled against interval_solver.py's Rule 1 sets and
# structural_verifier.py's TOPOLOGY_TEMPLATES keys (see module docstring).
TOPOLOGY_TRIGGERS: dict[str, list[str]] = {
    "ldo": [
        "ldo",
        "low dropout",
        "low-dropout",
        "low drop out",
        "linear regulator",
    ],
    "buck_converter": [
        "buck converter",
        "buck regulator",
        "step-down",
        "step down",
        "buck",
    ],
    "boost_converter": [
        "boost converter",
        "boost regulator",
        "step-up",
        "step up",
        "boost",
    ],
    "buck_boost": [
        "inverting buck-boost",
        "buck-boost",
        "buck boost",
        "buck_boost",
    ],
    "inverting_amplifier": [
        "inverting amplifier",
        "inverting op-amp",
        "inverting opamp",
    ],
    "voltage_divider": [
        "voltage divider",
        "resistor divider",
    ],
    "rc_lowpass": [
        "rc low-pass",
        "rc lowpass",
        "rc low pass",
        "low-pass filter",
        "lowpass filter",
    ],
    "current_source": [
        "current source",
        "current mirror",
    ],
}

# A multi-word/hyphenated phrase match is unambiguous; a single bare word
# (e.g. "buck") is common in EE prompts but slightly more likely to be part
# of a different phrase — scored lower.
_PHRASE_CONFIDENCE = 0.90
_WORD_CONFIDENCE = 0.75

# Applied once per additional distinct topology matched in the same prompt.
# A prompt that genuinely triggers two different topologies is ambiguous;
# neither guess should retain full unambiguous confidence.
_AMBIGUITY_PENALTY = 0.15

# Phrases that collide with buck_converter/boost_converter keywords — see
# module docstring's vocabulary reconciliation note. Any of these found in
# the prompt is stripped out before buck_converter/boost_converter keywords
# are scanned, so substrings like "boost regulator" (contained inside
# "buck-boost regulator") or "buck" (contained inside "buck boost") cannot
# spuriously match.
_BUCK_BOOST_PHRASES = ("buck-boost", "buck boost", "buck_boost", "inverting buck-boost")


def _contains_buck_boost(prompt_lower: str) -> bool:
    """True if the prompt mentions buck-boost in any spelling."""
    return any(phrase in prompt_lower for phrase in _BUCK_BOOST_PHRASES)


def _mask_buck_boost_phrases(prompt_lower: str) -> str:
    """Remove every buck-boost spelling from the text (see module docstring)."""
    masked = prompt_lower
    for phrase in _BUCK_BOOST_PHRASES:
        masked = masked.replace(phrase, " ")
    return masked


def _find_match(keywords: list[str], text: str) -> tuple[str, bool] | None:
    """Return (matched_keyword, is_phrase) for the first keyword found, or None."""
    for keyword in keywords:
        if keyword in text:
            is_phrase = any(c in keyword for c in (" ", "-", "_"))
            return keyword, is_phrase
    return None


def classify_topology(prompt: str) -> list[TopologyGuess]:
    """Classify a design prompt into 0+ topology guesses.

    Deterministic keyword matching — see module docstring for why this
    mirrors methodology_classifier.py's pattern rather than adding a new
    LLM call. Never raises; returns [] on any internal failure so Stage 1
    parsing is never blocked by this step.

    Guesses are filtered to TOPOLOGY_CLASSIFICATION_THRESHOLD and above
    before being returned, and sorted by confidence descending, so
    ImprovedIntentDict.populate_goal_topology_compat() — which promotes
    goal_topologies[0].name to goal_topology whenever the list is
    non-empty — only ever promotes a guess this module considers
    reasonably reliable.

    Args:
        prompt: Raw user design prompt (same text passed into parse_intent).

    Returns:
        list[TopologyGuess], possibly empty, sorted by confidence descending.

    Example:
        >>> guesses = classify_topology("design a 3.3V LDO regulator")
        >>> guesses[0].name
        'ldo'
        >>> guesses = classify_topology("design a buck-boost converter")
        >>> guesses[0].name
        'buck_boost'
    """
    try:
        prompt_lower = prompt.lower()
        masked_prompt = (
            _mask_buck_boost_phrases(prompt_lower)
            if _contains_buck_boost(prompt_lower)
            else prompt_lower
        )

        candidates: list[TopologyGuess] = []
        for slug, keywords in TOPOLOGY_TRIGGERS.items():
            # buck_boost must scan the original text (that's the phrase
            # being detected); every other slug scans the masked text so
            # buck-boost substrings cannot collide with its keywords.
            scan_text = prompt_lower if slug == "buck_boost" else masked_prompt
            match = _find_match(keywords, scan_text)
            if match is None:
                continue
            matched_keyword, is_phrase = match
            confidence = _PHRASE_CONFIDENCE if is_phrase else _WORD_CONFIDENCE
            candidates.append(
                TopologyGuess(
                    name=slug,
                    confidence=confidence,
                    evidence=[matched_keyword],
                )
            )

        if len(candidates) > 1:
            # Ambiguous prompt — multiple distinct topologies matched.
            # Penalize all, preserving relative ranking.
            candidates = [
                TopologyGuess(
                    name=c.name,
                    confidence=max(0.0, round(c.confidence - _AMBIGUITY_PENALTY, 4)),
                    evidence=c.evidence,
                )
                for c in candidates
            ]

        qualifying = [
            c for c in candidates if c.confidence >= TOPOLOGY_CLASSIFICATION_THRESHOLD
        ]
        qualifying.sort(key=lambda c: c.confidence, reverse=True)

        if qualifying:
            logger.debug(
                "Topology classification: %s",
                [(g.name, g.confidence) for g in qualifying],
            )
        return qualifying

    except Exception as exc:  # never raises — Stage 1 must not fail here
        logger.error(f"Topology classification failed: {exc}")
        return []
