# OpenForge — What's Left

> **Last updated:** 2026-07-06
> **Updated by:** DOC_DRIFT_AUDIT.md remediation (synced against PROJECT_CONTEXT.md)
> **Rule:** Update this file whenever a task is completed, added, or reprioritised.
>            Every change must be recorded in the Change Log at the bottom.

---

## How to Use This File

- Tasks are grouped by priority tier
- Each task has a status: ⬜ Not started | 🟡 In progress | ✅ Done | 🚫 Blocked
- When you complete a task: mark ✅, move it to the Completed section, add a Change Log entry
- When you add a new task: add it to the correct tier, add a Change Log entry
- When priority changes: move it, add a Change Log entry

---

## Tier 1 — Critical Path (blocks E2E system from running)

All Tier 1 tasks complete. E2E orchestrator path is wired end-to-end.

---

## Tier 2 — Parsing System (modular backend)

Modular parser backends implemented and gate-tested. Remaining work is GPU validation and Phase 3 eval.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 2.1 | GPU lab validation — Phase 2 VLM + Phase 3 LLM with real weights | ⬜ Not started | vlm_enabled: true run on lab GPU |
| 2.2 | Phase 3 eval harness — field_f1 ≥ 0.93 gate on 5 golden datasheets | ⬜ Not started | Needs grid-level ground truth annotation |
| 2.10 | Fix native segfault: `pdfplumber`/`pypdfium2` + `ultralytics`/`torch` in-process | 🚫 Blocked | CRITICAL | Any real (non-mocked) run of `parse_datasheet()` | Confirmed 2026-07-06 on M3 Pro (Apple Silicon, no CUDA): importing `pdfplumber` before Phase 1 YOLO inference runs crashes the process with SIGSEGV, no Python exception, 100% reproducible. `pipeline.py` imports `phase2_tsr` (which imports `pdfplumber`) at module load, so this is unconditional for every MPN via `parse_datasheet()`/`pilot_ingest.py`. `KMP_DUPLICATE_LIB_OK=TRUE` does not fix it. Root cause not yet isolated beyond "native library conflict between pypdfium2's bundled PDFium and torch/ultralytics." Not attempted further per explicit instruction not to patch Phase 2/3 backend code without a fix plan. |
| 2.11 | Wire real rule-based Phase 3 extractor (exists, unintegrated) into `src/datasheet/phase3_extract/` | ⬜ Not started | HIGH | Any non-empty Phase 3 output from `parse_datasheet()` | `src/datasheet/phase3_extract/extractor.py`'s `extract_from_grid()` is a hardcoded placeholder — always returns 0 electrical params/pins/ratings + review flag `"LLM extraction not fully implemented"`, regardless of LLM availability. A real, working rule-based parser already exists at `prototypes/p1-parser/src/phase3_extract/` (`parameter_extractor.py`, `pinout_extractor.py`, `absolute_max_extractor.py`, `footnote_resolver.py`, `validation.py`) but was never ported into the production module tree the real pipeline calls. |

### Parser full-scope coverage (beyond analog/power ICs)

> Source: [parser_fullscope_gap_analysis.md](improvement_plan/parser_fullscope_gap_analysis.md)
> Baseline: TI analog/power ICs, tabular data, pinouts under ~30 pins.
> Target: MCU, digital IC, RF, sensor, power MOSFET, and related datasheet types.

| # | Task | Status | Severity | Blocks | Notes |
|---|------|--------|----------|--------|-------|
| 2.3 | Gap 1 — Large MCU pinout tables (chunking + AF columns) | ⬜ Not started | HIGH | MCU schematic synthesis | Pin table chunking, AF0–AF15 parser, >50-row heuristic in section classifier; `prompt_templates.py`, `extractor.py` |
| 2.4 | Gap 2 — Structured alternate-function / pin mux extraction | ⬜ Not started | HIGH | MCU net assignment | `PinDefinition` schema bump (`default_function`, `AlternateFunction`); P2 multi-function normalization; DB migration |
| 2.5 | Gap 3 — RF parameter units and section keywords | ⬜ Not started | MEDIUM | RF methodology BOMs | Add dBm, dBc, dB, ppm to `unit_normalizer.py`; RF keywords in `section_classifier.py`; RF prompt context |
| 2.6 | Gap 4 — Timing table vs timing diagram split | ⬜ Not started | MEDIUM | Clean MCU extraction | Phase 1 figure-vs-table split on TIMING regions; skip waveform figures to `review_flags`; Baidu OCR `type=figure` helps |
| 2.7 | Gap 5 — Thermal data for power devices | ⬜ Not started | MEDIUM | Thermal review flags | Thermal section keywords → extraction; θJA/θJC in Phase 3 prompt; `°C/W` in unit normalizer |
| 2.8 | Gap 6 — Connector mechanical data | 🚫 Out of scope | LOW | — | Footprint library lookup, not datasheet extraction |
| 2.9 | Gap 7 — FPGA datasheets | 🚫 Defer v2 | LOW | — | Bank-aware pin extraction + I/O standard tables; skeleton + `review_required=True` until then |

**Coverage gaps not yet in pipeline:** register maps (I2C/SPI sensors), dense timing tables on interface ICs, crystal frequency units (partial), large MCU pin counts (144+).

**Maintenance follow-up:** `tests/unit/intent/test_pipeline_stage2.py` still unpacks 2-tuple from `run_intent_pipeline` — update to triple after Tier 1.5.

---

## Tier 3 — Knowledge Base Population

These populate the KG. System can run without them but will produce poor BOMs.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 3.1 | Book parser (KG-1) — replace spaCy primary with LLM-primary triple extraction | ⬜ Not started | spaCy stays as sentence boundary only |
| 3.2 | Book parser (KG-1) — add chapter classifier to route formula-heavy chapters | ⬜ Not started | Keyword heuristic, no ML needed |
| 3.3 | Nexar batch pre-ingestion — GraphQL client + PDF downloader + checkpointed runner | 🟡 Implemented, not yet run | `src/knowledge_base/scraper/adapters/nexar_adapter.py`, `pdf_downloader.py`, `mpn_discovery.py`, `population_runner.py` (4-phase checkpoint/resume) all exist and are gate-tested. Remaining: task 3.6, a production run. |
| 3.4 | KiCad library file importer (Tier 0) | 🟡 Parser done, KG writer missing | `src/knowledge_base/tier0/` (`symbol_parser.py`, `footprint_parser.py`, `map_generator.py`, `batch_runner.py`) parses `.kicad_sym`/`.kicad_mod` and writes JSON symbol/footprint maps. **Does not write KG nodes** — no `kg3_writer.py` exists yet to convert those maps into `COMPONENT_INSTANCE`/`PIN` nodes. |
| 3.5 | App note prose extractor — placement rule extraction from app note text | ✅ Done | `src/knowledge_graph/ingestion/kg2_appnotes/prose_extractor.py` (not `placement_extractor.py` — that filename never existed) implements `extract_design_rules()` / `extract_placement_rules()`, tested in `tests/unit/test_kg2_appnotes.py`. |
| 3.6 | Run KB population — Nexar batch pre-ingestion on 10 priority components | ⬜ Not started | Depends on 3.3 (module ready, production run not yet executed) |
| 3.7 | Tier 0 → KG-3 writer — convert KiCad symbol/footprint maps into KG nodes | ⬜ Not started | New task, split out of 3.4 now that the parser side is confirmed done |
| 3.8 | Wire `install_topologies()` into graph bootstrap or a population phase | ⬜ Not started | `src/knowledge_graph/topology/library.py` exists, schema + unit-tested; not called from any ingestion path today. Zero `TOPOLOGY` nodes in a production graph until this runs. |
| 3.9 | Populate `intent.goal_topology` in the parser/completion engine | ✅ Done | `src/intent/topology_classifier.py` — deterministic keyword classifier (mirrors `methodology_classifier.py`), wired into `parse_intent()`. Threshold 0.60, matching the pre-existing hardcoded cutoff in `axiom_loader.py`/`retrieval/planner.py`. Proven end-to-end in `tests/unit/intent/test_topology_pipeline_integration.py`. Also unblocks `axiom_loader`/`retrieval` topology consumption, which read the same field. |
| 3.10 | Add `TOPOLOGY` to `goal_mapper._START_NODE_TYPES` | ⬜ Not started | Required before `query_graph()` can surface Topology/FunctionalBlock nodes even after 3.8 lands |

---

## Tier 4 — Quality and Evaluation

These improve accuracy. System runs without them but evaluation is incomplete.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 4.1 | Curate 25-datasheet test corpus in corpus/test/ | ⬜ Not started | Currently 0/25; should span component types in gap analysis matrix (not just analog/power) |
| 4.2 | Few-shot examples for Phase 3 extraction prompts | ⬜ Not started | See brainstorming/FEW_SHOT_PROMPT_ANALYSIS.md |
| 4.3 | Few-shot examples for Phase 5 layout extraction prompts | ⬜ Not started | Same doc |
| 4.4 | Pin normalizer LLM fallback few-shot examples | ⬜ Not started | Same doc |
| 4.5 | Calibrate Layout review-gate confidence threshold | ⬜ Not started | `src/orchestrator.py` uses `confidence_thresholds["layout_constraint"]` with fallback `0.85` as an unvalidated placeholder. Existing layout-specific precedent is only Phase 5 extraction acceptance at `0.65`; the `0.85` fallback is not grounded in layout data and must be tuned against real layout-review outcomes before being treated as authoritative. |

### Review-gate maintenance notes

- `review_queue.bom_json` and `review_queue.artifact_json` intentionally duplicate BOM snapshots for backward compatibility. `artifact_json` is the generic, authoritative multi-stage resume snapshot if the two fields ever disagree; `bom_json` is a BOM-only compatibility mirror kept for older queue rows and callers. Treat this as minor tech debt to remove after old queues no longer need migration support.

---

## Tier 5 — Research Paper

| # | Task | Status | Notes |
|---|------|--------|-------|
| 5.1 | Write Section 1 — Introduction | ⬜ Not started | Target: DAC/DATE/ICCAD or NeurIPS/ICLR ML-for-Systems workshop |
| 5.2 | Write Section 2 — Related Work | ⬜ Not started | Start here, parallel with code |
| 5.3 | Design evaluation benchmark for paper | ⬜ Not started | Needs E2E system working |
| 5.4 | Run experiments and collect results | ⬜ Not started | Needs Tier 1 + Tier 2 complete |
| 5.5 | Write remaining sections + submit | ⬜ Not started | 4–6 page workshop format |

---

## Completed Tasks

Record every finished task here with date.

| Date | Task | Notes |
|------|------|-------|
| 2026-07-06 | `pilot_ingest.py` now respects `knowledge_graph.backend`; real 15-MPN pilot run blocked (not completed) | Switched active backend to `neo4j` in `configs/default.yaml` per direct instruction; found `scripts/pilot_ingest.py` hardcoded `KnowledgeGraph` (NetworkX) and never read the config backend selection at all, so the switch would have silently done nothing — fixed via `GraphBackendRegistry`, same pattern as `kg_snapshot.py`; 2 new tests, all 10 in `test_pilot_ingest.py` pass. Confirmed real: `models/yolov8_doclaynets.pt` placed at the path `Config` actually expects (was only present under `prototypes/p1-parser/models/`); Phase 1 DLA verified standalone on a real 68-page datasheet (104 table crops, ~15s, CPU). **Could not complete the real pilot run** — see Tier 2 task 2.10 (segfault) below. Also confirmed via Tier 2 task 2.11: Phase 3's real extraction is a hardcoded placeholder (not a documented-but-real rule-based fallback as assumed) — every parsed datasheet would get 0 extracted fields regardless of backend, even absent the segfault. `eval/run_eval.py` does not exist anywhere in the main repo (only `prototypes/p1-parser/eval/phase1|phase2/run_eval.py`, Phase 1/2 only, not corpus-scale E2E) — confirmed non-functional/aspirational as described in `PROJECT_CONTEXT.md`; no new permanent regression test corpus was added as a result (would have required fabricating fixtures from a run that never completed). |
| 2026-07-06 | Fixed live-untested `Neo4jGraphBackend` edge-reading bug; manual KG snapshot/restore | `_record_data()` was using the driver's `record.data()`, which flattens `Relationship` values into a lossy `(start_props, type, end_props)` tuple instead of the relationship's own properties — broke `get_edges_from`/`get_edges_to`/`save`/`stats` for every edge. Only surfaced by actually running `tests/integration/test_neo4j_backend.py` against a live container (previously only mock-tested); fixed by reading `dict(record)` directly. Added `scripts/kg_snapshot.py` / `scripts/kg_restore.py` for manual, on-demand snapshot/restore (GraphML always + Neo4j-native `neo4j-admin` dump when that backend is active), reusing `knowledge_version()`. Verified end-to-end against `neo4j:5.26.27-community`: snapshot, mutate, restore, confirmed data reverted. |
| 2026-07-06 | Multi-stage blocking review gates for BOM/Netlist/Layout/NIR | Generalized the review queue to stage-aware `artifact_json` snapshots and stage-aware approval/resume. Layout threshold `0.85` is explicitly tracked as an unvalidated placeholder pending real layout-review calibration; `bom_json` remains a compatibility mirror, with `artifact_json` authoritative. |
| 2026-07-06 | Topology classification wired into Stage 1 (task 3.9, closes DOC_DRIFT_AUDIT.md N4) | `src/intent/topology_classifier.py`; `intent.goal_topology` now actually populated in production, proven by real-pipeline integration tests |
| 2026-07-06 | Blocking human-review gate at orchestrator level | `src/orchestrator.py` `run_e2e()` halts (`status="pending_review"`) instead of warning-and-proceeding; `bom_json` snapshot column on `review_queue`; `approve-design`/`reject-design` CLI; `resume_after_review()` resumes from the persisted snapshot (never regenerates). Closed DOC_DRIFT_AUDIT.md finding N7. |
| 2026-07-06 | Stage 2.75 interval-constraint solver | `src/intent/interval_solver.py` — voltage/dropout chain + thermal budget rules; wired into `run_intent_pipeline()` before `query_graph()` and into `generate_bom_candidates()`; fails loudly with named conflicts. |
| 2026-07-06 | Topology + Constraint KG schema | New `KGNodeType` members (`TOPOLOGY`, `FUNCTIONAL_BLOCK`, `DESIGN_CONSTRAINT`), `KGRelation.IMPLEMENTS`/`CONSTRAINED_BY`, `KGNode.design_id`. LDO + Buck Converter formal topologies with parameterized `ScalingLaw` edges (`src/knowledge_graph/topology/`). Per-design persisted constraint nodes (`src/knowledge_graph/constraints/`). **Not yet wired into production graph paths — see Tier 3 tasks 3.8–3.10.** |
| 2026-07-06 | GraphBackend abstraction | `src/knowledge_graph/backends/` — `GraphBackend` interface, `NetworkXGraphBackend` (moved from monolithic `graph.py`), `GraphBackendRegistry`. `graph.py` is now a thin compat subclass. Neo4j backend is design-only (`NEO4J_BACKEND_DESIGN.md`) — no driver, no registry entry. |
| 2026-07-05 | Full documentation drift audit (`DOC_DRIFT_AUDIT.md`) | 26 findings across architecture docs vs. live code; this file and `PROJECT_CONTEXT.md` corrected per the audit's recommended fix order. |
| 2026-06-27 | RetrievalEngine wired into intent pipeline (task 1.5) | Stage 2.5 _run_retrieval; triple return; generate_bom stub kwarg; 8/8 gate tests |
| 2026-06-27 | Stage 2 wired into intent pipeline (task 1.3) | _run_stage2 + Gate 2 in run_intent_pipeline; 7/7 gate tests |
| 2026-06-27 | E2E orchestrator — src/orchestrator.py + 8/8 gate tests | run_e2e() wires Teams A–E; never raises |
| 2026-06-27 | PARSER_P1 — Backend interfaces + registry | Gate-tested in Cursor |
| 2026-06-27 | PARSER_P2 — YOLOv8 LayoutDetectorBackend | Gate-tested in Cursor |
| 2026-06-27 | PARSER_P3 — PaddleOCR ImageTableBackend | Gate-tested in Cursor |
| 2026-06-27 | PARSER_P4 — pdfplumber+Camelot VectorTableBackend | Gate-tested in Cursor |
| 2026-06-27 | PARSER_P5 — Qwen2-VL ImageTableBackend (swap proof) | Gate-tested in Cursor |
| 2026-06-27 | PARSER_P6 — Qwen2.5-7B LLMBackend | Gate-tested in Cursor |
| 2026-06-27 | PARSER_P7 — Modular pipeline orchestrator | Gate-tested in Cursor |
| 2026-06-27 | PARSER_P8 — PostgreSQL ComponentDatasheet writer | Gate-tested in Cursor |
| 2026-06-27 | Run PARSER_P1–P8 in Cursor (gate test each) | All 8 phases executed and gate-tested |
| 2026-06-27 | PARSER_P1 through P8 prompts written | All 8 prompts designed by Claude |
| 2026-06-27 | Modular parser backend architecture designed | BackendRegistry, 5 interfaces, plug-and-play config |
| 2026-06-26 | Stage 05 search/storage/deployment complete | Synonym expansion, coverage reporting, model pinning |
| 2026-06-26 | Retrieval engine (Stage 3) gate pass — 36/36 tests | RetrievalEngine built; not yet wired to BOM |
| 2026-06-21 | Stage 2 completion engine smoke-tested — 12/12 pass | Not yet wired into main intent pipeline |
| Prior | All team gates A–F passing — 699 unit tests | Teams A/B/C/D/E/F all gate-tested |
| Prior | 5/5 golden corpus Phase 1 eval — 100% recall/precision | YOLOv8 DLA validated |
| Prior | PARSING_SCOPE_AND_ARCHITECTURE.md written | Tiered parsing architecture decided |

---

## Change Log

Every change to this file must be recorded here.
Format: `YYYY-MM-DD | action | what changed | why`

| Date | Action | What | Why |
|------|--------|------|-----|
| 2026-07-06 | FIXED + BLOCKED | `scripts/pilot_ingest.py` backend wiring; added tasks 2.10 (segfault, CRITICAL) and 2.11 (Phase 3 placeholder, HIGH) | Attempted the first real (non-mocked) 15-datasheet pilot run on real hardware (M3 Pro). Fixed a genuine bug found along the way (pilot script ignored the configured KG backend). Investigation before the run surfaced that Phase 3 extraction is unimplemented placeholder code, not the documented rule-based fallback, and that `eval/run_eval.py` doesn't exist in the main repo. The run itself never completed: a reproducible, uncatchable SIGSEGV occurs the moment `pdfplumber` and `ultralytics`/`torch` are loaded in the same process, before any datasheet is parsed. Recorded as blocking findings rather than silently patched, since fixing Phase 2/3 backend code was explicitly out of scope for this task. |
| 2026-07-06 | FIXED + ADDED | `Neo4jGraphBackend._record_data()` edge-reading bug; `scripts/kg_snapshot.py` / `scripts/kg_restore.py` | The prior Neo4j backend task was only mock-tested; running it live for the first time (required first step of this task) surfaced a real bug masked by the live integration test's own broad `except Exception: pytest.skip(...)`. Fixed, then built manual KG version control (snapshot before risky ops like the ingestion pilot; restore on demand) on the now-verified backend. |
| 2026-07-06 | ADDED | Layout gate threshold calibration task and review-queue snapshot duplication note | Prevent `confidence_thresholds["layout_constraint"] = 0.85` and `bom_json`/`artifact_json` duplication from being mistaken for validated, undocumented behavior |
| 2026-07-06 | CORRECTED | Tasks 3.3/3.4/3.5 status vs. live code | DOC_DRIFT_AUDIT.md N12–N14: Nexar scraper and Tier 0 parser were implemented but marked "Not started"; prose extractor was done but referenced under a filename (`placement_extractor.py`) that never existed |
| 2026-07-06 | ADDED | Tasks 3.7–3.10 (Tier 0 KG writer, topology install/wiring, goal_topology population) | Split out of the drift audit's topology-wiring and Tier 0 findings (N4, N3) |
| 2026-07-06 | COMPLETED | Blocking review gate, Stage 2.75 interval solver, Topology/Constraint schema, GraphBackend abstraction | Landed since the 2026-06-27 update; this file had not been synced (DOC_DRIFT_AUDIT.md pattern #3, WHATS_LEFT vs PROJECT_CONTEXT desync) |
| 2026-06-27 | ADDED | Parser full-scope gaps 2.3–2.9 from gap analysis | Track MCU/RF/thermal coverage beyond analog/power baseline |
| 2026-06-27 | COMPLETED | RetrievalEngine BOM wiring (task 1.5) | tier_1.5_prompt implemented; 8/8 unit gate tests pass; orchestrator triple unpack |
| 2026-06-27 | COMPLETED | Embedding ingestion **module** (task 1.4) | `src/retrieval/embedding_ingestor.py` — `run_embedding_ingestion()` implemented, 10/10 unit gate tests pass. **Not called** from `src/orchestrator.py`, `src/intent/pipeline.py`, or `src/knowledge_base/scraper/population_runner.py` — gate-tested module only, not runtime-integrated (DOC_DRIFT_AUDIT.md N20). |
| 2026-06-27 | COMPLETED | Stage 2 intent pipeline wiring (task 1.3) | tier_1.3_prompt implemented; 7/7 unit gate tests pass |
| 2026-06-27 | COMPLETED | E2E orchestrator (task 1.2) — src/orchestrator.py | Tier 1 prompt implemented; 8/8 unit gate tests pass |
| 2026-06-27 | COMPLETED | PARSER_P1–P8 executed and gate-tested in Cursor | User confirmed all 8 parser phases done |
| 2026-06-27 | CREATED | Initial version of WHATS_LEFT.md | First creation during document reorganisation |
