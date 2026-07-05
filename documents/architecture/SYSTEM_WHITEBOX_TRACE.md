# OpenForge PCB Intelligence System — White-Box Pipeline Trace

## SECTION 1 — TITLE AND OVERVIEW

This document traces every script, every function call, and every data transformation that occurs from the moment an engineer types a design prompt to the moment fabrication-ready PCB files are produced. All code paths, function names, field names, thresholds, and error behaviors shown below are taken directly from the implementation under `src/`. There is no single monolithic `src/pipeline.py`; the system is orchestrated through four team-level entry points that a caller wires in sequence: `src/intent/pipeline.py`, `src/datasheet/pipeline.py`, `src/knowledge_graph/pin_normalizer/__init__.py`, `src/synthesis/pipeline.py`, and `src/output/__init__.py`.

---

## SECTION 2 — THE COMPLETE PIPELINE AT A GLANCE

```
Engineer types: "design a 3.3V LDO regulator for an IoT sensor"
        │
        ▼
[STAGE 1] src/intent/parser.py → parse_intent(prompt, config)
        │ Output: IntentDict
        ▼
[STAGE 1b — optional block] IntentDict.clarification_required == True
        │ → pipeline stops; empty ValidatedBOM returned (no queue enqueue)
        ▼
[STAGE 1c] src/completion/__init__.py → run_completion_engine(intent, config)
        │ Output: ImprovedIntentDict (Stage 2 requirement completion)
        │ Failure: caught and logged, proceeds with Stage 1 output unchanged
        ▼
[STAGE 1d] src/retrieval/__init__.py → RetrievalEngine.run_retrieval(intent)
        │ Output: Optional[RetrievalResult] (Stage 2.5 KB retrieval)
        │ Skipped entirely if config.database_url is unset; never raises
        ▼
[STAGE 1e — HARD GATE] src/intent/interval_solver.py → assert_interval_feasible(intent)
        │ Stage 2.75 — deductive feasibility pre-check, runs BEFORE query_graph
        │ Raises ConstraintConflictError on infeasible constraints (e.g. dropout
        │ chain, thermal budget). Caught by run_intent_pipeline(); halts with an
        │ empty/flagged ValidatedBOM and calls enqueue_bom() — does not proceed
        │ to Stage 2.
        ▼
[STAGE 2] src/knowledge_graph/query/__init__.py → query_graph(intent, graph, config)
        │ Output: DesignSubgraph
        │ Runs AFTER Stages 1c/1d/1e — not immediately after Stage 1
        ▼
[STAGE 3] src/bom/generator.py → generate_bom(subgraph, intent, config, retrieval_result=...)
        │ Output: ValidatedBOM (pre-validation)
        ▼
[STAGE 4] src/bom/validator.py → validate_bom(bom, config)
        │ Output: ValidatedBOM (cross-component checks applied)
        ▼
[STAGE 4a] src/knowledge_graph/constraints/__init__.py → persist_design_constraints(intent, bom.design_id, graph)
        │ Writes DESIGN_CONSTRAINT nodes (layer 5) scoped to design_id — persisted
        │ provenance, never discarded, versioned against KG state at creation
        ▼
[STAGE 4b — REVIEW GATE, BLOCKING] src/review/queue.py → enqueue_bom(validated_bom, config)
        │ Fires when: ValidatedBOM.review_required == True
        │ Stage tag: "bom_generation"; stores full ValidatedBOM JSON snapshot
        │ src/orchestrator.py → run_e2e() HALTS HERE (status="pending_review")
        │ Resume only via src/orchestrator.py → resume_after_review(design_id, ...)
        │ after human approval — see SECTION 5, Gate 2
        ▼
[STAGE 5] src/datasheet/pipeline.py → parse_datasheet(component_id, pdf_path, config)
        │   (called once per BOMEntry.specific_part; not inside Team C/D orchestrators)
        │
        ├─ [5a] src/datasheet/phase1_dla/__init__.py → process(pdf_path, config)
        │         Output: Phase1Output
        ├─ [5b] src/datasheet/phase2_tsr/__init__.py → process(phase1_output, config)
        │         Output: Phase2Output
        ├─ [5c] src/datasheet/phase3_extract/__init__.py → process(phase2_output, config)
        │         Output: ComponentDatasheet (pre-verdict)
        ├─ [5d] src/datasheet/phase4_validate/__init__.py → validate() + apply_verdict()
        │         Output: ComponentDatasheet (review_required set)
        └─ [5e] src/datasheet/phase5_layout/__init__.py → extract_layout_constraints(...)
                  Output: list[PlacementConstraint] merged via model_copy
        │ Final output: ComponentDatasheet
        ▼
[STAGE 5b — REVIEW GATE] src/review/queue.py → enqueue(datasheet, validation_result, config)
        │ Fires when: ComponentDatasheet.review_required == True
        │ Stage tag: "phase4_validation"
        ▼
[STAGE 6] src/knowledge_graph/pin_normalizer/__init__.py → normalize_pins(datasheets, config)
        │ Output: list[ComponentDatasheet] with PinDefinition.normalized_function set
        │ Note: caller must invoke; not wired inside run_synthesis_pipeline()
        ▼
[STAGE 7] src/schematic/__init__.py → synthesize_schematic(bom, datasheets, subgraph, config)
        │   internally: net_assigner.assign_power_nets(), assign_protocol_nets(),
        │              passive_assigner.assign_passives(), erc.check_erc()
        │ Output: SchematicGraph
        ▼
[STAGE 8] src/layout/__init__.py → generate_layout_spec(schematic, datasheets, subgraph, config)
        │ Output: LayoutSpec
        ▼
[STAGE 9] src/nir/__init__.py → build_nir(bom, datasheets, schematic, layout, config)
        │   internally: nir/builder.py → assemble_nir()
        │              nir/validator.py → validate_nir()
        │ Output: NIR
        ▼
[STAGE 9b — REVIEW GATE] src/review/queue.py → enqueue_nir(nir, config)
        │ Fires when: nir.is_review_required() == True (any CRITICAL ReviewFlag)
        │ Stage tag: "nir_validation"
        ▼
[STAGE 10] src/output/__init__.py → run_output_pipeline(nir, output_dir, config)
        │
        ├─ [10a] src/output/tscircuit_serializer.py → serialize_to_tscircuit(nir, output_dir/tscircuit, config)
        ├─ [10b] src/output/kicad_serializer.py → serialize_to_kicad(nir, output_dir/kicad, config)
        └─ [10c] src/output/doc_generator.py → generate_design_report(nir, output_dir/report, config)
        │ Output: OutputResult (TSX, KiCad files, report path)
        ▼
Fabrication-ready files on disk under output_dir/
```

**Team-level orchestrators (actual call chains in code):**

| Orchestrator | File | Functions called |
|---|---|---|
| Intent → BOM | `src/intent/pipeline.py` | `parse_intent` → [`run_completion_engine`] → [`RetrievalEngine.run_retrieval`] → `assert_interval_feasible` (hard gate) → `query_graph` → `generate_bom` → `validate_bom` → `persist_design_constraints` → [`enqueue_bom`] |
| Datasheet P1 | `src/datasheet/pipeline.py` | `phase1_dla.process` → `phase2_tsr.process` → `phase3_extract.process` → `phase4_validate.validate/apply_verdict` → [`phase5_layout.extract_layout_constraints`] → [`enqueue`] |
| BOM → NIR | `src/synthesis/pipeline.py` | `synthesize_schematic` → `generate_layout_spec` → `build_nir` → [`enqueue_nir`] |
| NIR → files | `src/output/__init__.py` | `serialize_to_tscircuit` ∥ `serialize_to_kicad` ∥ `generate_design_report` |
| E2E entry point | `src/orchestrator.py` | `run_intent_pipeline` → [BLOCKS if `review_required`] → `query_graph` (re-query) → `parse_datasheet` (per component) → `normalize_pins` → `run_synthesis_pipeline` → `run_output_pipeline` |
| Post-review resume | `src/orchestrator.py` | `resume_after_review(design_id, ...)` → deserializes persisted `ValidatedBOM` snapshot (never regenerates) → same post-BOM stages as `run_e2e` |

---

## SECTION 3 — STAGE-BY-STAGE WHITE-BOX TRACE

### Stage 1 — Intent Parsing

**Script:** `src/intent/parser.py`  
**Function called:** `parse_intent(prompt: str, config: Config) -> IntentDict`  
**Called by:** `src/intent/pipeline.py` → `run_intent_pipeline()` line 30  
**Depends on output of:** Raw engineer prompt string

**What this script does:**  
`parse_intent()` first attempts LLM extraction via `_call_llm_with_instructor()` using `SYSTEM_PROMPT` and a `ParsedIntent` Pydantic response model. When Instructor/OpenAI is unavailable (current default), it falls back to `_rule_based_parse()` which keyword-matches methodology triggers from `src/intent/methodology_classifier.py`. The raw goal is cleaned through `clean_goal()` using `GOAL_STOPWORDS` and `COMPONENT_TYPE_NORMALIZATION` (e.g. `"ldo"` → `"ldo_regulator"`). Methodology is re-validated by `validate_methodology()`, constraints are inferred by `infer_constraints()`, and ambiguities are detected by `detect_ambiguities()`. If any `AmbiguityFlag` has `severity == "CRITICAL"`, `clarification_required` is set to `True`. The function never raises.

**Input — what it receives:**

```json
[EXAMPLE INPUT — raw prompt string]
"design a 3.3V LDO regulator for an IoT sensor"
```

**Output — what it produces:**

```json
[EXAMPLE OUTPUT — IntentDict]
{
  "goal": "ldo_regulator",
  "frequency": null,
  "application": "iot sensor",
  "explicit_constraints": [],
  "inferred_constraints": ["low_power_operation"],
  "design_methodology": "power_management",
  "board_type": "double_sided_SMD",
  "ambiguities": [],
  "clarification_required": false,
  "raw_prompt": "design a 3.3V LDO regulator for an IoT sensor"
}
```

**What happens if something goes wrong:**  
Does not raise. On total failure inside `run_intent_pipeline()`, the caller receives a fallback `IntentDict` with `goal="unknown"` and `clarification_required=True` plus an empty `ValidatedBOM` with `total_confidence=0.0` and `review_required=True` (`src/intent/pipeline.py` lines 46–56).

---

### Stage 2 — Knowledge Graph Query

**Script:** `src/knowledge_graph/query/__init__.py`  
**Function called:** `query_graph(intent: IntentDict, graph: KnowledgeGraph, config: Config) -> DesignSubgraph`  
**Called by:** `src/intent/pipeline.py` → `run_intent_pipeline()` line 37  
**Depends on output of:** Stage 1 (`IntentDict`)

**What this script does:**  
Maps `intent.goal` to start nodes via `goal_mapper.map_goal_to_nodes()`. Loads the methodology node `design_methodology:{intent.design_methodology.value}` from KG layer 5. Runs BFS traversal through `traversal.bfs_traverse()` with `config.kg_traversal_max_depth` (default 4) and `config.kg_min_edge_confidence` (default 0.60). If `intent.frequency` is set, prunes nodes whose `frequency_hz` property is outside ±20% of the target. Assembles a `DesignSubgraph` via `result_builder.build_subgraph()`. Never raises; returns empty subgraph on failure.

**Input — what it receives:**

```json
[EXAMPLE INPUT — IntentDict from Stage 1]
{
  "goal": "ldo_regulator",
  "design_methodology": "power_management",
  "application": "iot sensor",
  "raw_prompt": "design a 3.3V LDO regulator for an IoT sensor"
}
```

**Output — what it produces:**

```json
[EXAMPLE OUTPUT — DesignSubgraph]
{
  "component_types": [
    {
      "id": "component_type:ldo_regulator",
      "node_type": "component_type",
      "layer": 2,
      "label": "ldo_regulator",
      "properties": {"output_voltage": 3.3},
      "source": "kg:design_recipe:iot_ldo",
      "confidence": 0.92,
      "extraction_method": "p1_vector"
    },
    {
      "id": "component_type:input_capacitor",
      "node_type": "component_type",
      "layer": 2,
      "label": "input_capacitor",
      "properties": {},
      "source": "kg:design_recipe:iot_ldo",
      "confidence": 0.88,
      "extraction_method": "p1_vector"
    }
  ],
  "component_instances": [
    {
      "id": "component_instance:TPS7A20DRVR",
      "node_type": "component_instance",
      "layer": 3,
      "label": "TPS7A20DRVR",
      "properties": {"component_type": "ldo_regulator", "output_voltage": 3.3},
      "source": "TI datasheet corpus",
      "confidence": 0.97,
      "extraction_method": "p1_vector"
    }
  ],
  "design_rules": [],
  "placement_rules": [],
  "routing_hints": [],
  "design_methodology": "power_management",
  "path_confidences": {
    "component_type:ldo_regulator": 0.92,
    "component_instance:TPS7A20DRVR": 0.97
  },
  "query_depth": 4,
  "query_metadata": {}
}
```

**What happens if something goes wrong:**  
Returns `_empty_subgraph(methodology_str)` with all node lists empty and `path_confidences={}`. Logs warning `"No KG nodes found for goal: ..."`. Never raises.

---

### Stage 3 — BOM Generation

**Script:** `src/bom/generator.py`  
**Function called:** `generate_bom(subgraph: DesignSubgraph, intent: IntentDict, config: Config) -> ValidatedBOM`  
**Called by:** `src/intent/pipeline.py` → `run_intent_pipeline()` line 38  
**Depends on output of:** Stage 2 (`DesignSubgraph`) and Stage 1 (`IntentDict`)

**What this script does:**  
Generates a UUID `design_id`. Resets the reference designator counter via `get_counter().reset()`. For each `KGNode` in `subgraph.component_types`, calls `select_component()` from `src/bom/selector.py` which maps component type labels to ref prefixes (`ldo_regulator` → `"U"`), resolves specific parts from `subgraph.component_instances`, and builds `BOMEntry` objects. Computes `total_confidence` via `score_bom()` with criticality weights (e.g. `ldo_regulator` weight 2.0). Sets `review_required=True` when `total_confidence < config.confidence_thresholds["bom_total"]` (default **0.85** from `configs/default.yaml`), any entry has `confidence < config.confidence_thresholds["bom_component"]` (default **0.75**), or any entry has `specific_part is None`.

**Input — what it receives:**

```json
[EXAMPLE INPUT — DesignSubgraph + IntentDict]
{
  "subgraph": { "...": "see Stage 2 output" },
  "intent": { "goal": "ldo_regulator", "design_methodology": "power_management" }
}
```

**Output — what it produces:**

```json
[EXAMPLE OUTPUT — ValidatedBOM (pre-validate_bom pass)]
{
  "design_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "intent": { "goal": "ldo_regulator", "raw_prompt": "design a 3.3V LDO regulator for an IoT sensor" },
  "components": [
    {
      "ref": "U1",
      "component_type": "ldo_regulator",
      "specific_part": "TPS7A20DRVR",
      "value_constraints": {"output_voltage": 3.3},
      "justification": "Selected TPS7A20DRVR for 3.3V LDO in IoT sensor application",
      "source": "TI datasheet corpus",
      "confidence": 0.92,
      "alternatives": [],
      "review_flag": false
    },
    {
      "ref": "C1",
      "component_type": "input_capacitor",
      "specific_part": null,
      "value_constraints": {},
      "justification": "Input decoupling for ldo_regulator stage",
      "source": "kg:design_recipe:iot_ldo",
      "confidence": 0.748,
      "alternatives": [],
      "review_flag": true
    }
  ],
  "cross_component_rules": [],
  "total_confidence": 0.8912,
  "review_flags": [],
  "review_required": true,
  "created_at": "2026-06-20T08:15:00Z"
}
```

**What happens if something goes wrong:**  
Never raises. On exception, returns `ValidatedBOM` with empty `components`, `total_confidence=0.0`, `review_required=True`. Empty `subgraph.component_types` also yields empty BOM with `review_required=True`.

---

### Stage 4 — BOM Validation

**Script:** `src/bom/validator.py`  
**Function called:** `validate_bom(bom: ValidatedBOM, config: Config) -> ValidatedBOM`  
**Called by:** `src/intent/pipeline.py` → `run_intent_pipeline()` line 39  
**Depends on output of:** Stage 3 (`ValidatedBOM`)

**What this script does:**  
Runs three non-short-circuiting passes on a copy of the input BOM. Pass 1 (`_pass1_voltage_compatibility`) flags power components with conflicting `value_constraints["output_voltage"]` (>0.1 V difference). Pass 2 (`_pass2_logic_level_compatibility`) flags IC logic voltage mismatches (>0.5 V). Pass 3 (`_pass3_supplier_availability`) calls `check_availability()` from `src/bom/supplier_cache.py` and sets `review_flag=True` on entries marked `UNAVAILABLE`. Appends all flag strings to `review_flags`. Returns a new `ValidatedBOM` via `model_copy`; never mutates input.

**Input — what it receives:**

```json
[EXAMPLE INPUT — ValidatedBOM from Stage 3]
{
  "design_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "components": [ "...U1 TPS7A20DRVR...", "...C1 unresolved..." ],
  "total_confidence": 0.8912,
  "review_required": true,
  "review_flags": []
}
```

**Output — what it produces:**

```json
[EXAMPLE OUTPUT — ValidatedBOM after validation]
{
  "design_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "components": [ "...same entries, C1 may have review_flag updated..." ],
  "total_confidence": 0.8912,
  "review_flags": [
    "Availability unverified for TPS7A20DRVR — confirm before procurement"
  ],
  "review_required": true,
  "created_at": "2026-06-20T08:15:00Z"
}
```

**What happens if something goes wrong:**  
Does not raise. Validation failures are expressed as string entries in `review_flags`, not exceptions.

---

### Stage 4b — Human Review Gate (BOM)

**Script:** `src/review/queue.py`  
**Function called:** `enqueue_bom(bom: ValidatedBOM, config: Config) -> ReviewQueueItem`  
**Called by:** `src/intent/pipeline.py` → `run_intent_pipeline()` line 41–42 when `validated_bom.review_required == True`  
**Depends on output of:** Stage 4 (`ValidatedBOM`)

**What this script does:**  
Writes a SQLite row to `review_queue` table (path from `config.review_queue_path`, default `output/review_queue.db`). Creates a `ReviewQueueItem` with `stage="bom_generation"`, `component_id=bom.design_id`, `verdict="REVIEW_REQUIRED"`, and `flags=bom.review_flags`. Severity is `"CRITICAL"` if any flag string contains `"CRITICAL"`, else `"WARNING"`.

**Input — what it receives:**

```json
[EXAMPLE INPUT — ValidatedBOM with review_required=True]
{
  "design_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "review_required": true,
  "review_flags": ["Availability unverified for TPS7A20DRVR — confirm before procurement"]
}
```

**Output — what it produces:**

```json
[EXAMPLE OUTPUT — ReviewQueueItem persisted to SQLite]
{
  "item_id": "550e8400-e29b-41d4-a716-446655440000",
  "stage": "bom_generation",
  "component_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "pdf_path": "N/A",
  "severity": "WARNING",
  "verdict": "REVIEW_REQUIRED",
  "flags": ["Availability unverified for TPS7A20DRVR — confirm before procurement"],
  "created_at": "2026-06-20T08:15:01Z",
  "status": "pending",
  "resolved_at": null,
  "resolution_notes": null
}
```

**What happens if something goes wrong:**  
SQLite write failures propagate as exceptions from `sqlite3.connect()`. The BOM pipeline itself does not catch enqueue failures.

---

### Stage 5 — Datasheet Parsing (P1 Pipeline Orchestrator)

**Script:** `src/datasheet/pipeline.py`  
**Function called:** `parse_datasheet(component_id: str, pdf_path: Path, config: Config) -> ComponentDatasheet`  
**Called by:** External caller (once per `BOMEntry.specific_part`); not invoked inside `run_intent_pipeline()` or `run_synthesis_pipeline()`  
**Depends on output of:** Stage 4 (`ValidatedBOM.components[].specific_part` and PDF path resolution by caller)

**What this script does:**  
Orchestrates phases 1→2→3→4→5 in strict order. Calls `phase1_dla(pdf_path, config)`, then `phase2_tsr(phase1_output, config)`, then `phase3_extract(phase2_output, config)`, then `validate()` + `apply_verdict()` from phase 4, then conditionally `extract_layout_constraints()` if any `TableCrop.section_type == LAYOUT_RECOMMENDATIONS`. Sets `component_id` on the final object via `model_copy`. If `review_required=True` after phase 4, calls `enqueue()`. Raises `FileNotFoundError` if PDF missing; wraps unhandled phase exceptions as `DatasheetPipelineError(phase_name, component_id, cause)`.

**Input — what it receives:**

```python
[EXAMPLE INPUT]
component_id = "TPS7A20DRVR"
pdf_path = Path("corpus/golden/TPS7A20DRVR.pdf")
config = Config.from_yaml("configs/default.yaml")
```

**Output — what it produces:**

```json
[EXAMPLE OUTPUT — ComponentDatasheet after all phases]
{
  "component_id": "TPS7A20DRVR",
  "manufacturer": "Texas Instruments",
  "description": "200-mA, high-accuracy, low-IQ, low-dropout voltage regulator",
  "package": "SOT-23-5",
  "source_pdf_hash": "a3f8c2e1...sha256...",
  "electrical_parameters": [ "..." ],
  "absolute_max_ratings": [ "..." ],
  "pins": [ "..." ],
  "layout_constraints": [],
  "extraction_method": "p1_vector",
  "extraction_confidence": 0.937,
  "review_required": false,
  "review_flags": [],
  "pipeline_version": "1.0",
  "created_at": "2026-06-20T08:16:30Z"
}
```

**What happens if something goes wrong:**  
Raises `DatasheetPipelineError` with `phase` attribute set to the failing phase name (e.g. `"Phase 3"`) per `src/datasheet/pipeline.py` lines 231–237. Re-raises existing `DatasheetPipelineError` unchanged.

---

### Stage 5a — Phase 1 Document Layout Analysis (DLA)

**Script:** `src/datasheet/phase1_dla/__init__.py`  
**Function called:** `process(pdf_path: Path, config: Config) -> Phase1Output`  
**Called by:** `src/datasheet/pipeline.py` → `parse_datasheet()` line 127  
**Depends on output of:** PDF file on disk

**What this script does:**  
Computes `source_pdf_hash` via `compute_pdf_sha256()`. Rasterizes all pages with `_rasterize_all_pages()`. Loads YOLOv8n-DocLayNet from `config.model_paths["yolov8n_doclaynet"]` and runs `_detect_all_pages()` at confidence threshold 0.25. Crops table regions to PNG bytes, classifies section types via `classify_section()`, detects multipage continuations via `detect_multipage_tables()`, and links footnotes via `link_footnotes()`. Returns `Phase1Output` with `table_crops`, `footnote_maps`, and timing metadata.

**Input — what it receives:**

```python
[EXAMPLE INPUT]
pdf_path = Path("corpus/golden/TPS7A20DRVR.pdf")
```

**Output — what it produces:**

```json
[EXAMPLE OUTPUT — Phase1Output]
{
  "pdf_path": "corpus/golden/TPS7A20DRVR.pdf",
  "source_pdf_hash": "a3f8c2e1b4d5...",
  "total_pages": 28,
  "table_crops": [
    {
      "page_number": 4,
      "section_type": "electrical_characteristics",
      "image_bytes": "<binary PNG>",
      "bounding_box": [120, 340, 890, 720],
      "heading_text": "Detected caption near table",
      "is_multipage_continuation": false,
      "detection_confidence": 0.94
    },
    {
      "page_number": 5,
      "section_type": "pinout",
      "bounding_box": [100, 200, 900, 600],
      "detection_confidence": 0.91
    }
  ],
  "footnote_maps": [],
  "processing_time_ms": 842.3
}
```

**What happens if something goes wrong:**  
Raises `FileNotFoundError` if PDF or YOLO weights missing. Raises `RuntimeError` on processing failure. Wrapped by parent as `DatasheetPipelineError(phase="Phase 1", ...)`.

---

### Stage 5b — Phase 2 Table Structure Recognition (TSR)

**Script:** `src/datasheet/phase2_tsr/__init__.py`  
**Function called:** `process(phase1_output: Phase1Output, config: Config) -> Phase2Output`  
**Called by:** `src/datasheet/pipeline.py` → `parse_datasheet()` line 140  
**Depends on output of:** Stage 5a (`Phase1Output`)

**What this script does:**  
For each `TableCrop`, runs dual-path extraction: Path A (`extract_table_vector_path()` via pdfplumber + Camelot) and Path B (`extract_table_vlm_path()` via Qwen2-VL-7B when enabled). Selects the best grid via `pick_best_grid()`. Runs `detect_merged_cells()` on the winner. Passes `footnote_maps` through unchanged. Skips tables where both paths fail (logs error, continues).

**Input — what it receives:**

```json
[EXAMPLE INPUT — Phase1Output table_crops summary]
{
  "source_pdf_hash": "a3f8c2e1b4d5...",
  "table_crops": [
    {"page_number": 4, "section_type": "electrical_characteristics", "detection_confidence": 0.94},
    {"page_number": 5, "section_type": "pinout", "detection_confidence": 0.91}
  ],
  "footnote_maps": []
}
```

**Output — what it produces:**

```json
[EXAMPLE OUTPUT — Phase2Output]
{
  "source_pdf_hash": "a3f8c2e1b4d5...",
  "grids": [
    {
      "section_type": "electrical_characteristics",
      "rows": 12,
      "cols": 5,
      "cells": [["Parameter", "Conditions", "Min", "Typ", "Max"], "..."],
      "confidence": 0.95,
      "extraction_path": "vector",
      "has_merged_cells": false
    },
    {
      "section_type": "pinout",
      "rows": 6,
      "cols": 4,
      "confidence": 0.93,
      "extraction_path": "vector",
      "has_merged_cells": false
    }
  ],
  "footnote_maps": [],
  "processing_time_ms": 412.7
}
```

**What happens if something goes wrong:**  
Raises `FileNotFoundError` if source PDF missing. Individual table failures log and skip; if all tables fail, returns `Phase2Output` with empty `grids`. Per-table dual-path failure raises `ValueError` inside `_process_single_table()` which is caught at the loop level.

---

### Stage 5c — Phase 3 Semantic Extraction

**Script:** `src/datasheet/phase3_extract/__init__.py`  
**Function called:** `process(phase2_output: Phase2Output, config: Config) -> ComponentDatasheet`  
**Called by:** `src/datasheet/pipeline.py` → `parse_datasheet()` line 153  
**Depends on output of:** Stage 5b (`Phase2Output`)

**What this script does:**  
Extracts component header via `extract_component_header()`. Calls `extract_from_grids()` which iterates each `GridMatrix` through `extract_from_grid()` — rule-based grid parsing with optional LLM path via Instructor + Qwen2.5-7B. Computes `field_coverage` ratio across electrical parameters, absolute max ratings, and pins. Aggregates `extraction_confidence` via `compute_extraction_confidence(method, phase2_confidence, field_coverage)` using weights 40% method / 30% phase2 / 30% coverage. Sets `PinDefinition.normalized_function=None` (Rule 3 — normalization deferred to Stage 6). Sets `review_required=True` if any review flags exist.

**Input — what it receives:**

```json
[EXAMPLE INPUT — Phase2Output grids summary]
{
  "source_pdf_hash": "a3f8c2e1b4d5...",
  "grids": [
    {"section_type": "electrical_characteristics", "confidence": 0.95, "extraction_path": "vector"},
    {"section_type": "pinout", "confidence": 0.93, "extraction_path": "vector"}
  ]
}
```

**Output — what it produces:**

```json
[EXAMPLE OUTPUT — ComponentDatasheet (pre-verdict)]
{
  "component_id": "TPS7A20DRVR",
  "manufacturer": "Texas Instruments",
  "description": "200-mA, high-accuracy, low-IQ, low-dropout voltage regulator",
  "package": "SOT-23-5",
  "source_pdf_hash": "a3f8c2e1b4d5...",
  "electrical_parameters": [
    {
      "parameter_name": "Output Voltage",
      "symbol": "VOUT",
      "conditions": "VIN = 5 V, IOUT = 1 mA",
      "value": {
        "raw_text": "3.3",
        "normalized_value": 3.3,
        "unit": "V",
        "typ_val": 3.3,
        "confidence": 0.97
      },
      "section_type": "electrical_characteristics",
      "source_page": 4,
      "source_table_index": 0,
      "review_required": false
    }
  ],
  "absolute_max_ratings": [
    {
      "parameter_name": "Input Voltage",
      "value": {"raw_text": "6.0", "max_val": 6.0, "unit": "V", "confidence": 0.96},
      "source_page": 3
    }
  ],
  "pins": [
    {
      "pin_number": "1",
      "raw_name": "IN",
      "normalized_function": null,
      "pin_type": "power",
      "description": "Input voltage supply",
      "source_page": 5
    },
    {
      "pin_number": "2",
      "raw_name": "GND",
      "normalized_function": null,
      "pin_type": "ground",
      "source_page": 5
    },
    {
      "pin_number": "5",
      "raw_name": "OUT",
      "normalized_function": null,
      "pin_type": "output",
      "source_page": 5
    }
  ],
  "extraction_method": "p1_vector",
  "extraction_confidence": 0.937,
  "review_required": false,
  "review_flags": [],
  "created_at": "2026-06-20T08:16:28Z"
}
```

**What happens if something goes wrong:**  
Phase-level exceptions propagate to `parse_datasheet()` and become `DatasheetPipelineError(phase="Phase 3", component_id, cause)`.

---

### Stage 5d — Phase 4 Validation

**Script:** `src/datasheet/phase4_validate/__init__.py`  
**Functions called:** `validate(datasheet, config) -> ValidationResult` then `apply_verdict(datasheet, validation_result) -> ComponentDatasheet`  
**Called by:** `src/datasheet/pipeline.py` lines 170–174  
**Depends on output of:** Stage 5c (`ComponentDatasheet`)

**What this script does:**  
`validate()` checks for missing `component_id`, `manufacturer`, `package`, and low `extraction_confidence`. Verdict logic: `confidence < 0.3` → `"BLOCK"` / `"CRITICAL"`; `confidence < 0.7` or any flags → `"WARN"` / `"WARNING"`; else `"PASS"`. `apply_verdict()` sets `review_required=True` when verdict is `"BLOCK"` or `"WARN"`, merges validation flags into `review_flags` via `model_copy` (never mutates in place).

**Input — what it receives:**

```json
[EXAMPLE INPUT — ComponentDatasheet from Stage 5c]
{
  "component_id": "TPS7A20DRVR",
  "extraction_confidence": 0.937,
  "review_required": false
}
```

**Output — what it produces:**

```json
[EXAMPLE OUTPUT — ValidationResult + updated ComponentDatasheet]
{
  "validation_result": {
    "verdict": "PASS",
    "severity": "WARNING",
    "confidence": 0.937,
    "flags": []
  },
  "datasheet": {
    "component_id": "TPS7A20DRVR",
    "extraction_confidence": 0.937,
    "review_required": false,
    "review_flags": []
  }
}
```

**What happens if something goes wrong:**  
Low confidence example: `extraction_confidence=0.25` → verdict `"BLOCK"`, `review_required=True`, flag `"Low extraction confidence: 0.25"`. Parent pipeline then calls `enqueue()` at line 221.

---

### Stage 5e — Phase 5 Layout Extraction

**Script:** `src/datasheet/phase5_layout/__init__.py`  
**Function called:** `extract_layout_constraints(pdf_path: Path, phase1_output: Phase1Output, config: Config) -> list[PlacementConstraint]`  
**Called by:** `src/datasheet/pipeline.py` lines 184–195 (only if `_has_layout_sections(phase1_output)` is True)  
**Depends on output of:** Stage 5a (`Phase1Output`) and original PDF path

**What this script does:**  
Finds pages with `TableSectionType.LAYOUT_RECOMMENDATIONS` crops. Extracts text via `extract_page_texts()`. Sends text blocks to `parse_constraints()` (Qwen2.5-7B via Instructor). Validates output via `validate_and_finalize()`. Returns empty list immediately if no layout sections exist or on any failure. Never raises.

**Input — what it receives:**

```python
[EXAMPLE INPUT]
pdf_path = Path("corpus/golden/TPS7A20DRVR.pdf")
phase1_output  # with LAYOUT_RECOMMENDATIONS crops on pages 22–23
```

**Output — what it produces:**

```json
[EXAMPLE OUTPUT — list[PlacementConstraint] merged into ComponentDatasheet]
[
  {
    "constraint_type": "proximity",
    "subject": "C_IN",
    "relative_to": "U1.IN",
    "relative_to_type": "pin",
    "max_distance_mm": 3.0,
    "hard": true,
    "source_sentence": "Place input capacitor within 3 mm of the IN pin.",
    "confidence": 0.82
  }
]
```

**What happens if something goes wrong:**  
Returns `[]` on model failure, empty text extraction, or no layout pages. Logged as warning; pipeline continues without layout constraints.

---

### Stage 6 — Pin Normalization

**Script:** `src/knowledge_graph/pin_normalizer/__init__.py` → `src/knowledge_graph/pin_normalizer/normalizer.py`  
**Function called:** `normalize_pins(datasheets: list[ComponentDatasheet], config: Config) -> list[ComponentDatasheet]`  
**Called by:** External caller between Stage 5 and Stage 7 (not wired inside `run_synthesis_pipeline()`)  
**Depends on output of:** Stage 5 (`list[ComponentDatasheet]`)

**What this script does:**  
For each pin in each datasheet, runs three tiers: (1) `normalize_from_dictionary()` → confidence 1.0; (2) `resolve_with_context()` → confidence 0.90; (3) `normalize_via_llm()` → variable confidence. Updates pins via `pin.model_copy(update={"normalized_function": canonical, "normalization_confidence": confidence})`. Failed pins get `normalized_function=None` and a review flag string `"Pin {n} ({raw_name}): normalization failed"`. Never mutates input objects.

**Input — what it receives:**

```json
[EXAMPLE INPUT — ComponentDatasheet pins before normalization]
{
  "component_id": "TPS7A20DRVR",
  "pins": [
    {"pin_number": "1", "raw_name": "IN", "normalized_function": null},
    {"pin_number": "2", "raw_name": "GND", "normalized_function": null},
    {"pin_number": "5", "raw_name": "OUT", "normalized_function": null}
  ]
}
```

**Output — what it produces:**

```json
[EXAMPLE OUTPUT — ComponentDatasheet pins after normalization]
{
  "component_id": "TPS7A20DRVR",
  "pins": [
    {"pin_number": "1", "raw_name": "IN", "normalized_function": "POWER_INPUT", "normalization_confidence": 1.0, "normalization_method": "dictionary"},
    {"pin_number": "2", "raw_name": "GND", "normalized_function": "POWER_GROUND", "normalization_confidence": 1.0},
    {"pin_number": "5", "raw_name": "OUT", "normalized_function": "POWER_POSITIVE", "normalization_confidence": 1.0}
  ],
  "review_flags": []
}
```

**What happens if something goes wrong:**  
Never raises. Unresolvable pins remain with `normalized_function=None`; review flag appended. Per-datasheet exceptions log and return original datasheet unchanged.

---

### Stage 7 — Schematic Synthesis

**Script:** `src/schematic/__init__.py`  
**Function called:** `synthesize_schematic(bom: ValidatedBOM, datasheets: list[ComponentDatasheet], subgraph: DesignSubgraph, config: Config) -> SchematicGraph`  
**Called by:** `src/synthesis/pipeline.py` → `run_synthesis_pipeline()` line 66  
**Depends on output of:** Stage 4 (`ValidatedBOM`), Stage 5+6 (`list[ComponentDatasheet]`), Stage 2 (`DesignSubgraph`)

**What this script does:**  
Builds `ref_map` via `build_ref_map(bom, datasheets)` mapping component IDs to `(ref, ComponentDatasheet)` tuples. Creates power nets via `assign_power_nets()` — groups `POWER_POSITIVE` pins into `VCC` or `VCC_{voltage}V` (derived from datasheet description), `POWER_GROUND` → `GND`, `POWER_INPUT` → `VIN`. Creates signal nets via `assign_protocol_nets()` matching `normalized_function` against `PROTOCOL_GROUPS` from `configs/canonical_functions.yaml`. Adds passive nets via `assign_passives()`. Classifies functional blocks via `classify_blocks()`. Runs ERC via `check_erc()`. Computes `synthesis_confidence` as mean of `net.net_confidence` values. Never raises; returns empty `SchematicGraph` with CRITICAL `ReviewFlag` on exception.

**Input — what it receives:**

```json
[EXAMPLE INPUT]
{
  "bom": { "design_id": "...", "components": [{"ref": "U1", "specific_part": "TPS7A20DRVR"}] },
  "datasheets": [{ "component_id": "TPS7A20DRVR", "pins": [{"normalized_function": "POWER_INPUT", "pin_number": "1"}, "..."] }]
}
```

**Output — what it produces:**

```json
[EXAMPLE OUTPUT — SchematicGraph]
{
  "netlist": [
    {
      "net_name": "VCC_3V3",
      "net_type": "power",
      "connections": [
        {"ref": "U1", "pin_name": "POWER_POSITIVE", "pin_number": "5"}
      ],
      "source_rule": "power_net_assignment",
      "net_confidence": 1.0
    },
    {
      "net_name": "GND",
      "net_type": "power",
      "connections": [
        {"ref": "U1", "pin_name": "POWER_GROUND", "pin_number": "2"}
      ],
      "source_rule": "power_net_assignment",
      "net_confidence": 1.0
    },
    {
      "net_name": "VIN",
      "net_type": "power",
      "connections": [
        {"ref": "U1", "pin_name": "POWER_INPUT", "pin_number": "1"}
      ],
      "source_rule": "power_net_assignment",
      "net_confidence": 1.0
    }
  ],
  "blocks": [],
  "erc_result": {"passed": true, "violations": [], "rules_checked": 4},
  "synthesis_confidence": 1.0,
  "unresolved_pins": [],
  "review_flags": []
}
```

**What happens if something goes wrong:**  
Returns `SchematicGraph` with empty netlist and CRITICAL `ReviewFlag(reason="Schematic synthesis failed: ...", stage="schematic_synthesis")`. Unresolved pins appended to `unresolved_pins` list with WARNING or CRITICAL severity.

---

### Stage 8 — Layout Engine

**Script:** `src/layout/__init__.py`  
**Function called:** `generate_layout_spec(schematic: SchematicGraph, datasheets: list[ComponentDatasheet], subgraph: DesignSubgraph, config: Config) -> LayoutSpec`  
**Called by:** `src/synthesis/pipeline.py` → `run_synthesis_pipeline()` line 74  
**Depends on output of:** Stage 7 (`SchematicGraph`), Stage 5+6 (`list[ComponentDatasheet]`), Stage 2 (`DesignSubgraph`)

**What this script does:**  
Selects `BoardSpec` via `select_board_spec(subgraph.design_methodology)` — layer count and material based on methodology string. Collects placement constraints via `collect_constraints()` merging datasheet layout constraints and KG-4 placement rules. Generates routing hints via `generate_routing_hints(schematic.netlist, board_spec)`. Builds component groups via `build_groups(schematic.blocks)`. Never raises; returns empty `LayoutSpec` with default 2-layer FR4 board on failure.

**Input — what it receives:**

```json
[EXAMPLE INPUT — SchematicGraph + DesignSubgraph]
{
  "schematic": { "netlist": ["...VCC_3V3...", "...GND...", "...VIN..."] },
  "subgraph": { "design_methodology": "power_management", "placement_rules": [] }
}
```

**Output — what it produces:**

```json
[EXAMPLE OUTPUT — LayoutSpec]
{
  "placement_constraints": [],
  "component_groups": [],
  "routing_hints": [],
  "board_spec": {
    "layers": 2,
    "material": "FR4",
    "thickness_mm": 1.6,
    "copper_weight_oz": 1.0,
    "min_trace_width_mm": 0.15,
    "min_clearance_mm": 0.15,
    "min_via_drill_mm": 0.3,
    "surface_finish": "HASL"
  }
}
```

**What happens if something goes wrong:**  
Returns default empty `LayoutSpec` with 2-layer FR4 defaults. Error logged; no exception raised.

---

### Stage 9 — NIR Assembly and Validation

**Script:** `src/nir/__init__.py` → `src/nir/builder.py` + `src/nir/validator.py`  
**Function called:** `build_nir(bom, datasheets, schematic, layout, config) -> NIR`  
**Called by:** `src/synthesis/pipeline.py` → `run_synthesis_pipeline()` line 82  
**Depends on output of:** Stages 4, 5+6, 7, 8

**What this script does:**  
`assemble_nir()` maps each `BOMEntry` to a `ComponentRef` (footprint from matching `ComponentDatasheet.package`, `datasheet_confidence=entry.confidence`). Copies schematic netlist, layout constraints, groups, routing hints, and board spec. Populates `confidence_scores`, `net_confidence`, `justifications`, and `source_citations` dicts from BOM entries. Merges BOM review flags and schematic unresolved-pin flags into `review_flags`. `validate_nir()` runs six structural rules (`NIR_VALIDATION_RULES`): unknown netlist refs, unknown placement refs, nets with <2 connections, power nets without exactly one source, zero-confidence components. Returns new NIR with additional `ReviewFlag` entries; never mutates input.

**Input — what it receives:**

```json
[EXAMPLE INPUT — upstream artifacts summary]
{
  "bom": { "design_id": "a1b2c3d4-...", "components": [{"ref": "U1", "specific_part": "TPS7A20DRVR", "confidence": 0.92}] },
  "schematic": { "netlist": ["...3 nets..."] },
  "layout": { "board_spec": {"layers": 2} }
}
```

**Output — what it produces:**

```json
[EXAMPLE OUTPUT — NIR]
{
  "schema_version": "1.0",
  "design_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "prompt": "design a 3.3V LDO regulator for an IoT sensor",
  "design_methodology": "power_management",
  "components": [
    {
      "ref": "U1",
      "component_id": "TPS7A20DRVR",
      "component_type": "ldo_regulator",
      "footprint": "SOT-23-5",
      "value": null,
      "manufacturer": "Texas Instruments",
      "datasheet_confidence": 0.92,
      "justification": "Selected TPS7A20DRVR for 3.3V LDO in IoT sensor application"
    }
  ],
  "netlist": [
    {"net_name": "VCC_3V3", "net_type": "power", "connections": [{"ref": "U1", "pin_name": "POWER_POSITIVE", "pin_number": "5"}], "source_rule": "power_net_assignment", "net_confidence": 1.0},
    {"net_name": "GND", "net_type": "power", "connections": [{"ref": "U1", "pin_name": "POWER_GROUND", "pin_number": "2"}], "net_confidence": 1.0},
    {"net_name": "VIN", "net_type": "power", "connections": [{"ref": "U1", "pin_name": "POWER_INPUT", "pin_number": "1"}], "net_confidence": 1.0}
  ],
  "placement_constraints": [],
  "component_groups": [],
  "routing_hints": [],
  "board_spec": {"layers": 2, "material": "FR4", "thickness_mm": 1.6, "min_trace_width_mm": 0.15, "min_clearance_mm": 0.15},
  "confidence_scores": {"U1": 0.92},
  "net_confidence": {"VCC_3V3": 1.0, "GND": 1.0, "VIN": 1.0},
  "justifications": {"U1": "Selected TPS7A20DRVR for 3.3V LDO in IoT sensor application"},
  "source_citations": {"U1": "TI datasheet corpus"},
  "review_flags": [],
  "created_at": "2026-06-20T08:17:00Z",
  "pipeline_version": "1.0"
}
```

**What happens if something goes wrong:**  
`build_nir()` never raises. Assembly failure returns NIR with CRITICAL flag `stage="nir_assembly"`. `validate_nir()` adds CRITICAL flags for structural violations (e.g. `"Net VCC_3V3 references unknown ref U2"`). `run_synthesis_pipeline()` calls `enqueue_nir()` when `nir.is_review_required()` (any CRITICAL flag). Synthesis-level exception returns `_failure_nir()` with CRITICAL flag `stage="synthesis_pipeline"`.

---

### Stage 10a — tscircuit Output

**Script:** `src/output/tscircuit_serializer.py`  
**Function called:** `serialize_to_tscircuit(nir: NIR, output_dir: Path, config: Config) -> TSCircuitOutput`  
**Called by:** `src/output/__init__.py` → `run_output_pipeline()` line 51  
**Depends on output of:** Stage 9 (`NIR`)

**What this script does:**  
Calls `check_version(nir)` from `src/nir/migrations.py` (raises `ValueError` on schema mismatch — caught by parent). Generates TSX via `_generate_tsx()`: resolves element types through `get_element_type()`, footprints through `resolve_footprint()`, emits `circuit.add(<Chip name="U1" footprint="SOT-23-5" />)` lines, then `circuit.connect()` for each net (power nets use global syntax `".VCC_3V3"`). Writes `{design_id}.tsx`. Invokes `npx @tscircuit/cli export --format svg` and `--format 3d` via `_run_cli()`. Never raises; returns `TSCircuitOutput` with `success=True/False`.

**Input — what it receives:**

```json
[EXAMPLE INPUT — NIR component + netlist summary]
{
  "design_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "components": [{"ref": "U1", "component_id": "TPS7A20DRVR", "component_type": "ldo_regulator", "footprint": "SOT-23-5"}],
  "netlist": [{"net_name": "VCC_3V3", "net_type": "power", "connections": [{"ref": "U1", "pin_name": "POWER_POSITIVE", "pin_number": "5"}]}]
}
```

**Output — what it produces:**

```
[EXAMPLE OUTPUT — generated TSX excerpt]
circuit.add(<Chip name="U1" footprint="SOT-23-5" />)  // TPS7A20DRVR
circuit.connect("U1.pos", ".VCC_3V3")
circuit.connect("U1.neg", ".GND")
circuit.connect("U1.pin1", ".VIN")
```

```json
[EXAMPLE OUTPUT — TSCircuitOutput]
{
  "tsx_path": "output/tscircuit/a1b2c3d4-e5f6-7890-abcd-ef1234567890.tsx",
  "schematic_svg_path": "output/tscircuit/a1b2c3d4-e5f6-7890-abcd-ef1234567890_schematic.svg",
  "pcb_3d_path": "output/tscircuit/a1b2c3d4-e5f6-7890-abcd-ef1234567890_pcb_3d.glb",
  "unresolved_footprints": [],
  "unresolved_elements": [],
  "cli_error": null,
  "success": true
}
```

**What happens if something goes wrong:**  
Returns `TSCircuitOutput(success=False, cli_error="tscircuit CLI not found...")`. Parent `run_output_pipeline()` catches exception and logs; other serializers continue independently.

---

### Stage 10b — KiCad Output

**Script:** `src/output/kicad_serializer.py`  
**Function called:** `serialize_to_kicad(nir: NIR, output_dir: Path, config: Config, mcp_client=None) -> KiCadOutput`  
**Called by:** `src/output/__init__.py` → `run_output_pipeline()` line 58  
**Depends on output of:** Stage 9 (`NIR`)

**What this script does:**  
Instantiates `KiCadMCPClient(config.kicad_mcp_url)` (default `http://localhost:3000`). Executes MCP tool sequence: `create_schematic` → per-component `add_symbol` (with `resolve_kicad_symbol()` / `resolve_kicad_footprint()`) → `add_power_symbol` for power nets → `add_wire` pairwise along each net → `add_net_label` for nets with >2 connections → `run_erc` → `create_pcb` → `place_footprint` per component → routing hint tools → `run_drc` → `export_gerbers` → `export_bom` → `save_all`. Never raises; returns `KiCadOutput` with error field on `KiCadMCPError`.

**Input — what it receives:**

```json
[EXAMPLE INPUT — NIR]
{
  "design_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "components": [{"ref": "U1", "component_id": "TPS7A20DRVR", "component_type": "ldo_regulator", "footprint": "SOT-23-5"}],
  "board_spec": {"layers": 2}
}
```

**Output — what it produces (MCP call sequence for U1):**

```python
[EXAMPLE OUTPUT — KiCad MCP calls]
client.call("create_schematic", {"name": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"})
client.call("add_symbol", {
    "reference": "U1",
    "library": "Regulator_Linear",
    "symbol": "TPS7A20",
    "value": "TPS7A20DRVR",
    "footprint": "Package_TO_SOT_SMD:SOT-23-5"
})
client.call("add_power_symbol", {"net_name": "VCC_3V3"})
client.call("add_wire", {"net": "VCC_3V3", "from_component": "U1", "from_pin": "POWER_POSITIVE", "to_component": "U1", "to_pin": "POWER_POSITIVE"})
client.call("run_erc", {})
client.call("create_pcb", {"name": "a1b2c3d4-e5f6-7890-abcd-ef1234567890", "layers": 2})
client.call("place_footprint", {"reference": "U1", "x": 0.0, "y": 0.0, "layer": "top", "rotation": 0})
client.call("run_drc", {})
client.call("export_gerbers", {"output_dir": "output/kicad/gerbers"})
client.call("export_bom", {"output_path": "output/kicad/bom.csv", "format": "csv"})
client.call("save_all", {"schematic_path": "output/kicad/a1b2c3d4....kicad_sch", "pcb_path": "output/kicad/a1b2c3d4....kicad_pcb"})
```

```json
[EXAMPLE OUTPUT — KiCadOutput]
{
  "schematic_path": "output/kicad/a1b2c3d4-e5f6-7890-abcd-ef1234567890.kicad_sch",
  "pcb_path": "output/kicad/a1b2c3d4-e5f6-7890-abcd-ef1234567890.kicad_pcb",
  "gerber_dir": "output/kicad/gerbers",
  "bom_path": "output/kicad/bom.csv",
  "erc_passed": true,
  "drc_passed": true,
  "success": true
}
```

**What happens if something goes wrong:**  
Returns `KiCadOutput(success=False, error="MCP tool 'add_symbol' failed: ...")` on `KiCadMCPError`. Connection failures to MCP server surface here.

---

### Stage 10c — Documentation Report

**Script:** `src/output/doc_generator.py`  
**Function called:** `generate_design_report(nir: NIR, output_dir: Path, config: Config) -> Path`  
**Called by:** `src/output/__init__.py` → `run_output_pipeline()` line 65  
**Depends on output of:** Stage 9 (`NIR`)

**What this script does:**  
Builds Markdown via `_build_markdown(nir)` with eight sections: Design Summary (aggregate confidence via `_aggregate_confidence()`), BOM table, Netlist Summary (flags nets with `net_confidence < 0.75` as `⚠ LOW`), Placement Constraints, Routing Hints, Design Decisions Log, Review Flags (sorted CRITICAL first), Validation Summary. Writes `{design_id}_report.md`. Attempts PDF via `pandoc`, then `weasyprint`; falls back to Markdown. Never raises.

**Input — what it receives:** Full `NIR` from Stage 9.

**Output — what it produces:**

```
output/report/a1b2c3d4-e5f6-7890-abcd-ef1234567890_report.pdf
(or .md if PDF tools unavailable)
```

**What happens if something goes wrong:**  
Returns fallback Markdown path with error note. Logged; no exception propagated.

---

## SECTION 4 — DATA TRANSFORMATION TRACE

**Prompt:** `"design a 3.3V LDO regulator for an IoT sensor"`  
**Component:** TPS7A20DRVR (voltage regulator)

### At Stage 1 — IntentDict

```json
{
  "goal": "ldo_regulator",
  "frequency": null,
  "application": "iot sensor",
  "explicit_constraints": [],
  "inferred_constraints": ["low_power_operation"],
  "design_methodology": "power_management",
  "board_type": "double_sided_SMD",
  "ambiguities": [],
  "clarification_required": false,
  "raw_prompt": "design a 3.3V LDO regulator for an IoT sensor"
}
```

### At Stage 3 — BOMEntry

```json
{
  "ref": "U1",
  "component_type": "ldo_regulator",
  "specific_part": "TPS7A20DRVR",
  "value_constraints": {"output_voltage": 3.3},
  "justification": "Selected TPS7A20DRVR for 3.3V LDO in IoT sensor application",
  "source": "TI datasheet corpus",
  "confidence": 0.92,
  "alternatives": [],
  "review_flag": false
}
```

### At Stage 5c — ComponentDatasheet (after Phase 3)

```json
{
  "component_id": "TPS7A20DRVR",
  "manufacturer": "Texas Instruments",
  "description": "200-mA, high-accuracy, low-IQ, low-dropout voltage regulator",
  "package": "SOT-23-5",
  "pins": [
    {"pin_number": "1", "raw_name": "IN", "normalized_function": null, "pin_type": "power"},
    {"pin_number": "2", "raw_name": "GND", "normalized_function": null, "pin_type": "ground"},
    {"pin_number": "5", "raw_name": "OUT", "normalized_function": null, "pin_type": "output"}
  ],
  "electrical_parameters": [
    {
      "parameter_name": "Output Voltage",
      "conditions": "VIN = 5 V, IOUT = 1 mA",
      "value": {"raw_text": "3.3", "normalized_value": 3.3, "unit": "V", "typ_val": 3.3, "confidence": 0.97}
    }
  ],
  "extraction_method": "p1_vector",
  "extraction_confidence": 0.937
}
```

### At Stage 6 — after Pin Normalization

```json
{
  "component_id": "TPS7A20DRVR",
  "pins": [
    {"pin_number": "1", "raw_name": "IN", "normalized_function": "POWER_INPUT", "normalization_confidence": 1.0},
    {"pin_number": "2", "raw_name": "GND", "normalized_function": "POWER_GROUND", "normalization_confidence": 1.0},
    {"pin_number": "5", "raw_name": "OUT", "normalized_function": "POWER_POSITIVE", "normalization_confidence": 1.0}
  ]
}
```

### At Stage 7 — NetlistEntry in SchematicGraph

```json
{
  "net_name": "VCC_3V3",
  "net_type": "power",
  "connections": [
    {"ref": "U1", "pin_name": "POWER_POSITIVE", "pin_number": "5"}
  ],
  "source_rule": "power_net_assignment",
  "net_confidence": 1.0
}
```

### At Stage 9 — ComponentRef in NIR

```json
{
  "ref": "U1",
  "component_id": "TPS7A20DRVR",
  "component_type": "ldo_regulator",
  "footprint": "SOT-23-5",
  "value": null,
  "manufacturer": "Texas Instruments",
  "datasheet_confidence": 0.92,
  "justification": "Selected TPS7A20DRVR for 3.3V LDO in IoT sensor application"
}
```

### At Stage 10b — KiCad MCP call

```python
client.call("add_symbol", {
    "reference": "U1",
    "library": "Regulator_Linear",
    "symbol": "TPS7A20",
    "value": "TPS7A20DRVR",
    "footprint": "Package_TO_SOT_SMD:SOT-23-5"
})
```

### At Stage 10a — tscircuit TSX line

```tsx
circuit.add(<Chip name="U1" footprint="SOT-23-5" />)  // TPS7A20DRVR
circuit.connect("U1.pos", ".VCC_3V3")
```

---

## SECTION 5 — HUMAN REVIEW GATES

The pipeline has **four decision points** where automated execution pauses or flags work for human review. Three persist items to the SQLite review queue (`src/review/queue.py`); one blocks without enqueueing.

### Gate 1 — Intent Clarification (pre-queue)

| Field | Value |
|---|---|
| **Trigger** | `IntentDict.clarification_required == True` — any `AmbiguityFlag` with `severity == "CRITICAL"` (e.g. RF design without frequency, generic goal) |
| **Threshold source** | `src/intent/parser.py` lines 411–413; `src/intent/ambiguity_detector.py` |
| **Queue enqueue?** | **No** — `run_intent_pipeline()` returns `_empty_bom()` immediately without calling `enqueue_bom()` |
| **What reviewer sees** | Empty BOM with `review_required=True`, `total_confidence=0.0`. Clarification questions via `get_clarification_questions(intent)` |

**After approval:** Engineer revises prompt and re-runs `run_intent_pipeline()`.

---

### Gate 2 — BOM Generation Review (blocking, orchestrator-enforced)

| Field | Value |
|---|---|
| **Trigger** | `ValidatedBOM.review_required == True` after `generate_bom()`, OR a Stage 2.75 `ConstraintConflictError` from `assert_interval_feasible()` |
| **Thresholds** | `total_confidence < config.confidence_thresholds["bom_total"]` → **0.85**; any `BOMEntry.confidence < config.confidence_thresholds["bom_component"]` → **0.75**; any `specific_part is None` (`configs/default.yaml`) |
| **Enqueue** | `enqueue_bom(validated_bom, config)` → stage `"bom_generation"`; stores the **full serialized `ValidatedBOM`** in the `bom_json` column of the same SQLite record (single source of truth, no separate snapshot file) |
| **Additional flags** | `validate_bom()` appends strings to `review_flags` (voltage conflicts, supplier availability) |
| **Blocking behavior** | `src/orchestrator.py` → `run_e2e()` halts here and returns `E2EResult(status="pending_review", overall_success=False)`. Synthesis, layout, and serialization do **not** run until approved. |

**Reviewer CLI session:**

```
$ python -m src.review.cli list
Item ID    Component            Severity   Verdict  Flags  Created
550e8400   a1b2c3d4-e5f6-7890   WARNING    REVIEW_  1      2026-06-20 08:15:01
           -abcd-ef1234567890              REQUIRED

Total pending: 1

$ python -m src.review.cli review 550e8400-e29b-41d4-a716-446655440000
{
  "item_id": "550e8400-e29b-41d4-a716-446655440000",
  "stage": "bom_generation",
  "component_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "severity": "WARNING",
  "verdict": "REVIEW_REQUIRED",
  "flags": ["Availability unverified for TPS7A20DRVR — confirm before procurement"],
  "status": "pending"
}

$ python -m src.review.cli approve 550e8400-e29b-41d4-a716-446655440000 --notes "Part confirmed in stock"
Approved item 550e8400... (a1b2c3d4-e5f6-7890-abcd-ef1234567890)

$ python -m src.review.cli correct 550e8400-e29b-41d4-a716-446655440000 --notes "Changed U1 to TPS7A2033DRVR"
Marked item 550e8400... as corrected (a1b2c3d4-e5f6-7890-abcd-ef1234567890)
```

**After approval:** Approve by `design_id` (not `item_id`):

```
$ python -m src.review.cli approve-design a1b2c3d4-e5f6-7890-abcd-ef1234567890
Approved design a1b2c3d4-... (item 550e8400...)
Resume with: src.orchestrator.resume_after_review(design_id, ...)
```

Then continue the pipeline from Python:

```python
from src.orchestrator import resume_after_review
result = resume_after_review(design_id, graph, output_dir, config)
```

`resume_after_review()` deserializes the **persisted `bom_json` snapshot**
from the queue record — it does not regenerate the BOM, so the design that
gets built is guaranteed to be exactly what the reviewer approved. A design
that is still `pending` or was `rejected` returns without running any
downstream stage (`status="pending_review"` or `status="rejected"`).

Corrected items export via:

```
$ python -m src.review.cli export --output data/corrections_export.jsonl
Exported 1 items to data/corrections_export.jsonl
```

---

### Gate 3 — Datasheet Extraction Review (Phase 4)

| Field | Value |
|---|---|
| **Trigger** | `ComponentDatasheet.review_required == True` after `apply_verdict()` |
| **Thresholds** | `extraction_confidence < 0.3` → verdict `"BLOCK"`; `extraction_confidence < 0.7` or validation flags → verdict `"WARN"` (`src/datasheet/phase4_validate/__init__.py`) |
| **Enqueue** | `enqueue(datasheet, validation_result, config)` → stage `"phase4_validation"` |
| **Stored fields** | `component_id`, `verdict` (PASS/WARN/BLOCK), `severity`, `flags=datasheet.review_flags` |

**Reviewer CLI:** Same commands as Gate 2 (`list`, `review`, `approve`, `correct`).

**After approval:** Corrected datasheet re-ingested; pipeline continues to pin normalization and synthesis.

---

### Gate 4 — NIR Structural Review

| Field | Value |
|---|---|
| **Trigger** | `nir.is_review_required() == True` — any `ReviewFlag` with `severity == "CRITICAL"` |
| **Sources** | BOM flags, schematic unresolved power pins, NIR validation rules (`validate_nir()`), synthesis failures |
| **Enqueue** | `enqueue_nir(nir, config)` → stage `"nir_validation"` |
| **Threshold** | No confidence threshold — purely structural CRITICAL flags |

**Reviewer CLI:** Same commands. Item `component_id` is the `design_id`.

**After approval:** `run_output_pipeline(nir, output_dir, config)` produces fabrication files.

---

## SECTION 6 — OUTPUT FILES PRODUCED

For a single design with `design_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"` and `output_dir = "output/"`:

| File | Pattern | Produced by | Contains |
|------|---------|-------------|---------|
| tscircuit TSX | `{design_id}.tsx` | `src/output/tscircuit_serializer.py` | `@tscircuit/core` circuit definition with `circuit.add()` and `circuit.connect()` |
| Schematic SVG | `{design_id}_schematic.svg` | tscircuit CLI via `tscircuit_serializer._run_cli()` | Vector schematic render |
| 3D PCB model | `{design_id}_pcb_3d.glb` | tscircuit CLI via `tscircuit_serializer._run_cli()` | 3D board model |
| KiCad schematic | `{design_id}.kicad_sch` | `src/output/kicad_serializer.py` → MCP `save_all` | KiCad schematic document |
| KiCad PCB | `{design_id}.kicad_pcb` | `src/output/kicad_serializer.py` → MCP `save_all` | KiCad PCB layout |
| Gerber files | `gerbers/*.gbr` | `src/output/kicad_serializer.py` → MCP `export_gerbers` | Fabrication layer files |
| BOM CSV | `bom.csv` | `src/output/kicad_serializer.py` → MCP `export_bom` | Component bill of materials |
| Design report (PDF) | `{design_id}_report.pdf` | `src/output/doc_generator.py` → pandoc/weasyprint | Full design traceability report |
| Design report (MD fallback) | `{design_id}_report.md` | `src/output/doc_generator.py` | Same content when PDF tools unavailable |
| Review queue DB | `review_queue.db` (SQLite) | `src/review/queue.py` | Pending/resolved review items |
| NIR JSON | *(in-memory only)* | `src/nir/builder.py` → `assemble_nir()` | Not written to disk by default; caller must serialize |

**Output directory layout after `run_output_pipeline()`:**

```
output/
├── tscircuit/
│   ├── {design_id}.tsx
│   ├── {design_id}_schematic.svg
│   └── {design_id}_pcb_3d.glb
├── kicad/
│   ├── {design_id}.kicad_sch
│   ├── {design_id}.kicad_pcb
│   ├── bom.csv
│   └── gerbers/
└── report/
    └── {design_id}_report.pdf
```

---

## SECTION 7 — KNOWLEDGE GRAPH ROLE

### Five abstraction layers (`src/schemas/kg.py`)

| Layer | `KGNodeType` values | Content |
|-------|---------------------|---------|
| **1** | `physics_concept` | Physics laws, thermal models |
| **2** | `component_type` | Abstract categories: `ldo_regulator`, `input_capacitor` |
| **3** | `component_instance` | Specific parts: `TPS7A20DRVR`, `GRM155R71C104KA88D` |
| **4** | `design_recipe`, `placement_rule`, `routing_rule`, `electrical_property`, `topology`, `functional_block` | Design patterns, constraints, quantitative rules, formal circuit topologies (LDO, Buck Converter) |
| **5** | `design_methodology`, `design_constraint`, project nodes | Methodology definitions (`power_management`, `RF_highfreq`); per-design-run persisted constraints scoped by `design_id` |

**Known layer-numbering collision (not yet fixed — see
`TOPOLOGY_CONSTRAINT_LAYER.md §4` for the migration proposal):**
`src/knowledge_graph/ingestion/kg2_appnotes/kg2_graph_builder.py` writes
`DESIGN_RECIPE` nodes at **layer=2**, contradicting the canonical layer-4
assignment in this table and in the `KGNode` docstring. Do not assume the
`layer` field alone reliably groups all recipe nodes until that migration
lands — filter by `node_type` in addition to `layer` if this matters for
your query.

Edge types include `REQUIRES`, `USES`, `HAS_PROPERTY`, `CONNECTS_TO`, `MUST_BE_NEAR`, `GOVERNED_BY`, `IMPLEMENTS` (component realizes a topology), `CONSTRAINED_BY`, and others defined in `KGRelation`.

### Population scripts

| Layer | Populated by |
|-------|-------------|
| 1–2 | `src/knowledge_graph/ingestion/kg1_aac/` — All About Circuits scraper + graph builder |
| 4 | `src/knowledge_graph/ingestion/kg2_appnotes/` — application note prose extraction + KG-2/KG-4 builders |
| 3 | `src/knowledge_graph/importers/p1_importer.py` — imports `ComponentDatasheet` JSON from P1 parser |
| 4 | `src/knowledge_graph/topology/library.py` → `install_topologies()` — LDO + Buck Converter with parameterized `ScalingLaw` data on edges. **Schema and unit-tested only** — not called from any ingestion path, graph bootstrap, or `run_intent_pipeline()`. A graph with no explicit `install_topologies()` call has zero `TOPOLOGY` nodes. |
| 5 | `src/knowledge_graph/admin/methodologies.py` — `seed_default_methodologies()` |
| 5 | `src/knowledge_graph/constraints/__init__.py` → `persist_design_constraints()` — called from `run_intent_pipeline()` on every run; writes `DESIGN_CONSTRAINT` nodes |

Storage: `KnowledgeGraph` class in `src/knowledge_graph/graph.py` is now a
thin backward-compatible subclass of `NetworkXGraphBackend`
(`src/knowledge_graph/backends/networkx_backend.py`). All storage logic
lives behind the `GraphBackend` interface
(`src/knowledge_graph/backends/_interfaces.py`), selected via
`GraphBackendRegistry` and the `knowledge_graph.backend` config key
(default, and only registered option today: `"networkx"`). **Neo4j is
design-only** — `NEO4J_BACKEND_DESIGN.md` specifies the full backend, but
`GRAPH_BACKEND_REGISTRY` has no `"neo4j"` entry, no driver dependency is
installed, and selecting `"neo4j"` raises `ValueError` at registry
construction. `config.neo4j_uri` exists on `Config` but nothing reads it.

### Query timing

`query_graph()` in `src/knowledge_graph/query/__init__.py` does **not** run
immediately after intent parsing. Inside `run_intent_pipeline()` it runs
after Stage 1c (`run_completion_engine`), Stage 1d (`RetrievalEngine`), and
Stage 1e (`assert_interval_feasible` — a hard gate that can halt the
pipeline before `query_graph` is ever called). See Section 2's updated
diagram. It traverses from goal-mapped start nodes to produce a
`DesignSubgraph` scoped to the design methodology.

**Topology nodes are not yet reachable from this traversal:**
`goal_mapper._START_NODE_TYPES` in `src/knowledge_graph/query/goal_mapper.py`
maps goals to `(COMPONENT_TYPE, DESIGN_RECIPE)` nodes only — it does not
include `TOPOLOGY`. Even in a graph where `install_topologies()` has been
called, `query_graph()` will not surface `Topology`/`FunctionalBlock` nodes
in the resulting `DesignSubgraph` until `goal_mapper` is updated.

**RESOLVED 2026-07-06 (`DOC_DRIFT_AUDIT.md` N4):** `src/intent/interval_solver.py`
reads `intent.goal_topology` to select the LDO dropout-chain rule.
`src/intent/topology_classifier.py` now populates `goal_topologies` (and,
via `populate_goal_topology_compat()`, `goal_topology`) inside
`parse_intent()` — Stage 1 — using deterministic keyword matching at a
0.60 confidence threshold. This is proven to actually take effect through
the real pipeline in `tests/unit/intent/test_topology_pipeline_integration.py`:
an LDO-style prompt with an infeasible supply now correctly halts at the
Stage 2.75 gate with a named voltage/dropout conflict; boost- and
buck-boost-style prompts correctly skip that rule and proceed.

### KGNode → BOMEntry path

```
IntentDict.goal
    → goal_mapper.map_goal_to_nodes(goal, graph)
    → traversal.bfs_traverse(start_nodes, graph, max_depth=4, min_edge_confidence=0.60)
    → result_builder.build_subgraph(...) → DesignSubgraph.component_types[]

DesignSubgraph.component_types[i]  (KGNode, layer=2, label="ldo_regulator")
    → bom/selector.select_component(comp_type_node, subgraph, intent, counter)
        → _find_matching_instance() scans subgraph.component_instances (layer=3)
        → matching_instance.label → BOMEntry.specific_part  ("TPS7A20DRVR")
        → subgraph.path_confidences[comp_type_node.id] → BOMEntry.confidence  (0.92)
        → _get_value_constraints() from subgraph.design_rules edges → BOMEntry.value_constraints
        → _get_ref_prefix("ldo_regulator") → "U" + counter → BOMEntry.ref = "U1"
    → BOMEntry
```

If no matching instance exists: `specific_part=None`, confidence penalized ×0.85, `review_flag=True`.

---

## SECTION 8 — CONFIDENCE SCORES — END TO END

### 1. First assignment — P1 Phase 3 extraction

Per-field confidence originates in `ExtractedValue.confidence` during grid extraction (`src/datasheet/phase3_extract/extractor.py`). Grid-level confidence comes from Phase 2 `GridMatrix.confidence` (vector or VLM path winner).

Aggregate datasheet confidence computed in `src/datasheet/phase3_extract/__init__.py`:

```python
extraction_confidence = compute_extraction_confidence(
    method=extraction_result.extraction_method,      # P1_VECTOR or P1_VLM
    phase2_confidence=extraction_result.confidence,  # mean grid confidence
    phase3_field_coverage=field_coverage,            # extracted_fields / total_fields
)
```

Formula in `src/datasheet/utils.py` (weights: **40%** method base + **30%** phase2 + **30%** field coverage):

| `ExtractionMethod` | Base confidence (`EXTRACTION_METHOD_CONFIDENCE`) |
|---|---|
| `manual` | 1.0 |
| `p1_vector` | 0.97 |
| `p1_vlm` | 0.85 |
| `p1_phase5_nlp` | 0.80 |
| `llm_fallback` | 0.72 |

Example: `0.97×0.4 + 0.95×0.3 + 0.88×0.3 = 0.937` → stored as `ComponentDatasheet.extraction_confidence`.

### 2. Pin normalization confidence

Set per pin in `normalize_pins()`:
- Dictionary tier: **1.0**
- Context tier: **0.90**
- LLM tier: variable from `normalize_via_llm()`
- Failed: **0.0**, review flag added

Threshold in config: `confidence_thresholds.pin_normalization` = **0.70** (`configs/default.yaml`).

### 3. BOMEntry.confidence

Originates from `DesignSubgraph.path_confidences[comp_type_node.id]` in `select_component()`. Penalized ×**0.85** when no specific part resolved.

### 4. ValidatedBOM.total_confidence

Weighted aggregate via `score_bom()` in `src/bom/confidence_scorer.py`:

```
total = sum(entry.confidence × criticality_weight) / sum(criticality_weight)
```

Criticality weights: `ldo_regulator` = **2.0**; passives = **0.5**; default = **1.0**.

### 5. Review gate thresholds

From `configs/default.yaml` (read by `generate_bom()`):

| Threshold key | Value | Effect |
|---|---|---|
| `bom_total` | **0.85** | `ValidatedBOM.review_required=True` if below |
| `bom_component` | **0.75** | Per-entry trigger for `review_required` |

Phase 4 datasheet gate (hardcoded in validator): `extraction_confidence < 0.3` → BLOCK; `< 0.7` → WARN.

NIR gate: any CRITICAL `ReviewFlag` → `is_review_required()=True` (no numeric threshold).

### 6. NIR confidence fields

`assemble_nir()` in `src/nir/builder.py` maps:

```python
confidence_scores = {entry.ref: entry.confidence for entry in bom.components}
# e.g. {"U1": 0.92}

net_confidence = {net.net_name: net.net_confidence for net in schematic.netlist}
# e.g. {"VCC_3V3": 1.0, "GND": 1.0}

ComponentRef.datasheet_confidence = entry.confidence  # per component
```

Net confidence in schematic derives from mean `PinDefinition.normalization_confidence` via `_mean_confidence()` in `net_assigner.py` (default **0.5** if no confidence set).

### 7. Final design report

`generate_design_report()` computes aggregate via `_aggregate_confidence(nir)`:

```python
scores = [c.datasheet_confidence for c in nir.components] + [n.net_confidence for n in nir.netlist]
aggregate = sum(scores) / len(scores)
```

Report flags individual nets with `net_confidence < 0.75` (`_LOW_CONFIDENCE_THRESHOLD` in `doc_generator.py`) with `⚠ LOW` marker. BOM table shows per-component `datasheet_confidence` and `justification` with `source_citations`.

### Traceability chain (TPS7A20DRVR example)

```
PDF cell "3.3" → ExtractedValue.confidence=0.97
    → compute_extraction_confidence() → ComponentDatasheet.extraction_confidence=0.937
    → (separate track) KG path_confidence=0.92 → BOMEntry.confidence=0.92
    → score_bom() → ValidatedBOM.total_confidence=0.8912
    → assemble_nir() → NIR.confidence_scores["U1"]=0.92, ComponentRef.datasheet_confidence=0.92
    → normalize_pins() → PinDefinition.normalization_confidence=1.0
    → assign_power_nets() → NetlistEntry.net_confidence=1.0
    → generate_design_report() → report shows U1 confidence 0.92, nets at 1.00
```

Every value in the final BOM table, netlist summary, and component justification in the design report carries a numeric confidence and a source citation string traceable back to the KG traversal path and/or the P1 extraction pipeline.
