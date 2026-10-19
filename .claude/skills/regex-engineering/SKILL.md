---
name: regex-engineering
description: "Writing correct, fast and portable regular expressions: when to use a parser instead, flavor differences (PCRE2, Python re, JavaScript u/v flags, RE2/Go, Rust regex, Java, .NET, POSIX grep/sed/awk), test-table-driven construction, anchoring and full-match validation, Unicode traps, catastrophic backtracking diagnosis and fixes, and safe multi-file search-and-replace. Load when writing, debugging or reviewing a regex or an rg/sed/perl rewrite."
when_to_use: "Any re.compile/RegExp/regexp.MustCompile/Pattern.compile/Regex(...) in a diff; input validation with a pattern; a parser built from regexes; slow requests or CPU spikes traced to a regex (ReDoS); 'invalid or unsupported Perl syntax' when porting to Go/RE2; 'look-behind requires fixed-width pattern'; bulk rewrites with rg, sed -i, perl -pi or sd."
---

# Regex engineering

Practice for writing and reviewing regexes. Automata theory (regular languages, NFA/DFA construction,
pumping lemma) stays in `cs-foundations` section 6; the ReDoS threat-model entry stays in
`security-review`; test-suite design in `testing-strategy`. Verified on Python 3.13/3.14, Node 24 and
Go 1.27; check other flavors' docs before relying on an edge case.

Deep material: [flavor matrix, replacement and escaping syntax](references/flavor-matrix.md) |
[worked example: full Python and Go code with tests](references/log-parser-example.md)

## 1. Regex or parser?

| Input | Use | Not a regex because |
|---|---|---|
| Tokens, log lines, IDs, flat key=value, simple line formats | regex | (fits) |
| HTML / XML | lxml, selectolax, html5lib, BeautifulSoup | nesting, attribute order, entities, comments |
| JSON / YAML / TOML | `json`, `jq`, a YAML/TOML parser | nesting, escapes, numbers |
| CSV / TSV | `csv` module, `encoding/csv`, a CSV library | quoted fields with commas and newlines |
| URLs | `urllib.parse`, WHATWG `URL`, `net/url` | schemes, IDNA, percent-encoding |
| Dates and times | `datetime.fromisoformat`, `dateutil`, `time.Parse`, `Temporal` | calendars, offsets, leap rules |
| Numbers with ranges ("0-255", "1-31") | regex for shape `[0-9]{1,3}`, then parse and compare | range logic in regex is unreadable and wrong |
| Balanced or nested constructs | a real parser (recursive descent, PEG, tree-sitter) | regular languages cannot count |
| Email addresses | loose sanity check (`^[^@\s]+@[^@\s]+\.[^@\s]+$`) plus a verification message | RFC 5322 is not worth matching; deliverability is the real test |

## 2. Flavor matrix (summary; full table in [the flavor reference](references/flavor-matrix.md))

| Feature | PCRE2 (`grep -P`, `rg -P`, PHP) | Python `re` | JavaScript | Go / RE2 | Rust `regex` | Java | .NET |
|---|---|---|---|---|---|---|---|
| Lookahead | yes | yes | yes | **no** | **no** | yes | yes |
| Lookbehind | yes (bounded length) | fixed width only | yes (any length) | **no** | **no** | bounded length | any length |
| Backreferences | yes | yes | yes | **no** | **no** | yes | yes |
| Atomic `(?>...)` / possessive `a++` | yes / yes | yes / yes (3.11+) | **no / no** | no / no | no / no | yes / yes | yes / no |
| Named group | `(?<n>)`, `(?P<n>)` | `(?P<n>)`; `(?<n>)` only in the `regex` module | `(?<n>)` | `(?P<n>)`; `(?<n>)` from Go 1.22 | `(?P<n>)`, `(?<n>)` (1.8+) | `(?<n>)` | `(?<n>)`, `(?'n')` |
| String anchors | `\A`, `\z`, `\Z` | `\A`, `\Z` (= end); `\z` from 3.14 | none: `^`/`$` without `m` | `\A`, `\z` | `\A`, `\z` | `\A`, `\z`, `\Z` | `\A`, `\z`, `\Z` |
| `$` without multiline | end or before final `\n` | end or before final `\n` | end only | end only | end only | end or before final line terminator | end or before final `\n` |
| `\p{L}` | yes | no (`regex` module yes) | with `u` or `v` | yes | yes | yes | yes |
| Inline flags `(?i)` / scoped `(?i:...)` | yes / yes | yes / yes | ES2025 scoped modifiers only | yes / yes | yes / yes | yes / yes | yes / yes |
| Linear-time guarantee | no (JIT is still backtracking) | no | no | **yes** | **yes** | no | only `RegexOptions.NonBacktracking` (.NET 7+) |
| Match timeout | match limits | no (`regex` module: `timeout=`) | no | n/a | n/a (size limits) | no | yes: `new Regex(p, o, TimeSpan)` |

JavaScript flags: `u` (code points, `\p{...}`), `v` (ES2024: `u` plus set operations `[\p{L}--[a-z]]`,
string properties), `d` (match indices), `y` (sticky), `s` (dotall). `RegExp.escape` is ES2025
(Node 24 has it). POSIX BRE/ERE (`grep`, `sed`, `awk`): no `\d` (use `[0-9]` or `[[:digit:]]`), no lazy
quantifiers, no lookaround; GNU adds `\+ \? \|` to BRE and `\b \< \>`; BSD/macOS `sed -i` needs a
suffix argument (`sed -i ''`). Go/Rust with lookaround needs: restructure (section 11), or `fancy-regex`
(Rust) / `regexp2` (Go), which reintroduce backtracking.

## 3. Construction procedure

1. **Write the test table first**: 5-15 rows, positive and negative, including the near misses (empty
   field, extra space, trailing newline, wrong case, non-ASCII digit, maximum length).
2. **Anchor**: validation uses full-match (section 4); search patterns get explicit delimiters.
3. **Build incrementally**: one field at a time, run the table after each addition.
4. **Prefer negated classes to lazy dots**: `"[^"]*"` instead of `".*?"`; it cannot run past the
   delimiter and backtracks less.
5. **Name groups** and read them by name; positional `group(3)` breaks when a group is added.
6. **Verbose mode** (`re.X`; `(?x)` in PCRE, Java, Rust and .NET; Go/RE2 has none, so concatenate
   commented string pieces) with one comment per line for anything over ~40 characters. In verbose
   mode whitespace is ignored: write a literal space as `\x20` or `[ ]`.
7. **Compile once** as a module-level constant (`LOG_LINE = re.compile(...)`,
   `var logLine = regexp.MustCompile(...)`); never inside a loop or per request.
8. **Check worst-case time** (section 6) before merging.

## 4. Validation versus search

| Need | Python | JavaScript | Go | Java |
|---|---|---|---|---|
| Whole string must match | `re.fullmatch(p, s)` | `/^(?:...)$/` (no `m` flag) | `^(?:...)$` | `matcher.matches()` |
| Find anywhere | `re.search` | `re.exec` / `str.match` | `FindString` | `matcher.find()` |
| Starts with | `re.match` (anchors at start only) | `/^.../` or sticky `y` | `^...` | `lookingAt()` |

- Python `$` and `re.match(r"...$")` accept a trailing newline: `re.search(r"^abc$", "abc\n")` is a
  match. Use `re.fullmatch` or `\Z` (`\z` also works from 3.14).
- Wrap alternations before anchoring: `^cat|dog$` means `(^cat)|(dog$)`; write `^(?:cat|dog)$`.
- `re.M` / `m` makes `^`/`$` match at every line; `re.S` / `s` makes `.` match `\n`. A validator with
  `m` accepts `"ok\nDROP TABLE"` because one line matched.
- Limit input length before matching (`if len(s) > 256: reject`); it bounds the worst case on any engine.

## 5. Unicode traps

| Trap | Behaviour | Fix |
|---|---|---|
| Python 3 `\d`, `\w` on `str` | match any Unicode digit/letter: `re.fullmatch(r"\d+", "١٢٣")` succeeds | `[0-9]`, `[A-Za-z0-9_]`, or `re.ASCII` |
| Go `\d`, `\w`, `\b`; JS `\d`, `\w`, `\b` (even with `u`) | ASCII only | `\p{Nd}`, `\p{L}` (JS needs `u`/`v`) when Unicode is wanted |
| Case-insensitive `i` | Python `(?i)i` matches `I`, `ı` and `İ`; JS `/i/iu` matches none of the Turkish forms | lowercase with an explicit locale before matching when the locale matters |
| German sharp s | `(?i)ß` matches `ẞ` but not `SS` in Python `re` and JS | `regex` module full case folding `(?fi)` or `casefold()` both sides |
| Combining marks | `é` precomposed vs `e` + U+0301: `re.fullmatch("\u00e9", "e\u0301")` fails | normalize both pattern input and text (`unicodedata.normalize("NFC", s)`; NFKC for compatibility forms) |
| Grapheme clusters | one emoji family is 5+ code points; `.` matches one code point | `\X` (PCRE2, Python `regex`), `Intl.Segmenter` in JS |
| JS astral characters | `/^.$/.test("😀")` is false without `u` | always use `u` or `v` |
| `\b` next to non-ASCII | JS and Go treat `é` as a non-word char, so `\bcafé\b` fails at the end | explicit classes or lookaround with `\p{L}` |

## 6. Catastrophic backtracking

Backtracking engines (PCRE2, Python, JS, Java, .NET default) can take exponential or polynomial time
when several paths match the same text and the overall match then fails.

| Dangerous shape | Example | Why |
|---|---|---|
| Nested quantifiers | `(a+)+$`, `(\w+\s?)+$` | 2^n ways to split the run |
| Overlapping alternation under a quantifier | `(a\|ab)*c`, `(\w\|\d)+` | both branches match the same chars |
| Adjacent unbounded tokens sharing chars | `.*.*=`, `\s*\s*$`, `\w+\d+` | O(n^2) or O(n^3) split points |
| Repeated optional groups | `(a?){n}a{n}` | the classic textbook blow-up |
| Unanchored search with a slow suffix | `re.search(r"\s+$", s)` on long whitespace without a final match | O(n^2) over start positions |

Measured on this stack (Python 3.13, Apple silicon): `re.match(r"(a+)+$", "a"*24 + "!")` takes 0.47 s
and `"a"*26 + "!"` 1.9 s: each extra character doubles the time.

| Fix | Example |
|---|---|
| Make alternatives mutually exclusive | `(?:[^"\\]\|\\.)*` instead of `(?:.\|\\.)*` |
| Unroll the loop | `"[^"\\]*(?:\\.[^"\\]*)*"` for quoted strings with escapes |
| Atomic group / possessive quantifier (not JS, not .NET possessive) | `(?>a+)+$`, `a++` |
| Linear engine | RE2 (`google-re2` for Python, `re2` for Node, `re2j` for Java), Go, Rust, .NET `NonBacktracking` |
| Cap input length, add a timeout | `len(s) <= 4096`; `regex.match(p, s, timeout=0.1)`; .NET `TimeSpan` |

Detection: `regexploit-py src/` (Python AST scan; also `regexploit-js`, stdin `regexploit`),
`recheck` (npm; `checkSync(source, flags)` returns `status: "vulnerable"` with `complexity.type` and an
attack string), `eslint-plugin-regexp` rules `regexp/no-super-linear-backtracking` (in
`flat/recommended`) and `regexp/no-super-linear-move`, `safe-regex` (star-height heuristic only).
Then a timing test: each pattern on 50 KB adversarial inputs (long runs of the repeated char followed
by a non-matching char) must finish under 100 ms. Never compile user-supplied patterns on a backtracking
engine; use RE2 with a size limit, or `re.escape` the input and search for it literally.

## 7. Multi-file search and replace

```bash
rg -n 'getUser\(' src/                       # preview: every hit with line numbers
rg -n -P '(?<=\buser_)id\b' src/             # PCRE2 when you need lookaround
rg -l -0 'getUser\(' src/ | xargs -0 perl -pi -e 's/\bgetUser\(/fetchUser(/g'
sd -p 'getUser\(' 'fetchUser(' $(rg -l 'getUser\(' src/)   # sd preview; drop -p to apply
git diff --stat && git diff                   # review, then run tests
```

| Tool | In-place flag | Group in replacement | Notes |
|---|---|---|---|
| GNU sed | `-i` | `\1` | `-E` for ERE; `-z` for NUL-separated |
| BSD/macOS sed | `-i ''` | `\1` | no `\+` in BRE; use `-E` |
| perl | `-pi -e` (`-0777` for whole-file) | `$1`, `$+{name}` | PCRE-like syntax, portable across OSes |
| sd | default (`-p` preview) | `$1`, `${name}` | Rust `regex` syntax; `-F` literal |
| rg | none (`--replace` only prints) | `$1`, `${name}` | use for preview and file lists |
| Python `re.sub` | n/a | `\1`, `\g<name>` | function replacer for computed values |
| JS `replace` | n/a | `$1`, `$<name>` | `$` in replacement is special: use a function |
| Go `ReplaceAllString` | n/a | `${1}`, `${name}` | `$1x` means group `1x`: always brace |

Escape literal input before embedding it: `re.escape`, `RegExp.escape` (ES2025), `regexp.QuoteMeta`,
`regex::escape`, `Pattern.quote`, `Regex.Escape`; escape replacement strings too
(`Matcher.quoteReplacement`, a function replacer in JS). Changes that depend on syntax (rename a method
but not a same-named local, move an import) go to `codemod-automation`, not regex.

## 8. Testing regexes

- Table-driven unit tests assert both the match decision and every captured group; a regex test that
  only checks "matches" misses wrong captures.
- Property test against a reference: generate valid inputs, render them, parse with the regex, compare
  (`hypothesis.strategies.from_regex(LOG_LINE, fullmatch=True)` generates matching strings; check the
  regex agrees with the real parser on them).
- Fuzz for time: random and adversarial inputs up to the length cap, assert the time budget per call.
- One shared table file (JSON) when the same pattern exists in two languages; both suites read it.
- Placement of these tests in the suite and coverage reasoning: `testing-strategy`.

## 9. Readability in review

- A comment states the intent ("ISO-8601 UTC timestamp, millisecond precision optional").
- Numeric ranges, dates, checksums: match the shape, then parse and compare in code.
- Flag any regex compiled on a hot path (inside a request handler or loop) without a module constant.
- Flag `.*` between two delimiters; ask for a negated class.
- Compose long patterns from named fragments and keep each fragment testable (in JS, join
  `String.raw` pieces into `new RegExp(...)`):

```python
DATE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
TIME = r"[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?"
TS = rf"{DATE}T{TIME}(?:Z|[+-][0-9]{{2}}:[0-9]{{2}})"   # in rf-strings, {2} must be {{2}}
```

## 10. Regex set operations

Use when several patterns route or classify the same input (URL routers, WAF rules, log classifiers):
does a later rule ever fire, do two rules overlap, are two refactored patterns equivalent?

```python
import interegular                 # pip install interegular
from greenery import parse         # pip install greenery
list(interegular.compare_regexes(r"/users/[a-z]+", r"/users/admin", r"/orders/\d+"))
# -> [('/users/[a-z]+', '/users/admin')]   the admin route is shadowed by the generic one
interegular.Comparator.from_regexes({"a": r"/users/[a-z]+", "b": r"/users/admin"}).get_example_overlap("a", "b")
(parse(r"/users/[a-z]+") & parse(r"/users/admin")).empty()   # False: they intersect
parse("a|b").equivalent(parse("[ab]"))                         # True: safe refactor
```

- Rust: `regex-automata` builds the DFA explicitly (`dfa::dense::DFA::new(p)`, features `dfa-build` +
  `syntax`) and reports its size (`memory_usage()`, bytes) before you ship a large pattern set;
  `regex::RegexSet` matches many patterns in one pass.
- Blow-up sources: counted repetition (`a{1000}` is 1,000 NFA states; Go rejects counts over 1000 and
  nested products like `(a{100}){100}`), and "n-th symbol from the end" families
  (`(a|b)*a(a|b){n}`) whose DFA needs 2^n states. Linear engines then fall back to slower NFA
  simulation or hit size limits (`RegexBuilder::size_limit` in Rust).

## 11. Pitfalls

- Greedy `.*` crossing delimiters: `<.*>` matches from the first `<` to the last `>` on the line.
- Unescaped dots: `api.example.com` also matches `apixexample.com`; escape (`api\.example\.com`) or
  compare hostnames exactly.
- `[A-z]` includes `[ \ ] ^ _` and the backtick; write `[A-Za-z]`.
- Forgetting the global flag (JS `replace` without `g` replaces only the first match; `replaceAll`
  requires `g` for a regex) or the multiline flag for per-line anchors.
- Locale-dependent `\w` and case folding (section 5); `re.LOCALE` only works with bytes patterns.
- Regex HTML scraping that breaks when attribute order, quoting or whitespace changes.
- A JS regex with `g` or `y` used with `test()` keeps `lastIndex` between calls: alternating results.
- Pattern built from user input without escaping: wrong matches at best, ReDoS at worst.

## 12. Worked example: log-line parser, Python then Go/RE2

Format: `ts level [req=ID] msg`, request tag optional, e.g.
`2026-10-19T08:15:02.123Z INFO [req=7f3a9c] user login ok`. The 12-row table (stored as
`cases.json`, read by both test suites):

| # | Line | Expected |
|---|---|---|
| 1 | `2026-10-19T08:15:02.123Z INFO [req=7f3a9c] user login ok` | req `7f3a9c`, msg `user login ok` |
| 2 | `2026-10-19T08:15:02Z WARN disk 91% full` | req none |
| 3 | `2026-10-19T08:15:02.123456+02:00 ERROR [req=a-1] upstream 503` | offset timestamp |
| 4 | `2026-10-19T08:15:02Z INFO [cache] warmed in 3 ms` | req none, msg starts with `[cache]` |
| 5 | `2026-10-19T08:15:02Z DEBUG [req=abc] [req=def] echoed` | req `abc`, msg `[req=def] echoed` |
| 6 | `... INFO [req=] boot` | no match (malformed tag must not leak into msg) |
| 7 | `... INFO [req=abc]` | no match (tag without message) |
| 8 | `... info lowercase level` | no match |
| 9 | `... NOTICE unknown level` | no match |
| 10 | `INFO no timestamp` | no match |
| 11 | `... INFO trailing newline\n` | no match |
| 12 | `٢٠٢٦-10-19T08:15:02Z INFO arabic-indic year` | no match (`\d` would accept it) |

Python (verbose, named groups, ASCII digits, full-match):

```python
LOG_LINE = re.compile(r"""
    (?P<ts>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}
           (?:\.[0-9]{1,9})? (?:Z|[+-][0-9]{2}:[0-9]{2}))
    \x20(?P<level>TRACE|DEBUG|INFO|WARN|ERROR|FATAL)
    \x20(?: \[req=(?P<req>[A-Za-z0-9-]{1,64})\]\x20   # a valid request tag
          | (?!\[req=) )                              # or no tag at all
    (?P<msg>\S.*)
    """, re.VERBOSE)

def parse(line: str) -> dict | None:
    m = LOG_LINE.fullmatch(line)
    return m.groupdict() if m else None
```

Checks run: `pytest` on the table (12/12 pass); ReDoS: `regexploit-py .` reports nothing, and five
50 KB adversarial inputs (`"[req=" * 10000`, 50,000 fraction digits, 50,000 spaces, 50,000 zeros,
50,000 newlines) each parse in under 0.01 ms, far inside the 100 ms budget.

Go port: RE2 rejects `(?!` ("invalid or unsupported Perl syntax"). Restructure the lookahead into an
extra branch of the optional group that captures the forbidden prefix, then reject when it
participated. Go's leftmost-first submatch semantics prefer the valid-tag branch, then the `badtag`
branch, then skipping the group, exactly like a backtracking engine would.

```go
var logLine = regexp.MustCompile(`^` +
	`(?P<ts>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}` +
	`(?:\.[0-9]{1,9})?(?:Z|[+-][0-9]{2}:[0-9]{2}))` +
	` (?P<level>TRACE|DEBUG|INFO|WARN|ERROR|FATAL)` +
	` (?:\[req=(?P<req>[A-Za-z0-9-]{1,64})\] |(?P<badtag>\[req=))?` +
	`(?P<msg>\S.*)$`)

func Parse(line string) *Entry {
	loc := logLine.FindStringSubmatchIndex(line)
	if loc == nil || loc[2*logLine.SubexpIndex("badtag")] >= 0 {
		return nil // no match, or a malformed [req=...] tag
	}
	// ... build Entry from the ts, level, req, msg indices
}
```

`go test` on the same `cases.json`: 12/12 pass, linear-time test passes. Note row 11: Go's `$` matches
only at the end of text, Python needed `fullmatch` for the same result. Full code and both test files:
[log-parser example](references/log-parser-example.md).

Related: `zero-downtime-migrations`, `resilience-patterns`, `dependency-upgrades`,
`docs-and-adr-writing`, `codemod-automation`, `cs-foundations`, `security-review`, `testing-strategy`,
hub `coding-general`.
