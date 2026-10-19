# Argument defects: detection cues and moderator responses

Debaters (and judges) commit these. The moderator logs them in `flow.md` under Process notes; judges
are told which were logged. Logging is not striking: only failed evidence challenges strike claims.

| Defect | Cue in the transcript | Moderator response |
|---|---|---|
| straw man | rebuttal paraphrases an opposing claim without its id, or attacks a weaker version | return for rewrite citing the id and quoting the claim |
| motte and bailey | strong claim in opening (bailey), retreat to a trivial version when challenged (motte), strong version reused in closing | flow records the claim as the motte version; closing may not reclaim the bailey |
| equivocation | key term changes meaning between rounds or sides ("availability" as uptime vs CAP availability) | add a definition to setup.md; mark affected clashes as partly illusory |
| false dilemma | "either we migrate now or we fail at scale" | add a missing-option row to the assumption register |
| moving goalposts | the bar for the other side's evidence rises after it is met | judges told the bar as set in setup.md |
| Gish gallop | many weak claims to exceed the opponent's response capacity | 5-claim cap in R1, 2 new claims in R2; judges weigh by impact, not count |
| appeal to authority | "vendor X says", "experts agree" without primary evidence | assertion unless sourced; challenge eligible |
| survivorship | evidence drawn only from successes ("companies that migrated grew") | judges note selection; ask for the denominator in CX |
| base-rate neglect | vivid incident used as if typical | CX question: "how many incidents of this type in the last N months?" |
| unit or percentile slip | p50 compared with p99; Mb vs MB; per-node vs cluster | flow note; correct numbers before relay if unambiguous |
| precision theatre | estimates with false precision ("saves 37.4%") from guesses | judges weigh as grade D |
| tu quoque | "your option has the same problem" used to avoid answering | answered only if it shows the problem is equal in size; otherwise evasion |
| slippery slope | chain of unsupported "will lead to" steps | each link needs a warrant; unsupported links are assertions |
| circular | conclusion assumed in a premise ("it is safer because it has fewer risks") | flag; judges discount |
| post hoc | correlation in time presented as cause ("latency rose after the upgrade") | CX question asking for the mechanism or a controlled comparison |
| non-answer | CX answer that does not start with yes, no, a number or unknown | evasion logged |
| new in closing | claim or evidence absent from R1-R3 appears in R4 | struck before relay |
| concession laundering | concedes a point in R2, closing argues it again as if standing | flow status governs; judges told |

## Judge-side biases and controls

| Bias | Control |
|---|---|
| verbosity (longer seems better) | word limits with truncation; explicit instruction |
| position / order | rotate presentation order per judge |
| self-preference (judge favours text like its own) | judges of a different agent type (hence tier, config/models.json) from debaters where possible; no agent identity in labels |
| authority of tone | rubric anchors refer to evidence grades and claim statuses, not style |
| recency (last speaker remembered) | flow ledger read before the transcript |
| anchoring on the first clash | RFD must name the decisive clash and the losing side's strongest argument |

## Toulmin quick form (for the hidden-assumption scan)

```text
Claim:      what is asserted
Grounds:    the data offered
Warrant:    why the grounds support the claim (often unstated)
Backing:    support for the warrant (missing backing = hidden assumption)
Qualifier:  how strongly (always, usually, in regime R)
Rebuttal:   conditions under which the claim fails
```

Example: Claim "migration is high-risk". Grounds "40 stored procedures". Warrant "procedures depend on
semantics the target lacks". Backing: none given; the assumption is that the target's isolation and
procedural features differ in ways those 40 procedures use. Test: run the compatibility spike.
