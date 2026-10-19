---
name: tree-of-thought
description: "Deliberate search over reasoning paths: define states and thought granularity, generate diverse candidate steps, evaluate states with hard checks first and value or vote judgments second, choose BFS/beam, DFS with backtracking, best-first or MCTS-lite by problem shape, prune with thresholds and learned nogoods, budget the search, and distribute branches and evaluators across parallel subagents with a shared tree file. Load when a problem needs exploration with backtracking rather than one linear chain of reasoning."
when_to_use: "first-principles-decomposer and any agent facing proofs, constrained designs, plans, puzzles, algorithm design or multi-hypothesis diagnosis where early choices matter and partial solutions can be judged. Not for lookups, linear tasks, or problems where only final answers can be checked (use best-of-N sampling with a verifier instead)."
---

# Tree of thought

Tree of Thoughts (Yao et al., 2023) treats reasoning as search: a **state** is a partial solution, a
**thought** is a step that extends it, a **generator** proposes thoughts, an **evaluator** judges
states, and a **search algorithm** decides what to expand next and when to backtrack. On Game of 24
with GPT-4 it raised success from 4% (chain of thought) to 74% (breadth 5). Related designs: flat
sampling with majority vote (self-consistency, Wang et al., 2022), graph-structured thoughts that
merge branches (Besta et al., 2023), and MCTS over reasoning or actions (RAP, Hao et al., 2023;
LATS, Zhou et al., 2023). In this stack the tree is real: branches go to parallel subagents and
evaluators are independent agents or executed checks, not the same context grading itself.

## 0. When to use

| Problem shape | Method |
|---|---|
| early decisions constrain later ones, partial states can be judged, backtracking helps | tree of thought (this skill) |
| only final answers can be checked, and checking is cheap | best-of-N sampling plus verifier (flat; no tree) |
| a correct answer is likely on the first try | single chain; verify after |
| options are known; need to pick one | judge-panel or mediator-voting |
| the problem is to decompose into independent parts | planning-dag, not search |
| evaluating a partial state is no better than guessing | do not use ToT; its pruning would be random |

## 1. Define the search problem (write it down first)

```yaml
root: "<problem statement and constraints>"
state: "<what a partial solution contains, e.g. remaining numbers; accepted lemmas; chosen design decisions>"
thought: "<one step: an arithmetic operation; a lemma; one design decision; one hypothesis refinement>"
goal_test: "<how a complete solution is recognised>"
hard_checks: ["<executable or exact checks on partial states: compile, run test, compute, type-check, constraint check>"]
value_scale: "sure | likely | impossible  (or 1-10 with anchors)"
strategy: beam      # beam | dfs | best-first | mcts
params: {k: 4, b: 3, d_max: 4, tau: 2}   # tau on the summed sure/likely/impossible map (see the reference); 1-10 scale: tau on the mean, e.g. 4
budget: {max_states: 40, max_agent_calls: 30}
```

Thought granularity is the most important design decision. Too fine (a token, a sentence) and the
evaluator cannot tell good from bad; too coarse (a whole proof) and there is nothing to prune.
Choose the **smallest step whose result can be evaluated meaningfully**, preferably by a hard check.

## 2. Generate candidate thoughts

- k candidates per expanded node, typically 3-5. More only if the evaluator is cheap and reliable.
- Two generation modes:
  - **Propose**: one call returns k distinct thoughts at once, with an exclusion list of thoughts
    already in the tree (canonical form). Cheap, fewer duplicates, but candidates share one
    context's blind spots.
  - **Sample**: k independent calls (different agent types, ideally on different tiers, or
    framings). More diverse, more duplicates, k times the cost. Use for the first one or two depths, where diversity matters most.
- Diversity operators to request explicitly: refine, decompose, generalise, specialise, invert the
  approach, change representation, borrow from another field (analogical-transfer), relax a
  constraint then repair.
- Canonicalise and deduplicate before evaluation (normalise expressions, sort sets, strip wording).
  Duplicates waste evaluator budget and inflate apparent consensus.

## 3. Evaluate states

Evaluation order, cheapest reliable signal first:

1. **Hard checks** (executable, exact): arithmetic in Bash or Python, compiling, running a test,
   type-checking, a constraint solver, a benchmark, a Grep of the codebase. A failed hard check prunes
   the node with certainty; a passed goal-test check makes it a solution candidate.
2. **Value** judgments: each evaluator scores the state independently with a reason. Scales:
   - `sure / likely / impossible` mapped to a steep numeric scale (the original Game-of-24 setup used
     roughly 20 / 1 / 0.001) and summed over several evaluations. The sum ranks by optimism and does
     not veto: one "sure" outweighs any number of "impossible" votes, so an "impossible" that names a
     violated constraint is handled as a pruning rule (section 5), not through the sum;
   - 1-10 with written anchors (1 contradicts a constraint, 5 plausible with no evidence, 10 verified).
3. **Vote** judgments: one evaluator compares siblings and picks the most promising (or ranks them).
   Use when absolute scores are unreliable but comparisons are easy.
4. **Lookahead**: value(state) = best value after one or two cheap greedy rollouts. Costly; use when
   immediate states are hard to judge but near-complete ones are easy.

Evaluator independence: never let the generator score its own thoughts as the deciding signal
(self-preference). Use a different agent type (preferably on a different tier in config/models.json;
never a per-call model/effort) for fuzzy values; average 2-3 evaluators when the scale is noisy.
Record every score with its reason in the tree file; reasons are what make nogoods possible.

## 4. Choose the search strategy

| Shape | Strategy | Parameters |
|---|---|---|
| shallow (d <= 4), evaluator decent, want robustness | BFS / beam | beam b = 2-5, k = 3-5 |
| deep, goal recognisable, strong pruning signal | DFS with backtracking | threshold tau; nogood learning |
| uneven tree, reliable scalar values | best-first (priority queue on value) | global budget |
| noisy evaluator, need exploration vs exploitation | MCTS-lite (UCT) | c ~ sqrt(2) for rewards in [0, 1] |
| two or more independent sub-trees | split the problem; search each separately | per-subtree budget |

Formulas:

```
beam, branching k, beam b, depth d:   states generated  G = k + (d - 1) * b * k
                                       e.g. k = 4, b = 3, d = 4  ->  G = 4 + 36 = 40
evaluations                            E = G * e          (e evaluators per state)
DFS worst case                         k^d; with pruning keep effective branching near 1-2
UCT selection                          argmax_a  Q(a)/N(a) + c * sqrt( ln N(parent) / N(a) )
```

Beam with a **diversity reserve**: keep the top b-1 by value plus the best-valued node that differs
most from them (different first decision). It costs one slot and prevents the whole beam collapsing
into one family of near-duplicates.

## 5. Pruning and backtracking

Prune a node when any of these holds, and write the reason:
- a hard check failed (certain);
- value < tau after at least two independent evaluators agree (do not prune on one fuzzy score);
- an "impossible" vote names a violated constraint and a hard check or a second evaluator confirms it;
- it matches a **nogood**;
- it duplicates a node already in the tree (canonical form);
- depth limit reached without meeting the goal test.

**Nogood learning** (the search analogue of conflict-driven clause learning): when a subtree dies,
extract the reason as a reusable pattern ("any design that keeps a single writer cannot meet the
write SLO", "allocation-related causes ruled out: GC logs unchanged") and add it to the tree's nogood
list. Generators receive the list; evaluators prune matching nodes on sight. Nogoods are often the
most valuable output of a failed search.

Backtracking in DFS: when all children of a node are pruned, mark it `dead`, record the nogood, and
return to the parent's next-best child. Re-expanding a dead node needs new information (a new
nogood-free thought, a corrected check), never just another try.

## 6. Budget and stopping

Set the budget before starting (`max_states`, `max_agent_calls`, wall time); check `remaining_depth`,
`spawns_this_session` and `budget` in the `<stack-context>` header and fit the plan inside them. At
`budget="soft"` expand no new branches: verify the best state and stop (stop rule 2). At
`budget="hard"` spawn nothing except finishing agents (file-summarizer, quality-control, validator,
source-summarizer); return the best state, the frontier and the nogoods.

Stop when the first of these holds:
1. A solution passes the goal test **and** its verification (hard check, or adversarial-verifier for
   arguments and proofs).
2. Budget exhausted: return the best state, the open frontier with values, and the nogoods.
3. Plateau: the best value has not improved for two depths.
4. Frontier empty: everything pruned. Return the nogoods as a negative result ("no design with these
   constraints exists because ...") and the constraint whose relaxation would reopen the search.

## 7. Distributing branches across subagents

You are the coordinator: you own the tree file, the budget and every selection decision. Workers are
leaves.

Per wave (one depth for beam, one batch for best-first):
1. Pick the nodes to expand (strategy section 4).
2. **One message** with one generator Agent call per node, each with `run_in_background: false`
   (up to 20 per message). For more than ~8 homogeneous items: only if you are the main thread (no
   `<stack-context>` header), call the Workflow tool with name `fanout`, `items` = the node list,
   `promptTemplate` = the generator brief; as a subagent, send batches of up to 20 Agent calls per
   message. Each brief is self-contained: root, the path of accepted thoughts, constraints,
   nogoods, exclusion list, k, output schema, "do not spawn subagents".
3. Canonicalise and deduplicate the returned children.
4. Run hard checks yourself (Bash) or via `tester`; then **one message** with evaluator calls
   (`run_in_background: false`) for the survivors (value per node, or vote per sibling group).
5. Update the tree file, nogoods and budget; apply pruning; select the next wave.

Agent per role (tiers from config/models.json; never pass model/effort on the call):

| Role | Default | Why |
|---|---|---|
| generator | an ADVANCED-tier agent that owns the problem (mathematics-expert for proofs, architect for design, computer-science-expert for algorithms) | creativity is the bottleneck |
| hard check | Bash, or tester (MEDIUM tier) | exact signals are cheap |
| fuzzy evaluator | an agent type different from the generator, preferably on another tier (plan-critic for plans, validator, another domain expert) | reduces self-preference |
| format or constraint evaluator | a script, or validator (MEDIUM tier) | mechanical |
| final verifier | adversarial-verifier (ADVANCED tier) | refute before reporting |

Domain experts as generators: for a design search, generators can be different experts
(computer-science-expert for algorithmic branches, physics-expert for physical bounds); this is also
the cheapest diversity lever.

Depth limits: at `remaining_depth="1"` workers must be leaves (they are by design). At
`remaining_depth="0"`, run the search in your own context with small k and b (k = 3, b = 2) and
hard checks via Bash. Brief templates and the full tree schema: [search reference](references/search-reference.md).

## 8. Tree file

Keep it at `<out_dir>/<YYYYMMDD-HHMM>-<slug>/tree.json`; it is the only state that survives between
waves.

```json
{"root": "...", "strategy": "beam", "params": {"k": 4, "b": 3, "d_max": 4, "tau": 2},
 "budget": {"max_states": 40, "used": 17, "max_agent_calls": 30, "calls_used": 12},
 "nogoods": [{"id": "NG1", "pattern": "allocation-related cause", "evidence": "gc logs unchanged", "from": "n3"}],
 "nodes": [
  {"id": "n0", "parent": null, "depth": 0, "thought": "root", "status": "expanded"},
  {"id": "n2", "parent": "n0", "depth": 1, "thought": "pool default changed", "canon": "pool-size",
   "checks": [{"cmd": "grep -n maxPerHost ...", "result": "pass"}],
   "evals": [{"by": "E1", "score": "likely", "reason": "..."}], "value": 2.0, "status": "open"}
 ]}
```

Status values: `open`, `expanded`, `pruned(<reason>)`, `dead(<nogood id>)`, `solved`, `verified`.

## Worked example 1: Game of 24 (mechanics)

Input 4 9 10 13. State = remaining numbers; thought = one operation on two numbers; goal test = one
number equal to 24; hard check = exhaustive search on the remaining numbers (trivial for 3 numbers).
Depth-1 proposals (k = 5) and evaluation:

| Thought | New state | Hard check (solvable?) | Value |
|---|---|---|---|
| 13 - 9 = 4 | 4 4 10 | yes: (10 - 4) x 4 | sure |
| 10 - 4 = 6 | 6 9 13 | yes: 6 x (13 - 9) | sure |
| 13 - 10 = 3 | 3 4 9 | yes: (9 - 3) x 4 | sure |
| 9 + 13 = 22 | 4 10 22 | no | impossible: pruned |
| 4 x 9 = 36 | 10 13 36 | no | impossible: pruned |

With b = 3 the beam keeps three sure states and solves at depth 3: (13 - 9) x (10 - 4) = 24. The point
is not the puzzle: once a hard check exists for partial states, the LLM evaluator becomes a tie-breaker
and the search becomes reliable.

## Worked example 2: diagnosing a p99 regression (engineering)

Root: p99 latency of a service rose from 120 ms to 310 ms after a dependency upgrade; p50 unchanged.
State = set of accepted findings; thought = one hypothesis refinement with a cheap check; strategy =
beam (b = 2) with DFS-style nogoods; generators: a performance-minded expert and a language expert;
evaluator: tester runs the checks.

| Depth | Node | Thought | Check | Outcome |
|---|---|---|---|---|
| 1 | n1 | GC pressure from new allocation pattern | compare GC pause logs before and after | unchanged: dead, NG1 "allocation-related" |
| 1 | n2 | HTTP client connection-pool behaviour changed | diff lockfile and the client's changelog; Grep config | bump confirmed, changelog mentions pool defaults: likely |
| 1 | n3 | TLS handshakes increased (keep-alive change) | handshake rate metric | +4x: likely |
| 1 | n4 | N+1 queries introduced by ORM bump | query count per request | unchanged: pruned |
| 2 | n2a | pool exhaustion under burst: requests queue for a connection | pool wait-time histogram | p99 wait 180 ms: sure |
| 2 | n3a | handshakes are a symptom of n2a (new connections opened on exhaustion) | correlate handshake spikes with pool saturation | correlated: merged into n2a |
| 3 | n2a1 | restore previous pool size in config | load test, control vs change | p99 back to 125 ms: solved, verified |

Output: root cause n2a with the verifying experiment, NG1 recorded (it saves the next investigation
an afternoon), and the merge of n3a into n2a explained (the tree became a graph: two branches were
one cause seen twice).

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| all children look alike | propose mode without exclusions; one model | sample mode at shallow depths; vary agents; exclusion list |
| values all "likely" | evaluator cannot discriminate at this granularity | coarser thoughts, hard checks, or vote mode |
| beam converges on one family early | no diversity reserve | keep one diverse slot |
| budget gone at depth 2 | k and b too large for d | compute G before starting; cut k first |
| same dead end explored twice | no nogoods | record nogoods and pass them to generators |
| confident wrong answer | goal test not verified | hard check or adversarial-verifier before reporting |
| generator grades itself highly | self-evaluation | separate evaluator of a different agent type |

## Output

Follow output-contract. `## Result`: the solution (or best state), the path of thoughts with their
checks, and the stop reason. `## Evidence`: hard-check outputs and the verification of the final
state; evaluator reasons for decisive prunes. `## Files`: `tree.json` and check outputs under your
`out_dir`. `## Open doubts`: unexplored frontier nodes with values, and nogoods resting on fuzzy
evaluations only. `## Confidence`: high only when the solution passed a hard check or survived
adversarial verification; otherwise medium at best.
