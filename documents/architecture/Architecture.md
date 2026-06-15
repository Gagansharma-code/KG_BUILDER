#  OpenForge Intelligence System — Architecture Document

**Goal:** Given a natural language prompt like "build a 2.4GHz antenna", the system determines what components are needed, why, and hands that structured knowledge to KiCad for PCB generation — entirely offline, open source, and private.

---

## The Core Problem We Are Solving

Existing tools (CircuitLM, Circuitron) assume you already know what components you need. Engineers don't want to specify components — they want to describe *what they're building* in plain language and have the system figure out the rest.

This requires a system that understands engineering at three levels:

1. **Physics** — what is an antenna, what is impedance
2. **Design recipes** — to build a 2.4GHz antenna you need these specific parts with these specific values
3. **Component rules** — which IC connects to which passive, what decoupling goes where

No existing open-source system combines all three. This is our research contribution.

---

## System Overview

```
Engineer types:
"I need to build a 2.4GHz patch antenna for a drone"
        │
        ▼
┌─────────────────────────────────────────────────────┐
│              LAYER 0: Natural Language Interface     │
│         (Local LLM — Qwen2.5-7B-Instruct)           │
│   Parses intent → extracts: type, frequency,        │
│   application, constraints                          │
└─────────────────────────┬───────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│           LAYER 1: Knowledge Graph Query             │
│              (Neo4j or NetworkX)                     │
│                                                     │
│  Query: "2.4GHz antenna" + "drone" + constraints    │
│  Returns: component types, design rules, values     │
│                                                     │
│  Graph has 3 knowledge layers (see below)           │
└─────────────────────────┬───────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│         LAYER 2: Bill of Materials Generator         │
│                                                     │
│  Converts graph query result into:                  │
│  - Component list with types                        │
│  - Required values/specs per component              │
│  - Justification (why each component is needed)     │
│  - Flags anything needing human decision            │
└─────────────────────────┬───────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│         LAYER 3: Datasheet Parser (Problem 1)        │
│                                                     │
│  For each component in BOM:                         │
│  - Fetch matching datasheet                         │
│  - Extract pinouts, electrical characteristics      │
│  - Validate against design rules from graph         │
└─────────────────────────┬───────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│       LAYER 4: KiCad MCP (Problems 5 & 6)           │
│                                                     │
│  Takes validated BOM + pinout data                  │
│  Generates schematic + PCB layout                   │
└─────────────────────────────────────────────────────┘
```

---

## The Knowledge Graph — Three Layers

This is the brain of the entire system. Everything else is plumbing around it.

### Layer 1: Physics & Principles

**Source:** All About Circuits (allaboutcircuits.com/textbook) — Volumes 1–5
**What it stores:** Fundamental relationships between concepts.

```
(antenna) --[requires]--> (impedance matching)
(impedance matching) --[uses]--> (inductor)
(impedance matching) --[uses]--> (capacitor)
(patch antenna) --[is_a]--> (antenna)
(patch antenna) --[requires]--> (dielectric substrate)
(dielectric substrate) --[has_property]--> (relative_permittivity)
```

**Analogy:** This is the physics textbook layer. It tells you *what* things are and *what they need* in principle.

---

### Layer 2: Design Recipes

**Source:** Application notes from Texas Instruments, Analog Devices, Murata — all freely downloadable PDFs
**What it stores:** Specific, quantitative design rules tied to real-world use cases.

```
(2.4GHz_patch_antenna) --[requires_substrate_with]--> (εr BETWEEN 2.2 AND 4.5)
(2.4GHz_patch_antenna) --[requires_connector]--> (SMA_connector)
(2.4GHz_patch_antenna) --[feedline_impedance]--> (50_ohm)
(half_bridge_driver) --[requires_bootstrap]--> (100nF_capacitor)
(LDO_regulator) --[requires_bypass]--> (10uF_capacitor ON input_pin)
(LDO_regulator) --[requires_bypass]--> (1uF_capacitor ON output_pin)
```

**Analogy:** This is the recipe book. It tells you *exactly* what ingredients and quantities, not just the concept.

---

### Layer 3: Component-to-Component Rules

**Source:** Output of Problem 1 (P1 datasheet parser) — structured JSON from parsed datasheets
**What it stores:** Concrete IC-level connection rules derived from real datasheet data.

```
(TPS63020) --[requires_decoupling_on_VIN]--> (10uF_ceramic)
(TPS63020) --[requires_decoupling_on_VOUT]--> (22uF_ceramic)
(TPS63020) --[inductor_value]--> (1uH TO 4.7uH)
(CC2640R2F) --[requires_crystal]--> (32MHz_XTAL)
(CC2640R2F) --[RF_output_impedance]--> (50_ohm)
(CC2640R2F) --[requires_matching_network_at]--> (RF_pin)
```

**Analogy:** This is the manufacturer's installation manual. It tells you what *that specific part* needs around it.

---

## Knowledge Graph Node & Edge Schema

```python
# Node types
class ConceptNode:
    id: str              # "patch_antenna", "SMA_connector"
    type: str            # "component_type", "property", "value", "constraint"
    layer: int           # 1 (physics), 2 (recipe), 3 (component-specific)
    source: str          # URL or document name
    confidence: float    # 1.0 for manually verified, lower for auto-extracted

class EdgeRelation:
    source_node: str
    relation: str        # "requires", "uses", "has_property", "connects_to",
                         # "is_a", "incompatible_with", "replaces"
    target_node: str
    constraints: dict    # {"value": "50", "unit": "ohm", "condition": "at 2.4GHz"}
    source: str          # which document this came from
    confidence: float
```

---

## Data Sources & Ingestion Pipeline

### Source 1: All About Circuits (Layer 1)

```
URL: allaboutcircuits.com/textbook
Volumes needed:
  - Vol 1: DC (resistors, capacitors, basic laws)
  - Vol 2: AC (inductors, impedance, filters, RF basics)
  - Vol 3: Semiconductors (diodes, transistors, op-amps)
  - Vol 5: Reference (formulas, tables)

Ingestion method:
  1. Scrape chapter HTML → clean text
  2. Extract sentences
  3. NLP: subject-verb-object triple extraction
  4. Map to knowledge graph nodes/edges
  5. Human review of extracted triples (spot check)
```

### Source 2: Application Notes (Layer 2)

```
Sources:
  - Texas Instruments: ti.com/application-notes (free PDF download)
  - Analog Devices: analogdevices.com/en/resources/app-notes
  - Murata: murata.com (antenna/RF design notes)

Priority app notes:
  - AN-1294 (TI): Antenna selection for 2.4GHz
  - AN-2519 (TI): RF layout guidelines
  - AN-1849 (TI): Bootstrap capacitor selection for gate drivers
  - ADI MT-094: Microstrip and stripline design

Ingestion method:
  - Problem 1 pipeline (PDF → JSON) extracts tables
  - Additional NLP pass extracts design rules from prose sections
  - Rules stored as Layer 2 edges with quantitative constraints
```

### Source 3: Datasheet Parser Output (Layer 3)

```
Source: Output of Problem 1 (P1 parser) for each IC in corpus

Ingestion method:
  - P1 parser produces ComponentDatasheet JSON
  - Post-processing script converts JSON fields to graph edges:
      pin → connects_to → net_type
      parameter → has_value → normalized_value
  - Each edge tagged with confidence score from P1 pipeline
```

---

## Query Engine: Natural Language → BOM

When an engineer types "build a 2.4GHz antenna for a drone", the query engine does this:

```
Step 1 — Intent Extraction (Local LLM)
  Input:  "build a 2.4GHz antenna for a drone"
  Output: {
    "goal": "antenna",
    "frequency": "2.4GHz",
    "application": "drone",
    "constraints": ["compact", "lightweight"]   ← inferred from "drone"
  }

Step 2 — Graph Traversal
  Start node: "2.4GHz_antenna"
  Traverse edges: requires, uses, has_property
  Depth: 3 levels (component → subcomponent → part value)
  Output: subgraph of all required nodes

Step 3 — BOM Generation
  Convert subgraph to structured BOM:
  [
    {
      "component_type": "patch_antenna_element",
      "reason": "primary radiating element for 2.4GHz",
      "constraints": {"substrate_εr": "2.2-4.5", "size": "~31mm x 31mm"},
      "source": "TI AN-1294"
    },
    {
      "component_type": "SMA_connector",
      "reason": "50-ohm RF feed connection",
      "constraints": {"impedance": "50Ω"},
      "source": "allaboutcircuits.com Vol 2 Ch 14"
    },
    {
      "component_type": "matching_network",
      "reason": "impedance match between feedline and antenna",
      "constraints": {"topology": "L-network or pi-network", "frequency": "2.4GHz"},
      "source": "ADI MT-094"
    }
  ]

Step 4 — Human Review Gate
  Flag any component where:
  - graph confidence < 0.85
  - multiple conflicting design rules exist
  - application-specific constraint not in graph
  Engineer approves/modifies before proceeding to P1 parser + KiCad
```

---

## Project Structure

```
open-forge-knowledge-graph/
├── src/
│   ├── ingestion/
│   │   ├── scraper_aac.py          # All About Circuits scraper
│   │   ├── scraper_appnotes.py     # TI/ADI app note PDF downloader
│   │   ├── triple_extractor.py     # NLP: sentence → (subject, verb, object)
│   │   └── p1_importer.py          # Import P1 parser JSON → graph edges
│   ├── graph/
│   │   ├── schema.py               # Node and Edge Pydantic models
│   │   ├── builder.py              # Build/update graph from triples
│   │   ├── query_engine.py         # Traverse graph given intent dict
│   │   └── validator.py            # Check graph consistency
│   ├── bom/
│   │   ├── generator.py            # Subgraph → structured BOM
│   │   └── reviewer.py             # Flag uncertain items for human review
│   ├── nlp/
│   │   ├── intent_parser.py        # LLM: natural language → intent dict
│   │   └── triple_parser.py        # spaCy/LLM: text → triples
│   └── pipeline.py                 # End-to-end orchestrator
├── data/
│   ├── raw/                        # Scraped HTML, downloaded PDFs
│   ├── triples/                    # Extracted (subject, verb, object) JSONL
│   └── graph/                      # Serialized graph (GraphML or Neo4j dump)
├── models/
│   └── qwen2.5-7b-instruct/        # Local LLM weights
├── configs/
│   └── sources.yaml                # Data source URLs and priorities
├── eval/
│   ├── test_queries.yaml           # e.g. "build a 2.4GHz antenna"
│   └── ground_truth_boms.json      # Hand-verified expected BOM outputs
└── pyproject.toml
```

---

## Technology Choices


| Component             | Tool                                      | Why                                                               |
| --------------------- | ----------------------------------------- | ----------------------------------------------------------------- |
| Graph database        | NetworkX (prototype) → Neo4j (production) | NetworkX needs no setup; Neo4j scales and supports Cypher queries |
| NLP triple extraction | spaCy + local Qwen2.5-7B                  | spaCy for fast sentence parsing; LLM for ambiguous cases          |
| Intent parsing        | Qwen2.5-7B-Instruct (local)               | Air-gapped, no cloud dependency                                   |
| PDF ingestion         | Problem 1 pipeline (P1 parser)            | Already designed; reuse directly                                  |
| Web scraping          | BeautifulSoup + requests                  | Simple, no JS rendering needed for allaboutcircuits.com           |
| Validation            | Pydantic schemas (reuse from P1)          | Consistent with existing codebase                                 |


---

## What Makes This Different From Existing Solutions


| Capability                          | CircuitLM | Circuitron | This System |
| ----------------------------------- | --------- | ---------- | ----------- |
| Natural language input              | ✅         | ✅          | ✅           |
| Air-gapped / offline                | ❌         | ❌          | ✅           |
| Physics-grounded (not hallucinated) | ❌         | ⚠️ partial | ✅           |
| Design recipe layer (app notes)     | ❌         | ❌          | ✅           |
| Datasheet-grounded component rules  | ❌         | ❌          | ✅           |
| Justification for every component   | ❌         | ❌          | ✅           |
| Human review gate before KiCad      | ❌         | ❌          | ✅           |
| Open source + private               | ✅         | ✅          | ✅           |


---

## Phased Build Plan

### Phase 0 — Foundation (Week 1)

- Set up project structure
- Scrape All About Circuits Vol 1 & 2 (DC + AC)
- Run basic triple extraction on 5 chapters
- Manually verify 50 extracted triples
- Build minimal NetworkX graph with verified triples

**Exit criteria:** Graph answers "what does a capacitor do?" correctly from extracted knowledge.

### Phase 1 — Layer 1 Complete (Week 2–3)

- Complete All About Circuits ingestion (all relevant volumes)
- Triple extraction pipeline automated
- Graph covers: resistors, capacitors, inductors, basic semiconductors, filters, RF basics
- Query engine returns correct component types for 10 test prompts

**Exit criteria:** "build an LC filter" returns correct component list with values.

### Phase 2 — Layer 2 (Week 4–5)

- Ingest 10 priority TI/ADI application notes
- Design recipe extraction (tables + prose rules)
- Layer 2 edges added to graph with quantitative constraints

**Exit criteria:** "build a 2.4GHz antenna" returns substrate εr range, connector type, feedline impedance.

### Phase 3 — Layer 3 + P1 Integration (Week 6–7)

- Connect P1 parser output → graph importer
- Layer 3 edges from parsed datasheets
- BOM generator produces justified component list

**Exit criteria:** Full BOM with justifications generated for 5 test cases.

### Phase 4 — KiCad Handoff (Week 8)

- BOM → P1 datasheet fetch → pinout extraction
- Validated JSON handed to KiCad MCP
- End-to-end test: natural language → PCB schematic

**Exit criteria:** "build a simple LDO power supply" produces a valid KiCad schematic.

---

## Open Questions (To Resolve Before Coding)

1. **Graph database:** Start with NetworkX for prototyping or go straight to Neo4j?
2. **Triple extraction quality:** How much manual verification is needed per source?
3. **App note licensing:** Confirm TI/ADI app notes are freely redistributable offline.
4. **Scope of Layer 1:** Which All About Circuits chapters are highest priority for target use cases?
5. **Human review UI:** CLI sufficient, or is a simple web UI needed for BOM approval?

---

*This document is the single source of truth for the OpenForge Knowledge Graph system architecture. Update it as decisions are made.*