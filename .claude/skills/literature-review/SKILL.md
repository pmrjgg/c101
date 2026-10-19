---
name: literature-review
description: "Academic literature workflow - scoping a review, arXiv and SSRN search via Jina, Exa paper search, scholarly APIs for citation chaining (Semantic Scholar, OpenAlex, Crossref, arXiv), screening with reason codes, three-pass paper reading (abstract, contributions, method, results, limitations), like-for-like comparison matrices, faithful equation and algorithm extraction, and BibTeX-style reference lists. Load when surveying papers, comparing methods, tracing a result to its origin, or extracting equations or algorithms from papers."
when_to_use: "Any task whose evidence is mainly papers or preprints - related-work surveys, method comparisons, finding who introduced an idea, checking what a paper actually reports, or turning a paper's algorithm into a spec."
---

# Literature review

Deliverables, under your `out_dir`:

```
<stamp>-<slug>.md             synthesis (output-contract offload target)
<stamp>-<slug>/protocol.md    question, criteria, search log, PRISMA-lite counts
<stamp>-<slug>/screen.tsv     id, title, year, decision, reason code
<stamp>-<slug>/cards/<key>.md one paper card per included paper
<stamp>-<slug>/matrix.md      comparison matrix
<stamp>-<slug>/refs.bib       BibTeX-style reference list
```

## 1. Scope the review

| Review type | Use when | Papers screened / included | Rounds of chaining |
|---|---|---|---|
| Rapid | "what are the main approaches to X", a decision this week | 30-60 / 8-15 | 1 backward |
| Scoping | map a field: method families, benchmarks, open problems | 100-300 / 25-60 | 1 backward + 1 forward |
| Systematic-lite | "does X beat Y on Z", claims will be published or built on | 200+ / all that meet criteria | until saturation |

Write `protocol.md` before searching:

```markdown
Question: <in the form Problem / Method / Comparison / Outcome>
  e.g. P: long-context LLM inference; M: KV-cache compression; C: full cache, other compression; O: accuracy on long-context benchmarks, memory, latency
Inclusion: <years, publication types (peer-reviewed, preprints?), languages, must report O on a named benchmark>
Exclusion: <E-codes below>
Sources: arXiv, SSRN, Exa publication search, Semantic Scholar / OpenAlex chaining, venue proceedings
Search log: | # | date | tool | query | hits | new |
Counts: identified <n> -> deduplicated <n> -> screened <n> -> full-text <n> -> included <n>
```

Exclusion reason codes for `screen.tsv`: **E1** out of scope, **E2** no evaluation on the outcome,
**E3** superseded version (keep the latest), **E4** duplicate, **E5** not comparable setting
(different task or metric), **E6** full text inaccessible (record, do not silently drop),
**E7** not primary research (survey or position paper: mine its references instead).

## 2. Search

Run the seed searches in one message:

| Tool | Call | Notes |
|---|---|---|
| `mcp__jina__search_arxiv` | `{query: [5 variants], num: 10}` | CS, maths, physics, quant-bio, econ, stats; variants use the field's terms of art; add `tbs: "qdr:y"` only for a last-12-months rapid review (origin tracing and scoping need older work; use Exa `startPublishedDate` or S2 `year=` for exact windows from protocol.md) |
| `mcp__jina__search_ssrn` | `{query: [variants], num: 10}` | economics, finance, law, management, social science working papers |
| `mcp__exa__web_search_advanced_exa` | `{query: "A paper proposing <method idea> evaluated on <benchmark>", category: "publication", startPublishedDate: "<YYYY-MM-DD>", numResults: 20}` | neural: describe the paper you want; also `category: "pdf"` |
| Exa advanced, venue-pinned | `includeDomains: ["openreview.net", "aclanthology.org", "proceedings.neurips.cc", "proceedings.mlr.press", "dl.acm.org", "ieeexplore.ieee.org"]` | peer-reviewed versions |
| Scholarly APIs via Bash `curl` | see [scholarly APIs](references/scholarly-apis.md) | keyword search with year filters, citation counts, chaining |

Query variants: the method name, its family name, the problem phrased as the community does, the
benchmark name, and a contrarian query (`"<method>" limitations`, `"<method>" fails`,
`revisiting <method>`). Log every query.

Dedup: one canonical id per paper (DOI if published, else `arXiv:<id>` without version). Map arXiv
versions and published versions to the same paper; keep both links on the card.

## 3. Screen

1. Title/abstract pass over every unique hit: include, exclude (reason code), or maybe.
2. Full-text pass over include + maybe.
3. A second judgement on "maybe" items: a quick independent re-screen (for large sets, a fan-out
   of source-summarizer calls with the inclusion criteria) and accept when both agree; disagreements
   go to full text.

Keep exclusions; the counts in protocol.md must reconcile.

## 4. Read papers: three passes

| Pass | Time | Read | Output |
|---|---|---|---|
| 1 | 5-10 min | title, abstract, introduction's contribution list, section headings, figures, conclusion | 5 Cs: category, context (closest prior work), correctness (assumptions plausible?), contributions, clarity; include/exclude decision |
| 2 | 30-60 min | method, experimental setup, main results tables, ablations, limitations | full paper card with numbers and locations |
| 3 | hours | everything; re-derive key steps; check code | only for the 2-5 papers the conclusion rests on |

Tools:
- Abstract and metadata: `mcp__jina__read_url {url: ["https://arxiv.org/abs/<id>"]}`.
- Full text: `https://arxiv.org/html/<id>` when it exists (cleaner maths and tables), else
  `https://arxiv.org/pdf/<id>`; publisher PDFs via their DOI landing pages when open access.
- Targeted: `read_url` with `question: "What datasets and metrics are used, and what are the main results?"`, `topk: 4`.
- Tables, equations, figures: `mcp__jina__extract_pdf {id: "<arXiv id>", type: "table,equation"}`.
- Papers longer than ~40 pages or many papers at once: source-summarizer per paper with the card
  template, then you read only the cards.

Paper card (full template: [paper card](references/paper-card.md)): citation key, links, problem,
contribution claims (as the authors state them), method in 3-5 lines, setup (data, splits, metric,
baselines, compute), headline results with table or figure numbers, ablations, stated limitations,
your noted limitations, code and data availability, reproductions found.

## 5. Comparison matrix

| key | year | venue | family | core idea | benchmark / split | metric | result | best baseline (same table) | compute | code | caveats |
|---|---|---|---|---|---|---|---|---|---|---|---|

Rules:
- Compare numbers only on the same benchmark, split, metric and protocol. Otherwise put them in
  separate blocks and say "not directly comparable" with the reason.
- Prefer each paper's numbers for its own method; for baselines prefer the baseline's own paper or
  an independent reproduction over a competitor's re-run.
- Mark **reported** (from the paper) vs **reproduced** (independent run) vs **re-run by competitor**.
- Record variance or confidence intervals when given; single-run deltas under about 1 point on noisy
  benchmarks are not evidence of improvement.

## 6. Citation chaining

- **Backward**: references of each included paper (Semantic Scholar `/references`, OpenAlex
  `referenced_works`, or the paper's bibliography).
- **Forward**: papers citing it (Semantic Scholar `/citations`, OpenAlex `filter=cites:<W id>`).
- Rank candidates: relevance to the question first, then recency, then citation count (citation
  counts favour older papers and popular venues; do not use them as quality).
- Saturation: stop when a chaining round adds fewer than 10% new included papers, or two rounds add
  none. Record the round counts in protocol.md.
- Origin tracing ("who introduced X?"): walk backward until the earliest paper that defines the idea;
  check that later papers credit it; distinguish the term's coinage from the idea's first use.

## 7. Faithful equation and algorithm extraction

1. Copy notation exactly as the paper writes it; define every symbol as the paper defines it, with
   its section.
2. Cite location: `(Eq. 7, Sec. 3.2, p. 5 of arXiv:<id>v<n>)`. Version matters: equations change
   between versions.
3. LaTeX in `$$...$$`; do not simplify or "improve" inside the extraction. Corrections go in a
   separate note: `Note: Eq. 7 appears to miss a 1/N factor; Eq. 9 and the code (<permalink>) include it.`
4. Algorithms: preserve step order, loop structure, inputs, outputs, and every hyperparameter with
   its default and the paper's recommended range. Keep the paper's line numbering.
5. Check dimensional and shape consistency (matrix shapes, units) and that the extracted algorithm
   reproduces any worked example in the paper.
6. Cross-check against the official code when it exists; differences between paper and code are
   findings, report both.
7. Never fill a gap by invention: write `[not specified in the paper]`.

Example extraction:

```markdown
Scaled dot-product attention (Eq. 1, Sec. 3.2.1, arXiv:1706.03762):
$$\mathrm{Attention}(Q, K, V) = \mathrm{softmax}\!\left(\frac{QK^\top}{\sqrt{d_k}}\right) V$$
Symbols: Q, K, V are the query, key and value matrices; d_k is the key dimension (paper: d_k = 64 in the base model).
```

## 8. Synthesis

Structure the synthesis by question, not by paper:
1. Taxonomy of approaches (families, their core trade-off).
2. What is established (multiple independent results agree, comparable settings).
3. What is contested (conflicting results; diagnose: setting, metric, compute, data leakage).
4. What is missing (benchmarks not covered, regimes untested, no reproductions).
5. Implications for the caller's decision.

Every sentence of type "X improves Y" carries the evidence grade (source-evaluation) and the
setting: "improves accuracy by 2-3 points on B at 7B scale [3][5]; no result above 70B".

## 9. References

BibTeX-style list in `refs.bib` and numbered list in the synthesis. Key = first author's surname +
year + first title word, lowercase (`vaswani2017attention`). Format details and examples:
[reference formats](references/bibtex.md).

## Delegation

| Task | Agent | Notes |
|---|---|---|
| Pass-1 cards for 20+ papers | source-summarizer via parallel Agent calls in ONE message (3-5 papers per call, up to 20 calls, `run_in_background: false`); larger sets: return `Workflow name=fanout args={items, agentType: "source-summarizer", promptTemplate}` as an Open doubt (only the main thread, with no `<stack-context>` header, launches workflows) | give the card template path and the inclusion criteria; each child writes its cards to its own path and returns summary + paths |
| A sub-area of a scoping review | paper-researcher per sub-area | disjoint query sets; merge matrices yourself |
| Verify headline numbers you will rely on | fact-checker | batch 5 claims per call with paper locations |
| Reproduce a small result or run released code | tester or the matching expert | only when the decision depends on it |
| Equations needing domain judgement | mathematics-expert, physics-expert, quantum-computing-expert, computer-science-expert | one scoped question each |

## Never

- Cite a paper you have only seen in a search snippet or another paper's related-work section.
- Compare numbers across different benchmarks, splits, metrics or protocols as if comparable.
- Present a preprint's claim as peer reviewed, or an abstract's claim as the paper's measured result.
- Alter an equation or algorithm silently, or fill missing details by guessing.
- Circumvent paywalls; use the open version or record E6.
