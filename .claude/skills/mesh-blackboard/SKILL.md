---
name: mesh-blackboard
description: "Blackboard protocol for sub-agent meshes: directory layout .stack/blackboard/<task-id>/ (GOAL.md, board.md index, posts/NNNN-<agent>-<type>.md with frontmatter from/type/refs/status), the six post types and their status lifecycles, id-block allocation for parallel writers, routing rounds, quiescence and termination criteria, conflict handling, and final consolidation, with a helper script. Load when running or participating in a mesh."
when_to_use: "When specialists must react to each other's partial results over several rounds (API or protocol contracts, threat models, cross-layer diagnosis, designs where one discipline's answer changes another's), and whenever a brief points you at a .stack/blackboard/ directory."
---

# Mesh blackboard

A mesh is a set of specialists who never talk directly. They talk through files on a shared board.
The **router** (`mesh-router`) is the only agent that edits shared state: it allocates post ids,
routes open items each round, changes statuses, writes decisions and the final consolidation.
**Participants** only add new post files. This single-writer rule is what keeps parallel agents from
corrupting the board.

Templates for every post type, a full board example and the participant brief:
[post templates](references/post-templates.md). Helper script: [board.py](scripts/board.py).

## 1. Layout

```
.stack/blackboard/<task-id>/            task-id = <YYYYMMDD-HHMM>-<slug>
  GOAL.md          goal, done-criteria D1..Dn, participants + scope, budget, glossary, authority table
  board.md         router-owned: round log + generated index of all posts
  rounds.json      per-round stats written by `board.py index --round r`
  posts/NNNN-<agent>-<type>.md    one post per file, append-only
  .snap/           router-owned copies of filed posts (`board.py index` writes them, flags edits)
  FINAL.md         router's consolidation at termination
```

Create it with:

```bash
python3 .claude/skills/mesh-blackboard/scripts/board.py init .stack/blackboard/20261019-1500-plugin-abi \
  --goal "Define the host-call ABI and threat model for WASM editor plugins" \
  --criteria "ABI for host calls specified" "Capability model specified" "p99 host-call overhead budget agreed" "Threat model with mitigations" \
  --participants architect security-auditor rust-expert code-optimizer
```

Then fill GOAL.md's Participants (scope per agent), Glossary (terms and units) and Authority
(which agent's word wins on which sub-question, and why) before round 1.

## 2. Post format

```markdown
---
id: 0019
from: security-auditor
type: objection
to: rust-expert
refs: [0009]
status: open
round: 2
confidence: 0.8
criteria: [D1, D4]
---
# Shared-memory zero-copy ABI allows TOCTOU on host-validated buffers
<= 400 words. Evidence as file:line, command plus output excerpt, or URL plus access date.
```

Required keys: `id`, `from`, `type`, `status`, `round`. Use `refs` for every post that responds to
another, `to` when addressing a specific agent (`any` or omitted means router decides), `criteria`
for which done-criteria the post bears on, `confidence` (0..1) on claims, answers and objections.
Filename must be `NNNN-<from>-<type>.md` with the same id as the frontmatter.

## 3. Post types and status lifecycles

| Type | Purpose | Posted with | Router moves it to |
|------|---------|-------------|--------------------|
| `claim` | assertion bearing on a criterion | `open` | `supported` (evidence, no standing objection), `contested` (objection open), `rejected`, `superseded` |
| `evidence` | facts bearing on a post; a `Stance: <supports, undermines, withdraws or concedes> <id>` line under the title | `filed` | stays `filed` |
| `question` | request for information, addressed with `to` | `open` | `answered`, `dropped` |
| `answer` | reply to a question (refs it) | `filed` | `accepted`, `rejected` |
| `objection` | challenge to a claim (refs it), with the failure scenario | `open` | `sustained`, `overruled`, `withdrawn` |
| `decision` | router's ruling on a criterion or conflict (refs everything relied on) | `final` | `superseded` (only by a later decision) |

Open items = posts with status `open` or `contested`. Only `decision` posts with status `final`
satisfy a criterion. Participants never post decisions; the router never posts claims.

## 4. Router procedure

### Round 0: seed

1. `board.py init`, complete GOAL.md (criteria must be checkable: "p99 overhead under 2 microseconds
   measured by bench X", not "fast enough").
2. For each criterion, post one `question` (ids 0001, 0002, ...; `from: mesh-router`, `round: 0`)
   addressed to the participant who owns it per the authority table.
3. `board.py index DIR --round 0`.

### Round r >= 1

1. **Read state**: `board.py index DIR` (JSON summary: open items, unmet criteria, problems).
   Read the bodies of posts that are open or new since your last read; never the whole board.
2. **Route**: build at most one work package per participant (at most 5 items each):

   | Open item | Route to |
   |-----------|----------|
   | `question` with `to` | that agent |
   | `question` without `to` | owner of the sub-question per the authority table |
   | `claim` without evidence | its author (supply evidence) or a verifier: `fact-checker` (external fact), `tester` (runtime behaviour), `adversarial-verifier` (reasoning) |
   | `objection` with no rebuttal | the claim's author (one rebuttal, revision or concession) |
   | `objection` after rebuttal, not withdrawn | adjudication ladder, section 6 |
   | criterion with no claim | the owning participant: post a claim with evidence |
   | stale participant (routed twice, no posts) | drop it from routing; note in round log |

3. **Allocate ids**: `board.py ids DIR --agents <agents routed this round> mesh-router --block 10`
   (the router's own block is for decisions and for evidence it posts on behalf of one-off leaves).
   Put each agent's block in its brief and in the round log.
4. **Launch** all routed participants in ONE message, each Agent call with `run_in_background: false`
   (you index their posts before closing the round; never rely on arrival order) (more than 8 participants
   in a round means the mesh is too wide, split it). Use the participant brief from
   [post templates](references/post-templates.md). Brief = paths and post ids, never pasted posts.
5. **Close the round**, in this order:
   a. `board.py index DIR` and fix its `problems` (duplicate ids, bad filenames, unknown refs):
      rename or reject with a note in the round log; never silently delete.
   b. Apply the status rules (section 5) with `board.py set DIR <id> <status>`; post decisions
      that are now justified.
   c. `board.py index DIR --round r` to record `new_substantive` and `open_after`, then append the
      round-log row in board.md (routed items, id blocks, new posts, open after).
6. **Check termination** (section 7). If not terminating, go to round r+1.

## 5. Status rules (mechanical where possible)

| Condition after a round | Set |
|-------------------------|-----|
| Question has an answer that addresses it | question `answered`, answer `accepted` |
| Answer is off-topic or unsupported | answer `rejected`, question stays `open` (re-route once, then `dropped`) |
| Claim has at least one `evidence` or accepted answer supporting it and no `open` objection | claim `supported` |
| Claim has an `open` objection | claim `contested` |
| Objection author posts evidence `Stance: withdraws <objection id>` | objection `withdrawn`; claim back to `open` or `supported` |
| Claim author posts evidence `Stance: concedes <claim id>` | claim `rejected`, objection `sustained` |
| Author posts a revised claim refs the old one | old claim `superseded` |
| Adjudication (section 6) rules | objection `sustained` (claim `rejected` or revised) or `overruled` |
| Criterion's claims all `supported`, none contested | router posts `decision` (`criteria: [Dk]`, refs claims and evidence) |

## 6. Conflict handling

Ladder for a contested claim. Each step happens at most once per conflict.

1. **Rebuttal**: claim author answers the objection: rebut (`evidence` with `Stance: undermines
   <objection id>`), revise (new `claim` that refs the old claim and the objection), or concede
   (`evidence` with `Stance: concedes <claim id>`).
2. **Withdraw or persist**: objection author withdraws or adds new evidence. Repeating the same
   argument does not count; the router marks it persisted.
3. **Adjudicate** by conflict type:

   | Conflict type | Adjudicator |
   |---------------|-------------|
   | External fact (spec says X, version supports Y) | `fact-checker` |
   | Runtime or performance behaviour | `tester` or `code-optimizer` runs it; the measurement decides |
   | Reasoning, proof step, security argument | `adversarial-verifier` (defaults to refuted when evidence is thin) |
   | Within one participant's declared authority | authority table: that participant's position, with dissent recorded |
   | Trade-off or value judgment across disciplines | spawn `mediator` on the competing positions (needs remaining_depth >= 3; `/mediate` only if you are the main thread with no `<stack-context>` header), or `debate-moderator` for binary choices; otherwise return `Workflow name=mediate args={...}` as an Open doubt |

4. **Decide**: router posts a `decision` citing the adjudication, which side prevailed, and the
   dissent. The losing side may not re-open it without new evidence.

Never: delete or rewrite posts, let an exchange exceed two rebuttal cycles, or decide a factual
dispute by majority of participants.

## 7. Quiescence and termination

Per round r: `new_substantive(r)` = new claims + questions + objections; `open_after(r)` = open items
after status updates. `board.py index --round r` records both and prints `quiescent` and `stalled`.

Stop at the first true condition:

| # | Condition | Then |
|---|-----------|------|
| T1 | All criteria have a `final` decision (`all_criteria_met: true`) | Consolidate (section 8). |
| T2 | Quiescent: `new_substantive == 0` for 2 consecutive rounds | Consolidate; unmet criteria become Open doubts. |
| T3 | Stalled: `open_after(r) >= open_after(r-2) > 0` over rounds r-2 >= 1 (the seed round 0 never counts) while posts are still being written | Force decisions on the top 3 open items via section 6 step 3, then one final round, then consolidate. |
| T4 | Budget: `max_rounds` (default 6), `max_posts` (default 60), spawn headroom `H < 20` (`delegation-protocol`), header `budget="soft"` (finish the current round, route no new exploratory items) or `budget="hard"` (stop now; only file-summarizer, quality-control, validator, source-summarizer may be spawned) | Consolidate with what exists; state the cutoff; unmet criteria become Open doubts. |

Round sizing: P participants per round costs about `P * (c + B_r)` tokens, with `B_r` the board
material each reads. Keep `B_r` small: GOAL.md, board.md, and only the posts routed to that agent.

## 8. Consolidation

1. Post remaining `decision`s for criteria that can be decided from supported claims.
2. Write FINAL.md:

```markdown
# FINAL: <task-id>
## Outcome            one paragraph answer to GOAL
## Criteria
| id | status (met/unmet) | decision post | key claims/evidence | confidence | dissent |
## Decisions          one line each with post ids
## Open doubts        unmet criteria, unresolved objections, with the next action
## Stats              rounds, posts by type, participants, spawns, termination reason (T1-T4)
```

3. If 3 or more disciplines contributed and the outcome needs an integrated design, hand FINAL.md
   and the decision posts to `cross-domain-synthesizer`; otherwise return directly.
4. Return the output contract: Result = outcome + criteria table summary; Files = FINAL.md, board.md;
   Evidence = decision post ids; Open doubts = unmet criteria.

## 9. Participant rules (include in every brief)

- Read GOAL.md, board.md and the posts listed in your brief. Read other posts only if they are
  referenced by those.
- Write new files only, in `posts/`, using only your allocated ids. Never edit board.md, GOAL.md,
  or any existing post (including your own).
- One claim, question or objection per post. At most 400 words. Evidence is concrete: file:line,
  command plus output excerpt, URL plus date. No evidence means confidence at most 0.5.
- Objections state the failure scenario. Withdrawals and concessions are `evidence` posts with a
  `Stance: withdraws <id>` or `Stance: concedes <id>` line under the title; revisions are new claims that ref
  the old one. Never edit the old post.
- Address questions to other participants with `to`; the router will route them next round.
- Return per output-contract, short: Result = `Status:` line, then `<id> <type> <one-line title>` per
  post written; Open doubts for anything you could not post about.

## 10. Worked example (abridged)

Goal: host-call ABI and threat model for WASM editor plugins. Participants: `architect` (D1, D2),
`rust-expert` (D1 implementation), `code-optimizer` (D3), `security-auditor` (D4).

| Round | Activity | Open after |
|-------|----------|------------|
| 0 | Router posts 0001-0004, one question per criterion | 4 |
| 1 | architect claims capability-handle ABI with copy-in buffers (0005) and a capability model (0006); rust-expert claims zero-copy shared-memory buffers (0009); code-optimizer claims a 2 microsecond p99 budget with a bench plan (0013); security-auditor posts a threat list (0017) and asks whether plugins run with shared memory (0018) | 6 |
| 2 | security-auditor objects to 0009: a guest thread can rewrite a buffer between host validation and use (0019, TOCTOU); rust-expert answers 0018: shared memory is enabled (0023) | 6, 0009 contested |
| 3 | rust-expert revises to copy-in/copy-out (0024 supersedes 0009); code-optimizer measures copy-in at 0.38 microseconds p99 for 4 KiB with a per-call latency harness (0028), supporting 0005 and 0013; security-auditor posts evidence mapping each threat in 0017 to a mitigation and to a capability check in 0006 (0032), supporting 0017 and 0006 | 2 (0019, 0024) |
| 4 | security-auditor posts `Stance: withdraws 0019` citing 0024's copy-out (0033), so 0024 is supported; router posts decisions on D1-D4 (0037-0040), each citing only supported claims | 0 |

Id blocks came from `board.py ids ... --block 4`, which is why numbering has gaps.

Termination T1 after round 4 (all four criteria have `final` decisions). FINAL.md records the dissent: rust-expert notes zero-copy could return for
read-only buffers mapped immutable, left as an Open doubt with a proposed follow-up benchmark.
