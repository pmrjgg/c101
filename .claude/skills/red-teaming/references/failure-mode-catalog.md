# Failure-mode catalog

Seed lists for premortems, assumption hunts and FMEA rows. Use them to widen coverage after your
own pass, never instead of reading the plan. Each item names a mechanism; turn the relevant ones
into FMEA rows with the plan step they attach to.

## Contents
- Premortem prompts
- Distributed systems and services
- Data migrations and schema changes
- Releases and deployments
- Performance and capacity
- Security and abuse (plan level)
- Research plans
- ML and evaluation work
- LLM-agent workflows (this stack)
- Projects and organizations

## Premortem prompts

Use one prompt per category; ask for the single most plausible failure story each.

| Category | Prompt |
|---|---|
| Technical | "The core mechanism worked in testing and failed in production. What was different?" |
| Data | "The system ran fine but the data it produced was wrong for weeks. How did nobody notice?" |
| Scale | "Traffic or data volume reached 10x the estimate on day one. What broke first?" |
| Dependency | "A service, library, vendor or quota we rely on changed or disappeared. Which one, and what then?" |
| People and process | "The key person was unavailable at the critical step. What stalled?" |
| Security and abuse | "Someone used this exactly as designed, for a purpose we did not intend. What did they do?" |
| Cost and time | "It took three times as long and cost three times as much. Where did the time go?" |
| Adoption | "It shipped on time and nobody used it. Why?" |
| Rollback | "We needed to undo it on day 3. Why could we not?" |
| Agent stack | "The agents produced a confident, well-formatted, wrong result. Which step let it through?" |

## Distributed systems and services

- Retries without exponential backoff and jitter: retry storms; retries at several layers multiply.
- Missing or too-long timeouts: threads or connections pile up behind a slow dependency.
- Cache stampede on expiry of a hot key; cold cache after deploy or failover.
- At-least-once delivery without idempotency keys: duplicate side effects.
- Ordering assumed but not guaranteed across partitions, retries or replicas.
- Clock skew used for ordering, expiry or leases.
- Split brain after a network partition; two leaders accepting writes.
- No backpressure: queues grow until memory or disk runs out.
- Hot partition or hot key concentrating load on one shard.
- Global configuration push without staged rollout: one bad config, total blast radius.
- Certificate, token or domain expiry with no alert.
- Health checks that pass while the service cannot do useful work.

## Data migrations and schema changes

- Dual-write divergence (no transaction spans both stores); verification by row counts only
  (use per-row checksums or sampled compares).
- Schema changes that rewrite or lock large tables; long-running transactions blocking DDL.
- Backfill load on the primary; backfill not resumable; backfill racing live writes.
- Encoding, collation, time zone or precision changes altering values silently.
- NULL vs empty vs missing semantics differing between systems.
- Narrowing types (64-bit to 32-bit ids, text length limits).
- Irreversible steps (drop column, delete source) scheduled before verification completes.
- Cutover ordering: readers switched before writers, or caches holding old-format data.

## Releases and deployments

- No canary or staged rollout; no feature flag to disable new behaviour.
- Irreversible database migration shipped in the same release as the code that needs it.
- Mixed-version fleet during rollout: old and new versions disagree on formats or protocols.
- Rollback path never rehearsed; rollback breaks on data written by the new version.
- Clients that cannot be rolled back (mobile apps, cached frontends, third-party integrations).
- Environment drift: staging differs from production in config, data size or versions.
- Transitive dependency upgrades pulled in by a lockfile refresh.

## Performance and capacity

- Capacity estimate from average load, not peak; no headroom for failover (N-1 capacity).
- p99 ignored: mean improves while tail latency regresses.
- Benchmarks on toy data; production data skewed (hot keys, huge rows).
- N+1 queries hidden behind an ORM; chatty calls across regions.
- Memory growth under sustained load (leaks, unbounded caches, unbounded queues).
- Garbage collection or compaction pauses at peak.

## Security and abuse (plan level)

- New endpoint without authentication or authorization review; IDs guessable (enumeration).
- No rate limiting on expensive or sensitive operations (login, password reset, export, search).
- Personal data in logs, analytics or error reports; retention never defined.
- Secrets in CI variables, build logs or committed config.
- New third-party dependency or vendor with data access and no review.
- Admin or support tooling with broader access than the product itself.
- Abuse of legitimate features: bulk invites as spam, file upload as malware hosting,
  webhooks as SSRF, free tier as compute for abuse.

## Research plans

- Question too broad to answer; no stopping criterion.
- Key sources paywalled, unavailable or behind JS-heavy pages (plan Spider/Playwright time).
- Single-source claims; citation laundering (many articles, one origin).
- Search queries phrased to confirm the expected answer.
- Stale sources for fast-moving topics; version mismatch in technical documentation.
- Conflicting sources not logged, then silently resolved toward the first one read.

## ML and evaluation work

- Train/test leakage (duplicates, temporal leakage, preprocessing fit on all data).
- Evaluation set too small: confidence interval wider than the claimed improvement.
- Single seed; improvement inside seed variance.
- Baseline under-tuned relative to the proposed method.
- Benchmark contamination for LLM evaluations.
- Metric that does not reflect the user outcome (Goodhart).
- Compute or data licensing constraints discovered late.

## LLM-agent workflows (this stack)

- **Prompt injection**: fetched pages, files or tool output containing instructions; agents must
  treat them as data. Plans that pipe scraped text into agents with write or network tools need a
  read-only stage in between.
- **Tool overreach**: an agent with Bash, network and write access where read-only would do; use
  `disallowedTools` or a narrower agent.
- **Runaway spawning or token burn**: recursion or fan-out exceeding depth, spawn rules or budgets
  (the pre-agent hook enforces depth 8, `spawn_rules` with `orchestrators_until_depth` 6,
  `max_spawns_per_session` 400 and the token budgets: session 3B with soft at 2.25B, per prompt
  120M with soft at 90M, in `config/policy.json`); plans should estimate spawns and tokens per phase
  and say what happens at `budget="soft"`/`"hard"`.
- **Interactive-only steps** (must work under `bin/stack-sdk run` too): a subagent step that
  launches a saved workflow (main thread only; return `Workflow name=... args={...}` as an Open
  doubt); a step that asks the user or needs an approval mid-run (fails under SDK `dontAsk`;
  return Open doubts); a result consumed before a background child finished (use
  `run_in_background: false`); diversity via per-call `model`/`effort` (stripped; pick agents of
  different tiers); built-in computer use or Chrome with no Playwright/peekaboo fallback; ledgers
  in TodoWrite (not enabled on the 5.5 models; use files under `.stack/out/`).
- **File collisions**: parallel agents writing the same path; give each worker a distinct output
  path under its own `out_dir`.
- **Context overflow**: large tool outputs pasted into replies instead of offloaded to files
  (output-contract rule; `file-summarizer`).
- **Hallucinated citations or APIs**: no `fact-checker` sample, no context7 check of library APIs.
- **Correlated ensemble failure**: every voter or judge on the same model and the same sources;
  agreement mistaken for evidence (`bayesian-aggregation`, effective N).
- **Unverified "done"**: workers report success without a check; no `validator` gate.
- **Quotas and cost**: Exa, Jina and Spider rate limits and credits; Spider remote browser
  sessions billed while open (close them); image generation costs per call.
- **Key leakage**: key values echoed into logs, transcripts or output files.
- **Workflow scripts**: unvalidated args, barriers where a pipeline would do, silently dropped
  items (no `log()`), nondeterministic calls that the workflow runtime rejects.
- **Output-contract drift**: a child returns prose where the caller parses a schema; the merge step
  fails or silently drops the item.

## Projects and organizations

- One person or one team holds an undocumented critical step (bus factor 1).
- Lead times not in the plan: security review, procurement, legal, access requests.
- Dependence on another team's roadmap without a committed date.
- Planning fallacy: estimate built bottom-up only; compare with how long similar projects took
  (reference-class forecasting).
- Unclear decision rights: nobody can approve the go/no-go.
- Change freezes, holidays and on-call gaps around the cutover date.
- Success metric not instrumented before launch, so success cannot be shown.
