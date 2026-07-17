# Phase 1 — Golden Corpus Expansion

**Model:** Claude Sonnet 5 (per earlier model guidance — this is careful transcription against real datasheets, not novel reasoning)
**Files:** `corpus/golden/*.json`, `corpus/golden/CORPUS_MANIFEST.md`
**Time estimate:** 4–6 hours (mostly your time reading real datasheets and verifying, not Cursor's)

---

## Important finding before you start

`CORPUS_MANIFEST.md` states the original corpus was **deliberately scoped to exclude MCUs, DSPs, and FPGAs**:

> Corpus Selection Criteria: Analog or power management IC (no MCUs, DSPs, FPGAs). Single electrical characteristics table. Pinout under 30 pins preferred.

There's already an **archived** entry: `TI_TMS320F280039C` — a DSP MCU, 254 pages, 1600+ pin mux configs, explicitly marked "out of P1 scope."

This matters: expanding the corpus to include MCU/RF/thermal parts is you **deliberately reversing that scoping decision**, which is correct given your new 90–95% target — just go in knowing it, not accidentally. Also: do NOT start with `TMS320F280039C` itself. 1600+ pin mux configs is the *end boss* of Gap 1/2, not the starting stress test — you'd be debugging pin chunking and AF extraction on the hardest possible case simultaneously. Pick a smaller MCU first (see below), and only revisit `TMS320F280039C` once Gaps 1 and 2 are proven on something manageable.

---

## Verified golden file format (from `TI_TPS62933_v1_ground_truth.json`)

Top-level keys:
```json
{
  "component_id": "TPS62933DRLR",
  "manufacturer": "Texas Instruments",
  "package": "SOT-23-...",
  "sections": [ ... ],
  "pins": [
    {
      "pin_number": "1",
      "pin_name": "RT",
      "pin_type": "A",
      "description": "..."
    }
  ],
  "metadata": {
    "datasheet_id": "SLUSEA4D",
    "revision": "D",
    "date": "August 2022",
    "operating_conditions": "...",
    "footnote_map": { "(1)": "...", ... }
  },
  "datasheet_version": "...",
  "extraction_timestamp": "..."
}
```

**Note:** `pins[].pin_name` here, not `raw_name` — the golden format doesn't map 1:1 to `PinDefinition` field names. This is expected; that's what `validate_ground_truth.py` (which you already updated in Task 4) translates. Match the existing format exactly, don't invent a new one — consistency with the 5 existing files matters more than matching the Pydantic schema field names directly.

For MCU pins with alternate functions, extend the pin object with an `alternate_functions` array using the **new structured format** (matching what you already did for `TI_INA219`):
```json
{
  "pin_number": "42",
  "pin_name": "PB5",
  "pin_type": "IO",
  "description": "...",
  "default_function": "GPIO",
  "alternate_functions": [
    { "name": "SPI2_MOSI", "af_index": 5, "peripheral": "SPI" },
    { "name": "TIM3_CH2", "af_index": 2, "peripheral": "TIM" }
  ]
}
```

---

## The 5 datasheets to add

### 1. Small MCU — validates Gap 1 baseline + Gap 2 baseline
**Recommendation:** STM32F030 (or ATTINY85 if you want something even simpler first)
- 20–48 pins, some with alternate functions
- Purpose: prove pin chunking and AF extraction work correctly *before* throwing a 144-pin table at it
- Download from ST's official site; use the datasheet PDF directly

### 2. Large MCU — the real Gap 1/2 stress test
**Recommendation:** STM32F407 or RP2040
- 64–216 pins, multi-page pin table, AF0–AF15 style columns (if STM32F4 family)
- This is the one that actually exercises the chunking logic and multi-page merge
- **Do this one only after #1 passes** — if chunking is broken, you want to find that on the 48-pin case, not the 144-pin one

### 3. RF IC — validates Gap 3
**Recommendation:** CC1101 or nRF24L01
- Look for dBm, dBc, and S-parameter values in the electrical characteristics
- Note any RF-specific section headings ("Spurious Emissions", "Phase Noise", "Port Characteristics") — these are exactly what Gap 3's section classifier keywords need to match

### 4. Power MOSFET with thermal table — validates Gap 5
**Recommendation:** IRLZ44N (already named in the gap doc) or AO3400
- Must have a thermal characteristics table with θJA / θJC values
- Confirm these land under `ELECTRICAL_CHARACTERISTICS` per your Phase 0 decision (no `THERMAL_CHARACTERISTICS` enum)

### 5. Application-circuit figure part — validates Diagram doc's A2 extraction
**Recommendation:** Any TI LDO or buck converter where the passive values (decoupling cap, feedback resistor) are shown *only* in the typical application circuit figure, not restated in body text
- This is the hardest one to find — you need to actually read a few candidate datasheets to confirm the values are figure-only, not duplicated in text
- If you can't find a clean figure-only case, a part where captions near the figure state the values (e.g. "C1 = 10µF") is an acceptable substitute — it validates the caption-extraction path even if it's not the hardest case

---

## Process per datasheet (repeat 5x)

1. Download the official manufacturer PDF.
2. Read it yourself — don't have Cursor "extract" the ground truth from the PDF; ground truth needs to be hand-verified against the source, that's the whole point of a golden corpus. Cursor can help you *format* the JSON once you've read the values, not derive them.
3. Build the JSON matching the exact structure shown above (component_id, manufacturer, package, sections, pins, metadata, datasheet_version, extraction_timestamp).
4. For MCU pins with multiple functions, use the structured `alternate_functions` format.
5. For thermal parts, make sure θJA/θJC appear as electrical parameters (matching your Phase 0 routing decision) in `sections`.
6. Save as `corpus/golden/<MANUFACTURER>_<PART>_v1_ground_truth.json`, following existing naming convention.
7. Run `python corpus/golden/validate_ground_truth.py` after each file — catch format errors immediately, not after all 5 are done.

---

## Update the manifest

After all 5 are added, update `corpus/golden/CORPUS_MANIFEST.md`:

```markdown
## Status: 10/10 complete ✅

| # | Component | Type | Status | Pages | Notes |
|---|---|---|---|---|---|
| 1 | TI_SN74LVC1G04 | Logic Gate | ✅ Complete | ~10 | Single inverter |
| 2 | TI_TLV7021 | Comparator | ✅ Complete | ~20 | Simple analog |
| 3 | TI_INA219 | Current Sensor | ✅ Complete | ~30 | I2C interface |
| 4 | TI_LM5176 | Buck-Boost Controller | ✅ Complete | ~45 | Power IC |
| 5 | TI_TPS62933 | Sync Buck Converter | ✅ Complete | ~30 | Replacement for TMS320 |
| 6 | <SMALL_MCU> | MCU (small) | ✅ Complete | ~N | Gap 1/2 baseline |
| 7 | <LARGE_MCU> | MCU (large) | ✅ Complete | ~N | Gap 1/2 stress test — multi-page pinout, AF columns |
| 8 | <RF_PART> | RF Transceiver | ✅ Complete | ~N | Gap 3 — dBm/dBc units, RF sections |
| 9 | <MOSFET_PART> | Power MOSFET | ✅ Complete | ~N | Gap 5 — thermal table (θJA/θJC) |
| 10 | <APP_CIRCUIT_PART> | LDO/Buck | ✅ Complete | ~N | Diagram doc A2 — figure-only passive values |

## Archived

| Component | Reason |
|---|---|
| TI_TMS320F280039C | DSP MCU — deferred stress test; revisit after Gaps 1/2 proven on #7 |

## Corpus Selection Criteria (updated)

Original scope (analog/power, <30 pins) expanded per 90–95% coverage target
(see documents/improvement_plan/parser_fullscope_gap_analysis.md).
MCU, RF, and thermal-relevant parts now in scope. FPGA and connector-only
datasheets remain out of scope (see gap doc Gaps 6–7, explicitly deferred/excluded).
```

Note the manifest change on `TMS320F280039C` — reword from "out of P1 scope" to "deferred stress test," since it's no longer permanently excluded, just sequenced later.

---

## Exit criteria

- 10 golden files total, `validate_ground_truth.py` reports 10/10 OK
- `CORPUS_MANIFEST.md` updated to reflect new scope and 10 entries
- Each new file hand-verified by you against the actual datasheet PDF (not just schema-valid — schema-valid ≠ correct)

---

## After Phase 1

Report back with: how many parts, which ones, validator result. Then we move to Phase 2 (RF/thermal unit normalizer — quick win) or Phase 3 (timing split), your call on order since both are independent.
