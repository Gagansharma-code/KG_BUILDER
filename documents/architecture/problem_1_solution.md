# Automated Datasheet Parsing Pipeline

**Project:** AI-Driven EDA Tool Integration (Open Forge)
**Objective:** Extract highly accurate, structured, machine-readable electronic component data from heterogeneous PDF datasheets (e.g., Texas Instruments) to feed downstream AI layout generation.

---

## 🏗️ Architecture Overview

PDFs are vector-based graphic files, not structured databases. To achieve absolute accuracy necessary for defense-grade PCB design, we cannot rely on regex or simple text scraping. The pipeline follows a **Hybrid Multimodal** approach, simulating human reading cognition: seeing the layout, understanding the grid, extracting the semantics, and validating the physics.

The pipeline has **5 phases** (updated 2026-07-06 — a Phase 5 was added
after this document was originally written; see `DOC_DRIFT_AUDIT.md` N19
and `src/datasheet/phase5_layout/`):

```
PDF Input
   │
   ▼
[Phase 1] Document Layout Analysis  ──→  Table crops + Footnote crops (linked)
   │
   ▼
[Phase 2] Table Structure Recognition  ──→  Structured grid matrix (with confidence)
   │
   ▼
[Phase 3] Constrained Semantic Extraction  ──→  Normalized, typed JSON
   │
   ▼
[Phase 4] Physics Validation  ──→  Validated data
   │
   ▼
[Phase 5] Layout Extraction  ──→  PlacementConstraint list (src/datasheet/phase5_layout/)
   │
   ▼
Validated ComponentDatasheet → KiCad MCP Server
```

---

## Phase 1: Document Layout Analysis (DLA)

Before reading the text, the system must visually identify where tables and footnotes exist on the page, isolating them from schematics, performance graphs, and descriptive text.

### Strategy

1. **Rasterization:** Convert the PDF pages into high-resolution images (e.g., 300 DPI) using `pdf2image`.
2. **Object Detection:** Pass the images through a document-specific vision model.
3. **Cropping:** Extract the regions classified specifically as `Table` and `Footnote`.
4. **⚠️ Footnote Linkage (New):** After cropping, detect superscript markers (e.g., `(1)`, `*`) inside table cells and match them to their corresponding footnote crop by spatial proximity and marker identity. Store this linkage in a `footnote_map` dictionary:

```python
# Example footnote_map structure
footnote_map = {
    "(1)": "Guaranteed by design. Not tested in production.",
    "(2)": "Applies when V_CC > 3.0V",
}
```

> **Why this matters:** Datasheets frequently hide critical constraints (temperature derating, test conditions) inside footnotes. Ignoring the linkage means your extracted data silently carries `(1)` tokens with no meaning — a hidden error that can produce invalid PCB layouts.

### Recommended Models / Tools

* **LayoutLMv3 (Microsoft):** Industry standard for document understanding; handles both visual and textual features.
* **YOLOv8 / YOLOv10 (DocLayNet):** Extremely fast and easily deployable in an air-gapped environment. Train/fine-tune on the DocLayNet dataset.
* **Marker / Surya:** Open-source pipelines optimized for PDF-to-Markdown with high accuracy in layout detection.

---

## Phase 2: Table Structure Recognition (TSR)

Once the table's bounding box is isolated, the internal matrix (rows, columns, merged cells) must be reconstructed.

### Strategy: Parallel Dual-Path with Confidence Selection

> **Change from original:** Path A and Path B now run **in parallel**, not sequentially. Both produce a candidate grid matrix; a confidence scorer picks the winner. This eliminates the silent failure mode where Path A returns a mangled matrix and the pipeline proceeds without knowing it.

```
Cropped Table Image
        │
   ┌────┴────┐
   ▼         ▼
[Path A]   [Path B]
Vector     VLM
Lines      Image
   │         │
   ▼         ▼
Grid_A     Grid_B
   │         │
   └────┬────┘
        ▼
  Confidence Scorer
  (structural agreement,
   cell count, parse ratio)
        │
        ▼
  Best Grid Matrix
```

#### Path A: Vector Fallback

* **How it works:** Scan the PDF vector instructions for explicit horizontal and vertical lines.
* **Tools:** `pdfplumber`, `Camelot` (lattice mode).
* **Best for:** Fully bordered tables (common in older datasheets). Gives 100% accurate structural extraction when lines are present.

#### Path B: Multimodal Fallback

* **How it works:** Pass the cropped table image directly to a Vision-Language Model (VLM).
* **Tools:** Gemini 1.5 Pro (Cloud), Qwen-VL (Local/Air-gapped), LLaVA.
* **Prompting Strategy:** Instruct the VLM to return the grid structure in Markdown table format, then parse it into a matrix.
* **Best for:** Whitespace-delimited or partially-bordered tables (increasingly common in modern TI datasheets).

#### Confidence Scorer Logic

```python
def pick_best_grid(grid_a, grid_b) -> dict:
    """
    Score each candidate grid and return the higher-confidence result.
    Attach the confidence metadata for downstream use.
    """
    score_a = score_grid(grid_a)   # checks: cell count, empty ratio, parse success
    score_b = score_grid(grid_b)

    winner = grid_a if score_a >= score_b else grid_b
    winner["_confidence"] = max(score_a, score_b)
    winner["_source"] = "vector_path_A" if score_a >= score_b else "vlm_path_B"
    return winner
```

---

## Phase 3: Constrained Semantic Extraction (The "Brain")

Raw grid text (`V_CC`, `VDD`, `3.3`) is useless until mapped to standardized electrical concepts. We must force the LLM to categorize the data strictly according to our backend data structures.

### Strategy

Use structured generation libraries to ensure the LLM's output conforms to a strict JSON schema. This guarantees that your KiCad MCP server receives deterministic, parsable types instead of conversational text.

### Implementation Setup (Python)

* **Tools:** `Instructor`, `Pydantic`.

### ⚠️ Unit Normalization Layer (New)

A dedicated normalization step must run **before** data hits the Pydantic model. Different datasheets express the same value in different units — your backend must receive a single canonical form.

> **Analogy:** You asked three people how far the station is. One said "2 km", one said "2000 m", one said "1.24 miles". You need a translator before the data hits your map.

```python
CANONICAL_UNITS = {
    "voltage": "V",
    "current": "mA",
    "resistance": "Ω",
    "capacitance": "pF",
    "frequency": "MHz",
    "temperature": "°C",
    "time": "ns",
}

def normalize_value(raw_value: str, raw_unit: str, param_type: str) -> tuple[float, str]:
    """
    Convert any expressed unit to the canonical unit for that parameter type.
    Examples:
        ("3300", "mV", "voltage")  → (3.3, "V")
        ("0.5", "A",  "current")   → (500.0, "mA")
        ("1.5", "kΩ", "resistance")→ (1500.0, "Ω")
    """
    # ... conversion logic ...
```

### Pydantic Schema (with Confidence Metadata)

Every extracted value must carry a `confidence` score and `source` tag so the downstream system — and human reviewers — know how trustworthy each field is.

```python
from pydantic import BaseModel
from typing import Optional

class ExtractedValue(BaseModel):
    raw_text: str              # Original text from the cell, e.g. "3300 mV"
    value: float               # Normalized numeric value, e.g. 3.3
    unit: str                  # Canonical unit, e.g. "V"
    confidence: float          # 0.0 – 1.0 score from the TSR phase
    source: str                # "vector_path_A" or "vlm_path_B"
    footnote: Optional[str]    # Linked footnote text if superscript was detected

class ElectricalParameter(BaseModel):
    name: str                          # e.g. "V_CC", "I_CC", "V_IL"
    parameter_type: str                # e.g. "voltage", "current", "threshold"
    min_value: Optional[ExtractedValue]
    typ_value: Optional[ExtractedValue]
    max_value: Optional[ExtractedValue]
    conditions: Optional[str]          # e.g. "T_A = 25°C"

class ComponentDatasheet(BaseModel):
    component_id: str
    manufacturer: str
    parameters: list[ElectricalParameter]
```

---

## Phase 4: Physics Validation 

> **This phase was described in the Architecture Overview but was missing from the original pipeline. It is non-negotiable for defense-grade accuracy.**

After semantic extraction, every parameter set is passed through a rule engine that checks physical plausibility. This layer catches OCR errors, VLM hallucinations, and unit-normalization bugs *before* they propagate to KiCad layout generation.

> **Analogy:** Think of this as a physics teacher checking your homework. Even if your calculation looks formatted correctly, they'll catch it if `V_CC = 0.001V` for a 3.3V logic IC.

### Validation Rule Categories

#### 1. Min / Typ / Max Ordering

```python
def validate_parameter_ordering(param: ElectricalParameter) -> list[str]:
    errors = []
    if param.min_value and param.typ_value:
        if param.min_value.value > param.typ_value.value:
            errors.append(f"{param.name}: min ({param.min_value.value}) > typ ({param.typ_value.value})")
    if param.typ_value and param.max_value:
        if param.typ_value.value > param.max_value.value:
            errors.append(f"{param.name}: typ ({param.typ_value.value}) > max ({param.max_value.value})")
    return errors
```

#### 2. Cross-Parameter Electrical Rules

```python
ELECTRICAL_RULES = [
    # Rule: V_CC must be greater than V_IL (logic low threshold)
    {
        "rule": "V_CC > V_IL",
        "params": ["V_CC", "V_IL"],
        "check": lambda vcc, vil: vcc.typ_value.value > vil.max_value.value,
        "severity": "CRITICAL",
    },
    # Rule: V_IH (logic high threshold) must be less than V_CC
    {
        "rule": "V_IH < V_CC",
        "params": ["V_IH", "V_CC"],
        "check": lambdavih, vcc:vih.max_value.value < vcc.min_value.value,
        "severity": "CRITICAL",
    },
]
```

#### 3. Plausibility / Range Sanity Checks

```python
SANITY_RANGES = {
    # (param_name_pattern, unit, min_sane, max_sane)
    "V_CC":  ("voltage",     0.5,    40.0),    # supply voltage: 0.5V – 40V
    "I_CC":  ("current",     0.001,  5000.0),  # supply current: 1µA – 5A in mA
    "T_J":   ("temperature", -55.0,  175.0),   # junction temp: -55°C – 175°C
}
```

### Validation Output

```python
class ValidationResult(BaseModel):
    component_id: str
    passed: bool
    errors: list[str]        # CRITICAL issues — block downstream use
    warnings: list[str]      # Suspicious values — flag for human review
    review_required: bool    # True if any confidence score < threshold
```

### Routing Logic

```
ValidationResult
       │
  passed=True ──────────────────────→ KiCad MCP Server
  passed=False (warnings only) ─────→ KiCad MCP Server + Human Review Flag
  passed=False (critical errors) ───→ BLOCKED — re-trigger Phase 2/3 or escalate
```

---

## Confidence Metadata Flow (Cross-Pipeline)

Every extracted value carries a `confidence` field that originates in Phase 2 (TSR) and travels unchanged through Phase 3 and Phase 4. If confidence drops below a configurable threshold at any stage, the record is flagged for human review rather than silently passed downstream.

```
Phase 2 TSR → confidence=0.91, source="vlm_path_B"
     │
     ▼
Phase 3 Extraction → value=3.3, unit="V", confidence=0.91
     │
     ▼
Phase 4 Validation → passed=True, review_required=False (0.91 > threshold 0.85)
     │
     ▼
KiCad MCP Server ✅
```

> **This is especially critical for air-gapped deployments** where you cannot re-query a cloud API on failure. The confidence field makes uncertainty explicit rather than hidden.

---

