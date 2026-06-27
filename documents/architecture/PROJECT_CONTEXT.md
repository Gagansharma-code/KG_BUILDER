# Open Forge — Project Context (Living Document)

> **Purpose:** Single attachable context file for Claude Projects, Cursor, and handoffs.
> **Update rule:** Edit this file at the end of every team milestone or phase completion (see §2).
> **Do not duplicate** the full architecture spec here — link to it.

---

## 1. Snapshot

| Field | Value |
|-------|-------|
| **Last updated** | 2026-06-26 |
| **Updated by** | Stage 05 search/storage/deployment implementation |
| **Current milestone** | Teams A–E gates implemented; **Stage 2 smoke-tested**; **Stage 3 retrieval + Stage 05 search/storage layer complete**; full E2E orchestrator + GPU eval deferred |
| **Active work** | KB Tier 0 KiCad library ingestion complete; Tier 3 community pipeline deferred; Search controller: ASHA + SA polisher + beam search escalation complete |
| **Repo root** | `open_forge/` (package: `openforge-pcb`) |
| **Code root** | `src/` (canonical); legacy P1 prototype at `prototypes/p1-parser/` |
| **Unit tests** | 699 passing (`pytest tests/unit -q`) — per commit 76b78d6 |
| **Retrieval gate tests** | 36 passing (`pytest tests/retrieval tests/db -q`) — Stage 3 + Stage 05 |

### Team dashboard

| Team | Subsystems | Gate | Status | Exit criteria met? |
|------|------------|------|--------|-------------------|
| **A** | Datasheet parser (P1, phases 1–5), scrapers | `eval/gates/team_a_gate.py` (7 checks) | ✅ Gate pass | Partial — GPU VLM eval deferred |
| **B** | Knowledge graph, pin normalizer (P2/P4) | `eval/gates/team_b_gate.py` (8 checks) | ✅ Gate pass | Yes — unit + gate |
| **C** | Intent parser, BOM generator (P5 prep) | `eval/gates/team_c_gate.py` (8 checks) | ✅ Gate pass | Yes — unit + gate |
| **D** | Schematic, layout, NIR builder (P5) | `eval/gates/team_d_gate.py` (8 checks) | ✅ Gate pass | Yes — unit + gate |
| **E** | KiCad + tscircuit output (P6) | `eval/gates/team_e_gate.py` (10 checks) | ✅ Gate pass | Yes — unit + gate |
| **F** | Schemas, platform, review CLI | `eval/gates/team_f_gate.py` (7 checks) | ✅ Gate pass | Yes — unit + gate |

**Legend:** ✅ Complete · 🟡 Implemented / partial · ⬜ Not started

### Infrastructure

| Deliverable | Status | Notes |
|-------------|--------|-------|
| `docker/Dockerfile` | ✅ | Python 3.11 + Poppler + Node 20 + `@tscircuit/cli` pre-cached |
| `docker/build_airgapped_image.sh` | ✅ | Builds and exports `openforge-pcb:airgapped.tar` |
| Full E2E orchestrator (prompt → fabrication files) | ⬜ | Team pipelines exist; top-level wiring pending |
| Improvement-plan docs | ✅ | `documents/improvement_plan/` (5 architecture decisions + tscircuit loopholes) |
| Stage 2 completion engine | 🟡 | `src/completion/` — smoke-tested on Entry 001; `tests/completion/smoke_test_real_prompts.py` 12/12 PASS |
| PostgreSQL KB schema | ✅ | `db/migrations/001_initial_schema.sql` — pgvector `VECTOR(4096)` for Qwen3 embeddings |
| Retrieval engine (Stage 3) | ✅ | `src/retrieval/` — 4-layer search + RRF fusion; gate tests in `tests/retrieval/` |
| Search/storage layer (Stage 05) | ✅ | Synonym expansion, coverage reporting, model pinning, deployment docs — see `documents/guides/stage_5_Search_storage.md` |
| Model version registry | ✅ | `config/model_versions.yaml` — pinned Qwen2.5-7B, Qwen3-Embedding-8B, Qwen2-VL, DocLayNet |
| Deployment docs | ✅ | `docs/DEPLOYMENT_NOTES.md`, `BACKUP_STRATEGY.md`, `MODEL_COMPATIBILITY_MATRIX.md` |
| vLLM config | ✅ | `config/vllm_config.yaml` — lab GPU deployment placeholder |

---

## 2. Milestone update protocol

When a team milestone or phase is **declared complete**, update the following sections in order:

1. **§1 Snapshot** — `Last updated`, `Current milestone`, `Active work`, team dashboard row
2. **§5 Team detail** — mark checklist items `[x]`, record measured metrics vs targets
3. **§6 Code inventory** — list new modules/files added
4. **§7 Model & corpus status** — if weights or corpus changed
5. **§9 Blockers** — remove resolved items; add new ones
6. **§11 Changelog** — one row: date, team/phase, summary

### Milestone sign-off checklist (copy per team/phase)

```markdown
### Team X / Phase N sign-off — YYYY-MM-DD
- [ ] All module files implemented per OPENFORGE_SUBSYSTEMS.md
- [ ] Unit tests pass (`pytest tests/unit`)
- [ ] Team gate passes (`python eval/gates/team_X_gate.py`)
- [ ] README.md status updated
- [ ] PROJECT_CONTEXT.md §1, §5, §6, §11 updated
- [ ] Eval reports updated (if applicable)
```

---

## 3. Mission & scope

**Open Forge** is an air-gapped, intelligence-driven PCB design system. Given a natural language prompt, it parses datasheets, queries an engineering knowledge graph, generates a validated BOM, synthesizes schematics, and exports KiCad and tscircuit fabrication files — with provenance on every value.

The six original problems (P1–P6) from `objectives.md` are sub-problems within the PCB Builder product:

| Problem | Role | Canonical code |
|---------|------|----------------|
| P1 — Datasheet parsing | Data ingestion → `ComponentDatasheet` JSON | `src/datasheet/` |
| P2 — Pin normalization | Cross-component net synthesis | `src/knowledge_graph/pin_normalizer/` |
| P3 — Block diagram CV | Reference topologies into KG-2 | Planned (Team A) |
| P4 — Knowledge graph | Authoritative engineering brain | `src/knowledge_graph/` |
| P5 — Connection synthesis | Schematic + layout + NIR | `src/schematic/`, `src/layout/`, `src/nir/` |
| P6 — KiCad / tscircuit export | Fabrication output | `src/output/` |

| In scope | Out of scope (v1) |
|----------|-------------------|
| Air-gapped / on-prem deployment | Cloud APIs (Gemini, etc.) |
| TI analog/power IC datasheets | MCUs, DSPs, FPGAs (254-page DSP archived) |
| KiCad + tscircuit dual export | Live KiCad MCP server integration |
| Human review queue for low-confidence items | Automated PCB fabrication ordering |

**Deployment:** Air-gapped. Model weights baked into Docker image; tscircuit CLI pre-cached in image layer.

---

## 4. Documentation authority

Read in this order when implementing:

| Priority | File | Role |
|----------|------|------|
| 1 | `documents/architecture/OPENFORGE_ARCHITECTURE.md` | **Master system design** |
| 2 | `documents/architecture/OPENFORGE_SUBSYSTEMS.md` | Subsystem specs (S1–S10) |
| 3 | `documents/architecture/OPENFORGE_INTEGRATION.md` | KiCad + tscircuit integration |
| 4 | `documents/architecture/PROJECT_CONTEXT.md` | **This file** — current status only |
| 5 | `documents/assessments/p1_assessment_filled.md` | Authoritative P1 schema, metrics, phased plan |
| 6 | `documents/improvement_plan/` | Next-step architectural decisions (intent schema, DB, retrieval) |
| 7 | `documents/guides/stage_5_Search_storage.md` | Stage 05 search/storage/deployment implementation spec |
| 8 | `documents/guides/CODING_STANDARDS_P1.md` | Code style, TDD, config patterns |
| 9 | `documents/objectives.md` | Six formal problem statements |

**Legacy P1 prototype:** `prototypes/p1-parser/` — golden corpus eval history; do not extend for new features.

**Index:** `documents/README.md`

---

## 5. Team detail

### Team A — Data Engineering (P1 Datasheet Parser) 🟡

**Gate:** 7/7 pass · **Pipeline:** `src/datasheet/pipeline.py` → `parse_datasheet()`

| Phase | Module path | Status |
|-------|-------------|--------|
| 1 DLA | `src/datasheet/phase1_dla/` | ✅ Implemented + tested |
| 2 TSR | `src/datasheet/phase2_tsr/` | ✅ Implemented (`vlm_enabled: false` on MacBook) |
| 3 Extract | `src/datasheet/phase3_extract/` | ✅ Implemented (rule-based; LLM stub optional) |
| 4 Validate | `src/datasheet/phase4_validate/` | ✅ Implemented |
| 5 Layout | `src/datasheet/phase5_layout/` | ✅ Implemented |

**Legacy prototype eval (5/5 golden PASS):** `prototypes/p1-parser/eval/phase1/PHASE1_RESULTS.md`

**Deferred exit metrics:**
- Phase 2 `cell_accuracy` / `merged_cell_accuracy` — needs grid-level golden GT
- Phase 3 `field_f1 ≥ 0.93` — needs `eval/phase3/` harness vs `*_ground_truth.json`
- GPU lab run with `vlm_enabled: true` and `llm_enabled: true`

---

### Team B — Knowledge Graph (P2/P4) ✅

| Module | Path | Status |
|--------|------|--------|
| Graph builder + query | `src/knowledge_graph/graph.py`, `query/` | ✅ |
| KG ingestion (AAC, app notes) | `src/knowledge_graph/ingestion/` | ✅ |
| P1 importer | `src/knowledge_graph/importers/p1_importer.py` | ✅ |
| Pin normalizer | `src/knowledge_graph/pin_normalizer/` | ✅ |
| Semantic search | `src/knowledge_graph/semantic_search.py` | ✅ |
| Admin CLI | `src/knowledge_graph/admin/` | ✅ |

---

### Team C — Intelligence Layer ✅

| Module | Path | Status |
|--------|------|--------|
| Intent parser | `src/intent/parser.py`, `pipeline.py` | ✅ |
| Methodology classifier | `src/intent/methodology_classifier.py` | ✅ |
| Ambiguity detector | `src/intent/ambiguity_detector.py` | ✅ |
| Requirement completion engine (Stage 2) | `src/completion/engine.py`, `axiom_loader.py`, `contradiction_checker.py` | 🟡 Smoke-tested |
| Retrieval engine (Stage 3 + 05) | `src/retrieval/` | ✅ Gate pass |
| BOM generator | `src/bom/generator.py`, `selector.py`, `validator.py` | ✅ |
| Supplier cache | `src/bom/supplier_cache.py` | ✅ |

**Stage 2 smoke test (2026-06-21):** Against Entry 001 Libbrecht-Hall prompt (`SCIENTIFIC_PROMPT_ANALYSIS_LOG.md` Entry 003), `run_completion_engine` correctly escalated `operating_environment` and `supply_voltage` dangerous assumptions to blocking `Ambiguity` entries and set `clarification_required=True`. Harness: `tests/completion/smoke_test_real_prompts.py` (12/12 PASS).

**Known gap:** `ImprovedIntentDict` v2 schema and Stage 2 not yet wired into the main intent pipeline — see `documents/improvement_plan/01_INTENT_PARSING_SCHEMA.md`, `02_REQUIREMENT_COMPLETION_ENGINE.md`.

**Retrieval engine (Stage 3 + Stage 05) — 2026-06-22:**

| Module | Path | Status |
|--------|------|--------|
| Retrieval orchestrator | `src/retrieval/engine.py` | ✅ |
| 4-layer search + RRF fusion | `src/retrieval/search_layers.py` | ✅ |
| Retrieval planner | `src/retrieval/planner.py` | ✅ |
| KB client (PostgreSQL) | `src/retrieval/kb_client.py` | ✅ |
| Query synonym expansion | `src/retrieval/query_expander.py`, `synonyms.yaml` | ✅ Stage 05 |
| Layer 1 coverage reporter | `src/retrieval/coverage_reporter.py` | ✅ Stage 05 |
| QA gate + freshness checker | `src/retrieval/qa_gate.py`, `freshness.py` | ✅ |

**Stage 05 changes:** Embedding dimension upgraded to 4096 (`Qwen/Qwen3-Embedding-8B`). Vector search applies query-side instruction prefix only; documents encoded without prefix. `RRF_K = 60` named constant. Coverage metrics surfaced in `retrieval_metadata.coverage_reports`.

**Gate:** `pytest tests/retrieval/test_retrieval.py tests/db/test_schema.py` — 36/36 PASS (mocked DB, no live PostgreSQL).

**Deferred:** Embedding ingestion pipeline (`INSERT INTO component_embeddings`), runtime Qwen3 model loading in `RetrievalEngine`, wiring retrieval into BOM/synthesis E2E flow. KG semantic search (`src/knowledge_graph/semantic_search.py`) remains separate MiniLM/FAISS stack.

**Guide:** `documents/guides/stage_5_Search_storage.md` · `documents/guides/atge_3_RetrievalKB_Engine.md`

---

### Team D — Circuit Synthesis (P5) ✅

| Module | Path | Status |
|--------|------|--------|
| Schematic synthesizer | `src/schematic/` | ✅ |
| Layout engine | `src/layout/` | ✅ |
| NIR builder + validator | `src/nir/` | ✅ |
| Synthesis orchestrator | `src/synthesis/pipeline.py` | ✅ |

**Contract:** `run_synthesis_pipeline(bom, datasheets, subgraph, config) → NIR` — never raises.

---

### Team E — Output & Integration (P6) ✅

| Module | Path | Status |
|--------|------|--------|
| tscircuit serializer | `src/output/tscircuit_serializer.py` | ✅ |
| KiCad serializer | `src/output/kicad_serializer.py` | ✅ |
| Footprint/symbol maps | `src/output/tscircuit_*_map.py`, `kicad_*_map.py` | ✅ |
| Design report | `src/output/doc_generator.py` | ✅ |
| Output orchestrator | `src/output/` (`run_output_pipeline`) | ✅ |

**Gate:** 10/10 pass · **Tests:** `test_tscircuit_serializer.py`, `test_kicad_serializer.py`, `test_output_pipeline.py`, `test_doc_generator.py`

**Reference:** `documents/improvement_plan/ts_circuit_architectural_loopholes.md`

---

### Team F — Platform & Schemas ✅

| Module | Path | Status |
|--------|------|--------|
| Core schemas | `src/schemas/` (datasheet, intent, kg, nir) | ✅ |
| Review queue + CLI | `src/review/queue.py`, `cli.py` | ✅ |
| Config | `src/config.py`, `configs/default.yaml` | ✅ |
| Team gates | `eval/gates/team_*_gate.py` | ✅ A–F |

---

## 6. Code inventory

### Canonical (`src/`)

```
src/
├── config.py
├── intent/                 # Team C — NL prompt → intent_dict
├── completion/             # Team C — Stage 2 requirement completion engine
├── retrieval/              # Team C — Stage 3 KB retrieval + Stage 05 search/storage
├── knowledge_graph/        # Team B — KG build, query, pin normalizer, ingestion
├── bom/                    # Team C — BOM generation and validation
├── datasheet/              # Team A — P1 parser (phases 1–5) + pipeline.py
├── schematic/              # Team D — schematic synthesis
├── layout/                 # Team D — layout spec generation
├── nir/                    # Team D — NIR builder + validator
├── synthesis/              # Team D — synthesis orchestrator
├── output/                 # Team E — KiCad + tscircuit serializers
├── review/                 # Team F — human review queue + CLI
└── schemas/                # Team F — Pydantic contracts (datasheet, intent, kg, nir)
```

### Tests (`tests/`)

```
tests/unit/                 # 699 tests across all teams
tests/retrieval/            # Stage 3 + Stage 05 retrieval gate tests (17 tests)
tests/db/                   # PostgreSQL schema gate tests (19 tests)
tests/completion/           # Stage 2 gate + smoke tests (Entry 001/002 prompts)
tests/integration/          # (placeholder)
eval/gates/                 # Team acceptance gates A–F
```

### Legacy prototype (`prototypes/p1-parser/`)

Archived standalone four-phase parser. Retained for:
- Golden corpus eval history (`eval/phase1/PHASE1_RESULTS.md`)
- Model download scripts (`scripts/download_models.py`)
- Spike results (`eval/spike/SPIKE_RESULTS.md`)

### Config & data

```
config/model_versions.yaml  # Pinned model registry (Stage 05)
config/vllm_config.yaml     # vLLM lab deployment config (Stage 05)
configs/default.yaml        # Canonical runtime config
configs/canonical_functions.yaml
configs/sources.yaml
db/migrations/              # PostgreSQL schema (pgvector VECTOR(4096))
docs/                       # Deployment notes, backup strategy, model matrix (Stage 05)
corpus/golden/              # 5 hand-verified TI PDFs + ground_truth JSON
data/                       # KG graph storage (gitignored runtime data)
docker/                     # Air-gapped deployment image
```

---

## 7. Model & corpus status

### Model weights

Canonical config paths in `configs/default.yaml`. Weights live under `models/` (gitignored) — download via legacy prototype script:

```bash
cd prototypes/p1-parser && python scripts/download_models.py --all
```

| Model | Role | Status |
|-------|------|--------|
| YOLOv8n-DocLayNet | Phase 1 DLA | ✅ Verified in prototype |
| Qwen2-VL-7B-Instruct | Phase 2 Path B (VLM) | ✅ Verified; GPU eval deferred |
| Qwen2.5-7B-Instruct | Phase 3 LLM + intent parser + Stage 2 | ✅ Verified; disabled on MacBook |
| Qwen/Qwen3-Embedding-8B (Q4, 4096-dim) | Layer 3 vector search | 🟡 Config pinned in `config/model_versions.yaml`; lab deployment pending |

**Model pinning:** All production model versions registered in `config/model_versions.yaml`. See `docs/MODEL_COMPATIBILITY_MATRIX.md` for cloud vs local delta and validation requirements.

### Golden corpus — 5/5 complete ✅

Promoted to repo root: `corpus/golden/`

| # | Component | Ground truth |
|---|-----------|--------------|
| 1 | TI_SN74LVC1G04 | `corpus/golden/TI_SN74LVC1G04_v1_ground_truth.json` |
| 2 | TI_TLV7021 | `corpus/golden/TI_TLV7021_v1_ground_truth.json` |
| 3 | TI_INA219 | `corpus/golden/TI_INA219_v1_ground_truth.json` |
| 4 | TI_LM5176 | `corpus/golden/TI_LM5176_v1_ground_truth.json` |
| 5 | TI_TPS62933 | `corpus/golden/TI_TPS62933_v1_ground_truth.json` |

**Archived:** `TI_TMS320F280039C` → out of P1 scope (DSP MCU).

### Test corpus — 0/25

`corpus/test/` empty. Curate 25 additional TI datasheets for corpus-scale E2E eval.

---

## 8. Architecture (pipeline)

High-level flow — full detail in `OPENFORGE_ARCHITECTURE.md`:

```
Natural Language Prompt
    → Intent Parser (Team C) → ImprovedIntentDict
    → Requirement Completion Engine — Stage 2 (Team C)  [halt if clarification_required]
    → Retrieval Engine — Stage 3 (Team C)  [4-layer KB search: parametric → FTS → vector → KG]
    → KG Query (Team B)
    → BOM Generator (Team C) ──[human review if confidence < 0.85]──
    → Datasheet Parser P1 phases 1–5 (Team A)
    → Pin Normalizer (Team B)
    → Schematic + Layout + NIR (Team D)
    → KiCad + tscircuit Export (Team E)
```

### Locked models (air-gapped)

| Phase | Model | Fallback |
|-------|-------|----------|
| 1 DLA | YOLOv8n-DocLayNet | Surya |
| 2 Path A | pdfplumber + Camelot lattice | — |
| 2 Path B | Qwen2-VL-7B-Instruct | LLaVA-1.6-34B |
| 3 Extract | Qwen2.5-7B-Instruct + Instructor | Rule-based grid parsers |
| Intent + Stage 2 | Qwen2.5-7B-Instruct + Instructor | — |
| Layer 3 vector search | Qwen3-Embedding-8B (4096-dim, Q4) | Sequential load on 24GB GPU |

---

## 9. Blockers & immediate next steps

### Blockers

1. **Full E2E orchestrator** — individual team pipelines exist; no single `prompt → files` entry point yet
2. **GPU lab verification** — Phase 2 VLM and Phase 3 LLM paths need GPU run with weights
3. **Grid-level golden GT** — required for Phase 2 cell/merged-cell accuracy exit gate
4. **Intent schema gap** — flat constraint strings block typed downstream reasoning (`improvement_plan/01`)
5. **Embedding ingestion** — `component_embeddings` schema ready (4096-dim); no writer pipeline yet; ANN index helper not wired
6. **Retrieval E2E wiring** — `RetrievalEngine` not yet connected to BOM/synthesis orchestrator

### Immediate next steps (ordered)

1. Wire top-level E2E orchestrator across Team C (intent → completion → retrieval) → A → B → D → E pipelines
2. Build embedding ingestion pipeline to populate `component_embeddings` with Qwen3-Embedding-8B
3. Run GPU lab eval: Phase 2 VLM + Phase 3 LLM + Qwen3 embedding model with golden corpus
4. Annotate grid-level golden GT for 5 components
5. Implement improvement-plan intent schema (`01_INTENT_PARSING_SCHEMA.md`)

---

## 10. Key paths

```
open_forge/
├── README.md
├── pyproject.toml                          # package: openforge-pcb
├── documents/
│   ├── architecture/
│   │   ├── PROJECT_CONTEXT.md              ← this file
│   │   ├── SCIENTIFIC_PROMPT_ANALYSIS_LOG.md  ← prompt gap + validation log
│   │   ├── OPENFORGE_ARCHITECTURE.md       ← master design
│   │   └── OPENFORGE_SUBSYSTEMS.md
│   ├── improvement_plan/                   ← next-step architecture decisions
│   └── assessments/p1_assessment_filled.md
├── config/                                 # Model registry + vLLM config (Stage 05)
├── docs/                                   # Deployment, backup, model compatibility (Stage 05)
├── db/migrations/                          # PostgreSQL + pgvector schema
├── src/                                    ← canonical codebase
├── tests/unit/
├── tests/retrieval/                        ← Stage 3 + Stage 05 gate tests
├── tests/db/                               ← schema gate tests
├── eval/gates/                             ← team acceptance gates
├── corpus/golden/
├── docker/                                 ← air-gapped image
└── prototypes/p1-parser/                   ← legacy P1 prototype (reference only)
```

### Quick commands

```bash
python3 -m venv venv && source venv/bin/activate
pip install -e .

pytest tests/unit -q
pytest tests/retrieval tests/db -q   # Stage 3 + Stage 05 retrieval gate
python eval/gates/team_a_gate.py   # repeat for b–f

# Air-gapped Docker build (requires network)
./docker/build_airgapped_image.sh

# Legacy P1 golden eval
cd prototypes/p1-parser && python eval/phase1/run_eval.py
```

---

## 11. Changelog

| Date | Team/Phase | Summary |
|------|------------|---------|
| 2026-06-27 | KB Scraping | Implemented KB scraping engine: NexarAdapter (GraphQL, batch-50), TIAdapter (CDN patterns), ADIAdapter (CDN patterns), stub adapters (ST/NXP/Infineon/Microchip), DigiKeyAdapter (API v4, category sweep + single-MPN fetch), RequestTracker (8,500/day budget cap), mpn_discovery (KiCad seed + DigiKey sweep, cap 100/category), pdf_downloader (streaming SHA-256 dedup, documents table), app_note_fetcher (static guided_app_notes manifest); population_runner (4-phase checkpoint/resume). |
| 2026-06-27 | Eval | Implemented search controller eval benchmark: 15 fixed design tasks (5 simple/medium/hard), BenchmarkTask schema, run_benchmark() with injected pipeline callable, Pass@1/Pass@N metrics, Markdown report generator. Tasks drawn from SCIENTIFIC_PROMPT_ANALYSIS_LOG (TASK_011/012/013/014) and canonical circuit types. Scorer uses structural verifier — no human-in-the-loop required. |
| 2026-06-26 | Search Controller / BOM | Implemented TPE BOM Sampler: cross-design component preference learning via empirical mean ERC scoring by (component_type, specific_part). Persists to data/bom_tpe_history.json. enrich_bom_candidates() populates BOMEntry.alternatives from history, enabling generate_bom_candidates() to produce meaningful variant BOMs. record_asha_outcome() integrates with search controller output. No Optuna dependency. |
| 2026-06-26 | Search Controller | Replaced LLM-guided MCTS escalation with width-3 beam search over programmatic repair moves. MCTS rejected after 8-point architectural debate (see MCTS_DECISION.md). Beam search uses same move types as SA polisher, maintains 3 parallel repair chains, max depth 4. No LLM inference consumed. |
| 2026-06-27 | P6 / Polisher | Programmatic SA graph polisher: `polish_schematic()` in `src/schematic/sa_polisher.py` — violation-guided `NetlistEntry` mutations, Metropolis acceptance, `verify_schematic` rescoring. Zero LLM tokens. Gate: `tests/unit/schematic/test_sa_polisher.py`. Activated when ASHA `hand_off_to_sa` is True. |
| 2026-06-27 | C / BOM | Multi-candidate BOM generation: `generate_bom_candidates()` and `BOMLadder` in `src/bom/candidates.py` (up to 3 ranked variants via alternative `specific_part` swap). Gate: `tests/unit/bom/test_bom_candidates.py`. Prerequisite for ASHA search controller (Prompt 5). |
| 2026-06-27 | P2 / Verifier | Structural verifier Layers 4-5 complete: VF2 topology signatures (`TOPOLOGY_TEMPLATES`, `expected_topologies` param) and power invariants (star ground, Kelvin sensing, AGND/DGND). Full 5-layer `verify_schematic()` ready for search controller. Gate: `tests/unit/schematic/test_structural_verifier.py`. |
| 2026-06-27 | P2 / Verifier | Structural verifier Layers 1-3: continuous scoring via `verify_schematic()` in `src/schematic/structural_verifier.py` (ERC wrap, pin-role compatibility, subcategory templates). Gate: `tests/unit/schematic/test_structural_verifier.py`. Layers 4-5 deferred to Prompt 3. |
| 2026-06-27 | P2 / Schema | Added `PinRole` enum, `CANONICAL_TO_ROLE` mapping, and additive `pin_role` field on `PinDefinition`; wired through pin normalizer and P1 importer. Gate: `tests/unit/schemas/test_pin_role.py`. Prerequisite for 5-layer structural verifier. |
| 2026-06-26 | KB / Tier 0 | Implemented KiCad s-expression parser (symbol_parser, footprint_parser, map_generator, batch_runner); auto-populates KICAD_SYMBOL_MAP and KICAD_FOOTPRINT_MAP from official KiCad repos; resolve_kicad_symbol() and resolve_kicad_footprint() now check generated JSON maps before hardcoded fallbacks |
| 2026-06-22 | C / Stage 05 | Search/storage/deployment layer implemented per `documents/guides/stage_5_Search_storage.md`: pgvector `VECTOR(4096)`, synonym expansion (`query_expander.py`, `synonyms.yaml`), Layer 1 coverage reporting, Qwen3 query-prefix vector search, `RRF_K=60`, model pinning (`config/model_versions.yaml`), vLLM config, deployment docs. Gate: `pytest tests/retrieval tests/db` 36/36 PASS. |
| 2026-06-21 | C | Stage 2 requirement completion engine smoke-tested against Entry 001 (Libbrecht-Hall). `operating_environment` and `supply_voltage` dangerous assumptions correctly escalated to blocking ambiguities; `clarification_required=True`. `tests/completion/smoke_test_real_prompts.py` 12/12 PASS. Logged in `SCIENTIFIC_PROMPT_ANALYSIS_LOG.md` Entry 003. |
| 2026-06-20 | E, F | Team E output pipeline complete (KiCad + tscircuit serializers, doc generator). Docker air-gap image added. 699 unit tests. Team E gate 10/10. |
| 2026-06-20 | E | tscircuit architectural loopholes documented. |
| 2026-06-19 | All | Repo consolidated: `openforge-pcb` at repo root; P1 prototype archived to `prototypes/p1-parser/`. Golden corpus promoted to `corpus/golden/`. Teams A–F code + gates bootstrapped. 654 unit tests; gates A–D pass. |
| 2026-06-19 | — | Improvement plans added (`documents/improvement_plan/`): intent schema, requirement engine, retrieval/KB, DB schema, search/storage deployment. |
| 2026-06-18 | — | Architectural revamp: OPENFORGE_*.md master docs; six-problem reframing as PCB Builder sub-problems. |
| 2026-06-13 | A (P1) | Legacy prototype Phase 1–4 implemented. Phase 1 golden eval 5/5 PASS. |
| 2026-06-12 | 0 | Golden corpus 5/5. Bootstrap + schemas. PROJECT_CONTEXT.md created. |

---

*When in doubt: implement against `OPENFORGE_ARCHITECTURE.md` and `OPENFORGE_SUBSYSTEMS.md`; report status here.*
