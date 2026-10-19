# Blackboard templates

Copy-ready templates for the mesh protocol in [../SKILL.md](../SKILL.md). Ids, agent names and
paths below are examples.

## GOAL.md

```markdown
# Goal
Define the host-call ABI and the threat model for WASM editor plugins so that the runtime team can
start implementation on 2026-11-02.

## Done criteria
- [ ] D1: Host-call ABI specified (signatures, ownership of buffers, error model) in a decision post
- [ ] D2: Capability model specified (what a plugin can request, how the user grants it)
- [ ] D3: p99 host-call overhead budget agreed and backed by a benchmark plan (bench name + harness path)
- [ ] D4: Threat model lists assets, trust boundaries, top 8 threats, each with a mitigation or an accepted risk

## Participants
- architect: overall ABI shape, capability model (D1, D2)
- rust-expert: implementability in the wasmtime-based host in crates/plugin-host (D1)
- code-optimizer: overhead budget and benchmark design (D3)
- security-auditor: threat model, review of every ABI decision for isolation breaks (D4, objections on D1/D2)

## Budget
- max_rounds: 6
- max_posts: 60
- words_per_post: 400

## Glossary
- host call: a guest-to-host function import invocation, measured from guest call to guest resume
- capability handle: opaque u32 issued by the host, scoped to one plugin instance
- overhead: wall time minus the host function's own work, in microseconds, release build, M-series laptop

## Authority
- isolation and threat severity: security-auditor (owns D4; may block any D1/D2 decision with a sustained objection)
- implementability in our host: rust-expert
- performance numbers: measurements by code-optimizer; opinions do not override a benchmark
- trade-offs across these: router decision citing GOAL priorities (security > latency > ergonomics)
```

## Post templates

### claim

```markdown
---
id: 0005
from: architect
type: claim
refs: [0001]
status: open
round: 1
confidence: 0.7
criteria: [D1]
---
# Host calls take capability handles and length-prefixed copy-in buffers
Claim: every host import has the shape `fn(handle: u32, ptr: u32, len: u32) -> i64` where negative
values are error codes and the host copies `len` bytes out of guest memory before validating.
Why: single validation point; no guest-visible host pointers.
Evidence: wasmtime host-function pattern in crates/plugin-host/src/imports.rs:40-88 (current prototype).
Would change my mind: a benchmark showing copy cost above 25% of the D3 budget for typical payloads.
```

### evidence

```markdown
---
id: 0028
from: code-optimizer
type: evidence
refs: [0005, 0013]
status: filed
round: 3
criteria: [D1, D3]
---
# Copy-in adds 0.38 us p99 at 4 KiB, well inside the 2 us budget of 0013
Stance: supports 0005
Command: `cargo bench -p plugin-host --bench hostcall_latency -- copy_in_4k`
Result excerpt: `copy_in_4k n=100000 p50=0.36us p99=0.38us max=1.21us` (per-call `Instant` samples,
sorted; criterion's `time: [lo est hi]` is a confidence interval of the mean, never a percentile)
Harness: crates/plugin-host/benches/hostcall_latency.rs:12-74 (harness = false). Release profile, M3 Pro, 2026-10-19.
```

### question

```markdown
---
id: 0018
from: security-auditor
type: question
to: rust-expert
refs: [0004]
status: open
round: 1
criteria: [D1, D4]
---
# Do plugin instances run with shared memory and the threads proposal enabled?
Need: whether a guest can have a second thread writing linear memory during a synchronous host call.
Decision that depends on it: whether any zero-copy ABI is a TOCTOU risk in the threat model.
```

### answer

```markdown
---
id: 0023
from: rust-expert
type: answer
refs: [0018]
status: filed
round: 2
confidence: 0.85
criteria: [D1]
---
# Yes: plugins get shared memory and threads, so guest memory can change during a host call
Our engine config enables the threads proposal and plugins import a shared memory:
crates/plugin-host/src/engine.rs:31. Another guest thread can therefore write linear memory while
the host is inside a synchronous host call. Without shared memory there would be no concurrent writer.
```

### objection

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
# 0009 zero-copy ABI is a TOCTOU hazard if plugins get shared memory (open question 0018)
Failure scenario: host validates a path string in guest memory, guest thread rewrites it to
`../../.ssh/id_ed25519` before the host opens it; host opens the attacker path with the plugin's
capability. Required fix: copy-in before validation, or disable shared memory for plugins.
```

### decision (router only)

```markdown
---
id: 0037
from: mesh-router
type: decision
refs: [0005, 0024, 0028, 0019, 0023, 0033]
status: final
round: 4
criteria: [D1]
---
# D1 decided: capability handles + copy-in/copy-out buffers
Decision: ABI per 0005 as revised by 0024 (copy-in before validation, copy-out on return).
Basis: shared memory is enabled (0023), so the TOCTOU objection 0019 was valid against 0009; it was
withdrawn (0033) once 0024 replaced zero-copy. Copy-in costs 0.38 us p99 at 4 KiB (0028), inside
the D3 budget of 2 us.
Dissent: rust-expert (0024 note) prefers zero-copy for read-only immutable mappings; recorded as an
Open doubt with a follow-up benchmark.
```

## Participant brief (router -> participant)

```
<one-line GOAL from GOAL.md>
MESH: .stack/blackboard/20261019-1500-plugin-abi/      ROUND: 3      YOU: rust-expert
READ: GOAL.md, board.md, and posts 0009, 0019, 0023 (read other posts only if these reference them)
YOUR ITEMS THIS ROUND:
 1. 0019 objection to your claim 0009 -> rebut with evidence, revise (new claim refs 0009, 0019), or
    concede (evidence post with a `Stance: concedes 0009` line under its title)
 2. D1 needs implementability evidence for copy-in/copy-out -> include file:line in the revised claim
WRITE: new files only in posts/, ids 0024..0027 only, filename NNNN-rust-expert-<type>.md,
  frontmatter keys id, from, type, to?, refs, status (claim/question/objection: open; evidence/answer: filed),
  round: 3, confidence (claims/answers/objections), criteria
RULES: never edit board.md, GOAL.md or any existing post; one claim/question/objection per post;
  <= 400 words; concrete evidence (file:line, command + output excerpt, URL + date)
RETURN: output-contract; Result = Status line, then one line per post: <id> <type> <title>
```

## board.md after round 2 (excerpt)

```markdown
# Board: 20261019-1500-plugin-abi

Router-owned. Participants never edit this file.

## Round log
| round | routed (agent: post ids) | id blocks | new posts | open after |
|-------|---------------------------|-----------|-----------|------------|
| 0 | router seeds D1-D4 questions | mesh-router 0001-0004 | 4 | 4 |
| 1 | architect: 0001, 0002; rust-expert: 0001; code-optimizer: 0003; security-auditor: 0004 | architect 0005-0008, rust-expert 0009-0012, code-optimizer 0013-0016, security-auditor 0017-0020 | 6 | 6 |
| 2 | security-auditor: review 0005, 0009; rust-expert: 0018 | security-auditor 0019-0022, rust-expert 0023-0026 | 2 | 6 |

## Index
<!-- index:start -->
| id | rnd | from | type | to | refs | status | crit | title |
|----|-----|------|------|----|------|--------|------|-------|
| 0005 | 1 | architect | claim |  | 0001 | open | D1 | Host calls take capability handles and length-prefixed copy-in buffers |
| 0009 | 1 | rust-expert | claim |  | 0001 | contested | D1 | Zero-copy shared-memory buffers for host calls |
| 0018 | 1 | security-auditor | question | rust-expert | 0004 | answered | D1,D4 | Do plugin instances run with shared memory and the threads proposal enabled? |
| 0019 | 2 | security-auditor | objection | rust-expert | 0009 | open | D1,D4 | 0009 zero-copy ABI is a TOCTOU hazard if plugins get shared memory (open question 0018) |
| 0023 | 2 | rust-expert | answer |  | 0018 | accepted | D1 | Yes: plugins get shared memory and threads, so guest memory can change during a host call |
<!-- index:end -->
```

(The real index lists every post; rows trimmed here.) Blocks were allocated with
`board.py ids DIR --agents <routed agents> --block 4`.

The index block is regenerated by `board.py index`; everything outside the markers is router prose.

## Choosing who answers an unaddressed question

| Question is about | Route to |
|-------------------|----------|
| A participant's own claim | that participant |
| An external fact (spec, version, paper) | `fact-checker` or `quick-researcher` as a one-off leaf, answer posted by the router citing it |
| Runtime behaviour of code in the repo | `tester` (one-off) or the participant owning that code |
| A discipline no participant covers | add a participant for one round only (its brief says so), or answer via a one-off expert call |
| Value trade-off | do not route; it becomes a decision item for the router |

One-off leaves (not participants) do not write posts. The router writes their result as an
`evidence` post with `from: mesh-router` and the leaf's output path in the body.

## Participant anti-patterns the router rejects

- Editing an existing post (even a typo fix): `board.py index` flags it; restore the filed copy from
  `.snap/` (the command is in the problem line) and log it.
- Posting a decision: re-type as a claim (router renames the file and fixes frontmatter, logs it).
- Bundling three claims in one post: ask for a split next round; index the first only.
- Evidence without a pointer ("benchmarks show"): the post stays `filed` but does not count as
  support, so the claim it backs stays `open` (or `contested`); note it in the round log; confidence
  capped at 0.5.
- Ids outside the allocated block: renumber and log; repeated offence drops the participant.
