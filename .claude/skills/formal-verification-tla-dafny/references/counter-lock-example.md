# Counter worked example: fixed spec, configs, Go port, trace-replay test

Companion to section 12 of the skill. The buggy `Counter.tla` is in section 3 of the skill.

## CounterLock.tla

```tla
---------------------------- MODULE CounterLock ----------------------------
EXTENDS Naturals, FiniteSets
CONSTANTS Procs
VARIABLES counter, pc, tmp, lock
vars == <<counter, pc, tmp, lock>>

Init == /\ counter = 0
        /\ lock = FALSE
        /\ pc = [p \in Procs |-> "acq"]
        /\ tmp = [p \in Procs |-> 0]

Acq(p)   == /\ pc[p] = "acq"
            /\ ~lock
            /\ lock' = TRUE
            /\ pc' = [pc EXCEPT ![p] = "read"]
            /\ UNCHANGED <<counter, tmp>>

Read(p)  == /\ pc[p] = "read"
            /\ tmp' = [tmp EXCEPT ![p] = counter]
            /\ pc'  = [pc EXCEPT ![p] = "write"]
            /\ UNCHANGED <<counter, lock>>

Write(p) == /\ pc[p] = "write"
            /\ counter' = tmp[p] + 1
            /\ pc' = [pc EXCEPT ![p] = "rel"]
            /\ UNCHANGED <<tmp, lock>>

Rel(p)   == /\ pc[p] = "rel"
            /\ lock' = FALSE
            /\ pc' = [pc EXCEPT ![p] = "done"]
            /\ UNCHANGED <<counter, tmp>>

AllDone == \A p \in Procs : pc[p] = "done"

Next == \/ \E p \in Procs : Acq(p) \/ Read(p) \/ Write(p) \/ Rel(p)
        \/ (AllDone /\ UNCHANGED vars)

Spec == Init /\ [][Next]_vars /\ WF_vars(Next)

TypeOK          == /\ counter \in Nat
                   /\ lock \in BOOLEAN
                   /\ pc \in [Procs -> {"acq", "read", "write", "rel", "done"}]
                   /\ tmp \in [Procs -> Nat]
NoLostUpdate    == AllDone => counter = Cardinality(Procs)
MutualExclusion == \A p, q \in Procs :
                     (pc[p] \in {"read", "write", "rel"} /\ pc[q] \in {"read", "write", "rel"}) => p = q
VacuityProbe    == counter < Cardinality(Procs)      \* must be VIOLATED
Termination     == <>AllDone
=============================================================================
```

`CounterLock.cfg`:

```
SPECIFICATION Spec
CONSTANTS Procs = {p1, p2}
INVARIANTS TypeOK NoLostUpdate MutualExclusion
PROPERTIES Termination
```

`Vacuity.cfg` (expected to fail):

```
SPECIFICATION Spec
CONSTANTS Procs = {p1, p2}
INVARIANT VacuityProbe
```

Alternative fix (atomic increment): replace `Read` and `Write` with
`Inc(p) == pc[p] = "inc" /\ counter' = counter + 1 /\ pc' = [pc EXCEPT ![p] = "done"] /\ UNCHANGED tmp`
(drop `lock`, start every process at `"inc"`).

## Expected results

| Spec | Procs | Result | Distinct states |
|---|---|---|---|
| Counter (buggy) | {p1, p2} | NoLostUpdate violated, 5-state trace (TLC stops at the first violation) | n/a |
| CounterLock | {p1, p2} | no error; Termination holds | 17 |
| CounterLock | {p1, p2, p3} | no error | 61 |
| Counter with atomic `Inc` | {p1, p2} / {p1, p2, p3} | no error | 4 / 8 |
| CounterLock + Vacuity.cfg | {p1, p2} | VacuityProbe violated (expected) | n/a |

The distinct-state counts were computed by an independent breadth-first enumeration of exactly
these actions. TLC's "states generated" is larger (it counts duplicates). Adding
`SYMMETRY Perms` (with `Perms == Permutations(Procs)` and `EXTENDS TLC`) reduces the counts; do that
for the safety run only.

## Go port

`counter.go`:

```go
package counter

import "context"

type Store interface {
	Get(ctx context.Context, key string) (val, ver int64, err error)
	CompareAndSet(ctx context.Context, key string, oldVer, newVal int64) (bool, error)
}

type Counter struct {
	S         Store
	afterRead func() // test seam between the spec's Read and Write steps; nil in production
}

// Incr refines the spec's atomic increment: a failed CAS retries Read+Write as one logical step.
func (c *Counter) Incr(ctx context.Context, key string) error {
	for {
		v, ver, err := c.S.Get(ctx, key)
		if err != nil {
			return err
		}
		if c.afterRead != nil {
			c.afterRead()
		}
		ok, err := c.S.CompareAndSet(ctx, key, ver, v+1)
		if err != nil || ok {
			return err
		}
	}
}
```

`counter_test.go`:

```go
package counter

import (
	"context"
	"sync"
	"testing"
)

type memStore struct {
	mu sync.Mutex
	kv map[string][2]int64 // value, version
}

func (m *memStore) Get(_ context.Context, k string) (int64, int64, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	e := m.kv[k]
	return e[0], e[1], nil
}

func (m *memStore) CompareAndSet(_ context.Context, k string, oldVer, v int64) (bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.kv[k][1] != oldVer {
		return false, nil
	}
	m.kv[k] = [2]int64{v, oldVer + 1}
	return true, nil
}

// Replays the TLC counterexample: p1 Read, p2 Read, p1 Write, p2 Write.
func TestReplayLostUpdateTrace(t *testing.T) {
	ctx := context.Background()
	s := &memStore{kv: map[string][2]int64{}}
	once := func(f func()) func() { var o sync.Once; return func() { o.Do(f) } }
	p1Read, p2Read, p1Wrote := make(chan struct{}), make(chan struct{}), make(chan struct{})
	p1 := &Counter{S: s, afterRead: once(func() { close(p1Read); <-p2Read })}  // step 1, wait for 2
	p2 := &Counter{S: s, afterRead: once(func() { close(p2Read); <-p1Wrote })} // step 2, wait for 3
	var wg sync.WaitGroup
	wg.Add(2)
	go func() { defer wg.Done(); _ = p1.Incr(ctx, "k"); close(p1Wrote) }() // step 3
	go func() { defer wg.Done(); <-p1Read; _ = p2.Incr(ctx, "k") }()       // step 4
	wg.Wait()
	if v, _, _ := s.Get(ctx, "k"); v != 2 {
		t.Fatalf("lost update replayed: counter = %d, want 2", v)
	}
}
```

Write the test against the old get-then-put implementation first: it must fail with counter = 1,
which proves the test reproduces the TLC trace. Then apply the fix and keep the test, plus
`go test -race`.

## Turning any TLC trace into a test

1. Name the code location that implements each spec action (here: `Get` = Read, `CompareAndSet` =
   Write).
2. Add a seam at each boundary between actions the trace interleaves (a hook, a fake store, or a
   deterministic scheduler such as loom/Shuttle in Rust).
3. Drive the seams in trace order with channels or barriers; assert the violated invariant.
4. Keep the test after the fix. If the fix merges actions (an atomic step), the seam stays at the
   retry boundary so the schedule remains expressible.
