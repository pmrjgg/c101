# Delegation depth, budgets and concurrency

## Depth 8

* The main thread is depth 0 — normally the `delegator` (`bin/claude-stack`, `claude --agent delegator`,
  or `./install.sh --main-agent`).
* Claude Code nests subagents natively; `.claude/settings.json` raises the limit from the default 3 to 8:
  `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=8` (and `CLAUDE_STACK_MAX_DEPTH=8` for the stack's own guard).
  At the limit Claude Code withholds the Agent tool from subagents.
* Depth counts from the delegator: delegator (0) → orchestrator (1) → … → leaf (8).

## The pre-agent hook

`PreToolUse` on `Agent|Task` runs `bin/stack hook pre-agent`, which:

1. finds the calling agent's native depth from `agent-<id>.meta.json` (`spawnDepth`; the main thread is 0);
2. **denies** the spawn if the child would exceed `CLAUDE_STACK_MAX_DEPTH`, telling the caller to do the work
   itself or return an open doubt;
3. **denies** spawns that break `config/policy.json` → `spawn_rules`: a caller → allowed-children table
   (Claude Code ignores `Agent(type)` lists inside subagent definitions, so per-level control lives here;
   e.g. `web-scraper` may only call summarizers) and `orchestrators_until_depth` (default 6: no
   orchestrator, mediator or panel is started deeper than that — deep levels are for leaves);
4. **denies** when the per-session spawn budget (`config/policy.json` → `max_spawns_per_session`, default 400)
   is exhausted — a runaway-fan-out guard;
5. otherwise prepends one line to the child's prompt:

```
<stack-context depth="3" max_depth="8" parent="orchestrator" remaining_depth="5" spawns_this_session="17" out_dir=".stack/out/rust-expert"/>
```

Every agent's preloaded `delegation-protocol` skill tells it how to act on this header:
`remaining_depth="0"` → no spawning; 1–2 → only leaves (researchers, summarizers, testers).
The hook fails open: on any internal error the spawn proceeds unchanged (errors go to
`~/.claude/stack-data/hook-errors.log`). Spawn statistics per session: `bin/stack depth`.

## Concurrency

* Several `Agent` calls in one assistant message run in parallel (Claude Code caps at
  `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS=20`).
* Saved workflows (`/swarm-run`, `/fanout`, `/mediate`, `/expert-panel`, `/research-sweep`,
  `/review-verify`, `/plan-tournament`) run up to `CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS=16`
  agents at once with deterministic control flow.
* Agent teams (experimental, `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) give long-lived teammates that
  message each other; not enabled by default because teammates cannot nest and skills don't preload.

## Doubts

Any agent at any depth can delegate a doubt (fact, runtime behaviour, quality, contested claim,
oversized output) to `quick-researcher`, `deep-researcher`, `fact-checker`, `tester`,
`quality-control`, `code-quality-analyst`, `adversarial-verifier` or `file-summarizer`, per the
preloaded `doubt-escalation` skill — budget permitting and depth permitting.
