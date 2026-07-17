# Golden Corpus

Ten hand-verified datasheets for evaluation (5 original + 5 Phase 1 expansion).
Each pair:

- `<VENDOR>_<part>_v1.pdf` — source PDF (gitignored; download from manufacturer)
- `<VENDOR>_<part>_v1_ground_truth.json` — nested golden ground truth

## Download Links

| File | URL |
|------|-----|
| TI_SN74LVC1G04_v1.pdf | https://www.ti.com/lit/ds/symlink/sn74lvc1g04.pdf |
| TI_TLV7021_v1.pdf | https://www.ti.com/lit/ds/symlink/tlv7021.pdf |
| TI_INA219_v1.pdf | https://www.ti.com/lit/ds/symlink/ina219.pdf |
| TI_LM5176_v1.pdf | https://www.ti.com/lit/ds/symlink/lm5176.pdf |
| TI_TPS62933_v1.pdf | https://www.ti.com/lit/ds/symlink/tps62933.pdf |
| ST_STM32F030C8_v1.pdf | https://www.st.com/resource/en/datasheet/stm32f030c8.pdf |
| RPI_RP2040_v1.pdf | https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf |
| TI_CC1101_v1.pdf | https://www.ti.com/lit/ds/symlink/cc1101.pdf |
| IR_IRLZ44N_v1.pdf | https://www.infineon.com/dgdl/Infineon-IRLZ44N-DataSheet-v01_01-EN.pdf |
| TI_TLV755P_v1.pdf | https://www.ti.com/lit/ds/symlink/tlv755p.pdf |

## Spike PDFs (subset)

Phase 0 spike uses: TLV7021, TMS320F28003x, LM5176.

## Validate Ground Truth

```bash
python corpus/golden/validate_ground_truth.py
```
