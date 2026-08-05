# OpenForge Search Controller — A Complete Explainer

> **Who this is for:** Someone new to the codebase who wants to understand *why* the search controller exists, how it works layer by layer, and how it compares to what PCBSchemaGen built.

---

## Part 1 — Why Does a "Search Controller" Exist at All?

When you ask OpenForge to design a circuit, the pipeline eventually asks a local LLM (Qwen2.5-7B) to write a netlist — a list of how every component pin connects to every wire.

LLMs are not perfect. They hallucinate connections. They connect a power output to another power output and cause a short circuit. They leave op-amp power pins floating. The first attempt is almost never 100% correct.

**The naive solution:** If it fails, ask the LLM to try again. Repeat until it passes.

**The problem:** This is linear. Fixing one error often breaks something else. You can get permanently stuck bouncing between two broken states, like trying to flatten a rug with a lump in it — push the lump left, it appears right.

The search controller solves this by running *multiple candidates simultaneously*, scoring each one continuously, and intelligently deciding which one to spend effort on next — instead of blindly retrying one path.

---

## Part 2 — What PCBSchemaGen Built: Thompson Sampling

PCBSchemaGen (the paper OpenForge is benchmarked against) treated schematic refinement as a **multi-armed bandit problem**.

### The Casino Analogy

Imagine you walk into a casino with 3 slot machines. You don't know which one pays out best. You have a limited number of pulls. How do you decide which machine to pull?

**Thompson Sampling** is one answer: for each machine, maintain a mental model of "how good do I think this machine is?" represented as a probability distribution. Pull whichever machine your model says is most likely to be the best *right now*. Update the model based on what you observe.

In PCBSchemaGen's case:
- Each "slot machine" is a candidate schematic
- Each "pull" is an LLM refinement attempt
- The "payout" is the structural verifier score (0.0 to 1.0)
- The "mental model" is a Beta distribution — a pair of numbers (α, β) per candidate that encodes how often it has scored well vs. poorly

They also added **adaptive temperature**: if a candidate is scoring high (close to 1.0), lower the LLM temperature to make precise corrections. If it's scoring low, raise temperature to explore completely different designs.

### Why This Was a Step Forward

Before this, every tool used a linear generate → check → retry loop. PCBSchemaGen's bandit search never got permanently stuck on one broken candidate. A failing schematic got deprioritised; a promising one got focused budget. This was a genuine architectural advance.

### The Weakness: It Only Worked at One Level

PCBSchemaGen has no BOM generation step. Their IC set is fixed. The bandit only operates at the *netlist* level — given these components, wire them correctly.

OpenForge has variance at *two* levels:
1. Which components to use (BOM selection)
2. How to wire them (schematic synthesis)

Thompson Sampling has no mechanism to learn that "this op-amp family consistently produces bad ERC scores across all netlist attempts" and demote it at the BOM level. It cannot close the feedback loop between Stage 4 and Stage 5.

---

## Part 3 — Why We Didn't Use Thompson Sampling

Beyond the two-level problem, Thompson Sampling has a deeper issue for OpenForge's specific setting:

**Beta distributions assume the underlying reward is stationary.** In other words, they assume machine #2 has a fixed "true" payout rate that just needs to be estimated. But in OpenForge, the reward from refining a schematic candidate *changes over time* — because the LLM's temperature changes, because different errors get targeted each round, because the schematic itself gets mutated. The Beta distribution's assumption breaks.

More importantly: **Thompson Sampling spends probability mass on candidates that are already dead.** If candidate A has scored 0.2, 0.1, 0.15 across three attempts, its Beta distribution still has non-zero probability of being pulled again. A deterministic elimination rule — "you're out" — would be more efficient.

This led us to **Successive Halving** and its asynchronous variant, **ASHA**.

---

## Part 4 — Our Architecture: The Four-Layer Controller

OpenForge's search controller is a **cascade of four specialised components**, each activating only when the previous one hands off. Think of it like a surgery team: the general surgeon operates first, a specialist steps in if needed, and a delicate instrument is used for the final millimetre.

```
┌─────────────────────────────────────────────────────────┐
│              OpenForge Search Controller                │
│                                                         │
│  Layer 0: TPE BOM Sampler    (Stage 4, before LLM)      │
│       ↓                                                 │
│  Layer 1: ASHA Controller    (primary, Stage 5)         │
│       ↓ if score >= 0.80                                │
│  Layer 2: SA Polisher        (fine-tuning, Stage 5)     │
│       ↓ if ASHA fails (score < 0.80)                    │
│  Layer 3: Beam Search        (escalation, Stage 5)      │
└─────────────────────────────────────────────────────────┘
```

---

## Layer 0 — TPE BOM Sampler

**File:** `src/bom/candidates.py` + `data/bom_tpe_history.json`

### What it does

Before any LLM is called for schematic synthesis, this layer decides *which components to try*. It generates up to 3 BOM candidates (a `BOMLadder`) — e.g., three different zero-drift op-amps that all satisfy the design spec — and ranks them.

### The Learning Mechanism

TPE stands for **Tree-structured Parzen Estimator**. The analogy: imagine you're a chef choosing between three brands of butter for a recipe. Over time, you notice Brand A always makes the dish greasy. You start choosing Brand B or C first. TPE is that learned preference, formalised.

OpenForge's TPE sampler stores `data/bom_tpe_history.json` — a record of which specific components, in which component categories, produced high ERC scores in past design sessions. When a new design arrives:

1. Generate 3 BOM candidates from KG-3 (the component knowledge graph)
2. Enrich each candidate's `alternatives` list using history — components that performed well on similar past designs get ranked higher
3. Pass the `BOMLadder` to the ASHA controller

### Why TPE beats Thompson Sampling at the BOM level

BOMs are **categorical** — you're choosing between discrete named parts, not a continuous number. Thompson Sampling's Beta distribution is designed for binary outcomes on a continuous scale. TPE is specifically built for categorical search spaces. It models the distribution of *good* configurations vs. *bad* ones and samples from the good region.

### The closed feedback loop

After the ASHA controller finishes, `record_asha_outcome()` writes the final ERC score back to the history file, keyed by `(component_type, specific_part)`. The next design session starts with this knowledge already baked in. **This cross-design learning is something PCBSchemaGen cannot do** because they have no BOM generation step.

---

## Layer 1 — ASHA Controller (Primary Search)

**File:** `src/schematic/search_controller.py`

### The Problem ASHA Solves

Imagine a teacher grading 6 students' essays. Each student gets multiple attempts to improve. The naive approach: give every student the same number of attempts before picking a winner. The problem: some essays are hopeless after attempt 1. You're wasting time on them.

**Successive Halving:** After each round, eliminate the bottom half. Give the survivors twice as many attempts. Repeat.

**ASHA (Asynchronous Successive Halving):** Don't wait for all candidates to finish a round before eliminating. As soon as a candidate finishes an evaluation and is in the bottom half, eliminate it immediately. Promoting and pruning happen continuously, not in synchronised batches.

### Why ASHA over Thompson Sampling

Thompson Sampling never definitively eliminates. ASHA does. In OpenForge, each LLM inference call costs 3–8 seconds of GPU time. Spending that budget on a candidate that scored 0.15 in round 1 is waste. ASHA provably minimises this waste for fixed budgets.

ASHA also handles **non-uniform evaluation cost** — a complex multi-topology design takes longer to evaluate than a simple LDO. Thompson Sampling has no concept of variable evaluation cost. ASHA accounts for it by pruning based on relative rank within each budget bracket, not on absolute time.

### What ASHA actually does in our code

1. Receive the `BOMLadder` (up to 3 BOM candidates from Layer 0)
2. For each BOM candidate, generate 2 netlist variants using the LLM at different temperatures (lower = exploit, higher = explore)
3. Score all candidates with `verify_schematic()` → returns a continuous score in [0.0, 1.0]
4. After each round, eliminate bottom candidates, give survivors more budget
5. When budget is exhausted, output the winning candidate and its `VerificationResult`
6. Set `hand_off_to_sa = True` if winner score is in [0.80, 1.0)
7. Set `hand_off_to_beam = True` if winner score is < 0.80

The verifier score feeds back to the TPE sampler via `record_asha_outcome()`.

---

## Layer 2 — SA Polisher (Fine-Tuning)

**File:** `src/schematic/sa_polisher.py`

**Trigger:** ASHA winner has score ≥ 0.80 but < 1.0.

### The Analogy

You've carved a wooden sculpture (ASHA's job — rough shape is right). Now you need to sand it to a perfect finish. You don't call the sculptor back. You use sandpaper — a simpler, cheaper tool.

The SA polisher uses **zero LLM tokens**. It works purely by programmatic graph mutations on the netlist — moving pins between nets, disconnecting NC-role pins, splitting bus conflicts — then scoring the result with `verify_schematic()`. This is the "sandpaper."

### The Math: Simulated Annealing

SA is inspired by metallurgy: when you heat metal and cool it slowly, atoms settle into a low-energy (optimal) crystal structure. If you cool too fast, you get defects.

The algorithm:
```
T = 1.0  (temperature — starts high)
for each step:
    pick a violation-guided move (e.g., disconnect this NC pin)
    apply it → get candidate netlist
    score candidate with verify_schematic()
    delta = candidate_score - current_score

    if delta > 0: always accept (it's better)
    if delta < 0: accept with probability exp(delta / T)
                  (sometimes accept worse moves to escape local minima)

    T = T * 0.90  (cool down)
```

The key insight: accepting *occasionally worse* moves prevents the algorithm from getting trapped in a local maximum (a state where every small change makes things worse, but a sequence of two changes could make things much better).

### Why this is better than asking the LLM to polish

The LLM would cost 3–8 seconds per attempt and might hallucinate new errors while fixing old ones. The SA polisher runs in milliseconds and only performs mathematically valid graph operations. It cannot hallucinate.

### Thresholds in the code

| Constant | Value | Meaning |
|---|---|---|
| `SA_TRIGGER_THRESHOLD` | 0.80 | Below this, SA won't run (design needs LLM help, not polishing) |
| `SA_DONE_THRESHOLD` | 1.00 | SA stops as soon as score reaches perfect |
| `SA_MAX_STEPS` | 50 | Maximum mutations attempted |
| `SA_T_INITIAL` | 1.0 | Starting temperature (high exploration) |
| `SA_ALPHA` | 0.90 | Cooling rate (multiply T by 0.90 each step) |
| `SA_T_MIN` | 0.01 | Minimum temperature (near-zero exploration) |

---

## Layer 3 — Beam Search Escalation

**File:** `src/schematic/beam_search_escalation.py`

**Trigger:** ASHA winner has score < 0.80 (SA wouldn't help — design is fundamentally broken).

### The Analogy

You're hiking to a summit in fog. You can't see the whole mountain. Instead of walking one path and backtracking if it fails, you send out 3 scouts simultaneously. Each scout takes one step, reports back their position. You keep the 3 scouts who are highest up. Repeat.

That's beam search: maintain `beam_width = 3` parallel candidate states. At each depth step, expand every state into all possible repair moves, score all resulting candidates, keep the top 3. Repeat for up to `max_depth = 4` steps.

### Why not MCTS (Monte Carlo Tree Search)?

MCTS was the original escalation proposal. It was **rejected** after an 8-point architectural debate. The core reasons:

1. **MCTS needs many rollouts to build reliable statistics.** With 3–8 seconds per LLM call and a budget of ~15 total calls, most MCTS nodes get visited once. Statistics never stabilise.
2. **OpenForge has immediate feedback at every step** (the 5-layer verifier). MCTS is designed for *sparse* rewards — delayed feedback where you only know the outcome at the end of a long sequence. That's chess. That's not schematic repair.
3. **The action space is small** (5 verifier layers = 5 possible repair targets). Exhaustive enumeration at depth 2 is 25 calls. Beam search covers this. MCTS overhead is not justified.

Beam search covers the same theoretical repair depth (≤ 4 sequential moves) at a fraction of the implementation cost and zero LLM inference.

### What beam search actually does

```
beam = [ASHA winner netlist]  (width = 1 initially)

for depth in range(4):
    candidates = []
    for each state in beam:
        re-verify state → get fresh violations
        generate all targeted repair moves from violations
        apply each move → get candidate netlist
        score each with verify_schematic()
        candidates.extend(all scored candidates)

    beam = top 3 candidates by score

    if best score >= 0.95: stop early

return best candidate across all depths
```

If beam search also fails (final score < 0.80 after 4 depths), the design is routed to the **human review queue** — the engineer sees it in the TUI with the per-layer breakdown and decides what to do.

---

## Part 5 — The 5-Layer Verifier: The Scoring Oracle

**File:** `src/schematic/structural_verifier.py`

Every layer of the search controller depends on a single function: `verify_schematic()`. This is the scoring oracle — it takes a netlist and returns a continuous score in [0.0, 1.0] plus a per-layer breakdown.

Without a continuous scorer, all of the above is impossible. You'd only have pass/fail, which gives no gradient for search to follow.

| Layer | Name | What it checks | Weight |
|---|---|---|---|
| 1 | Electrical Invariants | No short circuits, no floating power pins, basic ERC rules | Highest |
| 2 | Pin Role Compatibility | Every pin on a net has a compatible role (e.g., POWER_OUT can't share a net with another POWER_OUT) | High |
| 3 | Subcategory Templates | Op-amps have V+ and V− connected. MOSFETs have driven gates. Comparators have non-floating outputs. | Medium |
| 4 | Topology Signatures | VF2 subgraph isomorphism — does the netlist graph contain the expected circuit topology (e.g., LDO pattern, current source pattern)? | Medium |
| 5 | Power Invariants | Star-ground topology, Kelvin sensing connections, AGND/DGND separation | Medium |

The weighted mean of all layer scores is the final `VerificationResult.score`. The `critical_violations` list tells the SA polisher and beam search exactly *which* connections to target.

---

## Part 6 — The Full Picture

```
User prompt
    │
    ▼
Stage 4: BOM Generation
    │   TPE BOM Sampler consults history
    │   Returns BOMLadder (up to 3 ranked BOM candidates)
    │
    ▼
Stage 5: Schematic Synthesis (Search Controller)
    │
    ├─ ASHA Controller
    │       Generate 2 netlist variants per BOM candidate
    │       Score with verify_schematic() each round
    │       Eliminate bottom candidates, give survivors more budget
    │       Winner: best candidate when budget exhausted
    │
    ├─ if winner score ≥ 0.80
    │       SA Polisher
    │           Programmatic graph mutations
    │           Metropolis acceptance (temperature-guided)
    │           Zero LLM tokens
    │           Target: score = 1.0
    │
    ├─ if winner score < 0.80
    │       Beam Search Escalation (width=3, depth=4)
    │           Enumerate repair moves from violations
    │           Score all candidate moves
    │           Keep top 3 per depth step
    │           Target: score ≥ 0.95
    │
    └─ if still < 0.80 after beam search
            → Human Review Queue
    │
    ▼
    TPE history updated with final ERC score
    (cross-design learning persists to next session)
    │
    ▼
Stage 6+: NIR → Serializer → KiCad / tscircuit output
```

---

## Part 7 — Why This Is Better Than PCBSchemaGen's Controller

| Property | PCBSchemaGen (Thompson Sampling) | OpenForge (ASHA + SA + Beam + TPE) |
|---|---|---|
| Operates at BOM level | ❌ No BOM step | ✅ TPE sampler with cross-design learning |
| Operates at schematic level | ✅ Beta bandit | ✅ ASHA (provably better for fixed budgets) |
| Eliminates dead candidates | ❌ Never fully eliminates | ✅ ASHA hard-prunes bottom candidates |
| Fine-tuning near-perfect designs | ❌ Keeps using LLM | ✅ SA polisher: zero LLM, deterministic |
| Handles non-uniform eval cost | ❌ Assumes uniform | ✅ ASHA designed for this |
| Cross-design learning | ❌ Stateless per design | ✅ TPE history file persists |
| Handles compound topologies | ❌ Single-level search | ✅ Beam search escalation |
| LLM calls for polishing | ❌ Yes (expensive) | ✅ None (SA is purely algorithmic) |
| Air-gap compatible | ✅ Yes | ✅ Yes |

---

## Quick Reference: Files

| File | What it implements |
|---|---|
| `src/bom/candidates.py` | `BOMLadder`, `generate_bom_candidates()` |
| `src/bom/tpe_sampler.py` | `enrich_bom_candidates()`, `record_asha_outcome()` |
| `data/bom_tpe_history.json` | Cross-design component preference history |
| `src/schematic/search_controller.py` | ASHA controller — **implemented**, see status note below |
| `src/schematic/sa_polisher.py` | SA polisher, `SMove`, `_metropolis_accept()` |
| `src/schematic/beam_search_escalation.py` | `run_beam_search()`, `BeamState` |
| `src/schematic/structural_verifier.py` | `verify_schematic()`, 5-layer scorer |
| `src/schematic/llm_netlist_proposer.py` | Weak-model netlist proposal (Idea 2) |
| `src/schematic/self_improvement_loop.py` | Weak-model self-improvement loop (Idea 2) |
| `docs/MCTS_DECISION.md` | Full 8-point record of why MCTS was rejected |

---

## Status update — `search_controller.py` implemented

Earlier revisions of this document (and `PROJECT_CONTEXT.md` §9,
`CURRENT_REPO_MAP.md` §10 gap #1) stated that `src/schematic/
search_controller.py` did not exist and that `ASHAResult` only appeared in
comments. That gap is now closed: `run_search_controller()` and `ASHAResult`
are implemented, evaluating every BOM candidate in a `BOMLadder`, handing
the winner to `polish_schematic()` or `run_beam_search()` per the thresholds
documented above, and recording the outcome via `record_asha_outcome()`.

One correction to Part 4's description: because `synthesize_schematic()` is
deterministic (rule-based net assignment, not an LLM call), the first
implementation evaluates each BOM candidate exactly once rather than
generating "2 netlist variants using the LLM at different temperatures" —
there is no LLM in that path to sample from. The variance ASHA acts on
comes from which BOM candidate is chosen (Layer 0), not from resampling a
deterministic function. `src/schematic/llm_netlist_proposer.py` and
`src/schematic/self_improvement_loop.py` introduce the first LLM into the
schematic-synthesis path — a weak model + verifier-scored retry loop — which
is where multi-round, LLM-driven ASHA becomes a meaningful next step.

See `plan.md` (repo root) for the implementation plan and PR breakdown, and
`tests/unit/schematic/test_search_controller.py`,
`tests/unit/schematic/test_llm_netlist_proposer.py`,
`tests/unit/schematic/test_self_improvement_loop.py` for test coverage.
Not yet done: wiring `run_search_controller()` into `run_intent_pipeline()`
or `run_e2e()` — it is deliberately not called from either yet, so no
existing pipeline behavior changes until a caller opts in via
`config.search_controller.enabled`.