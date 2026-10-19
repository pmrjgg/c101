---
name: red-teaming
description: "Red-teaming plans, designs, claims and agent workflows before they are executed: premortem, assumption inventory and attack, FMEA-lite failure-mode enumeration scored by severity x likelihood x detectability with severity overrides, abuse and misuse cases, dependency and single-point-of-failure analysis, argument stress tests, and an actionable, prioritized fix list. Load when critiquing or hardening any plan or design, when acting as plan-critic, or when a decision is expensive or irreversible."
when_to_use: "plan-critic reviews, architect design hardening, the critique phase of /plan-tournament, pre-launch and pre-migration reviews, stress-testing a recommendation or argument. For verifying one specific claim use adversarial-verification; for code-level threat modeling use security-review."
---

# Red-teaming

Assume the plan will fail and find out how, while changing it is still cheap. Every finding ends
as a concrete change to the plan with an owner and a check, or as an explicit, signed acceptance.
Red-teaming is defensive: it identifies weaknesses and fixes; it does not build exploits.

## 1. Set up

1. **Freeze the target**: path and version of the plan or design. Red-team a moving target and
   findings go stale.
2. **Extract**: goal, success criteria, constraints, horizon, owners. Missing or unmeasurable
   success criteria is finding #1 (Major) on its own.
3. **Pick the depth** by stakes:

| Tier | When | Techniques | Spawns |
|---|---|---|---|
| Quick | reversible, small blast radius, < 1 day of work | premortem (5 stories), top-5 assumptions, fix list | 0 |
| Standard (default) | plans and designs worth more than a day, any shared system | all of sections 2-7, FMEA top 10 rows | 0-3 perspective agents |
| Deep | irreversible, security- or data-critical, expensive, many teams | everything + `security-auditor` abuse cases, `adversarial-verifier` on top findings, `debate-moderator` on contested trade-offs | 4-8 |

## 2. Premortem

Prospective hindsight: imagining the failure as already happened surfaces more causes than asking
"what could go wrong".

Prompt (to yourself or to each perspective agent):
> It is <horizon> from now. This plan was executed exactly as written and failed badly.
> Write the post-incident story in 5 sentences: what failed first, why it was not caught, what it
> cost, and which decision in the plan made it possible.

- Produce 5-10 **distinct** stories; force spread across the categories: technical, data, scale
  and performance, dependency and vendor, people and process, security and abuse, cost and time,
  adoption and user behaviour, the agent stack itself (for agent workflows).
- One story = one root cause. Merge stories with the same root cause.
- Each story yields failure modes (section 4) and assumptions it falsifies (section 3).
- Prompt bank by category: [failure-mode catalog](references/failure-mode-catalog.md#premortem-prompts).

## 3. Assumption inventory and attack

List every assumption, explicit or implicit, in this table:

| ID | Assumption | Load-bearing for (plan step) | Type | Status | If false | Test / signpost |
|---|---|---|---|---|---|---|
| A1 | <one sentence, falsifiable> | P4 | technical / data / org / user / economic / environmental | verified / plausible / unverified / contradicted | <consequence> | <cheapest check, or the early signal to watch> |

Implicit-assumption detectors (read the plan once per detector):
- every number (capacity, latency, cost, duration, dataset size): where did it come from?
- every "just", "simply", "should", "will": the hidden work or hope behind it;
- every external system, API, quota, credential, team or person;
- every step without an owner or without a check;
- every happy path: what happens on timeout, partial failure, retry, duplicate, rollback;
- every ordering: what if steps overlap, run twice, or run in the wrong order;
- every "same as before": is the environment, version or load actually the same.

**Attack**: for each assumption that is load-bearing AND not verified, negate it and trace the
consequences through the plan ("if A1 is false, P4 fails at peak, and P5 removes the fallback").
Prioritize by load-bearing x vulnerability; for the top ones, add either a test before the
dependent step, a signpost (early observable warning) with a pre-decided response, or a hedge
(an action that limits damage if the assumption fails). This is RAND's assumption-based planning
applied at plan scale.

## 4. FMEA-lite

For each plan step or design component, list failure modes and score three 1-5 scales.

| Score | Severity S (impact if it happens) | Likelihood L (within the horizon) | Detectability D (before harm) |
|---|---|---|---|
| 1 | cosmetic, no user impact | remote, < 1% | caught automatically before release (types, tests, CI) |
| 2 | minor degradation, workaround exists | unlikely, 1-10% | standard monitoring alerts within minutes |
| 3 | partial loss of function, days of rework or delay | possible, 10-30% | manual review or delayed monitoring (hours-days) |
| 4 | major outage, recoverable data inconsistency, missed deadline | likely, 30-60% | found by users or customers |
| 5 | security breach, irrecoverable data loss, legal or safety issue, project failure | near certain, > 60% | silent: corrupt data or plausible wrong answers |

RPN = S x L x D (1-125). RPN multiplies ordinal scales, so equal RPNs can hide very different
risks; severity rules take precedence (the same reason the AIAG-VDA FMEA handbook replaced RPN
ranking with action priority):

| Priority | Rule (first match wins) |
|---|---|
| **Must fix before proceeding** | S = 5 and L >= 2; or S >= 4 and D >= 4; or RPN >= 45 |
| **Should fix** (owner + date) or accept explicitly with a signpost | RPN 20-44, or S >= 4 |
| **Accept and monitor** | everything else, unless the fix is trivially cheap (then just fix it) |

Row template:

| ID | Step | Failure mode | Effect | Cause | S | L | D | RPN | Priority | Fix |
|---|---|---|---|---|---|---|---|---|---|---|

Score L and D from evidence where possible (incident history, load numbers, existing alerts); mark
guessed scores with `~` and treat them as assumptions.

## 5. Abuse and misuse cases

For every entry point (API, form, file input, message consumer, scheduled job, agent prompt):

> As a <actor>, I <action> in order to <goal>, exploiting <weakness>. Prevented or detected by <control or "nothing">.

Actors to cycle through: anonymous attacker, authenticated malicious user, curious insider, buggy
or retrying client, automated scraper or bot, compromised dependency, operator error, and for agent
workflows the agent itself following injected instructions from fetched content.
Write cases at the level of requirements and controls. Code-level threat modeling (STRIDE, trust
boundaries, injection classes) goes to `security-auditor` with the `security-review` skill.

## 6. Dependencies and single points of failure

Inventory every dependency of the plan's success path:

| Dependency | Kind (service, data, person, vendor, quota, credential, tool, MCP server) | Used by steps | Redundancy | Failure behaviour (timeout, fallback) | Blast radius |
|---|---|---|---|---|---|

SPOF tests:
- **Removal test**: remove the node; does the goal still succeed? If not and there is no
  redundancy or fallback, it is a SPOF.
- **Coupling test**: does the plan put unrelated critical paths on one component (auth now depends
  on the main database)?
- **Bus factor**: a step only one person or one agent configuration can perform.
- **Quota and rate limits**: planned call rate vs documented limit, with headroom.
- **Plan DAG**: critical path, fan-in nodes (many steps wait on one), steps with no rollback.
- **Common-mode failure**: redundancy that shares a cause (two replicas in one zone, three agents
  on the same model reading the same source).

## 7. Claims and arguments

When the target is a recommendation, analysis or argument rather than a plan:

1. **Steelman** it in 3 sentences; attack the strongest version.
2. List the premises; mark the **weakest load-bearing premise**.
3. **Alternative explanations** for the evidence (at least 2).
4. **Base rate**: how often does this kind of claim or project succeed in general?
5. **Selection effects**: survivorship, cherry-picked examples, benchmark chosen after the fact.
6. **Goodhart check**: does the success metric measure the goal, or can it be satisfied without it?
7. **Crux**: the observation that would change the conclusion. If nobody can name one, the claim
   is not testable as stated.

Hand specific factual or technical claims to `adversarial-verifier`; contested trade-offs with two
defensible sides to `debate-moderator` (an orchestration agent: see the depth rule in section 11).

## 8. Fix list

Every Must and Should finding gets a fix in this shape:

| Fix | Addresses | Change to the plan (concrete) | Owner (agent or role) | Verification (how we know it worked) | Cost S/M/L | Priority |
|---|---|---|---|---|---|---|

Rules:
- **Fix hierarchy**, prefer the highest that is affordable: eliminate the failure mode > reduce
  likelihood > improve detection > limit the effect (blast radius, rollback) > accept with a signpost.
- A fix is a change to steps, order, checks, owners or design. "Be careful", "monitor closely"
  and "add more testing" without a named test are not fixes.
- **Proportionality**: expected loss = P(failure) x impact. Reject a fix whose cost exceeds the
  expected loss it removes, and say so. Over-engineering in the original plan is a finding too.
- Every fix states its verification as a check that can pass or fail (fits `validation-gates`).
- After fixes, re-score the affected FMEA rows; a Must row that stays Must blocks the plan.

## 9. Finding severity

| Severity | Definition |
|---|---|
| Blocker | plan must not proceed: a Must FMEA row, a contradicted load-bearing assumption, no rollback for an irreversible step |
| Major | likely to cause failure, large rework or missed goal; fix before the affected step |
| Minor | degrades quality or efficiency; fix when convenient |
| Nit | wording, structure, presentation |

Rank findings by severity, then by RPN, then by cost of fix (cheap fixes first within a tier).

## 10. Worked example: session store migration

Plan under review: P1 add `sessions` table in PostgreSQL; P2 dual-write sessions from the app to
Redis and PostgreSQL; P3 backfill existing sessions; P4 switch reads to PostgreSQL Friday 18:00;
P5 remove Redis after one week.

Premortem stories (condensed): (1) Monday 09:00 login storm exhausts the database connection pool
because every request reads the session; (2) users logged out after cutover because PG writes had
been failing silently while Redis writes succeeded; (3) a month later the sessions table holds 200M
rows and autovacuum lags because nothing expires sessions; (4) the backfill runs `KEYS *` on
production Redis and blocks it; (5) the Friday-evening cutover hits a thin weekend on-call.

Assumptions: A1 PostgreSQL absorbs peak session reads (3k/s) (unverified, load-bearing for P4);
A2 dual-write keeps stores consistent (contradicted: no transaction spans both stores);
A3 expiry is handled (implicit, unverified); A4 backfill is safe at 40M keys (unverified);
A5 rollback = flip the read flag (true only while dual-write continues and Redis exists).

| ID | Step | Failure mode | S | L | D | RPN | Priority |
|---|---|---|---|---|---|---|---|
| FM1 | P4 | connection pool exhausted by session reads at peak | 5 | 3 | 2 | 30 | Must (S5, L>=2) |
| FM2 | P2 | silent PG write failures, stores diverge | 4 | 4 | 5 | 80 | Must |
| FM3 | P1/P5 | no expiry, table bloat | 3 | 5 | 3 | 45 | Must (RPN) |
| FM4 | P3 | blocking key enumeration on production Redis | 5 | 2 | 2 | 20 | Must (S5, L>=2) |
| FM5 | P5 | Redis removed while rollback still needs it | 4 | 2 | 4 | 32 | Must (S4, D4) |
| FM6 | P4 | cutover during thin on-call | 3 | 3 | 2 | 18 | trivial fix, take it |

SPOF: after P4 every authenticated request depends on the primary database, coupling auth to
main-database incidents (a long migration lock now logs everyone out).

| Fix | Addresses | Change | Owner | Verification | Cost |
|---|---|---|---|---|---|
| F1 | FM1, A1 | dedicated session pool behind PgBouncer; load test at 2x peak before P4 | tester, code-optimizer | p99 session read < 10 ms at 6k/s on prod-sized staging | M |
| F2 | FM2, A2 | write PG first inside the request transaction, then Redis; continuous sampled compare job | planner step P2b | cutover gate: mismatch < 0.01% for 72 h | M |
| F3 | FM3, A3 | `expires_at` column + index + batched delete every 5 min (or daily partitions dropped after max session age) | implementer | row count flat over 7 days in staging soak | S |
| F4 | FM4, A4 | backfill with cursor-based `SCAN` (COUNT 1000) against a replica, rate-limited, resumable | implementer | replica latency unchanged during dry run | S |
| F5 | FM5, A5 | keep dual-write and Redis 14 days after P4; remove only after a rollback rehearsal | planner | rehearsal log: rollback < 5 min, zero lost sessions | S |
| F6 | FM6 | cutover Tuesday 10:00 with runbook and on-call present | planner | runbook reviewed | S |

Verdict: blocked until F1-F5 are in the plan (five Must rows); F6 is trivially cheap and goes in
with them. Re-score after fixes: FM1 L 3 -> 1; FM2 L 4 -> 2, D 5 -> 2; FM3 L 5 -> 1; FM4 L 2 -> 1;
FM5 L 2 -> 1, D 4 -> 2. No Must rows remain; FM1, FM2, FM4 and FM5 stay Should (S >= 4), watched
through the staging load test, the compare-job mismatch metric, replica latency during the backfill
and the rollback rehearsal.

## 11. Running a multi-agent red team

- Spawn 2-4 perspective agents in one message, each with `run_in_background: false` (you merge all
  of them; never rely on completion order), ONE lens and the frozen target path. At `budget="soft"`
  drop to the Standard tier with no new perspective agents; at `budget="hard"` run the Quick tier
  yourself and list unexamined categories as Open doubts. Lenses:
  `plan-critic` (missing steps, verifiability, over-engineering), `security-auditor` (abuse cases),
  a domain expert (technical failure modes), `first-principles-decomposer` (assumption attack).
- Independence: perspectives do not see each other's findings until merge.
- Merge: dedup by (step, root cause); keep the highest severity; keep every distinct fix idea.
- Verify the top findings that rest on a factual or technical claim with `adversarial-verifier`
  before they become Blockers; a red-team finding is itself a claim.
- Depth: perspective agents are leaves ("do not spawn subagents"). `debate-moderator` is an
  orchestration agent: spawn it only when `remaining_depth` >= 3 (the hook refuses orchestration
  agents below depth 6); otherwise argue both sides yourself or return the trade-off as an Open
  doubt. At `remaining_depth` 1-2 spawn only leaves; at 0 run all lenses yourself, sequentially, and
  say so.

## 12. Anti-patterns

- A list of generic risks that would fit any plan ("scope creep", "communication issues").
- Findings without a plan step, a mechanism, and a fix.
- Severity inflation: everything is critical, so nothing is.
- Red-teaming the author instead of the artifact.
- Fixes that add process or infrastructure larger than the risk (expected-loss check).
- Stopping at the first plausible failure story; the fifth story is usually the useful one.
- Treating red-team output as verified fact (route claims to verification).

## 13. Output

```markdown
## Result
Verdict: BLOCKED until F1-F5 are applied (5 Blockers, 1 Minor); all fixes cost S or M.
Top risks: FM2 silent divergence (RPN 80), FM1 pool exhaustion (S5), FM5 rollback removed early (S4/D4).
## Evidence
Premortem stories, assumption table, FMEA table, dependency/SPOF table, abuse cases (as applicable).
## Files
<out_dir>/<stamp>-<slug>.md — full red-team report; fix list also as a checklist for the planner.
## Open doubts
Guessed L/D scores (marked ~), assumptions needing a measurement before the plan can be cleared.
## Confidence
How completely the techniques covered the plan; which categories were not examined.
```

## References

- [Failure-mode catalog](references/failure-mode-catalog.md): premortem prompts by category and
  recurring failure modes for distributed systems, data migrations, releases, research plans,
  ML and LLM-agent workflows (including this stack), and project/organizational plans.
