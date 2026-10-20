# Review formats

All reviews go to the project's `reviews/` folder, named `<YYYYMMDD-HHMM>-<kind>[-NNN].md`. The
shared header, summary, findings, strengths and next-steps sections follow manuscript-project
section 5.

## 1. Developmental review (`reviews/<stamp>-developmental.md`)

```markdown
# Developmental review: <title>

- Project: <path>  |  Chapters: 001-024 (82,140 words)  |  Date: <YYYY-MM-DD HH:MM>
- Reviewer: manuscript-reviewer  |  Tools: Python <ver>, manuscript.py index+stats

## Summary
Two to six sentences: what the book does well, the one or two changes that would most improve it.

| category | count | high | med | low |
|---|---|---|---|---|
| structure | 3 | 1 | 2 | 0 |
| plot-logic | 2 | 1 | 1 | 0 |
| character | 4 | 0 | 3 | 1 |
| pov-tense | 1 | 0 | 1 | 0 |
| continuity | 5 | 2 | 3 | 0 |
| pacing | 2 | 0 | 2 | 0 |
| openings-endings | 3 | 0 | 1 | 2 |

## Pacing map
| ch | words | cum % | dialogue | avg sent | turn | tension |
|---|---|---|---|---|---|---|
| 001 | 3120 | 3.8 | 0.34 | 13.1 | Mara takes the surveyor across | rising |

## Findings
| # | file:line | category | excerpt | why | suggestion |
|---|---|---|---|---|---|
| 1 | chapters/012_flood.md:1-210 | structure | (chapter is a memory) | midpoint does not turn; outline's reversal is missing | move the letter burning (016:44-90) here |

## Strengths
- ...

## Next steps
1. Structural: ...
2. Continuity: proposed bible entries (paste-ready block)
```

Categories: structure, plot-logic, stakes, character, pov-tense, continuity, pacing,
openings-endings, scene (scene without a turn).

## 2. Merged manuscript review (`reviews/<stamp>-manuscript-review.md`)

```markdown
# Manuscript review: <title>

- Project: <path>  |  Chapters: <range> (<words> words)  |  Date: <stamp>
- Reviewer: manuscript-reviewer (synthesis)  |  Inputs: N copyedit reports, N style reports, developmental pass
- Tools: Python <ver>, manuscript.py, prose_check.py <checks>, <hunspell/LanguageTool if used>

## Summary
Verdict: needs structural revision | ready for line editing | ready for copyedit | ready to submit.
Top actions in priority order (five by default, at most ten), each with the anchors it fixes.

| area | high | med | low |
|---|---|---|---|
| developmental | | | |
| style | | | |
| copyedit | | | |

## Developmental findings
(table as in the developmental review)

## Book-level line patterns
| # | pattern | category | chapters (count) | example anchor | suggestion |
|---|---|---|---|---|---|
| L1 | "a wave of X washed over" | generic-prose | 003 (4), 007 (3), 011 (5) | chapters/007_x.md:52 | concrete reaction; see style-007 |

## Per-chapter overview
| ch | words | copyedit h/m/l | style h/m/l | developmental | reviews |
|---|---|---|---|---|---|
| 003 | 3,410 | 2/5/1 | 1/6/3 | weekday contradiction | reviews/<stamp>-copyedit-003.md, reviews/<stamp>-style-003.md |

## Conflicts between reviews
| anchor | copy-editor | prose-stylist | resolution |
|---|---|---|---|

## Strengths
- ...

## Revision plan
1. Global (structure, arcs) ...
2. Sequence and scenes ...
3. Continuity ...
4. Line patterns (book-wide search-and-fix list) ...
5. Copyedit pass (apply per-chapter reviews; fix-on-request) ...

## Coverage
Chapters reviewed, chapters skipped (and why), failed or missing chapter reviews.
```

Coverage is mandatory: a merged review that silently omits a chapter is wrong.
