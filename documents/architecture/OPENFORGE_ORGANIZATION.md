# OpenForge PCB Intelligence System — Engineering Organization

**Version:** 1.0
**Owner:** Technical Program Manager
**Derives from:** OPENFORGE_ARCHITECTURE.md, OPENFORGE_SUBSYSTEMS.md

---

## 1. Overview

The system is divided into six engineering teams. Each team owns a set of subsystems, exposes typed Python APIs as integration contracts, and operates independently on its internal implementation. Teams integrate at defined contract boundaries — no team needs to understand another team's internals.

This document defines:
- Team ownership and composition
- Inputs, outputs, and dependencies per team
- API contracts at every integration boundary
- Milestones and deliverables
- Coordination protocols

---

## 2. Team Structure

```
┌─────────────────────────────────────────────────────────────┐
│  Team A: Data Engineering                                    │
│  Subsystems: S1 (Datasheet Parsing), S3 (Block Diagrams)    │
│  Produces: ComponentDatasheet JSON, KG-3/KG-4 edges         │
└───────────────────────────┬─────────────────────────────────┘
                            │ ComponentDatasheet JSON
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Team B: Knowledge Graph                                     │
│  Subsystems: S4 (KG construction + query), S2 (Pin Norm)    │
│  Consumes: ComponentDatasheet JSON, scraped text             │
│  Produces: KG, query API, normalized pins                    │
└───────────────────────────┬─────────────────────────────────┘
                            │ DesignSubgraph, normalized ComponentDatasheet
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Team C: Intelligence Layer                                  │
│  Subsystems: S5 (Intent Parser), S6 (BOM Generator)         │
│  Consumes: KG query API                                      │
│  Produces: ValidatedBOM                                      │
└───────────────────────────┬─────────────────────────────────┘
                            │ ValidatedBOM
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Team D: Circuit Synthesis                                   │
│  Subsystems: S7 (Schematic), S8 (Layout), NIR builder        │
│  Consumes: BOM + normalized ComponentDatasheet + KG subgraph │
│  Produces: NIR (Neutral Intermediate Representation)         │
└───────────────────────────┬─────────────────────────────────┘
                            │ NIR JSON
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Team E: Output and Integration                              │
│  Subsystems: S10 (KiCad + tscircuit serializers)            │
│  Consumes: NIR JSON                                          │
│  Produces: KiCad files, tscircuit files, documentation       │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Team F: Platform and Infrastructure                         │
│  Owns: Docker, storage, CI/CD, eval framework, review CLI   │
│  Serves all teams                                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Team A — Data Engineering

### Charter

Team A is responsible for all data ingestion: extracting structured data from PDF datasheets, application notes, and block diagram figures. They produce the `ComponentDatasheet` JSON objects that feed Team B's knowledge graph and Team D's schematic synthesizer.

### Composition

- 3–4 engineers: 1 ML engineer (VLM prompting + YOLOv8), 1–2 data engineers (PDF pipeline, orchestration), 1 QA engineer (corpus curation, eval)

### Subsystem Ownership

| Subsystem | Description |
|-----------|-------------|
| S1 — Datasheet Parser | Full 5-phase pipeline (DLA, TSR, Extraction, Validation, Layout Extraction) |
| S3 — Block Diagram Extractor | CV extraction of topology from figures |
| Web Scrapers | All About Circuits scraper, app note downloader |

### Inputs

| Input | Source | Format |
|-------|--------|--------|
| PDF datasheets | Corpus filesystem or URL list | PDF files |
| Application note PDFs | `scraper_appnotes.py` (own Team A tool) | PDF files |
| Component list for ingestion | Team C (BOM includes component IDs) | JSON list of component IDs |

### Outputs (API Contract)

Team A exposes two primary outputs:

#### Output 1: `ComponentDatasheet` JSON

One JSON file per component, conforming to `src/schemas/datasheet.py`.

```python
# API Team A exposes:
def parse_datasheet(
    component_id: str,
    pdf_path: Path,
    config: Config
) -> ComponentDatasheet:
    """
    Parse a single datasheet PDF and return a validated ComponentDatasheet.
    
    Raises:
        DatasheetParsingError: if P1 Phase 4 returns CRITICAL errors
        PhysicsValidationError: if extracted values fail physics checks
    """
```

```python
def parse_datasheet_batch(
    component_ids: list[str],
    pdf_dir: Path,
    config: Config,
    max_workers: int = 4
) -> list[ComponentDatasheet]:
    """Process multiple datasheets in parallel."""
```

#### Output 2: `BlockDiagramTopology` JSON

For each app note figure identified as a block diagram.

```python
def extract_block_diagram_topology(
    figure_image: bytes,
    source_document: str,
    config: Config
) -> BlockDiagramTopology:
    """
    Extract functional topology from a block diagram figure.
    Returns node/edge graph for KG-2 ingestion.
    """
```

### Dependencies

| Dependency | From | Needed For |
|------------|------|-----------|
| Qwen2-VL-7B-Instruct weights | Team F (deployment) | P1 Phase 2 (TSR Path B) |
| Qwen2.5-7B-Instruct weights | Team F (deployment) | P1 Phase 3, Phase 5 |
| YOLOv8n-DocLayNet weights | Team F (deployment) | P1 Phase 1 |
| Golden corpus (5 datasheets) | Team A curates | Eval and development validation |
| `src/schemas/datasheet.py` | Team F (platform) owns schema, Team A implements | Output contract |

### Deliverables

| Deliverable | Description | Format |
|-------------|-------------|--------|
| P1 parser (Phases 1–4) | Existing pipeline, production-ready | Python package |
| P1 Phase 5 | Layout section extractor | Python module |
| Block diagram extractor | Figure → topology | Python module |
| Golden corpus + ground truth | 5 datasheets + hand-verified JSON | JSON files |
| Eval metrics report | Per-phase accuracy vs targets | Markdown report |
| Scraper suite | AAC + app note downloaders | Python scripts |

### Milestones

| Milestone | Week | Exit Criteria |
|-----------|------|--------------|
| A1: P1 Phases 1–4 passing on golden corpus | Week 2 | All 4 phase metrics met on 5 golden datasheets |
| A2: P1 Phase 5 functional | Week 3 | ≥ 0.85 placement rule recall on 10 manually reviewed datasheets |
| A3: Block diagram extractor functional | Week 5 | ≥ 0.80 topology node recall on 10 app note diagrams |
| A4: Scraper suite operational | Week 2 | AAC Vols 1–2 scraped and stored; 10 priority app notes downloaded |
| A5: Full corpus (30 datasheets) processed | Week 6 | All 30 datasheets in `ComponentDatasheet` JSON |

---

## 4. Team B — Knowledge Graph

### Charter

Team B builds and maintains the five-layer Knowledge Graph. They own the KG schema, all ingestion pipelines (except S1 which is Team A), the query engine, and pin normalization. The KG is the engineering authority of the system — their output quality directly determines the quality of every design the system produces.

### Composition

- 3 engineers: 1 graph engineer (Neo4j, schema, traversal), 1 NLP engineer (triple extraction, placement extraction), 1 integration engineer (P1 importer, scraper integration)

### Subsystem Ownership

| Subsystem | Description |
|-----------|-------------|
| S4 — Knowledge Graph | Schema, builder, ingestion pipeline, query engine, validator |
| S2 — Pin Normalizer | Normalization dictionary + LLM fallback |
| KG-1 Ingestion | All About Circuits triple extraction |
| KG-2 Ingestion | App note design recipe + placement rule extraction |
| KG-4 Ingestion | Layout section rules (consuming Team A's Phase 5 output) |
| KG-5 Curation | Methodology rules (manual admin tool) |

### Inputs

| Input | Source | Format |
|-------|--------|--------|
| ComponentDatasheet JSON | Team A | JSON per component |
| BlockDiagramTopology JSON | Team A | JSON per figure |
| Scraped AAC HTML | Team A (scraper suite) | HTML text files |
| App note PDFs | Team A (scraper suite) | PDF files |

### Outputs (API Contract)

#### Output 1: KG Query API

```python
def query_graph(
    intent: IntentDict,
    config: Config
) -> DesignSubgraph:
    """
    Query the Knowledge Graph with a structured design intent.
    
    Returns:
        DesignSubgraph containing:
        - component_types: list of required ComponentType nodes
        - design_rules: list of quantitative rules with constraints
        - placement_rules: list of PlacementConstraint objects
        - routing_hints: list of RoutingHint objects
        - design_methodology: active methodology
        - path_confidences: dict of node_id → path confidence score
    
    Raises:
        KGQueryError: if start node cannot be mapped from intent
    """
```

#### Output 2: Pin Normalization API

```python
def normalize_pins(
    datasheets: list[ComponentDatasheet],
    config: Config
) -> list[ComponentDatasheet]:
    """
    Add normalized_function and normalization_confidence fields
    to every PinDefinition in every ComponentDatasheet.
    Does not mutate input; returns new list.
    """
```

#### Output 3: Component Semantic Search API

```python
def search_components(
    query: str,
    component_type: Optional[str],
    max_results: int = 10
) -> list[ComponentSearchResult]:
    """
    Find component instances in KG-3 matching a semantic query.
    Uses FAISS vector index over node embeddings.
    Example: search_components("3.3V LDO regulator low noise") → [TPS7A20, TLV755P, ...]
    """
```

### Dependencies

| Dependency | From | Needed For |
|------------|------|-----------|
| ComponentDatasheet JSON | Team A | KG-3 ingestion |
| `src/schemas/kg.py` | Team F | KGNode + KGEdge schema |
| Neo4j container | Team F | Production graph storage |
| FAISS | Team F (environment) | Vector index |
| spaCy model | Team F (environment) | Triple extraction |

### Deliverables

| Deliverable | Description | Format |
|-------------|-------------|--------|
| KG schema (`src/schemas/kg.py`) | KGNode + KGEdge Pydantic models | Python module |
| KG-1 ingestion pipeline | AAC → physics triples → graph | Python package |
| KG-2 ingestion pipeline | App notes → design recipes + placement rules | Python package |
| KG-3 importer (`p1_importer.py`) | ComponentDatasheet → KG-3 edges | Python module |
| KG-4 importer | Placement constraints → KG-4 edges | Python module |
| Query engine (`query_engine.py`) | intent → design_subgraph | Python module |
| Pin normalization module | Raw pin names → canonical functions | Python module |
| KG-5 admin tool | CLI for methodology rule curation | Python script |
| Graph consistency validator | `validator.py` | Python module |
| Triple quality report | Spot-check results for 50 triples per source | Markdown report |

### Milestones

| Milestone | Week | Exit Criteria |
|-----------|------|--------------|
| B1: KG-1 populated (physics layer) | Week 3 | AAC Vols 1–5 ingested; 500+ physics concept nodes; query answers "what does a capacitor do" correctly |
| B2: KG-2 populated (design recipes) | Week 5 | 10 priority app notes ingested; query answers "build 2.4GHz antenna" with correct substrate εr, connector type, feedline impedance |
| B3: KG-3 populated (component instances) | Week 6 | All 30 corpus components in KG-3 with pins and electrical properties |
| B4: KG-4 populated (placement rules) | Week 6 | Placement rules for all corpus components extracted and ingested |
| B5: KG-5 methodology rules set | Week 4 | All 5 methodologies defined with active rule sets |
| B6: Query engine functional | Week 5 | End-to-end query returns valid DesignSubgraph for all 20 test cases |
| B7: Pin normalization functional | Week 4 | ≥ 0.97 accuracy on known pin name test set |

---

## 5. Team C — Intelligence Layer

### Charter

Team C owns the natural language interface and BOM generation logic. They translate engineer prompts into structured design intents, and translate design intents into justified, validated bills of materials. They are the primary user-facing team — the quality of their output determines the first impression engineers have of the system.

### Composition

- 2–3 engineers: 1 NLP/LLM engineer (intent parsing, prompt engineering), 1 BOM logic engineer (selection, scoring, validation), 1 UX/review engineer (review workflow, CLI)

### Subsystem Ownership

| Subsystem | Description |
|-----------|-------------|
| S5 — Intent Parser | NL prompt → intent_dict |
| S6 — BOM Generator | DesignSubgraph → ValidatedBOM |
| Review workflow | BOM review queue, CLI, approval flow |

### Inputs

| Input | Source | Format |
|-------|--------|--------|
| Natural language prompt | User | String |
| `query_graph()` API | Team B | DesignSubgraph |
| Supplier cache database | Team F | SQLite/PostgreSQL |

### Outputs (API Contract)

#### Output 1: Intent Parser API

```python
def parse_intent(
    prompt: str,
    config: Config
) -> IntentDict:
    """
    Parse natural language design prompt into structured intent.
    
    Returns:
        IntentDict with goal, frequency, application, constraints,
        design_methodology, board_type, ambiguities, clarification_required.
    
    Raises:
        AmbiguousPromptError: if critical fields cannot be extracted
        (caller should present clarification questions to user)
    """
```

```python
def get_clarification_questions(
    intent: IntentDict
) -> list[ClarificationQuestion]:
    """
    Generate specific clarification questions for each ambiguity flag.
    Returns list of {question, field, options} objects.
    """
```

#### Output 2: BOM Generator API

```python
def generate_bom(
    subgraph: DesignSubgraph,
    config: Config
) -> ValidatedBOM:
    """
    Generate a validated BOM from a KG design subgraph.
    
    Returns:
        ValidatedBOM with components, justifications, confidence scores,
        review_flags, and total_confidence.
    
    Raises:
        BOMLowConfidenceError: if review gate triggered (caller handles review flow)
    """
```

### Dependencies

| Dependency | From | Needed For |
|------------|------|-----------|
| `query_graph()` API | Team B | BOM generation |
| `src/schemas/` | Team F | IntentDict, ValidatedBOM schemas |
| Qwen2.5-7B-Instruct | Team F (environment) | Intent parsing |

### Deliverables

| Deliverable | Description | Format |
|-------------|-------------|--------|
| Intent parser (`src/intent/parser.py`) | Prompt → IntentDict with Instructor | Python module |
| Methodology classifier (`methodology_classifier.py`) | Text → methodology label | Python module |
| BOM generator (`src/bom/generator.py`) | Subgraph → ValidatedBOM | Python module |
| Component selector (`src/bom/selector.py`) | ComponentType → specific part | Python module |
| BOM validator (`src/bom/validator.py`) | Cross-component compatibility checks | Python module |
| BOM review integration | Review queue writer, CLI hook | Python module |
| Intent test suite | 20 test prompts with expected intent dicts | YAML + JSON |
| BOM test suite | 20 test designs with hand-verified BOMs | JSON |

### Milestones

| Milestone | Week | Exit Criteria |
|-----------|------|--------------|
| C1: Intent parser functional | Week 3 | Correct intent dict for all 20 test prompts; methodology classification ≥ 95% |
| C2: BOM generator functional (type-level) | Week 4 | Returns correct component types (no specific parts yet) for 18/20 test designs |
| C3: BOM generator functional (specific parts) | Week 6 | Returns correct specific parts for components with KG-3 entries |
| C4: BOM validation functional | Week 5 | Catches voltage incompatibilities and logic level mismatches in test cases |
| C5: BOM review workflow functional | Week 5 | Review queue populated, CLI approve/correct working end-to-end |

---

## 6. Team D — Circuit Synthesis

### Charter

Team D owns the hardest technical problems in the system: schematic synthesis (P5), PCB layout specification, and NIR construction. They take a validated BOM and component data and produce a format-agnostic, fully specified PCB description. Their NIR is the product that Team E serializes.

### Composition

- 4 engineers: 1 senior engineer (schematic synthesis algorithm owner), 1 engineer (ERC, netlist validation), 1 engineer (layout engine, constraint solver), 1 engineer (NIR schema, builder, validator)

### Subsystem Ownership

| Subsystem | Description |
|-----------|-------------|
| S7 — Schematic Synthesizer | BOM + component data → schematic_graph (netlist) |
| S8 — Layout Engine | Schematic + KG-4 → layout_spec |
| NIR Builder | All upstream artifacts → validated NIR |

### Inputs

| Input | Source | Format |
|-------|--------|--------|
| ValidatedBOM | Team C | JSON |
| ComponentDatasheet (normalized pins) | Team A + Team B (P2) | JSON per component |
| DesignSubgraph (KG query result) | Team B | JSON |

### Outputs (API Contract)

#### Output 1: Schematic Synthesizer API

```python
def synthesize_schematic(
    bom: ValidatedBOM,
    datasheets: list[ComponentDatasheet],
    subgraph: DesignSubgraph,
    config: Config
) -> SchematicGraph:
    """
    Synthesize a complete netlist from BOM and component knowledge.
    
    Returns:
        SchematicGraph with:
        - nets: list[NetlistEntry] — all nets with all pin connections
        - blocks: list[FunctionalBlock] — functional subsystem groupings
        - erc_result: ERCResult — pass/fail with error list
        - unresolved_pins: list[PinRef] — pins that could not be connected
        - synthesis_confidence: float
        - review_flags: list[ReviewFlag]
    
    Raises:
        ERCCriticalError: if ERC finds irresolvable conflicts (caller handles review)
    """
```

#### Output 2: Layout Engine API

```python
def generate_layout_spec(
    schematic: SchematicGraph,
    datasheets: list[ComponentDatasheet],
    subgraph: DesignSubgraph,
    config: Config
) -> LayoutSpec:
    """
    Generate placement constraints and routing hints.
    
    Returns:
        LayoutSpec with:
        - placement_constraints: list[PlacementConstraint]
        - component_groups: list[ComponentGroup]
        - routing_hints: list[RoutingHint]
        - board_spec: BoardSpec
    """
```

#### Output 3: NIR Builder API

```python
def build_nir(
    bom: ValidatedBOM,
    datasheets: list[ComponentDatasheet],
    schematic: SchematicGraph,
    layout: LayoutSpec,
    config: Config
) -> NIR:
    """
    Assemble and validate the Neutral Intermediate Representation.
    
    Performs all cross-validation checks (see NIR_VALIDATION_RULES).
    Returns validated NIR or raises NIRValidationError with details.
    """
```

### Dependencies

| Dependency | From | Needed For |
|------------|------|-----------|
| ValidatedBOM | Team C | Schematic synthesis input |
| ComponentDatasheet (with normalized pins) | Team A + Team B | Connection synthesis |
| DesignSubgraph | Team B | KG-3 connection rules, KG-4 placement rules |
| `src/schemas/nir.py` | Team D owns this schema | NIR definition (all teams consume) |

### Deliverables

| Deliverable | Description | Format |
|-------------|-------------|--------|
| `src/schemas/nir.py` | NIR Pydantic schema (master source of truth) | Python module |
| `src/schematic/synthesizer.py` | Full synthesis algorithm | Python module |
| `src/schematic/net_assigner.py` | Power + protocol net assignment | Python module |
| `src/schematic/passive_assigner.py` | Decoupling + filter passive assignment | Python module |
| `src/schematic/erc.py` | Electrical rules checker | Python module |
| `src/layout/engine.py` | Constraint generation orchestrator | Python module |
| `src/layout/placement_solver.py` | Constraint satisfaction for placement | Python module |
| `src/layout/routing_hints.py` | Impedance, length match, width calculation | Python module |
| `src/nir/builder.py` | NIR assembly | Python module |
| `src/nir/validator.py` | NIR cross-validation | Python module |
| Synthesis test suite | 20 test designs with expected netlists | JSON |

### Milestones

| Milestone | Week | Exit Criteria |
|-----------|------|--------------|
| D1: NIR schema finalized | Week 2 | Schema reviewed and signed off by all teams (especially Team E) |
| D2: Power net assignment functional | Week 4 | Correct VCC/GND assignment for 20 test BOMs |
| D3: Protocol matching functional | Week 5 | SPI, I2C, UART nets correctly synthesized for 15 test cases |
| D4: Full schematic synthesis (ERC passing) | Week 6 | ERC pass rate ≥ 0.85 on 20 test designs without human intervention |
| D5: Layout engine functional | Week 6 | Placement constraints generated for all corpus components |
| D6: NIR builder + validator functional | Week 7 | NIR passes all structural checks for 18/20 test designs |

---

## 7. Team E — Output and Integration

### Charter

Team E owns the serialization layer: converting the validated NIR into KiCad files, tscircuit output, and documentation. They are responsible for the interface with both external tools and for the quality of the final deliverables that engineers receive.

### Composition

- 2–3 engineers: 1 KiCad MCP integration engineer, 1 tscircuit integration engineer, 1 documentation/validation engineer

### Subsystem Ownership

| Subsystem | Description |
|-----------|-------------|
| S10a — KiCad MCP Serializer | NIR → KiCad files via MCP |
| S10b — tscircuit Serializer | NIR → tscircuit TSX + 3D model |
| S10c — Documentation Generator | NIR → PDF design report |
| Post-output validation | ERC/DRC capture, review flagging |

### Inputs

| Input | Source | Format |
|-------|--------|--------|
| Validated NIR | Team D | JSON (NIR schema) |
| KiCad MCP server | External tool (KiCad + MCP server) | MCP protocol |
| tscircuit CLI/API | External tool | CLI or Node.js API |

### Outputs

| Output | Description | Format |
|--------|-------------|--------|
| KiCad schematic | `.kicad_sch` file | KiCad proprietary |
| KiCad PCB | `.kicad_pcb` file | KiCad proprietary |
| Gerber files | Fabrication-ready | Gerber RS-274X |
| tscircuit component | Circuit definition | TypeScript/TSX |
| Schematic SVG | Rendered schematic | SVG |
| 3D PCB model | 3D board visualization | GLB/STEP |
| BOM CSV | Formatted bill of materials | CSV |
| Design report | Full design documentation | PDF |

### API Contracts

#### KiCad Serializer API

```python
def serialize_to_kicad(
    nir: NIR,
    output_dir: Path,
    mcp_config: KiCadMCPConfig,
    config: Config
) -> KiCadOutput:
    """
    Serialize NIR to KiCad files using KiCad MCP server.
    
    Returns:
        KiCadOutput with:
        - schematic_path: Path to .kicad_sch
        - pcb_path: Path to .kicad_pcb
        - gerber_dir: Path to Gerber directory
        - bom_path: Path to BOM CSV
        - erc_result: ERCResult from KiCad
        - drc_result: DRCResult from KiCad
    """
```

#### tscircuit Serializer API

```python
def serialize_to_tscircuit(
    nir: NIR,
    output_dir: Path,
    config: Config
) -> TSCircuitOutput:
    """
    Serialize NIR to tscircuit format.
    
    Returns:
        TSCircuitOutput with:
        - tsx_path: Path to .tsx circuit file
        - json_path: Path to circuit.json
        - schematic_svg_path: Path to schematic SVG
        - pcb_3d_path: Path to 3D model (GLB)
    """
```

### Dependencies

| Dependency | From | Needed For |
|------------|------|-----------|
| Validated NIR | Team D | All serialization |
| `src/schemas/nir.py` | Team D | NIR deserialization |
| KiCad installation + MCP server | Team F (deployment) | KiCad serializer |
| tscircuit CLI (`@tscircuit/cli`) | Team F (environment) | tscircuit serializer |
| `pandoc` or `weasyprint` | Team F (environment) | Documentation PDF |

### Deliverables

| Deliverable | Description | Format |
|-------------|-------------|--------|
| `src/output/kicad_serializer.py` | NIR → KiCad MCP call sequence | Python module |
| `src/output/tscircuit_serializer.py` | NIR → tscircuit TSX/JSON | Python module |
| `src/output/doc_generator.py` | NIR → Markdown → PDF | Python module |
| tscircuit component template library | Mapping of component types to tscircuit elements | Python + TSX |
| KiCad footprint resolver | Footprint name → KiCad library reference | Python module |
| Post-output validation capture | ERC/DRC result ingestion from KiCad/tscircuit | Python module |
| End-to-end output test suite | 10 designs: NIR in → expected outputs | Test fixtures |

### Milestones

| Milestone | Week | Exit Criteria |
|-----------|------|--------------|
| E1: NIR schema consumed (mock test) | Week 3 | Serializers can deserialize a mock NIR and generate placeholder output |
| E2: KiCad serializer functional | Week 6 | Generates valid .kicad_sch from NIR for 5 test designs, ERC passes |
| E3: tscircuit serializer functional | Week 6 | Generates valid TSX + schematic SVG from NIR for 5 test designs |
| E4: 3D model generation | Week 7 | GLB output generated for 5 test designs |
| E5: Documentation generator | Week 7 | PDF design report generated for all 20 test designs |
| E6: Gerber export | Week 8 | Fabrication-ready Gerbers generated for 5 test designs |

---

## 8. Team F — Platform and Infrastructure

### Charter

Team F owns everything that all other teams depend on: the development environment, Docker deployment, model weight management, CI/CD, the evaluation framework, the review CLI, and all shared schemas. They do not own any product subsystem but their quality directly determines every team's velocity.

### Composition

- 2 engineers: 1 DevOps/infrastructure engineer, 1 platform/tooling engineer

### Responsibilities

| Responsibility | Description |
|----------------|-------------|
| Docker image | Build and maintain the air-gapped Docker image with all model weights baked in |
| Schema ownership | `src/schemas/` — NIR, ComponentDatasheet, KGNode — reviewed and versioned |
| Review CLI | `src/review/cli.py` — universal review tool used by all teams |
| Eval framework | `eval/run_eval.py`, metrics per stage, report generation |
| CI/CD | Automated test runs on every commit, linting, type checking |
| Storage setup | Neo4j, PostgreSQL, FAISS setup and configuration |
| Model registry | Model weight download scripts, version tracking |
| Environment spec | `pyproject.toml`, dependency management |

### Deliverables

| Deliverable | Description | Target Week |
|-------------|-------------|------------|
| `src/schemas/` (all schemas) | Pydantic models for all inter-team contracts | Week 1 |
| `src/config.py` | Single source of configuration | Week 1 |
| `pyproject.toml` | Full dependency specification | Week 1 |
| Project directory structure | All `__init__.py`, folder layout | Week 1 |
| `src/review/cli.py` | Universal review CLI | Week 2 |
| `src/review/queue.py` | SQLite review queue | Week 2 |
| Docker base image | CUDA + Python + Poppler + Neo4j | Week 2 |
| Model download scripts | Automated weight setup | Week 1 |
| `eval/run_eval.py` | Per-phase eval runner | Week 3 |
| `eval/metrics.py` | Precision, recall, F1 per stage | Week 3 |
| CI configuration | GitHub Actions or equivalent | Week 2 |
| Air-gapped deployment script | `build_airgapped_image.sh` | Week 8 |
| DEPLOYMENT_RUNBOOK.md | Step-by-step air-gapped deployment | Week 8 |

---

## 9. Inter-Team Dependencies Map

```
         Team F: Platform
         (schemas, env, infra)
              │ provides to all
    ┌─────────┼─────────────────────────────┐
    │         │                             │
    ▼         ▼                             ▼
 Team A    Team B                        Team C
 (Data)    (KG)                        (Intelligence)
    │         │                             │
    │ CDJ     │ normalized CDJ              │ ValidatedBOM
    └────────►│                             │
              │ DesignSubgraph (query API)  │
              └────────────────────────────►│
                                           │
                              ValidatedBOM │
                                           ▼
                                        Team D
                                     (Synthesis)
                                           │
                                      NIR  │
                                           ▼
                                        Team E
                                        (Output)

CDJ = ComponentDatasheet JSON
```

---

## 10. Coordination Protocols

### Weekly Sync Structure

| Meeting | Participants | Cadence | Purpose |
|---------|-------------|---------|---------|
| All-hands | All team leads | Weekly | Cross-team blockers, milestone check |
| A↔B sync | Team A lead + Team B lead | Weekly | ComponentDatasheet format alignment, ingestion pipeline status |
| B↔C sync | Team B lead + Team C lead | Weekly | KG query API contract, subgraph format |
| C↔D sync | Team C lead + Team D lead | Weekly | BOM format, synthesis integration |
| D↔E sync | Team D lead + Team E lead | Weekly | NIR schema changes, serializer integration |
| A↔F sync | Team A + Team F | Weekly | Model weight updates, eval framework |

### API Contract Change Protocol

1. Proposing team drafts the change to `src/schemas/` with rationale
2. Post to shared channel with 48-hour comment period
3. Consuming team(s) review and raise concerns
4. Team F merges and updates all affected tests
5. Proposing team provides migration path for any downstream breakage
6. No schema change is merged without all consuming team sign-off

### Review Queue Protocol

1. Any team can write to the shared SQLite review queue via `src/review/queue.py`
2. Items are tagged with `stage` and `severity`
3. Designated review engineers (one per team) process the queue daily
4. Corrections are exported weekly to `data/corrections_export.jsonl` for future fine-tuning

---

## 11. Complete Document Register

| Document | Owner | Consumers | Purpose |
|----------|-------|----------|---------|
| OPENFORGE_ARCHITECTURE.md | Team F | All teams | System-level architecture, flow, storage |
| OPENFORGE_SUBSYSTEMS.md | Team F | All teams | Per-subsystem technical spec |
| OPENFORGE_ORGANIZATION.md (this) | TPM | All teams | Team structure, APIs, milestones |
| OPENFORGE_INTEGRATION.md | Team E | Teams D, E | tscircuit + KiCad deep dive |
| `src/schemas/nir.py` | Team D | Teams D, E | NIR schema — master source |
| `src/schemas/datasheet.py` | Team F | Teams A, B, D | ComponentDatasheet schema |
| `src/schemas/kg.py` | Team F | Team B | KGNode + KGEdge schema |
| `src/schemas/intent.py` | Team C | Teams C, D | IntentDict + ValidatedBOM schema |
| KNOWLEDGE_GRAPH_SPEC.md | Team B | Teams B, A | Node types, edge types, ingestion rules per layer |
| VALIDATION_PLAN.md | Team F | All teams | Eval corpus, metrics, acceptance gates per stage |
| API_CONTRACT_TEAM_A.md | Team A | Team B | ComponentDatasheet JSON format + parse_datasheet() contract |
| API_CONTRACT_TEAM_B.md | Team B | Teams C, D | query_graph() + normalize_pins() + search_components() contracts |
| API_CONTRACT_TEAM_C.md | Team C | Team D | parse_intent() + generate_bom() contracts |
| API_CONTRACT_TEAM_D.md | Team D | Team E | synthesize_schematic() + build_nir() contracts |
| API_CONTRACT_NIR.md | Team D | Team E | NIR JSON schema with examples |
| DEPLOYMENT_RUNBOOK.md | Team F | Operations | Air-gapped Docker deployment procedure |
| EVAL_CORPUS_SPEC.md | Team A | Teams A, F | Golden corpus composition, annotation format |
| HARDWARE_SPEC.md | Team F | All teams | GPU/CPU requirements, model VRAM breakdown |
| TSCIRCUIT_INTEGRATION.md | Team E | Team E | tscircuit API reference, component mapping |
| KICAD_MCP_INTEGRATION.md | Team E | Team E | KiCad MCP tool reference, call sequence |

---

*This document governs the engineering organization of OpenForge. Update it when team ownership changes, API contracts are renegotiated, or milestones are revised. All changes require TPM and affected team lead approval.*
