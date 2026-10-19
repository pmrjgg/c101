# Pattern cards

One card per pattern: topology, owner, the brief elements that matter, termination, merge,
failure modes. Selection logic and cost formulas are in [../SKILL.md](../SKILL.md).

Notation: `->` spawn or hand-off, `=>` file hand-off, `||` concurrent, `[k]` k instances.

---

## 1. Single delegate

```
caller -> specialist => .stack/out/<specialist>/<ts>-<slug>.md
```

- **Owner**: the caller. **Participants**: one specialist chosen by domain.
- **Brief must carry**: goal, inputs as paths, constraints, acceptance criteria, output shape,
  where to write files. The child does not see your conversation.
- **Termination**: the child returns the output contract (Result, Evidence, Files, Open doubts, Confidence).
- **Merge**: none; you read Result and, if needed, the file at the given line anchors.
- **Failure modes**: under-specified brief (child guesses), wrong specialist (a Rust question to
  `cpp-expert`), asking for a full transcript back instead of a file path.
- **Upgrade trigger**: the child returns Open doubts that are themselves contested -> mediator or
  adversarial verify on those doubts.

## 2. Pipeline

```
planner => plan.md -> <domain expert, e.g. rust-expert> => diff -> tester => test-report -> validator => verdict
```

- **Owner**: `orchestrator` (multi-phase with gates) or the caller for 2-3 simple stages.
- **Key rule**: stages exchange FILES, not pasted text. Each stage brief names the upstream file and
  the exact section to consume.
- **Gates**: put `validator` (mechanical criteria) or `quality-control` (completeness, consistency)
  between phases whose failure is expensive to discover later.
- **Termination**: last stage passes its gate; or a gate fails twice -> re-plan (back to `planner`).
- **Failure modes**: gate that only re-reads the author's summary (must re-run commands), stage drift
  (stage 3 silently changes stage 1's interface), passing a 3k-line diff through the caller's context.
- **Within a workflow**: `pipeline(items, s1, s2, s3)` gives per-item chains with no barrier.

## 3. Fan-out / fan-in

```
caller -> [N] agentType ||  -> collation table (+ .stack/out/<caller>/<ts>-<slug>-results.json)
```

- **Owner**: `concurrent-dispatcher` (pure mechanics) or any agent with `concurrent-fanout` loaded.
- **Key rule**: items are independent and briefs are idempotent (deterministic output path per item).
- **Batching**: all Agent calls of a batch in ONE message, at most 20 per message; for N > 8 the main
  thread (no `<stack-context>` header) prefers `/fanout`, which pipelines without a per-batch barrier
  and validates a schema; a subagent sends batches of at most 20 Agent calls with
  `run_in_background: false`.
- **Termination**: every item has status ok | partial | failed after at most one retry.
- **Merge**: collation only (table, counts, failed ids). No content judgement; that belongs to a
  synthesizer or verifier downstream.
- **Failure modes**: hidden coupling between items (two items edit the same file), retrying hook
  denials, unbounded result text flooding the caller's context.

## 4. Swarm

```
swarm-coordinator -> [S] workers || -> [S] normalize || -> merge/dedup -> coverage ledger
```

- **Owner**: `swarm-coordinator`; `/swarm-run` for more than 6 shards when the caller is the main thread.
- **Differs from fan-out**: the coordinator designs the partition, tracks coverage of the whole job,
  dedups overlapping results and produces ONE merged answer. Workers may be heterogeneous.
- **Termination**: every shard in the ledger is done | failed | dropped, dropped ones logged with reason.
- **Merge**: dedup by an explicit key (file:line:class, canonical URL, normalized claim hash),
  then union, vote, or rank fusion. See the `swarm-execution` skill.
- **Failure modes**: shards too big (workers hit maxTurns and return partial), overlapping shards
  without dedup keys (double counting), the merge agent re-doing the work instead of merging.

## 5. Mesh / blackboard

```
mesh-router <-> .stack/blackboard/<task-id>/{GOAL.md, board.md, posts/NNNN-<agent>-<type>.md}
   round r: router reads board -> routes open items -> [P_r] specialists || post -> router indexes
```

- **Owner**: `mesh-router` (single writer of `board.md`; participants only add post files).
- **Use when**: specialists must see and react to each other's partial results (API contract between
  teams, threat model, cross-layer performance diagnosis).
- **Termination**: all done-criteria in GOAL.md met by evidence-backed decision posts; or quiescent for
  2 rounds; or max rounds (default 6); or open-item count did not fall for 2 rounds (stall -> force a
  decision).
- **Merge**: router writes decision posts, then FINAL.md; optionally `cross-domain-synthesizer`.
- **Failure modes**: everyone reads every post (cost explosion), participants editing others' posts,
  id collisions from parallel writers (pre-assign id blocks), never-ending objection ping-pong.
  Protocol details: `mesh-blackboard` skill.

## 6. Ensemble of experts

```
ensemble-assembler -> lead || specialists || challenger -> cross-domain-synthesizer (or mediator)
```

- **Owner**: `ensemble-assembler`.
- **Roles**: lead (owns the core sub-question), specialists (scoped sub-questions), challenger
  (attacks assumptions), integrator (runs AFTER the members, never alongside).
- **Brief must carry**: shared glossary and units, the member's scoped sub-question, the interface
  of its answer (what fields the integrator expects), out-of-scope list.
- **Termination**: all members returned; integrator produced a provenance table and a conflict matrix.
- **Failure modes**: overlap (two experts answer the same sub-question with no tie-break owner),
  missing discipline discovered at synthesis time, glossary drift (same word, different meaning).
  Details: `ensemble-assembly` skill.

## 7. Mediator vote

```
mediator -> [N] solvers || (independent) -> anonymize S1..SN -> [N] critique+rank || -> tally -> (debate) -> synth
```

- **Owner**: `mediator`; `/mediate` (main thread only) runs it with the tally computed in code.
- **Use when**: one question, several plausible competing answers, an objective-ish "best".
- **Rules**: solvers never see each other before critique; critique is blind (labels only);
  the voting rule is declared BEFORE votes are cast (Schulze default; Borda for many candidates with
  full rankings; approval for "acceptable set"; log pool for probabilities).
- **Termination**: winner with margin above threshold; otherwise one debate round between the top 2
  and a re-vote; still tied -> report tie with dissent.
- **Failure modes**: correlated voters (same agent, same framing), voting on complements, the
  synthesizer silently rewriting the winner into something nobody voted for.
  Math and tie-breaks: `mediator-voting` skill.

## 8. Judge panel

```
[N] attempts from distinct angles || -> [J] blind judges with rubric || -> aggregate -> winner + grafts
```

- **Owner**: `mediator` (with `judge-panel`) or `/plan-tournament` for plans.
- **Differs from mediator vote**: judges are not the authors; scoring is against a weighted rubric with
  anchored levels, aggregated by mean/median/trimmed mean.
- **Termination**: scores aggregated; inter-judge disagreement above threshold triggers one extra judge
  or a rubric clarification.
- **Failure modes**: rubric without anchors (judges score vibes), judges seeing author identity,
  synthesis that grafts incompatible pieces (check interface compatibility of grafts).

## 9. Adversarial verify

```
claim + evidence pointers -> [V] adversarial-verifier || (lenses: correctness, security, perf, repro, scope)
```

- **Owner**: whoever must act on the claim; `/review-verify` for code findings.
- **Rules**: default to refuted when evidence is insufficient; each verifier gets a distinct lens;
  survive iff at least ceil(V/2) verdicts are not refuted (2 of 3 standard).
- **Termination**: all verdicts in.
- **Failure modes**: sending the author's reasoning (anchors the verifier), V identical prompts
  (redundancy without diversity), verifying before dedup (pays V times per duplicate).

## 10. Loop-until-dry

```
round r: finders (varied angles) || -> dedup vs seen-set -> verify fresh -> if fresh==0: dry++ else dry=0
stop when dry == K (K=2 standard, 3 for audits)
```

- **Owner**: any orchestrator; built into `/research-sweep` and `/review-verify` style flows.
- **Key rule**: dedup against everything ever seen, not against confirmed only.
- **Vary the angle per round** (by container, by content, by entity, by time). Re-running the same
  finder prompt mostly re-finds the same items.
- **Hard cap**: max rounds by stakes (quick 2, standard 4, exhaustive 8) and the spawn budget.

## 11. Completeness critic

```
result -> critic: "what is missing?" -> gap list -> next round of work (or ship)
```

- **Owner**: `quality-control` (completeness vs request), `plan-critic` (plans), the critic stage of
  `/research-sweep` (modalities not run, claims unverified, sources unread).
- **Brief**: the original request verbatim, the result path, the list of modalities/shards/criteria
  that were planned. Ask for gaps ranked by impact with a concrete action per gap.
- **Termination**: no gap above the ship threshold, or remaining gaps accepted and listed as Open doubts.
- **Failure modes**: critic re-reviews quality instead of coverage; gaps without actions.
