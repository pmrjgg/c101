# Architecture

Rendered diagrams of everything below (system, lifecycle, guards, web safety, learning, image pipeline
and all eight workflows): [DIAGRAMS.md](DIAGRAMS.md).

```
                         user
                          │
                 depth 0  ▼
            ┌──────────────────────┐   classifies the request, picks the cheapest adequate route,
            │      delegator       │   keeps its own context lean (children return summary + file path)
            └──────────┬───────────┘
     ┌─────────────┬───┴──────────┬──────────────┬─────────────────┬──────────────┐
     ▼             ▼              ▼              ▼                 ▼              ▼
 general-chat  quick-/deep-   orchestrator   ensemble-assembler   mediator    saved workflows
               researcher     (plan DAG →    (picks experts,      (N solve,   /swarm-run /fanout
                              waves → gates) roles, briefs)       vote, synth) /mediate /expert-panel
                    │              │              │                  │        /research-sweep
                    ▼              ▼              ▼                  ▼        /review-verify
             web-searcher    planner/architect  15 domain experts  voters     /plan-tournament
                                                                             /visual-iterate
             web-scraper     swarm-coordinator  rust cpp go haskell (any
             web-crawler     mesh-router        julia java kotlin   agents)
             browser-op      concurrent-        python ts cg cs
             computer-op     dispatcher         quantum math physics design
             paper-res.          │                   │
             fact-checker        ▼                   ▼
             summarizers    reviewers, testers,  cross-domain-synthesizer, expert-panel-chair,
                            validators, QC,      debate-moderator, analogy-mapper,
                            optimizer, security  first-principles-decomposer
                                 │
        any agent, any depth ────┴──► doubts → quick-researcher · fact-checker · tester · quality-control
                                              code-quality-analyst · adversarial-verifier · file-summarizer
                                                                               … down to depth 8
```

## Layers

| layer | agents | pattern |
|---|---|---|
| Routing | `delegator` | main thread; one decision per request; never does heavy work |
| Orchestration | `orchestrator`, `swarm-coordinator`, `mesh-router`, `ensemble-assembler`, `concurrent-dispatcher`, `mediator` | DAG execution, swarms over shards, blackboard mesh, expert ensembles, fan-out, voting |
| Planning | `planner`, `architect`, `plan-critic` | task DAGs with acceptance criteria; design trade-offs; red-teaming |
| Quality | `reviewer`, `adversarial-verifier`, `validator`, `tester`, `quality-control`, `code-quality-analyst`, `code-optimizer`, `security-auditor`, `debugger` | find → verify → gate |
| Research | `quick-researcher`, `deep-researcher`, `web-searcher`, `web-scraper`, `web-crawler`, `browser-operator`, `computer-operator`, `paper-researcher`, `fact-checker`, `source-summarizer`, `file-summarizer` | Exa, Jina, Spider, Playwright, computer use |
| Experts | 15 domain experts | each preloads its craft skill; context7 for live docs |
| Synthesis | `cross-domain-synthesizer`, `expert-panel-chair`, `debate-moderator`, `analogy-mapper`, `first-principles-decomposer`, `general-chat` | combine knowledge from several experts into a higher-level answer |
| Image | `image-generator`, `image-editor`, `vector-artist`, `visual-reviewer` | the `image` MCP server (one configured endpoint per operation, tools listed only when configured); produce → `visual-reviewer` → revise until the rubric passes |
| Meta | `stack-tuner`, `agent-architect` | operate the learner; extend the stack |

Every agent preloads three protocol skills — `delegation-protocol`, `doubt-escalation`,
`output-contract` — plus at most three role skills. 227 skills in total (hubs and method skills plus 168 granular
playbooks, grouped into install packs in `config/packs.json`); see `docs/AGENTS.md`.

## Combining experts (higher-level problems)

1. **Ensemble** (`ensemble-assembler`): decompose by discipline, 2–7 experts with roles
   (lead / challenger / integrator / specialist), concurrent, scoped briefs with a shared glossary.
2. **Synthesis** (`cross-domain-synthesizer`): assumption map, claim-level provenance, a conflict
   matrix saying which expert is authoritative on which sub-question and why, emergent opportunities.
3. **Decision** when experts disagree: `mediator` (blind cross-ranking + Schulze/Borda/approval/
   log-opinion-pool vote, debate round on near-ties) or `expert-panel-chair` (Delphi rounds until the
   IQR stabilises) or `debate-moderator` (assigned positions, judged).
4. **Verification**: `adversarial-verifier` lenses before anything reaches the user; `quality-control` gate.

## Models: tiers and enforcement

Three tiers in `config/models.json` — `ADVANCED_MODEL`=claude-opus-5-5 (32 agents), `MEDIUM_MODEL`=claude-sonnet-5-5
(20), `LOW_MODEL`=claude-haiku-5-5 (5) — are the only models allowed:

* frontmatter `model` is rendered from the tier (`bin/stack agents tiers --apply`); doctor errors on any other model;
* `.claude/settings.json` sets `availableModels` (exact) + `enforceAvailableModels`, so Claude Code refuses others;
* the `pre-agent` hook strips per-call `model`/`effort`, so a caller cannot move a subagent off its tier;
* the main thread is pinned: `bin/claude-stack` launches `--agent delegator --model <tier> --effort <effort>` and
  refuses overrides, the `PreModelSwitch` hook blocks `/model` switches away from it, and a main-thread effort
  change (which hooks cannot block) is flagged on the next delegation; `bin/stack-sdk run` pins both.

## Per-agent knobs

`model`, `effort`, `maxTurns`, `mcpServers`, `skills` (and optionally `autoCompactWindow`) live in each
agent's frontmatter. Edit with `bin/stack agents set <agent> model=opus effort=xhigh maxTurns=60
mcpServers=exa,jina`; list with `bin/stack agents list`. The learner rewrites `maxTurns`/`effort`
within `config/learning.json` bounds (see `docs/LEARNING.md`). Per-call `model`/`effort` overrides
in Agent calls are stripped by the `pre-agent` hook: the tier is authoritative.

## Runtime state

| path | what |
|---|---|
| `.stack/out/<agent>/` | full outputs offloaded by agents (summary + path returned instead) |
| `.stack/blackboard/<task>/` | mesh-router blackboards |
| `.stack/images/<date>/` | image router outputs + sidecars |
| `.stack/playwright/` | screenshots, PDFs, traces |
| `~/.claude/stack-data/` | learning observations, posteriors, budgets, change log, spawn stats |
| `~/.claude/stack.env` | API keys (never in the repo) |
