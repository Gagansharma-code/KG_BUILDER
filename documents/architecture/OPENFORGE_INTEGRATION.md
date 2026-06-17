# OpenForge PCB Intelligence System — Integration Strategy and Requirements

**Version:** 1.0
**Owner:** Team E (Output and Integration)
**Derives from:** OPENFORGE_ARCHITECTURE.md, OPENFORGE_SUBSYSTEMS.md

---

## 1. tscircuit Integration

### 1.1 What tscircuit Is

tscircuit is an open-source React-based electronics design framework. It represents circuits as TypeScript/React component trees and can render schematics as SVG, generate 3D PCB models, and export Gerber files. Unlike KiCad (which is a desktop application), tscircuit is a library — circuit generation is programmatic and can be driven from Python via subprocess or Node.js API calls.

tscircuit's fundamental model: a circuit is a tree of React components. Each component declares its connections declaratively. The tscircuit core resolves the tree into a netlist and runs layout and routing.

### 1.2 Why tscircuit Is a First-Class Output

tscircuit offers capabilities that KiCad MCP does not:

| Capability | tscircuit | KiCad MCP |
|-----------|----------|----------|
| Programmatic circuit generation (no GUI) | Native | Via MCP protocol |
| SVG schematic rendering (embeddable) | Native | Requires KiCad GUI export |
| 3D PCB model (STEP/GLB) | Native | Requires KiCad with 3D viewer |
| Browser-renderable output | Native (SVG, JSON) | Not natively |
| Git-diff-friendly format | Yes (TypeScript source) | Partially (text format) |
| Component footprint library | tscircuit registry | KiCad library |
| Integrated design check | tscircuit DRC | KiCad DRC |

The two tools are complementary: KiCad is the industry standard for PCB fabrication workflows; tscircuit is superior for visualization, documentation, and programmatic design review.

### 1.3 tscircuit Data Model

tscircuit represents circuits at four levels:

**Level 1 — Component declaration:**
```tsx
<resistor name="R1" resistance="10k" footprint="0402" />
<chip name="U1" footprint="SOT-23-5" />
<capacitor name="C1" capacitance="10uF" footprint="0402" />
```

**Level 2 — Connection:**
```tsx
circuit.connect("U1.VCC", "R1.pin1")
circuit.connect("R1.pin2", ".VCC")  // power net
circuit.connect("U1.GND", ".GND")  // ground net
```

**Level 3 — Placement:**
```tsx
circuit.place("C1", {
  near: "U1.VCC",
  maxDistance: "2mm",
  layer: "top"
})
```

**Level 4 — Routing hints:**
```tsx
circuit.setRoutingConstraint("RF_OUT", {
  type: "impedance_controlled",
  impedance: 50,  // ohms
  traceWidth: "0.35mm"
})
```

### 1.4 NIR → tscircuit Mapping

The tscircuit serializer maps every NIR field to a tscircuit construct:

| NIR Field | tscircuit Construct |
|-----------|-------------------|
| `components[].ref` | `name` prop on component element |
| `components[].component_type` | tscircuit element type (resistor, capacitor, chip, etc.) |
| `components[].value` | `resistance`, `capacitance`, `inductance`, or `voltage` prop |
| `components[].footprint` | `footprint` prop |
| `netlist[].connections` | `circuit.connect()` call per pin pair |
| `netlist[].net_type == "power"` | `.VCC`, `.GND` power net references |
| `placement_constraints[]` | `circuit.place()` call with constraint params |
| `routing_hints[]` | `circuit.setRoutingConstraint()` call |
| `component_groups[]` | tscircuit group element wrapping components |

### 1.5 Component Type Mapping

```python
# src/output/tscircuit_serializer.py

TSCIRCUIT_ELEMENT_MAP = {
    # Passives
    "resistor": "resistor",
    "capacitor": "capacitor",
    "inductor": "inductor",
    "crystal": "crystal",
    "transformer": "inductor",  # closest available
    
    # Active components
    "ic": "chip",
    "microcontroller": "chip",
    "voltage_regulator": "chip",
    "op_amp": "chip",
    "comparator": "chip",
    "gate_driver": "chip",
    "RF_IC": "chip",
    
    # Discrete semiconductors
    "diode": "diode",
    "led": "led",
    "transistor": "transistor",
    "mosfet": "transistor",
    
    # Connectors and mechanical
    "connector": "connector",
    "sma_connector": "connector",
    "antenna": "antenna",
    
    # Power
    "power_source": "power_source",
}

def get_tscircuit_props(component: ComponentRef) -> dict:
    """Map NIR ComponentRef to tscircuit prop dict."""
    base_props = {"name": component.ref, "footprint": component.footprint}
    
    type_specific = {
        "resistor": {"resistance": component.value},
        "capacitor": {"capacitance": component.value},
        "inductor": {"inductance": component.value},
        "diode": {},
        "led": {"color": component.properties.get("led_color", "red")},
        "chip": {},
        "connector": {"pinCount": component.properties.get("pin_count", 2)},
        "power_source": {"voltage": component.value},
    }
    
    element_type = TSCIRCUIT_ELEMENT_MAP.get(component.component_type, "chip")
    return {**base_props, **type_specific.get(element_type, {})}
```

### 1.6 Full Serializer Output Structure

```python
class TSCircuitOutput:
    tsx_path: Path          # .tsx file: importable React circuit component
    json_path: Path         # circuit.json: JSON representation
    schematic_svg_path: Path  # rendered schematic SVG
    pcb_3d_path: Path       # 3D model (GLB format)
    bom_json_path: Path     # BOM in tscircuit format
    validation_result: dict  # tscircuit DRC/connectivity check results
```

### 1.7 Generated TSX File Format

```typescript
// Auto-generated by OpenForge tscircuit serializer v1.0
// Design ID: {design_id}
// Prompt: {original_prompt}
// Generated: {timestamp}
// Confidence: {aggregate_confidence}

import { Circuit, Resistor, Capacitor, Chip, PowerSource, Connector } from "@tscircuit/core"

/**
 * {design_id} — {original_prompt}
 * 
 * Components:
 * {bom_summary}
 * 
 * Design Methodology: {design_methodology}
 */
export const {design_id}Circuit = () => {
  const circuit = new Circuit()
  
  // ── Components ───────────────────────────────────────────────
  circuit.add(<Chip name="U1" footprint="SOT-23-5" />)          // TPS62933DRLR — buck converter
  circuit.add(<Capacitor name="C1" capacitance="10uF" footprint="0402" />)  // Input bypass — VCC_3V3
  circuit.add(<Inductor name="L1" inductance="1uH" footprint="0402" />)     // Power inductor
  
  // ── Connections ──────────────────────────────────────────────
  circuit.connect("U1.VIN", "C1.pos")
  circuit.connect("C1.neg", ".GND")
  circuit.connect("U1.SW", "L1.pin1")
  circuit.connect("L1.pin2", ".VCC_OUT")
  circuit.connect("U1.GND", ".GND")
  
  // ── Placement Constraints ────────────────────────────────────
  // C1 must be within 2mm of U1.VIN — source: TPS62933 datasheet layout section
  circuit.place("C1", { near: "U1.VIN", maxDistance: "2mm", hard: true })
  
  // ── Routing Hints ─────────────────────────────────────────────
  // SW node: minimize trace length — source: TPS62933 layout guidelines
  circuit.setRoutingConstraint("U1.SW_NET", { type: "min_length", note: "Minimize SW trace" })
  
  return circuit
}
```

### 1.8 tscircuit CLI Invocation

```python
# src/output/tscircuit_serializer.py

import subprocess
from pathlib import Path

def render_tscircuit_outputs(tsx_path: Path, output_dir: Path) -> dict[str, Path]:
    """
    Invoke tscircuit CLI to generate SVG, 3D model, and JSON from TSX source.
    
    Requires: @tscircuit/cli installed (npx @tscircuit/cli or globally)
    Air-gapped note: install tscircuit CLI via offline npm cache
    """
    base_cmd = ["npx", "@tscircuit/cli", "export"]
    
    results = {}
    
    # Generate schematic SVG
    svg_path = output_dir / "schematic.svg"
    subprocess.run(
        [*base_cmd, "--format", "svg", "--output", str(svg_path), str(tsx_path)],
        check=True, capture_output=True
    )
    results["schematic_svg"] = svg_path
    
    # Generate 3D model
    glb_path = output_dir / "pcb_3d.glb"
    subprocess.run(
        [*base_cmd, "--format", "3d", "--output", str(glb_path), str(tsx_path)],
        check=True, capture_output=True
    )
    results["pcb_3d"] = glb_path
    
    # Generate JSON
    json_path = output_dir / "circuit.json"
    subprocess.run(
        [*base_cmd, "--format", "json", "--output", str(json_path), str(tsx_path)],
        check=True, capture_output=True
    )
    results["circuit_json"] = json_path
    
    return results
```

### 1.9 tscircuit Infrastructure Requirements

| Requirement | Detail |
|-------------|--------|
| Node.js | v18+ (for tscircuit CLI) |
| tscircuit CLI | `@tscircuit/cli` installed via npm |
| npm offline cache | Pre-populated for air-gapped deployment |
| tscircuit footprint registry | Mirror locally for air-gapped operation |
| Storage | ~100MB for tscircuit + dependencies |

### 1.10 tscircuit Footprint Resolution

tscircuit fetches footprints from its registry (tscircuit.com/footprints) by default. For air-gapped operation:
- Download and mirror the full footprint registry locally during build-time
- Configure tscircuit CLI with `--registry-url file:///app/footprint-registry`
- Footprint names in NIR must match tscircuit registry naming convention

NIR footprint field format: standard IPC-7351 naming (`0402`, `SOT-23-5`, `SOIC-8`, `QFN-16`) which tscircuit accepts natively.

---

## 2. KiCad MCP Integration

### 2.1 What KiCad MCP Is

The KiCad MCP (Model Context Protocol) server exposes KiCad's design operations as structured tool calls. Instead of operating KiCad's GUI, the MCP server accepts JSON-formatted tool calls and translates them into KiCad operations. The MCP server runs as a sidecar process alongside KiCad.

KiCad MCP is critical because: (1) KiCad's native file formats (.kicad_sch, .kicad_pcb) are the industry standard for PCB fabrication. Any fab house accepts them. (2) KiCad's ERC and DRC are authoritative and industry-trusted. Running them on the OpenForge output provides a rigorous final validation.

### 2.2 Token Optimization Strategy (P6)

The original P6 objective notes that KiCad MCP integration requires strict context window management. OpenForge's approach:

**No LLM mediates the MCP calls.** The KiCad serializer generates the MCP tool call sequence deterministically from the NIR. No Qwen model sees the KiCad tool calls. This eliminates the token overflow risk entirely.

The serializer is a pure Python function: NIR → ordered list of MCP tool calls → execute sequentially. The only LLM involvement is upstream in the pipeline (intent parsing, semantic extraction), which has already run before the serializer is invoked.

### 2.3 MCP Tool Call Sequence

```python
# src/output/kicad_serializer.py

def serialize_to_kicad(nir: NIR, output_dir: Path, mcp_config: KiCadMCPConfig) -> KiCadOutput:
    
    mcp = KiCadMCPClient(mcp_config)
    
    # Phase 1: Create schematic
    mcp.call("create_schematic", {"name": nir.design_id, "template": "empty"})
    
    # Phase 2: Add component symbols
    for component in nir.components:
        library_ref = resolve_kicad_symbol(component.component_id, component.component_type)
        mcp.call("add_symbol", {
            "reference": component.ref,
            "library": library_ref.library,
            "symbol": library_ref.symbol,
            "value": component.value or component.component_id,
            "footprint": resolve_kicad_footprint(component.footprint),
            "position": {"x": 0, "y": 0}  # initial position, will be placed in Phase 7
        })
    
    # Phase 3: Add power symbols for each power net
    power_nets = [n for n in nir.netlist if n.net_type == "power"]
    for net in power_nets:
        mcp.call("add_power_symbol", {
            "net_name": net.net_name,
            "symbol": map_power_net_to_symbol(net.net_name)  # VCC_3V3 → VCC, GND → GND
        })
    
    # Phase 4: Add wires (netlist → schematic connections)
    for net in nir.netlist:
        pins = net.connections
        for i in range(len(pins) - 1):
            mcp.call("add_wire", {
                "net": net.net_name,
                "from_component": pins[i].ref,
                "from_pin": pins[i].pin_name,
                "to_component": pins[i+1].ref,
                "to_pin": pins[i+1].pin_name
            })
    
    # Phase 5: Add net labels (for multi-point nets)
    for net in nir.netlist:
        if len(net.connections) > 2:
            for pin in net.connections:
                mcp.call("add_net_label", {
                    "net_name": net.net_name,
                    "component": pin.ref,
                    "pin": pin.pin_name
                })
    
    # Phase 6: Run ERC
    erc_result = mcp.call("run_erc", {})
    
    # Phase 7: Create PCB
    mcp.call("create_pcb", {
        "name": nir.design_id,
        "board_layers": nir.board_spec.layers,
        "board_outline": generate_board_outline(nir.board_spec)
    })
    
    # Phase 8: Place footprints
    positions = compute_initial_positions(nir)  # constraint-satisfaction placement
    for component in nir.components:
        pos = positions[component.ref]
        mcp.call("place_footprint", {
            "reference": component.ref,
            "x": pos.x,
            "y": pos.y,
            "layer": pos.layer,
            "rotation": pos.rotation
        })
    
    # Phase 9: Apply routing constraints
    for hint in nir.routing_hints:
        if hint.hint_type == "impedance_controlled":
            mcp.call("set_net_class", {
                "nets": hint.nets,
                "trace_width": hint.value,
                "clearance": nir.board_spec.min_clearance_mm
            })
        elif hint.hint_type == "differential_pair":
            mcp.call("add_differential_pair_rule", {"nets": hint.nets})
        elif hint.hint_type == "min_width":
            mcp.call("set_net_class", {"nets": hint.nets, "trace_width": hint.value})
    
    # Phase 10: Apply keepout zones
    keepouts = [c for c in nir.placement_constraints if c.constraint_type == "keepout"]
    for keepout in keepouts:
        mcp.call("add_keepout_zone", {
            "reference": keepout.ref,
            "clearance_mm": keepout.min_distance_mm,
            "layer": "all"
        })
    
    # Phase 11: Run DRC
    drc_result = mcp.call("run_drc", {})
    
    # Phase 12: Export outputs
    gerber_dir = output_dir / "gerbers"
    mcp.call("export_gerbers", {"output_dir": str(gerber_dir)})
    bom_path = output_dir / "bom.csv"
    mcp.call("export_bom", {"output_path": str(bom_path), "format": "csv"})
    sch_path = output_dir / f"{nir.design_id}.kicad_sch"
    pcb_path = output_dir / f"{nir.design_id}.kicad_pcb"
    mcp.call("save_all", {"schematic_path": str(sch_path), "pcb_path": str(pcb_path)})
    
    return KiCadOutput(
        schematic_path=sch_path,
        pcb_path=pcb_path,
        gerber_dir=gerber_dir,
        bom_path=bom_path,
        erc_result=ERCResult(**erc_result),
        drc_result=DRCResult(**drc_result)
    )
```

### 2.4 Symbol and Footprint Resolution

KiCad requires that every component maps to a symbol in its library system. The resolver handles this:

```python
KICAD_SYMBOL_MAP = {
    # component_id → KiCad library:symbol
    "TPS62933DRLR": "Device:TPS62933",
    "TLV7021DBVR": "Comparator:TLV7021",
    # For components not in map, use component_type as fallback
}

KICAD_FOOTPRINT_MAP = {
    # NIR footprint string → KiCad footprint library:name
    "SOT-23-5": "Package_TO_SOT_SMD:SOT-23-5",
    "0402": "Resistor_SMD:R_0402_1005Metric",
    "0402_C": "Capacitor_SMD:C_0402_1005Metric",
    "SOT-23-3": "Package_TO_SOT_SMD:SOT-23",
    "SOIC-8": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    "QFN-16": "Package_DFN_QFN:QFN-16-1EP_3x3mm_P0.5mm_EP1.5x1.5mm",
}
```

Components not in the map are flagged for manual symbol assignment before schematic generation proceeds.

### 2.5 KiCad Footprint Position Calculator

The layout engine provides placement constraints (proximity, keepout, grouping) but not absolute coordinates. The KiCad serializer must convert constraints into absolute (x, y) positions.

```python
def compute_initial_positions(nir: NIR) -> dict[str, ComponentPosition]:
    """
    Convert placement constraints + component groups into initial absolute positions.
    This is a constraint-satisfaction problem solved by a simple force-directed layout.
    
    Algorithm:
    1. Group components by component_group
    2. Assign each group a region of the board
    3. Within each group, apply proximity constraints via force-directed placement
    4. Respect layer assignments (top/bottom)
    5. Return absolute (x, y, layer, rotation) per component
    """
```

The resulting positions are approximate — KiCad's interactive router and the engineer's manual review will refine them. The goal is to satisfy all hard constraints and get soft constraints as close as possible.

### 2.6 KiCad MCP Infrastructure Requirements

| Requirement | Detail |
|-------------|--------|
| KiCad installation | KiCad 7.x or 8.x (stable) |
| KiCad MCP server | kicad-mcp project (Python, runs alongside KiCad) |
| KiCad symbol libraries | KiCad standard library + custom library for DRDO components |
| KiCad footprint libraries | KiCad standard library |
| Display server | Xvfb (virtual framebuffer) for headless KiCad in Docker |
| Storage | ~2GB for KiCad + libraries |

---

## 3. NIR as Source of Truth

### 3.1 Why the NIR Exists

Without the NIR, two paths exist:
- **Path A:** Intelligence layer writes directly to KiCad → design is locked to KiCad, tscircuit integration requires re-running the intelligence layer
- **Path B:** Intelligence layer writes to both KiCad and tscircuit simultaneously → two synchronization problems, potential inconsistency between outputs

The NIR solves this by making the intelligence layer's output format-agnostic. The intelligence layer (Teams A–D) knows nothing about KiCad or tscircuit. Team E serializes the same NIR to both. If tscircuit adds new features, only the tscircuit serializer changes. If the NIR schema changes, it changes once and both serializers update.

### 3.2 NIR Schema Governance

The NIR schema (`src/schemas/nir.py`) is owned by Team D and governed by Team F. Changes require:
1. Team D proposes change with rationale
2. Team E reviews for serializability impact
3. Team F bumps the schema version
4. Both serializers are updated in the same PR
5. Test fixtures are updated
6. No partial migrations — all outputs from a given schema version are consistent

### 3.3 NIR Versioning

```python
class NIR:
    schema_version: str = "1.0"  # bumped on any breaking change
    # ...
```

Old NIR files can be identified by `schema_version` for reprocessing if schema changes.

---

## 4. Per-Subsystem Requirements Deep Dive

### 4.1 S1: Datasheet Parsing

| Category | Requirement | Detail |
|----------|-------------|--------|
| Datasets | Golden corpus | 5 datasheets, hand-annotated, covers logic IC, voltage comparator, large MCU, power controller, I2C sensor |
| Datasets | Test corpus | 25 datasheets: 8 logic, 6 voltage regulators, 6 MCUs, 4 op-amps, 4 power MOSFETs, 2 mixed-signal |
| Models | YOLOv8n-DocLayNet | Table/footnote detection; 11 classes; ONNX-exportable |
| Models | Qwen2-VL-7B-Instruct | Borderless table → markdown (TSR Path B) |
| Models | Qwen2.5-7B-Instruct | Semantic extraction + layout section parsing |
| Infrastructure | GPU 24GB VRAM | Required for Qwen2-VL inference in acceptable time |
| Infrastructure | Poppler | PDF rasterization at 300 DPI |
| Storage | 200GB NVMe | Model weights + corpus + outputs |
| Bottleneck | VLM inference speed | 5–10s per table on GPU; multiply by avg tables per datasheet (~15) = ~150s per datasheet |
| Failure mode | Borderless table hallucination | Dual-path + Phase 4 catches most; residual rate estimated < 2% |
| Failure mode | Layout section missing | ~30% of datasheets have no structured layout section; graceful skip |
| Accuracy risk | Phase 5 layout extraction | Less structured than electrical tables; expect lower recall (0.85 target) |
| Mitigation | Mock-first development | All phases written with fixtures; GPU model swaps in with zero code changes |

### 4.2 S4: Knowledge Graph

| Category | Requirement | Detail |
|----------|-------------|--------|
| Datasets | All About Circuits | Vols 1, 2, 3, 5 HTML; ~2000 pages of content |
| Datasets | TI app notes | Priority 20 (RF, power, gate driver, analog); expandable to 200+ |
| Datasets | ADI app notes | Priority 10 (precision analog, RF, power) |
| Datasets | IPC-2221 | Freely available; standard trace width and clearance tables |
| Models | spaCy en_core_web_trf | SVO triple extraction from engineering text |
| Models | Qwen2.5-7B-Instruct | Ambiguous triple resolution + placement rule extraction |
| Infrastructure | Neo4j | Production graph; 4GB heap; sidecar Docker container |
| Infrastructure | NetworkX | Prototype; no setup; serialize to GraphML |
| Infrastructure | FAISS | Vector index; ~500MB for 100K node embeddings |
| Storage | 20GB | Graph dump + triple JSONL + source documents |
| Bottleneck | Triple extraction quality | Manual spot-check required per source batch |
| Bottleneck | KG-5 methodology rules | Manual curation; limited by expert availability |
| Failure mode | Low-quality triple injection | Source: low-quality app notes → bad edges | Mitigation: source trust tier filter |
| Failure mode | Graph traversal slow on large subgraphs | Mitigation: depth limit + methodology filter applied early + result caching |
| Accuracy risk | KG-2 design recipe coverage | Only covers ingested app notes; gaps for novel designs | Mitigation: human review gate in BOM |
| Mitigation | Source versioning | Content hash prevents re-ingesting unchanged sources |

### 4.3 S5: Intent Understanding

| Category | Requirement | Detail |
|----------|-------------|--------|
| Models | Qwen2.5-7B-Instruct | NL → IntentDict via Instructor |
| Datasets | 20 test prompts | Covering: simple, complex, ambiguous, multi-constraint prompts |
| Infrastructure | Shared GPU (model already loaded from P1 pipeline) | No additional hardware |
| Bottleneck | Methodology misclassification on novel prompts | Mitigation: explicit rule table in system prompt + human review gate |
| Failure mode | Overly broad prompt ("build something wireless") | Mitigation: clarification question generator |
| Failure mode | Conflicting constraints ("compact and 100W output") | Mitigation: AmbiguityFlag with conflict type |

### 4.4 S6: BOM Generation

| Category | Requirement | Detail |
|----------|-------------|--------|
| Datasets | 20 hand-verified test BOMs | One per test prompt; manually checked against datasheets |
| Infrastructure | Supplier cache database (SQLite) | Updated offline; includes component availability + pricing snapshot |
| Bottleneck | Specific part selection for uncommon components | KG-3 may not have entries for all component types |
| Failure mode | Supplier cache stale | Flag with cache date; engineer verifies before procurement |
| Accuracy risk | No specific part in KG-3 for required type | Result: component type suggested without specific part; human selects |

### 4.5 S7: Schematic Synthesis

| Category | Requirement | Detail |
|----------|-------------|--------|
| Datasets | 20 test designs with expected netlists | Hand-verified net assignments for each test BOM |
| Models | None (rule-based + KG traversal) | Schematic synthesis is deterministic given KG + P2 output |
| Infrastructure | None beyond main system | Runs on CPU; synthesis is fast |
| Bottleneck | Novel component combinations not in KG-3 | Connection rules missing → unresolved pins → human review |
| Failure mode | Protocol ambiguity (MCU with both SPI and I2C peripherals on same pins) | Mitigation: pin table disambiguation; prioritize per application context |
| Failure mode | Missing passive in BOM | Mitigation: synthesizer requests BOM additions; BOM generator must handle back-propagation |
| Accuracy risk | ERC pass rate below target (< 0.85) | Root cause: missing KG-3 connection rules; fix by expanding corpus |

### 4.6 S8: PCB Layout Engine

| Category | Requirement | Detail |
|----------|-------------|--------|
| Datasets | Placement rule corpus | Phase 5 output for all 30 corpus datasheets + 20 app notes |
| Datasets | IPC-2221 trace width tables | Parsed into RoutingRule nodes in KG-4 |
| Models | Qwen2.5-7B-Instruct | Placement constraint extraction (shared with P1 Phase 5) |
| Infrastructure | None beyond main system | Layout engine is rule-based; no ML inference |
| Bottleneck | Constraint conflicts | Multiple sources specify conflicting constraints for same component |
| Failure mode | Missing substrate parameters for impedance calculation | Mitigation: FR4 defaults; engineer review flag |
| Failure mode | Board space estimation incorrect | Mitigation: conservative board size; engineer adjusts |

### 4.7 S10: Output Serializers

| Category | Requirement | Detail |
|----------|-------------|--------|
| Infrastructure (KiCad) | KiCad 7.x or 8.x + MCP server | Runs as sidecar; requires Xvfb for headless Docker |
| Infrastructure (tscircuit) | Node.js 18+ + @tscircuit/cli | Installed from offline npm cache |
| Infrastructure (docs) | pandoc or weasyprint | PDF generation from Markdown |
| Storage | Variable per design | Gerbers ~5MB; KiCad files ~2MB; tscircuit output ~1MB |
| Bottleneck | KiCad symbol resolution for unknown components | Missing symbols block schematic generation |
| Failure mode | tscircuit footprint not found in local registry | Mitigation: full registry mirrored locally; fallback to generic footprint with review flag |
| Failure mode | KiCad ERC/DRC errors in generated files | Expected on first integration; mitigation: capture and route to review queue |
| Accuracy risk | Position calculator produces poor initial placement | Mitigation: KiCad interactive router can fix; positions are soft guidance, not hard requirement |

---

## 5. End-to-End Failure Mode Analysis

The following scenarios represent the highest-risk failure paths across the entire pipeline.

| Scenario | Path | Impact | Detection | Mitigation |
|----------|------|--------|-----------|------------|
| VLM hallucination in P1 | Phase 2 → Phase 3 | Wrong component specs → bad PCB | Phase 4 physics validation | Dual-path confidence selection + validation blocks propagation |
| KG-3 gap for required component | L1 → L2 | No specific part in BOM | BOM confidence < 0.75 | Human review gate; engineer selects specific part |
| Unresolved pin in schematic synthesis | L5 ERC | Floating pin on output schematic | ERC pre-check flags it | Human review gate; engineer manually resolves |
| Methodology misclassification | L0 → L1 | Wrong rule set → wrong placement constraints | BOM consistency check | Human review gate at BOM; engineer can override methodology |
| KiCad symbol missing for component | L8a | KiCad serializer blocks | Resolver exception | Resolver returns error before MCP call; review flag added |
| tscircuit footprint missing | L8b | TSX file has unknown footprint | tscircuit DRC error | Local registry fallback to generic; review flag |
| Placement constraint conflict | L6 → L7 | DRC violation in output | NIR validator checks | Higher-priority source wins; conflict logged in review flag |
| Multi-page table truncation in P1 | Phase 1 | Missing rows → incomplete parameter set | Phase 3 field count below expected | Multi-page merger catches most; residual caught by Phase 4 |

---

*This document is the integration reference for Team E and all teams interfacing with the output layer. Changes to the tscircuit or KiCad MCP APIs must be reflected here immediately.*
