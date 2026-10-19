# Deep research worked example

Question from the caller: "Should our team move vector search from a dedicated vector database to
Postgres with pgvector for a 20M-embedding workload?"

This example shows the shape of a standard-depth run. Numbers inside angle brackets are filled from
the sources you actually read; nothing here is a finding.

## Phase 0: route
5 sub-questions, about 25 sources expected, no site-wide crawl needed: run it yourself with
delegated discovery. `remaining_depth` 5: leaves allowed.

## Phase 1: plan.md (excerpt)

```markdown
Decision this informs: platform team keeps or retires the dedicated vector DB in Q1.
Scope in: 20M x 768-dim embeddings, p95 < 50 ms, 200 QPS, filtered queries, managed Postgres.
Scope out: pricing negotiations, embedding model choice.
As-of: 2026-10-19
## Sub-questions
SQ1 [quantity] Recall/latency of pgvector HNSW at 10-50M vectors with metadata filters - owner: pgvector docs, independent benchmarks - web, papers
SQ2 [mechanism] How filtered search interacts with HNSW in pgvector (iterative scans, over-fetch) - owner: pgvector README/changelog - web
SQ3 [quantity] Index build time and memory at 20M x 768 - owner: pgvector docs, benchmarks - web
SQ4 [comparison] Operational trade-offs: backups, replication, upgrades, HA - owner: managed Postgres docs - web
SQ5 [landscape] Production reports of migrations in either direction - owner: engineering blogs - web
## Hypotheses
H1 pgvector meets p95 < 50 ms at 20M with filters - refuted if independent benchmarks at >=10M show p95 above 50 ms at recall >= 0.95
H2 (expected false) Dedicated DBs have no material advantage at this scale - refuted by consistent independent results showing 2x+ QPS at equal recall
```

## Phase 2: one message, five calls
- web-searcher x4 for SQ1, SQ3, SQ4, SQ5 (briefs from briefs.md; owner domains:
  `github.com/pgvector`, managed Postgres docs).
- Own calls for SQ2: `mcp__jina__read_url {url: ["https://github.com/pgvector/pgvector"], question: "filtering with HNSW, iterative index scans", topk: 4}`.

## Phase 3: triage outcome (illustrative)
- 41 records merged, 29 after canonical-URL dedup, 17 origin groups after collapsing syndicated
  posts and vendor reposts of the same benchmark.
- Grades: 4 A (pgvector README and changelog, managed Postgres docs), 6 B (independent benchmarks
  with published scripts), 5 C (vendor benchmarks: conflict of interest), 2 D (forum threads).

## Phase 4: claim ledger excerpt

| id | claim | supporting | contradicting | status |
|---|---|---|---|---|
| C2 | pgvector supports iterative index scans for filtered HNSW queries since <version> | S1 (README), S2 (changelog) | none | owner-attested |
| C5 | At ~10M vectors, pgvector HNSW reaches recall <x> at p95 <y ms> on <hardware> | S8 (indep), S11 (indep) | S14 (vendor) | contested |
| C9 | HNSW build at 20M x 768 needs <z GB> maintenance_work_mem to avoid slow builds | S3 (docs), S8 | none | confirmed |

## Phase 5: contradiction X1 (C5)
Diagnosis: method. S14 (a competing vendor) used default `ef_search` and no index-only tuning; S8
and S11 tuned `ef_search` and published scripts. Resolution: present both with conditions; leaning
toward S8/S11 because their method is reproducible, conflict of interest noted for S14.

## Phase 6: loop
Round 1: 22 queries, 14 confirmed claims (yield 0.64). Critique found: no contrarian production
report (SQ5), no data above 10M for filtered queries (SQ1). Round 2: 8 gap queries, 3 changes
(0.38), found one migration-away report. Round 3: 5 queries, 0 changes; no new origin group: dry.

## Phase 7: report skeleton (Summary)
"At 20M vectors with filters, pgvector is viable if <conditions from C2, C5, C9>; independent data
above 10M with filters is thin (gap G1), so run a two-day load test on production-shaped data before
deciding. Confidence 0.6 (medium): limited by G1."

Note how the gap converts into a concrete next action rather than a vague caveat.
