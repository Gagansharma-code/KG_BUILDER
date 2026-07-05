TASK
====
Do two things in this exact order:
1. Reorganise the documents/ folder into a clean, logical structure
2. Create WHATS_LEFT.md — a living doc that tracks remaining work

Read everything carefully before touching any file.

CONTEXT FILES TO READ FIRST
============================
documents/README.md
documents/architecture/PROJECT_CONTEXT.md
documents/architecture/OPENFORGE_ARCHITECTURE.md
documents/architecture/OPENFORGE_ORGANIZATION.md
documents/architecture/OPENFORGE_SUBSYSTEMS.md
documents/architecture/OPENFORGE_INTEGRATION.md
documents/architecture/SYSTEM_WHITEBOX_TRACE.md
documents/architecture/problem_1_solution.md
documents/assessments/p1_assessment_filled.md
documents/improvement_plan/01_INTENT_PARSING_SCHEMA.md
documents/improvement_plan/02_REQUIREMENT_COMPLETION_ENGINE.md
documents/improvement_plan/03_RETRIEVAL_AND_KB_STRATEGY.md
documents/improvement_plan/04_DATABASE_SCHEMA.md
documents/improvement_plan/05_SEARCH_STORAGE_DEPLOYMENT_ARCHITECTURE.md
documents/improvement_plan/GLM_5.2_IMPROVEMENT_PLAN_REVIEW.md
documents/improvement_plan/Prompt_analysis_Idea.md
documents/improvement_plan/Project_Brainstorming/PARSING_SCOPE_AND_ARCHITECTURE.md
documents/improvement_plan/Project_Brainstorming/Book_parsing_pipeline_proposal.md
documents/improvement_plan/Project_Brainstorming/SCHEMA_UPDATE_ENGINE_DESIGN.md
documents/improvement_plan/Project_Brainstorming/.md.2_analysis_on_worklist.md
documents/phase1/CURSOR_PROMPT_PHASE1.md
documents/phase1/PHASE1_CORPUS_EVAL_TUNING_LOG.md
documents/guides/CODING_STANDARDS_P1.md
documents/guides/QUICK_REFERENCE_PATTERNS.md
documents/guides/PROJECT_BOOTSTRAP_GUIDE.md

---

PART 1 — REORGANISE documents/ FOLDER
======================================

Current structure is a mess:
- Phase1 cursor prompts mixed with eval logs
- Brainstorming docs buried under improvement_plan/Project_Brainstorming
- Architecture docs mixed with early prototype docs
- No clear separation between decisions (done), design (active), and backlog

TARGET STRUCTURE
----------------

documents/
├── README.md                          ← rewrite this as master index
├── objectives.md                      ← leave in place, do not touch
│
├── architecture/                      ← FINAL decisions only. No drafts.
│   ├── PROJECT_CONTEXT.md             ← leave as-is (living doc, do not rewrite)
│   ├── OPENFORGE_ARCHITECTURE.md      ← leave as-is
│   ├── OPENFORGE_ORGANIZATION.md      ← leave as-is
│   ├── OPENFORGE_SUBSYSTEMS.md        ← leave as-is
│   ├── OPENFORGE_INTEGRATION.md       ← leave as-is
│   ├── SYSTEM_WHITEBOX_TRACE.md       ← leave as-is
│   └── problem_1_solution.md          ← leave as-is
│
├── assessments/                       ← completed assessment docs only
│   ├── p1_assessment_filled.md        ← leave as-is
│   └── PARSING_SCOPE_AND_ARCHITECTURE.md  ← MOVE from improvement_plan/Project_Brainstorming/
│
├── decisions/                         ← NEW folder: adopted improvement plan docs
│   ├── 01_INTENT_PARSING_SCHEMA.md         ← MOVE from improvement_plan/
│   ├── 02_REQUIREMENT_COMPLETION_ENGINE.md  ← MOVE from improvement_plan/
│   ├── 03_RETRIEVAL_AND_KB_STRATEGY.md     ← MOVE from improvement_plan/
│   ├── 04_DATABASE_SCHEMA.md               ← MOVE from improvement_plan/
│   ├── 05_SEARCH_STORAGE_DEPLOYMENT.md     ← MOVE from improvement_plan/
│   └── GLM_IMPROVEMENT_PLAN_REVIEW.md     ← MOVE from improvement_plan/
│
├── brainstorming/                     ← NEW folder: proposals and ideas not yet decided
│   ├── Book_parsing_pipeline_proposal.md    ← MOVE from improvement_plan/Project_Brainstorming/
│   ├── SCHEMA_UPDATE_ENGINE_DESIGN.md       ← MOVE from improvement_plan/Project_Brainstorming/
│   ├── FEW_SHOT_PROMPT_ANALYSIS.md          ← RENAME from improvement_plan/Prompt_analysis_Idea.md
│   └── WORKLIST_ANALYSIS.md                 ← RENAME from improvement_plan/Project_Brainstorming/.md.2_analysis_on_worklist.md
│
├── parsing/                           ← NEW folder: all parsing-related docs
│   ├── CURSOR_PROMPT_PHASE1.md              ← MOVE from documents/phase1/
│   ├── PHASE1_CORPUS_EVAL_TUNING_LOG.md     ← MOVE from documents/phase1/
│   └── PARSER_CURSOR_PROMPTS/              ← NEW subfolder
│       ├── PARSER_P1_INTERFACES.md         ← CREATE (copy the PARSER_P1 prompt text into here)
│       ├── PARSER_P2_YOLOV8.md             ← CREATE (copy PARSER_P2 prompt text)
│       ├── PARSER_P3_PADDLEOCR.md          ← CREATE (copy PARSER_P3 prompt text)
│       ├── PARSER_P4_PDFPLUMBER.md         ← CREATE (copy PARSER_P4 prompt text)
│       ├── PARSER_P5_QWEN2VL.md            ← CREATE (copy PARSER_P5 prompt text)
│       ├── PARSER_P6_QWEN25LLM.md          ← CREATE (copy PARSER_P6 prompt text)
│       ├── PARSER_P7_ORCHESTRATOR.md       ← CREATE (copy PARSER_P7 prompt text)
│       └── PARSER_P8_POSTGRES_WRITER.md    ← CREATE (copy PARSER_P8 prompt text)
│
└── guides/                            ← leave all files in place, do not touch
    ├── CODING_STANDARDS_P1.md
    ├── QUICK_REFERENCE_PATTERNS.md
    └── PROJECT_BOOTSTRAP_GUIDE.md

MOVE RULES
----------
- MOVE = git mv (preserve history). Use actual file moves, not copy+delete.
- DELETE the now-empty folders after moving:
    documents/phase1/
    documents/improvement_plan/Project_Brainstorming/
    documents/improvement_plan/   ← if empty after moves
- Do NOT touch any file under documents/architecture/ or documents/guides/
- Do NOT touch objectives.md
- p1_assessment.md (the unfilled template) → DELETE. It is superseded.

REWRITE documents/README.md
----------------------------
After all moves, rewrite README.md as a clean master index.
Structure:

# OpenForge — Documents Index

## Where to Start
| Document | Purpose |
|---|---|
| architecture/PROJECT_CONTEXT.md | Living project status — read this first |
| WHATS_LEFT.md | What is left to build — read this second |
| objectives.md | Six formal problem statements |

## Folder Guide
Brief one-line description of each folder:
- architecture/ — Finalised system design. Stable. Do not edit without review.
- assessments/ — Completed assessment docs and scope decisions.
- decisions/ — Adopted improvement plan docs. These are locked decisions.
- brainstorming/ — Proposals under consideration. Not yet decided.
- parsing/ — Parser architecture, eval logs, and all Cursor implementation prompts.
- guides/ — Coding standards and patterns for implementers.

## Key Living Documents
Two docs that must be kept up to date:
- architecture/PROJECT_CONTEXT.md — team status, gate results, blockers
- WHATS_LEFT.md — remaining work, priorities, and change log

---

PART 2 — CREATE documents/WHATS_LEFT.md
=========================================

This is a NEW living document. It has one job:
track what is left to build, in what order, and record every
time that list changes.

It is NOT a duplicate of PROJECT_CONTEXT.md.
PROJECT_CONTEXT.md = what has been done (team status, gate results)
WHATS_LEFT.md      = what has NOT been done yet (remaining work + change log)

CREATE the file at: documents/WHATS_LEFT.md

CONTENT TO WRITE
----------------

Use this exact structure:

---

# OpenForge — What's Left

> **Last updated:** 2026-06-27
> **Updated by:** [name or "Claude" if automated]
> **Rule:** Update this file whenever a task is completed, added, or reprioritised.
>            Every change must be recorded in the Change Log at the bottom.

---

## How to Use This File

- Tasks are grouped by priority tier
- Each task has a status: ⬜ Not started | 🟡 In progress | ✅ Done | 🚫 Blocked
- When you complete a task: mark ✅, move it to the Completed section, add a Change Log entry
- When you add a new task: add it to the correct tier, add a Change Log entry
- When priority changes: move it, add a Change Log entry

---

## Tier 1 — Critical Path (blocks E2E system from running)

These must be done before the system can produce any output end-to-end.

| # | Task | Status | Blocks | Notes |
|---|------|--------|--------|-------|
| 1.1 | Run PARSER_P1–P8 in Cursor (gate test each) | 🟡 In progress | Everything downstream | Prompts written, execution pending |
| 1.2 | E2E orchestrator — wire all team pipelines into single prompt→files entry point | ⬜ Not started | First real E2E run | One Cursor prompt needed |
| 1.3 | ImprovedIntentDict v2 migration — wire Stage 2 into main intent pipeline | ⬜ Not started | Stage 2 activation | Prompt already written; not executed |
| 1.4 | Embedding ingestion pipeline — write ComponentDatasheet embeddings to PostgreSQL component_embeddings | ⬜ Not started | Vector search | Schema ready; no writer exists |
| 1.5 | Wire RetrievalEngine into BOM/synthesis orchestrator | ⬜ Not started | Retrieval-grounded BOM | RetrievalEngine built; not connected |

---

## Tier 2 — Parsing System (modular backend)

Parser prompts written. Must be executed and gate-tested in Cursor sequentially.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 2.1 | PARSER_P1 — Backend interfaces + registry | 🟡 In progress | Prompt in parsing/PARSER_CURSOR_PROMPTS/ |
| 2.2 | PARSER_P2 — YOLOv8 LayoutDetectorBackend | ⬜ Not started | Depends on P1 gate pass |
| 2.3 | PARSER_P3 — PaddleOCR ImageTableBackend | ⬜ Not started | Depends on P1 gate pass |
| 2.4 | PARSER_P4 — pdfplumber+Camelot VectorTableBackend | ⬜ Not started | Depends on P1 gate pass |
| 2.5 | PARSER_P5 — Qwen2-VL ImageTableBackend (swap proof) | ⬜ Not started | Depends on P1 gate pass |
| 2.6 | PARSER_P6 — Qwen2.5-7B LLMBackend | ⬜ Not started | Depends on P1 gate pass |
| 2.7 | PARSER_P7 — Modular pipeline orchestrator | ⬜ Not started | Depends on P2–P6 gate pass |
| 2.8 | PARSER_P8 — PostgreSQL ComponentDatasheet writer | ⬜ Not started | Depends on P7 gate pass |
| 2.9 | GPU lab validation — Phase 2 VLM + Phase 3 LLM with real weights | ⬜ Not started | vlm_enabled: true run on lab GPU |
| 2.10 | Phase 3 eval harness — field_f1 ≥ 0.93 gate on 5 golden datasheets | ⬜ Not started | Needs grid-level ground truth annotation |

---

## Tier 3 — Knowledge Base Population

These populate the KG. System can run without them but will produce poor BOMs.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 3.1 | Book parser (KG-1) — replace spaCy primary with LLM-primary triple extraction | ⬜ Not started | spaCy stays as sentence boundary only |
| 3.2 | Book parser (KG-1) — add chapter classifier to route formula-heavy chapters | ⬜ Not started | Keyword heuristic, no ML needed |
| 3.3 | Nexar batch pre-ingestion CLI — GraphQL client + PDF downloader + batch runner | ⬜ Not started | Three-component build |
| 3.4 | KiCad library file importer (Tier 0) — s-expression parser → KG writer | ⬜ Not started | Deterministic, no ML |
| 3.5 | App note prose extractor — placement rule extraction from app note text | ⬜ Not started | placement_extractor.py is a stub |
| 3.6 | Run KB population — Nexar batch pre-ingestion on 10 priority components | ⬜ Not started | Depends on 3.3 |

---

## Tier 4 — Quality and Evaluation

These improve accuracy. System runs without them but evaluation is incomplete.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 4.1 | Curate 25-datasheet test corpus in corpus/test/ | ⬜ Not started | Currently 0/25 |
| 4.2 | Few-shot examples for Phase 3 extraction prompts | ⬜ Not started | See brainstorming/FEW_SHOT_PROMPT_ANALYSIS.md |
| 4.3 | Few-shot examples for Phase 5 layout extraction prompts | ⬜ Not started | Same doc |
| 4.4 | Pin normalizer LLM fallback few-shot examples | ⬜ Not started | Same doc |

---

## Tier 5 — Research Paper

| # | Task | Status | Notes |
|---|------|--------|-------|
| 5.1 | Write Section 1 — Introduction | ⬜ Not started | Target: DAC/DATE/ICCAD or NeurIPS/ICLR ML-for-Systems workshop |
| 5.2 | Write Section 2 — Related Work | ⬜ Not started | Start here, parallel with code |
| 5.3 | Design evaluation benchmark for paper | ⬜ Not started | Needs E2E system working |
| 5.4 | Run experiments and collect results | ⬜ Not started | Needs Tier 1 + Tier 2 complete |
| 5.5 | Write remaining sections + submit | ⬜ Not started | 4–6 page workshop format |

---

## Completed Tasks

Record every finished task here with date.

| Date | Task | Notes |
|------|------|-------|
| 2026-06-27 | PARSER_P1 through P8 prompts written | All 8 prompts designed by Claude; execution in Cursor pending |
| 2026-06-27 | Modular parser backend architecture designed | BackendRegistry, 5 interfaces, plug-and-play config |
| 2026-06-26 | Stage 05 search/storage/deployment complete | Synonym expansion, coverage reporting, model pinning |
| 2026-06-26 | Retrieval engine (Stage 3) gate pass — 36/36 tests | RetrievalEngine built; not yet wired to BOM |
| 2026-06-21 | Stage 2 completion engine smoke-tested — 12/12 pass | Not yet wired into main intent pipeline |
| Prior | All team gates A–F passing — 699 unit tests | Teams A/B/C/D/E/F all gate-tested |
| Prior | 5/5 golden corpus Phase 1 eval — 100% recall/precision | YOLOv8 DLA validated |
| Prior | PARSING_SCOPE_AND_ARCHITECTURE.md written | Tiered parsing architecture decided |

---

## Change Log

Every change to this file must be recorded here.
Format: `YYYY-MM-DD | action | what changed | why`

| Date | Action | What | Why |
|------|--------|------|-----|
| 2026-06-27 | CREATED | Initial version of WHATS_LEFT.md | First creation during document reorganisation |

---

END OF WHATS_LEFT.md CONTENT

---

GATE CHECKS
===========
After all file operations complete, verify:

Check 1: documents/WHATS_LEFT.md exists and has all 5 tiers
Check 2: documents/README.md has been rewritten with master index structure
Check 3: documents/parsing/PARSER_CURSOR_PROMPTS/ folder exists with 8 files
Check 4: documents/decisions/ folder exists with 6 files
Check 5: documents/brainstorming/ folder exists with 4 files
Check 6: documents/phase1/ folder no longer exists
Check 7: documents/improvement_plan/ folder no longer exists (or is empty)
Check 8: documents/architecture/ still has all its original files untouched
Check 9: documents/guides/ still has all its original files untouched
Check 10: p1_assessment.md (unfilled template) no longer exists

Print a summary table of all files moved, created, and deleted.

CONSTRAINTS
===========
- No file under documents/architecture/ or documents/guides/ may be modified
- objectives.md must not be touched
- PROJECT_CONTEXT.md must not be touched
- Use file moves not copy+delete where possible
- WHATS_LEFT.md is a markdown file — no code, no Pydantic, no imports
- All 8 PARSER cursor prompt files must contain the full prompt text
  (copy verbatim from the conversation / wherever they are stored)