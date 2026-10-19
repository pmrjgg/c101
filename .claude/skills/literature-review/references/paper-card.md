# Paper card template

One file per included paper: `cards/<key>.md`. Fill from the paper itself; anything you infer is
marked `(inferred)`. Locations (section, table, figure, page) on every number.

```markdown
# <key>: <Title>
Authors: <list>   Year: <yyyy>   Venue: <venue or "preprint">   Status: peer-reviewed | preprint | workshop
Links: arXiv:<id>v<n> | doi:<doi> | code: <url or none> | data: <url or none>
Versions read: <v1/v3/published>; differences noted: <none | list>

## Problem
<1-2 sentences, the authors' framing>

## Claimed contributions (authors' words, paraphrased)
1. ...
2. ...

## Method
<3-5 lines: core idea, what is new versus the closest prior work [key]>
Key equations: Eq. <n> (Sec. <s>) - see extraction below if needed

## Setup
Datasets / benchmarks: <name, split, size>
Metrics: <name, direction (higher/lower better)>
Baselines: <list, and whether re-run or copied from prior papers>
Compute: <hardware, hours, model size>
Seeds / variance: <n runs, std or CI if given | single run>

## Results
| benchmark | metric | this paper | best baseline | delta | location |
|---|---|---|---|---|---|

## Ablations
<which components matter, with locations>

## Limitations
Stated by authors: <list, location>
Noted by reviewer (you): <e.g. single seed, tuned on test, baseline under-tuned, compute not matched>

## Reproductions and follow-ups
<independent reproductions, refutations, or "none found" (with search date)>

## Relevance to our question
<1-3 lines; include/exclude decision and reason code>
```

## Pass-1 shortcut (5 Cs, for screening)

```markdown
# <key>
Category: <method | analysis | benchmark | system | survey>
Context: <closest 1-3 prior works>
Correctness: <assumptions look plausible? red flags?>
Contributions: <1-3 bullets>
Clarity: <readable | dense | unclear>
Decision: include | exclude E<n> | maybe
```

## Red flags while reading

- Baselines copied from older papers with different settings.
- Hyperparameters tuned on the test set; no validation split mentioned.
- Gains within run-to-run noise; single seed.
- Compute or data not matched between method and baselines.
- Benchmark contamination risk (test data plausibly in pretraining data) not discussed.
- Claims in the abstract that the results tables do not show.
