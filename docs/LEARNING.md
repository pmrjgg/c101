# Bayesian self-tuning

After every session the stack learns, per agent type, how many steps (`maxTurns`), how much
reasoning (`effort`) and how many tokens it actually needs, and moves each agent's frontmatter
toward what the evidence supports. Code: `stack/learn/` (stdlib only). Config: `config/learning.json`.

## Data flow

```
SubagentStop (async, debounced)  ─┐
SessionEnd (detached background) ─┴─> bin/stack learn ingest   transcripts -> ~/.claude/stack-data/obs/<session>.json
                                      bin/stack learn update   posteriors  -> recommendations.json, budgets.json
                                      bin/stack learn apply    frontmatter <- maxTurns/effort (bounded, audited in changes.jsonl)
```

### What is observed (per agent run)

Source: `~/.claude/projects/<project>/<session>.jsonl` (main thread) and
`<session>/subagents/**/agent-<id>.jsonl` + `.meta.json` (subagents; `agentType`, native `spawnDepth`).

| field | how it is measured |
|---|---|
| `tool_rounds` | responses that call ≥1 tool — the unit `maxTurns` counts (parallel calls in one response are one round) |
| `turns` | unique `message.id` among assistant records (Claude Code writes one line per content block) |
| `output_tokens` | final `usage.output_tokens`; sidechain records written from the stream's `message_start` carry placeholders (`stop_reason: null`), so those turns are estimated from content length (3.6 chars/token) and flagged `output_estimated` |
| `thinking_tokens` | `usage.output_tokens_details.thinking_tokens` |
| `ctx_peak` | max over turns of `input + cache_read + cache_creation` tokens — the context window actually used |
| `output_max_turn` | largest single-turn output — drives the max-output-tokens window |
| `effort` | the level in effect from the `SubagentStop` payload (`effort.level`, recorded by the hook); the transcript's per-line `effort` reflects the session level, so it is only a fallback |
| `model` | `message.model` (mode over the run) |
| `capped` | the run hit `maxTurns` (`tool_rounds` ≥ the limit in force, or a max-turns marker) — a **right-censored** observation |
| `tool_calls`, `tool_errors`, `agent_spawns`, `duration_s`, `spawn_depth`, `workflow` | diagnostics |

## Models

### maxTurns — censored log-normal, grid posterior

`log(tool_rounds) ~ Normal(μ, σ)`. Prior: `μ ~ N(log(maxTurns_current / 2.5), log 2.5)`,
`log σ ~ N(log 0.6, 0.6)` — i.e. the hand-set limit is taken as roughly 2.5× a typical run.
The posterior is computed exactly on a 48×28 grid over (μ, σ):

```
log p(μ,σ | data) = log prior
                  + Σ_exact  w_i · log φ((y_i − μ)/σ) − w_i log σ        (sufficient statistics)
                  + Σ_capped w_j · log(1 − Φ((log cap_j − μ)/σ))           (survival: "needed ≥ cap")
```

Censoring matters: if an agent keeps hitting a too-low cap, treating those runs as "needed exactly
cap turns" would lock the cap in place; as survival terms they push the posterior upward.

Recommendation = `ceil(q95 of the posterior predictive × 1.15)`, clamped to the agent's bounds,
moved at most ×2 / ÷2 per update, and only applied when it differs by ≥10% (hysteresis).
Requires an effective sample size ≥ 3.

### Data window — forgetting factor by prequential score

Observations are weighted `w_i = γ^(age_i)` (age in runs). γ ∈ {1, .99, .97, .94, .90, .85} is chosen
per agent by the **prequential log score**: for each of the last 12 runs, fit on the runs before it
and score the run with the predictive log density (or log survival if it was capped). Among the γ
within 1.5 nats of the best, the longest memory wins, so the window only shortens when there is
clear evidence of drift (new tasks, a model change). `effective_runs = (1−γⁿ)/(1−γ)` is reported.

### effort — Dirichlet over output-token bands + Beta failure rate

Each run is categorised by output tokens (thinking included) into a band:
`low < 4k ≤ medium < 16k ≤ high < 48k ≤ xhigh < 120k ≤ max`. A Dirichlet over the bands
(prior 0.5 each + stickiness 3 on the current level) gives the **smallest level covering 80%** of
runs. A Beta(1, 4) posterior on the failure rate (capped runs) then:

* escalates one level when `E[P(fail)] > 0.25` (the agent keeps running out of road), and
* blocks de-escalation while `E[P(fail)] > 0.08`.

Moves one level per update, within per-agent bounds (e.g. `mathematics-expert` never below `high`).
Requires an effective sample size ≥ 5.

### Token windows

Log-normal posteriors (same machinery, uncensored) on `output_tokens`, `tokens_total`, `ctx_peak`
and `output_max_turn` give `[min, median, max]` = predictive `[q05, q50, q95]` per agent, written to
`~/.claude/stack-data/budgets.json`:

* `max_output_tokens` = q95 of the largest single-turn output × 1.15, clamped to [8k, 128k] — use
  as `CLAUDE_CODE_MAX_OUTPUT_TOKENS` for headless runs of that agent;
* `recommend_1m_context` = q95 of `ctx_peak` > 80% of a 200k window — consider `model: opus[1m]`
  or `autoCompactWindow` for that agent.

Internal agents (prompt suggestions, `/btw`) report an empty agent type and are ignored.

## Commands

```bash
bin/stack learn ingest --all            # backfill from every transcript on this machine
bin/stack learn update                  # recompute posteriors
bin/stack learn report                  # table: n, gamma, maxTurns cur->rec, effort cur->rec, P(fail), tokens
bin/stack learn report --agent rust-expert --json
bin/stack learn apply --dry-run         # what would change
bin/stack learn apply                   # write frontmatter (audited in ~/.claude/stack-data/changes.jsonl)
```

Set `"auto_apply": false` in `config/learning.json` to review changes before they land, or
`"enabled": false` to stop learning. Per-agent bounds live under `"agents"`; set `"learn": false`
there to freeze an agent. Changes are ordinary edits to tracked files, so `git diff .claude/agents`
shows exactly what the learner did.
