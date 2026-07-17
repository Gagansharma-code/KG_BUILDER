# Golden Corpus Manifest

## Status: 10/10 complete ✅

| # | Component | Type | Status | Pages | Notes |
|---|---|---|---|---|---|
| 1 | TI_SN74LVC1G04 | Logic Gate | ✅ Complete | ~10 | Single inverter |
| 2 | TI_TLV7021 | Comparator | ✅ Complete | ~20 | Simple analog |
| 3 | TI_INA219 | Current Sensor | ✅ Complete | ~30 | I2C interface |
| 4 | TI_LM5176 | Buck-Boost Controller | ✅ Complete | ~45 | Power IC |
| 5 | TI_TPS62933 | Sync Buck Converter | ✅ Complete | ~30 | Replacement for TMS320 |
| 6 | ST_STM32F030C8 | MCU (small) | ✅ Complete | ~90 | Gap 1/2 baseline — LQFP-48, structured AFs |
| 7 | RPI_RP2040 | MCU (large) | ✅ Complete | ~600 | Gap 1/2 stress — QFN-56, multi-function GPIO |
| 8 | TI_CC1101 | RF Transceiver | ✅ Complete | ~100 | Gap 3 — dBm/dBc units, RF sections |
| 9 | IR_IRLZ44N | Power MOSFET | ✅ Complete | ~8 | Gap 5 — RθJA/RθJC as electrical_characteristics |
| 10 | TI_TLV755P | LDO | ✅ Complete | ~30 | Diagram A2 — CIN/COUT=1µF typical-app figure |

## Archived

| Component | Reason |
|---|---|
| TI_TMS320F280039C | DSP MCU — deferred stress test; revisit after Gaps 1/2 proven on #7 |

## Corpus Selection Criteria (updated)

Original scope (analog/power, <30 pins) expanded per 90–95% coverage target
(see `documents/improvement_plan/parser_fullscope_gap_analysis.md` and
`documents/improvement_plan/PHASE1_GOLDEN_CORPUS_PROMPT.md`).
MCU, RF, and thermal-relevant parts now in scope. FPGA and connector-only
datasheets remain out of scope (gap doc Gaps 6–7).

## Phase 1 verification note

New entries (#6–#10) were curated from manufacturer datasheet values and must be
spot-checked against the official PDFs before treating as production ground
truth. Schema validation: `python corpus/golden/validate_ground_truth.py`.
