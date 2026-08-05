# Idea 1 & Idea 2 — A Plain-Language Explainer

> **Who this is for:** Someone opening this repo for the first time who wants to
> understand what "Idea 1" and "Idea 2" actually do, without reading source code
> first. Built for the AMD AI Developer Program Track 2 submission.

If you want the full architectural reasoning (why ASHA over Thompson Sampling,
the four-layer cascade in detail), see
[`Search_controller_decision.md`](./Search_controller_decision.md) in this same
folder. This doc is the short version.

---

## The problem both ideas solve

Open Forge designs a circuit in stages: pick components (BOM) → wire them into a
schematic (netlist) → verify the result against a 5-layer structural checker
(pin roles, power/ground shorts, ERC, layer-by-layer scoring). The first attempt
at any of this is rarely perfect — components can be swapped for better ones,
and any part of the process that touches an LLM can hallucinate a connection.

Before Idea 1, nothing closed the loop between "try something" and "score it,
then decide what to do next." Each stage ran once. Idea 1 builds that loop.
Idea 2 then gives the loop something genuinely useful to iterate on: a small,
fast model that gets meaningfully better through retries alone, no fine-tuning.

---

## Idea 1 — The ASHA Search Controller

**File:** [`src/schematic/search_controller.py`](../../src/schematic/search_controller.py)

**What it does, in one sentence:** evaluate every BOM candidate, keep the best
one, and automatically decide whether it needs cleanup, heavier rework, or
nothing at all.

```
For each BOM candidate (from the existing TPE sampler):
    synthesize a schematic → build a ref map → verify_schematic() → score

Take the highest-scoring candidate. Then:
    score ≥ 1.00        → done, ship as-is
    0.80 ≤ score < 1.00  → SA polisher (fine-tuning pass)
    score < 0.80         → beam search escalation (heavier rework)

If score is still < 0.80 after beam search → flag for human review.
Record the outcome back into the TPE sampler so future BOM picks improve.
```

Everything in that flow already existed as a separate, tested module
(`generate_bom_candidates`, `synthesize_schematic`, `verify_schematic`,
`polish_schematic`, `run_beam_search`) — Idea 1 didn't reinvent any of them.
It's the orchestrator that was missing: the piece that actually runs them in
sequence, on real candidates, and makes the routing decision.

**Why "ASHA"?** Named after Asynchronous Successive Halving, the search-
scheduling idea it's modeled on. The paper Open Forge is benchmarked against
(PCBSchemaGen) used Thompson Sampling / multi-armed-bandit instead — a
reasonable choice for their setup, but it only reasons about one level of
variance (how to *wire* a fixed set of parts). Open Forge has two levels
(which parts to use, *and* how to wire them), and Thompson Sampling has no
clean way to say "this whole BOM candidate is bad, stop spending budget on
it" — a Beta distribution never fully rules a dead candidate out. A
deterministic elimination rule does that better, hence ASHA-style routing
instead. Full reasoning in `Search_controller_decision.md`.

**Honest caveat:** because schematic synthesis today is fully deterministic
(rule-based net assignment, no LLM in that specific step), re-evaluating the
*same* BOM candidate twice would just produce the same score — so this first
version is best-of-N over BOM candidates, not true multi-round ASHA with
resampling. That's fine; the loop, the TPE learning, the SA polish, and the
beam-search escalation all get switched on for real for the first time
either way. Idea 2 is what introduces the first stochastic (LLM-based)
generator into this path — see below.

**Tests:** `tests/unit/schematic/test_search_controller.py`, plus Team D
gate CHECK 9 (`eval/gates/team_d_gate.py`) as a real end-to-end smoke check.

---

## Idea 2 — Weak-Model + Verifier Self-Improvement Loop ("Agent Maxing")

**Files:**
[`src/schematic/llm_netlist_proposer.py`](../../src/schematic/llm_netlist_proposer.py)
(generates a netlist proposal) and
[`src/schematic/self_improvement_loop.py`](../../src/schematic/self_improvement_loop.py)
(the retry loop around it).

**The pitch in one sentence:** a small, fast local model (Qwen2.5-1.5B-Instruct
— deliberately smaller than the 7B model Open Forge uses elsewhere) can close
most of the gap to a much bigger model, purely by retrying against a
deterministic scorer. No fine-tuning, no reward model, no RL.

```
Round 0: weak model proposes a netlist, no hints. Score it. This is the
         "before" number — how bad is the weak model completely on its own?

Round 1+: feed the previous round's actual verifier violations back into
          the prompt as plain-language correction instructions. Try again.
          Temperature schedule: [0.7, 0.7, 0.9, 0.9, 0.5] — cools down once
          it's close, reheats if still stuck, cools again for a final
          precise pass.

Stop early if a round scores ≥ 0.95, or after 5 rounds either way.
Best score seen across all rounds = the "after" number.

If the best result lands between 0.80–1.00, run it through the SA polisher
as a free final cleanup pass (zero extra LLM cost) — the same polisher
Idea 1 uses. It can also fall through to beam search if it's still weak.
```

The verifier (`verify_schematic()`) never changes and never gets asked to
score itself — it's the exact same deterministic 5-layer checker Idea 1
uses. The model never grades its own work; a fixed, separately-built
verifier does.

**Why this is the actual deliverable:** the round-0-vs-best-of-loop score
gap is the entire point. A small model that's bad alone but competitive
after a few verifier-guided retries is a much cheaper story than "just use
the big model," and it's the "agent maxing" idea the AMD Track 2 pitch is
built around.

**Tests:** `tests/unit/schematic/test_llm_netlist_proposer.py` and
`tests/unit/schematic/test_self_improvement_loop.py` (fully mocked, no GPU
needed, run in plain CI). Real end-to-end measurement lives in
`eval/benchmarks/agent_maxing_benchmark.py`, which runs the existing
15-task benchmark suite in two arms — weak model alone vs. weak model +
this loop — and is meant to produce the actual before/after chart.

**Honest caveat, stated plainly:** both modules are fully implemented and
pass their unit/gate tests against mocked verifiers. What has **not** been
confirmed yet is a completed real-GPU run of
`agent_maxing_benchmark.py` producing an actual `report.md` with a real
score delta — that step needs the 1.5B model's weights downloaded onto a
machine with a GPU (or patient CPU inference). If you're reading this and
that run hasn't happened yet, that's the next concrete step, not a gap in
the code.

---

## Where to look next

| Question | Where |
|---|---|
| "Why ASHA and not Thompson Sampling, in full detail?" | [`Search_controller_decision.md`](./Search_controller_decision.md) |
| "What's the exact routing/threshold logic?" | `src/schematic/search_controller.py` (`run_search_controller`) |
| "How does the feedback prompt get built?" | `src/schematic/llm_netlist_proposer.py` (`propose_netlist_llm`) |
| "What does a full run's history look like?" | `src/schematic/self_improvement_loop.py` (`RoundRecord`, `SelfImprovementResult`) |
| "How do I actually run the benchmark?" | `eval/benchmarks/agent_maxing_benchmark.py` — CLI entry point, no separate runner |
| "What's the original build plan these came from?" | `plan.md` (repo root) |
