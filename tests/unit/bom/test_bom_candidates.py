"""Gate tests for generate_bom_candidates and BOMLadder."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.bom.candidates import (
    BOMLadder,
    _build_variant_bom,
    _component_weight,
    _find_highest_weight_entry,
    generate_bom_candidates,
)
from src.schemas.intent import BOMEntry, DesignMethodology, IntentDict, ValidatedBOM


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_entry(
    ref: str,
    component_type: str,
    specific_part: str | None = "TEST_PART",
    confidence: float = 0.90,
    alternatives: list[str] | None = None,
) -> BOMEntry:
    return BOMEntry(
        ref=ref,
        component_type=component_type,
        specific_part=specific_part,
        confidence=confidence,
        alternatives=alternatives or [],
        justification="test justification",
        source="test",
    )


def _make_mock_entry(
    ref: str,
    component_type: str,
    specific_part: str | None = "TEST_PART",
    confidence: float = 0.90,
    alternatives: list[str] | None = None,
) -> MagicMock:
    entry = MagicMock()
    entry.ref = ref
    entry.component_type = component_type
    entry.specific_part = specific_part
    entry.confidence = confidence
    entry.alternatives = alternatives or []
    entry.justification = "test justification"
    entry.model_copy = lambda update: _apply_update(entry, update)
    return entry


def _apply_update(entry: MagicMock, update: dict) -> MagicMock:
    """Simulate Pydantic model_copy(update=...)."""
    new_entry = MagicMock()
    new_entry.ref = entry.ref
    new_entry.component_type = entry.component_type
    new_entry.specific_part = update.get("specific_part", entry.specific_part)
    new_entry.confidence = update.get("confidence", entry.confidence)
    new_entry.alternatives = update.get("alternatives", entry.alternatives)
    new_entry.justification = update.get("justification", entry.justification)
    new_entry.model_copy = lambda u: _apply_update(new_entry, u)
    return new_entry


def _make_bom(
    components: list,
    total_confidence: float = 0.90,
    review_required: bool = False,
) -> ValidatedBOM:
    intent = IntentDict(
        goal="test",
        application="test",
        design_methodology=DesignMethodology.STANDARD_SMD,
        board_type="standard_SMD",
        raw_prompt="test",
    )
    return ValidatedBOM(
        design_id=str(uuid.uuid4()),
        intent=intent,
        components=components,
        total_confidence=total_confidence,
        review_required=review_required,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _make_mock_bom(
    components: list,
    total_confidence: float = 0.90,
    review_required: bool = False,
) -> MagicMock:
    bom = MagicMock()
    bom.design_id = str(uuid.uuid4())
    bom.components = components
    bom.total_confidence = total_confidence
    bom.review_required = review_required
    bom.created_at = datetime.now(timezone.utc).isoformat()

    def _model_copy(update):
        new_bom = MagicMock()
        new_bom.design_id = update.get("design_id", bom.design_id)
        new_bom.components = update.get("components", bom.components)
        new_bom.total_confidence = update.get("total_confidence", bom.total_confidence)
        new_bom.review_required = update.get("review_required", bom.review_required)
        new_bom.created_at = update.get("created_at", bom.created_at)
        new_bom.model_copy = _model_copy
        return new_bom

    bom.model_copy = _model_copy
    return bom


def _make_validated_bom(total_confidence: float) -> ValidatedBOM:
    intent = IntentDict(
        goal="test",
        application="test",
        design_methodology=DesignMethodology.STANDARD_SMD,
        board_type="standard_SMD",
        raw_prompt="test",
    )
    return ValidatedBOM(
        design_id=str(uuid.uuid4()),
        intent=intent,
        components=[
            BOMEntry(
                ref="U1",
                component_type="ldo_regulator",
                justification="test",
                source="test",
                confidence=total_confidence,
            )
        ],
        total_confidence=total_confidence,
        review_required=False,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


# ── _component_weight ─────────────────────────────────────────────────────────

def test_weight_ldo_is_high():
    assert _component_weight("ldo_regulator") == 2.0

def test_weight_antenna_is_high():
    assert _component_weight("antenna") == 2.0

def test_weight_capacitor_is_low():
    assert _component_weight("capacitor") == 0.5

def test_weight_resistor_is_low():
    assert _component_weight("resistor") == 0.5

def test_weight_unknown_is_default():
    assert _component_weight("some_unknown_type") == 1.0

def test_weight_mcu_is_high():
    assert _component_weight("microcontroller") == 2.0


# ── _find_highest_weight_entry ────────────────────────────────────────────────

def test_find_highest_weight_returns_high_weight():
    entries = [
        _make_entry("C1", "capacitor"),
        _make_entry("U1", "ldo_regulator"),
        _make_entry("R1", "resistor"),
    ]
    result = _find_highest_weight_entry(entries)
    assert result.ref == "U1"

def test_find_highest_weight_empty_returns_none():
    assert _find_highest_weight_entry([]) is None

def test_find_highest_weight_single_entry():
    entries = [_make_entry("U1", "ldo_regulator")]
    result = _find_highest_weight_entry(entries)
    assert result.ref == "U1"


# ── _build_variant_bom ────────────────────────────────────────────────────────

def test_build_variant_bom_swaps_specific_part():
    entry = _make_mock_entry("U1", "ldo_regulator", specific_part="TPS7A20", alternatives=["LT3080"])
    bom = _make_mock_bom([entry])
    variant = _build_variant_bom(bom, "U1", "LT3080")
    assert variant is not None
    u1_variant = next(e for e in variant.components if e.ref == "U1")
    assert u1_variant.specific_part == "LT3080"

def test_build_variant_bom_has_new_design_id():
    entry = _make_mock_entry("U1", "ldo_regulator", alternatives=["LT3080"])
    bom = _make_mock_bom([entry])
    variant = _build_variant_bom(bom, "U1", "LT3080")
    assert variant.design_id != bom.design_id

def test_build_variant_bom_penalises_confidence():
    entry = _make_mock_entry("U1", "ldo_regulator", confidence=0.90, alternatives=["LT3080"])
    bom = _make_mock_bom([entry], total_confidence=0.90)
    variant = _build_variant_bom(bom, "U1", "LT3080")
    assert variant.total_confidence < 0.90

def test_build_variant_bom_leaves_other_entries_unchanged():
    u1 = _make_mock_entry("U1", "ldo_regulator", alternatives=["LT3080"])
    c1 = _make_mock_entry("C1", "capacitor", specific_part="GRM155")
    bom = _make_mock_bom([u1, c1])
    variant = _build_variant_bom(bom, "U1", "LT3080")
    c1_variant = next(e for e in variant.components if e.ref == "C1")
    assert c1_variant.specific_part == "GRM155"


# ── BOMLadder ─────────────────────────────────────────────────────────────────

def test_bom_ladder_best_returns_first():
    bom1 = _make_validated_bom(0.92)
    bom2 = _make_validated_bom(0.88)
    ladder = BOMLadder(
        candidates=[bom1, bom2],
        n_candidates=2,
        ladder_id=str(uuid.uuid4()),
    )
    assert ladder.best() is bom1

def test_bom_ladder_scores():
    bom1 = _make_validated_bom(0.92)
    bom2 = _make_validated_bom(0.88)
    ladder = BOMLadder(
        candidates=[bom1, bom2],
        n_candidates=2,
        ladder_id=str(uuid.uuid4()),
    )
    assert ladder.scores() == [0.92, 0.88]

def test_bom_ladder_requires_at_least_one_candidate():
    with pytest.raises(Exception):
        BOMLadder(candidates=[], n_candidates=0, ladder_id=str(uuid.uuid4()))


# ── generate_bom_candidates ─────────────────────────────────────────────────

def _mock_generate_bom(bom_mock):
    """Return a patch context that makes generate_bom return bom_mock."""
    return patch("src.bom.candidates.generate_bom", return_value=bom_mock)

def test_generate_bom_candidates_returns_bom_ladder():
    bom = _make_bom([_make_entry("U1", "ldo_regulator")])
    with _mock_generate_bom(bom):
        ladder = generate_bom_candidates(MagicMock(), MagicMock(), MagicMock())
    assert isinstance(ladder, BOMLadder)

def test_generate_bom_candidates_single_when_no_alternatives():
    entry = _make_entry("U1", "ldo_regulator", alternatives=[])
    bom = _make_bom([entry])
    with _mock_generate_bom(bom):
        ladder = generate_bom_candidates(MagicMock(), MagicMock(), MagicMock())
    assert ladder.n_candidates == 1

def test_generate_bom_candidates_multiple_when_alternatives_exist():
    entry = _make_entry("U1", "ldo_regulator", alternatives=["LT3080", "MCP1700"])
    bom = _make_bom([entry])
    with _mock_generate_bom(bom):
        ladder = generate_bom_candidates(MagicMock(), MagicMock(), MagicMock(),
                                          max_candidates=3)
    assert ladder.n_candidates >= 2

def test_generate_bom_candidates_ranked_descending():
    entry = _make_entry("U1", "ldo_regulator", confidence=0.92,
                         alternatives=["LT3080", "MCP1700"])
    bom = _make_bom([entry], total_confidence=0.92)
    with _mock_generate_bom(bom):
        ladder = generate_bom_candidates(MagicMock(), MagicMock(), MagicMock(),
                                          max_candidates=3)
    scores = ladder.scores()
    assert scores == sorted(scores, reverse=True)

def test_generate_bom_candidates_max_is_three():
    entry = _make_entry("U1", "ldo_regulator",
                         alternatives=["A", "B", "C", "D", "E"])
    bom = _make_bom([entry])
    with _mock_generate_bom(bom):
        ladder = generate_bom_candidates(MagicMock(), MagicMock(), MagicMock(),
                                          max_candidates=3)
    assert ladder.n_candidates <= 3

def test_generate_bom_candidates_ladder_id_is_uuid():
    bom = _make_bom([])
    with _mock_generate_bom(bom):
        ladder = generate_bom_candidates(MagicMock(), MagicMock(), MagicMock())
    uuid.UUID(ladder.ladder_id)

def test_generate_bom_candidates_survives_generate_bom_exception():
    intent = IntentDict(
        goal="test",
        application="test",
        design_methodology=DesignMethodology.STANDARD_SMD,
        board_type="standard_SMD",
        raw_prompt="test",
    )
    with patch("src.bom.candidates.generate_bom", side_effect=RuntimeError("KG down")):
        with patch("src.bom.candidates.ValidatedBOM") as mock_vbom:
            mock_vbom.return_value = _make_bom([])
            ladder = generate_bom_candidates(MagicMock(), intent, MagicMock())
    assert isinstance(ladder, BOMLadder)
    assert ladder.n_candidates >= 1

def test_generate_bom_candidates_primary_varied_component_set():
    entry = _make_entry("U1", "ldo_regulator", alternatives=["LT3080"])
    bom = _make_bom([entry])
    with _mock_generate_bom(bom):
        ladder = generate_bom_candidates(MagicMock(), MagicMock(), MagicMock(),
                                          max_candidates=2)
    if ladder.n_candidates > 1:
        assert ladder.primary_varied_component == "ldo_regulator"

def test_generate_bom_candidates_metadata_has_base_design_id():
    bom = _make_bom([])
    with _mock_generate_bom(bom):
        ladder = generate_bom_candidates(MagicMock(), MagicMock(), MagicMock())
    assert "base_bom_design_id" in ladder.generation_metadata

def test_existing_generate_bom_import_unchanged():
    """Regression: original generate_bom must still be importable from src.bom."""
    from src.bom import generate_bom, validate_bom, generate_bom_candidates, BOMLadder
    assert callable(generate_bom)
    assert callable(validate_bom)
    assert callable(generate_bom_candidates)
    assert BOMLadder is not None
