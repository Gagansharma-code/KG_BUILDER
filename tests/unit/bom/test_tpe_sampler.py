"""Gate tests for TPE BOM Sampler."""
from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

import pytest

from src.bom.tpe_sampler import (
    MIN_OBSERVATIONS_FOR_PREDICTION,
    BOMOutcome,
    ComponentRanking,
    TPEBOMSampler,
    record_asha_outcome,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_bom_entry(
    ref: str = "U1",
    component_type: str = "ldo_regulator",
    specific_part: str | None = "TPS7A20DRVR",
    confidence: float = 0.92,
    alternatives: list[str] | None = None,
) -> MagicMock:
    entry = MagicMock()
    entry.ref = ref
    entry.component_type = component_type
    entry.specific_part = specific_part
    entry.confidence = confidence
    entry.alternatives = alternatives or []
    entry.model_copy = lambda update: _apply_entry_update(entry, update)
    return entry


def _apply_entry_update(entry: MagicMock, update: dict) -> MagicMock:
    new = MagicMock()
    new.ref = entry.ref
    new.component_type = entry.component_type
    new.specific_part = update.get("specific_part", entry.specific_part)
    new.confidence = entry.confidence
    new.alternatives = update.get("alternatives", entry.alternatives)
    new.model_copy = lambda u: _apply_entry_update(new, u)
    return new


def _make_bom(
    design_id: str | None = None,
    components: list | None = None,
) -> MagicMock:
    bom = MagicMock()
    bom.design_id = design_id or str(uuid.uuid4())
    bom.components = components or [_make_bom_entry()]

    def _model_copy(update):
        new_bom = MagicMock()
        new_bom.design_id = bom.design_id
        new_bom.components = update.get("components", bom.components)
        new_bom.model_copy = _model_copy
        return new_bom

    bom.model_copy = _model_copy
    return bom


def _make_ladder(candidates: list) -> MagicMock:
    ladder = MagicMock()
    ladder.ladder_id = str(uuid.uuid4())
    ladder.candidates = candidates
    ladder.model_copy = lambda update: _apply_ladder_update(ladder, update)
    return ladder


def _apply_ladder_update(ladder: MagicMock, update: dict) -> MagicMock:
    new = MagicMock()
    new.ladder_id = ladder.ladder_id
    new.candidates = update.get("candidates", ladder.candidates)
    new.model_copy = lambda u: _apply_ladder_update(new, u)
    return new


# ── BOMOutcome ────────────────────────────────────────────────────────────────

def test_bom_outcome_creation():
    o = BOMOutcome(
        design_id="D1",
        component_type="ldo_regulator",
        specific_part="TPS7A20DRVR",
        erc_score=0.95,
    )
    assert o.design_id == "D1"
    assert o.erc_score == 0.95
    assert o.timestamp is not None

def test_bom_outcome_allows_none_specific_part():
    o = BOMOutcome(
        design_id="D1",
        component_type="ldo_regulator",
        specific_part=None,
        erc_score=0.50,
    )
    assert o.specific_part is None


# ── TPEBOMSampler initialisation ──────────────────────────────────────────────

def test_sampler_starts_empty_when_no_file(tmp_path):
    sampler = TPEBOMSampler(history_path=tmp_path / "history.json")
    assert sampler.total_outcomes == 0

def test_sampler_creates_history_file_on_record(tmp_path):
    path = tmp_path / "history.json"
    sampler = TPEBOMSampler(history_path=path)
    bom = _make_bom()
    sampler.record_outcome(bom, 0.90)
    assert path.exists()

def test_sampler_loads_existing_history(tmp_path):
    path = tmp_path / "history.json"
    initial_data = [
        {
            "design_id": "D1",
            "component_type": "ldo_regulator",
            "specific_part": "TPS7A20DRVR",
            "erc_score": 0.95,
            "timestamp": "2026-01-01T00:00:00+00:00",
        }
    ]
    path.write_text(json.dumps(initial_data), encoding="utf-8")
    sampler = TPEBOMSampler(history_path=path)
    assert sampler.total_outcomes == 1

def test_sampler_handles_corrupt_history_file(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("not valid json {{{{", encoding="utf-8")
    sampler = TPEBOMSampler(history_path=path)
    assert sampler.total_outcomes == 0


# ── record_outcome ────────────────────────────────────────────────────────────

def test_record_outcome_increments_total(tmp_path):
    sampler = TPEBOMSampler(history_path=tmp_path / "h.json")
    bom = _make_bom(components=[
        _make_bom_entry("U1", "ldo_regulator", "TPS7A20DRVR"),
        _make_bom_entry("C1", "capacitor", "GRM155"),
    ])
    sampler.record_outcome(bom, 0.92)
    assert sampler.total_outcomes == 2

def test_record_outcome_persists_to_disk(tmp_path):
    path = tmp_path / "h.json"
    sampler = TPEBOMSampler(history_path=path)
    bom = _make_bom()
    sampler.record_outcome(bom, 0.88)
    sampler2 = TPEBOMSampler(history_path=path)
    assert sampler2.total_outcomes == 1


def test_save_load_round_trip_preserves_outcomes(tmp_path):
    """Explicit public save() → new TPEBOMSampler(_load) round-trip."""
    path = tmp_path / "round_trip.json"
    sampler = TPEBOMSampler(history_path=path)
    sampler.record_outcome(_make_bom(design_id="D-rt-1"), 0.91)
    sampler.record_outcome(
        _make_bom(
            design_id="D-rt-2",
            components=[_make_bom_entry(specific_part="ALT-PART")],
        ),
        0.77,
    )
    sampler.save()

    reloaded = TPEBOMSampler(history_path=path)
    assert reloaded.total_outcomes == 2
    assert {o.design_id for o in reloaded._history} == {"D-rt-1", "D-rt-2"}
    assert {o.specific_part for o in reloaded._history} == {
        "TPS7A20DRVR", "ALT-PART",
    }
    scores = {o.design_id: o.erc_score for o in reloaded._history}
    assert scores["D-rt-1"] == pytest.approx(0.91)
    assert scores["D-rt-2"] == pytest.approx(0.77)


def test_save_never_raises_on_unwritable_path(tmp_path):
    """save() must not break the design pipeline on I/O failure."""
    bad_parent = tmp_path / "not_a_dir"
    bad_parent.write_text("blocker", encoding="utf-8")
    sampler = TPEBOMSampler(history_path=bad_parent / "nested" / "h.json")
    sampler._history.append(
        BOMOutcome(
            design_id="D1",
            component_type="ldo_regulator",
            specific_part="X",
            erc_score=0.5,
        )
    )
    sampler.save()  # must not raise


def test_record_outcome_clamps_erc_score(tmp_path):
    sampler = TPEBOMSampler(history_path=tmp_path / "h.json")
    bom = _make_bom()
    sampler.record_outcome(bom, 1.5)
    assert sampler._history[-1].erc_score <= 1.0

def test_record_outcome_normalises_component_type(tmp_path):
    sampler = TPEBOMSampler(history_path=tmp_path / "h.json")
    bom = _make_bom(components=[
        _make_bom_entry(component_type="  LDO_Regulator  ")
    ])
    sampler.record_outcome(bom, 0.90)
    assert sampler._history[0].component_type == "ldo_regulator"


# ── get_preferred_parts ───────────────────────────────────────────────────────

def test_get_preferred_parts_returns_empty_below_min_observations(tmp_path):
    sampler = TPEBOMSampler(history_path=tmp_path / "h.json")
    for i in range(MIN_OBSERVATIONS_FOR_PREDICTION - 1):
        sampler._history.append(BOMOutcome(
            design_id=f"D{i}",
            component_type="ldo_regulator",
            specific_part="TPS7A20DRVR",
            erc_score=0.90,
        ))
    result = sampler.get_preferred_parts("ldo_regulator")
    assert result == []

def test_get_preferred_parts_returns_ranked_parts(tmp_path):
    sampler = TPEBOMSampler(history_path=tmp_path / "h.json")
    for _ in range(4):
        sampler._history.append(BOMOutcome(
            design_id=str(uuid.uuid4()),
            component_type="ldo_regulator",
            specific_part="TPS7A20DRVR",
            erc_score=0.95,
        ))
    for _ in range(4):
        sampler._history.append(BOMOutcome(
            design_id=str(uuid.uuid4()),
            component_type="ldo_regulator",
            specific_part="LT3080",
            erc_score=0.80,
        ))
    result = sampler.get_preferred_parts("ldo_regulator")
    assert len(result) >= 1
    assert result[0] == "TPS7A20DRVR"

def test_get_preferred_parts_excludes_current_selection(tmp_path):
    sampler = TPEBOMSampler(history_path=tmp_path / "h.json")
    for _ in range(4):
        sampler._history.append(BOMOutcome(
            design_id=str(uuid.uuid4()),
            component_type="ldo_regulator",
            specific_part="TPS7A20DRVR",
            erc_score=0.95,
        ))
    for _ in range(4):
        sampler._history.append(BOMOutcome(
            design_id=str(uuid.uuid4()),
            component_type="ldo_regulator",
            specific_part="LT3080",
            erc_score=0.88,
        ))
    result = sampler.get_preferred_parts(
        "ldo_regulator",
        exclude_part="TPS7A20DRVR",
    )
    assert "TPS7A20DRVR" not in result
    assert "LT3080" in result

def test_get_preferred_parts_respects_n(tmp_path):
    sampler = TPEBOMSampler(history_path=tmp_path / "h.json")
    for part in ["P1", "P2", "P3", "P4"]:
        for _ in range(4):
            sampler._history.append(BOMOutcome(
                design_id=str(uuid.uuid4()),
                component_type="ldo_regulator",
                specific_part=part,
                erc_score=0.85,
            ))
    result = sampler.get_preferred_parts("ldo_regulator", n=2)
    assert len(result) <= 2

def test_get_preferred_parts_excludes_none_parts(tmp_path):
    sampler = TPEBOMSampler(history_path=tmp_path / "h.json")
    for _ in range(4):
        sampler._history.append(BOMOutcome(
            design_id=str(uuid.uuid4()),
            component_type="ldo_regulator",
            specific_part=None,
            erc_score=0.50,
        ))
    result = sampler.get_preferred_parts("ldo_regulator")
    assert result == []


# ── get_component_ranking ─────────────────────────────────────────────────────

def test_get_component_ranking_returns_none_below_threshold(tmp_path):
    sampler = TPEBOMSampler(history_path=tmp_path / "h.json")
    result = sampler.get_component_ranking("ldo_regulator")
    assert result is None

def test_get_component_ranking_returns_ranking_with_enough_data(tmp_path):
    sampler = TPEBOMSampler(history_path=tmp_path / "h.json")
    for _ in range(MIN_OBSERVATIONS_FOR_PREDICTION + 1):
        sampler._history.append(BOMOutcome(
            design_id=str(uuid.uuid4()),
            component_type="ldo_regulator",
            specific_part="TPS7A20DRVR",
            erc_score=0.92,
        ))
    result = sampler.get_component_ranking("ldo_regulator")
    assert isinstance(result, ComponentRanking)
    assert result.component_type == "ldo_regulator"
    assert len(result.ranked_parts) >= 1

def test_get_component_ranking_is_sorted_descending(tmp_path):
    sampler = TPEBOMSampler(history_path=tmp_path / "h.json")
    for _ in range(4):
        sampler._history.append(BOMOutcome(
            design_id=str(uuid.uuid4()),
            component_type="ldo_regulator",
            specific_part="HIGH_SCORE_PART",
            erc_score=0.95,
        ))
    for _ in range(4):
        sampler._history.append(BOMOutcome(
            design_id=str(uuid.uuid4()),
            component_type="ldo_regulator",
            specific_part="LOW_SCORE_PART",
            erc_score=0.60,
        ))
    ranking = sampler.get_component_ranking("ldo_regulator")
    scores = [score for _, score in ranking.ranked_parts]
    assert scores == sorted(scores, reverse=True)


# ── enrich_bom_candidates ─────────────────────────────────────────────────────

def test_enrich_bom_candidates_returns_ladder(tmp_path):
    sampler = TPEBOMSampler(history_path=tmp_path / "h.json")
    bom = _make_bom()
    ladder = _make_ladder([bom])
    result = sampler.enrich_bom_candidates(ladder)
    assert result is not None

def test_enrich_bom_candidates_does_not_modify_when_no_history(tmp_path):
    sampler = TPEBOMSampler(history_path=tmp_path / "h.json")
    entry = _make_bom_entry(alternatives=[])
    bom = _make_bom(components=[entry])
    ladder = _make_ladder([bom])
    result = sampler.enrich_bom_candidates(ladder)
    enriched_entry = result.candidates[0].components[0]
    assert enriched_entry.alternatives == []

def test_enrich_bom_candidates_populates_alternatives_from_history(tmp_path):
    sampler = TPEBOMSampler(history_path=tmp_path / "h.json")
    for _ in range(4):
        sampler._history.append(BOMOutcome(
            design_id=str(uuid.uuid4()),
            component_type="ldo_regulator",
            specific_part="LT3080",
            erc_score=0.88,
        ))
    entry = _make_bom_entry(
        component_type="ldo_regulator",
        specific_part="TPS7A20DRVR",
        alternatives=[],
    )
    bom = _make_bom(components=[entry])
    ladder = _make_ladder([bom])
    result = sampler.enrich_bom_candidates(ladder)
    enriched_entry = result.candidates[0].components[0]
    assert "LT3080" in enriched_entry.alternatives

def test_enrich_bom_candidates_does_not_add_current_part_as_alternative(tmp_path):
    sampler = TPEBOMSampler(history_path=tmp_path / "h.json")
    for _ in range(4):
        sampler._history.append(BOMOutcome(
            design_id=str(uuid.uuid4()),
            component_type="ldo_regulator",
            specific_part="TPS7A20DRVR",
            erc_score=0.95,
        ))
    entry = _make_bom_entry(
        component_type="ldo_regulator",
        specific_part="TPS7A20DRVR",
        alternatives=[],
    )
    bom = _make_bom(components=[entry])
    ladder = _make_ladder([bom])
    result = sampler.enrich_bom_candidates(ladder)
    enriched_entry = result.candidates[0].components[0]
    assert "TPS7A20DRVR" not in enriched_entry.alternatives

def test_enrich_bom_candidates_never_raises(tmp_path):
    sampler = TPEBOMSampler(history_path=tmp_path / "h.json")
    sampler._history = None  # type: ignore
    ladder = _make_ladder([_make_bom()])
    result = sampler.enrich_bom_candidates(ladder)
    assert result is not None


# ── record_asha_outcome ───────────────────────────────────────────────────────

def test_record_asha_outcome_delegates_to_sampler(tmp_path):
    sampler = TPEBOMSampler(history_path=tmp_path / "h.json")
    bom = _make_bom()
    record_asha_outcome(sampler, bom, 0.95)
    assert sampler.total_outcomes == len(bom.components)


# ── clear_history ─────────────────────────────────────────────────────────────

def test_clear_history_resets_outcomes(tmp_path):
    path = tmp_path / "h.json"
    sampler = TPEBOMSampler(history_path=path)
    bom = _make_bom()
    sampler.record_outcome(bom, 0.90)
    sampler.clear_history()
    assert sampler.total_outcomes == 0
    assert not path.exists()

def test_clear_history_never_raises_when_no_file(tmp_path):
    sampler = TPEBOMSampler(history_path=tmp_path / "nonexistent.json")
    sampler.clear_history()


# ── component_types_observed ──────────────────────────────────────────────────

def test_component_types_observed_returns_unique_types(tmp_path):
    sampler = TPEBOMSampler(history_path=tmp_path / "h.json")
    for ctype in ["ldo_regulator", "capacitor", "ldo_regulator"]:
        sampler._history.append(BOMOutcome(
            design_id=str(uuid.uuid4()),
            component_type=ctype,
            specific_part="X",
            erc_score=0.9,
        ))
    types = sampler.component_types_observed
    assert len(types) == 2
    assert "ldo_regulator" in types
    assert "capacitor" in types


# ── imports ───────────────────────────────────────────────────────────────────

def test_tpe_sampler_importable_from_bom_package():
    from src.bom import TPEBOMSampler, record_asha_outcome, BOMOutcome, ComponentRanking
    assert callable(record_asha_outcome)
    assert TPEBOMSampler is not None
