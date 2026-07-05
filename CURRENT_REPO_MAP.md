# CURRENT_REPO_MAP.md

> Generated: 2026-07-05. Orientation reference for the DRDO workspace.
> Application code lives under `open_forge/`. Paths below are relative to the repo root (`DRDO/`).

---

## 1. Directory structure

| Path | Contents | Team mapping (when discoverable) |
|------|----------|----------------------------------|
| `AGENTS.md` | Spartan AI toolkit agent rules for this workspace | — |
| `.cursor/` | Cursor IDE rules (e.g. backend-micronaut conventions) | — |
| `.spartan-packs` | Spartan pack manifest | — |
| `open_forge/` | **Main OpenForge application** (Python package, tests, docs, eval) | All teams A–F |
| `open_forge/src/schemas/` | Shared Pydantic contracts | **Team F** |
| `open_forge/src/datasheet/` | P1 datasheet parser phases 1–5 + `pipeline.py` orchestrator | **Team A** |
| `open_forge/src/parsing/` | Modular P1 pipeline with pluggable backends + `BackendRegistry` | **Team A** (alternate entry) |
| `open_forge/src/knowledge_graph/` | KG storage, ingestion, query, pin normalizer, semantic search | **Team B** |
| `open_forge/src/knowledge_base/` | KB scrapers, Tier-0 KiCad library ingestion | **Team A** (data) / platform |
| `open_forge/src/intent/` | NL prompt → `ImprovedIntentDict` | **Team C** |
| `open_forge/src/completion/` | Stage 2 Requirement Completion Engine | **Team C** |
| `open_forge/src/retrieval/` | Stage 3 KB retrieval + search/storage layers | **Team C** |
| `open_forge/src/bom/` | BOM generation, validation, multi-candidate + TPE sampler | **Team C** |
| `open_forge/src/schematic/` | Schematic synthesis, ERC, structural verifier, SA polisher, beam search | **Team D** (synthesis) |
| `open_forge/src/layout/` | Layout spec generation | **Team D** |
| `open_forge/src/nir/` | NIR builder + validator | **Team D** |
| `open_forge/src/synthesis/` | Team D pipeline orchestrator (`run_synthesis_pipeline`) | **Team D** |
| `open_forge/src/output/` | KiCad + tscircuit serializers, design report | **Team E** |
| `open_forge/src/review/` | Human review queue + CLI | **Team F** |
| `open_forge/src/orchestrator.py` | E2E orchestrator (`run_e2e`) | Cross-team |
| `open_forge/tests/` | Pytest suite (unit, schema, completion, retrieval, db) | — |
| `open_forge/eval/gates/` | Team acceptance gate scripts A–F | Per team |
| `open_forge/eval/benchmarks/` | Benchmark runner + task schema | — |
| `open_forge/documents/` | Architecture, decisions, guides, improvement plans | — |
| `open_forge/config/` | Model version + vLLM config YAML | — |
| `open_forge/configs/` | Application default config (`default.yaml`) | — |
| `open_forge/corpus/` | Golden test corpus (`corpus/golden/`) | **Team A** |
| `open_forge/data/` | Runtime/domain data (`domain_knowledge/`, `graph/`, `raw/`) | — |
| `open_forge/db/` | DB schema validator + SQL migrations | Platform |
| `open_forge/docker/` | Docker / air-gap deployment assets | **Team F** |
| `open_forge/migrations/` | Flyway-style migration stubs | Platform |
| `open_forge/prototypes/` | Archived P1 prototype (`prototypes/p1-parser/`) | Legacy **Team A** |
| `open_forge/output/` | Runtime output directory (empty scaffold) | — |

---

## 2. Knowledge Graph implementation

### Storage backend

- **NetworkX (implemented):** `open_forge/src/knowledge_graph/graph.py` — class `KnowledgeGraph` wraps `networkx.DiGraph`. Nodes stored as `KGNode` under graph node attr `data`; edges as `KGEdge` under edge attr `data`. Supports GraphML save/load.
- **Neo4j (scaffolding only):** `neo4j_uri` field in `open_forge/src/config.py`; docstrings in `open_forge/src/schemas/kg.py`, `open_forge/src/knowledge_graph/graph.py`, and `open_forge/src/knowledge_graph/__init__.py` describe a Neo4j-backed production target. **No Neo4j driver/client code exists in `src/`.**

### Five conceptual layers (ADR / architecture naming)

| Layer | Concept | Primary modules | Node types / builders |
|-------|---------|-----------------|----------------------|
| Physics | Physics concepts | `open_forge/src/knowledge_graph/ingestion/kg1_aac/` (`graph_builder.py`, `__init__.py`) | `KGNodeType.PHYSICS_CONCEPT`, layer `1` |
| Design Recipes | Design patterns / circuits | `open_forge/src/knowledge_graph/ingestion/kg2_appnotes/kg2_graph_builder.py` | `KGNodeType.DESIGN_RECIPE`, layer `4` in builder |
| Component Rules | Component types, instances, electrical properties, pins | `open_forge/src/knowledge_graph/importers/p1_importer.py`; `open_forge/src/knowledge_graph/ingestion/kg2_appnotes/kg2_graph_builder.py` (component types) | `COMPONENT_TYPE` (layer 2), `COMPONENT_INSTANCE` (layer 3), `ELECTRICAL_PROPERTY`, `PIN` |
| Placement Rules | Proximity / keepout / layout | `open_forge/src/knowledge_graph/importers/p1_importer.py`; `open_forge/src/knowledge_graph/ingestion/kg2_appnotes/kg4_graph_builder.py` | `KGNodeType.PLACEMENT_RULE`, layer `4`; also `ROUTING_RULE` |
| Methodology Rules | Design methodology constraints | `open_forge/src/knowledge_graph/admin/methodologies.py`; `open_forge/src/knowledge_graph/query/methodology_filter.py` | `KGNodeType.DESIGN_METHODOLOGY`, layer `5` |

### Query / search API

- `open_forge/src/knowledge_graph/query/__init__.py` — **`query_graph(intent, graph, config) -> DesignSubgraph`** (primary Team C entry)
- `open_forge/src/knowledge_graph/semantic_search.py` — MiniLM + FAISS index over `COMPONENT_TYPE`, `COMPONENT_INSTANCE`, `DESIGN_RECIPE`
- `open_forge/src/knowledge_graph/validator.py` — graph consistency checks (orphaned edges, confidence bounds)

### Node / edge schema (Pydantic — canonical)

**File:** `open_forge/src/schemas/kg.py`

**Enums:**
- `KGNodeType`: `PHYSICS_CONCEPT`, `COMPONENT_TYPE`, `COMPONENT_INSTANCE`, `DESIGN_RECIPE`, `ELECTRICAL_PROPERTY`, `PLACEMENT_RULE`, `ROUTING_RULE`, `DESIGN_METHODOLOGY`, `NET_TYPE`, `STANDARD`, `PIN`
- `KGRelation`: `REQUIRES`, `USES`, `HAS_PROPERTY`, `CONNECTS_TO`, `MUST_BE_NEAR`, `MUST_AVOID`, `IS_A`, `GOVERNED_BY`, `REQUIRES_ROUTING`, `PART_OF`, `REPLACES`, `INCOMPATIBLE_WITH`, `OVERRIDES`

**Classes:**
- `KGNode` — fields: `id`, `node_type`, `layer` (1–5), `label`, `properties`, `source`, `confidence`, `extraction_method`, `created_at`
- `KGEdge` — fields: `source_id`, `relation`, `target_id`, `constraints`, `source_document`, `confidence`, `layer`
- `DesignSubgraph` — fields: `component_types`, `component_instances`, `design_rules`, `placement_rules`, `routing_hints`, `design_methodology`, `path_confidences`, `query_depth`, `query_metadata`
- `ComponentSearchResult` — fields: `node`, `similarity_score`, `matching_properties`

**Note:** `KGNode.layer` docstring maps layers 1–5 to physics → types → instances → recipes → projects, while ingestion code also labels subsystems KG-1, KG-2, KG-4 (see §10).

---

## 3. Pydantic schemas

### Core shared contracts (`open_forge/src/schemas/`)

| File | Classes |
|------|---------|
| `open_forge/src/schemas/intent.py` | `FrequencySpec`, `AmbiguityFlag`, `DesignMethodology` (enum), `PerformanceRequirements`, `VoltageSpec`, `CurrentSpec`, `ElectricalConstraints`, `ThermalConstraints`, `ManufacturingConstraints`, `ReliabilityRequirements`, `ComplianceRequirements`, `CostConstraints`, `ComponentPreference`, `ImprovedIntentDict`, `BOMEntry`, `ValidatedBOM` — alias `IntentDict = ImprovedIntentDict` |
| `open_forge/src/schemas/common.py` | `Ambiguity`, `NoiseSpec`, `AccuracySpec`, `StabilitySpec`, `ProductionVolume` (enum), `ImpliedRequirement`, `TopologyGuess`, `DesignRequest`, `OutOfScopeRequest` |
| `open_forge/src/schemas/kg.py` | `KGNodeType`, `KGRelation`, `KGNode`, `KGEdge`, `DesignSubgraph`, `ComponentSearchResult` |
| `open_forge/src/schemas/datasheet.py` | `ExtractedValue`, `ElectricalParameter`, `AbsoluteMaxRating`, `PinDefinition`, `PlacementConstraint`, `ComponentDatasheet` (+ enums `ExtractionMethod`, `PinRole`, `TableSectionType`, etc.) |
| `open_forge/src/schemas/nir.py` | `ComponentRef`, `PinRef`, `NetlistEntry`, `PlacementConstraint`, `RoutingHint`, `ComponentGroup`, `BoardSpec`, `ReviewFlag`, `NIR` |
| `open_forge/src/schemas/documents.py` | `IngestedDocument`, `KiCadPinDef` |

### Intent / completion / retrieval

| File | Classes |
|------|---------|
| `open_forge/src/completion/schemas.py` | `QuantifiedSpec`, `Contradiction`, `DangerousAssumption`, `RequirementCompletionResult` |
| `open_forge/src/retrieval/schemas.py` | `ComponentQuery`, `DocumentQuery`, `RetrievalPlan`, `ComponentCandidate`, `DocumentResult`, `RetrievalResult` |
| `open_forge/src/intent/parser.py` | `ParsedIntent` (LLM extraction intermediate) |

### BOM / search adjuncts

| File | Classes |
|------|---------|
| `open_forge/src/bom/candidates.py` | `BOMLadder` |
| `open_forge/src/bom/tpe_sampler.py` | `BOMOutcome`, `ComponentRanking` (dataclasses, not Pydantic) |

### KG ingestion / import adjuncts

| File | Classes |
|------|---------|
| `open_forge/src/knowledge_graph/ingestion/_schemas.py` | `Triple`, `IngestionResult`, `ScrapedChapter` |
| `open_forge/src/knowledge_graph/importers/_schemas.py` | `ImportResult`, `BatchImportResult` |

### Schematic / layout / output / review

| File | Classes |
|------|---------|
| `open_forge/src/schematic/_schemas.py` | `FunctionalBlock`, `ERCViolation`, `ERCResult`, `SchematicGraph` |
| `open_forge/src/layout/_schemas.py` | `LayoutSpec` |
| `open_forge/src/review/_schemas.py` | `ReviewQueueItem` |
| `open_forge/src/output/__init__.py` | `OutputResult` |
| `open_forge/src/output/kicad_serializer.py` | `KiCadOutput` |
| `open_forge/src/output/tscircuit_serializer.py` | `TSCircuitOutput` |
| `open_forge/src/output/kicad_symbol_map.py` | `KiCadSymbolRef` |
| `open_forge/src/orchestrator.py` | `E2EResult` |

### Parsing pipeline backends

| File | Classes |
|------|---------|
| `open_forge/src/parsing/backends/_schemas.py` | `BoundingBox`, `DetectedRegion`, `GridCell`, `GridMatrix`, `VLMResponse`, `LLMResponse`, `LayoutDetectorConfig`, `ImageTableConfig`, `VectorTableConfig`, `Qwen2VLConfig`, `LLMConfig`, `ParsingConfig` |
| `open_forge/src/datasheet/phase1_dla/_schemas.py` | `TableCrop`, `FootnoteMap`, `Phase1Output` |
| `open_forge/src/datasheet/phase2_tsr/_schemas.py` | `CellValue`, `GridMatrix`, `Phase2Output` |
| `open_forge/src/datasheet/phase5_layout/_schemas.py` | `LayoutExtractionResult`, `PageTextBlock` |

### Config / eval

| File | Classes |
|------|---------|
| `open_forge/src/config.py` | `Config` (`pydantic_settings.BaseSettings`) |
| `open_forge/eval/benchmarks/task_schema.py` | `BenchmarkTask`, `TaskResult`, `BenchmarkReport` |

---

## 4. Search controller

Documented design: `open_forge/documents/decisions/Search_controller_decision.md` (TPE → ASHA → SA → Beam Search).

| Component | File | Entry function / class | Status |
|-----------|------|------------------------|--------|
| TPE BOM Sampler | `open_forge/src/bom/tpe_sampler.py` | `TPEBOMSampler`, `TPEBOMSampler.enrich_bom_candidates()`, `record_asha_outcome()` | **Implemented** |
| Multi-candidate BOM | `open_forge/src/bom/candidates.py` | `generate_bom_candidates()` → `BOMLadder` | **Implemented** |
| ASHA Controller | `open_forge/src/schematic/search_controller.py` (documented) | — | **Not yet implemented** — file does not exist; `ASHAResult` referenced only in comments (`tpe_sampler.py`, `beam_search_escalation.py`) |
| Simulated Annealing polisher | `open_forge/src/schematic/sa_polisher.py` | `polish_schematic()` | **Implemented** (not wired into E2E) |
| Beam Search escalation | `open_forge/src/schematic/beam_search_escalation.py` | `run_beam_search()` | **Implemented** (not wired into E2E) |
| Structural scoring | `open_forge/src/schematic/structural_verifier.py` | `verify_schematic()` | **Implemented** |

**TPE history file:** `open_forge/data/bom_tpe_history.json` — path constant `DEFAULT_HISTORY_PATH` in `tpe_sampler.py`; file not present in repo (runtime/gitignored).

### Integration point (future hook)

> **Primary entry where a design candidate should enter the search stack:**
>
> `open_forge/src/bom/candidates.py` — **`generate_bom_candidates(subgraph, intent, config, ...) -> BOMLadder`**
>
> Intended flow (per decision doc, not fully wired):
> 1. `TPEBOMSampler.enrich_bom_candidates(ladder)` — Layer 0
> 2. **[missing]** ASHA controller evaluates each `ValidatedBOM` candidate via synthesis + `verify_schematic()`
> 3. `polish_schematic()` if score ∈ [0.80, 1.0)
> 4. `run_beam_search()` if score < 0.80
> 5. `record_asha_outcome(sampler, winner_bom, final_score)`
>
> **Current production paths bypass this stack entirely:**
> - `open_forge/src/intent/pipeline.py` → `generate_bom()` (single BOM, not `generate_bom_candidates()`)
> - `open_forge/src/orchestrator.py` → `run_e2e()` → `run_synthesis_pipeline()` → `synthesize_schematic()` with no search/refinement loop

---

## 5. Intent pipeline

| Stage | Location | Entry point | Notes |
|-------|----------|-------------|-------|
| Stage 1 — Intent parsing | `open_forge/src/intent/parser.py` | `parse_intent(prompt, config) -> ImprovedIntentDict` | Uses `ParsedIntent` for LLM path; rule-based fallback |
| ImprovedIntentDict v2 schema | `open_forge/src/schemas/intent.py` | class `ImprovedIntentDict` (`schema_version: "2.0"`) | Alias `IntentDict = ImprovedIntentDict` |
| Stage 2 — Requirement Completion | `open_forge/src/completion/engine.py` | `run_completion_engine(intent, config) -> ImprovedIntentDict` | Exported from `open_forge/src/completion/__init__.py` |
| Stage 2.5 — KB retrieval | `open_forge/src/retrieval/engine.py` | `RetrievalEngine.run_retrieval(intent) -> RetrievalResult` | Skipped when `config.database_url` absent |
| Orchestrator | `open_forge/src/intent/pipeline.py` | **`run_intent_pipeline(prompt, graph, config)`** | Returns `(IntentDict, ValidatedBOM, Optional[RetrievalResult])` |

**Connection to BOM / search:**
- `run_intent_pipeline` calls Stage 2 → Stage 2.5 → `query_graph()` → `generate_bom(subgraph, intent, config, retrieval_result=...)` → `validate_bom()`
- `generate_bom` accepts optional `RetrievalResult` from Stage 2.5 (`open_forge/src/bom/generator.py`)
- Search stack (`generate_bom_candidates`, TPE, ASHA, SA, beam) is **not** called from `run_intent_pipeline` or `run_e2e`

**Supporting intent modules:**
- `open_forge/src/intent/constraint_inferrer.py` — `infer_constraints()`
- `open_forge/src/intent/ambiguity_detector.py` — `detect_ambiguities()`
- `open_forge/src/intent/methodology_classifier.py` — `validate_methodology()`

---

## 6. Parsing pipeline (P1)

### Primary orchestrator (legacy, used by E2E)

**File:** `open_forge/src/datasheet/pipeline.py` — **`parse_datasheet(component_id, pdf_path, config) -> ComponentDatasheet`**

| Phase | Name | Location |
|-------|------|----------|
| 1 | Layout detection (DLA) | `open_forge/src/datasheet/phase1_dla/` — `process()` via `__init__.py` |
| 2 | Table extraction (TSR) | `open_forge/src/datasheet/phase2_tsr/` — `process()` |
| 3 | Semantic extraction | `open_forge/src/datasheet/phase3_extract/extractor.py` — `process()` |
| 4 | Validation / verdict | `open_forge/src/datasheet/phase4_validate/__init__.py` — `validate()`, `apply_verdict()` |
| 5 | Layout constraints | `open_forge/src/datasheet/phase5_layout/` — `extract_layout_constraints()` |

**Note:** Phase 4 performs generic datasheet validation (confidence, missing fields). There is **no module explicitly named "physics validation"** under `src/datasheet/`; physics-oriented checks are not implemented as a separate phase in code.

### Modular orchestrator (BackendRegistry)

**File:** `open_forge/src/parsing/modular_pipeline.py` — **`parse_datasheet_modular(component_id, pdf_path, config) -> ComponentDatasheet`**

Phases 1–2 route through `BackendRegistry`; phases 3 and 5 reuse Team A modules above.

### BackendRegistry abstraction

**File:** `open_forge/src/parsing/backends/_registry.py` — class **`BackendRegistry`**

| Registry constant | Config key | Implemented backends | Registered but missing |
|-------------------|------------|----------------------|------------------------|
| `LAYOUT_DETECTOR_REGISTRY` | `parsing.layout_detector` | `yolov8` → `open_forge/src/parsing/backends/layout/yolov8_backend.py` | `surya` → `surya_backend` (**file not present**) |
| `VECTOR_TABLE_REGISTRY` | `parsing.vector_table` | `pdfplumber_camelot` → `open_forge/src/parsing/backends/vector_table/pdfplumber_camelot_backend.py` | — |
| `IMAGE_TABLE_REGISTRY` | `parsing.image_table` | `paddleocr`, `qwen2_vl` | — |
| `VLM_REGISTRY` | `parsing.vlm` | — | `qwen2_vl` → `open_forge/src/parsing/backends/vlm/qwen2_vl_backend.py` (**directory not present**) |
| `LLM_REGISTRY` | `parsing.llm` | `qwen25_7b` → `open_forge/src/parsing/backends/llm/qwen25_backend.py` | — |

Interfaces: `open_forge/src/parsing/backends/_interfaces.py` — `LayoutDetectorBackend`, `VectorTableBackend`, `ImageTableBackend`, `VLMBackend`, `LLMBackend`.

**E2E wiring:** `open_forge/src/orchestrator.py` calls **`parse_datasheet`** (legacy), not `parse_datasheet_modular`.

---

## 7. Test suite structure

### Organization

| Directory | Scope |
|-----------|-------|
| `open_forge/tests/unit/` | Module-level unit tests (majority of suite) |
| `open_forge/tests/unit/intent/` | Intent pipeline stages |
| `open_forge/tests/unit/parsing/` | Modular parsing backends + pipeline |
| `open_forge/tests/unit/bom/` | BOM candidates, TPE sampler |
| `open_forge/tests/unit/schematic/` | Structural verifier, SA polisher, beam search |
| `open_forge/tests/unit/retrieval/` | Embedding ingestor |
| `open_forge/tests/unit/knowledge_base/` | Scraper, Tier-0 parsers |
| `open_forge/tests/unit/eval/` | Benchmark runner |
| `open_forge/tests/unit/schemas/` | Schema extension tests |
| `open_forge/tests/schema/` | Intent schema contract tests |
| `open_forge/tests/completion/` | Stage 2 engine + smoke tests |
| `open_forge/tests/retrieval/` | RetrievalEngine gate tests |
| `open_forge/tests/db/` | DB schema tests |
| `open_forge/eval/gates/` | Team acceptance gates (`team_a_gate.py` … `team_f_gate.py`) — runnable scripts, not pytest |

### Naming conventions

- Pytest files: `test_<module>.py` or `test_<feature>.py`
- Gate tests often annotated in docstrings: `"""Gate tests for …"""`
- Smoke test: `open_forge/tests/completion/smoke_test_real_prompts.py`

### Mocking external dependencies

- **`open_forge/tests/conftest.py`** — adds repo root to `sys.path` only (no fixtures)
- **DB / network mocking pattern:** `@patch.object(RetrievalEngine, "_route_to_review_queue")`, `MagicMock` KB client — see **`open_forge/tests/retrieval/test_retrieval.py`** (docstring: *"mocked DB, no live PostgreSQL"*)
- **E2E orchestrator mocking:** **`open_forge/tests/unit/test_orchestrator.py`** — `@patch` on `run_intent_pipeline`, `parse_datasheet`, `query_graph`, synthesis/output stages
- **Verifier / search subtests:** patch `verify_schematic` in `open_forge/tests/unit/schematic/test_sa_polisher.py` and `test_beam_search_escalation.py`

Tests are organized **by module/domain**, not by team letter — though gate scripts map to teams A–F.

---

## 8. Verification layer

### 5-layer structural verifier

**File:** `open_forge/src/schematic/structural_verifier.py`

| Layer | `VerifierLayer` enum | Implementation |
|-------|---------------------|----------------|
| 1 | `ELECTRICAL_INVARIANTS` | Delegates to `check_erc()` from `open_forge/src/schematic/erc.py` |
| 2 | `PIN_ROLE_COMPATIBILITY` | Pin role driver/receiver checks |
| 3 | `SUBCATEGORY_TEMPLATES` | BOM subcategory template matching |
| 4 | `TOPOLOGY_SIGNATURES` | **VF2 subgraph isomorphism** via `networkx.algorithms.isomorphism.vf2` against `TOPOLOGY_TEMPLATES` (hardcoded LDO, buck graphs) |
| 5 | `POWER_INVARIANTS` | Power net / rail invariant checks |

**Entry point:** **`verify_schematic(netlist, ref_map, bom=None, expected_topologies=None) -> VerificationResult`**

Supporting dataclasses (not Pydantic): `LayerViolation`, `LayerResult`, `VerificationResult`.

**Tests:** `open_forge/tests/unit/schematic/test_structural_verifier.py`

### ERC (Electrical Rules Check)

**File:** `open_forge/src/schematic/erc.py` — **`check_erc(netlist, ref_map) -> ERCResult`**

Rules list: `ERC_RULES = ["no_output_conflict", "power_net_has_source", "no_required_pin_floating", "no_logic_level_mismatch", "no_floating_inputs"]`

Schemas: `ERCViolation`, `ERCResult` in `open_forge/src/schematic/_schemas.py`

**Called from:** `synthesize_schematic()` in `open_forge/src/schematic/__init__.py` (production ERC during synthesis); also Layer 1 of structural verifier.

**Note:** Structural verifier docstring explicitly states it is *"Separate from src/schematic/erc.py — does not replace existing ERC."*

---

## 9. Existing usage of "topology," "constraint," and "recipe"

### topology

| Location | Usage |
|----------|-------|
| `open_forge/src/schemas/common.py` | `TopologyGuess` model; used in `ImprovedIntentDict.goal_topologies` |
| `open_forge/src/schemas/intent.py` | `goal_topology`, `goal_topologies`, `ElectricalConstraints.supply_topology` |
| `open_forge/src/schematic/structural_verifier.py` | `VerifierLayer.TOPOLOGY_SIGNATURES`, `TOPOLOGY_TEMPLATES`, `_build_topology_templates()`, VF2 topology matching |
| `open_forge/src/retrieval/planner.py` | `topology_slugs` derived from `goal_topologies` |
| `open_forge/src/retrieval/schemas.py` | `RetrievalPlan.topology_slugs` |
| `open_forge/src/retrieval/engine.py` | `get_design_pattern(slug)` loop over `topology_slugs` |
| `open_forge/src/retrieval/kb_client.py` | SQL column `topology_type`; `get_design_pattern(topology_type)` |
| `open_forge/src/retrieval/search_layers.py` | `kg_traversal(topology_slugs, kb)` |
| `open_forge/src/completion/axiom_loader.py` | Loads YAML axioms by topology slug; condition `goal_topology contains '…'` |
| `open_forge/src/completion/contradiction_checker.py` | `supply_topology` checks |
| `open_forge/src/completion/system_prompt.py` | "topology axioms", `by_topology` grouping |
| `open_forge/src/schemas/kg.py` | `KGRelation.REQUIRES_ROUTING` docstring ("routing topology"); `routing_hints` ("topology requirements") |
| `open_forge/src/knowledge_graph/ingestion/kg2_appnotes/kg2_graph_builder.py` | Keyword list includes `"topology"` for entity detection |

### constraint

| Location | Usage |
|----------|-------|
| `open_forge/src/schemas/datasheet.py` | `PlacementConstraint` model; `ComponentDatasheet.layout_constraints` |
| `open_forge/src/schemas/nir.py` | `PlacementConstraint`; `NIR.placement_constraints` |
| `open_forge/src/schemas/kg.py` | `KGEdge.constraints` dict; placement/routing rule semantics |
| `open_forge/src/schemas/intent.py` | `*Constraints` models (`ElectricalConstraints`, `ThermalConstraints`, etc.); `BOMEntry.constraints` |
| `open_forge/src/intent/parser.py` | `explicit_constraints`, `inferred_constraints`; `_typed_constraints_as_strings()` |
| `open_forge/src/intent/constraint_inferrer.py` | `infer_constraints()`, `APPLICATION_INFERENCES` |
| `open_forge/src/completion/schemas.py` | `Contradiction.constraint_a/constraint_b`; `ImpliedRequirement.source_constraint` |
| `open_forge/src/datasheet/phase5_layout/` | `constraint_validator.py`, `extract_layout_constraints()` |
| `open_forge/src/layout/constraint_collector.py` | Collects layout constraints into layout spec |
| `open_forge/src/knowledge_graph/importers/p1_importer.py` | Converts `PlacementConstraint` → `PLACEMENT_RULE` nodes |
| `open_forge/src/knowledge_graph/ingestion/kg2_appnotes/kg4_graph_builder.py` | `convert_placement_constraints_to_graph()` |
| `open_forge/src/knowledge_graph/admin/methodologies.py` | `active_constraint_types`, `suppressed_constraint_types` on methodology nodes |
| `open_forge/src/knowledge_graph/query/methodology_filter.py` | Filters placement rules by methodology constraint types |
| `open_forge/src/schematic/structural_verifier.py` | `constraints_checked`, `constraints_passed` on `LayerResult` |
| `open_forge/src/retrieval/embedding_ingestor.py` | Formats `PlacementConstraint` for embedding text |
| `open_forge/tests/schema/test_fix5_explicit_constraints.py` | Asserts removed `explicit_constraints` field on `ImprovedIntentDict` |

### recipe

| Location | Usage |
|----------|-------|
| `open_forge/src/schemas/kg.py` | `KGNodeType.DESIGN_RECIPE`; layer-4 "design recipes" in module docstring |
| `open_forge/src/schemas/documents.py` | `IngestedDocument.design_recipes_extracted` counter |
| `open_forge/src/schemas/nir.py` | `design_methodology` described as "methodology/recipe used" |
| `open_forge/src/knowledge_graph/ingestion/kg2_appnotes/kg2_graph_builder.py` | `_create_design_recipe_node()`, IDs `design_recipe:…` |
| `open_forge/src/knowledge_graph/ingestion/kg2_appnotes/__init__.py` | "KG-2 (design recipes)" ingestion pass |
| `open_forge/src/knowledge_graph/ingestion/kg2_appnotes/prose_extractor.py` | "Design rules → KG-2 (component types, recipes)" |
| `open_forge/src/knowledge_graph/semantic_search.py` | Indexes `DESIGN_RECIPE` nodes |
| Test/fixture strings | e.g. `"buck_regulator_recipe_v1"`, `"test_recipe_v1"` in output/NIR tests |

No formal **`TopologyGraph`** or **`ConstraintGraph`** classes exist in `src/` today (only ADR proposal terminology).

---

## 10. Known gaps or inconsistencies

1. **ASHA search controller missing:** `open_forge/documents/decisions/Search_controller_decision.md` and `PROJECT_CONTEXT.md` reference `open_forge/src/schematic/search_controller.py`. **File does not exist.** `ASHAResult` appears only in comments in `tpe_sampler.py` and `beam_search_escalation.py`.

2. **Search stack not wired to production pipelines:** `generate_bom_candidates`, `TPEBOMSampler`, `polish_schematic`, and `run_beam_search` are implemented and tested but **not imported or called** from `run_intent_pipeline`, `run_synthesis_pipeline`, or `run_e2e`.

3. **Documentation vs code on intent pipeline wiring:** Stale task tracker archived to `open_forge/documents/archive/restructure_docs.md`. **`open_forge/documents/architecture/PROJECT_CONTEXT.md`** had stale Stage 2 / retrieval / E2E gap text (updated 2026-07-05). `WHATS_LEFT.md` changelog (2026-06-27) aligns with wired code.

4. **KG layer numbering mismatch:**
   - ADR / architecture text: Physics, Design Recipes, Component Rules, Placement Rules, Methodology Rules
   - `KGNode.layer` docstring in `kg.py`: 1=physics, 2=types, 3=instances, 4=recipes, 5=**projects**
   - Ingestion code uses **KG-1, KG-2, KG-4** labels (skips KG-3 in app-note path); `p1_importer` uses **KG-3 / KG-4**
   - `DESIGN_METHODOLOGY` nodes use **layer 5** in `admin/methodologies.py`, overlapping the "projects" layer description

5. **Neo4j described but not implemented:** Multiple docstrings say "Neo4j-backed"; only NetworkX + GraphML + `neo4j_uri` config field exist.

6. **BackendRegistry registers missing backends:** `surya` layout detector and `qwen2_vl` VLM backend paths are registered in `_registry.py` but corresponding source files/directories are absent — selecting them in config would raise `ImportError`.

7. **Dual P1 entry points:** E2E uses legacy `parse_datasheet`; modular `parse_datasheet_modular` + `BackendRegistry` exist in parallel and are not the E2E default.

8. **Phase 4 "physics validation":** Architecture docs describe physics validation as P1 Phase 4; code implements generic validation in `phase4_validate` without physics-specific rules or naming.

9. **`explicit_constraints` removed from schema but linger in parser:** `ImprovedIntentDict` no longer has `explicit_constraints` (tests enforce this), but `ParsedIntent` and rule-based parser paths in `intent/parser.py` still construct/use `explicit_constraints` internally before mapping to typed v2 fields.

10. **E2E subgraph duplication:** `run_e2e` re-queries KG via `query_graph()` after `run_intent_pipeline` already queried internally — acknowledged in comment as acceptable duplication.

11. **`data/bom_tpe_history.json`:** Referenced as TPE persistence path; not committed (expected runtime artifact).

12. **Retrieval vs KG semantic search:** Two separate vector stacks — PostgreSQL KB retrieval (`open_forge/src/retrieval/`) vs MiniLM/FAISS KG semantic search (`open_forge/src/knowledge_graph/semantic_search.py`); not unified.

---

*End of map.*
