# Manuscript project: layout spec, custom structures, report template

## 1. manuscript.md, complete example

```markdown
---
title: "Salt Road"
author: "A. Writer"
language: en-US
pov: multiple-close-third
tense: past
genre: literary
target_words: 90000
chapter_dir: chapters
chapter_pattern: "^(\d{3})_([a-z0-9][a-z0-9-]*)\.md$"
---
# Salt Road

## Logline
A salt-marsh ferrywoman must choose between her brother and the town that drowned their father.

## Synopsis
(one to three paragraphs; spoilers allowed, this file is for the writer and editors)

## Chapters
<!-- chapters:start -->
| # | file | title | words | status | pov |
|---|---|---|---|---|---|
| 001 | chapters/001_the-ferry.md | The Ferry | 3120 | draft | Mara |
<!-- chapters:end -->
```

Rules:
- Front matter values: plain scalars, quoted strings, integers, inline lists `[a, b]`. A regex value
  must be quoted. No nested maps, no multi-line values.
- Only `index --write` touches the block between the two chapter markers; the rest is the user's.
- `language` picks the word list (`en-US` today); other variants (`en-GB`, `pt-PT`, `pt-BR`) need a
  word-list file of the same name next to the prose script, no code change.

## 2. outline.md

```markdown
## 001 The Ferry
- Goal: Mara gets the last fare across before the storm.
- Conflict: the passenger is the surveyor who will condemn the marsh.
- Outcome: she takes him across (yes, but: her brother sees them).
- Sequel: reaction, dilemma, decision to hide the surveyor's papers.
```

One `## NNN <title>` heading per chapter, numbers matching the chapter files. Scene-sequel or
goal-conflict-outcome beats; free text is fine.

## 3. bible/ files

| File | Entry shape |
|---|---|
| `characters.md` | `## Name` then age, appearance (fixed traits only), voice notes, relationships, arc in one line, first appearance `001:14` |
| `places.md` | `## Place` then geography, sensory anchors, who lives there, first appearance |
| `timeline.md` | table `| in-story date | chapter | event |` in story order |
| `glossary.md` | table `| term | spelling | meaning | first use |` for invented words, titles, ship names, slang |

New facts invented while drafting are appended with the chapter anchor where they first appear, so
continuity checks can cite them.

## 4. style-sheet.md

```markdown
# Style sheet
- Spelling: US, Merriam-Webster 11th; CMOS 17/18 for fiction.
- Serial comma: yes. Em dash closed (word—word). Ellipsis: … (single character), spaced before only at sentence end.
- Numbers: spell out zero to one hundred and round numbers; years and times as digits (1994, 4:15).
- Dialogue: double quotes, single inside; punctuation inside closing quotes.
- Italics: thoughts no; foreign words not in MW yes; ship names yes.
## Names and terms
| term | form | notes |
|---|---|---|
| Mara Vell | Mara | never "Marah" |
| the Saltings | capitalized | the marsh as a place name |
## Character voice
- Tomas: short sentences, no contractions when angry.
## Banned phrases (project)
- "let out a breath she didn't know she was holding"
```

## 5. Custom structures

| User layout | Front matter |
|---|---|
| `chapters/ch01-arrival.md` | `chapter_pattern: "^ch(\d{2})-([a-z0-9-]+)\.md$"` |
| `scenes/0010_harbor.md` (gaps of ten) | `chapter_dir: scenes` and `chapter_pattern: "^(\d{4})_([a-z0-9-]+)\.md$"`; renumber off unless asked |
| `Chapter 01 - Arrival.md` | `chapter_pattern: "^Chapter (\d{2}) - (.+)\.md$"`; slugs are free text, `new` may refuse; suggest migration on request |
| parts in subfolders (`part-1/01_x.md`) | not supported by the pattern (one directory); propose a flat chapter_dir with part openers as chapters (`010_part-one.md`) or `concat` per part |

The pattern must contain exactly two capture groups, number then slug; validate after every change.

## 6. Report template

```markdown
# Copyedit report: Salt Road, chapter 003

- Project: ~/books/salt-road  |  Chapters: 003_the-letter.md  |  Date: 2026-10-20 14:32
- Reviewer: copy-editor  |  Tools: Python 3.13.1, prose_check.py mechanics+consistency, hunspell 1.7.2 (en_US)

## Summary
| category | count | high | med | low |
|---|---|---|---|---|
| punctuation | 7 | 2 | 4 | 1 |
| spelling | 3 | 3 | 0 | 0 |
| consistency | 2 | 1 | 1 | 0 |

## Findings
| # | file:line | category | excerpt | why | suggestion |
|---|---|---|---|---|---|
| 1 | chapters/003_the-letter.md:41 | punctuation | "I know." he said. | dialogue tag after a quote takes a comma | "I know," he said. |
| 2 | chapters/003_the-letter.md:57 | consistency | Marah stepped back | bible spells the name Mara | Mara stepped back |

## Strengths
- Dialogue punctuation is clean in the long argument (003:80-140), which carries most of the chapter.

## Next steps
1. Fix the 2 high punctuation findings and the name slip (5 minutes).
2. Add "the Saltings" to the style sheet; it appears in three spellings across the book.
```
