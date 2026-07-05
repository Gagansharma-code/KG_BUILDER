# ADR-001: Evolve OpenForge Knowledge Graph into Knowledge + Constraint + Topology Layers

**Status:** Accepted
**Date:** 2026-07-05
**Deciders:** Amartya (project lead); reviewed by Claude, Gemini, GLM-5

---

## Context

OpenForge's current Knowledge Graph has 5 layers in one graph (Physics, Design
Recipes, Component Rules, Placement Rules, Methodology Rules), prototyped in
NetworkX with Neo4j as the production target.

A teammate proposed evolving this into a system with three separate,
cooperating graphs — Knowledge Graph (static facts), Constraint Graph
(per-design objectives), and Topology Graph (reusable circuit patterns like
Buck Converter, LDO, PLL) — plus a new "Constraint Propagation Engine" and a
new "Topology Composer" service.

Think of the question this ADR answers as: **do we build three separate filing
cabinets, or add new drawers to the one cabinet we already have?** And for the
new capabilities bundled into the proposal — do we need brand-new machinery, or
can existing machinery (the KG, the ASHA/SA search stack, the intent-parsing
pipeline) be extended to cover them?

**Forces at play, specific to OpenForge:**
- **Non-negotiable:** full provenance traceability (relevant to defense-context
  review and JSS 55555 compliance) — every design decision must be explainable
  after the fact.
- **Non-negotiable:** 699+ passing unit tests as a stability baseline — any
  change must not require tearing up working subsystems.
- **Standing project principle:** simplicity over overengineering (LangGraph and
  Optuna were both previously rejected for adding machinery the actual problem
  didn't need).
- **Standing project principle:** schema fields/capabilities must be "wired
  when added" — no dead-weight additions with nowhere to plug in yet.

Three independent reviews were run against the original proposal (Claude,
Gemini, GLM-5). This ADR reflects where all three converged, resolves the
places they disagreed, and folds in the project lead's explicit prioritization
of decision criteria.

---

## Decision Criteria (agreed before scoring options)

**Hard gate — not traded off against anything:**
Every option must preserve **Determinism & Auditability**. Analogy: a court
case needs the evidence trail, not just the verdict. Anything that can't
explain *why* a component was chosen fails outright, regardless of elegance.

**Ranked trade-off criteria** (set by project lead):
1. **Genuine Capability Gap Evidence** — only fix problems the current system
   can actually be shown not to solve.
2. **Long-Term Scalability** — prefer options that won't need to be rebuilt
   once RF / mixed-signal designs arrive.
3. **Migration Risk / Incrementalism** — prefer changes that can be built and
   tested in isolated, non-coupled steps.
4. **Minimal New Machinery** — prefer extending what exists over building new
   subsystems (lowest priority of the four, by explicit choice).

---

## Decision

Adopt the following architecture. Each row states the decision, the option it
beat, and which criteria drove the call.

### 1. Graph Structure: One graph, not three

**Decision:** Single Neo4j graph. Add new node labels (`:TopologyNode`,
`:ConstraintNode`, `:ComponentClass`) and new relationship types. Do **not**
build three separate graph databases/services.

**Why:** Splitting into three graphs turns a fast in-database traversal (like
following a chain of pointers in one room) into a slow cross-network handoff
(fetch from database A, ship results over the network, re-query database B,
repeat). It also creates a silent-drift risk: if the Topology Graph references
a component class that the Knowledge Graph later renames or restructures,
nothing in a split system notices — in one graph, that broken reference either
resolves correctly or fails loudly, which is what you want.

**All three reviews agreed unanimously.**

---

### 2. Component Hierarchy: Class vs. Instance split

**Decision:** Adopt immediately. Introduce component *classes* (e.g. "Low
Noise LDO") carrying generic requirements (needs input cap, output cap,
thermal plane). Specific ICs (TPS7A20, LT3042, TLV755P) become *instances*
that only override device-specific numbers (current, dropout, noise, package).

**Why:** This is standard object/class inheritance — the same pattern as a
base class in code, where shared behavior lives once and subclasses only
override what's actually different. Removes duplication, requires no new
infrastructure, zero risk to the existing 699 tests if done as a schema
refactor.

**All three reviews agreed unanimously. Highest-confidence, lowest-risk item
in this ADR.**

---

### 3. Constraint Graph Lifecycle: Persist, don't discard

**Decision:** The per-design Constraint Graph is **persisted and versioned**,
not treated as temporary/discardable scratch space, as the original proposal
suggested.

**Why:** If a reviewer later asks "why was this LDO chosen over a switching
alternative?", the answer lives in the constraint decisions that led there.
Discarding them breaks the audit trail — a direct violation of the hard gate.
Storage cost is negligible (kilobytes to low megabytes per design run; Neo4j
handles this at scale without issue). Persisting also *improves* future
analysis: "why was X chosen" becomes a graph traversal instead of re-running
synthesis and hoping it reproduces the same result.

**All three reviews agreed unanimously.**

---

### 4. Constraint Propagation: Embedded interval-constraint solver, rolled out gradually

**Decision:** Build a lightweight, embedded interval/algebraic constraint
solver that runs *before* the ASHA/TPE/SA search stack sees the design space.
Roll it out first against known, specific constraint chains (voltage/dropout
math, thermal budget splits across rails) before trusting it with open-ended
conflict detection across arbitrary constraints.

**What this is not:** a new standalone "Constraint Propagation Engine"
service, and not the search stack's existing pruning under a new name.

**Why:** Both external reviews independently identified a real capability gap
I initially missed — the existing search stack (TPE/ASHA/SA) is good at
*sampling and scoring* candidates, like trying keys in a lock. But some
constraint problems are pure deduction, not search — if output is 3.3V and
dropout is 200mV, the input must be ≥3.5V; no sampling is needed to know that.
Feeding a search algorithm a problem that's actually just algebra wastes
compute discovering dead ends it could have ruled out instantly.

Two implementation shapes were proposed: a small hand-written rule-propagation
layer (~500 lines, cheaper, matches "Minimal Machinery") vs. an embedded
interval/SMT-style solver (more general, matches "Capability Gap Evidence" and
"Long-Term Scalability" better, since it doesn't require hand-writing a new
rule every time a new constraint type appears). Given the project lead ranked
Capability Gap Evidence and Long-Term Scalability above Minimal Machinery, this
ADR selects the **interval-solver direction**, but mitigates its migration risk
by introducing it gradually against a small set of known cases first, rather
than deploying it as a general-purpose solver on day one.

---

### 5. Topology Depth: Parameterized model from day one

**Decision:** Design the Topology layer to capture *parameterized
relationships* between blocks (e.g., "switching loop area scales inversely
with switching frequency," "compensation network complexity scales with
output capacitor ESR") from the start — including for simple topologies like
the LDO, so the pattern is consistent everywhere, not bolted on later only for
complex cases.

**What was considered and not chosen:** A flat, simple version (a topology as
just a named list of blocks, e.g. Buck Converter = Switching Loop + Feedback
Divider + Compensation Network + Bootstrap + Output Filter, with no
parameterization) was the initially recommended path, since the current P1
golden corpus is explicitly scoped to simple analog/power ICs under ~30 pins
and doesn't yet demand parameterized topologies. This is the one point in the
ADR where the project lead explicitly overrode the "evidence-first" instinct in
favor of scalability.

**Why the override:** Analogy — this is choosing to pour a foundation rated
for three floors even though only one floor is being built right now, rather
than a one-floor foundation that would need to be dug up and redone the moment
a second floor (RF / mixed-signal designs) gets added. The project lead
weighted Long-Term Scalability (#2) above Genuine Capability Gap Evidence in
this specific case.

**Honest cost, stated plainly:** the parameterized relationships for complex
topologies (e.g. the Buck Converter's frequency/loop-area scaling) cannot be
fully validated until a real scientist-requested design exercises them. Part
of this schema will exist before there is a concrete test case proving it
correct. This is a conscious, accepted trade — not an oversight.

---

### 6. Execution Context: Active rule-set + weights, not a flat weights table

**Decision:** An execution context (RF, Power, Mixed-Signal) carries both (a) a
set of *which* constraints/DRC rules are active, and (b) weights on those
rules — not just a single weights vector applied to a fixed set of objectives.

**Why:** RF context cares about impedance matching, S-parameter flatness, and
phase noise. Power context cares about efficiency, thermal distribution, and
EMI spectrum. These are genuinely different *dimensions* of evaluation, not the
same dimensions turned up or down — like the difference between changing which
instruments are even in the orchestra, versus just changing the volume on the
same instruments. Building only a weights table now would need to be redone the
moment a second domain (which is already planned) is added — cheap to build
correctly today, expensive to retrofit later.

---

### 7. Topology Composer: Rejected as a standalone service

**Decision:** Do **not** build a new "Topology Composer" service. Instead,
extend the existing intent → BOM pipeline to query the new Topology layer.

**Why:** Composing "USB powered RF spectrum analyzer" into USB Power + UART +
Clock + PLL + RF Front End + ADC is *intent decomposition* — already the job of
the existing intent-parsing pipeline. The Topology layer's job is narrower:
given one sub-requirement, map it to a circuit pattern. Building a separate
service to do both jobs duplicates existing team ownership and reintroduces the
scope-creep pattern the project has already caught and rejected once before
(the multimodal-RAG-with-ReAct proposal).

---

### 8. Migration Phasing: Merge Phases 3–5 into one integrated milestone

**Decision:** The original 5-phase migration plan (1: Component Classes → 2:
Topology Graph → 3: Constraint Graph → 4: BOM gen on constraint solving → 5:
schematic synthesis on topology composition) is revised: **Phases 3, 4, and 5
are merged into a single milestone with internal checkpoints**, rather than
three sequential go/no-go gates.

**Why:** Phase 4 (BOM generation using constraint solving) cannot actually be
validated without Phase 5's topology layer working, because constraints
propagate *through* topologies (e.g. "Noise < 5µVrms" only becomes "requires
Low Noise LDO" once the topology layer exists to make that connection).
Treating them as independently "passable" gates risks declaring a phase done
when it secretly depends on unfinished work — like signing off on a bridge
because one support pillar is poured, without checking whether the deck it's
supposed to hold has been built yet.

**Revised phasing:**
1. **Phase 1:** Component Classes (independent, ship first, low risk)
2. **Phase 2:** Topology Graph, parameterized from the start (independent of
   Phase 3, but should land before Phase 3 work begins)
3. **Phase 3+4+5 (merged milestone):** Constraint Graph → interval-constraint
   solver → BOM-on-constraints → schematic synthesis on topology composition,
   validated together with internal checkpoints rather than separate gates

---

## Trade-off Analysis Summary

| Decision | Capability Gap Evidence | Long-Term Scalability | Migration Risk | Minimal Machinery |
|---|---|---|---|---|
| Single graph | N/A — no gap exists for splitting | Best (extensible via labels) | Lowest risk | Best (no new DB) |
| Class/Instance split | Clear, existing duplication | Good | Very low (schema refactor only) | Best |
| Persist Constraint Graph | Required by audit-trail gate | Good (enables historical analysis) | Low (storage is cheap) | Neutral |
| Interval-constraint solver | **Strong** (deductive gap is real) | **Strong** (scales via variables, not hand-written rules) | Medium (new dependency; mitigated by gradual rollout) | Costs the most here — accepted trade-off |
| Parameterized Topology (day one) | Weak *today* — no current design needs it | **Strong** (avoids future rebuild) | Medium (unvalidated complex cases) | Costs some — accepted trade-off per lead's override |
| Rich Execution Context | Strong (RF vs. Power are different axes, demonstrably) | Strong | Low (still just metadata) | Good |
| Reject Topology Composer service | Strong (duplicated ownership is the actual problem) | Good | Low (no new service to maintain) | Best |
| Merge Phases 3–5 | N/A | Neutral | **Strong** (prevents false-confidence gating) | Neutral |

---

## Consequences

**What becomes easier:**
- Auditing any design decision post-hoc, since the constraint reasoning is
  preserved and queryable, not discarded.
- Adding new component instances (TI, ADI parts) without duplicating
  requirement logic already captured at the class level.
- Adding a second domain context (e.g. Mixed-Signal after RF and Power exist)
  without redesigning the context schema.
- Explaining infeasible designs immediately (constraint solver catches
  mathematically impossible requirement combinations before wasting search
  cycles).

**What becomes harder / needs attention:**
- The interval-constraint solver is a genuinely new dependency in the
  pipeline — it needs its own test coverage, separate from the 699 existing
  tests, before Phase 3+4+5 work begins.
- The parameterized Topology schema will contain untested complex cases
  (e.g. Buck Converter scaling relationships) until a real design exercises
  them — this needs to be tracked explicitly (e.g. in WHATS_LEFT.md) as "schema
  exists, not yet validated," so it isn't mistaken for finished work.
- Phase 3+4+5 being merged means it's a bigger single unit of work to review
  and gate than the original plan — needs clear internal checkpoints so it
  doesn't become an unreviewable monolith.

**What we'll need to revisit:**
- Whether the interval-constraint solver needs to graduate from "known cases
  only" to general-purpose conflict detection, once real scientist prompts
  start hitting cases the initial rollout doesn't cover.
- Whether the parameterized Topology schema's untested complex relationships
  hold up once the first RF or mixed-signal design actually runs through them.

---

## Action Items

1. [ ] Refactor existing KG schema: introduce `ComponentClass` nodes, migrate
   ICs to `HAS_CLASS` relationships, move shared requirements off individual
   instances.
2. [ ] Design `TopologyNode` schema with parameterized relationship support
   (not just flat block lists), starting with LDO and Buck Converter as the
   first two topologies.
3. [ ] Design `ConstraintNode` schema with `design_id` scoping for persistence
   and versioning.
4. [ ] Scope and build the embedded interval-constraint solver against a fixed
   initial rule set (voltage/dropout chains, thermal budget splits) — not
   general-purpose yet.
5. [ ] Define the Execution Context schema (active rule-set + weights) for RF
   and Power contexts as the first two.
6. [ ] Extend the existing intent → BOM pipeline to query the new Topology
   layer directly — no new service.
7. [ ] Update WHATS_LEFT.md to reflect merged Phase 3+4+5 milestone with
   internal checkpoints, replacing the original 5-phase sequential plan.
8. [ ] Flag parameterized-but-unvalidated Topology relationships explicitly in
   documentation so they aren't mistaken for tested, finished work.