<p align="center">
  <strong>Open Forge</strong>
</p>

<p align="center">
  <em>Turning datasheet PDFs into deterministic, machine-readable intelligence for AI-assisted PCB design.</em>
</p>

<p align="center">
  <a href="#the-vision">Vision</a> ·
  <a href="#the-six-problems">Roadmap</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#project-structure">Structure</a> ·
  <a href="#getting-started">Getting Started</a> ·
  <a href="#current-status">Status</a>
</p>

---

## The Vision

Electronic design automation still depends on humans manually reading hundreds of pages of PDF datasheets — hunting through electrical characteristics tables, absolute maximum ratings, pinout diagrams, and footnotes buried in inconsistent layouts. A single missed footnote or misread voltage limit can cascade into a failed board spin.

**Open Forge** is an open-source intelligence layer for PCB design. It reads datasheets the way an experienced engineer does: see the layout, reconstruct the tables, extract the semantics, and validate the physics — then hands structured, trustworthy data to downstream CAD tools through the [KiCad Model Context Protocol (MCP)](https://github.com/modelcontextprotocol).

The system is built for **air-gapped, on-prem deployment**. No cloud APIs. All model weights ship inside a self-contained Docker image. Deterministic output over probabilistic guesswork.

---

## The Six Problems

Open Forge tackles PCB intelligence as six interconnected problems. Each builds on the last, forming a complete path from raw PDF to validated schematic data.

| # | Problem | What it solves |
|---|---------|----------------|
| **1** | **Semi-Structured Data Extraction** | Parse electrical characteristics, absolute maximum ratings, and pinouts from heterogeneous PDF datasheets into standardized JSON |
| **2** | **Semantic Entity Resolution** | Normalize manufacturer-specific pin naming (`VDD`, `VCC`, `V+`) into universal electrical concepts |
| **3** | **Visual Topological Extraction** | Use computer vision to parse functional block diagrams and recover internal module relationships |
| **4** | **Authoritative Grounding** | Build a domain knowledge graph from canonical engineering texts so the AI reasons from physics, not hallucination |
| **5** | **Cross-Component Connection Synthesis** | Determine valid topological connections between arbitrary component symbols to form functional schematics |
| **6** | **System Integration & Inference Strategy** | Wire the intelligence layer into KiCad MCP with strict context-window management for deterministic CAD output |

**Active focus:** Problem 1 — the datasheet parsing pipeline (`p1-parser`).

---

## Architecture

PDFs are vector graphics, not databases. Regex and naive text scraping cannot deliver the accuracy PCB design demands. Open Forge uses a **hybrid multimodal pipeline** that mirrors human cognition: layout → structure → semantics → validation.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         PDF Datasheet Input                             │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Phase 1 — Document Layout Analysis (DLA)                               │
│  YOLOv8n-DocLayNet · table crops · footnote linkage                     │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Phase 2 — Table Structure Recognition (TSR)                            │
│  Dual-path: pdfplumber + Camelot  ∥  Qwen2-VL → confidence selection  │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Phase 3 — Constrained Semantic Extraction                              │
│  Qwen2.5 + Instructor → Pydantic · unit normalization · footnotes     │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Phase 4 — Physics Validation + KiCad Export                            │
│  Ordering rules · sanity ranges · cross-parameter checks → pass/warn/block│
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
                    <component_id>_parsed.json
                         ↓
                   KiCad MCP Server
```

### Design principles

- **Footnotes are first-class data.** Critical constraints hide in superscript markers. The pipeline links `(1)` tokens in table cells to their footnote text before extraction — silent footnote loss is a hidden layout bug.
- **Dual-path TSR with confidence scoring.** Vector extraction and vision-language models run in parallel; the best grid matrix wins. No silent mangling.
- **Physics validation before export.** Extracted values pass ordering rules, sanity ranges, and cross-parameter checks. Bad data is blocked, not forwarded.
- **Air-gapped by default.** YOLOv8, Qwen2-VL, and Qwen2.5 weights run locally. No external API calls at inference time.

---

## Project Structure

```
├── documents/                  # Specs, architecture, guides, assessments
│   ├── objectives.md           # Six formal problem statements
│   ├── architecture/           # Living status + pipeline narrative
│   ├── assessments/            # Authoritative P1 schema & metrics
│   └── guides/                 # Coding standards, dev workflows
│
└── p1-parser/                  # Problem 1 — datasheet parsing pipeline
    ├── src/
    │   ├── phase1_dla/         # Document layout analysis
    │   ├── phase2_tsr/         # Table structure recognition
    │   ├── phase3_extract/     # Semantic extraction
    │   └── phase4_validate/    # Physics validation + KiCad export
    ├── corpus/golden/          # Hand-verified ground truth (5 TI parts)
    ├── eval/                   # Phase eval harnesses + spike results
    ├── models/                 # Offline model weights (gitignored)
    └── configs/default.yaml    # Single source of truth for settings
```

### Key documentation

| Document | Purpose |
|----------|---------|
| [`documents/objectives.md`](documents/objectives.md) | Full problem statements for all six challenges |
| [`documents/architecture/PROJECT_CONTEXT.md`](documents/architecture/PROJECT_CONTEXT.md) | Living project status and phase dashboard |
| [`documents/assessments/p1_assessment_filled.md`](documents/assessments/p1_assessment_filled.md) | Authoritative P1 spec — schema, models, exit metrics |
| [`p1-parser/README.md`](p1-parser/README.md) | Parser setup, commands, and phase details |

---

## Getting Started

### Prerequisites

- Python 3.9+
- [Poppler](https://poppler.freedesktop.org/) — `brew install poppler` (macOS) or `poppler-utils` (Ubuntu)
- CUDA 11.8+ optional (CPU-only mode supported; VLM inference is slower)

### Quick start

```bash
cd p1-parser

python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Verify installation
pytest tests/unit/ -v
```

### Model weights (offline machine)

```bash
python scripts/download_models.py --yolo-only   # ~7 MB
python scripts/download_models.py --all         # ~30+ GB (YOLO + Qwen2-VL + Qwen2.5)
```

### Golden corpus validation

Five Texas Instruments datasheets with hand-verified ground truth:

| Component | Type |
|-----------|------|
| SN74LVC1G04 | Logic gate |
| TLV7021 | Comparator |
| INA219 | Current sensor |
| LM5176 | Buck-boost regulator |
| TPS62933 | Buck converter |

```bash
python corpus/golden/validate_ground_truth.py
```

---

## Current Status

| Phase | Name | Status |
|-------|------|--------|
| 0 | Spike & Tooling | Substantially complete |
| 1 | DLA Implementation | **Complete** — 5/5 golden corpus PASS |
| 2 | TSR Implementation | Implemented — golden eval metrics deferred |
| 3 | Extraction | Implemented — golden eval metrics deferred |
| 4 | Validation + KiCad Export | Implemented — FPR/FNR eval deferred |
| 5 | Docker + Air-Gapped Delivery | Not started |

**Next milestones:** full pipeline orchestrator (`pipeline.py`), human review queue, Phase 5 Docker image with baked-in weights, and end-to-end eval on a 30-datasheet corpus.

See [`documents/architecture/PROJECT_CONTEXT.md`](documents/architecture/PROJECT_CONTEXT.md) for the live phase dashboard.

---

## Output Contract

Every successfully parsed component produces a validated JSON file:

```
<component_id>_parsed.json
```

Structured with Pydantic schemas covering electrical parameters (with units and conditions), absolute maximum ratings, pinout definitions, and footnote resolutions — ready for KiCad MCP consumption.

---

## Contributing

Open Forge is in active development. If you are working on the parser:

1. Read `documents/assessments/p1_assessment_filled.md` for requirements
2. Follow `documents/guides/CODING_STANDARDS_P1.md`
3. Run `pytest` before opening a PR
4. Update `PROJECT_CONTEXT.md` when a phase milestone is reached

---

## License

Open source. See repository license for details.

---

<p align="center">
  <strong>Open Forge</strong> — structured intelligence for the boards we build.
</p>
