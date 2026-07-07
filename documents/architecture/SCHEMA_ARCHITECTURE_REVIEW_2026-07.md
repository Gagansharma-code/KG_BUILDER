# Schema Architecture Review — July 2026

**Status:** Proposed (analysis only — no implementation in this document)
**Date:** 2026-07-07
**Scope:** `KGNodeType`/`KGRelation` (`src/schemas/kg.py`), `DESIGN_CONSTRAINT`
nodes (`src/knowledge_graph/constraints/__init__.py`), typed intent constraint
categories (`src/schemas/intent.py`, `src/schemas/common.py`), topology layer
(`src/knowledge_graph/topology/`), interval solver
(`src/intent/interval_solver.py`).
**Method:** Every claim verified against `src/` directly. Architecture docs
were treated as claims to check, not sources — per the project's documented
doc/code-drift history. Contradictions found are logged in §5.
**Companion:** `SCIENTIFIC_PROMPT_ANALYSIS_LOG.md` Entry 004 (the 10-prompt
sweep that supplies the capability-gap evidence cited below).

Every recommendation is scored the same way ADR-001 scored its decisions —
hard gate first (Determinism & Auditability), then the four ranked criteria:
(1) Genuine Capability Gap Evidence, (2) Long-Term Scalability, (3) Migration
Risk / Incrementalism, (4) Minimal New Machinery. Per the dead-weight axiom,
every proposed field/node names its consumer.

---

## 0. Ground truth this review stands on (verified 2026-07-07)

Three code facts dominate everything below. They are restated once here so
each section doesn't re-derive them:

1. **The typed constraint categories are production-dry.** No code in `src/`
   constructs `ElectricalConstraints`, `ThermalConstraints`, or
   `PerformanceRequirements` — only tests do. `ParsedIntent`
   (`src/intent/parser.py:53-72`) has no such fields; the LLM parse path
   returns `None` by design (`parser.py:224-226`); Stage 2 writes only
   `implied_requirements`/`inferred_constraints` (`src/completion/engine.py:153-158`).
   Consequently the interval solver and `persist_design_constraints` both
   no-op on every real prompt today.
2. **The DESIGN_CONSTRAINT node is one-per-kind-per-design.** Node id is
   `design_constraint:{design_id}:{kind}`, `kind ∈ {electrical, thermal,
   performance, declared}`, with the whole spec serialized as a nested dict
   under `properties["spec"]` (`src/knowledge_graph/constraints/__init__.py:60-75,102-143`).
   On the Neo4j backend, nested properties become one opaque
   `properties_json` string; only `frequency_hz` and `component_type` are
   promoted to queryable scalars (`src/knowledge_graph/backends/neo4j_backend.py:469-475`).
3. **The topology layer is installed nowhere and traversable by nothing.**
   `install_topologies()` has zero production callers (unit tests only), and
   `goal_mapper._START_NODE_TYPES = (COMPONENT_TYPE, DESIGN_RECIPE)`
   (`src/knowledge_graph/query/goal_mapper.py:22`) excludes `TOPOLOGY`. The
   corrected header of `TOPOLOGY_CONSTRAINT_LAYER.md` already says this; it
   is still accurate.

---

## 1. Structural fit for growth — what breaks first

**Question:** Given the current enums and the DESIGN_CONSTRAINT
kind-plus-JSON-blob design, what *category* of future prompt breaks the
structure first?

**Answer: multi-rail / multi-block instrument prompts — and they break it at
a specific line, not hypothetically.**

`_constraint_node()` derives node identity from `(design_id, kind)` alone:

```python
id=f"design_constraint:{design_id}:{kind}"   # constraints/__init__.py:61
```

with exactly four kinds. `graph.add_node()` upserts on id (both backends).
So a design with **two** electrically distinct sub-systems can persist at
most **one** electrical constraint spec — the second silently overwrites the
first.

**Concrete example (Entry 004, Prompt 7):** the TEC controller has a
±500 mA H-bridge drive rail *and* a µA-budget thermistor instrumentation-amp
rail. Both are `ElectricalConstraints`-shaped facts. Persisting both under
`design_constraint:{id}:electrical` keeps whichever was written last — and
the audit trail (the hard gate) then contains a *wrong* record, which is
worse than a missing one. Seven of the ten Entry 004 prompts (any
battery-plus-analog-front-end instrument) have this shape. The failure is
currently masked only by ground-truth fact 1 — nothing populates the specs
at all — which means the first prompt to exercise the constraint persistence
path for real is also the first prompt to corrupt it.

The blob half of the design compounds this: because the spec lives inside
`properties_json`, a reviewer cannot even Cypher-query "all designs whose
supply max was below 4.2 V" to detect the overwrite after the fact.

**Recommended direction (BR-004-7):** keep the node type, change the
granularity — one `DESIGN_CONSTRAINT` node **per constraint**, with
`kind`, a `scope` (block/rail identity, aligning with the sub-block
decomposition of BR-004-8), and the constrained quantity promoted to scalar
properties (the `frequency_hz` promotion at `neo4j_backend.py:473` is the
existing precedent to follow). `knowledge_version` tagging carries over
unchanged.

| | Assessment |
|---|---|
| **Decision** | Per-constraint, block-scoped DESIGN_CONSTRAINT nodes; promote constrained scalars out of the blob |
| **Capability Gap Evidence** | **Strong** — id collision is demonstrable at `constraints/__init__.py:61` against Entry 004 P5/P7; blob unqueryability demonstrable at `neo4j_backend.py:469-475` |
| **Long-Term Scalability** | **Strong** — per-constraint nodes are the unit every future feature (condition scoping §3, DERIVED_FROM edges §2, CONSTRAINED_BY edges) needs to point at |
| **Migration Risk** | Low-medium — write path has one producer (`persist_design_constraints`) and its reader (`get_design_constraints`) has **zero production callers today** (verified), so the format can change without breaking any consumer |
| **Minimal Machinery** | Good — no new node type, no new relation; a granularity change inside one module |

The hard gate is the argument here, not a trade-off: the current design can
silently record false constraint history for multi-rail designs.

---

## 2. Estimation/output layer — minimal graph representation

**Question:** the minimal schema addition to represent "predicted output
metric" as distinct from "input constraint," satisfying the audit-trail gate.
(Computation itself out of scope.)

**Verified starting point:** no representation exists in any direction —
`KGNodeType` has nothing output-shaped, `src/analysis/` does not exist,
`NoiseAnalysisResult` (Entry 001 BR-001-6) was never built, and
`ValidatedBOM`/`DesignSubgraph` have no metric fields. All ten Entry 004
prompts request estimates (≥14 metric kinds), so this is the single most
demanded missing capability in the log.

**Proposal — two enum members, nothing else new:**

1. `KGNodeType.PREDICTED_METRIC` — layer 5, `design_id`-scoped (the existing
   `KGNode.design_id` scalar already covers this; no KGNode change).
   Properties, with the queryables promoted as scalars per the
   `frequency_hz` precedent: `metric_kind` (e.g. `"battery_life_h"`,
   `"cmrr_db"`, `"phase_noise_dbc_hz"`), `value`, `unit`, `condition`
   (structured, per §3), `method` (which estimator produced it, versioned),
   and `knowledge_version` (reuse `knowledge_version(graph)` exactly as
   DESIGN_CONSTRAINT nodes do — same tag, same function, no new scheme).
2. `KGRelation.DERIVED_FROM` — edges from the PREDICTED_METRIC node to every
   input that produced it: the DESIGN_CONSTRAINT nodes (§1 granularity makes
   these pointable), the COMPONENT_INSTANCE nodes whose datasheet parameters
   fed the estimate, and the TOPOLOGY node whose formula was applied.
   `KGEdge.constraints` (already `dict[str, Any]`) carries the per-input
   contribution (e.g. `{"contribution": "johnson_noise", "share": 0.62}`) —
   the same pattern `ScalingLaw` already uses on PART_OF edges.

**Audit trail, concretely:** "trace this predicted 4.2 nA/√Hz back" becomes
one traversal — `MATCH (m:PredictedMetric {design_id: $id, metric_kind:
"current_noise_na_rthz"})-[:DERIVED_FROM]->(input) RETURN input` — instead
of re-running an estimator and hoping for reproduction. This is the same
argument ADR-001 §3 made for persisting the constraint graph.

**Why a node and not a property on something existing:** an input constraint
is *asserted by the user* and exists before synthesis; a predicted metric is
*computed by the system* and exists only after — different lifecycle,
different provenance obligations (a metric must name its method and inputs;
a constraint must name its prompt text). Folding metrics into
DESIGN_CONSTRAINT would erase exactly the input-vs-derived distinction the
reviewer needs. This mirrors the ADR's IMPLEMENTS-vs-IS_A reasoning: don't
overload one relation with two meanings that traversal must later untangle.

**Named consumers (dead-weight axiom):** (a) the DocumentationGenerator
estimate section — BR-001-7, OPEN since Entry 001, currently blocked on
having nothing to render; (b) the review gate: a PREDICTED_METRIC that
violates a DESIGN_CONSTRAINT of the same quantity (predicted 620 µA vs
constraint <250 µA) is precisely the check the interval solver cannot do
alone, and gives reviewers a machine-checkable pass/fail; (c) the audit
query above.

| | Assessment |
|---|---|
| **Decision** | Add `PREDICTED_METRIC` node type + `DERIVED_FROM` relation; no new subsystem, no KGNode/KGEdge model changes |
| **Capability Gap Evidence** | **Strong** — 10/10 Entry 004 prompts + GAP-001-D open since Entry 001; nothing exists in any form |
| **Long-Term Scalability** | **Strong** — `metric_kind` is data, not schema; CMRR today, S-parameters later, zero further enum changes |
| **Migration Risk** | Low — purely additive enum members; str-Enums serialize; no existing node/edge changes shape |
| **Minimal Machinery** | Good — two enum members and a writer module; deliberately rejects a heavier "results database" or per-metric node types |

---

## 3. Frequency-/condition-scoped constraints — field, not node type

**Question:** new field on the existing DESIGN_CONSTRAINT spec, or a
distinct node type? Argued the way the interval-solver decision was argued.

**Verified starting point:** `NoiseSpec` already has `bandwidth_hz` and
`measurement_condition: Optional[str]` (`src/schemas/common.py:24-30`) — so
"noise at 1 kHz" is *partially* representable today (unpopulated, and the
condition is an opaque string). Nothing equivalent exists for gain,
impedance, or phase-noise conditions, and `FrequencySpec`
(`intent.py:41-53`) cannot hold a range at all ("10 Hz–100 kHz selectable",
Entry 004 P9).

**Recommendation: extend the spec models with one shared structured
sub-model; do NOT add a node type.**

Sketch (illustrative, not implementation):

```python
class ConditionScope(BaseModel):        # shared by Noise/Gain/…Spec models
    parameter: str                      # "frequency_hz", "offset_hz", "temp_c"
    at: Optional[float] = None          # point condition ("at 1 kHz")
    min: Optional[float] = None         # range condition ("10 Hz–100 kHz")
    max: Optional[float] = None
    raw_text: str
```

A condition is a *qualifier on a constraint*, not an entity with its own
identity, lifecycle, or relationships. That is the test the ADR applied when
it rejected the standalone Topology Composer (§7: don't build a new thing
whose job an existing thing already owns) and accepted the interval solver
(§4: build new machinery only where a genuinely different capability —
deduction vs search — exists). A condition node would add a traversal hop on
every constraint read, and given ground-truth fact 2 (blob storage), it
would buy zero queryability that scalar promotion on the per-constraint node
(§1) doesn't already buy more cheaply.

Two existing precedents support the field-shape: `ScalingLaw.condition`
(free string — `topology/_schemas.py:47-50`) shows conditions already live
*inside* payloads here, and `NoiseSpec.bandwidth_hz` shows the schema
already started down this road for one spec type. This proposal makes that
road structured and uniform instead of per-spec ad hoc.

**Named consumers:** the interval solver (a condition-scoped constraint must
not be compared against an unconditioned bound — Rule 1 today would happily
compare a 1 kHz noise number against a broadband one if both were populated);
the §2 review-gate comparison (a PREDICTED_METRIC is only comparable to a
constraint whose `ConditionScope` matches); component selection (datasheet
noise is specified at datasheet conditions — `ElectricalParameter.conditions`
already exists on the P1 side, so this creates the matching key).

| | Assessment |
|---|---|
| **Decision** | Structured `ConditionScope` sub-model on spec models + range support in `FrequencySpec`; reject a new node type |
| **Capability Gap Evidence** | Real but partial — 5/10 Entry 004 prompts; NoiseSpec shows the schema already half-committed |
| **Long-Term Scalability** | Good — `parameter` is open vocabulary; RF offsets and temperature conditions need no new schema |
| **Migration Risk** | Very low — additive optional fields; all construction sites unaffected (and per fact 1, there are no production construction sites yet — the cheapest possible moment to change shape) |
| **Minimal Machinery** | **Best of the options** — no node type, no relation, one sub-model |

Sequencing note: this lands *after* §1's granularity fix, so conditions are
promoted as scalars on per-constraint nodes rather than buried deeper in the
blob.

---

## 4. Protection/safety constraints — new structured field, mapped to existing FUNCTIONAL_BLOCK machinery

**Question:** new field vs new node type vs already-representable-and-unused?

**Verified starting point — all three at once, which is the finding:**
- *Already representable and unused:* `ThermalConstraints.kelvin_sensing_required`
  and `ElectricalConstraints.polarity_generation_required` exist
  (`intent.py:130,139`) with **no writer and no reader anywhere in src/**
  (verified by grep). These are pre-existing dead-weight fields — the
  project's own axiom, already violated in the current schema.
- *Not representable at all:* reverse-current protection, ESD, thermal
  shutdown, soft-start, EMI filtering have no field anywhere.
- *Not detected regardless:* zero protection keywords in the rule-based
  parser or `constraint_inferrer` (verified — Entry 004 GAP-004-G), so even
  the two existing booleans could never be set.

**Why booleans-per-behavior is the wrong shape:** Entry 004 alone would
demand eight new booleans, each needing parser wiring, and none able to
carry parameters ("reverse-current protection" on a 100 mA source vs an
80 mA laser driver are different circuits). Boolean-per-behavior is the flat
weights table the ADR §6 rejected: it hardcodes today's list of dimensions.

**Recommendation:**

1. One typed list on the intent —
   `protection_requirements: list[ProtectionRequirement]` where
   `ProtectionRequirement` has `kind` (open string vocabulary:
   `"reverse_current"`, `"reverse_polarity"`, `"esd"`, `"thermal_shutdown"`,
   `"soft_start"`, `"emi_input_filter"`, `"kelvin_sensing"`), optional
   numeric params, and `raw_text` provenance — replacing, not joining, the
   two dead booleans (deprecate them in the same change; keeping both would
   double-book the same fact).
2. At the KG level, **no new node type**: a protection behavior *is a
   required functional block* — exactly what `FUNCTIONAL_BLOCK` +
   `KGRelation.REQUIRES` already model. Persistence writes the requirement
   as a per-constraint DESIGN_CONSTRAINT node (§1) plus, once topologies are
   traversable (BR-004-4), a REQUIRES edge toward the matching
   `functional_block:*` node so synthesis must either resolve it or hit the
   review gate.

**Named consumers:** (a) BOM generation / topology composition — each
`ProtectionRequirement` must resolve to a block or produce a
`review_required` entry, making a silently-dropped safety feature
structurally impossible; (b) the §2 audit trail (a reviewer asks "where is
the reverse-current protection the prompt demanded?" and gets a node or a
flagged absence); (c) the Stage 2 rule checker, which already fires
bypass-cap warnings (Entry 003 smoke test) and is the natural place to warn
on unresolved protection asks.

**Safety framing:** for the other gaps, dropping an ask degrades quality;
here it produces a design *missing a safety feature the prompt explicitly
required*, with no record it was ever asked for. Under the hard gate this is
the most severe representability finding in this review despite being the
cheapest to fix.

| | Assessment |
|---|---|
| **Decision** | Typed `protection_requirements` list on intent; map to existing FUNCTIONAL_BLOCK/REQUIRES at KG level; deprecate the two dead booleans; reject both boolean-per-behavior and a new node type |
| **Capability Gap Evidence** | **Strong** — 6/10 Entry 004 prompts carry safety asks that are provably dropped today |
| **Long-Term Scalability** | Good — `kind` is vocabulary, not schema; parameters per kind |
| **Migration Risk** | Low — additive field with default `[]`; boolean deprecation touches zero callers (they have none) |
| **Minimal Machinery** | Good — one sub-model + reuse of FUNCTIONAL_BLOCK/REQUIRES; no new node or relation types |

---

## 5. Where the real code contradicts the docs

Logged in the same spirit as the "Topology KG install is NOT wired"
correction in `TOPOLOGY_CONSTRAINT_LAYER.md`. Verified 2026-07-07.

1. **Typed v2 categories are presented as working; they are unreachable.**
   `documents/decisions/01_INTENT_PARSING_SCHEMA.md` ("What Version 2
   Produces for Prompt 1", and "The intent parser produces both
   simultaneously during the transition period") describes populated
   `performance`/`electrical`/`thermal` output. In code: no production
   constructor exists for any of the three (grep of `src/`); the LLM path is
   a stub returning `None` (`parser.py:224-226`); `ParsedIntent` lacks the
   fields entirely. Every downstream consumer of these fields — interval
   solver rules 1–2, `persist_design_constraints`'s
   electrical/thermal/performance candidates,
   `contradiction_checker`'s `intent.electrical.supply_topology` read —
   is production-dead code today.
2. **`TOPOLOGY_CONSTRAINT_LAYER.md`'s "interval solver … wired into
   `run_intent_pipeline()`" overstates in the same way.** The call site is
   real (`src/intent/pipeline.py:116`) but by (1) the solver cannot fire on
   any real parsed prompt — it is wired and vacuous. The doc's own N3/N4
   corrections stopped one level too early.
3. **`_typed_constraints_as_strings` is dead-by-construction.**
   `parser.py:143-171` reads `parsed.electrical` / `.thermal` /
   `.reliability` / `.manufacturing` off `ParsedIntent`, which has none of
   those attributes; every `getattr(…, None)` silently yields `None`. The
   function only ever passes through `explicit_constraints`. (Already
   half-noted as item 9 in `CURRENT_REPO_MAP.md`; the stronger fact is that
   the typed branch can never execute.)
4. **`decisions/01`'s `ImprovedIntentDict` retains `explicit_constraints`
   "for backward compatibility"; the real one has no such field**
   (`src/schemas/intent.py` — absent; tests enforce absence per
   `CURRENT_REPO_MAP.md`). The decisions doc is stale against its own
   implementation; anyone building the missing parser from that doc would
   produce a schema violation.
5. **`decisions/01`'s `DesignRequest` includes `"python_gui"`/`"firmware"`
   literals; the real `DesignRequest` (`src/schemas/common.py:72-76`) has
   only the seven in-scope literals** — out-of-scope asks moved to
   `OutOfScopeRequest`. Same doc, same staleness.
6. **Layer numbering remains contradictory in live code.** `kg.py`'s
   canonical docstring says layer 4 = recipes, but `kg2_graph_builder.py`
   still writes `DESIGN_RECIPE` at `layer=2` (verified in the builder's
   constructor, "Returns: KGNode with layer=2"), while the topology library
   writes layer 4. `TOPOLOGY_CONSTRAINT_LAYER.md` §4 flagged this as
   pre-existing; still unfixed — any `find_nodes_by_layer(4)` consumer sees
   topologies but not recipes.
7. **The living log's own bookkeeping:** the analysis task that produced
   this review asked for "Entry 003," but Entry 003 was already assigned
   (2026-06-21 Stage 2 smoke test). Logged as Entry 004 to honor the
   document's "never edit past entries" rule.
8. **Confirmed still-accurate corrections** (no drift found — stated for
   completeness): topology install unwired + `goal_mapper` TOPOLOGY
   exclusion (`goal_mapper.py:22`); `CONSTRAINED_BY` as vocabulary-only with
   no writer; `IMPLEMENTS` writer existing but production-uncalled;
   `ElectricalConstraints.supply_topology` deliberately not a circuit
   topology.

---

## Recommendation summary (ADR-001 trade-off matrix format)

| Recommendation | Capability Gap Evidence | Long-Term Scalability | Migration Risk | Minimal Machinery |
|---|---|---|---|---|
| §1 Per-constraint, block-scoped DESIGN_CONSTRAINT nodes | Strong (id collision at `constraints/__init__.py:61`; 7/10 prompts) | Strong (unit every later feature points at) | Low-medium (writer has one producer, reader has zero callers) | Good (no new types) |
| §2 PREDICTED_METRIC + DERIVED_FROM | Strong (10/10 prompts; GAP-001-D open since Entry 001) | Strong (metric_kind is data) | Low (additive enums) | Good (two enum members) |
| §3 ConditionScope field, not node type | Real, partial (5/10; NoiseSpec precedent) | Good (open parameter vocabulary) | Very low (no production constructors exist yet) | Best |
| §4 protection_requirements → FUNCTIONAL_BLOCK/REQUIRES | Strong (6/10 safety asks provably dropped) | Good (kind is vocabulary) | Low (additive; dead booleans have no callers) | Good (reuses existing block machinery) |

**Sequencing dependency, stated once:** none of §§1-4 pays off until
Entry 004's two WIRING gaps close — typed-constraint population (BR-004-1)
and topology install/traversal (BR-004-4). Schema work done before those
would be dead weight by the project's own axiom; this review therefore
recommends the wiring items as the gate for starting any of the above.
