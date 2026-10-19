---
name: go-interfaces-generics
description: "Go API design: small consumer-side interfaces, accept interfaces and return structs, embedding, functional options, closed variants, generics with constraints and type sets, range-over-func iterators (iter.Seq, iter.Pull), and the slices, maps, cmp, unique and weak packages. Load when designing Go packages, adding generics or iterators, or reviewing the shape of a Go API."
when_to_use: "Designing or reviewing exported Go types, interfaces, constructors and package layout; errors like 'does not implement (missing method ...)', 'cannot use generic type without instantiation', 'does not satisfy comparable'; adding type parameters; writing iter.Seq/Seq2 iterators or hitting 'range function continued iteration after function for loop body returned false'; replacing helpers with slices/maps/cmp; mocks with dozens of methods."
---

# Go interfaces, composition and generics

Baseline Go 1.26/1.27; features follow the `go` line in go.mod. Version map: generics 1.18;
interfaces satisfy `comparable` 1.20; `slices`, `maps`, `cmp`, `min`/`max`/`clear` 1.21; `cmp.Or`,
`slices.Concat` 1.22; range-over-func, `iter`, `unique`, `slices.Chunk` 1.23; generic type aliases,
`weak`, `strings.Lines`/`SplitSeq`/`FieldsSeq` 1.24; a generic type may reference itself in its
type parameter list 1.26; generic methods and `strings.CutLast` 1.27.

Deep material: [iterator cookbook](references/iterator-cookbook.md) (adapters, zip/merge,
error-carrying sequences, single-use iterators) | [standard helpers](references/stdlib-helpers.md)
(slices/maps/strings/cmp catalogue, unique and weak recipes)

## 1. Interface rules

| Rule | Shape | Why |
|---|---|---|
| define the interface where it is consumed, with only the methods that consumer calls | `package billing` declares `type invoiceGetter interface{ Invoice(ctx context.Context, id string) (*Invoice, error) }` | the consumer states its needs; the producer can grow freely |
| one or two methods | `io.Reader`, `fmt.Stringer`, `http.Handler` | small interfaces compose (`io.ReadWriter`) and are trivial to fake |
| accept interfaces, return concrete `*T` | `func NewServer(st invoiceGetter) *Server` | callers see the full method set; adding a method to `*T` breaks nobody |
| compile-time conformance check | `var _ http.Handler = (*Server)(nil)` | the build fails where the type is defined, not at a distant wiring site |
| never export an interface only for mocking | tests declare their own small interface, or fake the concrete dependency | big exported interfaces leak implementation shape and break every fake on each new method |
| return an interface only when hiding the implementation is the point | `sha256.New() hash.Hash`, `error` | several implementations behind one constructor |

Adding a method to an exported interface breaks every implementer outside the package. An
unexported method in an exported interface seals it: other packages can satisfy it only by
embedding an existing implementation.

## 2. Composition

- Embedding promotes fields and methods; it is not inheritance. A promoted method runs with the
  inner value as receiver and never calls back into the outer type's "overrides".
- Embedding an exported `sync.Mutex` in an exported struct exports `Lock`/`Unlock`: use a named
  unexported field `mu sync.Mutex`.
- Embedding an interface in a struct promotes every method; any method the struct does not define
  panics with a nil dereference when the embedded value is nil:

```go
type auditedStore struct {
    Store                       // embedded interface: all methods promoted
    log *slog.Logger
}
func (s auditedStore) Delete(ctx context.Context, id int64) error {
    s.log.InfoContext(ctx, "delete", "id", id)
    return s.Store.Delete(ctx, id)
}
// auditedStore{log: l}.Get(ctx, 1)  -> panic: invalid memory address or nil pointer dereference
```

  Construct such decorators only through a function that rejects a nil inner value. In tests the
  same trick gives intentionally partial fakes that panic loudly on unexpected calls.
- Make zero values useful (`sync.Mutex`, `bytes.Buffer`, `strings.Builder`): design `T{}` to work,
  lazily initialising maps inside methods. When unexported fields need setup (maps, channels,
  goroutines, validated config), provide `New...(...) (*T, error)` and say in the doc comment that
  the zero value is not usable.

## 3. Shape table

| Need | Go shape | Example |
|---|---|---|
| polymorphism over behaviour | small interface | `Notifier.Notify(ctx, msg) error` |
| polymorphism over data shape | generics | `Set[T comparable]`, `slices.SortFunc` |
| closed set of variants | interface with an unexported marker method + type switch; lint `gochecksumtype` | AST nodes, domain events |
| enum of constants | `type Level int` + `const` block + `String()` (`stringer`); lint `exhaustive` | log levels, states |
| few, evolving options with defaults | functional options | `NewClient(addr, WithTimeout(2*time.Second))` |
| many options, loaded from files or flags | config struct + `DefaultConfig()` | `Config{Timeout: 2*time.Second}` |
| third-party extension points | interface + registry filled by `Register` from `init` | `database/sql.Register`, `image.RegisterFormat` |

```go
//sumtype:decl
type Event interface{ isEvent() }          // sealed: only this package can add variants
type Created struct{ ID string }
type Deleted struct{ ID, Reason string }
func (Created) isEvent() {}
func (Deleted) isEvent() {}

func apply(e Event) error {
    switch e := e.(type) {                 // gochecksumtype reports missing variants
    case Created: return create(e.ID)
    case Deleted: return remove(e.ID, e.Reason)
    }
    return fmt.Errorf("unknown event %T", e)
}
```

gochecksumtype treats a `default` clause as exhaustive unless `default-signifies-exhaustive: false`.

```go
type Option func(*config)
type config struct{ timeout time.Duration; retries int; logger *slog.Logger }

func WithTimeout(d time.Duration) Option { return func(c *config) { c.timeout = d } }
func WithRetries(n int) Option         { return func(c *config) { c.retries = n } }

func NewClient(addr string, opts ...Option) (*Client, error) {
    cfg := config{timeout: 5 * time.Second, retries: 3, logger: slog.Default()} // defaults live here
    for _, o := range opts { o(&cfg) }
    if cfg.timeout <= 0 { return nil, fmt.Errorf("client: timeout must be > 0, got %v", cfg.timeout) }
    return &Client{addr: addr, cfg: cfg}, nil
}
```

Choose one style per knob. Registries: the registering package panics on duplicate names, guards
the map with a mutex, and the main package chooses implementations by blank import. Prefer
explicit wiring in `main` when no third party needs to plug in.

## 4. Generics

| Use type parameters for | Use an interface or plain code for |
|---|---|
| containers: sets, caches, LRU, heaps, ordered maps | behaviour that differs per type (`Write`, `Notify`) |
| algorithms identical for every element type (map/filter/group over slices, maps, channels) | a single instantiation in the whole program |
| type-safe wrappers that remove `any` and assertions (`atomic.Pointer[T]`, pool or result wrappers) | a parameter used once: `f(r io.Reader)` beats `f[R io.Reader](r R)` |

| Constraint | Permits | Note |
|---|---|---|
| `any` | assignment, passing, conversion to `any` | no `==` unless also `comparable` |
| `comparable` | `==`, `!=`, map keys | since 1.20 interface types satisfy it: `Set[any]` compiles, then panics at runtime with `hash of unhashable type []int` |
| `cmp.Ordered` | `<`, `<=`, `>`, `>=` on integers, floats, strings and named types of them | floats: `cmp.Compare`/`cmp.Less` order NaN first; `<` does not |
| `~int64 \| ~string` union | the operators common to all terms | `~` admits named types such as `type UserID int64` |
| `S ~[]E, E any` | any slice type | keeps named slice types: `func Map[S ~[]E, E, R any](s S, f func(E) R) []R` |

- Interfaces with type terms are constraints only; they cannot be variable or field types.
- Methods with their own type parameters exist from 1.27 (file version `go 1.27`+):
  `func (c *Cache[K, V]) Map[R any](f func(V) R) map[K]R`. Interface methods cannot declare type
  parameters and a generic method never satisfies an interface method. Before 1.27 write a
  top-level function: `func MapValues[K comparable, V, R any](c *Cache[K, V], f func(V) R) map[K]R`.
- Generic type aliases (1.24): `type Set[T comparable] = map[T]struct{}`; re-export across
  packages during moves with `type Cache[K comparable, V any] = cache.Cache[K, V]`.
- Self-reference (1.26): `type Adder[A Adder[A]] interface{ Add(A) A }`.
- Explicit instantiation when no argument mentions a parameter: `cache.New[string, *User](time.Minute)`.
- Zero value of a type parameter: `var zero V; return zero, false`.
- A type switch on a type parameter (`switch any(v).(type)`) means generics were the wrong tool.
- Implementation: the compiler stencils one copy per GC shape (all pointer types share one) and
  passes a dictionary; calls to methods of a type parameter are indirect and may block inlining.
  Benchmark generic hot paths against a concrete version before claiming speed.
- Over-generic smells: a `Repository[T]` with CRUD for every entity, type parameters constrained
  only by `any` and used once, a constraint with methods where an interface parameter suffices.

## 5. Iterators

```go
// All yields the tree's entries in key order and stops as soon as the loop body breaks.
func (t *Tree[K, V]) All() iter.Seq2[K, V] {
    return func(yield func(K, V) bool) { t.walk(t.root, yield) }
}
func (t *Tree[K, V]) walk(n *node[K, V], yield func(K, V) bool) bool {
    if n == nil { return true }
    return t.walk(n.left, yield) && yield(n.key, n.val) && t.walk(n.right, yield)
}

// Filter is a composable adapter; Map, Take, Enumerate and Zip are in the cookbook.
func Filter[V any](seq iter.Seq[V], keep func(V) bool) iter.Seq[V] {
    return func(yield func(V) bool) {
        for v := range seq {
            if keep(v) && !yield(v) { return }
        }
    }
}
```

Rules:
- When `yield` returns false, return at once and never call it again; another call panics with
  `range function continued iteration after function for loop body returned false`.
- `defer` in the iterator function runs when the loop ends, breaks or panics: iterators may own
  resources (rows, files) and close them.
- Never hold a lock while calling `yield`: the loop body may call back into the type and deadlock
  (non-reentrant mutex). Snapshot under the lock, yield after unlocking.
- Single-use iterators (over a reader or a DB cursor) must say so in the doc comment.
- Errors: `iter.Seq2[T, error]` that stops after yielding the first error, or an `Err()` method
  checked after the loop (the `bufio.Scanner` convention).
- Naming: `All` for every element, `Keys`, `Values`, `Backward`, or the sequence's noun (`Users`).

`iter.Pull` turns a push sequence into `next`/`stop` for interleaving two sequences (zip, merge);
always `defer stop()`, and never call `next` or `stop` from two goroutines at once:

```go
func Zip[A, B any](as iter.Seq[A], bs iter.Seq[B]) iter.Seq2[A, B] {
    return func(yield func(A, B) bool) {
        nextA, stopA := iter.Pull(as)
        defer stopA()
        nextB, stopB := iter.Pull(bs)
        defer stopB()
        for {
            a, okA := nextA()
            b, okB := nextB()
            if !okA || !okB || !yield(a, b) { return }
        }
    }
}
```

| Want | Standard call (1.23+ unless noted) |
|---|---|
| Seq into a new slice | `slices.Collect(seq)` (nil when empty) |
| sorted slice from a Seq | `slices.Sorted(seq)`, `slices.SortedFunc(seq, cmpFn)` |
| sorted map keys | `slices.Sorted(maps.Keys(m))` |
| iterate a slice | `slices.Values(s)`, `slices.All(s)` (index, value), `slices.Backward(s)` |
| Seq2 into a map | `maps.Collect(seq2)`; into an existing map `maps.Insert(m, seq2)` |
| append into a preallocated slice | `slices.AppendSeq(make([]T, 0, n), seq)` |
| fixed-size chunks | `slices.Chunk(s, n)`: panics if n < 1; chunks share elements, capacity clipped |
| lazy string splitting (1.24) | `strings.SplitSeq(s, ",")`, `strings.FieldsSeq(s)`, `strings.Lines(s)` (lines keep their `\n`) |

Performance: simple iterators and loop bodies can be inlined into a plain loop; otherwise every
element costs an indirect call, so the hottest slice loops stay `for i, v := range s` until a
benchmark says otherwise. `iter.Pull` switches coroutines on every `next`: far cheaper than a
goroutine and channel, still costlier than push iteration. Return `iter.Seq` when callers stream;
return a slice when they need `len` or random access.

## 6. Standard helpers

| Task | Call |
|---|---|
| sort by several keys | `slices.SortFunc(s, func(a, b T) int { return cmp.Or(cmp.Compare(a.Last, b.Last), cmp.Compare(a.ID, b.ID)) })` |
| stable sort | `slices.SortStableFunc` (`SortFunc` is not stable) |
| search a sorted slice | `i, found := slices.BinarySearch(s, x)`; `BinarySearchFunc(s, key, cmpFn)` |
| dedupe | `slices.Sort(s); s = slices.Compact(s)` (`Compact` only removes adjacent duplicates) |
| batch | `for batch := range slices.Chunk(ids, 500) { ... }` |
| first non-zero / default | `port := cmp.Or(os.Getenv("PORT"), "8080")` |
| intern repeated values | `h := unique.Make(s)` (1.23): equal values give equal handles, `==` is a pointer compare, `h.Value()` returns the value |
| caches that must not keep values alive | `weak.Make(p)` / `wp.Value()` (1.24) plus `runtime.AddCleanup` to drop stale keys |
| split once from the right | `strings.CutLast(s, "/")` (1.27); otherwise `strings.LastIndex` |

Shrinking functions (`Delete`, `DeleteFunc`, `Compact`, `CompactFunc`, `Replace`) zero the vacated
tail since 1.22: always use the returned slice. Full catalogue in the standard helpers reference.

## 7. Package layout

- `cmd/<binary>/main.go` stays thin: parse config, wire dependencies, call `run(ctx) error`.
- `internal/` for code no other module may import (enforced by the go command: only the tree
  rooted at `internal`'s parent can import it).
- No `util`, `common`, `helpers`, `models` packages: name packages for what they provide
  (`retry`, `money`, `auth`). Short, lowercase, one word; no stutter (`user.Store`, not `user.UserStore`).
- Doc comments are full sentences starting with the identifier (`// Cache is ...`); package doc in
  `doc.go` (`// Package cache implements ...`); doc links `[Cache.All]`, `[iter.Seq]`.
- Testable examples `func ExampleCache_All()` with `// Output:` (or `// Unordered output:`) are
  compiled and run by `go test`, shown on pkg.go.dev, listed by `go doc -ex` (1.27); vet's `tests`
  analyzer flags examples naming missing identifiers.
- Deprecation: a paragraph `// Deprecated: Use [NewClient] instead.`; staticcheck SA1019 and gopls
  flag callers.

## 8. Nil-interface pitfall

An interface value is nil only when both its type and value are nil. A typed nil pointer stored in
an interface is not nil:

```go
func validate(u User) error {
    var verr *ValidationError
    if u.Email == "" { verr = &ValidationError{Field: "email", Reason: "required"} }
    return verr                 // BUG: (*ValidationError)(nil) wrapped in a non-nil error
}
// fix: if u.Email == "" { return &ValidationError{...} }; return nil
```

Same trap for `var s Store = openStore("")` when `openStore` returns a nil `*pgStore`. Rules:
declare results as the interface type (`error`, `Store`), return a literal `nil`, never return a
concrete error pointer type. staticcheck SA4023 catches some comparisons that can never be nil.

## 9. Worked example: split a 12-method repository, add a generic cache

Before: the producer exports one wide interface and returns it; every fake implements 12 methods
and a 13th method breaks all of them.

```go
// package store
type UserRepository interface {
    Create(ctx context.Context, u *User) error
    Get(ctx context.Context, id int64) (*User, error)
    GetByEmail(ctx context.Context, email string) (*User, error)
    Update(ctx context.Context, u *User) error
    Delete(ctx context.Context, id int64) error
    List(ctx context.Context, f Filter) ([]*User, error)
    Count(ctx context.Context, f Filter) (int, error)
    SetPassword(ctx context.Context, id int64, hash []byte) error
    AddRole(ctx context.Context, id int64, role string) error
    RemoveRole(ctx context.Context, id int64, role string) error
    Roles(ctx context.Context, id int64) ([]string, error)
    Touch(ctx context.Context, id int64, at time.Time) error
}
func NewUserRepository(db *sql.DB) UserRepository { return &pgUsers{db: db} }
```

Step 1, the producer returns its concrete type (methods unchanged):

```go
type Users struct{ db *sql.DB }
func NewUsers(db *sql.DB) *Users { return &Users{db: db} }
```

Step 2, each consumer declares what it calls:

```go
// package auth
type userFinder interface {
    GetByEmail(ctx context.Context, email string) (*store.User, error)
    Touch(ctx context.Context, id int64, at time.Time) error
}
var _ userFinder = (*store.Users)(nil)

// package admin
type userLister interface {
    List(ctx context.Context, f store.Filter) ([]*store.User, error)
    Count(ctx context.Context, f store.Filter) (int, error)
}
```

`main` passes the same `*store.Users` to `auth.NewService` and `admin.NewPanel`; it satisfies both
implicitly. Test fakes now implement 2 methods each.

Step 3, a generic TTL cache with an iterator:

```go
package cache

// Cache is a TTL cache safe for concurrent use. The zero value is not usable; call New.
type Cache[K comparable, V any] struct {
    mu  sync.RWMutex
    m   map[K]entry[V]
    ttl time.Duration
    now func() time.Time
}
type entry[V any] struct { v V; exp time.Time }
type kv[K comparable, V any] struct { k K; v V }

func New[K comparable, V any](ttl time.Duration) *Cache[K, V] {
    return &Cache[K, V]{m: make(map[K]entry[V]), ttl: ttl, now: time.Now}
}
func (c *Cache[K, V]) Set(k K, v V) {
    c.mu.Lock(); defer c.mu.Unlock()
    c.m[k] = entry[V]{v: v, exp: c.now().Add(c.ttl)}
}
func (c *Cache[K, V]) Get(k K) (V, bool) {
    c.mu.RLock(); e, ok := c.m[k]; c.mu.RUnlock()
    if !ok || c.now().After(e.exp) { var zero V; return zero, false }
    return e.v, true
}

// All yields a snapshot of live entries in unspecified order. No lock is held while yielding,
// so the loop body may call Get and Set.
func (c *Cache[K, V]) All() iter.Seq2[K, V] {
    return func(yield func(K, V) bool) {
        now := c.now()
        c.mu.RLock()
        snap := make([]kv[K, V], 0, len(c.m))
        for k, e := range c.m {
            if !now.After(e.exp) { snap = append(snap, kv[K, V]{k, e.v}) }
        }
        c.mu.RUnlock()
        for _, p := range snap {
            if !yield(p.k, p.v) { return }
        }
    }
}
```

Step 4, compose: a decorator in `auth` caches lookups and embeds the interface for `Touch`:

```go
type cachedFinder struct {
    userFinder                                    // Touch passes through
    byEmail *cache.Cache[string, *store.User]
}
func newCachedFinder(f userFinder, ttl time.Duration) cachedFinder {
    if f == nil { panic("auth: nil userFinder") } // the embedded-interface nil trap, closed
    return cachedFinder{userFinder: f, byEmail: cache.New[string, *store.User](ttl)}
}
func (c cachedFinder) GetByEmail(ctx context.Context, email string) (*store.User, error) {
    if u, ok := c.byEmail.Get(email); ok { return u, nil }
    u, err := c.userFinder.GetByEmail(ctx, email)
    if err != nil { return nil, err }
    c.byEmail.Set(email, u)
    return u, nil
}
```

Step 5, document and verify:

```go
func ExampleCache_All() {
    c := cache.New[string, int](time.Minute)
    c.Set("b", 2)
    c.Set("a", 1)
    m := maps.Collect(c.All())
    for _, k := range slices.Sorted(maps.Keys(m)) { fmt.Println(k, m[k]) }
    // Output:
    // a 1
    // b 2
}
```

```bash
go vet ./... && go test -race ./auth ./admin ./cache   # fakes: 2 methods each; example output checked
grep -rn 'UserRepository' --include=*.go . | wc -l     # 0 once every consumer has migrated
```

Result: a 13th method on `*store.Users` breaks no consumer and no fake; the cache is reusable for
any key and value type without `any` assertions.

## 10. Pitfalls

- Interface with one implementation and no consumer that needs substitution: delete it.
- `append` into a sub-slice with spare capacity overwrites the parent: `s[a:b:b]` or `slices.Clone`.
- `maps.Keys` returns `iter.Seq[K]`, not a slice (older `x/exp/maps` versions returned slices).
- `Set[any]` or `comparable` constraints instantiated with interfaces panic on unhashable values.
- Iterators that ignore `yield`'s false, or call `yield` after the loop broke: runtime panic.
- Yielding under a lock: deadlock when the loop body calls back in.
- `slices.SortFunc` comparator returning only -1/1 (never 0) or inconsistent orders: unspecified
  results; build comparators from `cmp.Compare` and `cmp.Or`.
- Exported struct embedding `sync.Mutex` or another type: you export its whole method set forever.
- Returning an interface from a constructor "for testability": callers lose methods and every new
  method becomes a breaking change.
- Generic code calling methods on `T` in a hot loop: indirect calls; measure against concrete code.
- Pre-1.27 code (or go.mod `go` < 1.27) cannot declare method type parameters: use functions.

Related: `go-error-handling`, `go-concurrency-context`, `go-testing-fuzzing`,
`go-modules-tooling`, `go-http-services`, `go-profiling-pprof`, hub `go-craft`.
