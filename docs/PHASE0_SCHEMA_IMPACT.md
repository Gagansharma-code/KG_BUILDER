# Phase 0b — Schema impact report (`phase0-schema-draft`)

**Branch:** `phase0-schema-draft`  
**Schema file:** `src/schemas/datasheet.py`  
**pipeline_version:** `1.0` → **`2.0`**  
**Status:** Draft for Team A / B / D (/ F schemas) sign-off — **not merged to main**.  
**Date:** 2026-07-17

This document lists every consumer that breaks or must be updated because of the Phase 0 schema draft. Extraction logic was **not** modified. Failures below were recorded by running the suite against this branch; known pre-existing / environment failures are called out separately so they are not mistaken for schema blast radius.

---

## Schema changes in this draft

1. **`AlternateFunction`** model (`name`, `af_index: Optional[int]`, `peripheral: Optional[str]`).
2. **`PinDefinition.alternate_functions`:** `list[str]` → `list[AlternateFunction]` (**breaking**).
3. **`PinDefinition.default_function: Optional[str]`** (reset-state function; additive).
4. **`ApplicationCircuitComponent`** model (exact fields from `Diagram_relevance_analysis.md`).
5. **`ComponentDatasheet`:** `application_circuit_components`, `thermal_pad_connect_to`, `thermal_via_count_recommended` (additive defaults).
6. **`pipeline_version` default** bumped to `"2.0"`.
7. **`TableSectionType`:** **no new enum value** (see decision below).

---

## TableSectionType decision (thermal)

### Options considered

| Option | Schema change | Downstream work |
|--------|---------------|-----------------|
| **A. Add `THERMAL_CHARACTERISTICS`** | New enum member | Classifier patterns + new Phase 3 prompt key + every exhaustive enum test/doc that says “7 types” |
| **B. Route thermal → `ELECTRICAL_CHARACTERISTICS`** (chosen) | None | Classifier keywords + thermal names inside existing electrical prompt (Phase 2 extraction work) |

### Blast radius if Option A were chosen (grep)

`TableSectionType` is referenced in **~25 source/test modules** (plus docs). High-touch switch sites:

| File | Role |
|------|------|
| `src/datasheet/phase1_dla/section_classifier.py` | `_SECTION_PATTERNS`; docstring “all 7” |
| `src/datasheet/phase3_extract/prompt_templates.py` | `PROMPT_TEMPLATES` dict — **must** add a prompt or thermal falls through inconsistently |
| `src/datasheet/phase3_extract/extractor.py` | Dominant section-type selection |
| `src/datasheet/pipeline.py` / `phase5_layout/` | Layout section checks (not thermal, but same enum surface) |
| `tests/unit/test_phase1_dla.py` | `test_classify_all_7_section_types` + many assertions |
| `tests/unit/test_schema_datasheet.py` | Enum value assertions |
| Parsing backends / modular pipeline | Mostly set `OTHER` today |

### Decision

**Do not add `THERMAL_CHARACTERISTICS`.** Route thermal / package-thermal tables to **`ELECTRICAL_CHARACTERISTICS`**.

**Why:** Gap doc allows either; thermal rows already fit `ElectricalParameter` (θJA etc. as named params). Option A expands the enum surface across classifier, prompts, and “all N types” tests for little semantic gain. Option B’s remaining work is keyword + prompt content only (no schema PR).

Documented on the enum in `datasheet.py` so later phases do not re-open this silently.

---

## Pytest results (this branch)

**Command:** `pytest tests/ -q --tb=line --no-cov`  
**Result:** `6 failed, 1243 passed, 1 skipped, 24 errors`

### Failures caused by this schema draft (must update before merge)

| Test | Failure | Why |
|------|---------|-----|
| `tests/unit/test_schema_datasheet.py::TestPinDefinition::test_valid_instantiation` | `ValidationError` on `alternate_functions=["UART_TX", "SPI_MOSI"]` | Expects `list[str]`; needs `AlternateFunction` instances/dicts |
| `tests/unit/test_schema_datasheet.py::TestComponentDatasheet::test_default_pipeline_version` | `assert '2.0' == '1.0'` | Default bumped to `2.0` |

### Failures / errors **not** attributed to this schema draft

| Symptom | Notes |
|---------|-------|
| `tests/unit/test_bom_generator.py` / `test_bom_validator.py` — 24× setup `ValidationError` on `ImprovedIntentDict.explicit_constraints` | Pre-existing intent schema drift; fixtures still pass removed field |
| `tests/unit/parsing/test_paddleocr_backend.py` (2) | Stubbed `cv2` in local env (`imdecode` missing) |
| `tests/unit/test_phase2_tsr.py::TestProcess::test_process_returns_phase2_output` | `processing_time_ms == 0.0` timing flake / env |
| `tests/unit/test_review_queue.py::TestListPending::test_list_pending_orders_by_created_at_desc` | UUID order assertion unrelated to datasheet schema |

### Tests that still pass but will need updates when AF data is non-empty

These construct `PinDefinition` / `ComponentDatasheet` with default empty `alternate_functions` today, so they did not fail. They still need Team review when structured AFs are populated:

- `tests/unit/test_phase3_extract.py`
- `tests/unit/test_pin_normalizer.py`
- `tests/unit/test_p1_importer.py`
- `tests/unit/test_schematic_synthesizer.py`
- `tests/unit/schematic/test_structural_verifier.py`
- `tests/unit/schemas/test_pin_role.py`
- `tests/unit/schemas/test_schema_extensions.py`
- `tests/unit/test_orchestrator.py` (fixture default `pipeline_version="1.0"` — still valid as explicit value)
- `tests/unit/retrieval/test_embedding_ingestor.py` (same)

---

## `eval/gates/team_a_gate.py`

**Result:** `FAIL (6/7)` — CHECK 7 mypy.

- Checks 1–6 **PASS** (imports, package normalize, Phase 5 empty, review queue, `DatasheetPipelineError`).
- CHECK 7 mypy fails on **pre-existing** errors in topology/intent/config/review/parsing paths; **no new error reported in `src/schemas/datasheet.py`**.
- Gate does **not** exercise the new AF / application-circuit fields yet.

---

## Impact by team (`CURRENT_REPO_MAP.md` ownership)

### Team F — Shared schemas (owner of `src/schemas/`)

| Item | Action |
|------|--------|
| `src/schemas/datasheet.py` | This PR — review + sign-off as contract owner |
| Consumers listed below | Coordinate version bump messaging (`pipeline_version=2.0`) |

### Team A — Datasheet parser / corpus / modular parsing

| File / artifact | Why it breaks or must change | Priority |
|-----------------|------------------------------|----------|
| `tests/unit/test_schema_datasheet.py` | **Fails now** — AF list[str] + pipeline_version default | Blocker |
| `src/datasheet/phase3_extract/prompt_templates.py` | `PINOUT_PROMPT` still documents `alternate_functions` as `list[str]`; must teach `AlternateFunction` + `default_function` before Gap 2 extraction | High (Phase 5 of upgrade plan) |
| `src/datasheet/phase3_extract/extractor.py` / `__init__.py` | Builds / checks `pin.alternate_functions`; LLM JSON with string lists will fail Pydantic validation once prompts change | High |
| `corpus/golden/TI_INA219_v1_ground_truth.json` | Non-empty `"alternate_functions": ["I2C_SDA"]` / `["I2C_SCL"]` — **invalid** under new type (empty `[]` elsewhere still OK) | High |
| Other golden files (`TI_TLV7021`, `TI_SN74LVC1G04`, …) | Empty AF arrays OK; may want `default_function` / new fields for forward compat | Medium |
| `corpus/golden/validate_ground_truth.py` | Validates against `ComponentDatasheet`; will reject INA219-shaped AF strings once that path loads pin models | High |
| `documents/parsing/PARSER_CURSOR_PROMPTS/PARSER_P8_POSTGRES_WRITER.md` | Example `alternate_functions=["GPIO", "SPI_CLK"]` stale | Docs |
| Thermal routing | **No schema change** — implement keywords → `ELECTRICAL_CHARACTERISTICS` in `section_classifier.py` in Phase 2 | Later |

**Do not change phase1–5 extraction in Phase 0** (already respected). Team A owns the follow-up prompt/extractor/corpus updates after sign-off.

### Team B — Knowledge graph / pin normalizer / P1 importer

| File / artifact | Why it must change | Priority |
|-----------------|--------------------|----------|
| `src/knowledge_graph/pin_normalizer/` (`normalizer.py`, `context_resolver.py`, related) | **Needs updating (implementation out of scope for this branch).** Today normalizes **one** `normalized_function` per pin from `raw_name` and **ignores** `alternate_functions` / `default_function`. Gap 2 requires normalizing **all** functions per pin without collapsing mux pins. Also should decide whether `default_function` vs `raw_name` is the primary normalization target. | High — sign-off blocker for Gap 2 |
| `src/knowledge_graph/importers/p1_importer.py` | Stores `"alternate_functions": pin.alternate_functions or []` on KG pin node properties. After schema change this becomes a list of models; GraphML/JSON properties need `model_dump()` (or name-only list) and eventually `default_function` | High |
| `tests/unit/test_pin_normalizer.py` | Passes with empty AFs; must gain multi-function cases once normalizer changes | High |
| `tests/unit/test_p1_importer.py` | Same — AF property shape assertions will need update when importer serializes structured AFs | High |
| `db/migrations/001_initial_schema.sql` (`pins.alternate_functions TEXT[]`) | Postgres column is `TEXT[]` (string array). Structured AF needs a migration (JSONB / side table) — **Platform + Team B** | High |
| `eval/gates/team_b_gate.py` | Builds `PinDefinition`s without AFs today; extend when multi-function behavior is gated | Medium |

### Team D — Schematic / NIR / synthesis

| File / artifact | Why it must change | Priority |
|-----------------|--------------------|----------|
| `src/schematic/net_assigner.py` | Uses `PinDefinition` / `normalized_function` for net grouping; does not read AFs today. When MCU pins carry many AFs, net assignment may need `default_function` or role from the chosen function — **review required**, likely code change in Gap 2+ | Medium |
| `src/schematic/passive_assigner.py` | Imports `PinDefinition`; additive fields OK; app-circuit passives may later interact with `application_circuit_components` | Low→Medium |
| NIR / layout consumers of `ComponentDatasheet` | Additive fields (`application_circuit_components`, thermal pad/via) are optional — safe at runtime until Team D wires them into BOM/schematic/layout | Medium (feature), Low (compat) |
| `tests/unit/test_schematic_synthesizer.py`, `tests/unit/schematic/test_structural_verifier.py` | Still pass; update when pin fixtures include structured AFs / `default_function` | Low |

### Platform / DB

| File | Why |
|------|-----|
| `db/migrations/` (new migration after `001_initial_schema.sql`) | Replace or augment `pins.alternate_functions TEXT[]`; add `default_function`; optionally columns for thermal pad / app-circuit tables |
| Any Postgres writer for P1 pins (see PARSER_P8) | Align with new JSON shape |

### Team C / E / F (other)

No direct pytest failures from this draft. Team C intent/BOM errors observed in the suite are **unrelated** (`explicit_constraints`). Team E serializers do not currently assert AF string lists.

---

## Sign-off checklist (before merge)

- [ ] Team F — schema contract + `pipeline_version=2.0`
- [ ] Team A — golden corpus AF shape + Phase 3 prompt/extractor plan (no extract code in this PR)
- [ ] Team B — pin_normalizer multi-function plan + `p1_importer` property serialization + DB migration plan
- [ ] Team D — ack additive app-circuit / thermal fields; pin mux impact on net assigner
- [ ] Confirm **no** `THERMAL_CHARACTERISTICS` enum (thermal → electrical)
- [ ] Re-run full pytest + `eval/gates/team_a_gate.py` after consumer updates
- [ ] **Do not merge** until sign-off; keep work on `phase0-schema-draft`

---

## Evidence commands used

```text
pytest tests/ -q --tb=line --no-cov
# → 6 failed, 1243 passed, 1 skipped, 24 errors
# Schema-attributed fails: test_schema_datasheet (AF + pipeline_version)

python eval/gates/team_a_gate.py
# → FAIL 6/7 (mypy CHECK 7; pre-existing errors; datasheet.py clean)
```

---

*End of Phase 0b impact report.*
