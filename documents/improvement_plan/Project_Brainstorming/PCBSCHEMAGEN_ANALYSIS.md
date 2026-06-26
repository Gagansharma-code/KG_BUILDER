# OpenForge — PCBSchemaGen Analysis and Adoption Roadmap

**Source paper:** PCBSchemaGen: Constraint-Guided Schematic Design via LLM for Printed Circuit Boards  
**Analysis date:** 2026-06-26  
**Purpose:** Identify what OpenForge should adopt, improve, or already does better — with implementation specifics for each point.

---

## Point 1 — Closed 32-Role Pin Ontology

OpenForge's `PinDefinition.normalized_function` is currently free-text. P2 pin normalization maps raw pin names to human-readable strings — but those strings are not machine-verifiable. You cannot programmatically check whether two pins are connected correctly if one is labeled `"SPI_CLOCK"` and the other `"CLK_IN"` — a human understands those are compatible, a verifier does not.

PCBSchemaGen solves this with 32 fixed roles. Every pin in the system maps to exactly one role from this closed set. The verifier then checks role-level compatibility rules — `POWER_OUT` connects to `POWER_IN`, not to another `POWER_OUT`. This is what makes deterministic verification possible.

**What OpenForge needs:** Change `normalized_function` from `Optional[str]` to an enum of pin roles — something like `POWER_IN`, `POWER_OUT`, `SIGNAL_IN`, `SIGNAL_OUT`, `DIFFERENTIAL_POS`, `DIFFERENTIAL_NEG`, `CLOCK`, `ENABLE`, `GROUND`, `REFERENCE`, `SENSE_POS`, `SENSE_NEG`, `NC`, and so on. The exact set should be designed once and frozen. P2 normalization then maps raw pin names to these roles rather than to free text strings. This is a schema change to `src/schemas/datasheet.py` and a rework of `src/knowledge_graph/pin_normalizer/`.

This is prerequisite to implementing Point 2.

**Verdict:** OpenForge should adopt. Specifically: the strict mapping to a closed pin role ontology and predefined relational predicates, as it perfectly grounds downstream programmatic verification.

---

## Point 2 — 5-Layer Deterministic Structural Verifier

This is the most structurally important adoption. PCBSchemaGen's 5 layers map directly onto gaps in OpenForge's current verification:

**Layer 1 — Electrical invariants:** Basic ERC — shorts, floating pins, undriven nets. OpenForge has `src/schematic/erc.py` which covers this partially. Close but not complete.

**Layer 2 — Pin-role compatibility:** Does every connection respect role rules? `POWER_OUT → POWER_IN` is valid. `POWER_OUT → POWER_OUT` is a short. `SIGNAL_OUT → SIGNAL_OUT` is a bus conflict. This requires the closed ontology from Point 1 and is entirely absent from OpenForge today.

**Layer 3 — Subcategory templates:** Every component type has mandatory pin connections. An op-amp must have V+ and V− power pins connected. A MOSFET gate must be driven. A comparator output must not be left floating. These are component-class rules derivable from KG-2 design recipes. OpenForge has the KG-2 data for these rules but no verifier that enforces them.

**Layer 4 — Topology signatures:** Covered under Point 8 below.

**Layer 5 — Power invariants:** Kelvin sensing connections, star-ground topology, separate analog and digital ground planes. These are domain-specific rules currently scattered in KG-4 placement rules but not enforced programmatically at schematic synthesis time.

The key property of this verifier: it produces a **continuous score** (fraction of constraints satisfied), not just pass/fail. This is what enables the Thompson Sampling search in Point 6. Without a continuous scorer, bandit search degrades to random restart.

**What OpenForge needs:** A new module `src/schematic/structural_verifier.py` implementing all 5 layers. Layers 1 and 5 partially exist — consolidate them here. Layers 2 and 3 require the pin role ontology. Layer 4 requires VF2. The output is a `VerificationResult` with a float score and per-layer breakdown for targeted error feedback.

**Verdict:** OpenForge should adopt. While the requirement completion engine injects domain axioms, relying on an LLM to follow them inherently risks hallucination. Adopting a strict deterministic verifier as a zero-cost process reward model ensures constraints are mathematically enforced rather than just suggested.

---

## Point 3 — Component Selection and BOM Generation

PCBSchemaGen does not have an independent BOM generator. Instead, the UCA retrieval catalog selects a small set of candidate ICs based on the user's prompt and required components. This candidate list is injected into the LLM's prompt as the "Available Components" list, and strict prompt instructions force the LLM to only use parts and footprints from this specific list.

OpenForge already does this better. The dedicated BOM generator grounded in the knowledge graph is a superior and more robust approach than relying on LLM context windows to filter and select components. No action needed here.

The observation from the analysis is correct — constraining an LLM to a context window of available components is fragile and does not scale.

**Verdict:** OpenForge already does better.

---

## Point 4 — Evaluation Methodology

PCBSchemaGen evaluates on two benchmarks: PCBBENCH (62 expert-authored tasks) and OPEN-SCHEMATICS-EVAL (165 tasks derived from open-source schematics). They evaluate correctness using their deterministic 5-layer verifier, meaning no human-in-the-loop or SPICE simulations are required to check schematic-level correctness. To ensure the verifier itself is trustworthy, they validated its verdicts against a blind senior PCB engineer on a 300-sample set, achieving a near-perfect Cohen's kappa agreement of 0.91. They measure success using Pass@1 and Pass@5 over a budget of 4 refinement attempts.

OpenForge currently has team gate tests that test individual pipeline stages with mocked inputs. It does not have an end-to-end design benchmark: a set of known-correct designs against which you run the full pipeline and measure pass rates.

For OpenForge this matters because right now there is no way to measure whether a change to the requirement completion engine or schematic synthesizer actually improves output quality. Every change is evaluated qualitatively by reviewing individual outputs. At scale this does not work.

**What OpenForge needs:** An `eval/` benchmark comprising 20-30 design tasks drawn from the scientist prompt log and from canonical circuit types in the population run corpus. Ground-truth correct BOMs and netlists for each. An automated scoring run against the structural verifier. This does not require new infrastructure — it requires curating the benchmark dataset and wiring the verifier as the scorer. This is also how you generate the OpenForge research paper's quantitative results.

**Verdict:** OpenForge should adopt. Building a deterministic oracle to act as an automated benchmark is critical for iterating on LLM workflows, as analog SPICE simulation cannot validate schematic-capture choices like real IC pinouts.

---

## Point 5 — Limitations OpenForge Must Engineer Around

PCBSchemaGen explicitly states several limitations that OpenForge must actively address:

**Context scaling limit:** Their UCA retrieval context limit restricts the IC library pool. Scaling to more than 1,000 ICs would bloat the prompt past 35k tokens and cause context degradation.

OpenForge avoids this problem because the BOM generator selects specific components before the schematic synthesizer runs. The LLM for schematic synthesis only sees the 5-15 components in the BOM, not a thousand candidates. This is a structural advantage and should be documented explicitly as a design decision.

**Model size floor:** Models under approximately 8B parameters completely collapse on hard tasks, proving that raw parameter count — not just retrieval — is a bottleneck. Qwen2.5-7B is OpenForge's schematic synthesis model. This is right at the floor. For simple topologies (LDO, basic op-amp buffer) it will work. For compound designs (Libbrecht-Hall + power section + potentiometer + VCO bias tee) it will struggle. The mitigation is not necessarily a larger model — it is the Thompson Sampling search (Point 6) which compensates for individual generation failures by running multiple candidates and selecting the best.

**Ontology breadth:** The system only handles board-level digital, analog, and power circuits. It cannot handle RF, high-speed digital signal integrity, or on-die mixed-signal SoCs. OpenForge should make the same explicit scope admission. The ZCOM 4596 VCO prompt from the scientist log is RF. Handling it requires RF-specific topology templates in KG-2 and RF-specific pin roles in the ontology. This is an expansion of scope that should be planned, not assumed to work automatically.

**Failure modes:** The vast majority of early LLM failures are basic Electrical Rule Check (ERC) violations, while complex power invariants (like Kelvin source independence) fail mostly on medium and hard tasks. Strict ERC rules also result in a small false-rejection rate of structurally sound designs.

**Verdict:** OpenForge is missing entirely the engineering mitigations for these constraints. Context scaling is accidentally mitigated by architecture. Model size and ontology breadth must be actively addressed.

---

## Point 6 — Thompson Sampling Bandit Search

### What It Is

Standard refinement loops fail because they are linear:

```
Generate → fail → fix error A → fail → fix error B → fail → stuck
```

Fixing one constraint violation frequently introduces another. The system has no way to escape local minima.

PCBSchemaGen reframes this as a multi-armed bandit problem:

- Each "arm" is a candidate schematic (there are multiple running simultaneously, not one)
- The 5-layer deterministic verifier produces a continuous reward score between 0 and 1 for each candidate — not just pass/fail
- Thompson Sampling maintains a Beta distribution over the expected reward of each arm, samples from it, and picks which candidate to refine next
- Adaptive temperature: if a candidate scores high (close to correct) → lower the LLM temperature for that refinement (exploit, make precise corrections). If it scores low → raise temperature (explore, rethink the design entirely)

The result is that the search never gets permanently stuck. A failing candidate is deprioritised; a promising one gets focused refinement. The budget of 4 refinement attempts is spread across candidates intelligently rather than wasted on a single broken path.

### Why This Matters for OpenForge

OpenForge's current pipeline is entirely linear and single-path:

```
Intent → Completion → Retrieval → BOM → Schematic → NIR → Serialize
```

If schematic synthesis produces a bad netlist, the only recovery is a human review gate. There is no internal search, no backtracking, no exploration of alternative designs. The system commits to one path at every stage.

This is the structural weakness PCBSchemaGen's mechanism directly addresses. And critically, OpenForge already has everything needed to implement a scoring oracle — it just does not use them for search:

- `src/schematic/erc.py` — ERC checker, continuous violation count
- `src/nir/validator.py` — NIR structural checks
- `src/bom/` — BOM validator with confidence scores
- Phase 4 physics validation — deterministic rule engine

These validators exist to catch errors. They do not currently guide generation. That is the gap.

### Where to Apply It in OpenForge

The right answer is not to copy PCBSchemaGen's approach directly. Their problem is narrower — fixed IC set, wire them correctly. OpenForge's problem has variance at multiple levels. The search mechanism should be applied at the two stages where variance is highest and validators already exist.

**Level 1 — BOM (Stage 4)**

The KG-3 query for a design requirement returns multiple candidate components. The current BOM generator commits to one. Instead:

- Generate top-3 BOM candidates from KG-3 (different components all meeting the same spec — e.g., three different zero-drift op-amps)
- Score each by: KG-3 confidence × datasheet extraction confidence × constraint satisfaction completeness
- Propagate the top-2 into Stage 5

This is cheap — no LLM calls needed, pure KG scoring.

**Level 2 — Schematic Synthesis (Stage 5)**

This is where PCBSchemaGen's mechanism applies most directly:

- For each surviving BOM candidate, generate 2-3 netlist candidates with different LLM temperatures
- Score each with ERC + NIR validator → continuous reward score
- Apply Thompson Sampling to select which candidate to refine next
- Adaptive temperature per candidate based on its current score
- Budget: 4 refinement attempts spread across candidates

Maximum candidates in flight: 6 (2 BOMs × 3 netlists). This is bounded and computationally feasible with the 7B model.

### What OpenForge Should Build That Is Better Than PCBSchemaGen

PCBSchemaGen's bandit operates only at the netlist level with a fixed IC set. OpenForge can run it across two levels simultaneously — BOM choice and netlist choice — with cross-level feedback.

The improvement: **the reward signal at Stage 5 (ERC score) feeds back into Stage 4 (BOM selection)**. If a BOM candidate consistently produces low ERC scores across all its netlist refinements, it is demoted and the next BOM candidate is promoted. This is something PCBSchemaGen cannot do because they have no BOM generation step.

Concretely:

```
BOM candidate A → netlist A1 (ERC 0.4), A2 (ERC 0.3), A3 (ERC 0.2) → consistently low → demote A
BOM candidate B → netlist B1 (ERC 0.7), B2 (ERC 0.8) → refine B2 → ERC 1.0 → done
```

The BOM-level selection is informed by schematic-level outcomes. This closes a feedback loop that no existing tool has.

### What This Requires to Build

Three additions to the existing codebase, none of which require new models:

1. **Multi-candidate BOM output** — modify `src/bom/` to return top-3 ranked candidates instead of committing to one. The ranking score already exists implicitly in the KG confidence path.

2. **Thompson Sampling controller** — a small module in `src/schematic/` that maintains Beta distributions over ERC scores per candidate, samples to select the next refinement target, and adjusts temperature accordingly. This is approximately 100 lines of pure Python.

3. **Cross-level feedback loop** — after 4 refinement attempts per BOM candidate, aggregate ERC scores and use them to update the BOM-level ranking. If a BOM candidate is consistently failing at Stage 5, pull the next one.

None of this requires a new model, new infrastructure, or GPU changes. The validators are already running — this just routes their output into a search mechanism instead of discarding it.

**Verdict:** OpenForge should adopt. This bandit-based search tree with continuous structural rewards and adaptive temperature is a massive improvement over standard linear CoT/Reflexion loops.

---

## Point 7 — Provenance

PCBSchemaGen does not explicitly solve strict provenance. While their prompt templates force the LLM to output a design plan explaining which functional blocks were chosen and why via standard Chain-of-Thought, there is no architectural mechanism mapping a generated connection back to a specific sentence in a source datasheet PDF. PCBSchemaGen relies on standard LLM self-explanation, which is subject to hallucination and is not technically traceable to the source document.

This is the gap where OpenForge's existing architecture has a partial solution that needs completing.

The BOM generator already produces justifications traceable to KG edges, and KG edges carry `source_document` fields. So component selection has partial provenance.

What is missing is **netlist-level provenance** — why is Pin A connected to Pin B? The schematic synthesizer in `src/schematic/` produces `NetlistEntry` objects that specify connections but carry no source attribution. When a scientist asks "why is the 100Ω resistor connected to the op-amp output?", the system cannot answer with a document reference.

The fix: every `NetlistEntry` in the NIR should carry a `source_recipe_id` field pointing to the KG-2 design recipe node that drove that connection. The schematic synthesizer already queries KG-2 to find connection rules — it just discards the provenance after using it. Preserving it on the netlist edge closes the loop.

This is also directly relevant to the research paper — OpenForge's provenance-grounded approach is a claimed contribution. It needs to be fully implemented, not partially.

**Verdict:** OpenForge is missing entirely full netlist-level provenance. OpenForge currently does better at BOM-level provenance than PCBSchemaGen, but the netlist level is unimplemented.

---

## Point 8 — VF2 Subgraph Isomorphism for Multi-Topology

PCBSchemaGen's Layer 3 topology verifier uses the VF2 subgraph isomorphism algorithm to check generated graphs against multiple domain-level topology templates (e.g., synchronous bucks, pi filters, half-bridges) simultaneously. They demonstrate this by successfully synthesizing a 5000 W AC-DC converter that combines five distinct domains: Sensing, MCU, Power Stage, Communication, and Auxiliary Power.

This directly addresses the multi-topology intent problem previously identified in the GLM review — where `goal_topologies: list[TopologyGuess]` needs to replace `goal_topology: Optional[str]`.

**The mechanism:** KG-2 stores topology templates as graph structures — nodes are component roles (op-amp, resistor, capacitor), edges are connection patterns (output→inverting input creates feedback). After schematic synthesis, run `networkx.algorithms.isomorphism.GraphMatcher` on the generated netlist against each expected topology template. If all expected topologies are found as subgraphs, the design passes Layer 4 of the structural verifier.

**For OpenForge this matters in two ways:**

**Validation:** Confirms that a compound design actually contains all the requested functional blocks. A Libbrecht-Hall + LDO design should match both a current source template and an LDO template as separate subgraphs. If either is missing, the verifier identifies which topology failed and the refinement loop targets it specifically.

**Debugging:** When the LLM generates a partial or malformed schematic, VF2 tells you exactly which topology subgraph is missing or malformed. This produces targeted error feedback rather than a generic "ERC failed" message — which is what PCBSchemaGen feeds back into the refinement prompt.

NetworkX's `GraphMatcher` already exists in the OpenForge dependency stack since KG is built on NetworkX. Implementation is a module in `src/schematic/topology_verifier.py` that takes the generated netlist graph and the set of expected topology templates from KG-2 and returns per-topology match results.

**Verdict:** OpenForge should adopt. Using VF2 subgraph isomorphism to detect and validate multiple independent functional blocks within a single netlist is a highly effective way to handle complex, multi-topology boards.

---

## Priority Order for Implementation

Based on dependencies and impact:

| Priority | Item | Dependency | Files |
|---|---|---|---|
| 1 | Pin role ontology (closed enum) | None — prerequisite for everything below | `src/schemas/datasheet.py`, `src/knowledge_graph/pin_normalizer/` |
| 2 | Structural verifier Layers 1-3 | Pin role ontology | `src/schematic/structural_verifier.py` (new) |
| 3 | VF2 topology verifier Layer 4 | Structural verifier scaffold | `src/schematic/topology_verifier.py` (new) |
| 4 | Thompson Sampling controller | Structural verifier (continuous score) | `src/schematic/bandit_controller.py` (new), `src/bom/` |
| 5 | Netlist provenance | NIR schema | `src/schemas/nir.py`, `src/schematic/synthesizer.py` |
| 6 | Eval benchmark | Structural verifier (as scorer) | `eval/benchmarks/` (new) |

Items 1-3 are coupled and should be one Cursor session. Items 4-6 are independent and can each be separate sessions.

---

## Summary of Verdicts

| Point | Verdict |
|---|---|
| 1 — Closed pin role ontology | **Adopt** — prerequisite for deterministic verification |
| 2 — 5-layer structural verifier | **Adopt** — most structurally important addition |
| 3 — BOM generation | **OpenForge already does better** — no action needed |
| 4 — Evaluation methodology | **Adopt** — critical for research paper and iteration |
| 5 — Limitations and failure modes | **Missing** — must engineer around context scaling, model floor, RF scope |
| 6 — Thompson Sampling bandit | **Adopt and improve** — extend to two-level BOM+netlist search |
| 7 — Provenance | **Missing at netlist level** — partial at BOM level, must complete |
| 8 — VF2 multi-topology | **Adopt** — NetworkX already in stack, direct implementation path |
