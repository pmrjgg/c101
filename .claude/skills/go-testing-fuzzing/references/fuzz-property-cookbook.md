# Fuzz and property cookbook

Native fuzzing finds inputs that crash or violate a property; `pgregory.net/rapid` generates
structured values and operation sequences and shrinks failures to a minimal case. Use both: fuzz
parsers and decoders on raw bytes, use rapid for APIs whose inputs are typed values or call sequences.

| Input shape | Tool |
|---|---|
| bytes or strings from the outside world (parsers, decoders, protocol frames) | native fuzzing |
| typed values with constraints (ranges, sorted slices, valid structs) | `rapid.Check` |
| sequences of operations against a model (caches, queues, state machines) | `rapid` state machine |
| the same rapid property, explored with coverage guidance | `f.Fuzz(rapid.MakeFuzz(prop))` |
| a few known edge cases | table test (section 1 of the skill), then seed both tools with them |

## 1. Property catalogue

Differential against a trusted reference:

```go
func FuzzParseInt(f *testing.F) {
    for _, s := range []string{"0", "-1", "9223372036854775807", "-9223372036854775808", "0x10", "+5", ""} {
        f.Add(s)
    }
    f.Fuzz(func(t *testing.T, s string) {
        got, gotErr := ParseInt(s)                          // ours
        want, wantErr := strconv.ParseInt(s, 10, 64)        // reference
        if (gotErr == nil) != (wantErr == nil) {
            t.Fatalf("ParseInt(%q) err = %v, strconv err = %v", s, gotErr, wantErr)
        }
        if gotErr == nil && got != want {
            t.Fatalf("ParseInt(%q) = %d, strconv = %d", s, got, want)
        }
    })
}
```

Idempotence and invariants:

```go
func FuzzNormalizePath(f *testing.F) {
    f.Add("a//b/../c/")
    f.Fuzz(func(t *testing.T, p string) {
        once := NormalizePath(p)
        if twice := NormalizePath(once); twice != once {
            t.Fatalf("NormalizePath not idempotent: %q -> %q -> %q", p, once, twice)
        }
        if strings.Contains(once, "//") { t.Fatalf("NormalizePath(%q) = %q contains //", p, once) }
    })
}
```

Multiple arguments: every `f.Add` must pass exactly the types of the `f.Fuzz` parameters after
`*testing.T`, in order (`f.Add("abc", 3)` pairs with `func(t *testing.T, s string, n int)`; an untyped
constant `3` is an `int`, so use `uint8(3)` for a `uint8` parameter).

Bounding work: return early or `t.Skip()` on inputs above a size limit so a worker never spends
seconds on one input; quadratic algorithms otherwise dominate the fuzzing budget.

## 2. Seeds and corpus files

- Seed from the table test so every known edge case starts the search:
  `for _, tc := range parseTests { f.Add(tc.in) }` (share the table at package level).
- Corpus files live in `testdata/fuzz/<FuzzName>/<name>`; each is `go test fuzz v1` followed by one
  Go literal per argument:

```
go test fuzz v1
string("0x")
int(3)
```

- After fixing a crasher, keep its file (it runs in every plain `go test`) and add a named table case
  describing the bug so the intent survives corpus cleanups.
- The generated corpus under `$(go env GOCACHE)/fuzz/` is local state: cache that directory
  in CI between nightly runs; `go clean -fuzzcache` deletes it.

## 3. CI fuzz loop

```bash
#!/usr/bin/env bash
# Fuzz every FuzzXxx in the module for FUZZTIME each; keep going, fail at the end if any target failed.
set -uo pipefail
FUZZTIME=${FUZZTIME:-5m}
status=0
for pkg in $(go list ./...); do
  for target in $(go test -list='^Fuzz' "$pkg" | grep '^Fuzz' || true); do
    echo "== $pkg $target"
    go test -run='^$' -fuzz="^${target}\$" -fuzztime="$FUZZTIME" -parallel="${FUZZ_PARALLEL:-4}" "$pkg" || status=1
  done
done
git status --porcelain -- '*testdata/fuzz/*'   # new crasher files to upload as artifacts
exit $status
```

Budget: PRs run seeds only (plain `go test`); nightly 5-10 minutes per target; a dedicated long run
(hours) before releases of parsers that face untrusted input. Limit `-parallel` on shared runners:
each worker is a separate process.

## 4. rapid properties

```go
func TestSortMatchesStdlib(t *testing.T) {
    rapid.Check(t, func(t *rapid.T) {
        s := rapid.SliceOf(rapid.Int()).Draw(t, "s")
        got := MySort(slices.Clone(s))
        want := slices.Clone(s)
        slices.Sort(want)
        if !slices.Equal(got, want) { t.Fatalf("MySort(%v) = %v, want %v", s, got, want) }
    })
}

func FuzzSortMatchesStdlib(f *testing.F) {                 // same property, coverage-guided
    f.Fuzz(rapid.MakeFuzz(func(t *rapid.T) {
        s := rapid.SliceOf(rapid.Int()).Draw(t, "s")
        if got := MySort(slices.Clone(s)); !slices.IsSorted(got) { t.Fatalf("MySort(%v) = %v", s, got) }
    }))
}
```

| Need | Generator (v1.3 API) |
|---|---|
| integers | `rapid.Int()`, `rapid.IntRange(min, max)`, `rapid.Int64Range`, `rapid.Uint8()`, `rapid.IntMin(n)` |
| floats | `rapid.Float64()`, `rapid.Float64Range(min, max)` |
| strings | `rapid.String()`, `rapid.StringN(minRunes, maxRunes, maxLen)`, `rapid.StringMatching("[a-z]{1,8}")`, `rapid.StringOf(rapid.RuneFrom([]rune("abc")))` |
| bytes | `rapid.SliceOf(rapid.Byte())`, `rapid.SliceOfBytesMatching(expr)` |
| slices, maps | `rapid.SliceOf(g)`, `rapid.SliceOfN(g, min, max)`, `rapid.SliceOfDistinct(g, keyFn)`, `rapid.MapOf(k, v)`, `rapid.MapOfN(k, v, min, max)` |
| choices | `rapid.SampledFrom(xs)`, `rapid.OneOf(g1, g2)`, `rapid.Just(v)`, `rapid.Permutation(xs)`, `rapid.Bool()` |
| pointers | `rapid.Ptr(g, allowNil)` |
| derived values | `rapid.Map(g, fn)`, `rapid.Custom(func(t *rapid.T) V { ... })`, `g.Filter(pred)` (only for rare rejections) |
| whole struct types | `rapid.Make[T]()` |
| recursive structures | `rapid.Deferred(func() *rapid.Generator[V] { ... })` |

Draw labels appear in the failure report: label every draw. Prefer constructing valid values
(`Custom`, `Map`) over filtering; heavy `Filter` use makes rapid give up.

State machines: exported methods with signature `func(*rapid.T)` (or `func(rapid.TB)`) become actions,
`Check(*rapid.T)` is the invariant run before the first and after every action, and
`t.Repeat(rapid.StateMachineActions(m))` drives them (about 30 actions per sequence by default). An
action that cannot run in the current state calls `t.Skip` before drawing; after 100 consecutive
skipped actions rapid stops with "can't find a valid (non-skipped) action". The full queue example is
section 10 of the skill. rapid v1.3 also has `rapid.SyncTest(t, prop)` for properties over
time-dependent code; read its doc for the bubble rules before using it.

## 5. rapid flags

Every flag has a `RAPID_` environment variable twin (`RAPID_CHECKS=10000`).

| Flag | Default | Use |
|---|---|---|
| `-rapid.checks` | 100 | test cases per property; 10_000 for a deep local run |
| `-rapid.steps` | 30 | average actions per `Repeat` sequence |
| `-rapid.seed` | 0 (random) | replay a printed seed |
| `-rapid.failfile` | "" | replay a specific fail file |
| `-rapid.nofailfile` | false | do not write fail files (read-only CI checkouts) |
| `-rapid.shrinktime` | 30s | cap on minimization time |
| `-rapid.v` / `-rapid.debug` | false | verbose and debugging output |

Fail files are written to `testdata/rapid/<TestName>/<TestName>-<timestamp>-<pid>.fail` and every
matching file is replayed automatically on the next run; commit them with the fix.
