# Expert-synthesis worksheets

Copy-ready templates for the workspace files listed in SKILL.md section 1, plus briefs for the
re-asks and escalations that synthesis typically needs.

## claims.md as JSON lines (machine-checkable variant)

Keep markdown for humans; when there are more than ~40 claims, also keep `claims.jsonl` so you can
filter with `jq` or Python.

```json
{"id":"C7","q":"Q2","src":"E2","type":"mechanism","claim":"FMM evaluates all pairwise forces in O(N)","evidence":"textbook complexity result","grade":"C","conf":0.85,"load_bearing":true,"depends":["A1"],"status":"conditional(N>=1e8)","anchor":".stack/out/computer-science-expert/20261019-1412-nbody.md:41"}
```

Useful queries:

```bash
jq -c 'select(.load_bearing and (.grade=="D"))' claims.jsonl          # validation gaps
jq -r '.q' claims.jsonl | sort | uniq -c | sort -n                      # thin sub-questions
jq -c 'select(.status|startswith("disputed"))' claims.jsonl            # open conflicts
```

## Coverage matrix

```markdown
| Q \ E | E1 | E2 | E3 | E4 | Seam? | Owner |
|-------|----|----|----|----|-------|-------|
| Q1 integrator choice | A | m |   |   | no | E1 |
| Q2 force algorithm   | a | A | A |   | no | E2 (+E3 measurement) |
| Q5 transport payload |   |   |   | m | yes (sim -> viewer) | none -> gap G1 |
```

## Assumption map

```markdown
| Id | Assumption | Held by | Kind (stated/implied-by-rec/implied-by-number) | Conflicts with | Claims depending | Load | Check | Result |
```

Load = (number of dependent load-bearing claims) x (impact if false: 1 low, 2 changes a component,
3 changes the recommendation). Check the top three by load before writing the answer.

## Conflict matrix

```markdown
| K | Q | Claims | Type T1-T6 | E-a position | E-b position | Rule (1-6) | Evidence used | Outcome | Residual | Escalated to | Status |
```

Outcome must be one of: `a wins`, `b wins`, `both, conditional on <A#>`, `both, split at <boundary>`,
`neither (new claim C#)`, `caller decides (T5)`, `pending <agent>`.

## Gap ledger

```markdown
| G | Type | Q | Load-bearing? | Cost to fill | Action | Agent / brief path | Result |
```

## Re-ask brief (to the owner of one disputed claim)

Send only to the expert who owns the claim, only about that claim. Self-contained:

```text
Goal: confirm, revise or withdraw one claim from your earlier report.
Your claim (C11, <path>:<line>): "<exact text>".
Counter-claim (C7, another expert, anonymous): "<exact text>", support: <evidence summary or path>.
Context: target regime is <N, hardware, constraints>. Glossary: <canonical terms used>.
Do: state whether your claim holds in this regime; give the decisive evidence (run it if you can,
cite primary sources otherwise); say what observation would change your answer.
Output: ## Result (holds / holds-if <condition> / withdrawn), ## Evidence, ## Confidence. Under 200 words.
Write nothing to disk unless you ran a benchmark; then save it under your out_dir and give the path.
```

Send it to the owning expert's agent type; it runs on its tier from config/models.json (pass no
model/effort, the pre-agent hook strips them). For a purely factual re-ask route to fact-checker
(MEDIUM tier) instead.

## Escalation brief to fact-checker

```text
Claim to verify (verbatim): "<claim>"
Scope: <versions / date range / platform list>
Return: supported | contradicted | unverifiable, with URL + access date and a quote under 15 words.
```

## Escalation brief to tester

```text
Behavioural claim: "<claim>"
Reproduce in: <repo path, command, input sizes>. Acceptance: <metric and threshold>.
Return the command, raw output path, and pass/fail per threshold. Do not modify source files.
```

## Extended worked example: decisions table and provenance appendix

Continuing the N-body example from SKILL.md.

| Decision | Chosen | Rejected | Deciding claims | Rule |
|---|---|---|---|---|
| force algorithm | Barnes-Hut, theta 0.6, GPU | FMM | C7, C11 (bench rerun, grade A) | 1 evidence, then 3 regime |
| integrator | KDK leapfrog, block time steps | RK4 fixed step | C3 (symplectic, bounded drift), C4 | 2 ownership (E1) |
| clocks | decoupled sim / render, viewer interpolates | lock-step 60 Hz | A3 rejected, O1 | assumption check |
| transport | server-side render or LOD stream | raw positions | Q5 derivation (12 MB/frame, 720 MB/s at 60 fps) | first-principles bound |
| browser API | WebGPU with WebGL2 fallback | WebGPU only | K4 pending fact-checker | hedge until verdict |

Provenance appendix shape:

```markdown
## Provenance
Intake: E1 physics-expert (opus/xhigh) <path>; E2 computer-science-expert (opus/xhigh) <path>;
E3 julia-expert (sonnet/high) <path>; E4 computer-graphics-expert (opus/high) <path>.
Claims: claims.md lines 1-58 (44 claims, 17 load-bearing, grades A:3 B:6 C:6 D:2).
Conflicts: conflicts.md (K1-K4). Gaps: gaps.md (G1 filled by derivation, G2 open).
```

## Seam checklist (run on every seam row)

- Units and scale of the handed-over quantity match on both sides?
- Rate: producer rate vs consumer rate; buffering or backpressure defined?
- Format and precision: serialisation, endianness, float width, schema version?
- Timing: clocks, ordering, latency budget split between the two sides?
- Failure ownership: who detects, who retries, who alerts when the hand-over fails?
- Capacity: the bound computed (bytes/s, ops/s) and compared with the channel's real capacity?
