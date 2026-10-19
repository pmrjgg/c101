# Metric definitions

Exact counting rules, so numbers are reproducible and comparable only when computed the same way.

## Cyclomatic complexity (McCabe, 1976)

Graph form: M = E - N + 2P (edges, nodes, connected components of the control-flow graph).
Practical form per function: M = 1 + number of decision points.

| Counted as +1 | Notes |
|---|---|
| `if`, `elif`/`else if` | `else` is not counted |
| `for`, `while`, `do-while`, comprehension `for`/`if` clauses | |
| each `case` label | `lizard -m` (modified CCN) counts a whole `switch` as 1 |
| `catch`/`except` clauses | |
| `&&`, `\|\|`, `and`, `or` | some tools skip boolean operators; state which you used |
| ternary `?:`, `?? ` (tool dependent) | |

Meaning: M is the number of linearly independent (basis) paths: the test count for basis-path coverage
and an upper bound on the tests needed for branch coverage (two sequential `if`s: M=3, branch coverage
needs 2). NIST SP 500-235 recommends 10 as a limit, with up to 15 accepted
when justified.

## Cognitive complexity (G. Ann Campbell, SonarSource, 2017)

Three rules:
1. **Ignore** structures that let several statements read as one (method declarations, null-coalescing
   `?.`/`??`, early `return`, unlabeled `break`/`continue`).
2. **Increment +1** for each break in linear flow: `if`, `else if`, `else`, ternary, `switch` (once for
   the whole switch), `for`, `foreach`, `while`, `do while`, `catch`, `goto`, labeled `break`/`continue`,
   each *sequence* of like boolean operators (`a && b && c` is +1; `a && b || c` is +2), and each
   recursive call (+1 per method in the recursion cycle).
3. **Nesting increment**: `if`, ternary, `switch`, loops and `catch` nested inside another flow
   structure (or inside a nested function/lambda) add +nesting level on top of their +1.
   `else`/`else if` add +1 but no nesting increment.

Worked example (from the original paper):

```javascript
function sumOfPrimes(max) {
  let total = 0;
  OUT: for (let i = 1; i <= max; ++i) {      // +1
    for (let j = 2; j < i; ++j) {            // +2 (nesting 1)
      if (i % j === 0) {                     // +3 (nesting 2)
        continue OUT;                        // +1 (labeled continue)
      }
    }
    total += i;
  }
  return total;
}                                            // cognitive 7, cyclomatic 4
```

```javascript
function getWords(number) {
  switch (number) {                          // +1
    case 1: return "one";
    case 2: return "a couple";
    case 3: return "a few";
    default: return "lots";
  }
}                                            // cognitive 1, cyclomatic 4
```

The pair shows why cognitive complexity is the better readability metric: a flat switch is easy to
read; nested loops with a labeled jump are not. Sonar's default function threshold is 15.

## Halstead and Maintainability Index

- n1, n2 = distinct operators, operands; N1, N2 = total operators, operands.
- Vocabulary n = n1 + n2; length N = N1 + N2; volume V = N log2 n; difficulty D = (n1 / 2) (N2 / n2);
  effort E = D V.
- Maintainability Index (original): MI = 171 - 5.2 ln(V) - 0.23 M - 16.2 ln(LOC). Visual Studio rescales
  to 0..100 with max(0, MI x 100 / 171); radon uses a variant that also rewards comments.
- Use MI only for trend lines inside one tool; it is opaque and dominated by size.

## Size

- NLOC: non-blank, non-comment lines (lizard). SLOC definitions differ across tools (scc, tokei, cloc);
  pick one tool per report.
- Function length correlates with defect density mostly through complexity; report both.

## Coupling (Chidamber-Kemerer and Martin)

| Metric | Definition |
|---|---|
| CBO (coupling between objects) | Number of other classes a class uses or is used by |
| RFC (response for a class) | Methods of the class + methods directly called by them |
| DIT (depth of inheritance tree) | Inheritance levels from the root |
| NOC (number of children) | Direct subclasses |
| Ce (efferent) | Classes inside a package that depend on classes outside it |
| Ca (afferent) | Classes outside a package that depend on classes inside it |
| I (instability) | Ce / (Ca + Ce); 0 = maximally stable, 1 = maximally unstable |
| A (abstractness) | Abstract classes and interfaces / total classes in the package |
| D (distance from main sequence) | \|A + I - 1\| |

Interpretation:
- Stable Dependencies Principle: depend in the direction of decreasing I.
- Zone of pain: A near 0 and I near 0 (concrete and heavily depended upon, e.g. a shared utility or a
  schema package). Changes are expensive; keep it small and deliberate.
- Zone of uselessness: A near 1 and I near 1 (abstractions nobody uses).
- For languages without classes, apply Ca/Ce/I at module or package level and A as the share of
  exported interfaces/traits/type classes.

## Cohesion

- LCOM1 (CK): pairs of methods sharing no field minus pairs sharing at least one (floored at 0). Sensitive
  to method count; avoid comparing across classes of different size.
- LCOM4 (Hitz and Montazeri): build a graph whose nodes are methods; connect two methods if they access
  the same field or one calls the other. LCOM4 = number of connected components.
  - 1: cohesive. >= 2: the class contains independent responsibilities; each component is a candidate
    class. 0: no methods (or only accessors, depending on the tool).
  - Exclude constructors and simple getters/setters, or every field access becomes a bridge.

Example: `class Invoice` with methods `{add_line, total}` touching `lines`, and `{send_email, render_pdf}`
touching `customer`, `template`: two components, LCOM4 = 2. Split into `Invoice` and `InvoiceDelivery`.

## Cycles

A dependency cycle is a strongly connected component (SCC) of the module graph with more than one
node. Tarjan's algorithm finds all SCCs in O(V + E):

```python
import sys
from collections import defaultdict

def sccs(edges):
    """edges: iterable of (src, dst). Returns list of SCCs with more than one node."""
    sys.setrecursionlimit(100000)
    g = defaultdict(list)
    nodes = set()
    for a, b in edges:
        g[a].append(b); nodes.update((a, b))
    index, low, stack, on, out, i = {}, {}, [], set(), [], [0]
    def visit(v):
        index[v] = low[v] = i[0]; i[0] += 1; stack.append(v); on.add(v)
        for w in g[v]:
            if w not in index:
                visit(w); low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop(); on.discard(w); comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                out.append(sorted(comp))
    for v in sorted(nodes):
        if v not in index:
            visit(v)
    return out
```

Feed it edges from `madge --json`, `go list`, `jdeps --dot-output`, or an import-grep, collapsed to
package level.

## Churn and hotspots

- Commits per file in a window (default 12 months, merges excluded).
- Lines changed (added + deleted) per file: heavier weight on rewrites; noisy with formatting commits,
  so prefer commit counts for ranking and lines for context.
- Defect signal: commits whose subject has fix/fixes/fixed/bug/hotfix/regression/patch as a whole word
  (the hotspots.py rule). Crude but useful; if the
  repo links issues (e.g. `Fixes #123` with a bug label), use that instead.
- Hotspot score: product of percentile ranks of churn and complexity (both in (0, 1]). Percentiles make
  the two scales comparable and reduce the effect of extreme outliers.
- Change coupling between files A and B: shared_commits(A, B) / min(commits(A), commits(B)); report
  pairs with at least 10 shared commits and coupling >= 0.5 that have no static dependency.

## Type coverage

- TypeScript (`type-coverage`): share of identifiers whose type is not `any` (explicit or implicit).
- Python (mypy): `--txt-report`/`--linecount-report` give per-module counts of typed vs untyped lines;
  `--any-exprs-report` counts expressions of type `Any`. pyright's `--verifytypes <package>` reports the
  completeness of a package's public API types.
- Go, Rust, Java, Kotlin are statically typed; track escape hatches instead: `any`/`interface{}`
  parameters (Go), `unsafe` blocks (`cargo geiger`), raw types and unchecked casts (Java), `!!` and
  platform types (Kotlin).
