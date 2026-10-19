# Tree-of-thought search reference

Pseudocode for the four strategies, the worker briefs, and the full tree-file schema. "expand" means
one wave of parallel generator calls; "evaluate" means hard checks first, then one wave of parallel
evaluator calls (SKILL.md sections 3 and 7).

## Beam search (default)

```text
frontier = [root]
for depth in 1..d_max:
    children = expand(frontier, k)                 # one message, one generator call per node
    children = dedupe(canonicalise(children))
    children = [c for c in children if hard_checks(c) != FAIL and not matches_nogood(c)]
    for c in children: if goal_test(c) and verify(c): return c
    score(children)                                 # one message of evaluator calls
    prune(children, tau, min_agreeing_evaluators=2)
    frontier = top(children, b - 1) + [most_diverse(children)]   # diversity reserve
    if budget_exhausted() or plateau(2): break
return best(frontier), frontier, nogoods
```

## DFS with backtracking and nogoods

```text
def dfs(node):
    if goal_test(node) and verify(node): return node
    if node.depth == d_max or budget_exhausted(): return None
    kids = evaluate(dedupe(expand([node], k)))
    kids = sorted([c for c in kids if c.value >= tau and not matches_nogood(c)], by value desc)
    for c in kids:
        r = dfs(c)
        if r: return r
    node.status = dead
    nogoods.add(extract_reason(node, kids))       # reusable pattern, with evidence
    return None
```

DFS fits when the goal is recognisable and pruning is strong; it is sequential by nature, so
parallelise inside each expansion (k generators at once) and across the top 2-3 root children
(independent DFS runs, one per subagent wave) rather than across depths.

## Best-first

```text
pq = max-heap keyed by value; push(root)
while pq and not budget_exhausted():
    n = pop(pq)
    if goal_test(n) and verify(n): return n
    for c in evaluate(dedupe(expand([n], k))): if not pruned(c): push(pq, c)
```

Batch it: pop the top m nodes (m = 3-8) per wave and expand them in one message.

## MCTS-lite (UCT)

```text
repeat until budget:
    node = root
    while node fully expanded and not terminal:
        node = argmax_child( Q(c)/N(c) + c_uct * sqrt( ln N(node) / N(c) ) )     # c_uct ~ 1.41
    if not terminal: node = add_child(expand([node], 1))
    reward = rollout(node)            # cheap greedy completion, scored in [0, 1] by a hard check if possible
    backpropagate(node, reward)       # N += 1, Q += reward along the path
return child of root with max N
```

Use when evaluations are noisy and repeated sampling helps. Rollouts must be cheap (a script, or a
LOW/MEDIUM-tier agent from config/models.json); otherwise MCTS burns the budget on rollouts.

## Generator brief

```text
You are a generator in a tree search. Do not spawn subagents. Do not evaluate other branches.
Problem (root): <root statement and constraints>
Accepted path so far (oldest first):
  1. <thought>  [check: <result>]
  2. ...
Known dead ends (nogoods), do not propose anything matching these:
  - NG1: <pattern> (evidence: <short>)
Already proposed at this node (canonical forms), do not repeat: <list>
Task: propose <k> distinct next steps. Each must be a single <thought unit> and must differ from the
others in approach, not only wording. Use these operators across the set: <refine | decompose |
invert | change representation | borrow from another field | relax-then-repair>.
Return JSON: [{"thought": "...", "canon": "<short canonical key>", "rationale": "<= 30 words",
"suggested_check": "<cheapest exact check, if any>"}]
```

## Value-evaluator brief

```text
You are an evaluator in a tree search. Do not spawn subagents. You did not generate these states.
Problem: <root>. Goal test: <goal>. Constraints: <list>. Nogoods: <list>.
State to judge (path of thoughts and check results): <...>
Judge whether this state can still reach a valid solution within <remaining depth> steps.
Answer one of: sure (you can see a completion; give it), likely (no contradiction, plausible),
impossible (name the violated constraint or the reason; this will become a nogood).
Return JSON: {"score": "sure|likely|impossible", "reason": "<= 50 words", "completion": "<if sure>"}
```

## Vote-evaluator brief

```text
Problem: <root>. Sibling states (anonymised S1..Sm): <list with paths and check results>.
Rank them by how likely each is to lead to a valid solution. Return JSON:
{"ranking": ["S3", "S1", ...], "reason": "<= 60 words", "impossible": ["S2: <reason>"]}
```

## Using the fanout workflow for large expansions (main thread only)

When a wave has more than ~8 nodes and you are the main thread (no `<stack-context>` header), call
the Workflow tool with name `fanout` with `items` = the frontier node
records (id, path, nogoods, exclusions), `agentType` = the generator agent, `promptTemplate` = the
generator brief with `{{item}}` in place of the node-specific parts, and a `schema` matching the
generator JSON. It returns `{results, failed}`; retry policy is built in (one retry on null). Merge
`results` into the tree file yourself; never let workers write to it. A subagent has no Workflow
tool: send batches of up to 20 Agent calls per message (`run_in_background: false`) instead.

## Tree-file schema

```json
{
  "root": "string",
  "spec": {"state": "string", "thought": "string", "goal_test": "string", "hard_checks": ["string"]},
  "strategy": "beam | dfs | best-first | mcts",
  "params": {"k": 4, "b": 3, "d_max": 4, "tau": 2, "c_uct": 1.41},
  "budget": {"max_states": 40, "used": 0, "max_agent_calls": 30, "calls_used": 0},
  "nogoods": [{"id": "NG1", "pattern": "string", "evidence": "string", "from": "node id", "certain": true}],
  "nodes": [{
    "id": "n7", "parent": "n2", "depth": 2,
    "thought": "string", "canon": "string",
    "checks": [{"cmd": "string", "result": "pass | fail | n/a", "output": "path"}],
    "evals": [{"by": "E1", "agent": "validator", "score": "sure | likely | impossible | 1-10", "reason": "string"}],
    "value": 0.0, "N": 0, "Q": 0.0,
    "status": "open | expanded | pruned(reason) | dead(NGx) | solved | verified",
    "merged_into": null
  }]
}
```

`certain: true` marks nogoods established by hard checks; nogoods from fuzzy evaluations stay
`false` and are listed under Open doubts in the final report.

## Value mapping for sure / likely / impossible

Sum over e evaluations with a steep map (sure 20, likely 1, impossible 0.001). With e = 3: three
"likely" = 3; one "sure" plus two "likely" = 22; any state with two "impossible" and one "likely"
scores ~1.0 and falls below a state with three "likely". Set tau on this raw sum; the default
tau = 2 (SKILL.md spec) keeps states with at least two "likely" and no more than one "impossible".
The sum ranks by optimism and does not veto: {sure, impossible, impossible} = 20.002 beats three
"likely" = 3. Prune on an "impossible" only when it names a violated constraint and a hard check or
a second evaluator confirms it.
