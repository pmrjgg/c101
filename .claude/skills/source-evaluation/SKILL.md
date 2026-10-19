---
name: source-evaluation
description: "Evaluating sources and citations - primary vs secondary vs tertiary, authority, recency and volatility, conflicts of interest, corroboration and independence (origin groups), red flags, an A-E evidence grading scale, fact-check verdicts, citation format with URL and access date, and the under-15-word quoting limit. Load when choosing which sources to trust, grading evidence, fact-checking a claim, or formatting citations."
when_to_use: "Before citing anything, when sources disagree, when a claim will be built on, and when checking another agent's citations."
---

# Source evaluation

Two distinct judgements, never merged:
1. **Source quality**: how much a given source can be trusted for a given kind of claim.
2. **Evidence strength for a claim**: how well the whole body of sources supports one atomic claim.

A strong source can carry a weak claim (a peer-reviewed paper cited for something it only mentions
in passing) and weak sources can jointly make a strong claim (if truly independent).

## 1. Source types

| Type | Examples | Good for | Typical failure |
|---|---|---|---|
| Primary | official docs, release notes, source code, standards, statutes, court records, filings, datasets, original papers, direct statements by the party | facts the source owns; original data | self-interest; spin in framing, not in data |
| Secondary | journalism with own reporting, review articles, textbooks, independent benchmarks, systematic reviews | synthesis, context, independent checks | transcription errors, overstated findings, staleness |
| Tertiary | encyclopedias, aggregators, listicles, "top 10" posts | finding primaries | citogenesis, no accountability |
| User-generated | forums, Q&A sites, issue threads, social posts | reproductions, workarounds, field reports | unverified, anecdotal; maintainer replies are the exception |
| Generated / SEO | content farms, auto-generated pages, AI summaries | nothing as evidence | fabricated specifics, plausible but wrong |

Rule: cite the primary for any fact it owns. Use secondaries to find primaries, to add independent
checks, and for synthesis the primary cannot provide about itself.

## 2. Source quality rubric

Score each criterion 0-2 for the claim at hand:

| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| Authority | anonymous, no track record | known outlet or practitioner | owner of the fact, standards body, maintainer, peer-reviewed venue |
| Proximity | third-hand or uncited | cites a primary | is the primary |
| Recency fit | older than the volatility window | within window, undated update | dated, within window |
| Method transparency | no method | partial (sample or setup missing) | full method, data or scripts |
| Independence | party with a stake in the claim | indirect interest (sponsorship, affiliate) | no stake |
| Internal consistency | numbers or dates contradict each other | minor slips | consistent |

Total 0-12. Source grade: **A** 11-12, **B** 8-10, **C** 5-7, **D** 3-4, **E** 0-2.
Any criterion at 0 caps the grade at C, except Independence = 0 on a fact the party owns (a vendor's
own release date) which stays uncapped.

Lateral reading beats inspecting the page itself: search what others say about the outlet or author
(SIFT: Stop, Investigate the source, Find better coverage, Trace claims to the original context).

## 3. Evidence grade for a claim (A-E)

| Grade | Requirement | Wording in output |
|---|---|---|
| A | 2+ independent sources from different origin groups, at least one primary graded A/B, no credible contradiction; or the owner's primary on its own fact with method visible | state as fact, cite |
| B | 1 strong primary plus consistent secondaries from the same origin; or 2+ independent B-grade secondaries | state as fact, cite, note basis if asked |
| C | 1 credible secondary; or a primary with caveats (preprint, small sample, old, vendor-run) | "reported by", "according to" |
| D | weak sources only (forums, undated, anonymous) or inference across sources | "unconfirmed reports", list as Open doubt if load-bearing |
| E | contradicted by stronger evidence, or no adequate source | do not assert; mention only if the caller will meet it elsewhere |

Confidence mapping for the output-contract: A 0.90-0.97, B 0.75-0.90, C 0.55-0.75, D 0.35-0.55,
E below 0.35. A composite answer takes the lowest grade among its load-bearing claims.

## 4. Independence test (corroboration)

Two sources corroborate only if all hold:
1. Different organisations (a vendor's docs and the same vendor's blog are one source).
2. Neither cites the other for this claim.
3. They do not share an upstream: same press release, wire story, dataset, paper, or benchmark run.
4. They did not both copy from a tertiary source (Wikipedia citogenesis).

Assign each source an **origin group** label (`acme-press-2026-03`, `NVD`, `smith2025-dataset`) and
count groups, not URLs. Trace a statistic back to the table it came from; if three articles cite
"a study" and none links it, that is zero verified sources until you find the study.

## 5. Recency and staleness

| Volatility | Examples | Window |
|---|---|---|
| very high | prices, stock levels, versions, rankings, availability, incidents in progress | days to weeks |
| high | API behaviour, policies, people in roles, laws in transition, model leaderboards | 1-6 months |
| medium | best practices, architecture guidance, market structure | 1-2 years |
| low | history, mathematics, physical constants, settled science | stable |

Dates: record published and updated. Missing: `mcp__jina__guess_datetime_url` (keep its confidence),
page metadata, `curl -sI <url>` Last-Modified (weak: servers rewrite it), first Wayback capture as an
upper bound on age. Staleness rule: if the newest adequate source is older than the window, answer
"as of <source date>", flag `stale`, cap confidence at 0.7.

## 6. Conflicts of interest

Downgrade one grade level and seek independent corroboration when the source:
- benchmarks its own product or a competitor's;
- is sponsored, an advertorial, or uses affiliate links;
- is funded by a party with a stake (check the paper's funding and competing-interests statements);
- is an advocacy group, a law firm marketing a practice, or a PR release.

A conflict of interest does not make a claim false; it makes it unconfirmed until independent
evidence agrees. Keep conflicted sources in a separate, labelled bucket when comparing numbers.

## 7. Red flags (check before citing)

- The cited source does not actually say it: open it and find the sentence.
- Numbers without denominators, baselines, units or dates; percentages of unknown wholes.
- Screenshots of text or charts with no link to the original.
- Retracted or corrected papers: check the publisher page for notices and the Retraction Watch
  database; check whether the preprint result changed in the published version.
- Lookalike domains, mismatched publisher name and domain, newly registered sites.
- Generated filler: generic phrasing, no named people, invented-looking specifics, no outbound citations.
- Superlatives ("fastest", "industry-leading") with no measurement.
- A quote attributed to a person with no primary record (talk, transcript, post).

## 8. Fact-check verdicts

For each claim (fact-checker's return format):

```
C<n>: <claim, exactly as given>
Verdict: supported | contradicted | unverifiable   [+ stale] [+ partly: <which part>]
Best source: <URL> (published YYYY-MM-DD, accessed YYYY-MM-DD), grade <A-E>
Quote: "<under 15 words>"
Note: <scope or date condition under which the verdict holds; what is wrong if contradicted>
```

- **supported**: an adequate source (grade B or better for the claim) says it, in scope and in date.
- **contradicted**: an equal or stronger source says otherwise in the same scope; state the correct value.
- **unverifiable**: no adequate source after the search budget; never upgraded by reasoning.
- Add `partly` when a compound claim is half right; split it if the caller allows.
- Add `stale` when the best source is older than the volatility window.

## 9. Citation format

Inline markers `[n]` after the claim they support. Reference list:

```
[n] <Author or Org>. "<Title>." <Publisher or site>, <published YYYY-MM-DD>[, updated YYYY-MM-DD]. <URL> (accessed YYYY-MM-DD).
```

- Papers: `Authors (Year). "Title." Venue. arXiv:<id> | doi:<doi>.` (literature-review has BibTeX form).
- Point to the location: section anchor, page number for PDFs (`#page=12`), table or figure number.
- Code: permalink with commit SHA and line range (`github.com/o/r/blob/<sha>/path#L10-L42`), not a
  branch link.
- Datasets: name, version or vintage, table id, access date.
- Never cite a search results page, an AI summary, or a URL you did not open.

Quoting:
- Quotes under 15 words, verbatim, in quotation marks, attributed. At most one quote per source in a
  given answer; paraphrase everything else.
- Never reproduce song lyrics, poems, or long passages, even when asked.
- Mark omissions with `...` and do not change meaning; `[sic]` for errors in the original.

## 10. Procedure for a claim you are about to rely on

1. Atomise: one subject, one predicate, one number with unit, scope and date.
2. Identify the owner of the fact; search it first (web-search-tools, primary-pinned).
3. Read the sentence in the source; record location and a short quote.
4. Grade the source (section 2), then the claim (section 3) after counting origin groups.
5. Check the window (section 5) and conflicts of interest (section 6).
6. Decide the wording from the grade table; record the citation.

Worked gradings (vendor benchmark, preprint vs published, news vs filing, forum fix, statistic
trace): [grading examples](references/grading-examples.md). Where primary sources live per domain:
[primary source catalog](references/primary-sources.md).
