# OpenForge — MCTS Architecture Decision Record

**Status:** REJECTED in favour of Beam Search  
**Date:** 2026-06-26  
**Decision maker:** Engineering review (Amartya + Claude architectural debate)

---

## Original Proposal

LLM-guided Monte Carlo Tree Search (AlphaGo-style) as the escalation path in
the unified search controller. Activated when ASHA exhausts its budget and
all candidates score below 0.8. The LLM acts as the policy network selecting
which verifier layer to target next; the 5-layer deterministic verifier acts
as the value function.

---

## The 8-Point Critique and Honest Assessment

### 1. Tree Stability

**Concern:** MCTS assumes node statistics become more accurate over time.
LLM non-determinism means the same prompt produces different schematics,
making tree node statistics unreliable.

**Assessment:** Partially valid. The deterministic verifier means rewards are
stable even if transitions are not. Node statistics average over stochastic
transitions. With 3-5 visits per node, averages are meaningful. However, the
real constraint is budget: on a local GPU with ~15 total inference calls, most
nodes get visited once. The averaging benefit never materialises.

**Verdict:** Concern partially upheld. Not the strongest objection.

---

### 2. Expansion Cost

**Concern:** Every MCTS node expansion is expensive LLM inference. For the
same budget, Best-of-N sampling may achieve equal or better results.

**Assessment:** Correct and the strongest practical objection. At 3-8 seconds
per inference on a local GPU, a 15-node MCTS tree costs 45-120 seconds before
any verifier calls. Best-of-N generates 15 independent candidates and scores
them all for the same cost. MCTS earns its overhead only if tree state
dependency is strong — which has not been demonstrated for schematic repair.

**Verdict:** Concern upheld. Budget efficiency favours Best-of-N or beam search
for the current system.

---

### 3. Action Space

**Concern:** If the action is "target Layer X", the LLM is doing the repair.
MCTS is selecting which prompt to issue, not making design decisions itself.
How much decision-making does the search algorithm actually contribute?

**Assessment:** Correct and sharp. With 5 possible actions (one per verifier
layer) at each node, exhaustive enumeration at depth 2 requires 25 LLM calls.
That is tractable with beam search. MCTS overhead is not justified when the
action space is this small. MCTS is appropriate when the branching factor is
large (chess: ~35 moves) and exhaustive evaluation is impossible.

**Verdict:** Concern upheld. Beam search covers the action space more
efficiently than MCTS for branching factor ≤ 5.

---

### 4. Failure Regime Specificity

**Concern:** What specific failure regime exists where ASHA fails, SA cannot
repair, but MCTS succeeds? Why not beam search, Best-of-N, or evolutionary
search instead?

**Assessment:** The failure regime is theoretically defined as: compound
multi-topology designs requiring depth-4+ repair sequences where fix ordering
matters. However, this regime has not been empirically observed. The eval
benchmark does not yet exist. Building MCTS before measuring repair depth
is premature optimisation. Beam search covers the same theoretical ground
for depth ≤ 4 at lower implementation cost.

**Verdict:** Concern upheld. Beam search is the appropriate alternative.
MCTS deferred pending empirical evidence of depth > 4 failures.

---

### 5. Immediate Reward

**Concern:** OpenForge has an immediate deterministic evaluator at every step.
MCTS is designed for sparse or delayed rewards. Why use long-horizon planning
when you have immediate feedback?

**Assessment:** Correct and decisive. The 5-layer verifier provides a
continuous score after every graph modification. This is the hill-climbing
setting. MCTS's lookahead is a solution to a problem (sparse reward) that
OpenForge does not have. Every alternative — hill climbing, beam search,
evolutionary search — has equal access to the immediate reward signal and
uses it more efficiently than MCTS.

**Verdict:** Concern fully upheld. This is the primary theoretical argument
against MCTS for OpenForge. Immediate rewards make MCTS's lookahead redundant.

---

### 6. Search Depth

**Concern:** MCTS is strongest in deep decision trees. Schematic repairs
appear to require only a handful of edits. What evidence suggests depth > 4?

**Assessment:** No evidence exists. The repair depth distribution is unknown
until the eval benchmark runs. Most pin-role and topology violations in the
current test corpus appear to require 2-3 targeted moves. Beam search with
depth 4 covers the observed and plausible repair space.

**Verdict:** Concern upheld. Insufficient evidence for depth > 4 repairs.

---

### 7. Complexity vs Benefit

**Concern:** MCTS is the most complex algorithm proposed. Please estimate
implementation complexity, overhead, and expected improvement over ASHA + SA.

**Honest estimate:**
- Implementation: 3-4 Cursor sessions, significant test surface, tree data
  structures, UCB, policy prior integration, backup propagation.
- Overhead: 2-4x more inference calls than Best-of-N for equivalent quality
  on simple designs.
- Expected improvement over ASHA + SA: Unknown. Likely zero for single-topology
  designs. Possible non-zero for compound designs with depth > 3 repairs —
  but this has not been measured.
- Engineering effort: Not justified until the failure regime is confirmed.

**Verdict:** Concern upheld. Complexity is not justified by the expected
improvement given current evidence.

---

### 8. Empirical Evidence

**Concern:** Please cite papers demonstrating MCTS outperforms beam search or
Best-of-N for expensive LLM-guided graph synthesis with deterministic evaluators.

**Honest acknowledgement:** No such papers exist specifically for PCB schematic
synthesis. AFLOW (2024) applies MCTS to LLM workflow optimisation over code
structures, but the action space, reward structure, and domain are fundamentally
different. The transfer to PCB design is speculative.

**Verdict:** Concern fully upheld. LLM-guided MCTS for OpenForge is an
unvalidated research hypothesis.

---

## Decision

**MCTS is not implemented.** The escalation path is replaced with width-3
beam search over the same repair-move space as the SA polisher. Beam search:

- Covers the theoretical failure regime (depth ≤ 4 sequential repairs)
- Is implementable in one Cursor session
- Has no research risk
- Scales to depth > 4 if that regime is empirically confirmed

---

## Revised Architecture

```
ASHA exhausts budget, winner score < 0.8
        ↓
Beam Search Escalation (width=3, depth=4)
        - Enumerates all repair moves from critical violations
        - Applies each to all beam states
        - Scores all candidates with verify_schematic()
        - Keeps top 3 by score
        - Repeats for up to 4 steps
        ↓
Best beam candidate → SA polisher if score >= 0.8
                    → Human review queue if score < 0.8 after beam search
```

---

## Conditions for Revisiting MCTS

MCTS should be reconsidered only if the eval benchmark produces ALL of the
following empirical results:

1. Designs exist where ASHA + SA + beam search all fail (final score < 1.0)
2. Those designs have repair sequences of depth ≥ 5 where fix ordering matters
3. Beam search with width 3 fails because it prunes the correct path at step 3
   due to locally misleading intermediate scores
4. A depth-5 MCTS tree with 30+ node visits correctly identifies the optimal
   repair sequence on those designs

If conditions 1-4 are all confirmed, implement MCTS. If conditions 1-3 are
met but condition 4 is not tested, implement wider beam search (width=5)
before committing to MCTS complexity.

---

## What This Decision Means for the Research Paper

The decision to use beam search instead of MCTS is itself a research
contribution: it demonstrates that immediate deterministic rewards from a
physical verifier make long-horizon planning unnecessary for schematic repair,
in contrast to domains where MCTS is standard. This is a non-obvious finding
worth one paragraph in the system design section.
