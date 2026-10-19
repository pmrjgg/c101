# Go iterator cookbook (Go 1.23+)

Conventions used below: state lives inside the `func(yield ...)` closure so every `range` starts
fresh; each adapter returns as soon as `yield` returns false; `yield` is called from one goroutine
at a time and never after the iterator function returned.

## Adapters

```go
func Map[V, R any](seq iter.Seq[V], f func(V) R) iter.Seq[R] {
    return func(yield func(R) bool) {
        for v := range seq {
            if !yield(f(v)) { return }
        }
    }
}

func Take[V any](seq iter.Seq[V], n int) iter.Seq[V] {
    return func(yield func(V) bool) {
        if n <= 0 { return }
        i := 0                                    // per-range state: inside the closure
        for v := range seq {
            if !yield(v) { return }
            if i++; i == n { return }
        }
    }
}

func Enumerate[V any](seq iter.Seq[V]) iter.Seq2[int, V] {
    return func(yield func(int, V) bool) {
        i := 0
        for v := range seq {
            if !yield(i, v) { return }
            i++
        }
    }
}

func KeysOf[K, V any](seq iter.Seq2[K, V]) iter.Seq[K] {
    return func(yield func(K) bool) {
        for k := range seq {
            if !yield(k) { return }
        }
    }
}

// Batch yields fresh slices of up to n values; callers may retain them.
func Batch[V any](seq iter.Seq[V], n int) iter.Seq[[]V] {
    return func(yield func([]V) bool) {
        buf := make([]V, 0, n)
        for v := range seq {
            if buf = append(buf, v); len(buf) == n {
                if !yield(buf) { return }
                buf = make([]V, 0, n)
            }
        }
        if len(buf) > 0 { yield(buf) }
    }
}
```

For slices already in memory prefer `slices.Chunk(s, n)` (no copies; chunks alias `s`).

## Merge two sorted sequences (iter.Pull)

```go
func MergeSorted[T cmp.Ordered](a, b iter.Seq[T]) iter.Seq[T] {
    return func(yield func(T) bool) {
        na, stopA := iter.Pull(a)
        defer stopA()
        nb, stopB := iter.Pull(b)
        defer stopB()
        va, okA := na()
        vb, okB := nb()
        for okA || okB {
            if !okB || (okA && cmp.Compare(va, vb) <= 0) {
                if !yield(va) { return }
                va, okA = na()
            } else {
                if !yield(vb) { return }
                vb, okB = nb()
            }
        }
    }
}
```

`stop` may be called several times and after `next` reported the end; `defer` it unconditionally.

## Error-carrying sequences

```go
// Users streams users ordered by id. Each range re-runs the query. A failure is yielded last.
func (s *Store) Users(ctx context.Context) iter.Seq2[*User, error] {
    return func(yield func(*User, error) bool) {
        rows, err := s.db.QueryContext(ctx, `SELECT id, email FROM users ORDER BY id`)
        if err != nil { yield(nil, err); return }
        defer rows.Close()                        // runs on normal end, break and panic
        for rows.Next() {
            u := new(User)
            if err := rows.Scan(&u.ID, &u.Email); err != nil { yield(nil, err); return }
            if !yield(u, nil) { return }
        }
        if err := rows.Err(); err != nil { yield(nil, err) }
    }
}

for u, err := range st.Users(ctx) {
    if err != nil { return fmt.Errorf("list users: %w", err) }
    process(u)
}
```

## Single-use iterators

```go
// Lines yields the lines of r without their newline. Single use: r is consumed.
// Call the returned error function after the loop.
func Lines(r io.Reader) (iter.Seq[string], func() error) {
    sc := bufio.NewScanner(r)
    return func(yield func(string) bool) {
        for sc.Scan() {
            if !yield(sc.Text()) { return }
        }
    }, sc.Err
}
```

For in-memory strings use `strings.Lines(s)` (1.24), which keeps the trailing `\n` on each line.

## Paginated APIs

```go
func (c *Client) Repos(ctx context.Context, org string) iter.Seq2[Repo, error] {
    return func(yield func(Repo, error) bool) {
        for page := 1; ; page++ {
            batch, more, err := c.listRepos(ctx, org, page)
            if err != nil { yield(Repo{}, err); return }
            for _, r := range batch {
                if !yield(r, nil) { return }      // breaking stops further page fetches
            }
            if !more { return }
        }
    }
}
```

## Channels and iterators

`for v := range ch` already works for channels. Converting a channel to `iter.Seq` is only useful
to plug it into adapters; the producer still needs ctx-aware sends (see the concurrency skill).
Never start a goroutine inside an iterator to "prefetch" without tying it to the loop's end: a
break would leak it.

## Testing iterators

```go
func TestAllEarlyBreak(t *testing.T) {
    tr := buildTree(1, 2, 3)
    n := 0
    for range tr.All() {                         // panics if All ignores yield's false
        if n++; n == 1 { break }
    }
    if got := slices.Collect(KeysOf(tr.All())); !slices.Equal(got, []int{1, 2, 3}) {
        t.Fatalf("All() keys = %v, want [1 2 3]", got)
    }
    if a, b := slices.Collect(KeysOf(tr.All())), slices.Collect(KeysOf(tr.All())); !slices.Equal(a, b) {
        t.Fatal("All() is not re-iterable")      // documents re-iterability
    }
}
```

Checklist: full iteration, early break, re-iteration (or a documented single-use contract), empty
input, error path for `Seq2[T, error]`, and `-race` when the source is shared.
