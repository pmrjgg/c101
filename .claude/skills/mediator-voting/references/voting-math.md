# Voting math reference

Exact definitions used by `scripts/tally.py` and by `/mediate`. Notation: candidates
C = {S1..Sk}, voters i = 1..N with weight w_i >= 0, W = sum_i w_i. A ballot ranking is a list of
tiers (best first); candidates in one tier are tied; unranked candidates form an implicit last tier.

## Contents
- Plurality
- Borda count
- Approval
- Pairwise matrix and Condorcet
- Schulze
- Logarithmic opinion pool (and linear pool for comparison)
- Margins, near-ties and robustness
- Properties table
- Equivalence clustering

## Plurality

score(S) = sum over voters of w_i / |T1_i| if S is in voter i's first tier T1_i.

- Majority criterion: if one candidate is first for more than W/2, it wins.
- Weakness: vote splitting. Two near-identical good candidates split their supporters and a third,
  polarizing one wins (the worked example in SKILL.md: S1 wins plurality with 2/5).
- Use only for self-consistency style votes over short answers where ballots are answers.

## Borda count

With k candidates, a voter's tier at 0-based positions [p, p+|T|) awards each member the average
of (k-1-p), (k-2-p), ..., i.e. tied candidates share the points of the positions they span.
score(S) = sum_i w_i * points_i(S). Max possible score: W(k-1).

- Rewards consistently high placement (compromise candidates).
- Clone-sensitive (teaming): adding a near-copy of S pushes rivals down one position on every ballot
  that ranks both copies above them, so near-duplicates must be merged first.
- Never elects a Condorcet loser, but can fail to elect a Condorcet winner.
- `--no-self`: the voter's own candidate gets the neutral midpoint (k-1)/2 instead of its earned
  points, so the author neither helps nor hurts it.

## Approval

score(S) = sum of w_i over voters approving S. Approval answers "acceptable or not"; it carries no
preference between approved candidates. Ask for approvals with a concrete bar ("would ship as-is",
"would sign off in review"), otherwise voters approve everything that is not wrong.

## Pairwise matrix and Condorcet

d[X][Y] = sum of w_i over voters with rank_i(X) strictly better than rank_i(Y). Voters who tie X
and Y, or (with `--no-self`) authored either, contribute to neither side.

- X is the **Condorcet winner** iff d[X][Y] > d[Y][X] for all Y != X.
- A **Condorcet cycle** exists when the pairwise majority relation is cyclic (A beats B, B beats C,
  C beats A). Any Condorcet-consistent method elects the Condorcet winner when one exists.

## Schulze

Winning-votes variant (the one implemented):

```
for X != Y:  p[X][Y] = d[X][Y] if d[X][Y] > d[Y][X] else 0
for i in C:                     # Floyd-Warshall "widest path"
  for j in C, j != i:
    for k in C, k != i, k != j:
      p[j][k] = max(p[j][k], min(p[j][i], p[i][k]))
X beats Y  iff  p[X][Y] > p[Y][X]
winner: X with p[X][Y] >= p[Y][X] for every Y   (always exists; may be several = tie)
ranking: successive unbeaten tiers (tier 1 = winner set; remove it, repeat). The beat relation is
         transitive; ranking by the number of candidates beaten is NOT equivalent when paths tie
```

Complexity O(k^3); trivial for k <= 20.

### Worked cycle example (9 voters, 3 candidates)

| Count | Ballot |
|---|---|
| 4 | A > B > C |
| 3 | B > C > A |
| 2 | C > A > B |

Pairwise matrix d (row beats column):

| | A | B | C |
|---|---|---|---|
| A | - | 6 | 4 |
| B | 3 | - | 7 |
| C | 5 | 2 | - |

A beats B 6-3, B beats C 7-2, C beats A 5-4: a cycle, no Condorcet winner.
Links: A->B 6, B->C 7, C->A 5. Strongest paths p:

| | A | B | C |
|---|---|---|---|
| A | - | 6 | min(6,7)=6 |
| B | min(7,5)=5 | - | 7 |
| C | 5 | min(5,6)=5 | - |

A vs B: 6 > 5, A vs C: 6 > 5, B vs C: 7 > 5. Schulze ranking A > B > C. Compare: plurality A
(4/3/2, margin 1/9, fragile), Borda ties A and B at 10 points each (C has 7). Report as near-tie
(no Condorcet winner), run the debate round between A and B.

The pure 3-voter cycle (A>B>C, B>C>A, C>A>B) gives all p entries equal to 2: Schulze reports a
three-way tie. That is the correct answer; go to the tie-break cascade.

## Logarithmic opinion pool

Each voter gives p_i(S) in [0,1]. Clip to [c, 1-c] with c = 0.02 (one zero would veto a candidate
under any geometric rule, and LLM extremes are poorly calibrated).

**Exclusive candidates** (exactly one can be correct):

```
q_i(S)   = p_i(S) / sum_S' p_i(S')                         # make each voter coherent
L(S)     = sum_{i in V_S} w_i log q_i(S) / sum_{i in V_S} w_i  # V_S: voters who scored S
P(S)     = exp(d * L(S)) / sum_S' exp(d * L(S'))            # d = 1: plain log pool
```

**Non-exclusive candidates** (several can be acceptable): pool each candidate on the logit scale,
`P(S) = sigmoid(d * sum_i w_i logit(p_i(S)) / sum_i w_i)`.

Linear pool for comparison: P(S) = sum_i w_i q_i(S) / W. It is never more extreme than the most
extreme voter and is the safer choice when voters may be wrong in correlated ways; the log pool
sharpens when voters agree and is externally Bayesian (pooling then updating on shared evidence
equals updating then pooling). The mediator uses the log pool to rank and the linear pool as a
sanity bound in the report. Details and extremizing rules: `bayesian-aggregation`.

Worked check (SKILL.md example, V1): p = (.7, .5, .2, .1) normalizes to (.467, .333, .133, .067).
Geometric means across the 5 voters: S1 .176, S2 .351, S3 .181, S4 .137; normalized:
.209 / .415 / .214 / .162.

## Margins, near-ties and robustness

| Method | Margin | Near-tie threshold |
|---|---|---|
| plurality | (s1 - s2) / W | 0.20 |
| approval | (s1 - s2) / W | 0.20 |
| borda | (s1 - s2) / (W(k-1)) | 0.10 |
| schulze | (p[win][run] - p[run][win]) / W on strongest paths (never negative), run = second-tier candidate with the smallest deficit | 0.20, or no Condorcet winner |
| logpool | P1 - P2 | 0.10 |

Additional near-tie triggers (method independent):
- **Leave-one-voter-out**: re-tally N times dropping one ballot each; any changed or tied winner.
  With 5 equal voters, a 3-2 pairwise result is always fragile by this test, which is intended.
- **No-self**: re-tally ignoring each voter's preference involving its own candidate; winner changes.
- **Method sensitivity** (report only): winners differ across methods. Explain why (usually clones
  or self-votes for plurality, polarization for Borda vs Schulze).

Thresholds assume 3-7 voters. For a weighted panel use the same thresholds on weight fractions.

## Properties table

| Property | Plurality | Borda | Approval | Schulze | Log pool |
|---|---|---|---|---|---|
| Elects Condorcet winner when one exists | no | no | no | yes | no |
| Never elects Condorcet loser | no | yes | no | yes | no |
| Robust to near-duplicate candidates | no (splitting) | no (teaming) | partly | yes (independence of clones) | partly |
| Uses preference intensity | no | ordinal only | no | no | yes (probabilities) |
| Resolves cycles deterministically | n/a | n/a | n/a | yes | n/a |
| Needs calibrated inputs | no | no | no | no | yes |

Arrow's theorem means no ranked method satisfies every fairness criterion at once; declare the
method in advance and report robustness instead of searching for a perfect rule.

## Equivalence clustering

Merge two solutions into one candidate when the Phase 0 equivalence rule says so. Typical rules:

| Problem type | Equivalent when |
|---|---|
| Choose among named options | same option chosen (rationale may differ) |
| Numeric answer | equal within the declared tolerance (absolute or relative) |
| Code / algorithm | same outputs on the declared test inputs and same asymptotic complexity |
| Design decision | same load-bearing decisions (list them in FRAME.md); details may differ |
| Proof / derivation | same conclusion AND both valid; different valid proofs of the same result are one candidate |

Borderline pairs stay separate; Schulze tolerates clones, a wrong merge destroys information.
