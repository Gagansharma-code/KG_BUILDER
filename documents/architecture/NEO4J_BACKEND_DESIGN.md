# NEO4J_BACKEND_DESIGN.md — Neo4j GraphBackend Design (Implementation Spec)

**Status:** Design only. No Neo4j driver or Cypher execution code exists in `src/`.
**Implements:** `GraphBackend` interface at `src/knowledge_graph/backends/_interfaces.py`
**Target class:** `src.knowledge_graph.backends.neo4j_backend.Neo4jGraphBackend`
**Deployment constraint:** **Self-hosted Neo4j only (Community or Enterprise edition). Neo4j Aura is explicitly out of scope — OpenForge is air-gapped at runtime and must never depend on a cloud-hosted database.**

This document is a mechanical-translation spec: the implementer should not
need to make architectural decisions.

---

## 1. Field/Type Mapping

### 1.1 KGNode → Neo4j node

Every `KGNode` becomes one Neo4j node with **two labels**:

1. The static label `:KGNode` (enables whole-graph operations and uniqueness constraint)
2. A dynamic label derived from `node_type.value` in PascalCase (enables label-indexed type scans)

| KGNodeType value | Neo4j label |
|---|---|
| `physics_concept` | `:PhysicsConcept` |
| `component_type` | `:ComponentType` |
| `component_instance` | `:ComponentInstance` |
| `design_recipe` | `:DesignRecipe` |
| `electrical_property` | `:ElectricalProperty` |
| `placement_rule` | `:PlacementRule` |
| `routing_rule` | `:RoutingRule` |
| `design_methodology` | `:DesignMethodology` |
| `net_type` | `:NetType` |
| `standard` | `:Standard` |
| `pin` | `:Pin` |
| *(any future member)* | PascalCase of `value` — **compute mechanically** (`"".join(w.capitalize() for w in value.split("_"))`), never from a hardcoded table, so parallel schema work (e.g. Topology/Constraint node types) is accommodated without touching this backend |

**KGNode field → property mapping:**

| KGNode field | Neo4j property | Type | Indexed? |
|---|---|---|---|
| `id` | `id` | string | **UNIQUE constraint** (see 1.4) |
| `node_type` | `node_type` | string (enum value) | yes (also encoded as label) |
| `layer` | `layer` | integer | yes (range index) |
| `label` | `label` | string | yes (text index, for goal_mapper matching) |
| `properties` | `properties_json` | string (JSON-serialized) | no |
| `source` | `source` | string | no |
| `confidence` | `confidence` | float | no |
| `extraction_method` | `extraction_method` | string (enum value) | no |
| `created_at` | `created_at` | string (ISO 8601) | no |
| *(any future scalar field, e.g. `design_id` from parallel Constraint work)* | same name, native type | — | add index only if a query filters on it |

**Why `properties_json` as a JSON string:** `KGNode.properties` is
`dict[str, Any]` with nested values. Neo4j properties cannot hold nested
maps. Serializing the whole dict to one JSON string preserves round-trip
fidelity with the Pydantic model (the same approach GraphML storage uses
today). The two `properties` keys that queries actually filter on today are
promoted to first-class Neo4j properties at write time:

- `properties.frequency_hz` → also written as `frequency_hz` (float) — used by `_apply_frequency_filter` in `query/__init__.py`
- `properties.component_type` → also written as `prop_component_type` (string) — used by `semantic_search.search_components` filter

On read, the backend reconstructs `KGNode.properties` **only** from
`properties_json`; the promoted properties are write-time duplicates for
query performance and are never read back into the model.

### 1.2 KGEdge → Neo4j relationship

Every `KGEdge` becomes one relationship whose **type is the uppercase of
`relation.value`** (`requires` → `:REQUIRES`, `connects_to` → `:CONNECTS_TO`,
etc. — mechanical uppercase, no hardcoded table, same forward-compatibility
rule as node labels).

| KGEdge field | Relationship property | Type |
|---|---|---|
| `source_id` / `target_id` | *(implicit in topology)* | — |
| `relation` | `relation` | string (also encoded as rel type) |
| `constraints` | `constraints_json` | string (JSON-serialized) |
| `source_document` | `source_document` | string |
| `confidence` | `confidence` | float |
| `layer` | `layer` | integer |
| *(any future field, e.g. `source_tier`, `verified`)* | same name, native type | — |

**Multigraph note:** NetworkX `DiGraph` permits at most one edge per
(source, target) pair — adding a second overwrites the first. Neo4j permits
parallel relationships. To preserve current behavior exactly, `add_edge`
MERGEs on `(source)-[r]->(target)` *regardless of relationship type* is NOT
expressible in one Cypher MERGE; instead the implementer must first
`DELETE` any existing relationship between the pair, then `CREATE` the new
one (see 2.2). This mirrors NetworkX overwrite semantics. If future schema
work wants parallel edges, that is a deliberate behavior change to make
*then*, not now.

### 1.3 What is NOT stored

- `DesignSubgraph` is a query *result*, never persisted.
- FAISS semantic-search index remains file-based and outside Neo4j.

### 1.4 Constraints and indexes (created at backend startup, idempotent)

```cypher
CREATE CONSTRAINT kgnode_id IF NOT EXISTS
FOR (n:KGNode) REQUIRE n.id IS UNIQUE;

CREATE INDEX kgnode_layer IF NOT EXISTS
FOR (n:KGNode) ON (n.layer);

CREATE INDEX kgnode_node_type IF NOT EXISTS
FOR (n:KGNode) ON (n.node_type);

CREATE TEXT INDEX kgnode_label IF NOT EXISTS
FOR (n:KGNode) ON (n.label);
```

All four run in `Neo4jGraphBackend.__init__` via a single startup routine.
They are Community-edition-compatible (no property existence constraints,
which are Enterprise-only — the Pydantic layer already guarantees field
presence before write).

---

## 2. Query Design — one Cypher pattern per GraphBackend method

Parameters use Neo4j driver `$param` syntax. All queries are documented
snippets, not executable code.

### 2.1 `add_node(node)` — upsert (matches NetworkX silent-update semantics)

```cypher
MERGE (n:KGNode {id: $id})
SET n = {
      id: $id, node_type: $node_type, layer: $layer, label: $label,
      properties_json: $properties_json, source: $source,
      confidence: $confidence, extraction_method: $extraction_method,
      created_at: $created_at,
      frequency_hz: $frequency_hz,            // nullable promoted prop
      prop_component_type: $prop_component_type // nullable promoted prop
    }
WITH n
CALL apoc.create.setLabels(n, ['KGNode', $dynamic_label]) YIELD node
RETURN node.id
```

**If APOC is unavailable** (keep the deployment dependency-free): replace the
`setLabels` call with a per-`node_type` query string built by Python f-string
interpolation of the *validated* PascalCase label (labels cannot be
parameterized in plain Cypher). The label string is derived from a
`KGNodeType` enum member, never from user input, so injection is not
possible. **Recommended: the f-string approach; do not require APOC.**

### 2.2 `add_edge(edge)` — with NodeNotFoundError + overwrite semantics

Step 1 — existence check (raise `NodeNotFoundError(missing_id)` if either count is 0):

```cypher
MATCH (s:KGNode {id: $source_id}) RETURN count(s) AS found
```

Step 2 — delete any existing relationship (NetworkX overwrite semantics), then create:

```cypher
MATCH (s:KGNode {id: $source_id})-[r]->(t:KGNode {id: $target_id})
DELETE r
```

```cypher
MATCH (s:KGNode {id: $source_id}), (t:KGNode {id: $target_id})
CREATE (s)-[r:REQUIRES {   // rel type interpolated from validated enum
    relation: $relation, constraints_json: $constraints_json,
    source_document: $source_document, confidence: $confidence,
    layer: $layer
}]->(t)
```

All three statements run in **one explicit transaction** so the
check-delete-create sequence is atomic.

### 2.3 `get_node(node_id)` — never raises

```cypher
MATCH (n:KGNode {id: $node_id}) RETURN n
```

Zero rows → return `None`. One row → rebuild `KGNode` from properties
(`properties` from `properties_json` via `json.loads`).

### 2.4 `get_edges_from(node_id, relation, min_confidence)`

```cypher
MATCH (s:KGNode {id: $node_id})-[r]->(t:KGNode)
WHERE ($relation IS NULL OR r.relation = $relation)
  AND r.confidence >= $min_confidence
RETURN s.id AS source_id, r, t.id AS target_id
```

### 2.5 `get_edges_to(node_id, relation)`

```cypher
MATCH (s:KGNode)-[r]->(t:KGNode {id: $node_id})
WHERE ($relation IS NULL OR r.relation = $relation)
RETURN s.id AS source_id, r, t.id AS target_id
```

### 2.6 `get_neighbors(node_id, relation, min_confidence)`

```cypher
MATCH (s:KGNode {id: $node_id})-[r]->(t:KGNode)
WHERE ($relation IS NULL OR r.relation = $relation)
  AND r.confidence >= $min_confidence
RETURN t
```

### 2.7 `node_exists(node_id)`

```cypher
MATCH (n:KGNode {id: $node_id}) RETURN count(n) > 0 AS exists
```

### 2.8 `find_nodes_by_type(node_type)`

```cypher
MATCH (n:KGNode) WHERE n.node_type = $node_type RETURN n
```

(Property-indexed; avoids dynamic-label interpolation on the read path.)

### 2.9 `find_nodes_by_layer(layer)`

```cypher
MATCH (n:KGNode) WHERE n.layer = $layer RETURN n
```

### 2.10 `stats()`

```cypher
MATCH (n:KGNode)
RETURN n.layer AS layer, count(n) AS node_count
```
```cypher
MATCH (:KGNode)-[r]->(:KGNode)
RETURN r.layer AS layer, count(r) AS edge_count
```

Python assembles the `node_count`/`edge_count`/`nodes_layer_N`/`edges_layer_N`
dict from these two grouped results (missing layers → 0).

### 2.11 `save(path)` / `load_into(path)`

Neo4j is itself the persistent store, so these become **export/import to the
existing GraphML format** for interoperability and backup:

- `save(path)`: run 2.8-style full scans (`MATCH (n:KGNode) RETURN n`;
  `MATCH (s)-[r]->(t) RETURN s.id, r, t.id`), rebuild `KGNode`/`KGEdge`
  Pydantic objects, and write GraphML **reusing the exact serialization code
  in `NetworkXGraphBackend.save`** (extract that GraphML write/read into a
  shared module-level helper — `backends/_graphml_io.py` — during
  implementation so the format has one owner).
- `load_into(path)`: parse GraphML with the shared helper, then bulk-write
  with batched `UNWIND`:

```cypher
UNWIND $nodes AS row
MERGE (n:KGNode {id: row.id})
SET n += row.props
```
```cypher
UNWIND $edges AS row
MATCH (s:KGNode {id: row.source_id}), (t:KGNode {id: row.target_id})
CREATE (s)-[r:__DYNAMIC__]->(t)   // per-relation-type batches, see 2.2 note
SET r += row.props
```

Batch size: 1,000 rows per transaction.

### 2.12 The query `query_graph()` needs

`query_graph()` today composes: `goal_mapper` (label keyword match over
`find_nodes_by_type`), `traversal.bfs_traverse` (depth- and
confidence-bounded BFS via repeated `get_edges_from`), frequency filter, and
`result_builder`. The backend interface methods above are sufficient — the
Python BFS keeps working unchanged against `Neo4jGraphBackend`.

**Optimization (implement, but keep the Python path as fallback):** a single
Cypher traversal replacing the N+1 `get_edges_from` loop:

```cypher
MATCH (start:KGNode) WHERE start.id IN $start_ids
MATCH path = (start)-[rels*1..$max_depth]->(n:KGNode)
WHERE ALL(r IN rels WHERE r.confidence >= $min_edge_confidence)
WITH n, path,
     reduce(conf = 1.0, r IN relationships(path) | conf * r.confidence)
       AS path_confidence
RETURN n.id AS node_id,
       max(path_confidence) AS best_confidence,
       [r IN relationships(path) | r] AS edges
```

Note: `max(path_confidence)` per node reproduces the "best path confidence"
semantics of `traversal.bfs_traverse`. Variable-length upper bound cannot be
a parameter in Cypher — interpolate the integer `max_depth` (config-sourced,
validated `int`) into the query string.

---

## 3. Migration Strategy — recommendation: (b) one-time cutover

**Recommended: one-time cutover with a migration script. Dual-write is rejected.**

Rationale:

1. The KG is a **build-time artifact** in OpenForge: it is populated by
   ingestion runs (pre-deployment, internet-connected phase) and read at
   design time (air-gapped runtime). There is no live user data and no
   uptime requirement during migration — the classic reasons for dual-write
   do not exist here.
2. Dual-write doubles every ingestion path's failure modes and would require
   consistency reconciliation between two stores that can drift silently.
3. The registry pattern already gives a clean rollback: set
   `knowledge_graph.backend: networkx` in config and the system runs exactly
   as today.

**Migration script** (`scripts/migrate_graphml_to_neo4j.py`, written in the
implementation task):

```
GraphML file (config.graph_path)
  → NetworkXGraphBackend.load()          # existing, tested reader
  → iterate nodes → Neo4jGraphBackend.add_node()   (batched UNWIND, 2.11)
  → iterate edges → Neo4jGraphBackend.add_edge()   (batched, per rel type)
  → verify: stats() on both backends must be identical
  → verify: N random node IDs round-trip to equal KGNode models
```

**Fate of existing GraphML files under cutover:** they are kept, untouched,
as the rollback artifact. `NetworkXGraphBackend` and its GraphML format
remain fully supported (it stays the default backend and the test baseline).
`Neo4jGraphBackend.save(path)` continues to emit GraphML (2.11), so periodic
GraphML snapshots double as backend-neutral backups. Nothing ever deletes a
GraphML file.

---

## 4. Air-Gap Confirmation

- This design assumes **self-hosted Neo4j Community or Enterprise edition
  exclusively**, reachable at `config.neo4j_uri` (already present in
  `src/config.py`, default `bolt://localhost:7687` per its docstring
  example). **Neo4j Aura is not supported, not referenced, and must not be
  added** — runtime is air-gapped with no outbound network access.
- Deployment implication: a Neo4j server image must ship with the
  pre-deployment bundle. Add `open_forge/docker/neo4j/` containing a
  `docker-compose.yml` pinning an exact self-hosted image version (pull at
  build time, load from local registry/tarball at deploy time), with volumes
  for `/data` and auth via environment file. No plugin dependencies (design
  avoids APOC per 2.1).
- The `neo4j` Python driver becomes a new pinned dependency **only when the
  implementation task lands**; it must not be imported at module top level in
  `neo4j_backend.py` (follow the lazy-import convention used by
  `NetworkXGraphBackend.__init__` for networkx) so that networkx-only
  deployments never need the driver installed.

---

## 5. Registry Wiring

One-line change in `src/knowledge_graph/backends/_registry.py`, following
the exact `LAYOUT_DETECTOR_REGISTRY` convention:

```python
GRAPH_BACKEND_REGISTRY: dict[str, str] = {
    "networkx": (
        "src.knowledge_graph.backends.networkx_backend.NetworkXGraphBackend"
    ),
    "neo4j": (
        "src.knowledge_graph.backends.neo4j_backend.Neo4jGraphBackend"
    ),
}
```

Selection via config (`configs/default.yaml`):

```yaml
knowledge_graph:
  backend: neo4j        # default remains "networkx"
```

`GraphBackendRegistry.__init__` already validates the name against the
registry and raises `ValueError` with the valid-options list on a miss —
adding the registry entry is the *only* wiring needed. `Neo4jGraphBackend`
must accept `config` in its `__init__` (the registry's
`_instantiate_backend` passes it automatically when the signature declares
it), from which it reads `config.neo4j_uri` plus auth credentials
(`OPENFORGE_NEO4J_USER` / `OPENFORGE_NEO4J_PASSWORD` env vars — add these
two fields to `Config` in the implementation task; never hardcode).

---

## Implementation checklist for the follow-up task (Cursor)

1. Extract GraphML read/write into `backends/_graphml_io.py`; make
   `NetworkXGraphBackend` use it (behavior-preserving, tests must stay green).
2. Add `neo4j` driver to dependencies (pinned); lazy import.
3. Implement `Neo4jGraphBackend(GraphBackend)` per Section 2, one method at a
   time, with a `testcontainers`-or-mock strategy: unit tests mock the driver
   session (no live DB in unit tests, per project convention); a separate
   `tests/integration/test_neo4j_backend.py` may use a local container and
   must be skipped when no server is reachable.
4. Add registry entry + `Config` auth fields + `docker/neo4j/`.
5. Write `scripts/migrate_graphml_to_neo4j.py` with the verification steps in
   Section 3.
6. Gate: `knowledge_graph.backend: neo4j` passes the same interface test
   suite (`tests/unit/test_graph_backend.py::TestNetworkXGraphBackend`
   parametrized over both backends) against a live local server.
