# OpenForge PCB Intelligence System — Master Architecture

**Version:** 1.0
**Owner:** Systems Architecture Team
**Status:** v1 — Implementation Reference

---

## 1. Mission Statement

OpenForge is an end-to-end, air-gapped, intelligence-driven PCB design system. Given a natural language prompt such as "build a 2.4GHz patch antenna for a drone," the system autonomously determines the required components, generates a justified bill of materials, synthesizes a schematic, produces a layout-ready PCB specification, and outputs fabrication-ready files in both KiCad and tscircuit formats — with every design decision traceable to authoritative engineering sources.

The system is built for defense-grade accuracy. Every value in every output carries a provenance chain: which source document it came from, which extraction method produced it, and what confidence score the system assigned it. No value is generated without grounding in an authoritative source.

---

## 2. Reframed Objectives

The six original engineering problems from `objectives.md` remain intact but are now sub-problems within the PCB Builder product. The PCB Builder is the product. P1 through P6 are implementation dependencies it requires solved.

| Original Problem | PCB Builder Role | Priority |
|-----------------|-----------------|---------|
| P1 — Datasheet Parsing | Data ingestion engine that feeds KG-3 and KG-4 | Critical path — must complete first |
| P2 — Pin Nomenclature Normalization | Enables cross-component net synthesis in schematic generator | Required before schematic synthesis |
| P3 — Block Diagram CV Extraction | Extracts reference circuit topologies from app note diagrams into KG-2 | Parallel track, high value |
| P4 — Knowledge Graph Construction | The authoritative engineering brain of the entire system | Critical path |
| P5 — Cross-Component Connection Synthesis | Schematic synthesizer — generates netlist from KG + component data | Depends on P1, P2, P4 |
| P6 — KiCad MCP Integration | Extended to include tscircuit as co-equal output target | Depends on P5 |

---

## 3. End-to-End System Flow

```
User Input — Natural Language Prompt
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  L0: Intent Parser                                          │
│  Qwen2.5-7B-Instruct + Instructor                          │
│  Extracts: goal, frequency, application, constraints        │
│  Classifies: design methodology                             │
│  Output: intent_dict (JSON)                                 │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  L1: Knowledge Graph Query Engine                           │
│  Neo4j / NetworkX                                           │
│  Traverses 5-layer KG with intent_dict                      │
│  Returns: design_subgraph with confidence scores            │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  L2: BOM Generator                                          │
│  Converts subgraph → specific component list                │
│  Applies confidence scoring                                 │
│  ── HUMAN REVIEW GATE (if confidence < 0.85) ──            │
│  Output: validated_bom (JSON)                               │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  L3: Datasheet Fetcher + P1 Parser (5-Phase Pipeline)       │
│  Phase 1: Document Layout Analysis (YOLOv8n-DocLayNet)      │
│  Phase 2: Table Structure Recognition (pdfplumber + Qwen2-VL)│
│  Phase 3: Semantic Extraction (Qwen2.5-7B + Instructor)     │
│  Phase 4: Physics Validation (rule engine)                  │
│  Phase 5: Layout Section Extraction (Qwen2.5-7B + NLP)     │
│  Output: ComponentDatasheet JSON per component              │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  L4: Pin Normalizer (P2)                                    │
│  Rule-based dictionary + Qwen2.5-7B fallback               │
│  VDD/VCC/V+/AVDD → POWER_POSITIVE                          │
│  SCK/SCLK/CLK → SPI_CLOCK                                  │
│  Output: normalized pin names on all ComponentDatasheet      │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  L5: Schematic Synthesizer (P5)                             │
│  Power net assignment                                       │
│  Protocol matching (SPI, I2C, UART, GPIO)                  │
│  KG-3 rule application                                      │
│  Passive component assignment                               │
│  Block topology assembly                                    │
│  ERC pre-check                                              │
│  ── HUMAN REVIEW GATE (on ERC errors) ──                   │
│  Output: schematic_graph (netlist + block topology)         │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  L6: Layout Engine                                          │
│  Placement constraint generation (KG-4 + Phase 5 output)   │
│  Routing hint generation (impedance, length match, width)   │
│  Design methodology rule application (KG-5)                 │
│  Component grouping by functional block                     │
│  Board spec determination                                   │
│  Output: layout_spec (placement constraints + routing hints)│
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  L7: NIR Builder + Validator                                │
│  Assembles Neutral Intermediate Representation              │
│  Cross-validates: BOM ↔ netlist ↔ placement                │
│  Runs structural consistency checks                         │
│  ── HUMAN REVIEW GATE (on CRITICAL validation errors) ──   │
│  Output: neutral_pcb_representation (NIR JSON)              │
└──────────┬────────────────────────────────┬────────────────┘
           │                                │
           ▼                                ▼
┌─────────────────────┐        ┌─────────────────────────────┐
│  L8a: KiCad MCP     │        │  L8b: tscircuit Serializer  │
│  Serializer         │        │                             │
│  .kicad_sch         │        │  .tsx circuit component     │
│  .kicad_pcb         │        │  JSON circuit format        │
│  BOM .csv           │        │  SVG schematic render       │
│  Gerber files       │        │  3D PCB model               │
│  via KiCad MCP      │        │  via tscircuit CLI/API      │
└─────────────────────┘        └─────────────────────────────┘
           │                                │
           └──────────────┬─────────────────┘
                          ▼
              ┌───────────────────────┐
              │  L8c: Documentation   │
              │  Generator            │
              │  Design review PDF    │
              │  BOM with sources     │
              │  Justification report │
              └───────────────────────┘
```

---

## 4. Knowledge Base Architecture

### 4.1 Five-Layer Knowledge Graph

The Knowledge Graph is the engineering brain of OpenForge. Every design decision made by the BOM generator, schematic synthesizer, and layout engine is traceable to a specific KG edge, which is traceable to a specific source document.

| Layer | Name | Source | Node Types | Edge Types |
|-------|------|--------|-----------|------------|
| KG-1 | Physics & Principles | All About Circuits Vols 1–5 | PhysicsConcept | requires, is_a, has_property |
| KG-2 | Design Recipes | TI/ADI/Murata app notes | DesignRecipe, ComponentType | uses, part_of, connects_to, requires |
| KG-3 | Component Rules | P1 parser output (electrical tables + pinouts) | ComponentInstance, Pin, Net | connects_to, requires, has_property |
| KG-4 | Placement & Routing | Datasheet layout sections + IPC-2221 + app note layout prose | PlacementRule, RoutingRule | must_be_near, must_avoid, requires_routing |
| KG-5 | Design Methodology | Expert-curated rules | DesignMethodology | governed_by, overrides, incompatible_with |

### 4.2 Complete Node Schema

```python
class KGNode:
    id: str                   # globally unique, e.g. "component_type:patch_antenna"
    node_type: Literal[
        "physics_concept",    # resistor, antenna, impedance, resonance
        "component_type",     # patch_antenna, LDO_regulator, bypass_capacitor
        "component_instance", # TPS62933DRLR, CC2640R2F — specific parts
        "design_recipe",      # 2.4GHz_patch_antenna, half_bridge_driver
        "electrical_property",# 50_ohm_impedance, 3.3V_supply
        "placement_rule",     # proximity_constraint, keepout_zone, layer_assignment
        "routing_rule",       # impedance_controlled, differential_pair, min_width
        "design_methodology", # RF_highfreq, power_management, mixed_signal, through_hole
        "net_type",           # power_net, signal_net, RF_net, differential_pair_net
        "standard",           # IPC-2221, IPC-7351, IPC-2581
        "pin"                 # specific pin on a component instance
    ]
    layer: int                # 1–5
    label: str                # human-readable name
    properties: dict          # type-specific attributes
    source: str               # document URL or filename
    confidence: float         # 0.0–1.0
    extraction_method: Literal["manual", "nlp_triple", "p1_parser", "vlm", "rule_based"]
    created_at: str           # ISO 8601
```

### 4.3 Complete Edge Schema

```python
class KGEdge:
    source_id: str
    relation: Literal[
        "requires",           # component A requires component/property B
        "uses",               # design recipe uses a component type
        "has_property",       # component has an electrical property
        "connects_to",        # pin or net connects to another pin or net
        "must_be_near",       # placement proximity: A must be within N mm of B
        "must_avoid",         # keepout: A must not be within N mm of B
        "is_a",               # taxonomy: patch_antenna is_a antenna
        "governed_by",        # component A is governed by methodology B
        "requires_routing",   # net requires a specific routing rule
        "part_of",            # component is part of a design recipe
        "replaces",           # component A can substitute for B (same function)
        "incompatible_with",  # A and B cannot be directly connected
        "overrides",          # methodology rule overrides a default rule
        "feeds_into"          # subsystem output feeds into subsystem input
    ]
    target_id: str
    constraints: dict         # {"value": "2.0", "unit": "mm", "condition": "always"}
    source_document: str      # where this edge came from
    confidence: float
    layer: int
```

### 4.4 Knowledge Graph Ingestion Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│  Source 1: All About Circuits (KG-1)                            │
│  scraper_aac.py → BeautifulSoup, chapter-by-chapter HTML       │
│  triple_extractor.py → spaCy SVO parsing + Qwen2.5-7B          │
│  Output: PhysicsConcept nodes + requires/is_a/has_property edges│
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Source 2: TI/ADI App Notes (KG-2 + KG-4)                      │
│  scraper_appnotes.py → topic-filtered PDF downloader            │
│  P1 parser → table extraction → DesignRecipe + property edges   │
│  prose_extractor.py → NLP on text sections:                     │
│    - Design rule sentences → KG-2 DesignRecipe edges            │
│    - Placement language ("place near", "keep away") → KG-4      │
│  Output: DesignRecipe nodes + ElectricalProperty + PlacementRule│
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Source 3: Component Datasheets (KG-3 + KG-4)                  │
│  P1 parser (Phases 1–4) → ComponentInstance + Pin + connects_to │
│  P1 Phase 5 → layout section → PlacementRule edges (KG-4)      │
│  P2 normalizer → adds normalized pin labels to Pin nodes        │
│  p1_importer.py → converts ComponentDatasheet JSON → KG edges   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Source 4: IPC-2221 / IPC-7351 Standards (KG-4)                │
│  P1 parser → table extraction (trace width vs current tables)   │
│  Output: RoutingRule nodes (min trace width, clearance tables)  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Source 5: Expert Curation (KG-5)                               │
│  Manual entry via CLI or admin UI                               │
│  DesignMethodology nodes + governed_by edges                    │
│  High-confidence override rules (confidence = 1.0)             │
└─────────────────────────────────────────────────────────────────┘
```

### 4.5 Design Methodology Classification

When a design methodology is identified, it activates a specific subset of KG-4 and KG-5 rules and suppresses others. This governs which placement and routing constraints apply.

| Methodology | Trigger Keywords | Active Rule Sets | Suppressed Rules |
|-------------|-----------------|-----------------|-----------------|
| RF_highfreq | antenna, RF, 2.4GHz, 5GHz, Bluetooth, WiFi, LoRa | RF keepout zones, 50Ω trace rules, copper pour keepout, ground plane continuity | Standard SMD proximity defaults |
| power_management | buck, boost, LDO, regulator, battery charger, SMPS | Hot loop grouping, thermal relief, high-current trace widths, EMI shielding area | Low-current default trace widths |
| mixed_signal | ADC, DAC, op-amp, analog, sensor, measurement | Analog-digital ground split, signal isolation, star grounding | Shared ground plane defaults |
| standard_SMD | general, control, digital, microcontroller | Standard IPC-2221 defaults | RF-specific overrides |
| through_hole | prototype, hand-solder, THT, DIP | Standard THT clearances, lead spacing | SMD-specific rules |

---

## 5. Neutral Intermediate Representation (NIR)

The NIR is the format-agnostic PCB description that sits between the intelligence layer and the output serializers. It is the source of truth at the point of output. KiCad and tscircuit are NIR consumers, not design authorities.

### 5.1 NIR Schema

```python
class ComponentRef:
    ref: str                  # "U1", "C3", "R12" — designator
    component_id: str         # "TPS62933DRLR" — specific part number
    component_type: str       # "buck_converter", "decoupling_capacitor"
    footprint: str            # "SOT-23-5", "0402"
    value: Optional[str]      # "10uF", "10kΩ", "1uH"
    manufacturer: str
    datasheet_confidence: float  # confidence of P1 extraction for this part
    justification: str        # why this component is in the design

class PinRef:
    ref: str                  # "U1" — component designator
    pin_name: str             # "VIN" — normalized via P2
    pin_number: str           # "1" — physical pin number

class NetlistEntry:
    net_name: str             # "VCC_3V3", "GND", "SW_NODE"
    net_type: str             # "power", "signal", "RF", "clock", "differential"
    connections: list[PinRef] # all pins on this net
    source_rule: str          # KG edge that established this connection

class PlacementConstraint:
    ref: str                  # component being constrained
    constraint_type: Literal["proximity", "keepout", "layer", "orientation", "group"]
    relative_to: str          # component ref or pin ref or board edge
    max_distance_mm: Optional[float]
    min_distance_mm: Optional[float]
    layer: Optional[str]      # "top", "bottom", "any"
    hard: bool                # True = DRC violation if broken, False = soft preference
    source: str               # which rule/document established this
    confidence: float

class RoutingHint:
    nets: list[str]           # affected nets
    hint_type: Literal[
        "impedance_controlled",
        "length_matched",
        "differential_pair",
        "min_width",
        "max_length",
        "isolation"
    ]
    value: Optional[float]
    unit: Optional[str]
    note: str                 # human-readable explanation

class ComponentGroup:
    name: str                 # "power_hot_loop", "RF_section", "MCU_block"
    refs: list[str]           # component designators in this group
    keep_together: bool       # treat as a placement cluster
    isolation_required: bool  # needs separation from other groups

class BoardSpec:
    layers: int               # 2, 4, 6
    material: str             # "FR4", "Rogers_4003C"
    thickness_mm: float
    copper_weight_oz: float
    min_trace_width_mm: float
    min_clearance_mm: float
    min_via_drill_mm: float
    surface_finish: str       # "HASL", "ENIG", "OSP"

class ReviewFlag:
    item_ref: str
    reason: str
    severity: Literal["CRITICAL", "WARNING", "INFO"]
    stage: str                # which pipeline stage flagged it
    suggested_resolution: Optional[str]

class NIR:
    design_id: str            # UUID
    prompt: str               # original NL input
    design_methodology: str
    components: list[ComponentRef]
    netlist: list[NetlistEntry]
    placement_constraints: list[PlacementConstraint]
    component_groups: list[ComponentGroup]
    routing_hints: list[RoutingHint]
    board_spec: BoardSpec
    bom: list[BOMEntry]
    justifications: dict[str, str]   # ref → justification string
    source_citations: dict[str, str] # ref → source document
    confidence_scores: dict[str, float]  # ref → confidence
    review_flags: list[ReviewFlag]
    extraction_metadata: dict
    created_at: str
    pipeline_version: str
```

---

## 6. Storage Architecture

| Store | Technology | Contents | Est. Size |
|-------|-----------|---------|----------|
| Knowledge Graph | NetworkX (proto) → Neo4j (prod) | All KG nodes and edges | ~500K nodes, ~2M edges |
| Component Database | PostgreSQL | Parsed component data, NIR-ready | ~100GB at 100K components |
| Document Archive | Filesystem + PostgreSQL metadata | Source PDFs, scraped HTML | ~50GB initial corpus |
| Review Queue | SQLite | Flagged items pending human review | <1GB |
| Correction History | JSONL on filesystem | Reviewed corrections, future fine-tune corpus | <10GB |
| Vector Index | FAISS | Node embeddings for semantic component search | ~2GB |
| Model Weights | Filesystem | Qwen2.5-7B, Qwen2-VL-7B, YOLOv8n | ~35GB |
| NIR Store | Filesystem (JSON) | Generated NIR objects | Variable per design |
| Output Store | Filesystem | KiCad files, tscircuit files, documentation | Variable per design |
| Eval Corpus | Filesystem | Golden datasheets + ground truth JSON | ~5GB |

---

## 7. AI and ML Component Map

All inference runs locally. No cloud API calls. GPU is required for acceptable performance on the VLM and LLM components.

| Component | Model | Task | VRAM | Pipeline Stage |
|-----------|-------|------|------|---------------|
| Document Layout Detector | YOLOv8n-DocLayNet | Table and footnote bounding box detection | 0.5GB | P1 Phase 1 |
| Table VLM | Qwen2-VL-7B-Instruct | Borderless table → markdown grid (TSR Path B) | 14GB | P1 Phase 2 |
| Semantic Extractor | Qwen2.5-7B-Instruct | Grid text → typed Pydantic JSON | shared | P1 Phase 3 |
| Layout Section Parser | Qwen2.5-7B-Instruct | Datasheet layout prose → placement rules | shared | P1 Phase 5 |
| Intent Parser | Qwen2.5-7B-Instruct | NL prompt → intent_dict | shared | L0 |
| Triple Extractor | spaCy + Qwen2.5-7B | Text sentence → (S, V, O) triples | shared | KG ingestion |
| Pin Normalizer | Rule dict + Qwen2.5-7B | Raw pin name → canonical label | shared | L4 |
| Block Diagram Parser | Qwen2-VL-7B-Instruct | App note block diagram image → topology graph | 14GB | P3 |

**Hardware constraint:** The 24GB VRAM GPU (RTX 3090 or A5000) cannot hold both Qwen2-VL-7B and Qwen2.5-7B simultaneously in bfloat16. The pipeline is designed sequentially — model weights are loaded and unloaded between phases. The orchestrator manages model lifecycle explicitly.

---

## 8. Human Review Architecture

Human review is a first-class pipeline stage, not an afterthought. Review gates are positioned at every stage boundary where confidence can fall below threshold.

| Gate | Location | Trigger | Queue | Blocks Downstream |
|------|---------|---------|-------|------------------|
| BOM Review | L2 → L3 | Total BOM confidence < 0.85, or any component < 0.75, or no specific part found | SQLite review_queue | Yes — L3 does not start until BOM is approved |
| Netlist Review | L5 → L6 | ERC errors from schematic synthesizer | SQLite review_queue | Yes — layout engine waits |
| Layout Review | L6 → L7 | DRC-equivalent conflicts in placement spec | SQLite review_queue | Yes — NIR builder waits |
| NIR Validation | L7 → L8 | Any CRITICAL NIR validation error | SQLite review_queue | Yes — serializers wait |
| Post-Output Review | L8 | ERC/DRC errors from KiCad or tscircuit validation after generation | SQLite review_queue | No — output generated but flagged |

Review CLI pattern (consistent with P1):
```
python -m src.review.cli list --stage bom
python -m src.review.cli review <item_id>
python -m src.review.cli approve <item_id>
python -m src.review.cli correct <item_id> --value <correction>
```

---

## 9. Accuracy and Validation Targets

| Stage | Metric | Target | Measurement Method |
|-------|--------|--------|--------------------|
| P1 Phase 1 DLA | Table detection recall | ≥ 0.92 | Eval on 5-golden-datasheet corpus |
| P1 Phase 1 DLA | Footnote linkage accuracy | ≥ 0.85 | Eval on golden corpus |
| P1 Phase 2 TSR | Cell-level grid accuracy | ≥ 0.95 | Eval on golden corpus |
| P1 Phase 3 Extraction | Field-level F1 | ≥ 0.93 | Eval on golden corpus |
| P1 Phase 4 Validation | False negative rate | ≤ 0.01 | Eval on golden corpus |
| P1 Phase 5 Layout Extraction | Placement rule recall | ≥ 0.85 | Manual verification on 10 datasheets |
| P2 Pin Normalization | Accuracy on known pin names | ≥ 0.97 | Dictionary coverage test |
| P3 Block Diagram Extraction | Topology node recall | ≥ 0.80 | Manual verification on 10 app notes |
| KG Triple Extraction | Triple precision | ≥ 0.90 | Spot-check 50 triples per source |
| BOM Generation | Component type correctness | ≥ 0.90 | Against 20 hand-verified test designs |
| Schematic ERC | Pass rate before human review | ≥ 0.85 | KiCad ERC on 20 test designs |
| End-to-end | Usable schematic without manual correction | ≥ 0.75 | Engineer review on 20 test designs |

---

## 10. Project Directory Structure

```
openforge-pcb/
├── src/
│   ├── intent/
│   │   ├── parser.py               # NL → intent_dict
│   │   └── methodology_classifier.py
│   ├── knowledge_graph/
│   │   ├── schema.py               # KGNode + KGEdge Pydantic models
│   │   ├── builder.py              # Ingest triples → graph
│   │   ├── query_engine.py         # intent_dict → design_subgraph
│   │   ├── validator.py            # Graph consistency checks
│   │   └── ingestion/
│   │       ├── scraper_aac.py      # All About Circuits scraper
│   │       ├── scraper_appnotes.py # TI/ADI app note downloader
│   │       ├── triple_extractor.py # Text → (S,V,O) triples
│   │       ├── placement_extractor.py  # Spatial language → KG-4 rules
│   │       └── p1_importer.py      # ComponentDatasheet JSON → KG-3 edges
│   ├── bom/
│   │   ├── generator.py            # design_subgraph → validated_bom
│   │   ├── selector.py             # ComponentType → specific part
│   │   └── reviewer.py             # Confidence scoring + review flagging
│   ├── datasheet/                  # P1 parser (existing, extended)
│   │   ├── phase1_dla/
│   │   ├── phase2_tsr/
│   │   ├── phase3_extract/
│   │   ├── phase4_validate/
│   │   └── phase5_layout/          # NEW: layout section extraction
│   ├── pin_normalizer/             # P2
│   │   ├── dictionary.py
│   │   └── llm_fallback.py
│   ├── block_diagram/              # P3
│   │   ├── detector.py             # VLM: image → topology
│   │   └── graph_builder.py        # Topology → KG-2 edges
│   ├── schematic/                  # P5
│   │   ├── synthesizer.py          # BOM + component data → netlist
│   │   ├── net_assigner.py         # Power, signal, protocol net assignment
│   │   ├── passive_assigner.py     # Decoupling, bypass, pull-up assignment
│   │   └── erc.py                  # Electrical rules check
│   ├── layout/
│   │   ├── engine.py               # Schematic → layout_spec
│   │   ├── placement_solver.py     # Constraint satisfaction for placement
│   │   └── routing_hints.py        # Impedance, length match, width hints
│   ├── nir/
│   │   ├── schema.py               # NIR Pydantic models (single source of truth)
│   │   ├── builder.py              # Assemble NIR from all upstream artifacts
│   │   └── validator.py            # Cross-validate NIR consistency
│   ├── output/
│   │   ├── kicad_serializer.py     # NIR → KiCad MCP calls
│   │   ├── tscircuit_serializer.py # NIR → tscircuit JSON/TSX
│   │   └── doc_generator.py        # NIR → PDF design report
│   ├── review/
│   │   ├── queue.py                # SQLite review queue writer
│   │   └── cli.py                  # Review CLI
│   ├── schemas/
│   │   ├── nir.py                  # NIR schema (master)
│   │   ├── datasheet.py            # ComponentDatasheet schema
│   │   └── kg.py                   # KGNode + KGEdge schema
│   ├── config.py                   # All settings — single source
│   └── pipeline.py                 # End-to-end orchestrator
├── models/                         # Local model weights (gitignored)
├── data/
│   ├── raw/                        # Scraped HTML, downloaded PDFs
│   ├── triples/                    # Extracted (S,V,O) JSONL
│   └── graph/                      # Serialized graph (GraphML or Neo4j dump)
├── corpus/
│   ├── golden/                     # Verified datasheets + ground truth
│   └── test/                       # Test datasheets
├── eval/
│   ├── run_eval.py
│   └── reports/
├── configs/
│   ├── default.yaml
│   ├── canonical_units.yaml
│   ├── methodology_rules.yaml
│   └── sources.yaml                # Scraper source list
├── docker/
│   ├── Dockerfile
│   └── build_airgapped_image.sh
└── pyproject.toml
```

---

## 11. Inter-Module API Contracts

Each module exposes a Python API with typed inputs and outputs. These contracts are the integration boundaries between teams.

```python
# L0: Intent Parser
def parse_intent(prompt: str, config: Config) -> IntentDict: ...

# L1: KG Query Engine
def query_graph(intent: IntentDict, config: Config) -> DesignSubgraph: ...

# L2: BOM Generator
def generate_bom(subgraph: DesignSubgraph, config: Config) -> ValidatedBOM: ...

# L3: Datasheet Parser (extended P1)
def parse_datasheet(component_id: str, pdf_path: Path, config: Config) -> ComponentDatasheet: ...

# L4: Pin Normalizer
def normalize_pins(datasheets: list[ComponentDatasheet], config: Config) -> list[ComponentDatasheet]: ...

# L5: Schematic Synthesizer
def synthesize_schematic(datasheets: list[ComponentDatasheet], subgraph: DesignSubgraph, config: Config) -> SchematicGraph: ...

# L6: Layout Engine
def generate_layout_spec(schematic: SchematicGraph, datasheets: list[ComponentDatasheet], subgraph: DesignSubgraph, config: Config) -> LayoutSpec: ...

# L7: NIR Builder
def build_nir(bom: ValidatedBOM, datasheets: list[ComponentDatasheet], schematic: SchematicGraph, layout: LayoutSpec, config: Config) -> NIR: ...

# L8a: KiCad Serializer
def serialize_to_kicad(nir: NIR, output_dir: Path, config: Config) -> KiCadOutput: ...

# L8b: tscircuit Serializer
def serialize_to_tscircuit(nir: NIR, output_dir: Path, config: Config) -> TSCircuitOutput: ...
```

---

## 12. Deployment Architecture

**Target:** Single air-gapped machine. Ubuntu 22.04 LTS. 1× NVIDIA A5000 or RTX 3090 (24GB VRAM).

```
Docker Container: openforge-pcb
├── GPU: CUDA 12.1 runtime
├── Python 3.10 + all dependencies
├── Model weights baked in:
│   ├── YOLOv8n-DocLayNet (0.5GB)
│   ├── Qwen2-VL-7B-Instruct (14GB bfloat16)
│   └── Qwen2.5-7B-Instruct (14GB bfloat16)
├── Neo4j embedded or sidecar container
├── PostgreSQL sidecar container
└── Volumes:
    ├── /data/datasheets  → input PDFs
    ├── /data/output      → generated files
    └── /data/graph       → KG persistence

CLI entry point:
docker run --gpus all openforge-pcb:v1.0 \
    python -m src.pipeline \
    --prompt "build a 2.4GHz patch antenna for a drone" \
    --output /data/output/
```

---

*This document is the system architecture reference. All team charters, subsystem specs, and integration documents derive from it. Changes to this document require review by all team leads.*
