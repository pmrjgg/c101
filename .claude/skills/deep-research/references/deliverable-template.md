# Deep research deliverable template

Copy into `<out_dir>/<stamp>-<slug>.md`. Keep the `##` headings: callers map them with
`grep -n '^## '`. Summary first, detail later; every factual sentence carries `[n]`.

```markdown
# <Question as a title>

As of YYYY-MM-DD. Prepared by deep-researcher for <caller>. Depth: <quick|standard|exhaustive>.

## Summary
<Executive answer, at most 150 words. Lead with the answer to the decision. State the one or two
conditions that would change it. Overall confidence: 0.xx (band).>

## Key findings
| # | Finding | Status | Grade | Confidence | Sources |
|---|---|---|---|---|---|
| F1 | <one-sentence claim with number, unit, date, scope> | confirmed | A | 0.90 | [3][7] |
| F2 | <...> | owner-attested | B | 0.85 | [5] |
| F3 | <...> | single-source (reported) | C | 0.55 | [9] |

## Analysis
### SQ1 <sub-question>
<Answer in 1-3 paragraphs. Mechanism or reasoning, then evidence with [n], then caveats.
Numbers: value, unit, population, method, date.>
### SQ2 ...

## Contradictions and how they were handled
| id | Conflict | Diagnosis | Resolution |
|---|---|---|---|
| X1 | <A> vs <B> | scope: managed vs self-hosted | both hold under stated conditions |
| X2 | <A> vs <B> | genuine disagreement | presented both; leaning A because <evidence> |

## Gaps and open questions
- <What could not be established, why, and what would establish it (data, access, experiment).>

## Recommendations
<Only if the brief asked for them. Each recommendation traces to findings: "Because F1 and F3, ...".>

## Method
- Sub-questions: <n>. Rounds: <n> (stopped because: dry | cap | budget).
- Queries: <n> (Exa <n>, Jina <n>, arXiv/SSRN <n>, WebSearch <n>). Crawls: <site, pages>.
- Sources screened: <n>; read in full: <n>; origin groups: <n>; fact-checked claims: <n>
  (<supported>/<contradicted>/<unverifiable>).
- Modality gaps: <e.g. Spider unavailable; paywalled sources not read>.
- Ledgers: `<stamp>-<slug>/claims.md`, `sources.jsonl`, `contradictions.md`.

## Sources
[1] <Author or Org>. "<Title>." <Publisher>, <published YYYY-MM-DD>. <URL> (accessed YYYY-MM-DD). <type>, grade <A-E>.
[2] ...
```

## Writing rules

- Lead with the answer; method goes last.
- Separate what sources report from what you infer: "Vendor benchmarks report X [4]; no independent
  replication was found" rather than "X is true".
- Hedge with numbers and conditions, not adverbs: "0.6 probability", "on datasets under 10M rows".
- Quotes: under 15 words, in quotation marks, attributed, at most one per source. Prefer paraphrase.
- Tables for comparisons of 3+ items; prose for mechanisms.
- No finding without a status; no number without a unit, date and scope.
- Keep the document under about 600 lines; move bulky tables to a sibling `.json` or appendix file
  and link it.
