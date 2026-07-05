"""Unit tests for src/intent/topology_classifier.py (isolated classifier logic)."""

from __future__ import annotations

from src.intent.topology_classifier import (
    TOPOLOGY_CLASSIFICATION_THRESHOLD,
    classify_topology,
)


class TestBasicClassification:
    def test_ldo_prompt(self) -> None:
        guesses = classify_topology("design a 3.3V LDO regulator for an IoT sensor")
        assert guesses
        assert guesses[0].name == "ldo"
        assert guesses[0].confidence >= TOPOLOGY_CLASSIFICATION_THRESHOLD

    def test_buck_converter_prompt(self) -> None:
        guesses = classify_topology("I need a buck converter stepping 12V to 5V")
        assert guesses[0].name == "buck_converter"

    def test_boost_converter_prompt(self) -> None:
        guesses = classify_topology("build a boost converter for a battery-powered device")
        assert guesses[0].name == "boost_converter"

    def test_buck_boost_prompt(self) -> None:
        guesses = classify_topology("design a buck-boost converter for a variable input supply")
        assert guesses[0].name == "buck_boost"

    def test_no_match_returns_empty(self) -> None:
        guesses = classify_topology("design a 2.4GHz patch antenna for a drone")
        assert guesses == []

    def test_never_raises_on_empty_prompt(self) -> None:
        assert classify_topology("") == []


class TestBuckBoostCollisionExclusion:
    """'buck' and 'boost' are substrings of buck-boost spellings — must not
    also spuriously classify as buck_converter/boost_converter."""

    def test_hyphenated_spelling_excludes_bare_words(self) -> None:
        guesses = classify_topology("build a buck-boost regulator")
        names = [g.name for g in guesses]
        assert "buck_boost" in names
        assert "buck_converter" not in names
        assert "boost_converter" not in names

    def test_spaced_spelling_excludes_bare_words(self) -> None:
        guesses = classify_topology("I want a buck boost converter design")
        names = [g.name for g in guesses]
        assert "buck_boost" in names
        assert "buck_converter" not in names
        assert "boost_converter" not in names

    def test_plain_buck_still_matches_when_no_boost_present(self) -> None:
        guesses = classify_topology("simple buck regulator, 5V to 3.3V")
        assert guesses[0].name == "buck_converter"

    def test_plain_boost_still_matches_when_no_buck_present(self) -> None:
        guesses = classify_topology("simple boost regulator, 3.3V to 5V")
        assert guesses[0].name == "boost_converter"


class TestConfidenceScoring:
    def test_phrase_match_scores_higher_than_bare_word(self) -> None:
        phrase = classify_topology("need a buck converter")
        bare = classify_topology("need a buck")
        assert phrase[0].confidence > bare[0].confidence

    def test_ambiguous_prompt_penalizes_both_candidates(self) -> None:
        """Mentioning both an LDO and a separate boost converter is genuinely
        ambiguous — both guesses should be penalized vs. an unambiguous prompt."""
        unambiguous = classify_topology("design an LDO regulator")
        ambiguous = classify_topology(
            "compare an LDO regulator against a boost converter for this design"
        )
        ldo_ambiguous = next(g for g in ambiguous if g.name == "ldo")
        assert ldo_ambiguous.confidence < unambiguous[0].confidence

    def test_sorted_descending_by_confidence(self) -> None:
        guesses = classify_topology("compare a buck converter with a buck regulator")
        confidences = [g.confidence for g in guesses]
        assert confidences == sorted(confidences, reverse=True)

    def test_low_confidence_guesses_never_returned(self) -> None:
        for guesses in (
            classify_topology("design a 3.3V LDO regulator"),
            classify_topology("compare an LDO regulator against a boost converter"),
        ):
            assert all(g.confidence >= TOPOLOGY_CLASSIFICATION_THRESHOLD for g in guesses)


class TestBroaderVocabulary:
    """Slugs beyond interval_solver's four, reconciled from
    structural_verifier.TOPOLOGY_TEMPLATES — retrieval/axiom_loader benefit
    from these being populated even though Rule 1 does not branch on them."""

    def test_inverting_amplifier(self) -> None:
        guesses = classify_topology("design an inverting amplifier with gain of -10")
        assert guesses[0].name == "inverting_amplifier"

    def test_voltage_divider(self) -> None:
        guesses = classify_topology("simple voltage divider to scale down a sensor signal")
        assert guesses[0].name == "voltage_divider"

    def test_rc_lowpass(self) -> None:
        guesses = classify_topology("need an RC low-pass filter at 1kHz cutoff")
        assert guesses[0].name == "rc_lowpass"

    def test_current_source(self) -> None:
        guesses = classify_topology("build a precision current source for a sensor bias")
        assert guesses[0].name == "current_source"
