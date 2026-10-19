# Templates

Copy, then replace every `<...>`. Leftover angle brackets are a review failure. Line counts in
comments are targets, not padding goals.

## 1. Design note (write before any file)

```markdown
# Design: <name>
- Type: agent | skill | workflow        Path: <path>
- Mission (2 sentences): <what it owns; what done means>
- Callers: <delegator class / orchestrator / workflow> ; Callees: <agents it spawns>
- Inputs: <brief fields, paths> ; Outputs: <reply shape, files under .stack/out/<name>/>
- Frontmatter: tier <ADVANCED_MODEL|MEDIUM_MODEL|LOW_MODEL>, effort <e>, maxTurns <n> (= ~2 x <tool rounds of a typical demanding run>), mcpServers [<...>], skills [<...>], color <c>
- Overlap check: nearest agents <a, b>; trigger difference: <...>
- Bounds: <none | {"maxTurns": [lo, hi], "effort": [lo, hi]}> because <...>
- Test plan: direct smoke brief <...> (criterion <...>); routed request <...>
- Wiring: <delegator row, orchestrator roster, spawn_rules in config/policy.json, settings, catalog>
```

## 2. Agent (worker or operator)

```markdown
---
name: <name>
description: "<Role> that <does what, with which tools or methods>. Use when <conditions>. Examples - <trigger 1>; <trigger 2>; <trigger 3>."
model: <tier model id: jq -r '.tiers.<TIER>.model' config/models.json; or let bin/stack agents set <name> tier=<TIER> write it>
effort: <low|medium|high|xhigh|max>
maxTurns: <n>
mcpServers: [<server>, <server>]   # names here; bin/stack mcp sync (or agents set <name> mcpServers=a,b) rewrites catalog servers inline
skills: [delegation-protocol, doubt-escalation, output-contract, <role-skill>]
color: <group colour>
---

You are the <role> of this agent stack. <What you own, for whom, and what a finished job looks
like, in 2-4 sentences.>

## When you are called

- Expected brief: <fields>. Missing <field> with a high cost of guessing: return an Open doubt.
- Done means: <verifiable end state>.
- Out of scope: <what you hand back, and to whom>.

## Operating procedure

1. Read the brief and the <stack-context> header; note remaining_depth, budget (soft: converge, no new
   exploratory branches, finish, verify, report; hard: spawn only file-summarizer, quality-control,
   validator, source-summarizer, wrap up and list gaps as Open doubts) and out_dir.
2. <Concrete step naming tools: Read/Grep paths, mcp__<server>__<tool> with key arguments.>
3. <...>
4. Verify: <command or check with pass threshold>.
5. Offload long output to `<out_dir>/$(date +%Y%m%d-%H%M)-<slug>.md` per output-contract.

## Delegation

- <agent-name> (<LOW|MEDIUM|ADVANCED>_MODEL tier) for <sub-task>; Agent with run_in_background: false
  when its result is needed before you continue. Cheaper or deeper = a different agent, never a
  per-call model/effort (stripped by the pre-agent hook).
- Parallel: <which calls go in one message; max count>.
- remaining_depth 0: <do it yourself / Open doubt>. 1-2: leaves only (<names>).
- Doubts: per doubt-escalation (<typical doubt> -> <agent>).

## Quality bar

- [ ] <check with a command or number>
- [ ] <check>
- [ ] Every claim in Result has Evidence (path:line, command + exit code, URL + date).

## Output

End with the output-contract sections. Result: <role-specific shape: table, verdict, paths>.
Files: <what this role typically writes>. Confidence: <what raises or caps it for this role>.

## Never

- <role-specific prohibition>
- Never read or print ~/.claude/stack.env or any key value.
```

Expert variant: insert after the mission paragraph

```markdown
## Expertise

- Sub-areas: <list with the specific techniques, not just topics>
- Tools and commands: <compilers, linters, profilers, test runners with flags>
- Standard references: <specs, books, docs the expert defers to; use context7 for library docs>
- Pitfalls you guard against: <the 5-10 mistakes that cost the most in this domain>
```

Pure leaf variant (summarizer, formatter): add `disallowedTools: Agent` as the last frontmatter
key; the Delegation section then says "You do not spawn. Doubts go back to the caller as Open
doubts."

## 3. Skill

```markdown
---
name: <name>
description: "<What it is and covers, in one line>. <When to load it.>"
when_to_use: "<Concrete triggers: before X, when Y fails, when asked Z.>"
---

# <Title>

<One paragraph: what done looks like when this skill is applied.>

## 1. Decide
| Situation | Choice | Why |
|---|---|---|

## 2. Procedure
1. <step with command>

## 3. Checklist
- [ ] <verifiable item>

## 4. Worked example
<input -> steps with real numbers -> output>

## 5. Failure modes
| Symptom | Cause | Fix |
|---|---|---|

Deep material: [<topic>](references/<topic>.md)
```

Reference file (`references/<topic>.md`): starts with `# <Topic>` and one line saying what it
is for; then tables or catalog sections. No frontmatter.

Script skeleton (`scripts/<tool>.py`):

```python
#!/usr/bin/env python3
"""<One line purpose.>

Subcommands
  check FILE...        <what>; exit 1 on failure
Stdlib only, Python 3.9+. Exit codes: 0 ok, 1 check failed, 2 usage or I/O error.
"""
from __future__ import annotations
import argparse, json, sys

def cmd_check(a) -> int:
    report = {"file": a.file, "errors": [], "warnings": []}
    # ... deterministic checks only ...
    print(json.dumps(report, indent=2))
    return 1 if report["errors"] else 0

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    x = s.add_parser("check"); x.add_argument("file"); x.set_defaults(fn=cmd_check)
    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except (OSError, ValueError) as e:
        sys.stderr.write("error: %s\n" % e)
        return 2

if __name__ == "__main__":
    sys.exit(main())
```

## 4. Saved workflow (complete, passes doctor and the harness)

Example name `claim-check`; rename `meta.name`, the file and `USAGE`. Uses only agents that
exist in this stack (`fact-checker`, `adversarial-verifier`).

```js
export const meta = {
  name: 'claim-check',
  description: 'Check a list of factual claims: one fact-checker per claim, then an adversarial-verifier pass on claims marked supported, returning verdicts with sources',
  whenToUse: 'A draft, report or answer contains several independent factual claims that must be verified before it ships. args {claims: [string], verify?: boolean = true, maxClaims?: number = 40}',
  phases: [
    { title: 'Check', detail: 'fact-checker per claim, pipelined' },
    { title: 'Verify', detail: 'adversarial-verifier tries to refute each supported claim' },
  ],
}

const USAGE = 'Call /claim-check with {claims: ["...", "..."], verify?: true, maxClaims?: 40}'
let A
try { A = typeof args === 'string' ? JSON.parse(args) : (args || {}) } catch (e) { return { started: false, reason: 'args is not valid JSON: ' + e.message, next: USAGE } }
const claims = Array.isArray(A.claims) ? A.claims.filter(c => typeof c === 'string' && c.trim()) : []
if (!claims.length) return { started: false, reason: 'claims must be a non-empty array of strings', next: USAGE }
const maxClaims = Math.max(1, Math.min(200, Math.floor(Number(A.maxClaims)) || 40))
const verify = A.verify !== false
const work = claims.slice(0, maxClaims)
if (claims.length > work.length) log('CAPPED: ' + (claims.length - work.length) + ' claims beyond maxClaims=' + maxClaims + ' were not checked')

const CHECK = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['supported', 'refuted', 'mixed', 'unverifiable'] },
    sources: { type: 'array', items: { type: 'object', properties: { url: { type: 'string' }, accessed: { type: 'string' }, quote: { type: 'string' } }, required: ['url'] } },
    note: { type: 'string' },
  },
  required: ['verdict', 'sources'],
}
const REFUTE = {
  type: 'object',
  properties: { refuted: { type: 'boolean' }, reason: { type: 'string' } },
  required: ['refuted', 'reason'],
}

phase('Check')
const results = await pipeline(work,
  (claim, _orig, i) => agent(
    'Fact-check this claim. Find at least 2 independent primary sources if they exist. Claim: ' + JSON.stringify(claim) +
    '\nReturn verdict (supported | refuted | mixed | unverifiable), sources (url, access date YYYY-MM-DD, quote under 15 words), and a one-line note.',
    { agentType: 'fact-checker', schema: CHECK, label: 'check #' + (i + 1), phase: 'Check' }),
  async (check, claim, i) => {
    if (!check) return { claim, check: null, verified: null }
    if (!verify || check.verdict !== 'supported') return { claim, check, verified: null }
    const v = await agent(
      'Try to refute this claim, which a fact-checker marked supported. Default to refuted=true if the evidence is insufficient.\nClaim: ' +
      JSON.stringify(claim) + '\nSources given: ' + JSON.stringify(check.sources),
      { agentType: 'adversarial-verifier', schema: REFUTE, label: 'refute #' + (i + 1), phase: 'Verify' })
    return { claim, check, verified: v }
  })

const rows = results.map((r, i) => r || { claim: work[i], check: null, verified: null })
const failed = rows.filter(r => !r.check).map(r => r.claim)
if (failed.length) log(failed.length + ' claims returned no result (agent skipped or failed)')
return {
  started: true,
  checked: rows.length,
  skipped: claims.slice(work.length),
  failed,
  results: rows.map(r => ({
    claim: r.claim,
    verdict: r.check ? (r.verified && r.verified.refuted ? 'contested' : r.check.verdict) : 'error',
    sources: r.check ? r.check.sources : [],
    refutation: r.verified ? r.verified.reason : null,
  })),
}
```

Fixtures for the harness (`fx.json`):

```json
{
  "fact-checker": [
    {"verdict": "supported", "sources": [{"url": "https://example.org/a", "accessed": "2026-10-19", "quote": "..."}]},
    {"verdict": "refuted", "sources": []}
  ],
  "adversarial-verifier": {"refuted": true, "reason": "single secondary source"},
  "label:check #3": null
}
```

`node scripts/wf_harness.js claim-check.js --args '{"claims":["a","b","c"]}' --fixtures fx.json --quiet`
returns 4 agent calls (3 checks, 1 refutation), one failed claim (`c`) and verdicts
`contested`, `refuted`, `error`.

Patterns to reuse:

| Need | Shape |
|---|---|
| Per-item multi-stage | `pipeline(items, stage1, stage2)`; stage callbacks get `(prev, item, index)` |
| Dedup or vote across all items | `const all = await parallel(thunks)` then plain-code merge, then next stage |
| Unknown-size discovery | loop until 2 consecutive rounds add nothing new; dedup against everything seen |
| Optional verification | inside a pipeline stage, return early when not needed (as `verify` above) |
| Budget-scaled fleet | `budget.total ? Math.floor(budget.total / 100000) : <default>` |

## 5. Tier entry (config/models.json, required) and learning bounds entry (optional)

```json
"agents": {
  "<name>": {"tier": "<TIER>", "effort": "<level>", "maxTurns": <n>, "why": "<one line>"}
}
```

Learning bounds (`config/learning.json`):

```json
"agents": {
  "<name>": {"maxTurns": [<lo>, <hi>], "effort": ["<lo>", "<hi>"]}
}
```

Use `{"learn": false}` for agents that must keep hand-set values.

## 6. Settings entry for a workflow

```json
"permissions": { "allow": [ "...", "Workflow(<name>)" ] }
```
