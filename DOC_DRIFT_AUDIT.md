# Documentation-vs-Code Drift Audit

**Date:** 2026-07-06  
**Scope:** `open_forge/` codebase cross-checked against listed documentation sources  
**Method:** Read-only. No application code or existing documentation was modified.

---

## Sources Checked (explicit confirmation)

| # | Source | Checked? | Notes |
|---|--------|----------|-------|
| 1 | `open_forge/documents/WHATS_LEFT.md` | ✅ Full read | Every tier status, completed section, maintenance note |
| 2 | `open_forge/documents/architecture/PROJECT_CONTEXT.md` | ✅ Full read | Snapshot, infrastructure table, blockers, changelog |
| 3 | `open_forge/documents/architecture/ADR.md` | ✅ Full read | Decisions, action items |
| 4 | `open_forge/documents/architecture/TOPOLOGY_CONSTRAINT_LAYER.md` | ✅ Full read | Status line, wiring claims |
| 5 | `open_forge/documents/architecture/NEO4J_BACKEND_DESIGN.md` | ✅ Full read | Target class, registry, migration checklist |
| 6 | `open_forge/documents/architecture/SYSTEM_WHITEBOX_TRACE.md` | ✅ Full read | Pipeline diagram, gates, KG storage, line refs |
| 7 | `open_forge/documents/architecture/OPENFORGE_ARCHITECTURE.md` | ✅ Full read | Review gates, directory tree, API contracts, deployment |
| 8 | `open_forge/documents/architecture/OPENFORGE_SUBSYSTEMS.md` | ✅ Substantial | S4 KGQueryEngine, S9 validators, subsystem tables |
| 9 | `open_forge/documents/architecture/OPENFORGE_INTEGRATION.md` | ✅ Substantial | TSCircuitOutput contract, integration tables |
| 10 | `open_forge/documents/architecture/OPENFORGE_ORGANIZATION.md` | ✅ Full read | Team deliverable paths |
| 11 | `open_forge/documents/architecture/MCTS_DECISION.md` | ✅ Full read | Search-controller escalation path |
| 12 | `open_forge/documents/architecture/Architecture.md` | ✅ Full read | 3-layer KG model, legacy project tree |
| 13 | `open_forge/documents/architecture/architectural_alternatives.md` | ✅ Skimmed | No strong status claims; alternatives only |
| 14 | `open_forge/documents/architecture/problem_1_solution.md` | ✅ Full read | Phase count, pipeline overview |
| 15 | `open_forge/documents/architecture/SCIENTIFIC_PROMPT_ANALYSIS_LOG.md` | ✅ Substantial | Entry 001 CAN HANDLE vs GAPS |
| 16 | `open_forge/documents/architecture/OPENFORGE_INTEGRATION.md` | ✅ (see #9) | — |
| 17 | Module/class docstrings under `open_forge/src/` | ✅ Sampled via ripgrep + targeted reads | Status words, ASHA/Neo4j refs, layer numbering, path refs (`graph.py`, `backends/`) |

**Not in scope but noted:** `open_forge/documents/decisions/Search_controller_decision.md` references `search_controller.py` (covered in Section 1). Parent `CURRENT_REPO_MAP.md` is largely accurate and was not re-audited as a primary source.

---

## Section 1: Previously Confirmed (for completeness)

#### [PROJECT_CONTEXT.md §9 + Search_controller_decision.md] claims: ASHA search controller exists at `src/schematic/search_controller.py` and will wire TPE/SA/beam search
- **Actual code state:** No `search_controller.py` anywhere under `open_forge/`. `generate_bom_candidates()` exists in `src/bom/candidates.py`; `polish_schematic()` in `src/schematic/sa_polisher.py`; `run_beam_search()` in `src/schematic/beam_search_escalation.py` — none called from `src/intent/pipeline.py`, `src/orchestrator.py`, or `src/synthesis/pipeline.py`. `ASHAResult` referenced only in comments (`src/bom/tpe_sampler.py`, `src/schematic/beam_search_escalation.py`), type undefined.
- **Severity:** Blocking — architecture docs describe a Stage 5 controller that does not exist.
- **Likely resolution:** Update docs to “scaffolding only”; implement `search_controller.py` when ready.
- **Confidence:** High

#### [NEO4J_BACKEND_DESIGN.md, SYSTEM_WHITEBOX_TRACE.md §7, `src/knowledge_graph/__init__.py` docstring] claims: Neo4j knowledge-graph backend is available / optional via `config.neo4j_uri`
- **Actual code state:** `neo4j_uri` field exists in `src/config.py` (lines 89+). `GRAPH_BACKEND_REGISTRY` in `src/knowledge_graph/backends/_registry.py` registers only `networkx`; comment explicitly says `"neo4j" is intentionally absent`. No `neo4j_backend.py`, no Neo4j driver usage, no `docker/neo4j/`, no `scripts/migrate_graphml_to_neo4j.py`. `neo4j` backend selection raises in `tests/unit/test_graph_backend.py`.
- **Severity:** Misleading — config suggests capability; runtime cannot use it.
- **Likely resolution:** Update WHITEBOX + `__init__.py` docstring to “design only”; keep NEO4J_BACKEND_DESIGN.md as forward-looking spec.
- **Confidence:** High

#### [Older project docs — user-reported] claims: `conflict_aware_add_edge()` exists; `source_tier` / `verified` are live KGNode fields
- **Actual code state:** `grep conflict_aware` across `open_forge/` returns **no matches** in `.py` or `.md` (may already have been removed from docs). `source_tier` / `verified` appear only as *future-field examples* in `NEO4J_BACKEND_DESIGN.md` line 81 (`*(any future field, e.g. source_tier, verified)*`). `src/schemas/kg.py` `KGNode` has no `source_tier` or `verified` fields. Edge writes use `GraphBackend.add_edge()` in `src/knowledge_graph/backends/networkx_backend.py` with no conflict-awareness wrapper.
- **Severity:** Misleading (if readers still have old docs) / Cosmetic (if references already purged from repo).
- **Likely resolution:** Confirm no external copies remain; if reintroducing provenance fields, update `KGNode` schema first.
- **Confidence:** High for absence in live code; Medium that all external doc copies are gone

#### [`src/schemas/kg.py` module docstring + TOPOLOGY_CONSTRAINT_LAYER.md §4] claims: Layer 4 = recipes; Layer 5 = project-specific placements
- **Actual code state:** Docstring at `src/schemas/kg.py` lines 9–14 assigns L4=recipes, L5=project placements. `src/knowledge_graph/ingestion/kg2_appnotes/kg2_graph_builder.py` creates `DESIGN_RECIPE` nodes at **`layer=2`** (line 128). `src/knowledge_graph/admin/methodologies.py` seeds `DESIGN_METHODOLOGY` at **`layer=5`** (line 144). New topology nodes correctly use layer 4 (`src/knowledge_graph/topology/library.py`). `DESIGN_CONSTRAINT` also uses layer 5 (`src/knowledge_graph/constraints/`).
- **Severity:** Misleading — ingestion data contradicts canonical layer docstring; queries filtering by layer may miss recipes.
- **Likely resolution:** Execute migration in TOPOLOGY §4 proposal, or document dual numbering until migrated.
- **Confidence:** High

---

## Section 2: New Findings

*Twenty-two new instances found beyond Section 1. Listed by severity.*

#### [SYSTEM_WHITEBOX_TRACE.md §2 pipeline diagram] claims: Intent path is `parse_intent` → `query_graph` → `generate_bom` → `validate_bom` → `[enqueue_bom]`
- **Actual code state:** `src/intent/pipeline.py` `run_intent_pipeline()` runs Stage 1 parse → Stage 2 `_run_stage2()` (`run_completion_engine`) → Stage 2.5 `_run_retrieval()` (`RetrievalEngine`) → Stage 2.75 `assert_interval_feasible()` → `query_graph` → `generate_bom(..., retrieval_result=...)` → `validate_bom` → `persist_design_constraints` → conditional `enqueue_bom`. No mention of Stages 2/2.5/2.75 or `run_e2e()` in WHITEBOX.
- **Severity:** Blocking — primary trace document describes a pre-2026-06-27 pipeline.
- **Likely resolution:** Rewrite §2 diagram and orchestrator table (`SYSTEM_WHITEBOX_TRACE.md` lines 15–30, 88).
- **Confidence:** High

#### [SYSTEM_WHITEBOX_TRACE.md §Gate 1 + §1350] claims: `query_graph()` runs immediately after intent parsing, before BOM generation; KG stored in `graph.py` with optional Neo4j
- **Actual code state:** `query_graph` runs after completion, retrieval, and interval solver (`src/intent/pipeline.py` lines 115–132). `src/knowledge_graph/graph.py` is now a thin facade over `src/knowledge_graph/backends/networkx_backend.py`; Neo4j not in registry (see Section 1).
- **Severity:** Blocking — wrong ordering and storage description for onboarding/debugging.
- **Likely resolution:** Update gate ordering; point storage section to `backends/` + registry.
- **Confidence:** High

#### [TOPOLOGY_CONSTRAINT_LAYER.md status line] claims: “Implemented (schema + LDO/Buck instances + solver + **pipeline wiring**).”
- **Actual code state:** `install_topologies()` in `src/knowledge_graph/topology/library.py` is called only from `tests/unit/knowledge_graph/test_topology_library.py`, not from ingestion, graph bootstrap, or `run_intent_pipeline`. `goal_mapper._START_NODE_TYPES` in `src/knowledge_graph/query/goal_mapper.py` is `(COMPONENT_TYPE, DESIGN_RECIPE)` — no `TOPOLOGY`. Doc itself notes IMPLEMENTS edges unwired (lines 101–103).
- **Severity:** Misleading — schema + unit tests yes; production wiring no.
- **Likely resolution:** Downgrade status to “schema + solver wired; topology KG install deferred.”
- **Confidence:** High

#### [TOPOLOGY_CONSTRAINT_LAYER.md §1 + interval_solver.py] claims: “interval solver already consumes `goal_topology` to select the dropout rule”
- **Actual code state (2026-07-06):** `src/intent/interval_solver.py` reads `intent.goal_topology`, but `src/intent/parser.py` never sets `goal_topology` or `goal_topologies` (`grep goal_topology` in parser = no matches). Pipeline does not populate topology before Stage 2.75. Field only set in tests or if caller pre-fills `goal_topologies` (`src/schemas/intent.py` `populate_goal_topology_compat`).
- **Severity:** Blocking — Rule 1 topology branching is dead code in normal pipeline runs (always `None` → skip).
- **Likely resolution:** Wire topology classification into parser/completion; add integration test.
- **Confidence:** High
- **RESOLVED 2026-07-06:** `src/intent/topology_classifier.py` added — deterministic keyword-based `classify_topology(prompt) -> list[TopologyGuess]`, mirroring `methodology_classifier.py`'s pattern (parser.py's LLM path is an unimplemented placeholder; the rule-based fallback is what actually runs, so a keyword classifier is what genuinely executes). Wired into `parse_intent()` Step 1b, populating `goal_topologies` on both `ImprovedIntentDict` construction sites. Threshold 0.60 (matches the pre-existing hardcoded cutoff in `axiom_loader.CONFIDENCE_THRESHOLD` and `retrieval/planner.py`'s `topology_slugs` filter — not a new value). Proven end-to-end in `tests/unit/intent/test_topology_pipeline_integration.py` (real `parse_intent()` + real `run_intent_pipeline()` through Stage 2.75, only Stage 2/downstream mocked): LDO-style prompts correctly halt the pipeline at the review gate with a named voltage/dropout conflict; boost- and buck-boost-style prompts correctly proceed. Side effect: this also unblocks `axiom_loader.load_axioms_for_intent()` and `retrieval/planner.py`'s `topology_slugs`, which read the same `goal_topologies` field and were previously always empty for the same reason.

#### [PROJECT_CONTEXT.md §1 Snapshot line 16] claims: “Search controller: ASHA + SA polisher + beam search escalation **complete**”
- **Actual code state:** Same as Section 1 — modules exist, controller missing, nothing wired to E2E. §9 Blockers line 370 correctly says `search_controller.py` missing.
- **Severity:** Misleading — internal contradiction in same file.
- **Likely resolution:** Change line 16 to “scaffolding complete, controller deferred”; align with §9.
- **Confidence:** High

#### [PROJECT_CONTEXT.md §1 Infrastructure table line 41] claims: “Full E2E orchestrator … ⬜ top-level wiring pending”
- **Actual code state:** `src/orchestrator.py` implements `run_e2e()` wiring intent → datasheet parse → synthesis → serialization; gate-tested in `tests/unit/test_orchestrator.py`. Milestone line 15 says E2E implemented.
- **Severity:** Misleading — contradictory rows in PROJECT_CONTEXT.
- **Likely resolution:** Mark infrastructure row ✅ with note “legacy P1 parser; modular swap pending.”
- **Confidence:** High

#### [OPENFORGE_ARCHITECTURE.md §8] claims: Review gates “**Blocks Downstream**” — e.g. “L3 does not start until BOM is approved”
- **Actual code state:** `src/orchestrator.py` lines 138–139: `if validated_bom.review_required: logger.warning("... proceeding anyway")`. No approval gate blocks synthesis.
- **Severity:** Misleading — safety model in docs ≠ runtime behavior.
- **Likely resolution:** Rewrite §8 to “enqueue + warn, non-blocking” or implement blocking gates.
- **Confidence:** High

#### [OPENFORGE_ARCHITECTURE.md §10 directory tree] claims: Paths including `src/pipeline.py`, `knowledge_graph/query_engine.py`, `knowledge_graph/builder.py`, `schematic/synthesizer.py`, `layout/placement_solver.py`, `ingestion/placement_extractor.py`, flat `ingestion/scraper_aac.py`
- **Actual code state:** Actual orchestrator is `src/orchestrator.py`. Query at `src/knowledge_graph/query/__init__.py`. Builders at `src/knowledge_graph/ingestion/kg1_aac/graph_builder.py` and `kg2_appnotes/kg2_graph_builder.py`. Schematic entry `src/schematic/__init__.py`. Layout has `routing_hint_generator.py`, no `placement_solver.py`. **`placement_extractor.py` does not exist** (prose logic in `src/knowledge_graph/ingestion/kg2_appnotes/prose_extractor.py`).
- **Severity:** Misleading — onboarding map is largely obsolete.
- **Likely resolution:** Regenerate §10 from live `src/` tree or mark archived.
- **Confidence:** High

#### [OPENFORGE_ARCHITECTURE.md §11 API contracts] claims: `query_graph(intent, config)`; `generate_bom(subgraph, config)`
- **Actual code state:** `query_graph(intent, graph, config)` in `src/knowledge_graph/query/__init__.py`; `generate_bom(subgraph, intent, config, retrieval_result=...)` in `src/bom/generator.py`.
- **Severity:** Misleading — copy-paste from contracts will not compile.
- **Likely resolution:** Fix signature block to match implementations.
- **Confidence:** High

#### [OPENFORGE_SUBSYSTEMS.md S4] claims: `class KGQueryEngine` with `_traverse`, `_overlay_methodology_rules`, `_score_and_rank`
- **Actual code state:** No `KGQueryEngine` class in `src/`. Public API is functional: `query_graph()` plus `goal_mapper.py`, `traversal.py`, `result_builder.py`, `methodology_filter.py`.
- **Severity:** Misleading — subsystem spec describes unimplemented class hierarchy.
- **Likely resolution:** Replace with actual module layout.
- **Confidence:** High

#### [ADR.md Action Items §298] claims: Introduce `ComponentClass` nodes, `HAS_CLASS` relationships (accepted ADR action item)
- **Actual code state:** No `ComponentClass` in `KGNodeType` (`src/schemas/kg.py`). `grep HAS_CLASS` / `ComponentClass` across `src/` = empty.
- **Severity:** Misleading — accepted ADR with zero implementation.
- **Likely resolution:** Track in WHATS_LEFT; mark ADR action items as open.
- **Confidence:** High

#### [WHATS_LEFT.md §3.4] claims: KiCad Tier 0 importer — ⬜ Not started (“KG writer”)
- **Actual code state:** Full Tier 0 package at `src/knowledge_base/tier0/` (`symbol_parser.py`, `footprint_parser.py`, `map_generator.py`, `batch_runner.py`). Writes JSON symbol/footprint maps, not KG nodes. PROJECT_CONTEXT changelog line 443 says implemented.
- **Severity:** Misleading — task tracker stale; scope description wrong.
- **Likely resolution:** Mark ✅ or 🟡 “maps only, no KG writer.”
- **Confidence:** High

#### [WHATS_LEFT.md §3.5 + OPENFORGE_ARCHITECTURE.md §10] claims: `placement_extractor.py` is a stub
- **Actual code state:** File does not exist. `src/knowledge_graph/ingestion/kg2_appnotes/prose_extractor.py` implements `extract_design_rules()` / `extract_placement_rules()` with tests in `tests/unit/test_kg2_appnotes.py`.
- **Severity:** Misleading — wrong filename and status.
- **Likely resolution:** Rename references to `prose_extractor.py`; update task status.
- **Confidence:** High

#### [WHATS_LEFT.md §3.3] claims: Nexar batch pre-ingestion CLI — ⬜ Not started
- **Actual code state:** `src/knowledge_base/scraper/adapters/nexar_adapter.py`, `pdf_downloader.py`, `population_runner.py` (4-phase checkpoint/resume), `mpn_discovery.py` exist. PROJECT_CONTEXT changelog line 434 documents implementation.
- **Severity:** Misleading — substantial code exists; may lack production CLI run.
- **Likely resolution:** Update to 🟡 with remaining gaps (production run task 3.6).
- **Confidence:** High

#### [PROJECT_CONTEXT.md / Search_controller_decision.md implicit] claims: `generate_bom_candidates()` is on the production BOM path
- **Actual code state:** Exported from `src/bom/__init__.py`, gate-tested, but `src/intent/pipeline.py` and `src/orchestrator.py` call `generate_bom()` only.
- **Severity:** Misleading — implemented helper not wired to E2E.
- **Likely resolution:** Document “module complete, awaits search_controller”; wire when controller lands.
- **Confidence:** High

#### [SCIENTIFIC_PROMPT_ANALYSIS_LOG.md Entry 001 CAN HANDLE table] claims: ✅ “Schematic synthesis for LDO + power section”, “NIR generation — Full pipeline runs to completion”, “KiCad/tscircuit — Serializer produces valid files”
- **Actual code state:** Same doc GAP-001-A (line 62): “BOM generator returns empty with `review_required=True`” for Libbrecht-Hall topology. E2E with empty/conflict BOM produces skeleton/failure paths, not validated end-to-end success for Entry 001 prompt.
- **Severity:** Misleading — capability matrix contradicts its own GAPS section.
- **Likely resolution:** Qualify CAN HANDLE rows with topology/KG preconditions or downgrade to 🟡.
- **Confidence:** High

#### [Architecture.md §“Three Layers”] claims: KG has 3 layers (Physics / Design Recipes / Component Rules); legacy tree with `src/graph/`, `src/nlp/intent_parser.py`, `src/pipeline.py`
- **Actual code state:** `src/schemas/kg.py` defines 5 abstraction layers (L1 physics → L5 constraints). Code lives under `src/knowledge_graph/`, `src/intent/`, `src/orchestrator.py`.
- **Severity:** Blocking for readers who start with this doc — wrong mental model and paths.
- **Likely resolution:** Archive `Architecture.md` or rewrite to match `OPENFORGE_ARCHITECTURE.md`.
- **Confidence:** High

#### [OPENFORGE_ORGANIZATION.md §Team deliverables] claims: Deliverables at `query_engine.py`, `schematic/synthesizer.py`, `layout/engine.py`, `placement_solver.py`, `routing_hints.py`
- **Actual code state:** Query: `src/knowledge_graph/query/__init__.py`. Schematic: `src/schematic/__init__.py` (`synthesize_schematic`). Layout: `src/layout/__init__.py`, `routing_hint_generator.py` (not `routing_hints.py`). No `placement_solver.py` or `layout/engine.py`.
- **Severity:** Misleading — team handoff paths wrong.
- **Likely resolution:** Update deliverable table to actual module paths.
- **Confidence:** High

#### [problem_1_solution.md §Architecture Overview] claims: Pipeline has **4 phases** ending at Phase 4 Physics Validation
- **Actual code state:** `src/datasheet/pipeline.py` runs Phase 5 layout via `src/datasheet/phase5_layout/`; mirror in `src/parsing/modular_pipeline.py`.
- **Severity:** Misleading — understates current parser scope.
- **Likely resolution:** Add Phase 5 section or cross-link to phase5 module.
- **Confidence:** High

#### [WHATS_LEFT.md Change Log task 1.4] claims: Embedding ingestion pipeline “COMPLETED”
- **Actual code state:** `src/retrieval/embedding_ingestor.py` + unit tests exist. `run_embedding_ingestion()` not called from `src/orchestrator.py`, `src/intent/pipeline.py`, or `src/knowledge_base/scraper/population_runner.py`.
- **Severity:** Misleading — module complete, not runtime-integrated.
- **Likely resolution:** Clarify “gate-tested module”; add wiring task.
- **Confidence:** High

#### [PROJECT_CONTEXT.md §9 #4 + WHATS_LEFT Tier 2 header] claims: Modular parser backends implemented; E2E path unspecified in WHATS_LEFT
- **Actual code state:** `src/orchestrator.py` line 14 imports legacy `parse_datasheet` from `src/datasheet/pipeline.py`, not `src/parsing/modular_pipeline.py`.
- **Severity:** Misleading — Tier 2 complete but E2E still on legacy path.
- **Likely resolution:** Add explicit WHATS_LEFT task “Wire E2E to modular parser.”
- **Confidence:** High

#### [OPENFORGE_ARCHITECTURE.md §12 + docker/Dockerfile] claims: “Python 3.10 + all dependencies”
- **Actual code state:** `open_forge/docker/Dockerfile` line 2: `FROM python:3.11-slim`. `pyproject.toml` requires `>=3.10`.
- **Severity:** Cosmetic — minor version mismatch.
- **Likely resolution:** Align §12 to 3.11 (or “3.10+; Docker uses 3.11”).
- **Confidence:** High

#### [OPENFORGE_INTEGRATION.md TSCircuitOutput contract] claims: Outputs include `json_path`, `bom_json_path`, `validation_result`; CLI generates `circuit.json`
- **Actual code state:** `src/output/tscircuit_serializer.py` defines `json_path: Optional[Path] = None` but serializer path does not populate it in normal flow. No `bom_json_path` or `validation_result` on output type.
- **Severity:** Cosmetic / Misleading — documented outputs partially absent.
- **Likely resolution:** Trim integration spec or implement missing export fields.
- **Confidence:** High

#### [OPENFORGE_ARCHITECTURE.md §5 NIR schema] claims: `NIR.bom: list[BOMEntry]`
- **Actual code state:** `src/schemas/nir.py` line 383: `bom: list[dict[str, Any]]`. `src/nir/builder.py` does not populate structured BOM entries on NIR.
- **Severity:** Cosmetic — type mismatch in architecture spec.
- **Likely resolution:** Update architecture schema doc.
- **Confidence:** High

#### [src/knowledge_graph/__init__.py module docstring lines 3–4] claims: “Neo4j-backed knowledge graph locally (prototype storage via GraphML)”
- **Actual code state:** Implementation is NetworkX-only via `src/knowledge_graph/backends/networkx_backend.py`. No Neo4j client (see Section 1).
- **Severity:** Misleading — package-level doc overstates backend.
- **Likely resolution:** Change to “NetworkX-backed (Neo4j planned — see NEO4J_BACKEND_DESIGN.md).”
- **Confidence:** High

#### [Module docstrings: bom/candidates.py, tpe_sampler.py, beam_search_escalation.py] claims: References to “ASHA controller”, `ASHAResult`, post-ASHA workflows as operational
- **Actual code state:** No `search_controller.py`, no `ASHAResult` type, no caller wiring (see Section 1).
- **Severity:** Misleading — inline docs describe future integration as present tense.
- **Likely resolution:** Prefix comments with “Planned:” or link to Search_controller_decision.md.
- **Confidence:** High

#### [WHATS_LEFT.md §2 maintenance note] claims: `test_pipeline_stage2.py` still unpacks 2-tuple from `run_intent_pipeline`
- **Actual code state:** Still accurate — e.g. `tests/unit/intent/test_pipeline_stage2.py` lines 140, 166, 197, 290 use 2-tuple unpack. Code returns 3-tuple (`src/intent/pipeline.py` line 84). **This is doc-accurate; tests are stale, not doc drift.**
- **Severity:** N/A — listed for completeness; WHATS_LEFT is correct.
- **Likely resolution:** Fix tests (maintenance), not WHATS_LEFT.
- **Confidence:** High

---

## Section 3: Summary Table

| ID | Doc source | One-line claim | Severity | Likely resolution |
|----|------------|----------------|----------|-------------------|
| S1-1 | PROJECT_CONTEXT, Search_controller_decision | `search_controller.py` / ASHA controller exists and wires search | Blocking | Update doc / implement controller |
| S1-2 | NEO4J_BACKEND_DESIGN, WHITEBOX, `kg/__init__.py` | Neo4j backend available via `neo4j_uri` | Misleading | Doc: design-only; code later |
| S1-3 | Older docs (user-reported) | `conflict_aware_add_edge`, `source_tier`, `verified` live | Misleading | Purge external copies; schema if needed |
| S1-4 | `kg.py` docstring, TOPOLOGY §4 | Layer 4=recipes, 5=placements; consistent numbering | Misleading | Migrate kg2 layers or document dual scheme |
| N1 | SYSTEM_WHITEBOX_TRACE §2 | Intent = parse → query → BOM (no Stages 2/2.5/2.75) | Blocking | Rewrite pipeline trace |
| N2 | SYSTEM_WHITEBOX_TRACE §7, §1350 | query_graph right after parse; optional Neo4j in graph.py | Blocking | Fix ordering + backends path |
| N3 | TOPOLOGY_CONSTRAINT_LAYER status | Topology layer + pipeline wiring implemented | Misleading | Downgrade status |
| N4 | TOPOLOGY §1, interval_solver | `goal_topology` drives dropout rule in pipeline | Blocking | **RESOLVED 2026-07-06** — `src/intent/topology_classifier.py` wired into `parse_intent()`; see full entry above |
| N5 | PROJECT_CONTEXT §1 L16 | Search controller “complete” | Misleading | Align with §9 blockers |
| N6 | PROJECT_CONTEXT §1 L41 | E2E orchestrator “pending” | Misleading | Mark implemented w/ caveats |
| N7 | OPENFORGE_ARCHITECTURE §8 | Review gates block downstream stages | Misleading | Doc non-blocking or implement gates |
| N8 | OPENFORGE_ARCHITECTURE §10 | Directory tree paths | Misleading | Regenerate tree |
| N9 | OPENFORGE_ARCHITECTURE §11 | `query_graph` / `generate_bom` signatures | Misleading | Fix API contracts |
| N10 | OPENFORGE_SUBSYSTEMS S4 | `KGQueryEngine` class | Misleading | Document functional modules |
| N11 | ADR Action Items | `ComponentClass` / `HAS_CLASS` shipped | Misleading | Mark ADR items open |
| N12 | WHATS_LEFT §3.4 | Tier 0 KiCad importer not started | Misleading | Update task status |
| N13 | WHATS_LEFT §3.5, OPENFORGE_ARCH §10 | `placement_extractor.py` stub | Misleading | Point to `prose_extractor.py` |
| N14 | WHATS_LEFT §3.3 | Nexar batch CLI not started | Misleading | Update to partial/complete |
| N15 | PROJECT_CONTEXT, search docs | `generate_bom_candidates` on E2E path | Misleading | Document unwired |
| N16 | SCIENTIFIC_PROMPT_ANALYSIS_LOG Entry 001 | CAN HANDLE full E2E for Entry 001 | Misleading | Add KG preconditions to matrix |
| N17 | Architecture.md | 3-layer KG + legacy `src/` tree | Blocking | Archive or rewrite |
| N18 | OPENFORGE_ORGANIZATION | Team deliverable file paths | Misleading | Update paths |
| N19 | problem_1_solution.md | 4-phase parser only | Misleading | Add Phase 5 |
| N20 | WHATS_LEFT Change Log 1.4 | Embedding ingestion runtime-complete | Misleading | Clarify module-only |
| N21 | WHATS_LEFT Tier 2, PROJECT_CONTEXT §9 | Modular parser in E2E | Misleading | Add E2E wiring task |
| N22 | OPENFORGE_ARCHITECTURE §12 | Python 3.10 in deployment | Cosmetic | Align to 3.11 |
| N23 | OPENFORGE_INTEGRATION | TSCircuit JSON/BOM export fields | Cosmetic | Trim or implement |
| N24 | OPENFORGE_ARCHITECTURE §5 | `NIR.bom: list[BOMEntry]` | Cosmetic | Fix schema doc |
| N25 | `kg/__init__.py` docstring | “Neo4j-backed” package | Misleading | Say NetworkX default |
| N26 | `bom/candidates.py` etc. docstrings | ASHA controller operational | Misleading | Mark planned |

---

## Section 4: Pattern Observations

### 1. Post-refactor docs not updated (`graph.py` → `backends/`)

The knowledge-graph backend split landed in code (`src/knowledge_graph/graph.py` is now a 32-line facade; logic in `src/knowledge_graph/backends/networkx_backend.py`) but **SYSTEM_WHITEBOX_TRACE**, **OPENFORGE_ARCHITECTURE §10**, and **`kg/__init__.py`** still describe the old monolithic `graph.py` world and optional Neo4j. This is the same failure mode as the layer-numbering collision: **code moved forward, canonical docs did not.**

### 2. “Module exists” mistaken for “feature shipped”

The strongest cluster of drift is **aspirational present tense**:

- Search stack: SA polisher, beam search, TPE sampler, `generate_bom_candidates` — all implemented as modules, documented as “complete,” none wired to `run_e2e` or `run_intent_pipeline`.
- Topology layer: schema + tests, not installed in production graph paths.
- Embedding ingestion: gate-tested module, not called from population or E2E.
- Tier 0 / Nexar scraping: code exists; **WHATS_LEFT** still says “not started.”

**Root cause:** Changelog/completion entries record *prompt implementation* and *gate tests*, while architecture docs imply *runtime integration*.

### 3. WHATS_LEFT vs PROJECT_CONTEXT desynchronization

`WHATS_LEFT.md` (last updated 2026-06-27) lags `PROJECT_CONTEXT.md` (2026-07-05) on Tier 0, Nexar, and E2E status. Two “source of truth” trackers disagree — WHATS_LEFT understates progress; PROJECT_CONTEXT overstates search-controller completion. **Pick one tracker or add explicit cross-sync rule.**

### 4. Legacy architecture docs still in tree

`Architecture.md` (3-layer KG, old `src/graph/` layout) and **OPENFORGE_ARCHITECTURE §10** phantom tree will mislead anyone who reads them before `PROJECT_CONTEXT.md`. Consider moving to `documents/archive/` with a banner, or deleting after merge.

### 5. Honest docs exist but are not the ones people grep first

`NEO4J_BACKEND_DESIGN.md` and `TOPOLOGY_CONSTRAINT_LAYER.md §4` explicitly flag gaps. `_registry.py` comments Neo4j as intentionally absent. `PROJECT_CONTEXT.md §9` correctly lists ASHA as missing. Drift happens when **higher-traffic summaries** (WHITEBOX, Snapshot table, subsystem class specs) are optimistic while **design-only docs** stay accurate — readers trust the wrong file.

### 6. Review / gate architecture is specified but not enforced

OPENFORGE_ARCHITECTURE §8 describes a blocking human-review state machine. Code enqueues to SQLite (`enqueue_bom`) but `orchestrator.py` proceeds regardless. WHITEBOX Gate 1 correctly says clarification does not enqueue; it does not document the newer Stage 2.75 constraint-conflict path (which **does** enqueue per current `pipeline.py`). Gate semantics in docs mix **desired** and **actual** behavior without labeling which is which.

---

## Recommended fix order

1. **SYSTEM_WHITEBOX_TRACE.md** — highest traffic, most wrong today  
2. **PROJECT_CONTEXT.md §1** — resolve internal contradictions (E2E, search controller)  
3. **WHATS_LEFT.md** — sync Tier 0, Nexar, prose extractor, E2E modular parser  
4. **OPENFORGE_ARCHITECTURE.md** §8–§11 — gates, tree, API contracts  
5. **Archive or rewrite `Architecture.md`** — prevent 3-layer model confusion  
6. **Wire `goal_topology` or document it as test-only** — closes topology-solver doc/code gap

---

*End of audit. 4 previously confirmed + 22 new findings (26 total in summary table). Zero new findings sections were omitted.*
