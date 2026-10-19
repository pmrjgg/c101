# Verbal probability

Converting words to numbers is lossy: surveys show readers assign widely different probabilities to
the same phrase. Ask agents for numbers; use these tables only for legacy text or as the last resort.

## Contents
- ICD 203 (default mapping)
- Sherman Kent's words of estimative probability
- IPCC likelihood scale
- Confidence is not likelihood
- LLM phrasing rules

## ICD 203 (default mapping)

US Intelligence Community Directive 203 (2015) defines seven bands. `pool.py verbal` uses the
midpoints.

| Term (synonym) | Band | Midpoint used |
|---|---|---|
| almost no chance (remote) | 1-5% | 0.03 |
| very unlikely (highly improbable) | 5-20% | 0.12 |
| unlikely (improbable) | 20-45% | 0.32 |
| roughly even chance (roughly even odds) | 45-55% | 0.50 |
| likely (probable) | 55-80% | 0.67 |
| very likely (highly probable) | 80-95% | 0.87 |
| almost certain (nearly certain) | 95-99% | 0.97 |

## Sherman Kent's words of estimative probability

Kent's 1964 proposal for intelligence estimates:

| Term | Probability |
|---|---|
| certain | 100% |
| almost certain | 93%, give or take about 6% |
| probable | 75%, give or take about 12% |
| chances about even | 50%, give or take about 10% |
| probably not | 30%, give or take about 10% |
| almost certainly not | 7%, give or take about 5% |
| impossible | 0% |

Note the differences from ICD 203 ("probable" 0.75 here vs 0.67). When a source states which
scale it follows, use that scale.

## IPCC likelihood scale

IPCC assessment reports use nested, one-sided ranges: virtually certain 99-100%, extremely likely
95-100%, very likely 90-100%, likely 66-100%, more likely than not >50-100%, about as likely as not
33-66%, unlikely 0-33%, very unlikely 0-10%, extremely unlikely 0-5%, exceptionally unlikely 0-1%.

Because ranges nest, map each term to the middle of the part not covered by the next stronger
term (a convention, state it when used): likely 0.78 (66-90), very likely 0.92 (90-95),
extremely likely 0.97, virtually certain 0.995 (clip to 0.98 for pooling), about as likely as not
0.50, unlikely 0.22 (10-33), very unlikely 0.07 (5-10), extremely unlikely 0.03.

## Confidence is not likelihood

ICD 203 separates likelihood (how probable the event is) from confidence (how good the evidence
and reasoning are) and says not to combine them in one statement. "High confidence that X is
unlikely" is coherent. For pooling:

- Likelihood words become p.
- Confidence words do NOT become p; they inform whether to trust the input (and, with history,
  its weight).

In this stack an agent's output-contract `Confidence` is the probability that its Result is
correct. If it carries a number, use it. If it carries only a word, ask once for a number; if that
is impossible, map high 0.85, medium 0.65, low 0.40 as a last resort, mark the input as converted,
and prefer the linear pool so that a mis-mapped input has bounded influence.

## LLM phrasing rules

- "may", "might", "could", "possible", "it is conceivable": no defensible mapping (readers spread
  them over most of the 0.1-0.6 range). Do not convert; re-ask.
- Hedged numbers ("around 70%, maybe higher") use the number.
- Ranges ("60-80%") use the midpoint, and treat the width as information about the agent's own
  uncertainty, not as weight.
- "Certainly", "definitely", "guaranteed" from an LLM become 0.98 at most after clipping, and are a
  cue to ask for the evidence (verify instead of pooling).
- Mixed language across agents (one numeric, others verbal): convert, then report which inputs
  were converted.
