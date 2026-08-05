# Plan — ASHA Search Controller + Weak-Model Self-Improvement Loop

**Audience:** Cursor (or any implementing agent), working directly in this repo.
**Scope:** Idea 1 (the missing supervisor/orchestrator loop) and Idea 2 (weak model +
verifier self-improvement — the "agent maxing" demo), from the AMD AI Developer
Program Track 2 pitch deck.
**Out of scope for this plan:** ROCm/AMD port (Idea 6), retrieval harness (Idea 3),
datasheet proofreader loop (Idea 4), review copilot (Idea 5), long-term memory (Idea 7),
and wiring any of this into `run_e2e()` / production defaults. Everything here lands
behind a config flag, off by default, so it cannot break existing gates.

Read `documents/decisions/Search_controller_decision.md` first — it is the design
doc this plan implements. Also skim `documents/architecture/MCTS_DECISION.md` for why
beam search (not MCTS) is the escalation path.

---

## 0. Ground truth before you write any code

Verify these against the live repo — this plan was written against the state as of
2026-08, and this codebase has a documented history of docs drifting from code
(see `DOC_DRIFT_AUDIT.md`). Specifically:

1. **`src/schematic/search_controller.py` does not exist.** `ASHAResult` is currently
   only mentioned in comments inside `src/bom/tpe_sampler.py` and
   `src/schematic/beam_search_escalation.py`. You are creating this file and this type
   for the first time.
2. **`synthesize_schematic()` (`src/schematic/__init__.py`) is fully deterministic** —
   rule-based net assignment (`net_assigner.py`, `passive_assigner.py`), not an LLM
   call. The decision doc's description of ASHA "generating netlist variants at
   different LLM temperatures" describes an *aspirational* design, not current code.
   This matters: **do not assume there is an LLM in the schematic-synthesis path
   today.** Idea 1 works entirely without one (variance comes from BOM candidates,
   not netlist resampling). Idea 2 is what introduces the first LLM into this path —
   see §2.
3. **`generate_bom_candidates()`, `TPEBOMSampler`, `polish_schematic()`, and
   `run_beam_search()` are already implemented and already gate-tested.** Do not
   reimplement them. Idea 1 is purely an orchestration layer over these four
   existing modules.
4. Confirm current test counts before starting (`pytest tests/unit -q`) so you have
   a baseline to diff against.

---

## 1. Idea 1 — ASHA Search Controller (`src/schematic/search_controller.py`)

### 1.1 What it does

Closes the loop described in `Search_controller_decision.md` §4–6, using only
already-built pieces:

```
BOMLadder (from generate_bom_candidates(), enriched by TPEBOMSampler)
    │
    ▼
for each BOM candidate:
    synthesize_schematic(candidate, datasheets, subgraph, config)  → SchematicGraph
    build_ref_map(candidate, datasheets)                            → ref_map
    verify_schematic(netlist, ref_map, bom=candidate)               → VerificationResult
    │
    ▼
winner = candidate with highest VerificationResult.score
    │
    ├─ winner.score >= 1.00                → done, no refinement needed
    ├─ 0.80 <= winner.score < 1.00          → polish_schematic(...)      (SA polisher)
    └─ winner.score < 0.80                  → run_beam_search(...)       (beam escalation)
    │
    ▼
if sampler provided: record_asha_outcome(sampler, winner_bom, final_score)
    │
    ▼
return ASHAResult
```

### 1.2 Honest naming caveat

Because `synthesize_schematic()` is deterministic, there is no point re-evaluating
the *same* BOM candidate twice — a second attempt would score identically. So this
first version is **best-of-N over BOM candidates**, not true multi-round ASHA
(successive halving needs something stochastic to re-sample across rounds). That's
fine and still delivers the whole point of Idea 1: the loop that currently doesn't
exist gets built, and TPE learning, SA polishing, and beam escalation all get
switched on for the first time. Idea 2 (§2) adds the LLM-based generator that gives
this controller actual rounds to iterate over — note that hook in `search_controller.py`
now (see 1.4) so Idea 2 slots in without a rewrite.

### 1.3 New file: `src/schematic/search_controller.py`

```python
"""ASHA search controller — closes the loop between BOM candidates, the
5-layer structural verifier, the SA polisher, and beam search escalation.

See documents/decisions/Search_controller_decision.md for the full design.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Optional

from src.bom.tpe_sampler import TPEBOMSampler, record_asha_outcome
from src.schematic._ref_mapper import build_ref_map
from src.schematic.sa_polisher import SA_DONE_THRESHOLD, SA_TRIGGER_THRESHOLD, polish_schematic
from src.schematic.beam_search_escalation import run_beam_search
from src.schematic.structural_verifier import verify_schematic

if TYPE_CHECKING:
    from src.bom.candidates import BOMLadder
    from src.config import Config
    from src.schemas.datasheet import ComponentDatasheet
    from src.schemas.intent import ValidatedBOM
    from src.schemas.kg import DesignSubgraph
    from src.schemas.nir import NetlistEntry
    from src.schematic.beam_search_escalation import BeamSearchResult
    from src.schematic.sa_polisher import SAPolishResult
    from src.schematic.structural_verifier import VerificationResult

logger = logging.getLogger(__name__)

HUMAN_REVIEW_THRESHOLD: float = 0.80  # below this after beam search, route to review


@dataclass
class ASHAResult:
    """Result of one full search-controller run.

    winner_bom:          The BOM candidate that produced the best schematic.
    winner_ladder_id:     ladder_id of the BOMLadder this came from (traceability).
    initial_verification: VerificationResult for winner_bom before any refinement.
    final_netlist:        Netlist after SA polish / beam search / neither.
    final_score:          Score after refinement.
    stage_used:           Which path was taken.
    sa_result:            Populated only if stage_used == "sa_polish".
    beam_result:          Populated only if stage_used == "beam_search".
    candidate_scores:     {design_id: score} for every BOM candidate evaluated —
                          this is the "before" data for the Idea 2 benchmark chart.
    routed_to_human_review: True if final_score < HUMAN_REVIEW_THRESHOLD after
                            beam search — caller must enqueue for review, this
                            function does not do it itself.
    """
    winner_bom: "ValidatedBOM"
    winner_ladder_id: str
    initial_verification: "VerificationResult"
    final_netlist: list["NetlistEntry"]
    final_score: float
    stage_used: Literal["asha_only", "sa_polish", "beam_search"]
    sa_result: Optional["SAPolishResult"] = None
    beam_result: Optional["BeamSearchResult"] = None
    candidate_scores: dict[str, float] = field(default_factory=dict)
    routed_to_human_review: bool = False


def run_search_controller(
    ladder: "BOMLadder",
    datasheets: list["ComponentDatasheet"],
    subgraph: "DesignSubgraph",
    config: "Config",
    sampler: Optional[TPEBOMSampler] = None,
    expected_topologies: Optional[list[str]] = None,
) -> ASHAResult:
    """Evaluate every BOM candidate, refine the winner, record the outcome.

    Never raises. On total failure returns an ASHAResult with score 0.0 and
    routed_to_human_review=True, mirroring the "never raises" convention used
    throughout src/schematic/.

    expected_topologies: pass None for the MVP — verify_schematic() auto-detects
    from BOM component_type keywords (see structural_verifier._run_layer4).
    Do NOT block this work on intent.goal_topology / KG topology wiring — that's
    a separate, already-tracked gap (PROJECT_CONTEXT.md §9, items 5 and 7).
    """
    ...
```

Fill in the body per §1.1's flow. Concretely:

1. `from src.schematic import synthesize_schematic` at call time inside the function
   (avoid a module-level circular import — `src/schematic/__init__.py` does not
   currently import `search_controller.py`, keep it that way).
2. For each `bom_candidate` in `ladder.candidates`:
   - `schematic = synthesize_schematic(bom_candidate, datasheets, subgraph, config)`
   - `ref_map = build_ref_map(bom_candidate, datasheets)`
   - `verification = verify_schematic(schematic.netlist, ref_map, bom=bom_candidate, expected_topologies=expected_topologies)`
   - stash `(bom_candidate, schematic, ref_map, verification)`
3. Pick the tuple with max `verification.score`. Build `candidate_scores` from all of
   them keyed by `bom_candidate.design_id`.
4. Threshold logic — reuse the constants already defined in `sa_polisher.py`
   (`SA_TRIGGER_THRESHOLD = 0.80`, `SA_DONE_THRESHOLD = 1.00`); do not redefine
   magic numbers locally:
   - `score >= SA_DONE_THRESHOLD` → `stage_used = "asha_only"`, `final_netlist = winner netlist`, `final_score = score`.
   - `SA_TRIGGER_THRESHOLD <= score < SA_DONE_THRESHOLD` → call
     `polish_schematic(netlist, ref_map, winner_bom, initial_verification, expected_topologies)`,
     `stage_used = "sa_polish"`, take `final_netlist`/`final_score` from `SAPolishResult`.
   - `score < SA_TRIGGER_THRESHOLD` → call
     `run_beam_search(netlist, ref_map, winner_bom, initial_verification, expected_topologies)`,
     `stage_used = "beam_search"`, take `final_netlist`/`final_score` from `BeamSearchResult`.
     Set `routed_to_human_review = final_score < HUMAN_REVIEW_THRESHOLD`.
5. If `sampler is not None`: `record_asha_outcome(sampler, winner_bom, final_score)`.
6. Wrap the whole function body in `try/except Exception` per repo convention
   (`sa_polisher.py`, `beam_search_escalation.py`, `synthesize_schematic()` all do
   this) — on failure, log and return a degraded `ASHAResult` with score `0.0` and
   `routed_to_human_review=True`. **Never let this function raise.**

### 1.4 Config additions

Add a small nested config so this is opt-in and every threshold is tunable without
code changes — follow the existing `ParsingConfig` / `KnowledgeGraphConfig` pattern
in `src/config.py`.

New file `src/schematic/_search_controller_schemas.py`:

```python
from pydantic import BaseModel, Field


class SearchControllerConfig(BaseModel):
    enabled: bool = Field(default=False, description="Master switch — off by default")
    max_bom_candidates: int = Field(default=3, ge=1, le=3)
    human_review_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
```

In `src/config.py`: import it, add
`search_controller: SearchControllerConfig = Field(default_factory=SearchControllerConfig)`
to `Config`, add `"search_controller": "search_controller"` to the `field_mapping`
dict in `from_yaml()`. Add a commented-out `search_controller:` block to
`configs/default.yaml` showing the shape.

### 1.5 Wiring point — keep it additive

`src/synthesis/pipeline.py`'s `run_synthesis_pipeline(bom, datasheets, subgraph, config)`
is exercised directly by Team D gate CHECK 2 and CHECK 7 with a single `ValidatedBOM`.
**Do not change that signature or behavior.** Instead:

1. Extract the "netlist → blocks → ERC → confidence → review_flags → SchematicGraph"
   packaging logic currently inside `synthesize_schematic()`
   (`src/schematic/__init__.py` lines ~73–98) into a small internal helper, e.g.
   `_package_schematic_graph(netlist, ref_map, bom, unresolved_pins) -> SchematicGraph`.
   **Before this refactor**, add a characterization test that calls
   `synthesize_schematic()` on a fixed BOM/datasheet fixture and snapshots the
   resulting `SchematicGraph` (or at least `netlist`, `erc_result.passed`,
   `synthesis_confidence`) — run it, confirm green, then refactor, then confirm
   still green with zero diff. This guarantees the refactor is behavior-preserving.
2. Add a new orchestrator function alongside `run_synthesis_pipeline`, e.g.
   `run_synthesis_pipeline_with_search(bom_ladder: BOMLadder, datasheets, subgraph, config, sampler=None) -> tuple[NIR, ASHAResult]`
   in `src/synthesis/pipeline.py`, that calls `run_search_controller()` then reuses
   `_package_schematic_graph()` + the existing `generate_layout_spec()` /
   `build_nir()` calls. This is new code, additive, cannot regress the existing
   function.
3. **Stop here for this handoff.** Wiring `run_synthesis_pipeline_with_search()`
   into `run_intent_pipeline()` / `run_e2e()` behind `config.search_controller.enabled`
   is a good follow-up PR but is not required to demonstrate Idea 1 — the gate test
   and unit tests below are sufficient proof it works end-to-end.

### 1.6 Tests

**`tests/unit/schematic/test_search_controller.py`** — new file, mirror the style of
`tests/unit/schematic/test_beam_search_escalation.py` exactly (same `_pin`/`_net`
helpers, `MagicMock` for `VerificationResult`, `patch(...)` on `verify_schematic`
and `synthesize_schematic` rather than exercising real component-graph logic).
Minimum cases:

- `run_search_controller` returns `ASHAResult` for a 1-candidate `BOMLadder`.
- Winner selection: given 3 candidates with mocked scores `[0.4, 0.9, 0.6]`,
  asserts the winner is the `0.9` candidate and `candidate_scores` has 3 entries.
- Score `>= 1.0` → `stage_used == "asha_only"`, `sa_result is None`, `beam_result is None`.
- Score `0.85` → `stage_used == "sa_polish"`, `polish_schematic` called exactly once
  (patch and assert `call_count`).
- Score `0.5` → `stage_used == "beam_search"`, `run_beam_search` called exactly once.
- Score `0.3` after beam search → `routed_to_human_review is True`.
- `sampler` provided → `record_asha_outcome` called once with the winner BOM and
  final score (patch `src.schematic.search_controller.record_asha_outcome`).
- Malformed/exception-raising `synthesize_schematic` → function still returns an
  `ASHAResult`, never raises (this is the "never raises" contract test every other
  module in `src/schematic/` has — match that pattern).

**`eval/gates/team_d_gate.py`** — extend, don't replace:

- Add `search_controller` and `ASHAResult` to the CHECK 1 import list.
- Add a new **CHECK 9**: build a 1-candidate `BOMLadder` (reuse the `ValidatedBOM`
  fixture already in CHECK 2), call `run_search_controller()`, assert the return
  type is `ASHAResult`. Keep it a smoke check — no GPU, no real model, everything
  through the existing rule-based `synthesize_schematic()`.

Exit criteria for PR 1: `pytest tests/unit/schematic/test_search_controller.py -q`
green, `python eval/gates/team_d_gate.py` still reports 9/9 (or however many checks
after your addition), and `pytest tests/unit -q` full-suite count only goes up, never
down.

---

## 2. Idea 2 — Weak Model + Verifier Self-Improvement Loop ("agent maxing")

### 2.1 Why this needs new inference code, not just wiring

Section 0.2 above is the key fact here: nothing in the schematic-synthesis path
currently calls an LLM. To have a genuine "weak model gets better through retries"
story, Idea 2 introduces the **first** LLM-based netlist generator, then shows that
wrapping a small/fast model in a verifier-scored retry loop closes most of the gap
to the deterministic rule-based synthesizer — without fine-tuning anything. That
before/after gap is the entire deliverable for the AMD submission.

### 2.2 New file: `src/schematic/llm_netlist_proposer.py`

Follow the existing LLM-backend calling convention in
`src/parsing/backends/llm/qwen25_backend.py` and the `InstructorWrapper` pattern in
`src/datasheet/phase3_extract/extractor.py` (Instructor + Pydantic response model
over a local Qwen checkpoint) — do not invent a new client pattern.

```python
"""LLM-based netlist proposer — the 'weak model' half of the self-improvement
loop. Structured-output generation only; scoring is verify_schematic(), never
the LLM itself.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from src.config import Config
    from src.schemas.datasheet import ComponentDatasheet
    from src.schemas.intent import ValidatedBOM
    from src.schemas.nir import NetlistEntry

logger = logging.getLogger(__name__)


class _LLMNetConnection(BaseModel):
    net_name: str
    net_type: str  # "power" | "ground" | "signal" | "differential" | "clock"
    pins: list[dict[str, str]] = Field(
        description='Each item: {"ref": "U1", "pin_number": "3"}'
    )


class _LLMNetlistProposal(BaseModel):
    connections: list[_LLMNetConnection]


@dataclass
class ProposedNetlistResult:
    netlist: list["NetlistEntry"]
    raw_response: str
    confidence: float
    model_used: str
    temperature: float
    parse_succeeded: bool


def propose_netlist_llm(
    bom: "ValidatedBOM",
    datasheets: list["ComponentDatasheet"],
    ref_map: dict,
    config: "Config",
    temperature: float = 0.7,
    feedback: Optional[str] = None,
) -> ProposedNetlistResult:
    """Ask the configured weak model to propose a complete netlist.

    feedback: if provided (a plain-language summary of the previous attempt's
    critical_violations), append it to the prompt as a correction instruction.
    This is the hook the self-improvement loop (§2.3) uses on rounds 2+.

    Never raises. On any failure (model load, parse, timeout) returns
    ProposedNetlistResult with parse_succeeded=False and an empty netlist —
    the caller (run_self_improving_synthesis) treats that as a score-0.0 round
    and continues, exactly like every other "never raises" module here.
    """
    ...
```

Implementation notes for the body:

- Build the prompt from `bom.components` (ref, component_type, specific_part) and,
  per ref, the pin list with `pin_role` from the matching `ComponentDatasheet` in
  `ref_map` (same data `_build_pin_role_lookup()` in `structural_verifier.py`
  already extracts — reuse that helper or a near-copy of it, don't re-derive pin
  roles from scratch).
- System prompt should state the goal explicitly: connect every pin with a role
  (`POWER_IN`, `POWER_OUT`, `GROUND`, `SIGNAL_IN`, `SIGNAL_OUT`, etc. — reuse
  `src.schemas.datasheet.PinRole`) into named nets, one net per electrical node,
  following standard practice (single shared `GND` net, one `VCC`-style net per
  supply rail unless levels differ). Keep the instructions short — this is a small
  model, not a reasoning model.
- Use Instructor's `response_model=_LLMNetlistProposal` against the model at
  `config.get_model_path("weak_netlist_proposer")` (new key — see §2.4).
- Map `_LLMNetlistProposal.connections` → `list[NetlistEntry]` (import from
  `src.schemas.nir`), building `PinRef` per pin. Set `source_rule="llm_proposal"`
  and `net_confidence` from a fixed heuristic (e.g. `0.6`) or the Instructor
  extraction confidence if available.
- Any pin referenced in the BOM/ref_map that the model never placed on a net
  should be logged (not silently dropped) — `structural_verifier` Layer 3 will
  catch missing required pins anyway, but a debug log line here saves debugging
  time later.

### 2.3 New file: `src/schematic/self_improvement_loop.py`

This is the actual "agent maxing" loop — the centerpiece deliverable.

```python
"""Weak-model + verifier self-improvement loop.

Round 0 is the 'before' number for the AMD-submission chart: one weak-model
attempt, no feedback. Every subsequent round feeds the previous round's
critical_violations back into the prompt. This module never trains anything —
all improvement comes from retrying against a deterministic scorer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from src.schematic.llm_netlist_proposer import propose_netlist_llm
from src.schematic.sa_polisher import SA_DONE_THRESHOLD, SA_TRIGGER_THRESHOLD, polish_schematic
from src.schematic.structural_verifier import verify_schematic

if TYPE_CHECKING:
    from src.config import Config
    from src.schemas.datasheet import ComponentDatasheet
    from src.schemas.intent import ValidatedBOM
    from src.schemas.nir import NetlistEntry

logger = logging.getLogger(__name__)

DEFAULT_MAX_ROUNDS: int = 5
DEFAULT_SCORE_THRESHOLD: float = 0.95
DEFAULT_TEMPERATURE_SCHEDULE: list[float] = [0.7, 0.7, 0.9, 0.9, 0.5]
# Later rounds run hotter (more exploration) if still stuck, then cool down
# for a final precise pass — same adaptive-temperature intuition PCBSchemaGen
# used (see Search_controller_decision.md Part 2), applied here per-round
# instead of via a Beta distribution.


@dataclass
class RoundRecord:
    round_index: int
    temperature: float
    score: float
    critical_violation_count: int
    feedback_given: Optional[str]


@dataclass
class SelfImprovementResult:
    rounds: list[RoundRecord]
    best_netlist: list["NetlistEntry"]
    best_score: float
    weak_model_alone_score: float   # round 0 score — the "before" bar
    final_score: float              # best_score, post-loop — the "after" bar
    converged: bool
    sa_polish_applied: bool


def run_self_improving_synthesis(
    bom: "ValidatedBOM",
    datasheets: list["ComponentDatasheet"],
    ref_map: dict,
    config: "Config",
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    temperature_schedule: Optional[list[float]] = None,
    expected_topologies: Optional[list[str]] = None,
) -> SelfImprovementResult:
    """Never raises. Returns the best result seen even on total failure
    (best_score=0.0, empty netlist, converged=False) — same contract as
    every other search-controller-adjacent module.
    """
    ...
```

Body outline:

1. `schedule = temperature_schedule or DEFAULT_TEMPERATURE_SCHEDULE`; pad/truncate
   to `max_rounds`.
2. `feedback = None`; loop `for i in range(max_rounds)`:
   - `proposal = propose_netlist_llm(bom, datasheets, ref_map, config, temperature=schedule[i], feedback=feedback)`
   - `verification = verify_schematic(proposal.netlist, ref_map, bom=bom, expected_topologies=expected_topologies)`
   - record a `RoundRecord`
   - if `i == 0`: stash `weak_model_alone_score = verification.score`
   - track best-so-far `(netlist, score)`
   - if `verification.score >= score_threshold`: break early, `converged = True`
   - build `feedback` for next round from `verification.critical_violations`
     (join `.message` strings, cap at e.g. 5 to keep the prompt short) and
     `verification.lowest_scoring_layer()`
3. After the loop: if `SA_TRIGGER_THRESHOLD <= best_score < SA_DONE_THRESHOLD`,
   call `polish_schematic()` on the best netlist as a free final cleanup pass
   (zero LLM cost) — set `sa_polish_applied = True`, update `best_netlist`/`best_score`
   from the `SAPolishResult`. This is the natural composition point with Idea 1:
   the self-improvement loop's output can also be handed to `run_beam_search()` if
   it lands below `SA_TRIGGER_THRESHOLD` — leave that as a one-line follow-up, not
   required for this PR, but leave a `# TODO(idea-1-composition):` comment marking
   the spot.
4. Wrap in `try/except Exception`, degrade gracefully, never raise.

### 2.4 Config additions

`config/model_versions.yaml` — add:

```yaml
  weak_netlist_proposer:
    name: "Qwen/Qwen2.5-1.5B-Instruct"
    revision: "main"
    quantization: null
    role: "Idea 2 — weak-model netlist proposal for the self-improvement loop"
    validated_prompt_version: "v1.0"
    note: >
      Deliberately smaller than intent_parser (Qwen2.5-7B). The self-improvement
      loop's whole point is showing this weaker model reach a comparable score
      through retries. Same model family as intent_parser to keep the ROCm/
      quantization story (Idea 6) simple — one family, two sizes.
```

`src/config.py` — add `"weak_netlist_proposer": Path("models/Qwen2.5-1.5B-Instruct")`
to the `model_paths` default factory dict.

New `SelfImprovementConfig` (same pattern as `SearchControllerConfig`, §1.4), in
`src/schematic/_search_controller_schemas.py` or a sibling file:
`enabled: bool = False`, `max_rounds: int = 5`, `score_threshold: float = 0.95`.
Wire into `Config` the same way.

### 2.5 The actual deliverable: before/after benchmark

This repo already has a benchmark harness — use it, don't build a parallel one.
`eval/benchmarks/{runner.py, tasks.py, metrics.py, task_schema.py, report_generator.py}`
implements the 15-task Pass@1/Pass@N suite referenced in `PROJECT_CONTEXT.md`'s
changelog (2026-06-27, "Eval" row). Read `eval/benchmarks/task_schema.py` and
`runner.py` before writing anything new.

New file: `eval/benchmarks/agent_maxing_benchmark.py`

- For each task in the existing 15-task set (or a subset — confirm with the team
  which tasks have BOMs simple enough for a 1.5B model to have a chance):
  - **Baseline arm:** `propose_netlist_llm(..., temperature=0.7)` once, score with
    `verify_schematic()`. No retries, no feedback. This is "weak model alone."
  - **Treatment arm:** `run_self_improving_synthesis(...)` with default settings.
    This is "weak model + agent loop."
- Emit a Markdown report via the existing `report_generator.py` conventions, with
  one table: task id, baseline score, treatment score, delta, rounds used,
  converged (Y/N). Add one summary line: mean baseline score vs. mean treatment
  score. **This table is the AMD-submission chart** — literally the one described
  in the pitch deck's Idea 2 slide ("show one chart: weak model alone vs weak
  model plus this loop").
- CLI entry point: `python -m eval.benchmarks.agent_maxing_benchmark --output report.md`,
  matching whatever invocation pattern `runner.py` already uses for the existing
  15-task suite.

### 2.6 Tests

**`tests/unit/schematic/test_llm_netlist_proposer.py`**

- Patch the Instructor/LLM call (do not load real weights in unit tests — match
  the "mocked DB, no live PostgreSQL" convention from `tests/retrieval/test_retrieval.py`).
- Well-formed mock response → `ProposedNetlistResult.parse_succeeded is True` and
  `netlist` has the expected `NetlistEntry` count.
- Malformed/exception-raising mock → `parse_succeeded is False`, empty netlist,
  function does not raise.
- `feedback` argument, when provided, appears in the constructed prompt (assert
  on the mock's call args).
- Prompt includes every `ref` from the BOM (regression guard against silently
  dropping components).

**`tests/unit/schematic/test_self_improvement_loop.py`** — mirror
`test_beam_search_escalation.py`'s style: patch `propose_netlist_llm` and
`verify_schematic` with `MagicMock`, control their return sequence with
`side_effect` to script a "improves over 3 rounds then converges" scenario and a
"never converges, exhausts max_rounds" scenario.

- Scores `[0.3, 0.3, 0.96]` with `max_rounds=5` → stops at round 2 (0-indexed),
  `converged is True`, `rounds` has exactly 3 `RoundRecord` entries.
- Scores that never clear `score_threshold` → runs exactly `max_rounds` rounds,
  `converged is False`.
- `weak_model_alone_score` always equals round-0's score, regardless of later
  rounds.
- Score lands at `0.85` after the loop → `polish_schematic` is called once,
  `sa_polish_applied is True`.
- `feedback_given` on round 0 is `None`; round 1+ is a non-empty string derived
  from round 0's violations.
- Total failure (proposer raises inside the mock) → function still returns
  `SelfImprovementResult`, never raises.

**Benchmark smoke test** — `tests/unit/eval/test_agent_maxing_benchmark.py`: run
`agent_maxing_benchmark.py`'s report-generation path against 2–3 stub tasks with a
fully mocked weak-model backend (no GPU, no real weights — this must run in plain
CI). Assert the output report contains both a baseline and treatment score per task
and the summary delta line.

Exit criteria for PR 2/3: all new unit tests green, `pytest tests/unit -q` count
increases, benchmark smoke test runs without GPU/model weights, and — once real
weights are available on a dev machine — one manual run of
`agent_maxing_benchmark.py` against the real 1.5B model produces `report.md` with a
positive mean delta (treatment > baseline). That report is the artifact to attach
to the AMD submission.

---

## 3. Suggested PR sequence

| PR | Contents | Depends on |
|----|----------|------------|
| 1 | `search_controller.py` + `ASHAResult` + `SearchControllerConfig` + unit tests + Team D gate CHECK 9 | nothing new — only existing modules |
| 2 | Characterization test + `_package_schematic_graph()` refactor of `synthesize_schematic()` (behavior-preserving) | PR 1 merged, existing tests green |
| 3 | `run_synthesis_pipeline_with_search()` in `src/synthesis/pipeline.py` | PR 1 + 2 |
| 4 | `llm_netlist_proposer.py` + config/model registry entries + unit tests | independent of 1–3, can run in parallel |
| 5 | `self_improvement_loop.py` + unit tests | PR 4 |
| 6 | `agent_maxing_benchmark.py` + smoke test + one real GPU run → `report.md` | PR 5, needs model weights downloaded |

PRs 1–3 and 4–5 can be built by two people in parallel — they only share
`structural_verifier.py`, which nobody is modifying. PR 6 is the one that needs an
actual machine with the weak model's weights on it.

---

## 4. Definition of done (mirrors the repo's existing milestone checklist)

```markdown
### Idea 1 + Idea 2 sign-off
- [ ] search_controller.py implemented, ASHAResult defined, never raises
- [ ] SelfImprovementConfig / SearchControllerConfig wired into src/config.py
- [ ] characterization test written BEFORE the synthesize_schematic() refactor,
      confirmed identical output AFTER
- [ ] llm_netlist_proposer.py implemented, never raises on malformed model output
- [ ] self_improvement_loop.py implemented, composes with polish_schematic()
- [ ] pytest tests/unit -q — count strictly greater than baseline, all green
- [ ] python eval/gates/team_d_gate.py — all checks pass including new CHECK 9
- [ ] eval/benchmarks/agent_maxing_benchmark.py produces report.md with a
      positive baseline→treatment delta on real weights
- [ ] README.md / PROJECT_CONTEXT.md updated per the existing milestone protocol
      (documents/architecture/PROJECT_CONTEXT.md §2)
- [ ] documents/decisions/Search_controller_decision.md updated to note
      search_controller.py now exists (it currently says it doesn't)
```

## 5. Open questions to settle before Cursor starts

1. **Weak model choice** — this plan proposes `Qwen2.5-1.5B-Instruct` (same family
   as the existing intent parser, easy story for Idea 6's ROCm work later). Confirm
   the team is fine downloading a second model, or pick an already-available one.
2. **Which of the 15 existing benchmark tasks are in scope** for §2.5 — some may
   need BOMs too complex for a 1.5B model to ever succeed on; worth a quick filter
   pass before the GPU run rather than after.
3. **Config flag names** (`search_controller.enabled`, `self_improvement.enabled`) —
   fine as proposed, but confirm before multiple people start branching config
   changes.
