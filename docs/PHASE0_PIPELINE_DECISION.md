# Phase 0a — Pipeline fork decision (recommendation)

**Status:** Recommendation only — neither pipeline has been deleted, merged, or deprecated.  
**Date:** 2026-07-17  
**Sources of truth:** `CURRENT_REPO_MAP.md`, `README.md`, `documents/parsing/PARSER_CURSOR_PROMPTS/`, git history, entry-point code.

---

## Recommendation

**Keep `src/datasheet/` as the upgrade target for Phases 1–5 of the parser upgrade.**  
Treat `src/parsing/` as a stalled parallel infrastructure layer: keep it, do not invest gap-fix extraction work there yet, and revisit cutover only after the modular path is wired into E2E / Team A gate and regains section classification parity.

**Do not merge or deprecate either tree in this phase.** Team decision required before Phase 1 code lands.

---

## Question 1 — Is `src/parsing/` actively developed or stalled?

### Evidence

| Signal | `src/datasheet/` | `src/parsing/` |
|--------|------------------|----------------|
| Git last touch (path) | `2026-06-19` — `e130709` *Consolidate openforge-pcb as repo root…* | `2026-06-27` — `30270f3` *Parsing infra built* |
| Commits touching path after introduction | Folder arrived in repo-root consolidation; no later path commits | **Exactly one** commit (`30270f3`) introduced the whole tree |
| Activity after `30270f3` | Production consumers keep evolving around `parse_datasheet` (orchestrator, pilot ingest, gates, docs) | **Zero** subsequent commits under `src/parsing/` despite many later repo commits (topology, Neo4j, KB, etc.) |
| README | Explicitly labels `datasheet/` as **“P1 parser (canonical — phases 1–5)”** | Not mentioned as canonical |
| `CURRENT_REPO_MAP.md` | “Primary orchestrator (legacy, used by E2E)” | “Modular orchestrator (BackendRegistry)” — alternate entry; E2E still on legacy |
| Cursor prompt intent (`PARSER_P7_ORCHESTRATOR.md`) | Left untouched by design | Built as a **parallel** entry point; “existing `pipeline.py` is NOT touched” |

### Verdict

`src/parsing/` is **stalled after a one-shot infrastructure drop** (2026-06-27). It is newer than the last `src/datasheet/` path commit, but there has been **no follow-on development** for ~3 weeks of active repo work. That is not “active development”; it is unfinished migration scaffolding with unit tests, not a live product path.

---

## Question 2 — Does `src/parsing/` produce a full `ComponentDatasheet` end to end?

### Evidence from `parse_datasheet_modular`

`src/parsing/modular_pipeline.py` **does** call all five logical phases and returns a `ComponentDatasheet`:

1. Phase 1 — `BackendRegistry` layout detector → `Phase1Output` / `TableCrop`s  
2. Phase 2 — vector + image table backends → `Phase2Output`  
3. Phase 3 — **delegates to** `src.datasheet.phase3_extract.process` (not `LLMBackend`)  
4. Phase 4 — `src.datasheet.phase4_validate.validate` / `apply_verdict`  
5. Phase 5 — `src.datasheet.phase5_layout.extract_layout_constraints` when layout sections exist  

So the **type contract is end-to-end**. Completeness of the *extraction product* is not:

| Gap vs canonical pipeline | Evidence |
|---------------------------|----------|
| No section classification in Phase 1 | Every modular `TableCrop` is hard-coded `TableSectionType.OTHER` (`modular_pipeline.py` ~line 83; `PARSER_P7` says Phase 3 LLM should classify — not implemented) |
| Phase 5 often skipped | `_has_layout_sections()` looks for `LAYOUT_RECOMMENDATIONS`; modular path never sets that, so layout extraction is usually skipped |
| Figures discarded | Phase 1 keeps only `region_type in ("table", "caption")` — `"figure"` regions are dropped |
| Footnotes deferred | `footnote_maps=[]` always; prompt/docs say linkage deferred |
| LLMBackend unused for datasheets | `_run_phase3` explicitly `del registry` and calls Team A phase3 |
| Missing registered backends | `CURRENT_REPO_MAP.md`: `surya` layout + `qwen2_vl` VLM registered but files absent |

### Verdict

**Full orchestrator skeleton, partial Phase 1–2 semantics.** Output is a `ComponentDatasheet`, but quality/parity with `parse_datasheet` is incomplete. Semantic extraction still lives entirely in `src/datasheet/phase3_extract/`.

---

## Question 3 — Which pipeline does `eval/gates/team_a_gate.py` exercise?

### Evidence

`eval/gates/team_a_gate.py` imports and calls only:

- `src.datasheet.pipeline.parse_datasheet` / `DatasheetPipelineError`
- `src.datasheet.phase1_dla` … `phase5_layout`
- `src.datasheet.utils`

It also runs `mypy` on `src/datasheet/` and `src/review/` — **not** `src/parsing/`.

Production / ingest paths agree:

- `src/orchestrator.py` → `parse_datasheet`
- `scripts/pilot_ingest.py` → `parse_datasheet`
- Unit E2E mocks patch `src.orchestrator.parse_datasheet`

Modular coverage is limited to `tests/unit/parsing/test_modular_pipeline.py` (and backend unit tests).

### Verdict

**Team A gate exercises `src/datasheet/` only.**

---

## Question 4 — Where are gap-analysis fixes cheaper?

Gap work from the planning docs: pin-table chunking, RF units, thermal routing, figure/application-circuit extraction, AF schema population.

| Fix | Already lives in | Why cheaper on `src/datasheet/` | When `src/parsing/` would help later |
|-----|------------------|----------------------------------|--------------------------------------|
| Pin chunking (Gap 1) | `phase3_extract/extractor.py` | Shared by both entry points today; only one place to edit | No advantage |
| RF units (Gap 3) | `phase3_extract/unit_normalizer.py` + `section_classifier.py` | Canonical classifier + prompts already wired | Modular skips classifier → RF keywords would not fire until classification is ported |
| Thermal (Gap 5) | Same classifier + prompts | Same as RF | Same classifier gap |
| AF extraction (Gap 2) | Phase 3 prompts/extractor + schema | Schema is shared; population code is Team A phase3 | No advantage |
| Figure / app-circuit (Diagram doc) | Needs region typing + caption/adjacent text | Canonical DLA already has DocLayNet classes; Phase 5 NLP path exists | Modular already models `region_type` including `"figure"` / `"caption"` and has PaddleOCR — **better substrate for figure work once cutover is real** |

### Cost argument

Building gap fixes into `src/parsing/` first means either:

1. Duplicating classifier / multipage / phase5 behavior that modular currently stubs, **or**  
2. Still editing `src/datasheet/phase3_*` while also finishing modular Phase 1 parity — **two surfaces**.

Building into `src/datasheet/` means one production path, one gate, one E2E wire. Figure/OCR benefits of `src/parsing/` remain available as a **later cutover** (swap Phase 1–2 backends) without redoing Gaps 1–5 semantic work.

### Verdict

**Cheaper now: `src/datasheet/`.**  
Preserve `src/parsing/` for a future Phase 1–2 backend swap (especially figure-typed regions + PaddleOCR), after it is gated and has section-classification parity.

---

## Decision summary (for team sign-off)

| # | Question | Finding |
|---|----------|---------|
| 1 | Active vs stalled? | `src/parsing/` stalled after single 2026-06-27 commit |
| 2 | Full `ComponentDatasheet`? | Yes as type/orchestrator; no as semantic/classification parity |
| 3 | Team A gate? | `src/datasheet.pipeline.parse_datasheet` only |
| 4 | Cheapest gap-fix host? | `src/datasheet/` (shared phase3–5; production/gate path) |

**Recommended Phase 1+ target:** `src/datasheet/`  
**Recommended disposition of `src/parsing/`:** keep as alternate entry; no deprecation; no gap-fix investment until cutover criteria below.

### Suggested cutover criteria (future, not Phase 0)

1. `team_a_gate.py` (or a sibling gate) exercises `parse_datasheet_modular`  
2. Modular Phase 1 classifies sections (or reuses `section_classifier`)  
3. E2E / `pilot_ingest` switchable via config  
4. Golden corpus parity with `parse_datasheet` on the five (then ten) golden parts  

---

*End of Phase 0a recommendation.*
