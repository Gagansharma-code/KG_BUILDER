# Topology Layer, Constraint Nodes & Interval Solver — Design Notes

**Status:** Implemented (schema + LDO/Buck instances + solver + pipeline wiring).
**Companion code:** `src/knowledge_graph/topology/`, `src/knowledge_graph/constraints/`,
`src/intent/interval_solver.py`.

---

## 1. Reconciliation with existing informal topology usages

The formal representation uses node IDs `topology:<slug>` where `<slug>` is
exactly the string vocabulary the rest of the system already uses. No
translation layer is needed.

| Existing usage | Relationship to the new Topology nodes |
|---|---|
| `TopologyGuess` (`schemas/common.py`) | `TopologyGuess.name` IS a topology slug. A guess with `name="buck_converter"` resolves via `graph.get_node("topology:buck_converter")`. TopologyGuess stays what it is — a *classification result with confidence*; the KG node is the *definition* it points to. |
| `goal_topology` / `goal_topologies` (`schemas/intent.py`) | Same slugs. `intent.goal_topology` resolves the same way. The interval solver already consumes `goal_topology` to select the dropout rule. |
| `ElectricalConstraints.supply_topology` | **Not** a circuit topology (values like `"single_dc"` describe the supply arrangement). Deliberately NOT mapped to Topology nodes — different concept, same word. |
| `topology_slugs` (`retrieval/planner.py`), `get_design_pattern(slug)` / SQL `topology_type` (`kb_client.py`) | Same slug vocabulary. The KB's `design_patterns.topology_type` column and the KG's `topology:<slug>` IDs are two views keyed by the same string. A future task can add a `kb_pattern_id` property to Topology nodes to make the join explicit. |
| `axiom_loader.py` (loads axioms by topology slug) | Same slugs; axiom YAML files could later be attached as properties or GOVERNED_BY edges on Topology nodes. |
| `TOPOLOGY_TEMPLATES` (`structural_verifier.py`) | Template dict keys `"ldo"` and `"buck_converter"` match our slugs. The hardcoded VF2 template graphs are *derivable* from the new structured data: each FUNCTIONAL_BLOCK → template node; PART_OF edges + block `depends_on` properties → template edges. Migration of `_build_topology_templates()` to derive from the KG is explicitly deferred (out of scope per task Section 2) — the new data is a superset of what the templates encode. |

**IMPLEMENTS vs IS_A decision:** a new `KGRelation.IMPLEMENTS` was added.
`IS_A` is taxonomic ("TPS5430 IS_A buck_regulator" — component class
hierarchy, owned by the parallel Component Class/Instance work). A component
*realizing* a circuit pattern is a different relation: "TPS5430 IMPLEMENTS
topology:buck_converter". Overloading IS_A would have made the component
taxonomy and the topology realization indistinguishable in traversal.
`CONSTRAINED_BY` was also added for future edges from design elements to
DESIGN_CONSTRAINT nodes (added now so the relation vocabulary is complete;
no edges of this type are written yet).

## 2. Parameterized relationships — where they live

`KGEdge.constraints` (`dict[str, Any]`) was sufficient — **no KGEdge schema
change.** Scaling relationships are typed `ScalingLaw` Pydantic models
(`topology/_schemas.py`) serialized under `constraints["scaling_laws"]` on
the block→topology PART_OF edge. Queryable (`ScalingLaw.
list_from_edge_constraints(edge.constraints)`), validated on read, and maps
directly onto the Neo4j design's `constraints_json` property (§1.2).

One KGNode change was made: optional scalar `design_id: str | None = None` —
exactly the field NEO4J_BACKEND_DESIGN.md §1.1 anticipated ("any future
scalar field, e.g. design_id … same name, native type"). Backward
compatible (default None; zero existing constructors affected).

## 3. Constraint-module extension decision (Section 0E)

**Reused:** `completion.schemas.Contradiction` (with
`detected_by="rule_checker"`) as the solver's finding format — reporting is
uniform with the Stage 2 contradiction checker.

**Not extended, and why:**
- `intent/constraint_inferrer.py` maps application keywords → constraint
  *strings* feeding `inferred_constraints`. It has no numeric model; interval
  arithmetic doesn't belong in a keyword table.
- `completion/contradiction_checker.py` runs *inside* the Stage 2 completion
  engine on (intent + LLM implied requirements) and is advisory. The solver
  must run *after* Stage 2.5 retrieval and *gate* BOM generation with a hard
  failure — different position in the pipeline, different failure semantics.
  Moving numeric rules there would either run them too early (before
  retrieval) or force the completion engine to become a pipeline gate.

**New code:** `src/intent/interval_solver.py` — two fixed rules
(voltage/dropout chain, thermal budget allocation), `ConstraintConflictError`
naming the exact conflicting constraints, and a defensive never-raise
`check_interval_constraints()` plus a loud `assert_interval_feasible()`.

## 4. Layer-numbering proposal (pre-existing collision flagged)

**Pre-existing inconsistencies (not introduced, not fixed here):**
- `KGNode.layer` docstring says 1=physics, 2=types, 3=instances, 4=recipes,
  5=projects.
- But `kg2_graph_builder.py` writes DESIGN_RECIPE nodes at **layer=2**
  (contradicting "4=recipes"), and DESIGN_METHODOLOGY nodes sit at
  **layer=5** (colliding with "5=projects").
- Ingestion modules use KG-1/KG-2/KG-4 labels that don't map 1:1 to the
  docstring.

**Assignment used by this task (consistent with the canonical docstring):**
- `TOPOLOGY`, `FUNCTIONAL_BLOCK` → **layer 4** (reusable design knowledge —
  the "recipes" tier; a topology is precisely a formalized design recipe).
- `DESIGN_CONSTRAINT` → **layer 5** (project/design-run-specific — the only
  node type that is per-run rather than global knowledge).

**Proposed repo-wide resolution (future task):** treat the docstring as
canonical; migrate `kg2_graph_builder` DESIGN_RECIPE writes from layer 2 → 4;
move DESIGN_METHODOLOGY from 5 → 4 (it is design knowledge, not per-project
data), leaving layer 5 exclusively for design_id-scoped nodes. Requires a
one-time data migration for existing GraphML files and updates to
`find_nodes_by_layer` call sites that assume current numbers.

## 5. Not yet validated against a real design

- The Buck Converter's `ScalingLaw` set (loop area vs f_sw, compensation
  complexity vs ESR, bootstrap cap vs gate charge, L vs f_sw, C_out vs ripple)
  is engineering-reviewed but **has not been exercised by a real
  scientist-requested design** (ADR-001 flag). The same applies to the LDO's
  laws.
- `IMPLEMENTS` edges: `link_component_implements()` exists and is tested, but
  no production code path creates these edges yet.
- `CONSTRAINED_BY` relation: vocabulary only; no writer yet.
- Thermal rule rail derivation currently covers the single primary output
  rail derivable from `ElectricalConstraints`; multi-rail intents need the
  future Execution Context work to enumerate sibling rails.
