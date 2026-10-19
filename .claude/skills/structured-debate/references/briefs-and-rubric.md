# Debate briefs and judging rubric

All briefs are self-contained. Debaters and judges never see this conversation, only the files you
point them to. Directory: `<out_dir>/<YYYYMMDD-HHMM>-<slug>/` with `setup.md`, `transcript.md`,
`flow.md`, `judges/`.

## setup.md

```markdown
# Motion
This team should <action> <scope> <by when>, instead of <status quo>.
## Definitions
<term>: <meaning, unit, measurement boundary>
## Status quo
<what happens if the motion fails>
## Criteria (weights sum to 1)
| Criterion | Weight | 1 | 3 | 5 |
## Burden
Proposition must show the change beats the status quo on the weighted criteria; ties go to the status quo.
## Decision threshold
Majority of judges and abs(signed margin sum) >= 2.
## Evidence rules
Tags [E#] with URL+date, file:line, command+output path, or shown computation. Untagged = assertion.
Up to 2 challenges per side, verdicts binding. Quotes < 15 words. No new evidence in closing.
## Context files
<paths>
## Format and limits
Opening 600 / Rebuttal 500 (+3 questions) / Answers 300 / Closing 300 words.
```

## Debater brief, R1 opening

```text
You are the <Proposition|Opposition|Advocate for option X> in a structured debate. Argue the assigned
side as strongly and honestly as the evidence allows, regardless of your own view. Do not spawn
subagents. Do not edit any file except your output file.

Read: <dir>/setup.md and the context files it lists.
Write <dir>/rounds/R1-<side>.md containing up to 5 claims, numbered <P|O|A>1..:
  Claim: one sentence.
  Warrant: why the grounds support the claim.
  Evidence: [E#] tags with source (URL + access date, file:line, command and output path, computation).
  Impact: which weighted criteria it moves, in which direction, and roughly how much.
Limit 600 words; text beyond the limit is cut before the other side sees it.
Return a 2-3 line summary of your claims (ids + one line each) and the file path.
```

## Debater brief, R2 rebuttal and questions

```text
Same role and rules. Read setup.md, transcript.md (R1 of all sides) and your own R1.
Write <dir>/rounds/R2-<side>.md:
  For EVERY opposing claim id: Concede | Contest (counter-evidence) | Mitigate (smaller impact,
  quantify) | Turn (show it helps your side). Cite the id. Unanswered claims count as conceded.
  Up to 2 new claims in the R1 format.
  Up to 3 cross-examination questions to each opposing side, each answerable with yes, no, a number
  or "unknown".
Limit 500 words. Return a 2-3 line summary and the path.
```

## Debater brief, R3 answers

```text
Same role. Read transcript.md through R2 and the challenge verdicts in flow.md.
Answer each question addressed to you: direct answer first (yes / no / number / unknown), then at
most 80 words. Answering a different question is logged as an evasion. Limit 300 words. Write
<dir>/rounds/R3-<side>.md and return a 2-3 line summary and the path.
```

## Debater brief, R4 closing

```text
Same role. Read the full transcript and flow.md. Weigh the 2-3 clashes that decide the debate
against the weighted criteria and explain why your side wins each, citing claim ids and challenge
verdicts. No new claims, no new evidence (they will be struck). Limit 300 words. Write
<dir>/rounds/R4-<side>.md and return a 2-3 line summary and the path.
```

## Judge brief

```text
You are judge <J-k> in a structured debate. You did not take part. Do not spawn subagents.
Read: setup.md (criteria, weights, burden), flow.md (claim statuses, challenge verdicts, evasions),
then the transcript in this order: <side order for this judge>.

Rules:
- Decide on the weighted criteria in setup.md, not on your own preferences about the topic.
- The flow ledger outranks rhetoric: struck claims are gone; dropped claims stand but count only by
  their impact; assertions (untagged) carry little weight.
- Length is not merit. Confidence of tone is not evidence.
- Ties go to the status quo.

Write <dir>/judges/J-k.md with:
  Scores per side (1-5) for support, clash, impact on criteria, survival, candour, using the anchors
  below.
  Winner and margin: narrow (1), clear (2), decisive (3).
  Reasons for decision, <= 150 words, citing claim ids.
  Decisive clash: claim ids and why it decided.
  Strongest argument of the losing side.
  Flip premise: the single premise that, if false, would flip your verdict.
Return the path and your winner + margin in one line.
```

Rotate the side order across judges (J1 Prop first, J2 Opp first, J3 Prop first for two sides; a
Latin-square rotation for 3-4 sides).

## Rubric anchors

| Criterion | 1 | 3 | 5 |
|---|---|---|---|
| support | key claims are assertions; warrants missing | mix of B/C evidence; most warrants stated | load-bearing claims grade A/B; every warrant explicit |
| clash | ignored the strongest opposing claims or answered a straw man | answered most claims by id, some weakly | answered every strong opposing claim by id with counter-evidence or quantified mitigation |
| impact on criteria | arguments do not map to the weighted criteria | maps to criteria qualitatively | quantifies movement on the highest-weight criteria |
| survival | claims struck in challenges; evasions in CX | one claim weakened; answers mostly direct | all challenged claims survived; all answers direct |
| candour | concedes nothing; overclaims | concedes minor points | concedes where the evidence requires and reprices its case accordingly |

## Moderator checklists

Before R1:
- [ ] Motion passes the section 1 checklist; criteria, weights and burden are in setup.md.
- [ ] Debaters matched in tier; judges independent and of a different agent type (hence tier where
      possible) than the debaters.
- [ ] Spawn budget covers 8 + 3 + 4 calls (two sides) or 4k + 3 + 2k (k sides).

After each round:
- [ ] Every output within its limit (truncate and note).
- [ ] Flow updated: each claim's status; dropped claims marked.
- [ ] R2: questions extracted; challenges dispatched in one message; verdicts recorded.
- [ ] R4: new claims or evidence struck before judges see the transcript.

After judging:
- [ ] Signed margin sum computed; decision threshold applied.
- [ ] Flip premises from all judges collected into the assumption register.
- [ ] The six hidden-assumption scans run (SKILL.md section 10).
