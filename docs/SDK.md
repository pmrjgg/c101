# Running the stack with the Claude Agent SDK

The same agents, skills, workflows, hooks and MCP servers run interactively (`bin/claude-stack`) and
programmatically through the [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/) (Python,
`claude-agent-sdk` in the uv environment). `stack_sdk/` is the bridge.

```bash
bin/stack-sdk run "Survey neural SDF rendering in 2026 and write a cited report"   # delegator as main thread
bin/stack-sdk run --cwd ~/code/other-project "Review the auth module"             # stack used from elsewhere
bin/stack-sdk agents          # the 57 agents as SDK AgentDefinitions (tier model, effort, maxTurns, MCP, skills)
bin/stack-sdk check           # build options for both placements and validate (no API call)
bin/stack-sdk mcp             # MCP servers as resolved for out-of-repo sessions (no secrets)
```

From Python:

```python
import asyncio
from claude_agent_sdk import query, ResultMessage
from stack_sdk import StackRunConfig, build_options

async def main():
    opts = build_options(StackRunConfig(cwd="/path/to/project"))   # main agent: delegator
    async for msg in query(prompt="...", options=opts):
        if isinstance(msg, ResultMessage):
            print(msg.subtype, msg.total_cost_usd)

asyncio.run(main())
```

Or only the agents: `from stack_sdk import load_agents; ClaudeAgentOptions(agents=load_agents(), ...)`.

## Two placements

| | in this repo (`cwd` inside it) | elsewhere |
|---|---|---|
| agents | discovered from `.claude/agents` (`setting_sources` includes `project`) | sent programmatically (`options.agents`) |
| main thread | `--agent delegator` (body replaces the system prompt) | Claude Code preset + delegator body appended |
| MCP servers | inline in each agent (lazy) + project `.mcp.json`, empty by default (loaded without prompts in SDK mode) | inline in each programmatic agent + resolved `.mcp.json` copy with absolute launcher paths |
| hooks | `.claude/settings.json` command hooks | the same handlers as Python callbacks (`stack_sdk/hooks.py`) |
| env | settings `env` | passed via `options.env` |
| learning | SessionEnd hook | the runner ingests the finished session itself |

## Defaults (unattended-safe)

* `permission_mode="dontAsk"` with an explicit allow-list (core tools, Agent, Workflow, Skill, every
  project MCP server) and `--permission-prompts none`: nothing hangs, a denied call is not retried.
* System `claude` CLI when installed (`--cli bundled` uses the SDK's bundled one), for parity with
  interactive sessions.
* Foreground subagents (`CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`, and the hook sets
  `run_in_background: false`): every parent receives its children's results before continuing —
  context usage over speed. `--background` turns it off.
* `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`: long workflows are not dropped at exit.
* `skills="all"`, `setting_sources=["user","project","local"]` (explicit, so local settings are not
  silently dropped).
* Main thread pinned to its agent's tier model and effort (delegator: `claude-opus-5-5`, `high`);
  `--model`/`--effort` are refused while a main agent is set. Subagents run on their tier models;
  per-call overrides are stripped by the hook.
* Only the three tier models are allowed anywhere: `availableModels` (exact match, enforced) is passed
  as SDK settings, and agents whose model is not a tier model are rejected at option build time.
* `task_budget = max_prompt_tokens` (400M) as the API pacing hint; the hooks enforce the hard
  session/prompt token limits; `--max-budget-usd` adds a USD hard stop.

## Agent definitions under the SDK

`AgentDefinition` fields map 1:1 from frontmatter: `description`, `prompt` (the body), `tools`,
`disallowedTools`, `model` (tier id), `skills`, `memory`, `mcpServers`, `initialPrompt`, `maxTurns`,
`background`, `effort`, `permissionMode`. `color` has no SDK field and is dropped (cosmetic).
`bin/stack-sdk check` fails if any other frontmatter key cannot be represented.

## Rules every agent follows so both runtimes behave the same

See docs/CONVENTIONS.md section 11: Workflow only from the main thread; no AskUserQuestion in
subagents (return Open doubts); `run_in_background: false` when a result is needed; no per-call
model/effort; no computer use / Chrome / agent teams without a fallback; self-contained bodies; no
steps that need an interactive approval.

## Limits to know

* The SDK's Python hooks cover 10 events (no SessionStart/SessionEnd); the runner compensates.
* Built-in computer use is interactive-only; `computer-operator` falls back to `peekaboo` (enable with
  `bin/stack mcp enable peekaboo`) or reports the task as blocked.
* Workflow availability in Python SDK sessions follows the CLI; the runner pre-authorises it.
* The SDK pins its own CLI; after `uv lock --upgrade-package claude-agent-sdk`, rerun the tests.
