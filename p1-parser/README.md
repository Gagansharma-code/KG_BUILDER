# P1 Datasheet Parser

> **Living status:** [`../documents/architecture/PROJECT_CONTEXT.md`](../documents/architecture/PROJECT_CONTEXT.md) — update on every phase completion.

Automated datasheet parsing pipeline for air-gapped PCB design systems (SSPL DRDO).

Extracts electrical characteristics, absolute maximum ratings, and pinouts from Texas Instruments PDF datasheets into validated, machine-readable JSON for downstream KiCad MCP integration.

## Architecture

Four-phase hybrid multimodal pipeline:

1. **Phase 1 (DLA):** Document layout analysis — table crops + footnote linkage
2. **Phase 2 (TSR):** Dual-path table structure recognition (vector + VLM)
3. **Phase 3 (Extraction):** Constrained semantic extraction with unit normalization
4. **Phase 4 (Validation):** Physics validation and routing (pass / warn / block)

See [`../documents/architecture/problem_1_solution.md`](../documents/architecture/problem_1_solution.md) for full architecture details.

## Current Status: Phase 4 Implemented (FPR/FNR eval deferred)

- [x] Project structure, config, schemas, logging
- [x] Golden corpus 5/5 annotated
- [x] YOLO + Qwen2-VL model weights verified
- [x] Phase 1 DLA implementation (`src/phase1_dla/`)
- [x] Phase 1 golden eval **5/5 PASS** — see `eval/phase1/PHASE1_RESULTS.md`
- [x] Phase 2 TSR implementation (`src/phase2_tsr/`) — dual-path vector + VLM
- [x] Phase 2 unit/integration tests (45 passing, mocked VLM)
- [ ] Phase 2 golden eval metrics (requires grid GT + GPU lab run)
- [x] Phase 3 extraction (`src/phase3_extract/`) — rule-based grid parsers
- [x] Phase 3 unit/integration tests (53 passing, no GPU)
- [ ] Phase 3 golden eval metrics (requires `eval/phase3/` harness)
- [x] Phase 4 validation + KiCad export (`src/phase4_validate/`)
- [x] Phase 4 unit/integration tests (45 passing, no GPU)
- [ ] Phase 4 FPR/FNR eval (requires 30-datasheet corpus harness)
- [ ] Full pipeline orchestrator (`src/pipeline.py`) + review queue

See [`../documents/architecture/PROJECT_CONTEXT.md`](../documents/architecture/PROJECT_CONTEXT.md) for full phase dashboard.  
Phase 1 eval tuning log: [`../documents/phase1/PHASE1_CORPUS_EVAL_TUNING_LOG.md`](../documents/phase1/PHASE1_CORPUS_EVAL_TUNING_LOG.md)

## Prerequisites

- Python 3.9+
- [Poppler](https://poppler.freedesktop.org/) (`poppler-utils` on Ubuntu, `brew install poppler` on macOS)
- CUDA 11.8+ optional (CPU-only mode supported, slower VLM inference)

## Installation

```bash
cd drdo-p1-parser
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

Verify:

```bash
python -c "import src; from src.schemas import ComponentDatasheet"
pytest tests/unit/ -v
```

## Directory Layout

```
drdo-p1-parser/
├── src/
│   ├── config.py              # Single source of truth for settings
│   ├── schemas/               # Pydantic models (output contract)
│   ├── phase1_dla/            # Phase 1 DLA (complete)
│   ├── phase2_tsr/            # Phase 2 TSR (implemented)
│   ├── phase3_extract/        # Phase 3 extraction (implemented)
│   ├── phase4_validate/       # Phase 4 validation + KiCad export (implemented)
│   └── pipeline.py            # Orchestrator (Phase 4+)
├── corpus/golden/             # Golden PDFs + ground truth JSON
├── eval/spike/                # Model spike runner + results
├── models/                    # Offline model weights (not in git)
└── configs/default.yaml
```

## Model Weights

Download offline weights (internet-connected machine only):

```bash
python scripts/download_models.py --yolo-only   # ~7 MB
python scripts/download_models.py --all         # ~30+ GB
```

See `models/README.md` and `logs/download.log` for details.

## Model Spike

Compare YOLOv8-DocLayNet vs Surya on 3 spike PDFs:

```bash
# Place PDFs in corpus/golden/ (see corpus/golden/README.md)
python eval/spike/run_spike.py
```

Results: `eval/spike/SPIKE_RESULTS.md`

**Locked default (pre-spike):** YOLOv8n-DocLayNet for Phase 1 DLA.

## Golden Corpus

Five golden datasheets with hand-verified ground truth JSON:

| Priority | Component | Status |
|----------|-----------|--------|
| 1 | TI_SN74LVC1G04 | Complete |
| 2 | TI_TLV7021 | Complete |
| 3 | TI_INA219 | Complete |
| 4 | TI_LM5176 | Complete |
| 5 | TI_TPS62933 | Complete (replaces archived TMS320) |

Validate ground truth:

```bash
python -c "
from pathlib import Path
from src.schemas import ComponentDatasheet
import json
for f in Path('corpus/golden').glob('*_ground_truth.json'):
    ComponentDatasheet.model_validate(json.loads(f.read_text()))
    print(f'OK: {f.name}')
"
```

## PDF Acquisition

TI datasheets are not in git. Download manually:

- [SN74LVC1G04](https://www.ti.com/lit/ds/symlink/sn74lvc1g04.pdf)
- [TLV7021](https://www.ti.com/lit/ds/symlink/tlv7021.pdf)
- [INA219](https://www.ti.com/lit/ds/symlink/ina219.pdf)
- [LM5176](https://www.ti.com/lit/ds/symlink/lm5176.pdf)
- [TPS62933](https://www.ti.com/lit/ds/symlink/tps62933.pdf)

Save as `corpus/golden/TI_<part>_v1.pdf`.

## Phase 2 TSR

Dual-path table extraction: pdfplumber + Camelot (Path A) parallel with Qwen2-VL (Path B).

```bash
# Unit tests (no GPU, VLM mocked/disabled)
pytest tests/unit/test_phase2_*.py tests/integration/test_phase2_e2e.py -v

# GPU lab eval (set phase2_tsr.vlm_enabled: true in configs/default.yaml)
python eval/phase2/run_eval.py --corpus corpus/golden --save-outputs
```

MacBook default: `phase2_tsr.vlm_enabled: false` — Path A only. Cell-level metrics deferred until grid golden GT exists.

## Phase 3 Extraction

Rule-based semantic extraction from Phase 2 `GridMatrix` tables: electrical parameters, pinouts, absolute maximum ratings, footnote resolution, and validation into `ComponentDatasheet`.

```bash
# Unit + integration tests (no GPU, LLM disabled)
pytest tests/unit/test_phase3_*.py tests/integration/test_phase3_e2e.py -v
```

MacBook default: `phase3_extract.llm_enabled: false` — rule-based extractors only. LLM stubs (`prompt_templates.py`, `extractor.py`) exist but are not wired into `run_phase3()`. Golden semantic eval (`field_f1 ≥ 0.93`) deferred until `eval/phase3/` harness exists.

## Phase 4 Validation & KiCad Export

Physics validation (ordering, sanity ranges, cross-parameter rules, abs-max checks) and KiCad-compatible JSON export from Phase 3 `ComponentDatasheet`.

```bash
# Unit + integration tests (no GPU, mock Phase 3 outputs)
pytest tests/unit/test_phase4_*.py tests/integration/test_phase4_e2e.py -v
```

Outputs written to `output/phase4/{component_id}_validation.json` and `{component_id}_kicad.json`. FPR/FNR corpus eval deferred. `src/pipeline.py` and review queue still pending.

## Development

```bash
black src/ tests/
mypy src/
pylint src/
pytest tests/unit/ -v
```

## License

Open source

