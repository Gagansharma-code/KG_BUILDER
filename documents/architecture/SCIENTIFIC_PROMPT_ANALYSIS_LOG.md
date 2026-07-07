# OpenForge — Scientific Prompt Analysis Log

**Purpose:** Every time a scientist or engineer submits a design prompt, this document records what the system can handle, what it cannot, and what needs to be built. This is a living document. Append a new entry every time a new prompt is received and analysed.

**Maintained by:** TPM / Lead Architect
**Update rule:** Add a new entry at the bottom. Never edit past entries. Mark gaps as RESOLVED when the corresponding capability is built and gated.

---

## How to Read This Document

Each entry has four sections:

- **PROMPT** — the exact prompt as received
- **CAN HANDLE** — what the current system processes correctly end-to-end
- **GAPS** — specific missing capabilities, each tagged as one of:
  - `[DATA GAP]` — the pipeline exists but the required data is not ingested
  - `[OUTPUT GAP]` — the NIR is correct but no serializer produces this format
  - `[ANALYSIS GAP]` — requires computation or simulation not in the pipeline
  - `[SCOPE GAP]` — outside PCB design entirely (software, firmware, mechanical)
  - `[COMPONENT GAP]` — specific part not in KG-3 or golden corpus
  - `[TOPOLOGY GAP]` — circuit topology not in KG-2 design recipes
- **BUILD REQUIREMENTS** — what needs to be designed and built to close each gap

---

## Entry 001 — Libbrecht-Hall Precision Current Source

**Date received:** 2026-06-19
**Received from:** DRDO Scientist
**Status:** PARTIALLY PROCESSABLE — data and analysis gaps block full execution

### PROMPT

> Design a ultra low noise and highly stable current source for 100mA current range using libbrecht hall design. Use ultra precision resistors. Include the power supply for all components and generate all required voltage and polarities. And use zero drift opamps. The circuit should work from single dc input. Include the required ldos. It should have capability to adjust the current using a potentiometer. Provide me list of components. Estimate the current noise.

---

### CAN HANDLE

| Capability | Status | Notes |
|-----------|--------|-------|
| Intent parsing | ✅ | `goal=current_source`, `methodology=mixed_signal` |
| Single DC input constraint extraction | ✅ | Extracted as explicit constraint |
| LDO requirement extraction | ✅ | Mapped to `power_management` sub-requirement |
| Potentiometer / adjustable current extraction | ✅ | Extracted as explicit constraint |
| LDO datasheet parsing | ✅ | If LDO part is in KG-3 |
| LDO selection and BOM entry | ✅ | If LDO design recipes in KG-2 |
| Schematic synthesis for LDO + power section | ✅ | Standard power topology |
| PCB layout spec generation | ✅ | Mixed-signal board spec selected |
| NIR generation | ✅ | Full pipeline runs to completion |
| KiCad output | ✅ | Serializer produces valid files |
| tscircuit output + 3D model | ✅ | Serializer produces valid files |

---

### GAPS

#### GAP-001-A `[TOPOLOGY GAP]`
**The Libbrecht-Hall current source topology is not in KG-2.**

The Libbrecht-Hall design (from Libbrecht & Hall, Rev. Sci. Instrum. 64, 2133, 1993) is a specific feedback-stabilized current source architecture used in atomic physics and precision measurement. It is not covered by any TI or ADI application note currently ingested. The query engine traverses the graph for `current_source` and finds no design recipe with the required feedback topology, sense resistor configuration, or op-amp selection criteria. The BOM generator returns empty with `review_required=True`.

**Impact:** System cannot generate a correct BOM or schematic without this topology in KG-2.

**Sources needed for ingestion:**
- Libbrecht & Hall 1993 paper (Rev. Sci. Instrum. 64, 2133)
- TI application note SBOA327 — Precision Current Source Design
- TI application note SBOA273 — Low-Noise Current Source Techniques
- ADI application note AN-1357 — Precision Current Sources and Sinks

---

#### GAP-001-B `[COMPONENT GAP]`
**Zero-drift op-amps are not in KG-3.**

The prompt specifically requires zero-drift op-amps. Candidate parts include OPA189 (TI), ADA4522-2 (ADI), AD8628 (ADI), OPA2188 (TI). None of these datasheets have been ingested through P1. The BOM generator cannot suggest a specific part — it can only output `component_type=zero_drift_op_amp` with `specific_part=None`, triggering a human review gate.

**Impact:** BOM will not contain specific op-amp part numbers. Engineer must manually select.

**Datasheets needed:**
- OPA189 (TI) — 0.1µV/°C max drift, rail-to-rail
- ADA4522-2 (ADI) — 2.5µV max offset, zero-drift
- AD8628 (ADI) — chopper-stabilized, single supply
- OPA2188 (TI) — dual, 0.03µV/°C drift

---

#### GAP-001-C `[COMPONENT GAP]`
**Ultra-precision resistors are not in KG-3.**

The prompt requires ultra-precision resistors for the sense element. Candidate parts include Vishay VSR series, Susumu RG series, and Caddock MP series. None are in the component database. The system will output `component_type=precision_resistor` with `specific_part=None`.

**Impact:** BOM will not contain specific resistor part numbers.

**Datasheets needed:**
- Vishay VSR 0.01% tolerance series
- Susumu RG2012N-xxx precision chip resistors
- Caddock MP915 precision power resistors

---

#### GAP-001-D `[ANALYSIS GAP]`
**Current noise estimation is not in the pipeline.**

The prompt asks to "estimate the current noise." This requires:
1. Johnson noise calculation: `V_noise = sqrt(4kTRΔf)` from resistor values
2. Op-amp input voltage noise density from datasheet (nV/√Hz) integrated over bandwidth
3. Op-amp input current noise density (pA/√Hz) integrated over bandwidth
4. Total output current noise calculation combining all sources
5. Spectral noise density plot (1/f corner + flat band)

None of this computation exists in the current pipeline. The NIR has no simulation or analysis layer. The DocumentationGenerator produces a design report but has no noise analysis section.

**Impact:** System cannot produce a noise estimate. This output is completely missing.

**What needs to be built:**
- `src/analysis/noise_estimator.py` — takes a `NIR` + list of `ComponentDatasheet` objects, reads electrical parameters (voltage noise density, current noise density, resistor values), applies noise analysis formulas, returns a `NoiseAnalysisResult` object
- `NoiseAnalysisResult` schema: total_current_noise_pA_rtHz, spectral_breakdown_by_source, dominant_noise_source, estimated_1f_corner_hz
- Documentation generator must be extended to include noise analysis section when `NoiseAnalysisResult` is present

---

#### GAP-001-E `[COMPONENT GAP]`
**Potentiometer for current adjustment not in KG-3.**

A wirewound or cermet potentiometer appropriate for precision current adjustment (e.g. Bourns 3590S, Vishay P11 series) is not in the component database. The system knows what a potentiometer is conceptually (KG-1 physics layer) but cannot recommend a specific part.

**Impact:** BOM entry for potentiometer will have `specific_part=None`.

---

### BUILD REQUIREMENTS FOR ENTRY 001

| ID | What to Build | Type | Priority |
|----|--------------|------|---------|
| BR-001-1 | Ingest Libbrecht-Hall paper + 3 precision current source app notes into KG-2 | Data ingestion run | HIGH — blocks full execution |
| BR-001-2 | Ingest 4 zero-drift op-amp datasheets through P1 into KG-3 | Data ingestion run | HIGH — blocks specific part selection |
| BR-001-3 | Ingest precision resistor datasheets through P1 into KG-3 | Data ingestion run | MEDIUM |
| BR-001-4 | Ingest precision potentiometer datasheets through P1 into KG-3 | Data ingestion run | LOW |
| BR-001-5 | Build `src/analysis/noise_estimator.py` module | New module | HIGH — prompt explicitly requests this |
| BR-001-6 | Add `NoiseAnalysisResult` to `src/schemas/` | New schema | Prerequisite for BR-001-5 |
| BR-001-7 | Extend DocumentationGenerator to include noise analysis section | Module extension | Depends on BR-001-5 |

---

---

## Entry 002 — Adjustable Current Source with VCO Bias Tee and USB-C Interface

**Date received:** 2026-06-19
**Received from:** DRDO Scientist
**Status:** PARTIALLY PROCESSABLE — multiple gaps, two are out of PCB scope

### PROMPT

> Design a SPICE schematic file for a adjustable current source with a combined interface to PC, power regulator and output SMA connector. I also need a bias tee where I can add the DC current and RF signal generated from the ZCOM 4596 VCO. I should be able to sweep the tune voltage pin to vary the frequency. The board should have micro connectors and a USB Type-C connector for connecting to PC. A Python GUI would be needed to control the circuit.

---

### CAN HANDLE

| Capability | Status | Notes |
|-----------|--------|-------|
| Intent parsing | ✅ | `goal=current_source`, `methodology=RF_highfreq` |
| RF methodology classification | ✅ | Correct — RF_highfreq activated by VCO/RF context |
| SMA connector selection and placement | ✅ | Standard component, in KiCad/tscircuit libraries |
| Power regulator section | ✅ | LDO selection works if parts are in KG-3 |
| NIR generation for processable subsections | ✅ | Partial NIR possible for power + connector sections |
| KiCad output for partial design | ✅ | Whatever the NIR contains gets serialized |
| tscircuit output + 3D model | ✅ | Same |
| USB-C connector footprint placement | ✅ | Footprint exists in libraries — placement works |
| Micro connector placement | ✅ | Standard footprints available |

---

### GAPS

#### GAP-002-A `[OUTPUT GAP]`
**SPICE netlist output format is not implemented.**

The prompt explicitly requests a SPICE schematic file (`.net` or `.cir` format). The current Team E output layer produces KiCad files and tscircuit files only. The NIR contains everything a SPICE netlist requires — component references, values, net connections, and component types. The serializer does not exist yet.

**Impact:** The system cannot produce the requested output format. KiCad and tscircuit files would be produced instead.

**What needs to be built:**
- `src/output/spice_serializer.py` — converts `NIR.netlist` and `NIR.components` to SPICE `.net` format
- `SpiceOutput` result schema: `net_path`, `validation_result`
- Add `check_version(nir)` call at start (same pattern as KiCad and tscircuit serializers)
- Add to Team E pipeline as a third output option

---

#### GAP-002-B `[COMPONENT GAP]`
**ZCOM 4596 VCO is not in KG-3.**

The ZCOM 4596 is a specific voltage-controlled oscillator from Z-Communications Inc. Its datasheet is not in the corpus. The P1 parser has never processed it. KG-3 has no entry for it. The system cannot generate pinout connections, tuning voltage range constraints, or RF output impedance requirements without this component's data.

**Impact:** The VCO cannot appear in the BOM with a specific part number or correct pinout. The bias tee connection to the VCO RF output cannot be synthesized.

**Datasheets needed:**
- ZCOM 4596 datasheet from Z-Communications
- Key parameters to extract: VTune range, Vtune sensitivity (MHz/V), RF output power, supply voltage, pinout, package

---

#### GAP-002-C `[TOPOLOGY GAP]`
**Bias tee circuit topology is not in KG-2.**

A bias tee combines a DC current path and an RF signal path using a series inductor (DC path, RF block) and a series capacitor (RF path, DC block). This is a standard RF component but the specific design recipe — inductor and capacitor selection criteria for a given frequency range, impedance matching to 50Ω, and connection to the VCO output — is not in KG-2. The schematic synthesizer has no rule that knows how to connect the bias tee elements.

**Impact:** The bias tee section cannot be synthesized. The system does not know what to place or how to connect it.

**Sources needed for ingestion:**
- Mini-Circuits application note on bias tee design
- ADI application note on RF bias tee circuit design
- Any TI RF design guide covering bias tee topologies at the relevant frequency range

---

#### GAP-002-D `[TOPOLOGY GAP]`
**USB-UART bridge design recipe is not in KG-2.**

USB-C connectivity to a PC requires a USB-UART or USB-serial bridge IC (candidates: CP2102N, CH340C, FT232RL). The design recipe for this — bridge IC selection, crystal or oscillator requirement, decoupling, USB termination resistors, D+/D- routing rules — is not in KG-2. The system can place a USB-C connector footprint but cannot synthesize the full USB communication subsystem.

**Impact:** USB-C section will be incomplete. BOM will have `component_type=usb_uart_bridge` with `specific_part=None`. USB-C connector placed but not correctly connected.

**Sources needed for ingestion:**
- TI CP2102N datasheet + application note
- WCH CH340C datasheet + application note
- FTDI FT232RL datasheet + application note
- USB 2.0 full-speed PCB layout guidelines (impedance controlled D+/D- traces)

---

#### GAP-002-E `[TOPOLOGY GAP]`
**VTune sweep circuit is not in KG-2.**

The prompt requires sweeping the VCO tuning voltage pin to vary the frequency. This requires either a DAC (digital-to-analog converter) controlled via USB, or a voltage ramp generator. The design recipe for a DAC-to-VTune interface — DAC selection, output filtering, voltage range matching to VCO VTune spec, and digital control interface — is not in KG-2. The intent parser extracts `tune_voltage_controllable=true` as a constraint but the BOM generator cannot resolve it to specific components without a design recipe.

**Impact:** No DAC or tuning circuit appears in the BOM. VTune pin is left unconnected in the schematic.

**Sources needed:**
- TI DAC8562 or similar precision DAC application note
- VCO tuning interface design recipes

---

#### GAP-002-F `[SCOPE GAP]`
**Python GUI is outside PCB design scope.**

The request for a Python GUI to control the circuit is a software deliverable, not a PCB design deliverable. OpenForge produces PCB files — schematics, layouts, Gerbers, BOMs. It does not generate software, firmware, or GUI applications. The intent parser should detect this requirement and flag it explicitly as out-of-scope in the `AmbiguityFlag` list with a message that the GUI must be developed separately.

**Impact:** No Python GUI will be produced. This is not a system gap — it is a scope boundary. The engineer must implement the GUI independently using the USB-C interface that OpenForge designs.

**What needs to be built:**
- Intent parser keyword detection for software-related requirements:
  `["python", "gui", "software", "firmware", "app", "application", "code", "script"]`
- When detected: add `AmbiguityFlag(field="software_requirement", severity="WARNING", description="Python GUI and software development is outside OpenForge scope. PCB design files will be produced. GUI must be implemented separately.")`

---

#### GAP-002-G `[SCOPE GAP]`
**SPICE simulation and schematic validation is outside current scope.**

The prompt implies the SPICE file should be simulatable — implying correct SPICE model assignments for every component. Assigning SPICE models (`.model` statements, subcircuit `.lib` files) to real component part numbers requires a SPICE model database that does not exist in OpenForge. Producing a syntactically valid SPICE netlist (GAP-002-A) is achievable. Producing a simulatable SPICE netlist with correct models is a larger capability gap.

**Impact:** Even with the SPICE serializer built, the output will be a structural netlist, not a simulation-ready file.

**What needs to be built (future):**
- SPICE model database: maps `component_id` → SPICE model file or subcircuit
- SPICE model fetcher: downloads models from manufacturer sites at corpus build time
- SPICE serializer extension: injects `.model` and `.lib` references into output

---

### BUILD REQUIREMENTS FOR ENTRY 002

| ID | What to Build | Type | Priority |
|----|--------------|------|---------|
| BR-002-1 | Build `src/output/spice_serializer.py` — NIR → SPICE netlist | New Team E serializer | HIGH — explicit in prompt |
| BR-002-2 | Ingest ZCOM 4596 datasheet through P1 into KG-3 | Data ingestion run | HIGH — blocks VCO section |
| BR-002-3 | Ingest bias tee design app notes into KG-2 | Data ingestion run | HIGH — blocks bias tee synthesis |
| BR-002-4 | Ingest USB-UART bridge datasheets + app notes into KG-2 and KG-3 | Data ingestion run | HIGH — blocks USB section |
| BR-002-5 | Ingest DAC + VTune interface app notes into KG-2 | Data ingestion run | MEDIUM — blocks sweep circuit |
| BR-002-6 | Add software requirement detection to intent parser | Intent parser extension | LOW — quality of life flag |
| BR-002-7 | SPICE model database + simulatable SPICE output | Future capability | LOW — deferred |

---

---

## Entry 003 — Stage 2 Smoke Test Validation (Entry 001 / Prompt 1)

**Date:** 2026-06-21
**Type:** Engine validation (not a new scientist prompt)
**References:** Entry 001 — Libbrecht-Hall Precision Current Source
**Status:** STAGE 2 VERIFIED — dangerous-assumption escalation behaves correctly for Prompt 1

### CONTEXT

The Stage 2 Requirement Completion Engine (`src/completion/engine.py`) was smoke-tested end-to-end against the Entry 001 Libbrecht-Hall prompt using a manually constructed `ImprovedIntentDict` and a mocked LLM response (no live API calls). Test harness: `tests/completion/smoke_test_real_prompts.py`.

### STAGE 2 BEHAVIOUR VERIFIED (PROMPT 1)

| Check | Result | Notes |
|-------|--------|-------|
| Axiom loading | ✅ | `load_axioms_for_intent` returned ≥5 axioms from `data/domain_knowledge/libbrecht_hall.yaml` with preconditions evaluated against the intent |
| Dangerous assumption → `operating_environment` | ✅ | Promoted to blocking `Ambiguity` (`blocking=True`, severity `ERROR`) |
| Dangerous assumption → `supply_voltage` | ✅ | Promoted to blocking `Ambiguity` (`blocking=True`, severity `ERROR`) |
| `clarification_required` | ✅ | Set to `True` when blocking ambiguities present |
| Inferred constraints threshold | ✅ | Only requirements with confidence ≥ 0.80 appear in `inferred_constraints` |
| Rule checker — negative rail | ✅ | No spurious contradiction when `negative_rail_converter` is already implied |
| Rule checker — bypass cap | ✅ | WARNING fired when `low_noise_ldo` implied without bypass/decoupling requirement |

**Smoke test verdict:** 12/12 assertions passed (9 for Prompt 1, 3 for Prompt 2 multi-topology / threshold cases).

### IMPLICATION FOR ENTRY 001

Entry 001 gaps (KG-2 topology, KG-3 components, noise analysis) remain **OPEN**. Stage 2 does not close those gaps. What it does provide: the system will **not silently assume** `operating_environment=laboratory` or `supply_voltage=15V–24V` for this prompt class. The pipeline must halt and request engineer confirmation before proceeding to BOM generation or synthesis.

---

## Gap Registry — Consolidated View

All open gaps across all entries. Update STATUS when resolved.

| Gap ID | Type | Description | Entry | Status | Blocked By |
|--------|------|-------------|-------|--------|-----------|
| GAP-001-A | TOPOLOGY | Libbrecht-Hall topology not in KG-2 | 001 | OPEN | BR-001-1 |
| GAP-001-B | COMPONENT | Zero-drift op-amps not in KG-3 | 001 | OPEN | BR-001-2 |
| GAP-001-C | COMPONENT | Ultra-precision resistors not in KG-3 | 001 | OPEN | BR-001-3 |
| GAP-001-D | ANALYSIS | Current noise estimation not in pipeline | 001 | OPEN | BR-001-5, BR-001-6 |
| GAP-001-E | COMPONENT | Precision potentiometer not in KG-3 | 001 | OPEN | BR-001-4 |
| GAP-002-A | OUTPUT | SPICE serializer not built | 002 | OPEN | BR-002-1 |
| GAP-002-B | COMPONENT | ZCOM 4596 VCO not in KG-3 | 002 | OPEN | BR-002-2 |
| GAP-002-C | TOPOLOGY | Bias tee topology not in KG-2 | 002 | OPEN | BR-002-3 |
| GAP-002-D | TOPOLOGY | USB-UART bridge recipe not in KG-2 | 002 | OPEN | BR-002-4 |
| GAP-002-E | TOPOLOGY | VTune sweep circuit not in KG-2 | 002 | OPEN | BR-002-5 |
| GAP-002-F | SCOPE | Python GUI is software, not PCB | 002 | SCOPE BOUNDARY | — |
| GAP-002-G | SCOPE | Simulatable SPICE models not in system | 002 | OPEN (DEFERRED) | BR-002-7 |
| GAP-004-A | WIRING | Typed v2 constraint categories never populated in production | 004 | RESOLVED 2026-07-07 (wiring only — see note after Entry 004; other Entry 004 gaps for these 10 prompts remain OPEN) | BR-004-1 |
| GAP-004-B | TOPOLOGY | 9+ named topologies absent (in-amp, Howland, TIA, lock-in, TEC, LNA, filters, PLL…) | 004 | OPEN | BR-004-3 |
| GAP-004-C | TOPOLOGY | `rc_lowpass` trigger misclassifies active-filter prompts | 004 | OPEN | BR-004-11 |
| GAP-004-D | TOPOLOGY | Battery→rails power delivery not a reusable topology | 004 | OPEN | BR-004-6 |
| GAP-004-E | ANALYSIS | No estimation layer for any requested metric (generalizes GAP-001-D) | 004 | OPEN | BR-004-2 |
| GAP-004-F | SCHEMA | No graph representation for predicted output metrics | 004 | RESOLVED 2026-07-07 (representation only — see note after Entry 004) | BR-004-14 |
| GAP-004-G | SCHEMA | Protection/safety behaviors silently dropped; `kelvin_sensing_required` dead | 004 | RESOLVED 2026-07-07 | BR-004-18 |
| GAP-004-H | SCHEMA | No frequency ranges / condition-scoped constraints beyond unpopulated NoiseSpec | 004 | RESOLVED 2026-07-07 (schema + KG/solver wiring — see note after Entry 004) | BR-004-16 |
| GAP-004-I | SCHEMA | Comparative topology selection stores no rationale | 004 | OPEN | BR-004-9 |
| GAP-004-J | SCHEMA | DESIGN_CONSTRAINT one-node-per-kind id collision (multi-rail) | 004 | RESOLVED 2026-07-07 | BR-004-7 |
| GAP-004-K | WIRING | Topology install not wired; goal_mapper can't start from TOPOLOGY | 004 | OPEN | BR-004-4 |
| GAP-004-L | COMPONENT | Component families for all 10 prompts absent (low-IQ LDOs highest leverage) | 004 | OPEN | BR-004-12 |
| GAP-004-M | DATA | Guard-ring / RF-matching layout rules not ingested | 004 | OPEN | BR-004-13 |
| GAP-004-N | SCHEMA | Composite instruments collapse to a single goal string (no sub-block decomposition) | 004 | OPEN | BR-004-8 |

---

## Build Requirements — Consolidated Backlog

Ordered by cross-entry priority. Items marked SHARED benefit multiple entries.

| ID | Description | Type | Entries | Priority | Status |
|----|-------------|------|---------|---------|--------|
| BR-001-5 | Noise estimator module | New module | 001 | HIGH | OPEN |
| BR-001-6 | NoiseAnalysisResult schema | New schema | 001 | HIGH | OPEN |
| BR-002-1 | SPICE serializer | New serializer | 002 | HIGH | OPEN |
| BR-001-1 | Libbrecht-Hall + current source app notes ingestion | Data | 001 | HIGH | OPEN |
| BR-001-2 | Zero-drift op-amp datasheets ingestion | Data | 001 | HIGH | OPEN |
| BR-002-2 | ZCOM 4596 datasheet ingestion | Data | 002 | HIGH | OPEN |
| BR-002-3 | Bias tee app notes ingestion | Data | 002 | HIGH | OPEN |
| BR-002-4 | USB-UART bridge datasheets + app notes ingestion | Data | 001, 002 | HIGH | OPEN |
| BR-001-7 | Documentation generator noise section | Extension | 001 | MEDIUM | OPEN |
| BR-002-5 | DAC + VTune interface app notes ingestion | Data | 002 | MEDIUM | OPEN |
| BR-001-3 | Precision resistor datasheets ingestion | Data | 001 | MEDIUM | OPEN |
| BR-001-4 | Precision potentiometer datasheets ingestion | Data | 001 | LOW | OPEN |
| BR-002-6 | Software requirement detection in intent parser | Extension | 002 | LOW | OPEN |
| BR-002-7 | SPICE model database + simulatable output | Future | 002 | DEFERRED | OPEN |
| BR-004-1 | Typed v2 constraint population in production (Stage 1/2) | Pipeline wiring | 004 | HIGH | CLOSED 2026-07-07 |
| BR-004-2 | Estimation layer: per-metric estimator modules (computation) — representation split to BR-004-14 | Module | 001, 004 | HIGH | OPEN |
| BR-004-3 | Ingest 9 named topologies from Entry 004 sweep | Data | 004 | HIGH | OPEN |
| BR-004-4 | Wire install_topologies + TOPOLOGY in goal_mapper start types | Pipeline wiring | 004 | HIGH | CLOSED |
| BR-004-5 | Structured protection/safety requirements | Schema + wiring | 004 | HIGH | CLOSED 2026-07-07 (superseded by BR-004-18 §4) |
| BR-004-6 | Reusable battery power-delivery topology | Data | 004 | MEDIUM-HIGH | OPEN |
| BR-004-7 | Constraint-node granularity fix (per-constraint, block-scoped) | Schema | 004 | MEDIUM-HIGH | CLOSED 2026-07-07 |
| BR-004-8 | Sub-block decomposition on intent | Schema + parser | 004 | MEDIUM-HIGH | OPEN |
| BR-004-9 | Comparative-selection rationale record | Schema | 004 | MEDIUM | OPEN |
| BR-004-10 | FrequencySpec ranges + condition scoping on specs | Schema | 004 | MEDIUM | CLOSED 2026-07-07 (superseded by BR-004-16 §3) |
| BR-004-11 | Classifier vocabulary expansion + rc_lowpass fix | Extension | 004 | MEDIUM | OPEN |
| BR-004-12 | Component families ingestion (low-IQ LDOs first) | Data | 004 | MEDIUM | OPEN |
| BR-004-13 | Guard-ring / RF layout rules ingestion | Data | 004 | LOW | OPEN |
| BR-004-14 | PREDICTED_METRIC + DERIVED_FROM graph representation (schema review §2, representation only) | Schema | 001, 004 | HIGH | CLOSED 2026-07-07 |
| BR-004-15 | PREDICTED_METRIC id includes method (cross-method coexistence) | Schema | 004 | MEDIUM | CLOSED 2026-07-07 |
| BR-004-16 | ConditionScope + FrequencySpec range + scalar promotion + solver guard (schema review §3) | Schema | 004 | MEDIUM | CLOSED 2026-07-07 |
| BR-004-17 | §3 follow-ups: FrequencySpec point/range exclusivity + PREDICTED_METRIC ConditionScope swap | Schema | 004 | LOW | CLOSED 2026-07-07 |
| BR-004-18 | protection_requirements schema + KG wiring + LLM population (schema review §4) | Schema + wiring | 004 | HIGH | CLOSED 2026-07-07 |
| BR-004-19 | Wire protection safety net into real `run_intent_pipeline` path | Pipeline wiring | 004 | HIGH | CLOSED 2026-07-07 |
| BR-004-20 | Decouple rule checker from Stage 2 success; flag incomplete runs | Pipeline wiring | 004 | HIGH | CLOSED 2026-07-07 |

---

*Append new entries below this line. Format: Entry NNN — [Title]*

---

## Entry 004 — Ten-Prompt Competency Sweep: Precision Instrumentation & RF Battery-Powered Designs

**Date received:** 2026-07-07
**Received from:** Project lead (batch gap-analysis task; the task named this "Entry 003 Gap Analysis," but Entry 003 was already assigned to the 2026-06-21 Stage 2 smoke test — per this document's own "never edit past entries" rule, this analysis is logged as Entry 004)
**Type:** Competency-question gap analysis (10 prompts analysed together; no pipeline execution — every verdict below is grounded in the current code, cited by file, not in architecture-doc claims)
**Status:** ANALYSIS ONLY — all 10 prompts are currently NOT PROCESSABLE end-to-end; every prompt hits at least one HIGH-priority gap

### PROMPTS (as received, condensed to their operative asks; full text in the originating task)

1. **Ultra-low-power instrumentation amplifier** for bridge sensors: <250 µA total, offset <5 µV, noise <50 nV/√Hz **at 1 kHz**, zero-drift/micropower CMOS amps, single Li-ion (3.0–4.2 V) with ultra-low-IQ regulators, programmable gain 10–1000, EMI protection, input filtering, BOM; estimate battery life, CMRR, offset drift, noise.
2. **Precision constant-current source** 1 µA–100 mA, **improved Howland pump or Libbrecht-Hall** by range, single 3.7 V Li-ion + ultra-low-IQ regulators, coarse/fine multiturn pots, **reverse-current protection, Kelvin sensing**; estimate output impedance, current noise, efficiency.
3. **Ultra-low-power precision voltage reference**, selectable 2.5/5/10 V, <500 µW, buried-zener or bandgap, zero-drift buffer, ultra-low-TCR resistor networks, low-IQ LDOs, trimming, **reverse-polarity protection**; estimate temp drift, output noise, long-term stability.
4. **Low-power transimpedance amplifier**, selectable 100 kΩ–100 MΩ, <1 mA, **compare JFET-input vs CMOS-input**, single 5 V with internal bias generation, reverse-bias generation, **guard-ring recommendations**, switchable gain; estimate bandwidth, NEP, input-referred noise.
5. **Battery-operated lock-in amplifier**: synchronous demodulation (analog switches or precision multipliers), single Li-ion, <500 mW, programmable LPF, gain control, reference generation, ultra-low-noise regulators; estimate dynamic reserve, bandwidth, noise floor.
6. **Libbrecht-Hall-inspired laser diode driver**: 0–80 mA adjustable, current noise <20 nA RMS, single-cell Li-ion + low-IQ LDOs, **soft-start, reverse-current protection, thermal shutdown**, fine adjustment; estimate efficiency, battery runtime, current stability.
7. **Ultra-low-power TEC temperature controller**, ±500 mA, **compare H-bridge linear vs hybrid linear-switching**, thermistor sensing via ultra-low-power in-amp, low-IQ regulators; estimate temperature stability, power dissipation, battery runtime.
8. **2.4 GHz LNA**, <8 mA, **compare common-source GaAs vs SiGe HBT vs CMOS cascode**, impedance matching, bias stabilization, **ESD protection**; estimate gain, noise figure, power consumption.
9. **Fourth-order Butterworth active low-pass filter**, cutoff selectable 10 Hz–100 kHz, **compare MFB vs Sallen-Key vs State-Variable**, minimum power, BOM; estimate passband ripple, THD, power dissipation.
10. **Battery-powered PLL frequency synthesizer** 10–500 MHz, ultra-low-phase-noise VCO, **compare integer-N vs fractional-N**, single Li-ion + low-IQ regulators; estimate lock time, phase noise, power consumption.

### METHOD NOTE — code, not docs

Every claim below was verified against `src/` at commit time. Two verified findings shape everything else and are stated up front:

1. **The typed v2 constraint categories are never populated in production.** `ParsedIntent` (`src/intent/parser.py:53-72`) has *no* `electrical`/`thermal`/`performance` fields; the LLM parse path is a placeholder that always returns `None` (`parser.py:224-226` — "For now, return None to trigger rule-based fallback"); the rule-based parser emits only strings from a fixed 14-keyword list (`parser.py:312-317`); and the Stage 2 completion engine writes only `implied_requirements`/`inferred_constraints`/ambiguity fields (`src/completion/engine.py:153-158`). A repo-wide search finds **zero** production constructors of `ElectricalConstraints(`, `ThermalConstraints(`, or `PerformanceRequirements(` — only tests. The one "end-to-end" proof (`tests/unit/intent/test_topology_pipeline_integration.py`) injects `electrical` via a *mocked* Stage 2 `model_copy`, and says so in its own docstring.
2. **Consequence:** the interval solver (`src/intent/interval_solver.py:101-106` — returns immediately when `intent.electrical is None`) and the constraint persister (`src/knowledge_graph/constraints/__init__.py:104-132` — skips every `None` category) both silently no-op on any real parsed prompt today. "Wired into the pipeline" (`src/intent/pipeline.py:116`) is literally true and practically vacuous.

**New tag introduced:** `[WIRING GAP]` — schema and consumer both exist, but the production path that connects them does not. This is distinct from `[DATA GAP]` (pipeline exists, rows missing) and `[SCHEMA GAP]` (field/node type missing). Justified by finding 1 above, which none of the existing six tags describes.

### CAN HANDLE

| Capability | Status | Notes |
|-----------|--------|-------|
| Goal/methodology extraction (all 10) | ✅ partial | Rule-based parse produces a goal string and methodology; RF_highfreq will trigger for P8/P10 via frequency keywords |
| Topology classification for P2/P6 core | ✅ partial | "current source" trigger exists (`topology_classifier.py:128-131`) — but resolves to a slug with no KG node behind it (see GAP-004-K) |
| Numeric frequency extraction (single value) | ✅ | `FrequencySpec` captures "2.4 GHz" (P8); cannot capture ranges (see GAP-004-H) |
| "Low power / compact / portable" string constraints | ✅ | In the rule-based keyword list; land in `inferred_constraints`/strings |
| Out-of-scope detection & review gates | ✅ | Blocking-ambiguity machinery is real and tested (Entry 003 smoke test) |
| BOM/report/KiCad/tscircuit output plumbing | ✅ | Structural — will produce mostly-empty BOMs with `review_required=True` given the gaps below |
| Battery-life, noise, CMRR, THD, phase-noise… estimation | ❌ | See GAP-004-E — nothing to run |
| Any typed numeric constraint (µV, nA/√Hz, mW budgets) | ❌ | See GAP-004-A — silently reduced to strings or dropped |

### GAPS

#### GAP-004-A `[WIRING GAP]` — Typed constraint categories unreachable in production. **Blocks 10/10 prompts.**
Every prompt carries hard numerics ("<250 µA total", "offset below 5 µV", "<500 mW", "current noise below 20 nA RMS"). The v2 schema has homes for many of these (`PerformanceRequirements.noise/accuracy`, `ElectricalConstraints.supply_current_budget/power_budget_mw` — `src/schemas/intent.py:95-131`), but per Method Note finding 1, nothing populates them. Today these asks survive only inside `raw_prompt`. Downstream, `_typed_constraints_as_strings` (`parser.py:143-171`) `getattr`s fields `ParsedIntent` has never had — dead code masked by `getattr(…, None)` defaults.
**What a working path looks like:** Stage 2 (or the real Instructor parse) returning `intent.model_copy(update={"electrical": ElectricalConstraints(supply_voltage=VoltageSpec(min_v=3.0, max_v=4.2, raw_text="single Li-ion 3.0–4.2V"), …)})` — exactly what the integration test fakes.
Not a re-report: no prior entry covers this; Entry 003 verified Stage 2's *ambiguity* behavior, not typed-field population.

#### GAP-004-B `[TOPOLOGY GAP]` — Nine-plus named topologies absent from both classifier and KG. **Blocks 10/10.**
`TOPOLOGY_TRIGGERS` (`src/intent/topology_classifier.py:84-132`) knows exactly 8 slugs (ldo, buck_converter, boost_converter, buck_boost, inverting_amplifier, voltage_divider, rc_lowpass, current_source). The KG topology library (`src/knowledge_graph/topology/library.py:40`) installs exactly **2** (`ldo`, `buck_converter`). Missing, per prompt: instrumentation amplifier (P1, P7), Howland current pump (P2), voltage reference module (P3), transimpedance amplifier (P4), lock-in / synchronous demodulator (P5), laser diode driver (P6), TEC driver — H-bridge and hybrid variants (P7), RF LNA cascode (P8), MFB / Sallen-Key / State-Variable active filters (P9), PLL synthesizer + loop filter + VCO interface (P10). Libbrecht-Hall (P2, P6) **confirms GAP-001-A** (still OPEN); the VCO/PLL interface asks **confirm GAP-002-B/GAP-002-E** territory.
**What it would look like:** `graph.get_node("topology:howland_current_pump")` returning a `TOPOLOGY` node with `FUNCTIONAL_BLOCK` PART_OF children carrying `ScalingLaw`s (e.g. `ScalingLaw(parameter="output_current_a", affects="sense_resistor_dissipation_w", direction="proportional", …)`) — the schema supports this today; the rows don't exist.

#### GAP-004-C `[TOPOLOGY GAP]` — Active-filter prompts are actively *mis*classified, not just unclassified. **Corrupts P9.**
`rc_lowpass` triggers include the phrases `"low-pass filter"`/`"lowpass filter"` (`topology_classifier.py:121-127`) at phrase confidence 0.90 — above the 0.60 threshold. Prompt 9's "fourth-order Butterworth **active** low-pass filter" will be confidently classified as a passive RC low-pass. This is worse than a miss: downstream consumers (`axiom_loader`, `retrieval/planner.topology_slugs`) receive a wrong-but-confident slug. First observed instance of a classification *correctness* hazard rather than a coverage hole.

#### GAP-004-D `[TOPOLOGY GAP]` — Battery→rails power delivery is re-derived per design, not a reusable topology. **Recurs in 7/10 (P1,2,3,5,6,7,10).**
Every battery prompt needs the same sub-system: single Li-ion input → low-IQ LDO(s) → regulated rail(s), possibly a bias/negative rail. Today `ElectricalConstraints.supply_topology` is a plain string ("battery"), deliberately not mapped to topology nodes (`TOPOLOGY_CONSTRAINT_LAYER.md` §1 — verified still accurate), and no `topology:battery_power_delivery` node exists. Each design would re-solve this from goal-string matching. A composite `TOPOLOGY` node with PART_OF blocks (cell input protection, low-IQ LDO per rail, optional inverter) would let 7 of these 10 prompts share one vetted recipe.

#### GAP-004-E `[ANALYSIS GAP]` — No estimation layer exists for **any** requested metric. **Blocks 10/10. Confirms and generalizes GAP-001-D.**
`src/analysis/` does not exist; `NoiseAnalysisResult` (BR-001-6) was never built. The 10 prompts request ≥14 metric kinds: battery life (P1,6,7,10), CMRR (P1), offset drift (P1), noise floor / current noise / output noise / input-referred noise / NEP (P1,2,3,4,5,6), output impedance (P2), efficiency (P2,6), temperature drift & long-term stability (P3,7), bandwidth (P4,5), dynamic reserve (P5), gain & noise figure (P8), passband ripple & THD (P9), lock time & phase noise (P10), power dissipation (P7,9,10). GAP-001-D scoped this to current noise; this sweep shows estimation is not a nice-to-have module but a **standing output category the log's own DesignRequest vocabulary already names** (`request_type="noise_analysis"|"simulation"` — `src/schemas/common.py:72-76`) with nothing behind it.

#### GAP-004-F `[SCHEMA GAP]` — Even with estimators built, predicted metrics have no graph representation.
Distinct from GAP-004-E: `KGNodeType` (`src/schemas/kg.py:43-63`) has no node type for a system-computed *output* (predicted CMRR, estimated battery life), and `DesignSubgraph`/`ValidatedBOM` carry no field for one. `DESIGN_CONSTRAINT` is the wrong home — it represents user-asserted *inputs*, and conflating the two would blur exactly the input-vs-derived distinction an auditor needs. Proposed minimal addition is specified in `SCHEMA_ARCHITECTURE_REVIEW_2026-07.md` §2 (PREDICTED_METRIC node + DERIVED_FROM relation). **Consumer named** (dead-weight axiom): the DocumentationGenerator report section (BR-001-7, still OPEN) and the post-hoc audit query "which constraint and which component instances produced this number."

#### GAP-004-G `[SCHEMA GAP]` — Protection/safety behaviors are silently dropped. **Blocks 6/10 (P1,2,3,4,6,8) with safety-relevant content.**
Asks: reverse-current protection (P2,6), reverse-polarity protection (P3), soft-start (P6), thermal shutdown (P6), Kelvin sensing (P2), ESD protection (P8), EMI protection + input filtering (P1), reverse-bias generation & guard rings (P4). Verified: `grep -ri "reverse.current|reverse.polarity|esd|thermal shutdown|soft.start|kelvin" src/intent/` → **zero hits**. The rule-based keyword list (`parser.py:312-317`) contains none of them; `APPLICATION_INFERENCES` (`constraint_inferrer.py`) contains none. Schema state: `ThermalConstraints.kelvin_sensing_required` exists (`intent.py:139`) but has **no writer and no reader anywhere in src/** — an existing dead-weight field, ironically violating the project's own axiom; `polarity_generation_required` likewise has no producer. There is no field at all for reverse-current/ESD/thermal-shutdown/soft-start. For a defense-context tool, silently dropping *safety* features is an audit failure, not a degradation. Recommendation argued in the schema review §4.

#### GAP-004-H `[SCHEMA GAP]` — Frequency-/condition-scoped constraints: partially representable, never populated, and ranges impossible.
The good news the hypothesis missed: `NoiseSpec` already has `bandwidth_hz` and `measurement_condition` (`src/schemas/common.py:24-30`), so "50 nV/√Hz **at 1 kHz**" (P1) *is* structurally representable — it just never gets populated (GAP-004-A) and `measurement_condition` is an opaque free string. The real holes: (a) `FrequencySpec` is a single `value`+`unit` (`intent.py:41-53`) — "10 Hz–100 kHz selectable" (P9) and "10–500 MHz" (P10) cannot be captured; (b) no way to scope a *gain*, *impedance*, or *phase-noise* constraint to a band/offset ("gain at 2.4 GHz" P8; "phase noise at offset" P10); (c) at the KG level, `DESIGN_CONSTRAINT` specs are serialized into the Neo4j `properties_json` blob (`src/knowledge_graph/backends/neo4j_backend.py:469-475`) — unqueryable by Cypher except for the two promoted scalars (`frequency_hz`, `prop_component_type`), which at least proves the promotion pattern exists. Field-vs-node-type argument in the schema review §3.

#### GAP-004-I `[SCHEMA GAP]` — Comparative topology selection cannot store *why*. **Blocks the compare asks in 5/10 (P4,7,8,9,10).**
Half the prompts explicitly ask the system to compare topologies and (implicitly) justify the winner. Today: `goal_topologies: list[TopologyGuess]` keeps candidates, but `TopologyGuess.evidence` is a list of matched *keywords* (`common.py:66-69`), not engineering rationale; `goal_topology` stores only the winner's slug; `BOMEntry.justification` is a fill-in template ("X required for Y design. Source: Z." — `src/bom/justification.py:46-60`); nothing records the rejected alternative or the criterion that rejected it. A reviewer asking "why fractional-N over integer-N?" gets a confidence float. This fails the audit-trail hard gate the moment comparison prompts become normal — and this sweep shows they already are.

#### GAP-004-J `[SCHEMA GAP]` — DESIGN_CONSTRAINT node identity collides for multi-rail/multi-block designs. **Latent in 7/10.**
`_constraint_node` builds ids as `design_constraint:{design_id}:{kind}` with `kind ∈ {electrical, thermal, performance, declared}` (`src/knowledge_graph/constraints/__init__.py:60-75`) — **one node per kind per design**, upserted. P7 has two electrically distinct sub-systems (thermistor in-amp rail vs ±500 mA TEC drive); P5 has four-plus. The second `electrical` spec would silently overwrite the first. Today this is masked by GAP-004-A (nothing populates the specs at all), but it is the first structural wall any real multi-rail design hits. Analysed as the primary Part B §1 finding.

#### GAP-004-K `[WIRING GAP]` — Topology KG remains uninstallable-in-practice and untraversable. **Prerequisite for every topology gain above.**
Re-verified 2026-07-07, still exactly as the corrected `TOPOLOGY_CONSTRAINT_LAYER.md` header states: `install_topologies()` is called only from its own unit tests (grep across src/, scripts/, tests/), and `goal_mapper._START_NODE_TYPES = (COMPONENT_TYPE, DESIGN_RECIPE)` (`src/knowledge_graph/query/goal_mapper.py:22`) means `query_graph()` can never reach a `TOPOLOGY` node even after installation. Ingesting the 9 missing topologies (GAP-004-B) is pointless until this is closed.

#### GAP-004-L `[COMPONENT GAP]` — Component families for all 10 prompts absent from KG-3.
Confirms **GAP-001-B** (zero-drift op-amps — P1,2,3), **GAP-001-C** (ultra-precision/low-TCR resistors — P2,3), **GAP-001-E** (precision multiturn pots — P2,6). New families with no ingested datasheets: micropower CMOS amplifiers (P1), ultra-low-IQ LDOs (P1,2,3,5,6,7,10 — highest-leverage single family in the sweep), buried-zener & bandgap references (P3), JFET-/CMOS-input electrometer amps (P4), analog switches & precision multipliers (P5), laser diodes + monitor photodiodes (P6), TEC modules + thermistors + H-bridge drivers (P7), GaAs/SiGe/CMOS RF transistors & LNAs (P8), PLL synthesizer ICs & VCOs (P10 — same family as GAP-002-B).

#### GAP-004-M `[DATA GAP]` — Layout-technique knowledge (guard rings, RF matching layout) absent as PLACEMENT_RULE/ROUTING_RULE rows.
P4's guard-ring recommendation and P8's impedance-matching layout are representable in principle — `PLACEMENT_RULE`/`ROUTING_RULE` node types exist (`kg.py:55-56`) and the P1 parser's Phase 5 extracts layout constraints — but no guard-ring or RF-matching rules exist in any ingested corpus. Data rows, not schema.

#### GAP-004-N `[SCHEMA GAP]` — Composite instruments collapse into a single goal string. **Structural for 10/10.**
Every prompt is a multi-subsystem instrument (P5: demodulator + LPF + gain + reference + power). The intent schema carries exactly one `goal: str` and one `goal_topology`; `in_scope_requests` holds *deliverable types*, not sub-blocks; `map_goal_to_nodes` then string-matches that one goal against node labels (`goal_mapper.py:64-97`). ADR-001 §7 assigned decomposition to the intent pipeline — correctly — but no schema field exists to hold the decomposition result. Without a `sub_blocks`-like structure (each with its own topology guess and constraint scope), the KG query sees "lock_in_amplifier" and never asks about the power rails at all. Interacts with GAP-004-J (constraint scoping needs the same block identity).

### BUILD REQUIREMENTS FOR ENTRY 004

Priority = number of the 10 prompts blocked (10-8 → HIGH, 7-4 → MEDIUM-HIGH/MEDIUM, ≤3 → LOW), consistent with Entry 001/002 usage.

| ID | What to Build | Type | Blocks | Priority |
|----|--------------|------|--------|---------|
| BR-004-1 | Production population of typed v2 constraint categories (real Stage 1 Instructor path and/or Stage 2 extraction) — unblocks interval solver + constraint persistence | Pipeline wiring | 10/10 | HIGH |
| BR-004-2 | Estimation layer: per-metric estimator modules + the PREDICTED_METRIC graph representation (schema review §2) — supersedes/absorbs BR-001-5/6/7 | New module + schema | 10/10 | HIGH |
| BR-004-3 | Ingest 9 named topologies (in-amp, Howland, V-ref module, TIA, lock-in, laser driver, TEC H-bridge/hybrid, LNA cascode, MFB/Sallen-Key/state-variable, PLL) as TOPOLOGY+FUNCTIONAL_BLOCK rows | Data ingestion | 10/10 | HIGH |
| BR-004-4 | Wire `install_topologies()` into graph bootstrap/ingestion + add TOPOLOGY to `goal_mapper._START_NODE_TYPES` | Pipeline wiring | 10/10 (prereq) | HIGH |
| BR-004-5 | Structured protection/safety requirements (schema review §4) + parser/Stage-2 detection; resolve or remove dead `kelvin_sensing_required` | Schema + wiring | 6/10 | HIGH (safety) |
| BR-004-6 | Reusable `topology:battery_power_delivery` composite node | Data + schema reuse | 7/10 | MEDIUM-HIGH |
| BR-004-7 | Constraint-node granularity fix: one node per constraint with block/rail scope (schema review §1) | Schema | 7/10 latent | MEDIUM-HIGH |
| BR-004-8 | Sub-block decomposition field on intent (`sub_blocks` with per-block topology + constraint scope) | Schema + parser | 10/10 structural | MEDIUM-HIGH |
| BR-004-9 | Comparative-selection rationale representation (schema review — trade-off record per rejected alternative) | Schema | 5/10 | MEDIUM |
| BR-004-10 | Condition/range scoping: `FrequencySpec` range support + structured condition on constraint specs (schema review §3) | Schema | 5/10 | MEDIUM |
| BR-004-11 | Classifier vocabulary: add the 9 topologies' triggers; fix `rc_lowpass` phrase-collision with active filters | Extension | 10/10 partial | MEDIUM |
| BR-004-12 | Component datasheet ingestion for the families in GAP-004-L (low-IQ LDOs first — 7/10 leverage) | Data ingestion | 10/10 partial | MEDIUM |
| BR-004-13 | Guard-ring / RF-matching layout rules ingestion | Data ingestion | 2/10 | LOW |

**Cross-references:** GAP-001-A/B/C/E and GAP-002-B/E each re-confirmed by this sweep and remain OPEN; no duplicates created — see per-gap notes above.

---

## Note — SCHEMA_ARCHITECTURE_REVIEW_2026-07.md §0 ground-truth fact 1: CLOSED (2026-07-07)

`ParsedIntent` (`src/intent/parser.py`) now carries real `electrical`/
`thermal`/`performance` fields, populated in production by a genuine
Instructor extraction call (`_extract_typed_constraints`, reusing
`call_llm_with_instructor` from `src/completion/engine.py` — no new LLM
client built). `parse_intent()`'s final `ImprovedIntentDict` construction now
forwards these fields (previously it silently dropped them even when
populated — a second wiring gap found and fixed in the same change).
Evidence: `tests/unit/intent/test_typed_constraint_extraction.py` (6 tests) —
proves population from a mocked LLM response, proves
`assert_interval_feasible` detects a real conflict on intent data that
flowed through the actual `parse_intent()` pipeline (not hand-built,
bypassing the parser), proves `persist_design_constraints` writes a non-empty
`electrical` DESIGN_CONSTRAINT node from that same real output, and proves
LLM/validation failures degrade to `None` without raising. Full regression
suite (1193 passed / 12 pre-existing unrelated failures, unchanged) confirms
no existing behavior broke. BR-004-1 in the backlog above should be
considered **CLOSED** by this change; GAP-004-A downgraded from OPEN to
CLOSED in the registry.

**Second wiring gap found during this fix (not silently patched — noted per
task instructions):** `call_llm_with_instructor`'s hardcoded 3-attempt
exponential backoff (1+2+4s) is correct for Stage 2 (a pipeline-gating call
worth retrying) but was the wrong default for this optional, best-effort
extraction — reusing it unmodified added ~7s of pure sleep to every
`parse_intent()` call when no LLM backend is reachable (confirmed via
`tests/unit/intent/test_topology_pipeline_integration.py`, which uses a real
`Config()` and slowed from ~0.01s/test to ~7s/test). Fixed by adding an
optional `max_attempts` parameter to `call_llm_with_instructor` (default
unchanged at `MAX_ATTEMPTS=3`, so Stage 2 callers are unaffected) and passing
`max_attempts=1` from the new call site — a fast, single-attempt failure
instead of Stage 2's full retry schedule. Residual, disclosed cost: any
`parse_intent()` call still pays one real connection attempt (~1.3s
confirmed locally) before degrading to `None` when no LLM server is
reachable — the same cost Stage 2 already unconditionally pays elsewhere in
the pipeline, not a new category of cost this change introduces.

---

## Note — 12 pre-existing test failures diagnosed and fixed (2026-07-07)

Following the BR-004-1 change above, an independent diagnosis (not assumed —
verified by stashing all uncommitted BR-004-1 changes via `git stash -u` and
re-running: identical 12 failures on the last real commit, `04e4d35`, with
zero BR-004-1 code present) confirmed all 12 pre-existing `FAILED` tests were
**unrelated to BR-004-1** and reduced to exactly **3 distinct root causes**,
all pre-existing v1→v2 `IntentDict` schema-migration drift never cleaned up
in the test suite:

1. **`Ambiguity` vs `AmbiguityFlag` model/vocabulary mismatch** (6 tests:
   3 in `tests/unit/test_schema_intent.py`, 2 in `tests/unit/test_intent_parser.py`,
   overlapping with root cause 2 below in 3 of those). `ImprovedIntentDict.ambiguities`
   is typed `list[Ambiguity]` (v2, `src/schemas/common.py`, severity
   `Literal["INFO","WARNING","ERROR"]`, field `candidate_resolutions`), but
   the failing tests still constructed/expected `AmbiguityFlag` (v1,
   `src/schemas/intent.py`, severity `Literal["CRITICAL","WARNING"]`, field
   `options`) — confirmed against `src/intent/ambiguity_detector.py`, whose
   real, current, unmodified blocking-ambiguity logic emits
   `severity="ERROR", blocking=True`, never `"CRITICAL"`. Fixed by
   constructing `Ambiguity` with `candidate_resolutions`/`severity="ERROR"`
   in place of `AmbiguityFlag`/`"CRITICAL"`/`options` at each failing call
   site; `AmbiguityFlag`'s own dedicated test class was left untouched (still
   valid coverage of that model, which still exists in the schema).
2. **`explicit_constraints` field referenced but absent from `ImprovedIntentDict`**
   (5 tests: 4 in `test_schema_intent.py`, 1 in `test_intent_parser.py`).
   Confirmed this field has never existed on the real v2 schema (matches the
   drift already logged in `SCHEMA_ARCHITECTURE_REVIEW_2026-07.md` §5,
   finding 4) — `infer_constraints()` only ever returns the app-inferred set,
   using explicit strings solely for de-dup filtering, never re-exposing them
   on the returned intent. Fixed by removing the field from test construction
   calls/assertions; `test_inferred_constraints_not_duplicated` was rewritten
   to check the de-dup behavior it could still verify (`"compact"` absent
   from `inferred_constraints`) rather than deleting the test's coverage
   entirely.
3. **`run_intent_pipeline()` return-arity mismatch** (4 tests, all in
   `tests/unit/intent/test_pipeline_stage2.py`) — exactly the maintenance
   item already tracked in `documents/WHATS_LEFT.md` ("still unpacks 2-tuple
   from `run_intent_pipeline` — update to triple"). `run_intent_pipeline`
   returns `(intent, bom, retrieval_result)`; fixed the 4 unpacking sites to
   `_, bom, _ =` / `a, b, _ =`.

All fixes were confined to the 3 test files above — no change to `parser.py`,
`ParsedIntent`, `interval_solver.py`, `persist_design_constraints`, or
`call_llm_with_instructor`, since Step 1 confirmed none of the 12 touched
anything BR-004-1 modified. One pre-existing unrelated lint finding
(`AmbiguityFlag` imported-but-unused in `test_intent_parser.py`, predating
BR-004-1) was cleaned up as a trivial drive-by since the import list was
already being edited.

**Left unfixed, flagged separately (task `task_9ef976e8`):** 24 pre-existing
collection `ERROR`s in `tests/unit/test_bom_generator.py` and
`tests/unit/test_bom_validator.py` share root cause 2 above exactly (a shared
fixture constructs `ImprovedIntentDict(..., explicit_constraints=[...])`).
Left out of scope since this task was explicitly scoped to the 12 `FAILED`
tests, not the separate `ERROR` category — spun off as its own follow-up
rather than folded in silently.

**Result:** full suite 1205 passed / 0 failed / 24 errors (unrelated,
flagged above), down from 1193 passed / 12 failed / 24 errors.

---

## Note — SCHEMA_ARCHITECTURE_REVIEW_2026-07.md §0 ground-truth fact 3: CLOSED (2026-07-07) — BR-004-4

**Wiring only.** `install_topologies()` now runs idempotently at graph
backend startup on all production paths:

- `KnowledgeGraph.__init__` and `KnowledgeGraph.load()` (`src/knowledge_graph/graph.py`)
- `Neo4jGraphBackend.__init__` immediately after `_ensure_schema()`
  (`src/knowledge_graph/backends/neo4j_backend.py`)
- `GraphBackendRegistry.get_graph_backend()` for config-selected backends
  (`src/knowledge_graph/backends/_registry.py`)

`goal_mapper._START_NODE_TYPES` now includes `KGNodeType.TOPOLOGY`
(`src/knowledge_graph/query/goal_mapper.py:22-26`). Verified against code:
`install_topologies()` was previously called only from
`tests/unit/knowledge_graph/test_topology_library.py`; `_START_NODE_TYPES`
was `(COMPONENT_TYPE, DESIGN_RECIPE)` only.

**Second wiring gap found during tracing (fixed in-scope):** `PART_OF` edges
run `FUNCTIONAL_BLOCK → TOPOLOGY`, so outbound-only BFS from a matched
topology start cannot reach its blocks. Fixed by
`_include_topology_blocks()` in `goal_mapper.py`, which co-starts matched
topology's `PART_OF` children so they appear in `path_confidences`.

**Third gap found during tracing (reported, not fixed — out of scope):**
`query_graph()` maps `intent.goal`, not `intent.goal_topology`
(`src/knowledge_graph/query/__init__.py:140`). A pipeline where
`topology_classifier` sets `goal_topology="buck_converter"` but `goal` is a
natural-language phrase (e.g. "5V regulator for drone") will not reach
`topology:buck_converter` unless the goal string also matches the topology
label. The topology search controller's outer loop (selecting among multiple
topology candidates from a KG shortlist — scoreboard, pruning, single- vs
multi-block scope) remains a separate, architecturally undecided future
feature and is **not** closed by this task.

**Fourth gap (reported, not fixed — out of scope):**
`result_builder.build_subgraph()` silently drops `TOPOLOGY` and
`FUNCTIONAL_BLOCK` from typed `DesignSubgraph` lists; they are present in
`path_confidences` after this fix but not in dedicated payload fields. No
change made — `DesignSubgraph` schema is locked per `kg.py` docstring.

Evidence: `tests/unit/knowledge_graph/test_topology_wiring.py` (5 gate
tests) — startup install, idempotency, `_START_NODE_TYPES`, real
`query_graph()` E2E for `goal="buck_converter"` returning
`topology:buck_converter` plus all five buck functional blocks in
`path_confidences`, and regression that `COMPONENT_TYPE` goal mapping is
unchanged. Full regression suite: **1210 passed / 0 failed / 24 errors**
(the 24 `explicit_constraints` collection errors remain tracked separately
as `task_9ef976e8`; no new failures introduced). Collateral test updates for
bootstrap baseline counts in 6 existing test files (stats/idempotency
assertions that assumed an empty `KnowledgeGraph()`).

---

## Note — BR-004-4 gaps #3 and #4: CLOSED (2026-07-07) — BR-004-5

**Gap #3 (goal_topology unused by query layer) — CLOSED.** `query_graph()`
now merges start nodes from both `intent.goal` (existing
`map_goal_to_nodes`) and `intent.goal_topology` (new
`map_goal_topology_to_nodes` in `goal_mapper.py`, resolving
`topology:<slug>`). Goal-based matching for `COMPONENT_TYPE`/`DESIGN_RECIPE`
is unchanged and additive. Verified: intent with
`goal="compact switching supply for drone avionics"` (no textual topology
match) and `goal_topology="buck_converter"` still reaches
`topology:buck_converter`.

**Gap #4 (typed DesignSubgraph exposure) — CLOSED.** `DesignSubgraph` now
carries `topologies: list[KGNode]` and `functional_blocks: list[KGNode]`
(`src/schemas/kg.py`); `result_builder.build_subgraph()` populates both from
the same traversal output BR-004-4 already produced. `path_confidences`
unchanged (additive only).

**Fifth gap found during tracing (reported, not fixed — out of scope):**
`generate_bom()` (`src/bom/generator.py`) iterates only
`subgraph.component_types` — it does not read `subgraph.topologies` or
`subgraph.functional_blocks`. A topology-only query now returns typed
topology data to the caller, but the BOM stage still produces an empty
component list until downstream consumers are wired. This is consumption
wiring, not query reachability; distinct from the topology search
controller's outer loop (candidate selection, scoreboard, pruning), which
remains undecided and **not built**.

Evidence: `tests/unit/knowledge_graph/test_topology_query_exposure.py` (3
gate tests) — `goal_topology`-only match, regression on goal-based
`COMPONENT_TYPE` mapping, typed-field E2E. Full regression suite: **1213
passed / 0 failed / 24 errors** (same 24 pre-existing collection errors;
no new failures).

---

## Note — SCHEMA_ARCHITECTURE_REVIEW_2026-07.md §1 BR-004-7: CLOSED (2026-07-07)

**Per-constraint, block-scoped DESIGN_CONSTRAINT nodes with scalar promotion.**

Verified ground truth before implementation:
- `_constraint_node()` previously derived id from `(design_id, kind)` only
  (`src/knowledge_graph/constraints/__init__.py:61`) — confirmed.
- `persist_design_constraints` is the sole writer; `get_design_constraints`
  has zero production callers — confirmed.
- Neo4j scalar promotion precedent at `_node_props` (`neo4j_backend.py:472-478`)
  promoted only `frequency_hz` / `component_type` — confirmed.

Changes:
1. **Scoped node identity** — id is now
   `design_constraint:{design_id}:{kind}:{scope}` with `scope` defaulting to
   `"default"` so unscoped callers retain one-node-per-kind upsert behavior.
2. **Scalar promotion** — typed constraint spec scalars (e.g.
   `supply_voltage_max_v`, `output_current_max_ma`, `operating_temp_max_c`)
   are flattened onto `node.properties` at write time and promoted to direct
   Neo4j node properties via the extended `_neo4j_promoted_scalars()` helper
   (same path as `frequency_hz` / `prop_component_type`). Full `spec` blob
   retained for audit completeness.
3. **`get_design_constraints()`** — optional `kind` filter; returns all scopes
   for a design/kind pair.

**Explicitly out of scope (unchanged):** multi-block decomposition from real
prompts (BR-004-8) — `ParsedIntent` still produces one constraint object per
kind; this task only makes the persistence layer ready to receive multiple
scoped writes when a future caller provides them.

Evidence: `tests/unit/knowledge_graph/test_design_constraints.py` (4 new gate
tests) — two scoped electrical constraints coexist, default scope reproduces
prior upsert, scalar promotion queryable on Neo4j, `get_design_constraints`
returns all scopes. Full regression suite: **1217 passed / 0 failed / 24
errors** (same 24 pre-existing collection errors; no new failures).

---

## Note — SCHEMA_ARCHITECTURE_REVIEW_2026-07.md §2 BR-004-14: CLOSED (2026-07-07)

**PREDICTED_METRIC + DERIVED_FROM graph representation (representation only).**

Verified ground truth before implementation:
- `KGNodeType` had no output-shaped member (`src/schemas/kg.py:43-64`) — confirmed.
- `src/analysis/` does not exist — confirmed.
- `ValidatedBOM` / `DesignSubgraph` carry no metric fields — confirmed.
- `KGEdge.constraints` is `dict[str, Any]` (`src/schemas/kg.py:169-172`) — confirmed.
- `knowledge_version(graph)` lives in `src/knowledge_graph/constraints/__init__.py`
  and is reused by DESIGN_CONSTRAINT writers — confirmed.

Changes:
1. **`KGNodeType.PREDICTED_METRIC`** — layer 5, `design_id`-scoped; properties:
   `metric_kind`, `value`, `unit`, `method`, `knowledge_version`, and optional
   `condition` (informal `dict` placeholder for future §3 `ConditionScope`).
2. **`KGRelation.DERIVED_FROM`** — directed edges from a predicted metric to
   input nodes (`DESIGN_CONSTRAINT`, `COMPONENT_INSTANCE`, `TOPOLOGY`); per-input
   contribution data on `KGEdge.constraints` (flat dict, same pattern as
   ScalingLaw payloads on PART_OF edges).
3. **Writer/reader** — `src/knowledge_graph/metrics/__init__.py`:
   `persist_predicted_metric(...)`, `get_predicted_metrics(...)`.

**Explicitly out of scope (unchanged / future work):**
- No `src/analysis/` or estimator/simulation logic (BR-004-2 computation portion,
  BR-001-5/6 remain open).
- No review-gate comparison of PREDICTED_METRIC vs DESIGN_CONSTRAINT violations.
- No `DocumentationGenerator` estimate-rendering section (BR-001-7).
- No §3 `ConditionScope` model — `condition` is a placeholder dict only.

Evidence: `tests/unit/knowledge_graph/test_predicted_metrics.py` (5 gate tests) —
node creation, DERIVED_FROM edges to real inputs, audit-trail traversal via
`get_neighbors(..., DERIVED_FROM)` on a live NetworkX backend, reader filter,
`knowledge_version` reuse. Full regression suite: **1222 passed / 0 failed / 24
errors** (same 24 pre-existing collection errors; no new failures).

---

## Note — §2 follow-up BR-004-15: CLOSED (2026-07-07)

**PREDICTED_METRIC cross-method overwrite fix.**

Verified: `persist_predicted_metric` derived node id from
`(design_id, metric_kind)` only (`src/knowledge_graph/metrics/__init__.py:63`) —
`method` was a property but not part of identity, so a second estimator writing
the same `metric_kind` silently overwrote the first (same class of bug as
BR-004-7 for DESIGN_CONSTRAINT).

Change: node id is now
`predicted_metric:{design_id}:{metric_kind}:{method}`. Same-method re-writes
still upsert (latest estimate wins); different methods coexist as separate nodes.
`get_predicted_metrics()` unchanged — may now return multiple nodes per
`metric_kind` when multiple methods produced one.

Evidence: `tests/unit/knowledge_graph/test_predicted_metrics.py` (2 new gate
tests) — cross-method coexistence, same-method upsert preserved. All 7 metrics
gate tests pass. Full regression suite: **1224 passed / 0 failed / 24 errors**
(same 24 pre-existing collection errors; no new failures).

---

## Note — SCHEMA_ARCHITECTURE_REVIEW_2026-07.md §3 BR-004-16: CLOSED (2026-07-07)

**ConditionScope + FrequencySpec range + KG scalar promotion + interval-solver guard.**

Verified ground truth before implementation:
- `NoiseSpec.measurement_condition` was an opaque string (`src/schemas/common.py:28`)
  — confirmed; no gain/impedance/phase-noise spec models exist beyond `NoiseSpec`.
- `FrequencySpec` was point-only (`value` + `unit`, `src/schemas/intent.py:41-53`)
  — confirmed; no `min_hz`/`max_hz`.
- `_flatten_spec_scalars` nested `condition` as `noise_condition_*` without a
  dedicated prefix — confirmed.

Changes:
1. **`ConditionScope`** shared sub-model in `src/schemas/common.py`.
2. **`NoiseSpec`** — `measurement_condition` removed; `condition:
   Optional[ConditionScope]` added (not duplicated).
3. **`FrequencySpec`** — optional `min_hz`/`max_hz` in absolute Hz for selectable
   ranges (point `value`+`unit` retained for backward compatibility).
4. **Scalar promotion** — `_flatten_spec_scalars` emits `condition_parameter`,
   `condition_at`, `condition_min`, `condition_max`; Neo4j backend promotes
   `condition_*` keys via existing `_neo4j_promoted_scalars` path.
5. **Interval solver Rule 3** — compares `performance.noise` vs
   `performance.component_noise_floor` only when `conditions_comparable()` passes;
   skips indeterminate comparisons (different `parameter` or absent conditions).

**Explicitly out of scope / not done:**
- §2 review-gate comparison (`PREDICTED_METRIC.condition` vs constraint
  `ConditionScope`) — separate future consumer.
- `PREDICTED_METRIC`'s informal `condition` dict placeholder **not** swapped to
  `ConditionScope` (flagged for small follow-up — **closed BR-004-17**).
- Parser-level population of `ConditionScope` from real prompts — separate future work.
- Full condition-reconciliation engine or unit conversion.

Evidence: `tests/unit/test_condition_scope.py` (6 gate tests). Full regression
suite: **1230 passed / 0 failed / 24 errors** (same 24 pre-existing collection
errors; no new failures).

---

## Note — §3 follow-ups BR-004-17: CLOSED (2026-07-07)

**FrequencySpec point/range exclusivity + PREDICTED_METRIC ConditionScope swap.**

1. **`FrequencySpec` precedence** — `value`+`unit` (point) and `min_hz`+`max_hz`
   (range) are mutually exclusive; Pydantic validator rejects construction when
   both are set. Range-only specs no longer carry a nominal `value`. Docstring
   states the rule explicitly. No existing construction sites used both (§3 range
   test was the only dual-field case; updated to range-only).

2. **`PREDICTED_METRIC.condition`** — `persist_predicted_metric(...)` now accepts
   `Optional[ConditionScope]` (from `src/schemas/common.py`); serialized to
   `properties["condition"]` via `model_dump` for graph storage. No
   condition-matching logic added (§2 review-gate remains future work).

Evidence: `tests/unit/test_condition_scope.py` (3 new FrequencySpec gate tests),
`tests/unit/knowledge_graph/test_predicted_metrics.py`
(`test_predicted_metric_condition_uses_real_model`). Full regression suite:
**1234 passed / 0 failed / 24 errors** (same 24 pre-existing collection errors;
no new failures).

---

## Note — SCHEMA_ARCHITECTURE_REVIEW_2026-07.md §4 BR-004-18: CLOSED (2026-07-07)

**protection_requirements schema + KG wiring + LLM population.**

Verified ground truth before implementation:
- `kelvin_sensing_required` / `polarity_generation_required` existed with zero
  writers/readers — confirmed and removed (not deprecated).
- No fields for reverse-current, ESD, thermal shutdown, soft-start, EMI — confirmed.
- Topology library (`install_topologies`) defines only LDO/buck-converter blocks —
  **no protection-specific `FUNCTIONAL_BLOCK` nodes exist today**; all unresolved
  protection asks hit the review-gate + Stage 2 warning path (expected for Entry 004).

Changes:
1. **`ProtectionRequirement`** + `protection_requirements` on `ImprovedIntentDict`.
2. **`persist_protection_requirements`** — per-requirement `DESIGN_CONSTRAINT`
   nodes (`kind="protection"`, `scope=<requirement.kind>`), scalar promotion,
   `REQUIRES` edge when a matching `functional_block:*` exists.
3. **Safety net** — `enqueue_unresolved_protection` (review queue /
   `GateStage.BOM`) + Stage 2 `run_rule_checker` Rule 4 WARNING per requirement.
4. **LLM extraction** — extended `TypedConstraintExtraction` / prompt in
   `_extract_typed_constraints` (BR-004-1 call, `max_attempts=1` unchanged).

Functional-block resolution: mapping table exists (`reverse_current` →
`reverse_current_protection`, etc.) but **no matching blocks in the live topology
library yet** — populating protection-specific blocks is separate future data work.

Evidence: `tests/unit/knowledge_graph/test_protection_requirements.py` (6 gate
tests), `tests/unit/intent/test_protection_extraction.py` (2 gate tests). Full
regression suite: **1242 passed / 0 failed / 24 errors** (same 24 pre-existing
collection errors; no new failures).

---

## Note — SCHEMA_ARCHITECTURE_REVIEW_2026-07.md §4 BR-004-19: CLOSED (2026-07-07)

**Protection safety net wired into real `run_intent_pipeline` path.**

Verified before change:
- `persist_design_constraints(...)` at `pipeline.py` lines 128 and 138 omitted
  `config`, so `enqueue_unresolved_protection` only fired when callers opted in.
- Stage 2 Rule 4 ran inside `run_completion_engine`, but contradictions only
  landed in `intent.contradictions_detected` with no downstream reader.

Changes:
1. **Pipeline persist path** — both `persist_design_constraints` call sites now
   pass `config=config`, so unresolved protection requirements enqueue review
   automatically on real pipeline runs.
2. **Stage 2 protection contradictions actionable** — when Stage 2 completed and
   populated `contradictions_detected`, protection Rule 4 flags (identified via
   structured `Contradiction.constraint_a` / `constraint_b` fields, not
   description text) are merged onto `ValidatedBOM.review_flags` with
   `review_required=True`, then surfaced via existing `enqueue_bom`.
3. **Non-protection Stage 2 warnings unchanged** — bypass-cap and other rule
   contradictions do not set `review_required` unless already triggered by BOM
   validation thresholds.

Evidence: `tests/unit/intent/test_pipeline_protection_safety_net.py` (3 gate
tests). Full regression suite: **1245 passed / 0 failed / 24 errors** (same 24
pre-existing collection errors; no new failures).

**Residual gap (closed by BR-004-20):** when `run_completion_engine` raised
`CompletionEngineError`, the rule checker was skipped on the failure path.

---

## Note — SCHEMA_ARCHITECTURE_REVIEW_2026-07.md §4 BR-004-20: CLOSED (2026-07-07)

**Rule checker decoupled from Stage 2 success; incomplete runs flagged.**

Verified before change:
- `_run_stage2` caught `CompletionEngineError` and returned Stage 1 intent with
  no rule-checker pass — protection Rule 4 and other mechanical checks were
  skipped entirely on that path.
- `run_rule_checker` accepts `RequirementCompletionResult()` (empty implied
  requirements); protection Rule 4 only needs `intent.protection_requirements`.

Changes:
1. **`_run_stage2` returns `(intent, stage2_incomplete)`** — failure paths set
   `stage2_incomplete=True` without retrying `run_completion_engine`.
2. **Rule checker on failure** — `_apply_rule_checker` runs immediately after a
   failed Stage 2 branch, merging rule-checker descriptions into
   `contradictions_detected`. Success path unchanged: rule checker still runs
   only inside `run_completion_engine`.
3. **Incomplete runs routed to review** — `stage2_incomplete` is surfaced as
   `"stage2_incomplete"` in `ValidatedBOM.review_flags` (BR-004-19 convention),
   sets `review_required=True`, and flows through existing `enqueue_bom`.
   `stage2_incomplete_from_bom()` helper provided for callers.

Closes the residual gap documented under BR-004-19.

Evidence: `tests/unit/intent/test_pipeline_stage2_incomplete.py` (4 gate
tests). Full regression suite: **1249 passed / 0 failed / 24 errors** (same 24
pre-existing collection errors; no new failures).