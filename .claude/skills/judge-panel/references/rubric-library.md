# Rubric library

Ready rubrics with weights, gates and anchors (1 / 3 / 5; 2 and 4 lie between). Copy one into
`RUBRIC.md`, adjust weights to the caller's priorities BEFORE opening candidates, keep anchors
observable. Weights sum to 1.

## Contents
- Plans and task DAGs
- System architecture
- Code changes
- Research reports
- Visual design and generated images
- Prose and documentation
- Prompts and agent briefs
- Judge brief

## Plans and task DAGs

Gates: meets every hard constraint in the goal; has a rollback or abort path for irreversible steps;
no credentials or secrets in the plan.

| Criterion | w | 1 | 3 | 5 |
|---|---|---|---|---|
| feasibility | .25 | needs capabilities, access or effort that is not available | feasible, with unknowns named but not scheduled | every step maps to an available agent/tool; unknowns have spikes scheduled first |
| risk | .20 | top risks absent | risks listed, mitigations generic ("monitor closely") | risks ranked by impact x likelihood, each with a concrete mitigation and an early signal |
| cost | .15 | unbounded or unstated | single overall estimate | per-phase estimate, dominant cost driver named, cheaper alternative considered |
| verifiability | .20 | success stated as adjectives | most steps have checks; some lack thresholds | each step has a threshold and a named check (command, test, metric, source) |
| completeness | .20 | a stated requirement has no step | all requirements touched, edge cases thin | every requirement traced to a step; rollout, migration and cleanup included |

## System architecture

Gates: satisfies the stated hard non-functional requirements (latency, availability, data residency,
budget); no unmitigated single point of failure on the critical path.

| Criterion | w | 1 | 3 | 5 |
|---|---|---|---|---|
| requirement fit | .25 | misses a functional or hard NFR | meets all, some by assumption | meets all with a stated mechanism per requirement |
| simplicity and operability | .20 | many novel components, unclear ownership | moderate component count, standard ops | fewest moving parts that meet the requirements; runbooks, alerts and deploy story stated |
| performance headroom | .15 | no capacity model | rough capacity numbers | capacity model with 2x+ headroom at peak and the first bottleneck identified |
| failure isolation | .15 | one fault takes down everything | partial isolation, unclear blast radius | bulkheads, timeouts, retries with budgets, graceful degradation per dependency |
| evolvability | .15 | change requires rewrites across components | changes are local for expected features | explicit seams for the top 3 expected changes; reversible decisions marked |
| cost | .10 | not estimated | order-of-magnitude estimate | estimate per component at expected and peak load |

## Code changes

Gates: builds; existing tests pass; no secrets committed; no new lint errors at the project's level.
Give judges `tester` output as evidence; never let judges guess whether tests pass.

| Criterion | w | 1 | 3 | 5 |
|---|---|---|---|---|
| correctness | .35 | a failing case is known or easily constructed | correct on the main paths, edge cases unproven | edge cases handled and demonstrated by tests or reasoning with file:line |
| tests | .20 | none for new behaviour | happy-path tests | tests for edge cases and failure paths; a regression test for each fixed bug |
| design fit | .20 | fights the existing architecture or API conventions | consistent but adds avoidable surface | minimal API surface, follows local conventions, no leaked abstractions |
| maintainability | .15 | hard to follow, duplicated logic | readable, some long functions or unclear names | small cohesive units, clear names, comments only where intent is non-obvious |
| performance | .10 | measurable regression on a hot path | neutral, unmeasured | neutral or better, with a measurement where it matters |

## Research reports

Gates: every key claim has a citation; a `fact-checker` sample of 5 citations finds no fabricated
or misattributed source.

| Criterion | w | 1 | 3 | 5 |
|---|---|---|---|---|
| accuracy | .30 | contains a contradicted key claim | key claims supported, minor errors | key claims triangulated across 2+ independent sources |
| coverage | .20 | a sub-question unanswered | all sub-questions answered, some thinly | all answered; gaps and unknowns stated explicitly |
| source quality | .20 | mostly secondary or undated | mix, primaries for some key claims | primaries for all key claims, dated, conflicts of interest noted |
| synthesis | .15 | list of summaries | some cross-source comparison | explicit reconciliation of conflicting findings and a clear bottom line |
| uncertainty | .15 | uniform confidence | confidence stated overall | confidence per key claim with the reason it is not higher |

## Visual design and generated images

Gates: every required element present; any rendered text spelled correctly and legible; aspect
ratio and size as specified; transparent background where requested.

| Criterion | w | 1 | 3 | 5 |
|---|---|---|---|---|
| brief adherence | .30 | wrong subject, style or mood | right subject, one brief element missed | every brief element present and prioritized as asked |
| composition and hierarchy | .20 | no focal point, cluttered | clear focal point, uneven balance | deliberate hierarchy, eye path and negative space |
| typography and text | .15 | garbled or illegible text | legible, generic | correct, legible, paired and scaled with intent |
| color and accessibility | .15 | clashing, low contrast | harmonious, some low-contrast text | palette on brief; text meets WCAG AA contrast (4.5:1 normal text) |
| technical quality | .20 | artifacts, distorted anatomy or geometry | minor artifacts on close inspection | clean at full resolution, consistent lighting and perspective |

## Prose and documentation

Gates: no factual error on a load-bearing statement; answers the question asked.

| Criterion | w | 1 | 3 | 5 |
|---|---|---|---|---|
| accuracy | .30 | a wrong statement a reader would act on | accurate, some imprecision | precise, versions and conditions stated |
| task completeness | .25 | reader cannot complete the task | completes the main path | main path plus failure modes and prerequisites |
| structure | .20 | wall of text | headings, some buried essentials | essentials first, scannable, each section one purpose |
| concision | .15 | padding, repetition | mostly tight | every sentence earns its place |
| audience fit | .10 | wrong level of assumed knowledge | mostly right | terms defined exactly where this audience needs them |

## Prompts and agent briefs

Gates: self-contained (the receiver needs no conversation history); no secrets.

| Criterion | w | 1 | 3 | 5 |
|---|---|---|---|---|
| self-containedness | .25 | relies on unstated context | inputs given, some implicit expectations | goal, inputs (paths), constraints and context all explicit |
| acceptance criteria | .25 | "do a good job" | criteria present, partly subjective | checkable criteria with thresholds |
| output shape | .15 | unspecified | format named | exact schema, file location and length bound |
| constraints and safety | .15 | none | main constraints | constraints, prohibitions and escalation path (Open doubts) |
| economy | .20 | long, repetitive, contradictory | clear, some redundancy | shortest brief that meets the other criteria |

## Judge brief

```text
You are judge <Jk> on a blind panel. Do not spawn subagents. You did not author any candidate.
Rubric (read first, apply literally): <run>/RUBRIC.md
Candidates, in this order for you: <P3, P1, P2>   (order differs per judge and means nothing)
Files: <run>/P1.md ... <run>/Pn.md
Evidence from automated checks (if any): <run>/evidence/

Procedure:
1. For each gate, mark pass/fail per candidate.
2. Criterion by criterion (not candidate by candidate): read the anchors, score every candidate 1-5,
   and cite evidence for each score (section reference or a quote under 15 words).
3. Length, polish and confidence of tone are not criteria. Do not reward a candidate for matching
   its own stated angle; reward outcomes.
4. For each candidate name the single best idea another candidate could adopt ("steal").
Write this JSON to <run>/scores/<Jk>.json and repeat it as a fenced json block inside your ## Result
section (keep the other output-contract sections around it):
{"judge": "<Jk>", "gates": {...}, "scores": {"P1": {"<criterion>": n, ...}, ...},
 "evidence": {"P1": {"<criterion>": "...", ...}, ...}, "steal": {"P1": "...", ...}}
```
