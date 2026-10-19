---
name: swarm-execution
description: "Running a swarm in this stack: sharding strategies (by file, source, hypothesis, parameter grid, time window), shard sizing formulas, the worker brief template, heterogeneous swarms, retries and shard splitting, the coverage ledger, dedup keys, merge/reduce strategies and logging dropped shards; when to switch to /swarm-run. Load when partitioning a large job across many workers."
when_to_use: "When a job is too big for one agent and must be split into shards whose results are deduplicated and merged, e.g. auditing a large codebase, sweeping many sources, testing many hypotheses or exploring a parameter grid; also when acting as the merge stage of /swarm-run."
---

# Swarm execution

A swarm is **partition + workers + ledger + merge**. The coordinator owns coverage of the whole
universe of work; each worker owns exactly one shard. The output is ONE merged result plus a ledger
that proves which units were covered, which failed, and which were dropped and why.

Commands, the shard planner script and normalization snippets: [shard recipes](references/shard-recipes.md).
Merge mechanics in depth (rank fusion, quorum, tree reduce): [merge and reduce](references/merge-reduce.md).

## 0. Merge-only guard

If your brief says MERGE MODE or hands you per-shard results to merge (you are the merge stage of
`/swarm-run`), do NOT spawn, re-partition, re-run workers or re-do shard work. Go to sections 7-9: build the ledger from the
per-shard statuses, dedup, merge, report coverage. Missing or failed shards are reported, not redone.

## 1. Procedure

1. **Define the unit and the universe U.** Unit = file, URL, sub-question x modality, hypothesis,
   grid point, or time window. Enumerate U with a command and record `|U|` (section 2 commands).
   A universe you cannot enumerate cannot be covered; say so and sample deliberately.
2. **Pick the sharding strategy** (section 2) and **the dedup key** (section 8) together. The worker
   output format must carry every field of the key, or the merge cannot dedup.
3. **Size shards** (section 3). Compute S. Budget per `delegation-protocol`: planned spawns
   `2S + 1 + ceil(0.15 S)` (workers, normalize, merge, retry reserve) must be at most `H/2`, where
   `H = max_spawns_per_session - spawns_this_session` (`config/policy.json`, 400 as shipped).
   If the header says `budget="soft"`, launch no shards beyond the planned set and no exploratory
   XSHARD follow-ups; if `budget="hard"`, launch nothing except `file-summarizer`, `quality-control`,
   `validator`, `source-summarizer`, mark unlaunched shards `dropped` (reason `budget`) and list them
   as Open doubts.
4. **Write the ledger** with every shard `pending` before launching anything (section 7).
5. **Choose execution** (section 10): direct Agent calls in one message for S <= 6; `/swarm-run` for
   S > 6 homogeneous only if you are the main thread (no `<stack-context>` header). As a subagent run
   batches of at most 20 Agent calls yourself, or return `Workflow name=swarm-run args={...}` as an
   Open doubt; heterogeneous batches of at most 8 per message; at most 20 per message ever.
6. **Launch.** All shards of a batch in ONE message, every Agent call with `run_in_background: false`
   (you need each result before ingesting); key returns by shard id, never by arrival order. Set each
   shard to `running`.
7. **Ingest returns.** Parse each worker's Status and SHARD lines, update the ledger, apply the retry table
   (section 6). Never retry hook denials.
8. **Merge** (section 9) with the declared key and strategy. Record contributing shards per item.
9. **Verify the ledger invariant**: units over leaf shards sum to `|U|`, no unit in two shards
   unless overlap was intentional, every shard in a terminal status.
10. **Return** the output contract: merged result (or its path), coverage line, dropped list, ledger path.

## 2. Sharding strategies

| Strategy | Unit | Partition method | Balance by | Typical workers | Main pitfall |
|----------|------|------------------|------------|-----------------|--------------|
| By file / package | source file | group by package or directory (cohesion), then bin-pack | LOC or bytes | `reviewer`, `security-auditor`, `code-quality-analyst`, language experts | bugs spanning shards; add an interfaces shard or the XSHARD channel |
| By source | URL, domain, corpus | sub-question x modality (web, papers, crawl) | expected pages | `web-searcher`, `paper-researcher`, `web-crawler`, `web-scraper` | syndicated duplicates; canonicalize URLs |
| By hypothesis | hypothesis | one hypothesis per shard, each with a discriminating test | expected effort | `debugger`, experts, `adversarial-verifier` | non-exclusive hypotheses; require a test that separates them |
| By parameter grid | grid point | Cartesian, Latin hypercube, or coarse-to-fine | runtime per point | `tester`, `code-optimizer`, `julia-expert` | grid explosion; coarse pass first, refine near the best |
| By time window / entity | commit range, month, tenant | contiguous windows | events per window | `debugger`, `deep-researcher`, `web-scraper` | boundary events counted twice; half-open windows |
| By lens | the same artifact | one lens per worker | n/a | `reviewer`, `security-auditor`, `code-optimizer` | that is `/review-verify` (main thread) or, from a subagent, one finder per lens plus `adversarial-verifier`; use that instead |

Decision rule: shard along the axis where the work is **independent**. If workers would need to read
each other's results to proceed, it is not a swarm; use a mesh (`mesh-blackboard`).

## 3. Shard sizing

Two limits bind a worker: context it can usefully read, and its `maxTurns`.

```
tokens_per_LOC        ~ 12          (typical source; minified/generated code is worse, exclude it)
read_budget_tokens    deep review   ~ 60k   ->  ~5k LOC per shard
                      targeted      ~ 150k  ->  15-30k LOC per shard (grep first, read hits only)
                      sources       ~ 8-15 pages per shard (read_url returns 2-10k tokens each)
turn_budget           expected tool calls <= 0.6 * maxTurns of the worker type
                      (reviewer 120 -> ~72 calls; web-scraper 80 -> ~48; debugger 160 -> ~96;
                       current values in config/models.json)
S                     = ceil(|U_size| / shard_capacity), then clamp to [2, spawn headroom / 2]
```

- Bin-pack with first-fit-decreasing inside cohesion groups (a package never splits unless it alone
  exceeds capacity). [shard_plan.py](scripts/shard_plan.py) does this from `wc -l` output and prints
  shards as JSON ready for `/swarm-run` (usage in [shard recipes](references/shard-recipes.md)).
- Target max/mean shard size under 1.5. A swarm's wall clock is its slowest shard.
- More than about 40 shards: prefer a coarser unit or a two-level swarm (sub-coordinators), which
  needs `remaining_depth >= 3`. Sampling is allowed only when declared: log the sampling rate and
  the excluded units in the result.

## 4. Worker brief template

Every worker gets the same skeleton; only SHARD and SCOPE change. Paths, not pasted content.

```
SWARM GOAL: <one line, identical for all shards>
SHARD: <id> (<k> of <S>)
SCOPE: <exact paths | URLs | hypothesis text | parameter tuple | time window>
OUT OF SCOPE: everything else. You may read outside scope only to resolve a referenced symbol or
  citation (at most 5 such reads; list them in Evidence).
TASK: <what to find/produce in this scope; acceptance criteria>
ITEM FORMAT: one line per item: ITEM <key> | <summary> | <severity> | <location>
  key = <dedup key definition, section 8>; more than 40 items: put them in the file and say so
WRITE: full details to .stack/out/<agentType>/<swarm-slug>/<shard-id>.md; its first line is the
  SHARD line below. If that file exists and its first line says STATUS ok, return its summary
  without redoing the work.
RETURN (output contract). Result line 1: Status: done|partial|blocked. Line 2, exactly:
  SHARD <id> STATUS <ok|partial|failed> COVERED <n>/<m> ITEMS <k>
  m = units in scope, n = units fully checked. partial = out of budget: list each unchecked unit
  under Evidence as "UNCOVERED: <unit>". Then the ITEM lines.
CROSS-SHARD: if an item depends on something outside scope, add an Open doubt
  "XSHARD: <question> -> <unit or path>" and do not chase it.
SPAWNING: do not spawn subagents; all shards share one spawn budget. Return Open doubts instead.
BUDGET: finish within about <0.6 * maxTurns> tool calls. Zero items is a valid result; say what you checked.
```

This is the same line format `/swarm-run` uses and parses (SHARD, ITEM, UNCOVERED, XSHARD lines),
so direct and workflow swarms merge the same way. Workers that omit the SHARD line get one corrective
retry (section 6), or a `file-summarizer` (LOW tier) normalize pass that extracts it from the shard file.

## 5. Heterogeneous swarms

Mix agent types (and therefore tiers) per shard when shards differ in kind or difficulty.

| Shard class | Agent | Tier (config/models.json) | Why |
|-------------|-------|---------------------------|-----|
| Mechanical extraction, normalize, summarize | `file-summarizer`, `source-summarizer` | LOW | cheap, deterministic |
| Typical code or source shard | `reviewer`, `web-searcher`, `web-scraper` | frontmatter default | learned defaults |
| Hotspot (high churn x complexity, past incidents, security boundary) | language expert or `security-auditor` | ADVANCED (`security-auditor`, `rust-expert`, `cpp-expert`); Go/Java/Kotlin/Julia experts are MEDIUM | misses are expensive |
| Novel hypothesis or proof step | domain expert | ADVANCED xhigh/max (`computer-science-expert`, `physics-expert`, `mathematics-expert`) | reasoning-bound |
| High-stakes unit | two workers of different tiers | e.g. `reviewer` (ADVANCED) + `go-expert` (MEDIUM) | decorrelate misses; merge with quorum |

Mechanics: with direct Agent calls set only `subagent_type` (the pre-agent hook strips `model`/`effort`);
the tier comes with the agent. `/swarm-run` takes one `agentType` for all shards (`model` only with
`general-purpose`), so for mixed swarms the main thread runs one `/swarm-run` per agent class and
merges the outputs; a subagent uses direct Agent calls for every class.

## 6. Retries and failure handling

| Observation | Action | Counts as |
|-------------|--------|-----------|
| No return / null (agent died) | Re-run the same brief once | the retry |
| `STATUS partial` with UNCOVERED units | New shard over only the uncovered units | the retry |
| `STATUS failed` (maxTurns, context) with 8+ units in scope | Split the shard in two (bisection), one attempt each | the retry |
| `STATUS failed` with few units, or `Status: blocked` | Resolve its first Open doubt if cheap (scope, missing path), re-run once with "grep first, read hits only" | the retry |
| Return lacks the SHARD line or key fields | One corrective retry quoting what was missing, or a `file-summarizer` normalize pass over the shard file | the retry |
| Hook denial (depth limit, spawn policy, spawn budget, token budget) | No retry. Mark `dropped`, reason `depth`, `policy` or `budget` | terminal |
| Worker wandered out of scope | Keep in-scope items; drop the rest; note it | none |
| Items look fabricated (paths or lines that do not exist) | Spot-check 3 with Read/Grep; if any fail, re-run the shard with an ADVANCED-tier agent (e.g. `reviewer` or the language expert instead of a MEDIUM/LOW worker) | the retry |

Each unit gets at most two attempts in total (the original plus one retry, where a split counts as the
retry). After that the unit is `failed` and appears in the result's failed list with its reason.
Reserve 15% of S for retries when computing the spawn budget.

## 7. Coverage ledger

Write to `.stack/out/<your-agent>/<YYYYMMDD-HHMM>-<slug>-ledger.md` and keep it current.

```
| shard | scope | units | agent / model | attempt | status | covered | items | file | note |
|-------|-------|-------|---------------|---------|--------|---------|-------|------|------|
| s01 | services/ingest/** | 212 files | reviewer / opus | 1 | ok | 212/212 | 4 | .stack/out/reviewer/cc-audit/s01.md | |
| s07 | internal/sched/** | 96 files | go-expert / sonnet | 1 | split | 9/96 | 1 | ... | maxTurns at 180 |
| s07a | internal/sched/{a..m}* | 48 files | go-expert / sonnet | 2 | ok | 48/48 | 3 | ... | |
| s07b | internal/sched/{n..z}* | 48 files | go-expert / sonnet | 2 | ok | 48/48 | 1 | ... | |
| s12 | third_party/** | 310 files | - | - | dropped | 0/310 | - | - | excluded by brief: vendored |
```

Statuses: `pending -> running -> ok | partial | failed | split | dropped` (the same vocabulary as
`/swarm-run`'s ledger). `failed` = no usable return after the retry (null, blocked, contract
violation); `dropped` = never run or abandoned on purpose (hook denial, excluded by brief, sampling), always with a reason. Leaf shards (not `split`)
must sum to `|U|`. Coverage = covered units / `|U|`, reported as a number and a fraction.
A shard with zero items is evidence of absence ONLY when its status is `ok`; say so explicitly.

## 8. Dedup keys

| Domain | Key | Normalization |
|--------|-----|---------------|
| Code findings | `path :: symbol :: class` | repo-relative path; enclosing function/method; fall back to a +/-3 line window when no symbol |
| Web sources | canonical URL | lowercase scheme and host, drop `www.`, fragments, `utm_*`, `gclid`, `fbclid`; drop trailing slash; prefer `rel=canonical` |
| Papers | arXiv id without version, or lowercase DOI | `2401.01234v3 -> 2401.01234`; title fallback: lowercase alnum only |
| Claims | entity set + normalized proposition | lowercase, keep numbers and units; near-duplicates via `mcp__jina__deduplicate_strings` on the claim texts |
| Hypotheses | id assigned at partition time | never re-key mid-run |
| Grid points | parameter tuple rounded to grid precision | sort keys; fixed decimal places |

Dedup BEFORE any expensive downstream step (verification, synthesis). Keep the union of evidence
and the list of contributing shards on the surviving item; agreement across shards is signal.

## 9. Merge and reduce

| Strategy | Use for | Rule |
|----------|---------|------|
| Union + dedup | findings, defects, sources | keep max severity, most specific scenario, union of evidence and shards |
| Quorum | redundant coverage of the same unit | keep if at least q of r workers report it (2 of 3 typical) |
| Reciprocal rank fusion | ranked lists from many shards | `score(d) = sum_i 1 / (60 + rank_i(d))`, sort descending |
| Argmax with confirmation | hypothesis and grid swarms | best by metric, then re-run the winner once to confirm; report the CI or spread |
| Statistical reduce | numeric measurements | median and IQR (timings), mean and 95% CI (counts); keep n |
| Tree reduce | merged material above about 60k tokens | groups of 4-6 shard outputs per merge agent (`file-summarizer`, LOW tier), then a final merge; levels = `ceil(log_b S)` |
| Conflict list | two shards contradict | never pick silently; list both with evidence, route to `adversarial-verifier` or the caller |

XSHARD doubts: group them by target unit; if 3 or more point at the same unit, run one follow-up
worker on that unit with all the questions attached; otherwise return them as Open doubts.

## 10. Execution mode

| Situation | Mode |
|-----------|------|
| S <= 6, any mix of agent types | Direct Agent calls, all in one message |
| S > 6, one agent type, you are the main thread (no `<stack-context>` header) | `/swarm-run` (Workflow tool, `name: "swarm-run"`; at most 150 shards per call by default) |
| S > 6, mixed agent types | Main thread: one `/swarm-run` per agent class; subagent: direct calls in batches of at most 8 per message |
| You are a subagent (any `<stack-context>` header) or `remaining_depth` 1 | Direct calls: homogeneous batches of at most 20, mixed at most 8 per message; ledger tracks batch numbers |
| You are the merge stage | Never launch workers; merge and report |

`/swarm-run` example:

```json
{ "name": "swarm-run",
  "args": { "task": "<SWARM GOAL + TASK + ITEM FORMAT from section 4>",
            "shards": [ {"id": "s01", "brief": "SCOPE: services/ingest/** (212 files, 24k LOC)"} ],
            "agentType": "reviewer",
            "key": "path::symbol::bug-class",
            "merge": "Union + dedup by key; keep max severity and the most specific failure scenario; list zero-item shards; conflicts to a separate list." } }
```

Optional args: `model` (opus|sonnet|haiku, only with `agentType: general-purpose`; never model/effort
for this stack's agents), `retry` (default 1), `maxShards` (default 150; extra shards are logged as
`dropped`, run them in a second call), `outDir` (default `.stack/out/swarm-run/<slug>`). It returns
`{started, outDir, merged, perShard, failed, coverage}`: `merged` carries the summary, `merged_path`,
`ledger_path`, deduped items (first 100) and conflicts; `coverage.line` is the coverage sentence and
`coverage.ledger` the ledger table. `started: false` comes with `reason` and `next`: fix the args.
Copy `failed` into your report with reasons; do not report coverage you did not get.

## 11. Worked example

Goal: find goroutine and context-cancellation leaks in a Go monorepo.

1. U: `git ls-files '*.go' ':!:*_test.go' ':!:vendor/*' ':!:*.pb.go'` -> 1,240 files, 180k LOC.
2. Strategy: by package, targeted mode (grep `go func`, `context.With`, `time.After`, `select {`
   first, read hits). Key: `path :: func :: leak-class`.
3. Capacity 20k LOC -> S = ceil(180k / 20k) = 9. `internal/sched` had 3 leak incidents: hotspot.
4. Spawns: 2*9 + 1 + 2 (retry reserve) = 21; session at 44 of 400, so H = 356 and 21 <= 178: ok.
5. Execution as `swarm-coordinator` (a subagent, so no Workflow): one message with 9 Agent calls, each
   with `run_in_background: false`: 8 shards with `subagent_type: reviewer`, plus `internal/sched` with
   `subagent_type: go-expert` (MEDIUM tier; for an ADVANCED hotspot use `reviewer` or
   `security-auditor`). On the main thread (no `<stack-context>` header) the 8 homogeneous shards may
   instead go to `/swarm-run` with `agentType: reviewer`.
6. Returns: 8 ok; `internal/sched` STATUS failed (maxTurns after 9/96 files) -> split into two
   shards of 48, both ok on attempt 2.
7. Merge: 23 raw items -> 17 unique (6 duplicates across shards on a shared helper). Two XSHARD
   doubts point at `pkg/pool`; one follow-up worker resolves both (one real leak, one false alarm).
8. Coverage 1,240/1,240, dropped 0. Findings ship, so hand the 18 items to 3-lens adversarial
   verification. Ledger at `.stack/out/swarm-coordinator/20261019-1412-go-leaks-ledger.md`.

## 12. Checklist before returning

- [ ] Every shard in a terminal status; leaf units sum to `|U|`.
- [ ] Coverage stated as `covered/|U|` and a percentage; failed and dropped units listed with reasons.
- [ ] Dedup applied with the declared key; duplicates count reported (raw -> unique).
- [ ] Conflicts listed, not silently resolved.
- [ ] Merged result over ~60 lines or ~3k characters is in `.stack/out/<agent>/<YYYYMMDD-HHMM>-<slug>.md`;
  Result carries the summary, the path and line anchors.
- [ ] Spawns used reported (planned vs actual).
