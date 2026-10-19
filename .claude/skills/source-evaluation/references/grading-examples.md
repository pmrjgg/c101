# Grading examples

Each example: the claim, the sources found, the scoring, and the resulting wording. Sources are
described generically; the method is the point.

## 1. Vendor performance claim

Claim: "Database X is 3x faster than Y for analytical queries."

| Source | Authority | Proximity | Recency | Method | Independence | Consistency | Total | Grade |
|---|---|---|---|---|---|---|---|---|
| X's blog benchmark | 1 | 2 | 2 | 1 (queries listed, hardware vague) | 0 | 2 | 8 | capped C (independence 0 on a competitive claim) |
| Independent benchmark with published scripts | 2 | 2 | 2 | 2 | 2 | 2 | 12 | A |
| News article repeating X's blog | 1 | 1 | 2 | 0 | 1 | 2 | 7 | C, same origin group as X's blog |

Origin groups: {X blog, news article} = 1, independent benchmark = 1. The independent run shows
1.4x on its workload. Claim grade: the "3x" is C (vendor only); "faster on TPC-H-like workload at
1.4x" is B (one independent primary with method).

Wording: "X reports a 3x speed-up on its own benchmark [1]; an independent run with published
scripts measured about 1.4x on <workload> [2]."

## 2. Preprint versus published version

Claim: "Method M improves accuracy by 4.1 points on benchmark B."

- arXiv v1 (2025-02): reports +4.1.
- Conference version (2025-10): reports +2.7 after fixing a data-leak issue noted by reviewers.

Rule: the published version supersedes the preprint unless the preprint is newer and says why.
Grade the +2.7 claim B (one primary, peer-reviewed, no independent replication); the +4.1 claim E
(superseded). Mention the change only if the caller is likely to meet the +4.1 figure.

## 3. News report versus filing

Claim: "Company C's revenue grew 30% last fiscal year."

- Business news article: "revenue up about 30%".
- Company's annual filing: revenue figures for both years give 27.6% growth; the 30% figure in the
  press release refers to a non-GAAP "constant currency" measure.

Grade: "27.6% reported revenue growth" A (owner-attested, audited filing); "30%" C with scope
"constant-currency, non-GAAP, per company press release". Present both with scope; this is a
definition difference, not a contradiction.

## 4. Forum fix for an error

Claim: "Setting `FOO_TIMEOUT=0` disables the timeout in tool T."

- Q&A answer with 300 upvotes, 2021.
- T's docs (current): `0` means "use the default", disabling requires `-1`.
- Maintainer comment in an issue (2024): behaviour changed in v3.

Grade: forum claim E for current versions (contradicted by owner docs), D-to-B historically (true
for v2, per maintainer). Wording: "In T v3+, `-1` disables the timeout; `0` restores the default [1].
Older answers recommending `0` predate v3 [2]."

## 5. Tracing a statistic

Claim: "90% of data was created in the last two years."

Trace: 15 articles repeat it; 6 attribute it to a company; the company's page links to a 2013
marketing report; that report gives no method. The number is also re-dated in each article ("last
two years" relative to the article date, not 2013).

Grade E as a current statistic (unverifiable, stale, re-dated). Wording if needed: "A widely repeated
figure traces to a 2013 marketing report without a published method [1]; no current measurement was
found."

## 6. Single primary owner of a fact

Claim: "Library L v5.0 was released on 2026-04-14."

Source: L's GitHub Releases page (tag date) and the package registry entry agree. Both are the
owner (same origin group), but the fact is the owner's own action and the method is the record
itself. Grade A (owner-attested). No independent corroboration needed.

## 7. Two independent secondaries, no primary

Claim: "Regulator R opened an inquiry into company Q in September."

- Outlet 1, own reporting, names two sources.
- Outlet 2, own reporting, different sources, adds the inquiry's reference number.
- No regulator press release found; the reference number does not resolve on R's site.

Grade B (two independent secondaries with own reporting), flagged "not confirmed by R". If the
decision is material, Open doubt: confirm on the regulator's register.
