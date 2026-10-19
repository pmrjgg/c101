# Worked example data: CI box

Inputs and verified outputs for the worked example in SKILL.md. Save the run-1 JSON below as
`box-run1.json` in your workspace, build `box-run2.json` from it with the additions listed under
run 2, then reproduce with:

```bash
STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"
python3 "$STACK/.claude/skills/triz-morphological/scripts/morph_box.py" box-run1.json --top 6 --diverse 4
python3 "$STACK/.claude/skills/triz-morphological/scripts/morph_box.py" box-run2.json --top 5 --diverse 4
```

Scores are illustrative 1-5 judgments for a mid-size codebase; replace them with your own (or have
two experts score independently and average) before relying on the ranking.

## Run 1: box-run1.json

```json
{
  "parameters": {
    "pr_selection":   ["affected", "ml-predicted", "all", "none"],
    "gate_selection": ["all", "affected"],
    "execution":      ["single", "sharded", "remote-exec"],
    "cache":          ["none", "local", "remote-cas"],
    "flakes":         ["retry-once", "quarantine", "none"]
  },
  "incompatible": [
    ["pr_selection=all", "gate_selection=affected", "PR lane stricter than the gate is inverted"],
    ["flakes=none", "gate_selection=all", "unhandled flakes block the merge queue"],
    ["flakes=none", "gate_selection=affected", "unhandled flakes block the merge queue"]
  ],
  "requires": [
    ["execution=remote-exec", "cache=remote-cas", "remote execution is built on a content-addressed store"]
  ],
  "criteria": {"speed": 0.4, "confidence": 0.4, "cost": 0.2},
  "scores": {
    "pr_selection=affected":     {"speed": 4, "confidence": 4, "cost": 4},
    "pr_selection=ml-predicted": {"speed": 5, "confidence": 3, "cost": 5},
    "pr_selection=all":          {"speed": 1, "confidence": 5, "cost": 1},
    "pr_selection=none":         {"speed": 5, "confidence": 1, "cost": 5},
    "gate_selection=all":        {"speed": 2, "confidence": 5, "cost": 2},
    "gate_selection=affected":   {"speed": 4, "confidence": 3, "cost": 4},
    "execution=single":          {"speed": 1, "confidence": 3, "cost": 5},
    "execution=sharded":         {"speed": 4, "confidence": 3, "cost": 3},
    "execution=remote-exec":     {"speed": 5, "confidence": 3, "cost": 3},
    "cache=none":                {"speed": 1, "confidence": 3, "cost": 3},
    "cache=local":               {"speed": 3, "confidence": 3, "cost": 4},
    "cache=remote-cas":          {"speed": 5, "confidence": 4, "cost": 4},
    "flakes=retry-once":         {"speed": 3, "confidence": 2, "cost": 4},
    "flakes=quarantine":         {"speed": 4, "confidence": 4, "cost": 3},
    "flakes=none":               {"speed": 2, "confidence": 3, "cost": 5}
  }
}
```

Output:

```text
box size 216, pairwise cells 89, incompatible pairs 3, requires rules 1
surviving 98 (pruned 54.6%)

top:
  3.96  pr_selection=ml-predicted  gate_selection=affected  execution=remote-exec  cache=remote-cas  flakes=quarantine
  3.92  pr_selection=affected  gate_selection=affected  execution=remote-exec  cache=remote-cas  flakes=quarantine
  3.88  pr_selection=ml-predicted  gate_selection=affected  execution=sharded  cache=remote-cas  flakes=quarantine
  3.88  pr_selection=ml-predicted  gate_selection=all  execution=remote-exec  cache=remote-cas  flakes=quarantine
  3.84  pr_selection=affected  gate_selection=affected  execution=sharded  cache=remote-cas  flakes=quarantine
  3.84  pr_selection=affected  gate_selection=all  execution=remote-exec  cache=remote-cas  flakes=quarantine

diverse shortlist:
  3.96  pr_selection=ml-predicted  gate_selection=affected  execution=remote-exec  cache=remote-cas  flakes=quarantine
  3.76  pr_selection=affected  gate_selection=all  execution=sharded  cache=remote-cas  flakes=quarantine
  3.72  pr_selection=affected  gate_selection=affected  execution=remote-exec  cache=remote-cas  flakes=retry-once
  3.72  pr_selection=none  gate_selection=affected  execution=sharded  cache=remote-cas  flakes=quarantine
```

Finding: the top configuration never runs the full suite anywhere (ML-predicted PR lane plus
affected-only gate). That is an unstated invariant, not a scoring error: "some lane must run every
test at least daily". Run 2 adds it as a parameter plus a requires rule.

## Run 2: box-run2.json (run 1 plus the invariant)

Added to run 1:

```json
"safety_net": ["none", "nightly-full"]
["gate_selection=affected", "safety_net=nightly-full", "some lane must run the full suite at least daily"]   (requires)
"safety_net=none": {"confidence": 2, "cost": 5}, "safety_net=nightly-full": {"confidence": 4, "cost": 3}   (scores)
```

Output:

```text
box size 432, pairwise cells 119, incompatible pairs 3, requires rules 2
surviving 154 (pruned 64.3%)

top:
  3.87  pr_selection=ml-predicted  gate_selection=affected  execution=remote-exec  cache=remote-cas  flakes=quarantine  safety_net=nightly-full
  3.83  pr_selection=affected  gate_selection=affected  execution=remote-exec  cache=remote-cas  flakes=quarantine  safety_net=nightly-full
  3.80  pr_selection=ml-predicted  gate_selection=affected  execution=sharded  cache=remote-cas  flakes=quarantine  safety_net=nightly-full
  3.80  pr_selection=ml-predicted  gate_selection=all  execution=remote-exec  cache=remote-cas  flakes=quarantine  safety_net=nightly-full
  3.77  pr_selection=affected  gate_selection=affected  execution=sharded  cache=remote-cas  flakes=quarantine  safety_net=nightly-full

diverse shortlist:
  3.87  pr_selection=ml-predicted  gate_selection=affected  execution=remote-exec  cache=remote-cas  flakes=quarantine  safety_net=nightly-full
  3.63  pr_selection=affected  gate_selection=all  execution=sharded  cache=remote-cas  flakes=quarantine  safety_net=none
  3.60  pr_selection=affected  gate_selection=affected  execution=sharded  cache=remote-cas  flakes=retry-once  safety_net=nightly-full
  3.57  pr_selection=ml-predicted  gate_selection=all  execution=remote-exec  cache=remote-cas  flakes=retry-once  safety_net=none
```

## Reading the result

- Pruning removed 64% of the box with four auditable rules; every pruned pair has a reason.
- The top row and the second row differ only in PR selection (ML-predicted vs dependency graph):
  a 0.04 score gap is noise at this scoring resolution. Decide by feasibility: ML selection needs
  enough failure history; dependency-graph selection needs a complete build graph.
- The diverse shortlist keeps a conservative option (full gate, no nightly) that a reviewer may
  prefer if merge-queue capacity is cheap. Present it; do not hide it behind the top score.
- Next checks: tester verifies hermeticity (cache soundness) on 20 random targets; quick-researcher
  or a CI-history query confirms failure-history volume for ML selection.
