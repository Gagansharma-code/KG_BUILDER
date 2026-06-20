# tscircuit Serializer — Known Accuracy Problems and Solutions

**Status:** Pre-validation. These problems are identified from code inspection.
None have been confirmed or ruled out by a real end-to-end pipeline run yet.
That run is the acceptance gate for Team E.

---

## Problem 1 — Footprint Name Resolution

### What the problem is

The NIR stores footprints as IPC-7351 normalized strings: `"SOT-23-5"`, `"0402"`, `"SOIC-8"`. The tscircuit serializer writes these directly into the footprint prop:

```typescript
circuit.add(<Chip name="U1" footprint="SOT-23-5" />)
```

tscircuit resolves footprints from its own internal registry. If the registry uses a different naming convention — `"sot23_5"`, `"SOT23-5"`, `"package:SOT-23-5"` — the footprint silently fails. The component appears in the schematic SVG as a generic unlabelled box with no land pattern. There is no error thrown. You only discover it by looking at the rendered output.

### Why it matters

A component with a wrong or unresolved footprint cannot be used for PCB layout. The 3D model will be wrong. The pad dimensions will be missing. The Gerber output will be incomplete.

### Solution

Build a footprint mapping table that translates IPC-7351 names to tscircuit registry names. Apply it in the serializer before writing the footprint prop.

```python
# src/output/tscircuit_footprint_map.py

TSCIRCUIT_FOOTPRINT_MAP: dict[str, str] = {
    # IPC-7351 name → tscircuit registry name
    # Populate by checking tscircuit registry at:
    # https://github.com/tscircuit/footprints
    "SOT-23-5":    "SOT-23-5",         # verify exact string
    "SOT-23-3":    "SOT-23",
    "SOT-23":      "SOT-23",
    "SOIC-8":      "SOIC-8_3.9x4.9mm_P1.27mm",
    "SOIC-16":     "SOIC-16_3.9x9.9mm_P1.27mm",
    "DIP-8":       "DIP-8_W7.62mm",
    "QFN-16":      "QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm",
    "QFN-24":      "QFN-24-1EP_4x4mm_P0.5mm_EP2.6x2.6mm",
    "0402":        "C_0402_1005Metric",   # for capacitors
    "0402_R":      "R_0402_1005Metric",   # for resistors
    "0603":        "C_0603_1608Metric",
    "0805":        "C_0805_2012Metric",
    "TO-220":      "TO-220-3_Vertical",
    "TSSOP-8":     "TSSOP-8_3x3mm_P0.65mm",
    "SMA":         "SMA_Amphenol_132289",
}

def resolve_footprint(ipc_name: str, component_type: str) -> tuple[str, bool]:
    """
    Translate IPC-7351 footprint name to tscircuit registry name.
    Returns (resolved_name, needs_review).
    needs_review=True if no mapping found.
    """
    # Passives use type-specific suffixes
    if component_type == "resistor" and ipc_name in ("0402", "0603", "0805"):
        mapped = ipc_name.replace("0402", "R_0402_1005Metric") \
                         .replace("0603", "R_0603_1608Metric") \
                         .replace("0805", "R_0805_2012Metric")
        return mapped, False

    if ipc_name in TSCIRCUIT_FOOTPRINT_MAP:
        return TSCIRCUIT_FOOTPRINT_MAP[ipc_name], False

    # Unknown: pass through and flag
    return ipc_name, True
```

**Validation step:** Run `resolve_footprint()` on all footprints in the NIR before generating the TSX file. Collect all `needs_review=True` results. If any exist, add a `ReviewFlag` to the output and log a warning. Do not block output — generate the file with the raw IPC name as fallback, but flag it clearly.

**How to build the full map:** Run the tscircuit CLI against a test circuit with each footprint name and check whether it renders correctly. This is a one-time manual verification process per footprint name. Automate it as a test: for each entry in `TSCIRCUIT_FOOTPRINT_MAP`, generate a minimal TSX with that footprint and assert the SVG output contains a non-generic component symbol.

---

## Problem 2 — Pin Reference Format in Connections

### What the problem is

The tscircuit `connect()` call references pins as `"ComponentRef.PinName"`. The pin name must match what the tscircuit footprint defines for that component.

The NIR `PinRef` has two fields: `pin_name` (P2 normalized, e.g. `"SPI_CLOCK"`) and `pin_number` (physical, e.g. `"1"`).

The serializer currently uses `pin_name` in connections:

```typescript
circuit.connect("U1.SPI_CLOCK", "U2.SPI_CLOCK")
```

tscircuit footprints for generic ICs define pins by number: `"pin1"`, `"pin2"`, `"pin3"`. They do not know what `"SPI_CLOCK"` is. This connection silently fails to resolve — the wire is not drawn.

For chips with named footprints (e.g. `<Resistor />` uses `"pin1"` and `"pin2"`), the pin names are fixed by the element type and do not match normalized function names either.

### Why it matters

Every signal connection in the schematic that uses a normalized function name instead of the correct pin reference will be missing from the rendered output. The schematic will look like a set of unconnected components.

### Solution

The serializer must use `pin_number` formatted as `"pin{number}"` for generic chip elements, and the correct semantic pin name for typed elements.

```python
def format_pin_ref(ref: str, pin_ref: PinRef, component_type: str) -> str:
    """
    Format a pin reference for tscircuit connect() calls.
    
    For generic chips: "U1.pin1" (use pin number)
    For resistors:     "R1.pin1" or "R1.pin2"
    For capacitors:    "C1.pos" or "C1.neg"
    For power nets:    ".VCC" or ".GND" (global net syntax)
    """
    TYPED_PIN_MAPS = {
        "resistor":  {"1": "pin1", "2": "pin2"},
        "capacitor": {"1": "pos",  "2": "neg"},
        "inductor":  {"1": "pin1", "2": "pin2"},
        "diode":     {"1": "A",    "2": "K"},     # anode, cathode
        "led":       {"1": "A",    "2": "K"},
    }

    if component_type in TYPED_PIN_MAPS:
        pin_map = TYPED_PIN_MAPS[component_type]
        pin_label = pin_map.get(pin_ref.pin_number, f"pin{pin_ref.pin_number}")
    else:
        # Generic chip: use pin number
        pin_label = f"pin{pin_ref.pin_number}"

    return f"{ref}.{pin_label}"

def format_power_net(net_name: str) -> str:
    """
    Power nets in tscircuit use global net syntax with a leading dot.
    "VCC" → ".VCC", "GND" → ".GND", "VCC_3V3" → ".VCC_3V3"
    """
    return f".{net_name}"
```

The connection generation then becomes:

```python
for net in nir.netlist:
    if net.net_type == "power":
        # Connect each component pin to the global power net symbol
        power_symbol = format_power_net(net.net_name)
        for pin in net.connections:
            component = nir.get_component(pin.ref)
            pin_label = format_pin_ref(pin.ref, pin, component.component_type)
            lines.append(f'circuit.connect("{pin_label}", "{power_symbol}")')
    else:
        # Signal nets: connect sequentially
        pins = net.connections
        component_types = {c.ref: c.component_type for c in nir.components}
        for i in range(len(pins) - 1):
            a = format_pin_ref(pins[i].ref, pins[i], component_types[pins[i].ref])
            b = format_pin_ref(pins[i+1].ref, pins[i+1], component_types[pins[i+1].ref])
            lines.append(f'circuit.connect("{a}", "{b}")')
```

---

## Problem 3 — Power Net Syntax

### What the problem is

This is related to Problem 2 but distinct enough to state separately. In tscircuit, power rails are global nets referenced with a leading dot: `.VCC`, `.GND`, `.VCC_3V3`. A connection written as:

```typescript
circuit.connect("U1.pin1", "C1.pos")  // both on VCC
```

creates a local net between U1 pin 1 and C1 positive. It does not connect them to the global VCC rail. The correct form is:

```typescript
circuit.connect("U1.pin1", ".VCC")
circuit.connect("C1.pos", ".VCC")
```

The current serializer generates pairwise connections for all nets including power nets. This means VCC and GND nets are wired as component-to-component chains rather than as global rails. The schematic will render but the power architecture will be wrong — it will look like a daisy chain rather than a star topology from a power rail.

### Solution

Detect power nets by `net.net_type == "power"` and emit global net connections instead of pairwise connections. The fix is the code shown in Problem 2's solution — the `if net.net_type == "power"` branch handles this correctly.

---

## Problem 4 — Component Element Mapping Gaps

### What the problem is

The serializer uses `TSCIRCUIT_ELEMENT_MAP` to decide which tscircuit element type to use for each component:

```python
TSCIRCUIT_ELEMENT_MAP = {
    "resistor": "resistor",
    "capacitor": "capacitor",
    "inductor": "inductor",
    "chip": "chip",
    # ...
}
```

Any component type not in this map falls back to `<chip />`. This produces a generic IC symbol in the schematic regardless of what the component actually is. A transistor rendered as a chip symbol, a crystal rendered as a chip symbol, and an SMA connector rendered as a chip symbol all look identical in the output. The schematic is technically complete but visually wrong and difficult for an engineer to read.

### Solution

Expand the map to cover all component types the BOM generator can produce:

```python
TSCIRCUIT_ELEMENT_MAP: dict[str, str] = {
    # Passives
    "resistor":             "resistor",
    "capacitor":            "capacitor",
    "inductor":             "inductor",
    "crystal":              "crystal",
    "ferrite_bead":         "inductor",     # closest available
    "fuse":                 "fuse",

    # Semiconductors
    "diode":                "diode",
    "led":                  "led",
    "zener_diode":          "diode",
    "transistor":           "transistor",
    "mosfet":               "transistor",
    "bjt":                  "transistor",

    # ICs (all map to chip)
    "op_amp":               "chip",
    "ldo_regulator":        "chip",
    "buck_converter":       "chip",
    "boost_converter":      "chip",
    "microcontroller":      "chip",
    "voltage_reference":    "chip",
    "gate_driver":          "chip",
    "comparator":           "chip",
    "adc_converter":        "chip",
    "dac_converter":        "chip",
    "usb_uart_bridge":      "chip",

    # Connectors and RF
    "connector":            "connector",
    "sma_connector":        "connector",
    "usb_connector":        "connector",
    "antenna":              "antenna",

    # Power
    "power_source":         "power_source",
    "potentiometer":        "resistor",     # closest available

    # Default
    "unknown":              "chip",
}
```

Add a validation pass before serialization that logs a warning for every component whose `component_type` is not in the map. This turns silent generic fallbacks into visible warnings.

---

## Problem 5 — Air-Gapped npm Dependency

### What the problem is

The tscircuit serializer calls the tscircuit CLI via `npx @tscircuit/cli`. In the DRDO air-gapped deployment, `npx` attempts to fetch the package from the npm registry — which is unreachable. The SVG and 3D model generation steps fail silently or throw a network error.

### Solution

The npm offline cache must be pre-populated during Docker image build time, before the image is taken into the air-gapped environment.

In the Dockerfile:

```dockerfile
# Install Node.js
RUN apt-get install -y nodejs npm

# Pre-cache tscircuit CLI and all dependencies
RUN npm install -g @tscircuit/cli
RUN npm pack @tscircuit/cli  # creates .tgz for offline installation

# Configure npm to use offline mode in production
ENV NPM_CONFIG_OFFLINE=true
```

The `ENV NPM_CONFIG_OFFLINE=true` line prevents npm from attempting any network calls when the container runs in the air-gapped environment. If a package is not in the cache, npm fails immediately with a clear error rather than hanging on a timeout.

Also mirror the tscircuit footprint registry locally:

```bash
# At build time (internet-connected environment)
git clone https://github.com/tscircuit/footprints /app/footprint-registry

# In configs/default.yaml
tscircuit_registry_url: "file:///app/footprint-registry"
```

---

## Validation Gate — What Needs to Run Before Team E is Complete

All five problems above are resolved by a single end-to-end validation run. Run it once on a real design before declaring the serializer production-ready.

```bash
# 1. Parse a real golden corpus datasheet
python -m src.datasheet.pipeline parse \
    --component-id TPS62933DRLR \
    --pdf corpus/golden/TPS62933.pdf

# 2. Run the full pipeline on a simple prompt
python -m src.pipeline \
    --prompt "3.3V LDO regulator with input and output decoupling capacitors" \
    --output eval/tscircuit_validation/

# 3. Run tscircuit CLI on the generated TSX
npx @tscircuit/cli export \
    --format svg \
    --output eval/tscircuit_validation/schematic.svg \
    eval/tscircuit_validation/*.tsx

# 4. Inspect the SVG manually:
#    - Do all components appear with correct symbols (not generic boxes)?
#    - Are all connections drawn?
#    - Are power rails shown as global nets (not component-to-component wires)?
#    - Are footprint names resolved (visible in component label)?

# 5. Run the 3D model export
npx @tscircuit/cli export \
    --format 3d \
    --output eval/tscircuit_validation/pcb_3d.glb \
    eval/tscircuit_validation/*.tsx

# 6. Open the GLB in any 3D viewer and verify components have correct shapes
```

If all five checks pass visually, all five problems are resolved. If any fail, the specific failure identifies which fix to apply.

---

## Summary

| Problem | Type | Severity | Fix complexity |
|---------|------|----------|---------------|
| 1 — Footprint name resolution | Integration mismatch | HIGH — wrong footprints break layout | One-time mapping table |
| 2 — Pin reference format | Logic error | CRITICAL — connections not drawn | Fix format_pin_ref() |
| 3 — Power net syntax | Logic error | HIGH — wrong power architecture | net_type branch in connect loop |
| 4 — Component element mapping gaps | Coverage gap | MEDIUM — wrong schematic symbols | Expand TSCIRCUIT_ELEMENT_MAP |
| 5 — Air-gapped npm dependency | Deployment gap | CRITICAL for DRDO | Dockerfile npm cache |

Problems 2 and 3 are code logic errors that will cause incorrect output regardless of footprint naming. Fix those first. Problems 1, 4, and 5 are integration and deployment issues — important but do not affect the logical correctness of the circuit representation.