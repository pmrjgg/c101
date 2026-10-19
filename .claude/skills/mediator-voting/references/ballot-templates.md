# Ballot templates

Copy, fill the angle-bracket fields, send. Every brief is self-contained: the receiving agent has
no access to your conversation. Pass paths, never pasted content; the receiver reads with Grep and
line ranges. Voters keep their output-contract sections: structured replies go to a file and into a
fenced json block inside `## Result`, and the mediator extracts them with code (jq/python).

## Contents
- Solve brief
- Anonymization checklist
- Critique and ballot brief
- Debate brief
- Re-vote brief
- Synthesis brief
- JSON schemas

## Solve brief

```text
You are voter <Vi> in a mediated decision. Solve the problem below independently.
Do not spawn subagents. Do not look for other voters' answers.

Problem card: <path>/FRAME.md (read sections "Problem" and "Answer schema" only)
Inputs: <paths>
Perspective: <one sentence lens, e.g. "Prefer provable worst-case bounds over average-case claims.">

Return EXACTLY these sections, at most 600 words in total:
## Answer        (<=5 lines: the decision or result itself, stated so it can be checked)
## Rationale     (why this is right; the key step a skeptic should check first)
## Assumptions   (bulleted; mark each verified / unverified)
## Risks         (how this answer could be wrong)
## How to verify (a concrete check: command, test input, source, or derivation step)
Then the output-contract Confidence line as a probability that your Answer is correct.
Write the full answer to <run>/raw/<Vi>.md and return a 3-line summary plus the path.
```

## Anonymization checklist

Apply to every normalized candidate before labelling:

- [ ] Remove agent names and roles ("as the architect", "computer-science-expert here").
- [ ] Remove model or vendor names and effort hints ("thinking harder", "at xhigh").
- [ ] Remove references to the author's own tools or files that only one voter used
      (`<run>/raw/V3.md`, `.stack/out/mathematics-expert/...`); keep the evidence, replace the path
      with a neutral one under `<run>/evidence/`.
- [ ] Normalize headings to the answer schema; same markdown style for all.
- [ ] Remove confidence statements from the candidate text (they enter via ballots, not prose).
- [ ] Equalize length: cap at ~600 words, trim Rationale first, never Answer or How to verify.
- [ ] Grep the normalized files for leftovers:
      `grep -inE "expert|architect|decomposer|opus|sonnet|haiku|fable|as an? (ai|assistant|model)" <run>/S*.md`

## Critique and ballot brief

```text
You are voter <Vi>. Below are <k> anonymous candidate answers to the same problem, in the order
<S3, S4, S1, S2> (order differs per voter; it carries no meaning). One of them may be yours; judge
it exactly as you judge the others. Do not spawn subagents.

Problem card: <path>/FRAME.md
Candidates: <run>/S1.md ... <run>/S<k>.md

For EACH candidate, first write a critique: the most important defect (concrete: input, step or
claim that fails) and the most important strength. Length and polish are not merit.
List any objection that can be checked mechanically under checkable_objections with how_to_check.
Then write this JSON to <run>/ballots/<Vi>.json and repeat it as a fenced json block inside your
## Result section (keep the other output-contract sections around it):
{"voter": "<Vi>",
 "critique": {"S1": "...", ...},
 "checkable_objections": [{"target": "S1", "claim": "...", "how_to_check": "..."}],
 "ranking": ["best", "...", ["tied", "tied"], "worst"],   // every candidate exactly once
 "approvals": ["candidates you would ship as-is"],
 "p_correct": {"S1": 0.0, ...},                           // each in [0.02, 0.98], numeric
 "self_label": "S? or null"}
Your ranking must agree with your p_correct order unless you explain the exception in critique.
```

## Debate brief

```text
You authored candidate <Sa>. It is in a near-tie with <Sb>. Do not spawn subagents.
Your candidate: <run>/<Sa>.md      Rival: <run>/<Sb>.md
Critiques of your candidate: <run>/critiques-<Sa>.md     Critiques of the rival: <run>/critiques-<Sb>.md

In at most 300 words:
1. For each critique of your candidate: CONCEDE (and patch) or REBUT (with a checkable reason).
2. The single strongest reason the rival is worse, checkable.
3. Optional: a patched version of your candidate written to <run>/<Sa>-patched.md. A patch may fix
   defects; it may not adopt the rival's core decision (that would be a different candidate).
```

## Re-vote brief

```text
You are voter <Vi>. Two candidates remain after a debate round. Do not spawn subagents.
Candidate <Sa> (possibly patched): <path>     Candidate <Sb>: <path>
Rebuttals: <run>/debate.md
Write to <run>/revote/<Vi>.json and repeat as a fenced json block inside ## Result:
{"voter": "<Vi>", "prefer": "<Sa|Sb|tie>", "p_correct": {"<Sa>": x, "<Sb>": y},
"reason": "<=40 words, the deciding consideration"}
```

## Synthesis brief

Use when the mediator delegates synthesis (for example to `cross-domain-synthesizer`):

```text
Write the final answer for this decision. The winner is <Sw> (method <m>, margin <x>).
Winner: <path>. Runners-up: <paths>. Ballots and critiques: <run>/ballots.json.
Rules: start from the winner's text; graft an element from a runner-up only if a critique praised it
or its candidate got at least half the approval weight, AND it does not contradict a load-bearing
decision of the winner, AND it does not reintroduce a confirmed objection.
Return: the final answer, a graft table (element | from | why compatible | accepted/rejected),
and the list of winner decisions you treated as load-bearing.
```

## JSON schemas

Ballot file `<run>/ballots.json` (input to `scripts/tally.py`):

```json
{"candidates": ["S1", "S2", "S3"],
 "exclusive": true,
 "ballots": [
   {"voter": "V1", "ranking": ["S2", ["S1", "S3"]], "approvals": ["S2"],
    "p_correct": {"S1": 0.3, "S2": 0.8, "S3": 0.2}, "weight": 1.0, "author_of": "S1"}]}
```

- `author_of` comes from the sealed `labels.json`, not from `self_label` (that one is the voter's
  guess, used to measure whether blinding held).
- `weight` defaults to 1; set it only from a documented calibration source.
- Set `exclusive: false` when several candidates can be simultaneously acceptable.

Tally output (abridged): `results.<method>.{scores, ranking, winner, tie, runner_up, margin,
robustness.{leave_one_out, loo_stability, no_self_winner, self_rank, near_tie}}`, plus
`method_agreement` and `method_sensitive`.
