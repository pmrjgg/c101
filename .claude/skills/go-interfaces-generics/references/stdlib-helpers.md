# Standard library helpers for generic and iterator code

Check the version column against the go.mod `go` line: since 1.27 `go test` runs the vet
`stdversion` check, which reports standard library symbols newer than the file's Go version.

## slices

| Function | Since | Notes |
|---|---|---|
| `Sort`, `SortFunc`, `SortStableFunc`, `IsSorted(Func)` | 1.21 | `SortFunc` is not stable; comparator returns <0, 0, >0 |
| `BinarySearch`, `BinarySearchFunc` | 1.21 | input sorted ascending by the same order; returns `(index, found)` |
| `Index(Func)`, `Contains(Func)` | 1.21 | linear |
| `Insert`, `Delete`, `DeleteFunc`, `Replace` | 1.21 | shrinking functions zero the vacated tail (1.22); use the returned slice |
| `Compact`, `CompactFunc` | 1.21 | adjacent duplicates only: sort first for global dedupe |
| `Clone`, `Clip`, `Grow` | 1.21 | `Grow(s, n)` guarantees room for n more appends |
| `Equal(Func)`, `Compare(Func)` | 1.21 | element-wise |
| `Max(Func)`, `Min(Func)` | 1.21 | panic on an empty slice |
| `Reverse` | 1.21 | in place |
| `Concat` | 1.22 | nil when the result is empty |
| `All`, `Values`, `Backward` | 1.23 | iterators over a slice |
| `Collect`, `AppendSeq`, `Sorted`, `SortedFunc`, `SortedStableFunc` | 1.23 | consume an `iter.Seq` |
| `Chunk` | 1.23 | panics if n < 1; chunks alias the input, capacity clipped |
| `Repeat` | 1.23 | never nil |

## maps

| Function | Since | Notes |
|---|---|---|
| `Clone`, `Copy`, `DeleteFunc`, `Equal`, `EqualFunc` | 1.21 | `Copy(dst, src)` overwrites existing keys |
| `All`, `Keys`, `Values` | 1.23 | iterators in unspecified order: `slices.Sorted(maps.Keys(m))` for determinism |
| `Collect`, `Insert` | 1.23 | build or extend a map from an `iter.Seq2` |

## cmp, builtins, sync

| Symbol | Since | Notes |
|---|---|---|
| `cmp.Compare`, `cmp.Less`, `cmp.Ordered` | 1.21 | NaN sorts before every other value; -0.0 equals 0.0 |
| `cmp.Or(vals...)` | 1.22 | first non-zero argument: defaults and multi-key comparators |
| `min`, `max`, `clear` | 1.21 | builtins; `clear(m)` empties a map, `clear(s)` zeroes a slice |
| `sync.OnceFunc`, `sync.OnceValue`, `sync.OnceValues` | 1.21 | lazy init; a panic in f re-panics on every call |

## strings and bytes

| Function | Since | Notes |
|---|---|---|
| `Cut` | 1.18 | `before, after, found := strings.Cut(s, "=")` |
| `CutPrefix`, `CutSuffix` | 1.20 | replace `HasPrefix` + `TrimPrefix` pairs |
| `Lines`, `SplitSeq`, `SplitAfterSeq`, `FieldsSeq`, `FieldsFuncSeq` | 1.24 | iterators; no intermediate slice; `Lines` keeps `\n` |
| `CutLast` | 1.27 | split around the last separator |

## iter, reflect, hashing

| Symbol | Since | Notes |
|---|---|---|
| `iter.Seq`, `iter.Seq2`, `iter.Pull`, `iter.Pull2` | 1.23 | `Pull` returns `next`, `stop`; always `defer stop()` |
| `reflect.Type.Fields`, `Methods`, `Ins`, `Outs`; `reflect.Value.Fields`, `Methods` | 1.26 | iterator forms of the index loops |
| `hash/maphash.Hasher`, `ComparableHasher` | 1.27 | contract for user-defined hash-based containers |
| `(*rand.Rand).N` (math/rand/v2) | 1.27 | generic method mirroring the top-level `rand.N` |

## unique (1.23): interning

```go
type Point struct{ region, zone unique.Handle[string] }
p := Point{region: unique.Make("eu-west-1"), zone: unique.Make("eu-west-1a")}
same := p.region == unique.Make("eu-west-1")   // true; compares handles, not string bytes
name := p.region.Value()                      // "eu-west-1" (shallow copy)
```

Use for high-cardinality repeated keys (labels, hostnames) parsed from input: one copy in memory,
O(1) equality. `Make` is safe for concurrent use.

## weak (1.24) and runtime.AddCleanup (1.24): caches that do not pin values

```go
type WeakCache[K comparable, V any] struct {
    mu sync.Mutex
    m  map[K]weak.Pointer[V]
}

func (c *WeakCache[K, V]) Get(k K) *V {
    c.mu.Lock(); defer c.mu.Unlock()
    if wp, ok := c.m[k]; ok {
        if v := wp.Value(); v != nil { return v }   // nil once the value became unreachable
        delete(c.m, k)
    }
    return nil
}

func (c *WeakCache[K, V]) Put(k K, v *V) {
    c.mu.Lock()
    c.m[k] = weak.Make(v)
    c.mu.Unlock()
    runtime.AddCleanup(v, func(k K) {               // arg must not be v itself, or v never dies
        c.mu.Lock(); defer c.mu.Unlock()
        if wp, ok := c.m[k]; ok && wp.Value() == nil { delete(c.m, k) }
    }, k)
}
```

Caveats from the `weak` docs: `Value` may return nil as soon as the object is unreachable but is
not guaranteed to ever do so; tiny pointer-free objects (about 16 bytes or less) may be batched
with live objects and never be reclaimed; two weak pointers compare equal only if made from the
same pointer. Prefer `AddCleanup` over `runtime.SetFinalizer` in new code.
