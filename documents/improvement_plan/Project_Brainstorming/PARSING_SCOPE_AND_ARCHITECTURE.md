# OpenForge — Datasheet Parsing Scope and Parser Architecture Analysis

**Document Version:** 1.0
**Status:** Design Only — No Implementation
**Scope:** Parsing complexity landscape + architecture decision for all ingested document types

---

## Part 1: Document Type Modality Map

Every document type OpenForge will ingest, with every modality it contains:

| Document Type | Text | Tables | Graphs | Equations | Schematics / Diagrams | Timing Diagrams | Mechanical Drawings | Structured Format | Metadata |
|---|---|---|---|---|---|---|---|---|---|
| IC Datasheets | ✓ dense | ✓ complex | ✓ performance curves | ✓ scattered | ✓ block diagrams | ✓ digital timing | ✓ package outlines | — | ✓ |
| Application Notes | ✓ tutorial | ✓ simpler | ✓ simulation plots | ✓ design formulas | ✓ circuit schematics | ✓ sometimes | — | — | ✓ |
| Reference Designs | ✓ minimal | ✓ BOM only | ✓ test results | — | ✓ schematics | — | — | — | ✓ |
| Research Papers | ✓ dense academic | ✓ results tables | ✓ measurement plots | ✓✓ critical (LaTeX-style) | ✓ circuit diagrams | — | — | — | ✓ (DOI, authors) |
| Standards (IPC/JEDEC) | ✓ formal | ✓ specification tables | — | ✓ tolerances | ✓ geometric diagrams | — | ✓ land patterns | — | ✓ |
| KiCad Library Files | — | — | — | — | — | — | — | ✓ s-expression | ✓ |
| Community (Stack Exchange) | ✓ conversational | — | — | — | ✓ embedded images | — | — | — | ✓ (tags, votes) |

---

## Part 2: Parsing Complexity Per Document Type

### IC Datasheets — Maximum Complexity

Every modality present. Tables have merged cells, sub-headers, and footnote linkages. Graphs require digitization. Timing diagrams require CV models. Mechanical drawings need dimensional extraction. Physics validation is mandatory because errors propagate to fabrication.

**What the current 5-phase pipeline does:**
- Phase 1: YOLOv8 rasterization + layout detection + footnote linkage
- Phase 2: Dual-path TSR (pdfplumber vector + Qwen2-VL)
- Phase 3: Qwen2.5-7B semantic extraction with unit normalization
- Phase 4: Physics validation (min/typ/max ordering, cross-parameter rules)
- Phase 5: Layout constraint extraction

This is correct and necessary for datasheets. The question is whether it generalises.

---

### Application Notes — High Complexity, Text-Dominant

Tables are present but simpler — no merged cells, no footnote dependencies. Equations are critical and appear inline in prose. Schematics are the key visual content, not performance graphs. No timing diagrams or mechanical drawings.

The existing pipeline over-invests here. Phase 4 (physics validation) is irrelevant — app notes describe design methodology, not component specifications. Phase 2 (dual-path TSR) is heavier than needed for BOM-style or comparison tables.

**What is actually needed:** layout detection → text extraction → table extraction (light) → equation capture → schematic image preservation.

---

### Reference Designs — Medium Complexity

BOM tables are the primary structured content and they are the simplest table format in the entire corpus: part number, value, quantity, footprint. No merged cells, no footnotes. Schematics are present but treated as images (not parsed into netlist). Test result tables are simple.

Running YOLOv8 + Qwen2-VL on a reference design BOM is a 10x overinvestment.

---

### Research Papers — Medium-High, Equation-Critical

The dominant parsing challenge is **equations**, not tables or graphs. Papers like Libbrecht & Hall (1993) contain the design physics that drives KG-2 topology knowledge. The equations are the knowledge. Standard text extraction destroys them (OCR reads `V_noise = sqrt(4kTRΔf)` as garbled characters). Tables are well-structured results tables with no complexity. Figures are measurement plots worth preserving as images.

**What is actually needed:** text extraction with equation preservation (Nougat), figure extraction as images, simple table extraction, metadata extraction (DOI, authors, year).

The existing 5-phase pipeline is wrong for this. Phase 1's YOLOv8 model is trained on DocLayNet — a corporate document dataset — and will misclassify academic paper layouts. Phase 4 physics validation is completely irrelevant.

---

### Standards Documents (IPC, JEDEC) — Medium Complexity

Formal, well-structured PDFs. Tables are specification tables (tolerance ranges, impedance specs) — well-bordered, no merged cells, no footnotes. Diagrams are geometric land pattern drawings with dimension annotations. Text is formal regulatory prose.

Lighter than datasheets. Key extraction targets are specification tables and geometric dimensions. Physics validation is not needed. YOLOv8 is unnecessary.

---

### KiCad Library Files — Zero Complexity, Different Problem

These are not PDFs. `.kicad_sym` and `.kicad_mod` are structured s-expression text files. No OCR, no vision model, no layout analysis. This requires a **custom parser** that reads the s-expression grammar and maps fields directly to the KB schema. Deterministic, fast, and trivial compared to every other document type.

Running any part of the PDF pipeline on these is a category error.

---

### Community Content (Stack Exchange) — Low Complexity

HTML pages. Text is the content. Embedded images are sometimes circuit diagrams but unreliably so. No tables of significance. No equations in parseable form.

**What is actually needed:** HTML stripping → text extraction → metadata extraction (vote score, tags, accepted status). No vision models needed.

---

## Part 3: Can a Single Parser Handle All of This?

**No — and attempting it would be wrong in two directions simultaneously.**

A unified parser built to handle datasheets (the most complex case) applied to all document types:
- Wastes compute on simple documents (running YOLOv8 on Stack Exchange HTML)
- Is wrong for research papers (DocLayNet-trained YOLOv8 misidentifies academic layouts)
- Is a category error for KiCad files (they are not PDFs)
- Adds physics validation where it is irrelevant (app notes, papers, standards)

A unified parser built to be lightweight enough for all document types:
- Cannot handle IC datasheets correctly (footnote linkage, merged cells, physics validation are non-negotiable)
- Cannot extract equations from research papers
- Cannot parse KiCad s-expressions

The problem space does not permit a single efficient parser.

---

## Part 4: Recommended Architecture — Tiered Parsing

Route each document to the correct tier based on document type classification before any parsing begins. Document type is known at download time — it is a property of the source adapter that produced it.

```
Downloaded Document
        │
        ▼
  Document Type Classifier (trivial — known from source adapter)
        │
        ├──── IC Datasheet ──────────→  Tier 1: Heavy Pipeline (existing 5-phase)
        │
        ├──── Application Note ──────→  Tier 2: Medium Pipeline
        ├──── Research Paper ────────→  Tier 2: Medium Pipeline (+ equation module)
        ├──── Standards Document ────→  Tier 2: Medium Pipeline
        ├──── Reference Design ──────→  Tier 2: Medium Pipeline
        │
        ├──── Community Content ─────→  Tier 3: Light Pipeline
        │
        └──── KiCad Library File ────→  Tier 0: Structured Parser (no ML)
```

---

## Part 5: Tier Definitions

### Tier 0 — Structured Parser

**Documents:** KiCad `.kicad_sym`, `.kicad_mod`
**Stack:** Custom s-expression parser → direct KB schema mapping
**ML models:** None
**Cost:** Negligible (~1ms per file)

---

### Tier 1 — Heavy Pipeline (existing 5-phase)

**Documents:** IC Datasheets
**Stack:** pdf2image → YOLOv8 → Dual-path TSR (pdfplumber + Qwen2-VL) → Qwen2.5-7B extraction → physics validation → layout constraint extraction
**ML models:** YOLOv8, Qwen2-VL-7B, Qwen2.5-7B
**Cost:** High (3–8 seconds per page, GPU-bound)

---

### Tier 2 — Medium Pipeline

**Documents:** Application notes, research papers, standards, reference designs
**Stack:** PDF text extraction (pdfplumber direct) → table extraction (pdfplumber lattice, no VLM) → equation capture (Nougat for academic papers only, skipped for others) → Qwen2.5-7B semantic extraction → no physics validation
**ML models:** Qwen2.5-7B only; Nougat added for research papers
**Cost:** Medium (< 1 second per page, CPU-feasible for simple docs)

---

### Tier 3 — Light Pipeline

**Documents:** Community content (Stack Exchange HTML)
**Stack:** HTML stripping → text extraction → metadata extraction (vote score, tags, accepted status)
**ML models:** None
**Cost:** Negligible (~10ms per document)

---

## Part 6: Trade-off Summary

| Dimension | Unified (heavy) | Unified (light) | Tiered |
|---|---|---|---|
| Computational cost | Wastes GPU on simple docs | Cannot handle datasheets | Right cost per document type |
| Accuracy | Wrong for papers and KiCad files | Wrong for datasheets | Right tool per type |
| Maintainability | One codebase | One codebase | Multiple pipelines |
| Extensibility | New doc type must fit one pipeline | Same constraint | New type gets its own tier or slots into an existing one |
| Inference latency | High for all | Low but incorrect | Low where possible, high only where required |
| Air-gap compatibility | ML-heavy everywhere | Fine | ML load minimised |

The maintainability cost of tiered is real — multiple pipelines instead of one. It is bounded: Tier 2 is a stripped-down version of Tier 1 sharing the same Qwen2.5-7B model. Tier 3 has no ML at all. Tier 0 is a deterministic parser. The shared model between Tier 1 and Tier 2 means the "multiple pipeline" cost is largely in routing and configuration, not in separate model stacks.
