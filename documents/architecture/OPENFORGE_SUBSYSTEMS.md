# OpenForge PCB Intelligence System — Subsystems and Technical Problems

**Version:** 1.0
**Owner:** Systems Architecture Team
**Derives from:** OPENFORGE_ARCHITECTURE.md

---

## Overview

This document defines every major technical subsystem in OpenForge, including its scope, inputs, outputs, implementation strategy, required datasets, models, infrastructure, failure modes, and accuracy targets. Each section is written at implementation depth — a team receiving one of these subsystems should have enough information to begin engineering design immediately.

---

## S1: Datasheet Parsing (Problem 1 Extended)

### Scope

Extract all machine-readable data from component datasheets (PDF format): electrical characteristics tables, absolute maximum ratings, pinout tables, and — critically — the layout recommendations section. This is the primary data ingestion engine that feeds KG-3, KG-4, and the component database.

### Expanded Five-Phase Pipeline

#### Phase 1: Document Layout Analysis

**What it does:** Rasterizes PDF pages and uses an object detection model to locate and classify regions (Table, Footnote, Heading, Figure, Paragraph). Tables and footnotes are extracted as cropped image regions with their page bounding boxes.

**Implementation:**
- `pdf2image` + Poppler: rasterize at 300 DPI to PNG
- YOLOv8n fine-tuned on DocLayNet: 11-class document region detection
- Footnote linker: superscript regex (`\(\d+\)`, `\*`) + spatial proximity matching to produce `footnote_map`
- Section classifier: heading text + vertical position heuristic → `section_type` label per table crop
- Multi-page merger: column-count matching + header deduplication across page boundaries

**Outputs:** List of table crops (PNG bytes) with labels (`electrical_characteristics`, `absolute_maximum_ratings`, `pinout`, `timing`, `ordering`, `other`), footnote_map, section headings.

**Accuracy target:** Table recall ≥ 0.92, footnote linkage ≥ 0.85.

#### Phase 2: Table Structure Recognition (Dual Path)

**What it does:** Reconstructs the internal row/column matrix from a cropped table image using two parallel paths, selecting the winner by confidence scoring.

**Path A (Vector):** `pdfplumber` + `Camelot` lattice mode. Extracts explicit PDF vector lines. Deterministic and 100% accurate for fully bordered tables. Fails silently on borderless tables.

**Path B (VLM):** Qwen2-VL-7B-Instruct. The cropped table image is passed to the VLM with a prompt instructing it to return the table as a Markdown table. The Markdown is then parsed into a row/column matrix.

**Confidence scorer:** `score_grid()` evaluates each candidate on: cell count, empty cell ratio, header row detection, merged cell ratio, parse success. `pick_best_grid()` returns the higher-scoring candidate with its metadata attached.

**Merged cell handling:** Colspan and rowspan are stored as `(row, col, rowspan, colspan)` metadata alongside the filled matrix (None values for spanned cells).

**Accuracy target:** Cell-level accuracy ≥ 0.95, merged cell accuracy ≥ 0.90.

#### Phase 3: Constrained Semantic Extraction

**What it does:** Converts the raw grid text matrix into typed, unit-normalized, schema-validated Pydantic objects.

**Unit normalization:** Runs before LLM extraction. Converts all values to canonical units (mV → V, µA → mA, kΩ → Ω). Full conversion table handles OCR aliases (u vs µ, ohm vs Ω). Unknown units trigger a `review_required` flag, never a silent pass.

**LLM extraction:** Qwen2.5-7B-Instruct with Instructor-enforced JSON schema. Different system prompts per section type (electrical characteristics, absolute maximum ratings, pinout). See `prompt_templates.py`.

**Footnote injection:** The `footnote_map` from Phase 1 is passed as context. Any value cell containing a superscript marker gets the linked footnote text attached to its `ExtractedValue.footnote` field.

**Accuracy target:** Field-level F1 ≥ 0.93, unit normalization accuracy = 1.0 (unit errors are critical).

#### Phase 4: Physics Validation

**What it does:** Applies a rule engine to the extracted Pydantic objects to detect OCR errors, VLM hallucinations, and unit normalization bugs before they propagate downstream.

**Rule categories:**
- Min/typ/max ordering: min ≤ typ ≤ max, violations are CRITICAL
- Cross-parameter electrical rules: V_CC > V_IL, V_IH < V_CC, V_OL < V_IL
- Sanity ranges: each parameter type has a physical plausibility range (e.g., supply voltage 0.5V–40V)
- Absolute-max rules: abs-max ceiling must always exceed recommended operating max for the same parameter

**Routing:**
- All CRITICAL errors → block, escalate to human review
- Warnings only → pass with `review_required = True`
- All clear → forward to Phase 5

**Accuracy target:** FPR ≤ 0.02, FNR ≤ 0.01.

#### Phase 5: Layout Section Extraction (New)

**What it does:** Identifies and extracts the "PCB Layout Recommendations" or "Layout Guidelines" section from the datasheet, converting spatial placement language into structured `PlacementConstraint` objects for KG-4 ingestion.

**Detection:** Section classifier from Phase 1 labels these regions. If not detected via heading, a text search for "layout" within the last 30% of the document is used as fallback.

**Extraction:** Qwen2.5-7B-Instruct with a placement-specific system prompt. The prompt instructs the model to identify sentences containing spatial relationships and return them as structured `PlacementConstraint` objects:

```json
{
  "constraint_type": "proximity",
  "subject": "C_IN",
  "relative_to": "U1.VIN",
  "max_distance_mm": 2.0,
  "hard": true,
  "source_sentence": "Place C_IN within 2mm of the VIN pin"
}
```

Recognized spatial patterns:
- "Place X within N mm of Y" → proximity, hard constraint
- "Keep X as short as possible" → max_length hint
- "Maintain a keepout of N mm around X" → keepout constraint
- "Route X before Y" → routing order hint
- "Avoid routing X near Y" → isolation constraint
- "Place X on the same side as Y" → layer constraint

**Output:** List of `PlacementConstraint` objects, added to the `ComponentDatasheet.layout_constraints` field, and imported to KG-4 by `p1_importer.py`.

### Required Infrastructure

- GPU: NVIDIA A5000 or RTX 3090 (24GB VRAM)
- Poppler (apt package, baked into Docker image)
- Model weights: YOLOv8n-DocLayNet, Qwen2-VL-7B-Instruct, Qwen2.5-7B-Instruct
- Storage: 200GB NVMe for model weights + corpus

### Failure Modes and Mitigations

| Failure | Impact | Mitigation |
|---------|--------|-----------|
| VLM hallucination on borderless table | Wrong specs | Dual-path + Phase 4 physics validation |
| Footnote linkage failure | Silent constraint loss | Flag unlinked superscripts as `review_required` |
| Unit normalization edge case | 1000× value error | Full conversion table + sanity range check |
| Layout section not found | Missing KG-4 data for this component | Log warning, continue without layout constraints |
| Multi-page table truncation | Incomplete parameter set | Phase 1 multi-page merger with header dedup |

### Datasets Required

- 5 golden datasheets (hand-annotated ground truth JSON) — for development validation
- 25 test datasheets across component families — for evaluation
- Target component families: analog ICs, power management, op-amps, logic ICs (no MCUs or DSPs for MVP scope)

---

## S2: Pin Nomenclature Normalization (Problem 2)

### Scope

Normalize manufacturer-specific pin names to a canonical electrical function vocabulary. This is a prerequisite for cross-component connection synthesis: the schematic synthesizer cannot determine that a TI MCU's "GPIO0/UART_TX" should connect to an FTDI chip's "TXD" without a normalized intermediate representation.

### Implementation

**Tier 1 — Rule-based dictionary (target: covers 95%+ of real-world names):**

```python
PIN_NORMALIZATION_MAP = {
    # Power nets
    ("VDD", "VCC", "V+", "PVDD", "AVDD", "DVDD", "VIO", "VBAT"): "POWER_POSITIVE",
    ("GND", "VSS", "AGND", "DGND", "PGND", "GND_A", "GND_D"): "POWER_GROUND",
    ("VIN", "VIN+", "SUPPLY"): "POWER_INPUT",
    
    # SPI
    ("SCK", "SCLK", "CLK", "CK", "SPI_CLK"): "SPI_CLOCK",
    ("MOSI", "SDI", "DI", "COPI", "SPI_MOSI"): "SPI_DATA_IN",
    ("MISO", "SDO", "DO", "CIPO", "SPI_MISO"): "SPI_DATA_OUT",
    ("CS", "CSB", "SS", "NSS", "CE", "NCS"): "SPI_CHIP_SELECT",
    
    # I2C
    ("SDA", "I2C_SDA", "DAT"): "I2C_DATA",
    ("SCL", "I2C_SCL", "I2C_CLK"): "I2C_CLOCK",
    
    # UART
    ("TX", "TXD", "UART_TX", "TXO"): "UART_TRANSMIT",
    ("RX", "RXD", "UART_RX", "RXI"): "UART_RECEIVE",
    
    # Control signals
    ("EN", "ENABLE", "ENB", "EN_N"): "ENABLE",
    ("RST", "RESET", "NRST", "RST_N"): "RESET",
    ("INT", "IRQ", "INTERRUPT", "NIRQ"): "INTERRUPT",
    ("PWM", "PWM_OUT"): "PWM_OUTPUT",
    ("NC", "DNP"): "NO_CONNECT",
}
```

**Tier 2 — LLM fallback (for unknown or ambiguous names):**
- Qwen2.5-7B-Instruct with Instructor
- System prompt includes the canonical vocabulary list
- Model returns: `{"canonical": "SPI_CLOCK", "confidence": 0.87, "reasoning": "SCLK is a standard abbreviation for SPI clock"}`
- Confidence < 0.70 → flag for human review

**Tier 3 — Context-based resolution:**
- If a pin name is ambiguous (e.g., "CLK" could be I2C clock or SPI clock), use adjacent pin names in the pinout table as context
- Use the component type from the BOM to bias the resolution (an op-amp is unlikely to have SPI)

### Output

Every `PinDefinition` in every `ComponentDatasheet` gains:
```python
normalized_function: str        # "SPI_CLOCK", "POWER_POSITIVE"
normalization_confidence: float # 0.0–1.0
normalization_method: str       # "dictionary", "llm", "context", "manual"
```

### Accuracy Target

≥ 0.97 on the dictionary-covered set (measured by checking all known TI and ADI pin names in the corpus against the map). LLM fallback accuracy ≥ 0.85 on a held-out test set of 200 ambiguous pin names.

### Failure Modes

| Failure | Impact | Mitigation |
|---------|--------|-----------|
| Unknown pin name not in dictionary | Connection not synthesized | LLM fallback + human review flag |
| Ambiguous resolution (GPIO vs signal) | Wrong net assignment | Context-based resolution + confidence threshold |
| Multi-function pin (GPIO/UART_TX) | Pin assigned to wrong net | Parse alternate functions list, expose all options to schematic synthesizer |

---

## S3: Block Diagram Extraction (Problem 3)

### Scope

Extract functional topology from application note block diagrams and IC functional block diagrams using computer vision. The output is a graph of modules and connections that feeds KG-2 (design recipes) with reference circuit topologies not captured by table extraction alone.

### Implementation

**Detection:**
- Phase 1 DLA detects `Figure` regions in datasheets and app notes
- A secondary classifier (trained or prompted VLM) identifies which figures are block diagrams vs graphs vs waveforms
- Trigger: YOLOv8 `Figure` label + Qwen2-VL-7B classification prompt: "Is this a block diagram, circuit schematic, waveform, or other?"

**Extraction:**
- Qwen2-VL-7B-Instruct with a topology extraction prompt
- Prompt instructs: "List all named blocks/components in this diagram and all connections between them"
- Output schema:
```json
{
  "nodes": [
    {"id": "MCU", "type": "microcontroller", "label": "CC2640R2F"},
    {"id": "ANT", "type": "antenna", "label": "2.4GHz antenna"}
  ],
  "edges": [
    {"from": "MCU", "to": "ANT", "label": "RF_output", "via": "matching_network"}
  ]
}
```

**KG Integration:**
- `graph_builder.py` converts extracted topology → KG-2 edges
- Each edge is a `connects_to` or `requires` edge with `source` pointing to the app note
- Confidence = 0.75 (VLM extraction), manual review bumps to 0.95

### Accuracy Target

≥ 0.80 topology node recall on 10 manually reviewed app note diagrams. Edge recall ≥ 0.70 (connections are harder to extract reliably).

### Failure Modes

| Failure | Impact | Mitigation |
|---------|--------|-----------|
| Low-resolution figure in PDF | VLM cannot read labels | Upsample to 600 DPI before VLM pass |
| Cluttered diagram with overlapping labels | Missed nodes/edges | Flag for manual review when confidence < 0.70 |
| Non-standard block diagram style | Topology not extractable | Fall through gracefully, log as unextracted |

---

## S4: Knowledge Graph Construction (Problem 4)

### Scope

Build, maintain, and query the five-layer Knowledge Graph. This is the central engineering authority of the system. Every design decision traces through the KG.

### Ingestion Sub-Pipelines

**KG-1 Ingestion (All About Circuits):**

`scraper_aac.py`:
- Downloads chapter HTML from allaboutcircuits.com/textbook, Vols 1–5
- Cleans to plain text (removes navigation, ads, code blocks)
- Stores with content hash to detect changes

`triple_extractor.py`:
- spaCy en_core_web_trf: tokenize, POS, dependency parse
- Extract Subject-Verb-Object triples from each sentence
- Filter for engineering-relevant triples (both S and O are electrical concepts)
- Ambiguous cases → Qwen2.5-7B-Instruct: "What is the relationship between X and Y in this sentence?"
- Output: JSONL stream of `(subject, relation, object, sentence, source_url, confidence)`
- Map relations to KG edge vocabulary (→ `requires`, `uses`, `has_property`, `is_a`)

`kg_builder.py`:
- Deduplicates nodes by label (canonical form)
- Merges edge confidences when the same fact appears in multiple sources (raises confidence)
- Persists to NetworkX (GraphML) for prototype, Neo4j for production

**KG-2 Ingestion (App Notes):**

`scraper_appnotes.py`:
- Maintains a `sources.yaml` with URL patterns for TI, ADI, Murata app note portals
- Downloads PDFs filtered by topic tags (RF, power, mixed-signal)
- Stores PDF hash + download date

App note ingestion runs two passes:
1. P1 parser (Phases 1–4): extracts tables → `DesignRecipe` nodes with quantitative values
2. `prose_extractor.py`: NLP on non-table text sections
   - Design rule patterns: "For X design, use Y" → `uses` or `requires` edge with quantitative constraint
   - Placement patterns: spatial language → KG-4 `PlacementRule` nodes (see `placement_extractor.py`)

**KG-3 Ingestion (P1 Output):**

`p1_importer.py`:
- Reads `ComponentDatasheet` JSON
- Creates `ComponentInstance` node with all electrical properties
- Creates `Pin` nodes with normalized names (P2 output)
- Creates `connects_to` edges from Pin → NetType (using P2 canonical vocabulary)
- Creates `requires` edges from component instance → required passives (from datasheet notes and app note cross-references)

**KG-4 Ingestion (Layout Rules):**

Two sources:
1. P1 Phase 5 output: `PlacementConstraint` objects from datasheet layout sections
2. IPC-2221 table extraction: trace width vs current tables → `RoutingRule` nodes

`src/knowledge_graph/ingestion/kg2_appnotes/prose_extractor.py` (app notes;
this file was previously misnamed `placement_extractor.py` in this
document — that filename never existed, corrected 2026-07-06 per
`DOC_DRIFT_AUDIT.md` N13):
- Receives plain text from prose sections of app notes
- Extracts sentences containing: "place", "near", "away", "within", "avoid", "keepout", "route", "shortest"
- Passes to Qwen2.5-7B with schema-enforced output → `PlacementConstraint` objects

**KG-5 Ingestion (Methodology Rules):**

Manual entry only. CLI tool:
```
python -m src.knowledge_graph.admin add-methodology \
    --name RF_highfreq \
    --triggers "antenna,RF,2.4GHz,5GHz,Bluetooth,WiFi" \
    --active-rules "RF_keepout,50ohm_trace,ground_plane_continuity" \
    --suppresses "standard_proximity_defaults"
```

### Query Engine Design

> Corrected 2026-07-06 (`DOC_DRIFT_AUDIT.md` N10): there is no
> `KGQueryEngine` class anywhere in `src/`. The query engine is a set of
> plain functions in `src/knowledge_graph/query/`, with `query_graph()` as
> the single public entry point (see `OPENFORGE_ARCHITECTURE.md` §11 and
> `SYSTEM_WHITEBOX_TRACE.md` §7). The pseudocode below described the
> *intended* design at the time; the actual module layout is:

```python
# src/knowledge_graph/query/__init__.py
def query_graph(intent: IntentDict, graph: KnowledgeGraph, config: Config) -> DesignSubgraph:
    # Step 1: map goal string to start nodes — src/knowledge_graph/query/goal_mapper.py
    start_nodes = goal_mapper.map_goal_to_nodes(intent.goal, graph)

    # Step 2: load methodology node (KG-5) — active_constraint_types, not "active_rules"
    methodology_node = graph.get_node(f"design_methodology:{intent.design_methodology.value}")

    # Step 3: BFS traversal — src/knowledge_graph/query/traversal.py
    path_confidences, traversed_edges = traversal.bfs_traverse(
        start_nodes, graph, max_depth=config.kg_traversal_max_depth,
        min_edge_confidence=config.kg_min_edge_confidence,
    )

    # Step 4: apply frequency filter (±20% of intent.frequency), inline in query/__init__.py
    if intent.frequency is not None:
        path_confidences = _apply_frequency_filter(path_confidences, intent.frequency, graph)

    # Step 5: assemble DesignSubgraph, applying methodology filter —
    # src/knowledge_graph/query/result_builder.py + methodology_filter.py
    return result_builder.build_subgraph(
        path_confidences, traversed_edges, graph, methodology_node,
        design_methodology=intent.design_methodology.value,
        query_depth=config.kg_traversal_max_depth,
    )
```

### Graph Consistency Validation

`validator.py` checks:
- No orphaned nodes (every node has at least one edge)
- No circular `requires` dependencies (A requires B requires A)
- Confidence values in [0, 1]
- Required fields populated for each node type
- Cross-layer consistency (ComponentInstance in KG-3 must have a corresponding ComponentType in KG-1 or KG-2)

### Storage Evolution

| Phase | Technology | When | Trigger |
|-------|-----------|------|---------|
| Prototype | NetworkX (in-memory, GraphML file) | Phase 0–1 build | Start here — no setup |
| Production | Neo4j (Docker sidecar) | Phase 2 build | When graph exceeds 100K nodes or team needs Cypher queries |
| Semantic search | FAISS index over node embeddings | After KG-1 complete | When "find similar components" use case is needed |

### Failure Modes

| Failure | Impact | Mitigation |
|---------|--------|-----------|
| Low triple extraction precision | Bad edges in KG → wrong BOM | Spot-check 50 triples per source before ingestion |
| Source format changes (AAC redesign) | Scraper breaks | Content hash detection + alert |
| KG-3 contradicts KG-2 (specific part rule overrides recipe) | Conflicting design decisions | KG-3 always wins over KG-2 for the same parameter; make explicit in query engine |
| Large graph traversal too slow | Query latency in production | Depth limit of 4, methodology filter applied early, cache common query paths |

---

## S5: Intent Understanding

### Scope

Transform a free-form natural language design specification into a structured `IntentDict` that the KG query engine can process. Detect design methodology, extract constraints, infer implicit requirements, and flag ambiguities that need clarification.

### Implementation

**Primary model:** Qwen2.5-7B-Instruct with Instructor-enforced JSON output schema.

**System prompt structure:**
1. Explain the output schema (goal, frequency, application, constraints, methodology, ambiguities)
2. Provide the methodology classification rules as a lookup table
3. List examples of implicit constraint inference (drone → compact, lightweight; medical → high reliability, galvanic isolation)
4. Instruct to flag every ambiguity (component names not in vocabulary, conflicting constraints, underspecified requirements)

**IntentDict schema:**
```python
class IntentDict:
    goal: str                         # "patch_antenna", "LDO_regulator", "motor_driver"
    frequency: Optional[FrequencySpec]
    application: str                  # "drone", "IoT sensor", "industrial motor control"
    explicit_constraints: list[str]   # directly stated in prompt
    inferred_constraints: list[str]   # inferred from application context
    design_methodology: str           # "RF_highfreq" | "power_management" | "mixed_signal" | "standard_SMD" | "through_hole"
    board_type: str                   # "double_sided_SMD" | "4_layer" | "through_hole"
    ambiguities: list[AmbiguityFlag]  # items needing clarification
    clarification_required: bool      # true if any CRITICAL ambiguity present
```

**Clarification flow:** If `clarification_required = True`, the pipeline pauses and presents ambiguity questions to the engineer before proceeding. The clarified responses are merged back into the intent dict.

### Failure Modes

| Failure | Impact | Mitigation |
|---------|--------|-----------|
| Methodology misclassification | Wrong rule set applied to entire design | Human review gate at BOM output checks consistency |
| Over-inferring constraints from vague prompt | Unnecessary constraints limit component selection | All inferred constraints marked `"inferred"` and presented to engineer for confirmation |
| Hallucinated goal mapping | Query engine receives nonsense start node | Map result validated against KG node vocabulary before proceeding |

---

## S6: BOM Generation

### Scope

Convert the design subgraph returned by the KG query engine into a specific, validated, justified bill of materials. This is where abstract design knowledge becomes a concrete list of parts.

### Component Selection Logic

```
For each ComponentType node in design_subgraph:
    1. Check KG-3 for recommended ComponentInstance nodes
       (direct "recommends" or "is_example_of" edges)
    2. If specific part found:
       → Use it, confidence = KG edge confidence
    3. If no specific part:
       → Output ComponentType with constraint envelope
       → Set specific_part = null
       → Set review_flag = true (engineer must select specific part)
    4. Check for alternative parts:
       → Traverse "replaces" edges from selected component
       → List alternatives with confidence scores
    5. Apply BOM-level constraints:
       → Verify voltage compatibility across all power components
       → Verify logic level compatibility (3.3V vs 5V systems)
       → Verify package compatibility (if board size constraint specified)
```

### Confidence Scoring

```python
def score_bom(bom: ValidatedBOM) -> float:
    """
    Aggregate confidence across all BOM components.
    Weighted by component criticality (power ICs weighted higher than passives).
    """
    component_scores = []
    for comp in bom.components:
        path_confidence = design_subgraph.get_path_confidence(comp.ref)
        specificity_penalty = 0.0 if comp.specific_part else 0.15
        component_scores.append({
            "ref": comp.ref,
            "score": path_confidence - specificity_penalty,
            "weight": COMPONENT_CRITICALITY.get(comp.component_type, 1.0)
        })
    return weighted_average(component_scores)
```

### Human Review Gate Logic

```
if bom.total_confidence < 0.85:
    → route entire BOM to review queue
elif any(c.confidence < 0.75 for c in bom.components):
    → route individual low-confidence components to review
elif any(c.specific_part is None for c in bom.components):
    → route unresolved components to review (engineer selects specific part)
else:
    → pass BOM to L3 (datasheet fetch)
```

### Supplier Integration (Air-Gapped)

Since the system is air-gapped, real-time supplier queries (Octopart, Digi-Key API) are not available. Instead:
- A cached supplier database is maintained locally, updated via periodic offline snapshots
- Availability and pricing data is approximate and stamped with the cache date
- If no cached data exists for a component, the BOM entry is flagged: "Availability: unknown — verify before procurement"

### Failure Modes

| Failure | Impact | Mitigation |
|---------|--------|-----------|
| No KG-3 entry for required component type | No specific part suggested | Review gate + engineer selects manually |
| KG recommends obsolete part | Procurement failure | Supplier cache staleness check + alternatives list |
| Conflicting BOM constraints (voltage incompatibility) | Nonfunctional design | BOM-level cross-validation before human gate |

---

## S7: Schematic Synthesis (Problem 5)

### Scope

Generate a complete electrical netlist by determining every pin-to-pin connection across all components in the BOM. This is the hardest technical problem in the system.

### Connection Synthesis Algorithm

**Step 1 — Power net assignment:**
All pins with canonical function `POWER_POSITIVE` → single VCC net (or named supply net if multiple voltage domains exist). All `POWER_GROUND` → GND. Supply nets named by voltage: `VCC_3V3`, `VCC_5V`, `VCC_1V8`.

If the BOM contains a voltage regulator: its output net feeds the VCC net of downstream components. The regulator's input feeds from the highest available supply.

**Step 2 — Protocol-based signal matching:**

For each communication protocol (SPI, I2C, UART, CAN, I2S):
- Identify all components in the BOM that have pins in that protocol's canonical vocabulary
- Assign one component as master (typically the MCU), others as slaves
- Connect: SPI_CLOCK on master → SPI_CLOCK on all slaves (shared net)
- Connect: SPI_DATA_IN on slave → SPI_DATA_OUT on master and vice versa
- Chip selects: SPI_CHIP_SELECT on each slave → unique GPIO on master

**Step 3 — KG-3 explicit rules:**

Query KG-3 for `connects_to` edges on each component instance. These are explicit rules extracted from datasheets:
- "TPS62933.FB connects to voltage divider output" → add voltage divider to BOM if not present, create FB net
- "CC2640R2F.RF_P requires matching network at RF output" → connect RF_P to matching network input

**Step 4 — Passive component assignment:**

For each decoupling/bypass/filter capacitor in the BOM:
- Query KG-4 placement rules to determine which IC pin it belongs to
- Query KG-3 for the specific capacitor value and placement
- Create a named net: `VCC_U1_BYPASS` for C1 across U1.VCC to GND

**Step 5 — Block topology assembly:**

Group components into functional blocks based on KG-2 `part_of` edges:
- Power block: voltage regulators, power capacitors, inductors
- MCU block: MCU + oscillator + decoupling
- RF block: antenna + matching network + RF IC + RF passives
- Sensor block: sensor ICs + conditioning passives

**Step 6 — ERC pre-check:**

```python
ERC_RULES = [
    # No two output pins on the same net
    lambda netlist: check_no_output_conflict(netlist),
    # No power net without a driver
    lambda netlist: check_power_net_driven(netlist),
    # No required pin left unconnected
    lambda netlist: check_required_pins_connected(netlist),
    # No incompatible logic levels on the same net
    lambda netlist: check_logic_level_compatibility(netlist),
    # No floating inputs (inputs with no driver)
    lambda netlist: check_no_floating_inputs(netlist),
]
```

### Schematic Graph Output

```python
class SchematicGraph:
    nets: list[NetlistEntry]
    blocks: list[FunctionalBlock]
    erc_result: ERCResult         # pass/fail + error list
    synthesis_confidence: float
    unresolved_pins: list[PinRef] # pins that could not be connected
    review_flags: list[ReviewFlag]
```

### Failure Modes

| Failure | Impact | Mitigation |
|---------|--------|-----------|
| No KG rule for a required connection | Pin left unconnected | Flagged in ERC + routed to human review |
| Conflicting protocol assignments | Two masters on same SPI bus | Protocol conflict detector in Step 2 |
| Logic level mismatch (5V to 3.3V) | Wrong component specification | ERC rule + level shifter auto-suggestion |
| Missing passive in BOM | Synthesis tries to assign nonexistent component | BOM feedback loop: synthesizer can request BOM additions |

---

## S8: PCB Layout Engine

### Scope

Generate a layout specification — placement constraints and routing hints — from the schematic graph, component data, and KG-4 rules. This engine does not perform autorouting. Autorouting is delegated to KiCad and tscircuit. The layout engine's job is to codify every constraint that those tools must satisfy.

### Placement Constraint Generation

**Source 1 — KG-4 rules (general placement):**
Every component type has placement rules in KG-4. These are methodology-filtered (RF_highfreq rules apply to the RF block, power_management rules apply to the power block).

**Source 2 — P1 Phase 5 output (component-specific):**
Each datasheet's layout section is already extracted as `PlacementConstraint` objects by the time the layout engine runs. These are the highest-confidence constraints (they come from the manufacturer).

**Source 3 — Functional block grouping:**
Components in the same functional block (schematic synthesizer output) get a `group` constraint: keep_together = True. The block itself may have a `must_avoid` constraint relative to other blocks (RF block must avoid power switching block).

**Constraint priority:**
1. Component-specific (P1 Phase 5) — highest priority, hard constraints
2. KG-4 methodology-governed rules — hard if methodology is active
3. Block grouping constraints — soft, can be overridden by engineer

### Routing Hint Generation

```python
ROUTING_HINT_GENERATORS = {
    "RF_net": lambda net, methodology: generate_impedance_hint(net, substrate_params),
    "differential_pair": lambda net, _: generate_length_match_hint(net),
    "high_current": lambda net, _: generate_min_width_hint(net, current_rating),
    "clock": lambda net, _: generate_isolation_hint(net, adjacent_analog_nets),
    "power": lambda net, _: generate_copper_pour_hint(net),
}

def generate_impedance_hint(net, substrate_params) -> RoutingHint:
    # Microstrip 50Ω formula: W = (87 / sqrt(εr + 1.41)) * ln(5.98*H / (0.8*W + T))
    # Solve for W given H (substrate thickness), T (copper thickness), εr
    trace_width = solve_microstrip_width(
        target_impedance=50.0,
        substrate_height=substrate_params.thickness,
        copper_thickness=substrate_params.copper_weight_oz * 0.035,  # oz to mm
        permittivity=substrate_params.dielectric_constant
    )
    return RoutingHint(
        nets=[net.name],
        hint_type="impedance_controlled",
        value=trace_width,
        unit="mm",
        note=f"50Ω microstrip width for {substrate_params.material}"
    )
```

### Board Specification Determination

```python
METHODOLOGY_BOARD_SPECS = {
    "RF_highfreq": BoardSpec(layers=2, material="Rogers_4003C", min_trace_mm=0.1, min_clearance_mm=0.1),
    "power_management": BoardSpec(layers=2, material="FR4", min_trace_mm=0.2, min_clearance_mm=0.2),
    "mixed_signal": BoardSpec(layers=4, material="FR4", min_trace_mm=0.1, min_clearance_mm=0.15),
    "standard_SMD": BoardSpec(layers=2, material="FR4", min_trace_mm=0.15, min_clearance_mm=0.15),
    "through_hole": BoardSpec(layers=2, material="FR4", min_trace_mm=0.25, min_clearance_mm=0.25),
}
```

### Failure Modes

| Failure | Impact | Mitigation |
|---------|--------|-----------|
| Conflicting placement constraints | DRC violation in output tool | Constraint conflict detector: hard constraints from higher-priority source win |
| Missing substrate parameters | Impedance calculation fails | Use FR4 defaults, flag for engineer review |
| Component group size too large for board estimate | Unrealistic placement | Log warning, allow engineer to override board dimensions |

---

## S9: Verification and Validation

### Scope

Validate the system's output at every stage boundary and at the final NIR level. Produce a validation report for each design.

### Stage-Level Validation

| Stage | Validator | Checks |
|-------|----------|--------|
| P1 Phase 4 | `physics_validator.py` | Min/typ/max ordering, cross-param rules, sanity ranges |
| BOM Generator | `bom_validator.py` | Voltage compatibility, logic level, package availability |
| Schematic Synthesizer | `erc.py` | Output conflicts, power net drivers, floating inputs, level mismatch |
| Layout Engine | `layout_validator.py` | Constraint conflicts, board spec feasibility |
| NIR Builder | `nir_validator.py` | Structural consistency, reference integrity, confidence aggregation |
| Post-KiCad | KiCad ERC/DRC | Electrical and design rules in generated schematic/PCB |
| Post-tscircuit | tscircuit validation | Connectivity and footprint checks |

### NIR-Level Validation

```python
NIR_VALIDATION_RULES = [
    # Structural
    "Every ref in netlist must exist in components",
    "Every net must have at least 2 pin connections",
    "Every power net must have exactly 1 source pin",
    "Every placement constraint ref must exist in components",
    
    # Confidence
    "Aggregate confidence must be computable for all components",
    "Any component with confidence < 0.60 must have a review flag",
    
    # Cross-validation
    "BOM component count must equal components list length",
    "All ERC-passing nets from schematic synthesizer must appear in netlist",
    "All hard placement constraints must reference valid component refs",
]
```

### Validation Output

```python
class ValidationReport:
    design_id: str
    overall_passed: bool
    stage_results: dict[str, StageValidationResult]
    critical_errors: list[str]    # block all downstream use
    warnings: list[str]           # allow with human review
    review_required: bool
    aggregate_confidence: float
    generated_at: str
```

---

## S10: Output Serializers

### S10a: KiCad MCP Serializer

**What it does:** Converts the NIR into KiCad files by calling the KiCad MCP server's tools.

**Token optimization strategy (P6):**
- Do not pass the entire NIR in one LLM context — the KiCad MCP server's LLM context would overflow
- Instead, call MCP tools directly with structured data, not through a conversational LLM interface
- Each MCP tool call is a deterministic operation: `add_component(ref, footprint, value)`, `add_wire(net, pin1, pin2)`
- The serializer generates the MCP call sequence from the NIR without any LLM involvement

**Serialization sequence:**
1. Create new schematic: `mcp.create_schematic(design_id)`
2. Add symbols: for each component in NIR → `mcp.add_symbol(ref, library, value, footprint)`
3. Add wires: for each net in NIR → for each pair of pins → `mcp.add_wire(from_pin, to_pin)`
4. Add power symbols: for each power net → `mcp.add_power_symbol(net_name)`
5. Run ERC: `mcp.run_erc()` → capture result
6. Create PCB: `mcp.create_pcb(board_spec)`
7. Place components: for each component + placement constraints → `mcp.place_component(ref, x, y, layer, rotation)`
8. Apply routing hints: `mcp.set_routing_constraint(net, hint_type, value)`
9. Run DRC: `mcp.run_drc()` → capture result
10. Export outputs: Gerber files, drill files, BOM CSV

### S10b: tscircuit Serializer

**What it does:** Converts the NIR into tscircuit's JSON circuit format and generates schematic SVG and 3D PCB model.

**tscircuit component mapping:**

```python
TSCIRCUIT_COMPONENT_MAP = {
    "resistor": lambda c: f'<resistor name="{c.ref}" resistance="{c.value}" footprint="{c.footprint}" />',
    "capacitor": lambda c: f'<capacitor name="{c.ref}" capacitance="{c.value}" footprint="{c.footprint}" />',
    "inductor": lambda c: f'<inductor name="{c.ref}" inductance="{c.value}" footprint="{c.footprint}" />',
    "chip": lambda c: f'<chip name="{c.ref}" footprint="{c.footprint}" />',
    "power_source": lambda c: f'<power_source name="{c.ref}" voltage="{c.value}" />',
}
```

**tscircuit circuit format:**

```typescript
// Generated by OpenForge tscircuit serializer
// Design: {design_id}
// Prompt: {original_prompt}

import { Circuit, Resistor, Capacitor, Chip, PowerSource } from "@tscircuit/core"

export const circuit = new Circuit()

// Components
circuit.add(<Chip name="U1" footprint="SOT-23-5" />)
circuit.add(<Capacitor name="C1" capacitance="10uF" footprint="0402" />)

// Connections
circuit.connect("U1.VIN", "C1.pos")
circuit.connect("C1.neg", ".GND")

// Placement hints
circuit.place("C1", { near: "U1.VIN", maxDistance: "2mm" })
```

**Outputs:**
- `.tsx` file: React component with circuit definition
- `schematic.svg`: rendered schematic via tscircuit CLI
- `pcb_3d.glb`: 3D PCB model via tscircuit CLI
- `circuit.json`: JSON representation of the circuit

### S10c: Documentation Generator

**Outputs from NIR:**
- BOM as formatted table with justifications and source citations
- Schematic description (functional block summary)
- Design decisions log (every KG-sourced decision with source document)
- Validation report (all ERC/DRC results)
- Human review actions taken
- Confidence summary

Format: Markdown → PDF via `weasyprint` or `pandoc` (both available offline).

---

*Consult OPENFORGE_ARCHITECTURE.md for the system context this document operates within. Consult OPENFORGE_ORGANIZATION.md for team ownership of each subsystem.*
