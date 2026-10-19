# Formal methods templates

## 1. Tool choice

| Question | Tool | Cost |
|---|---|---|
| Can this protocol/design violate an invariant? | TLA+ + TLC (explicit state), Apalache (SMT, bounded) | hours to days; spec only |
| Event-driven services with message queues | P language (model checking + systematic testing) | days |
| Structural constraints, access policies, data models | Alloy 6 | hours |
| Does this C function overflow / go out of bounds for all inputs up to a bound? | CBMC | minutes per harness |
| Same for Rust (incl. unsafe) | Kani (`cargo kani`) | minutes per harness |
| Rust concurrency interleavings in tests | loom (exhaustive, small), Shuttle (randomised) | minutes |
| Verified implementation with pre/postconditions | Dafny, Verus, Why3, Frama-C WP, SPARK | days to weeks |
| Deep mathematical / compiler / OS proofs | Lean 4, Rocq (formerly Coq), Isabelle/HOL | weeks to years |

## 2. TLA+ skeleton (finds a lost update)

`Counter.tla`:

```tla
---------------------------- MODULE Counter ----------------------------
EXTENDS Naturals, FiniteSets
CONSTANTS Procs
VARIABLES counter, pc, tmp
vars == <<counter, pc, tmp>>

Init == /\ counter = 0
        /\ pc = [p \in Procs |-> "read"]
        /\ tmp = [p \in Procs |-> 0]

Read(p)  == /\ pc[p] = "read"
            /\ tmp' = [tmp EXCEPT ![p] = counter]
            /\ pc'  = [pc EXCEPT ![p] = "write"]
            /\ UNCHANGED counter

Write(p) == /\ pc[p] = "write"
            /\ counter' = tmp[p] + 1
            /\ pc' = [pc EXCEPT ![p] = "done"]
            /\ UNCHANGED tmp

AllDone == \A p \in Procs : pc[p] = "done"

Next == \/ \E p \in Procs : Read(p) \/ Write(p)
        \/ (AllDone /\ UNCHANGED vars)          \* explicit termination, avoids deadlock report

Spec == Init /\ [][Next]_vars /\ WF_vars(Next)

TypeOK       == /\ counter \in Nat
                /\ pc \in [Procs -> {"read", "write", "done"}]
                /\ tmp \in [Procs -> Nat]
NoLostUpdate == AllDone => counter = Cardinality(Procs)
Termination  == <>AllDone
=============================================================================
```

`Counter.cfg`:

```
SPECIFICATION Spec
CONSTANTS Procs = {p1, p2}
INVARIANTS TypeOK NoLostUpdate
PROPERTIES Termination
```

Run:

```bash
java -XX:+UseParallelGC -cp tla2tools.jar tlc2.TLC -workers auto -config Counter.cfg Counter.tla
```

TLC reports NoLostUpdate violated with the trace: p1 reads 0, p2 reads 0, p1 writes 1, p2 writes 1.
Fix in the spec first (make Read+Write one atomic action, or add a lock variable), re-check, then
port the fix to code and add a regression test reproducing the trace.

Apalache (`apalache-mc check --config=Counter.cfg --length=10 Counter.tla`) needs type annotations
on constants and variables (`\* @type: Int;` style comments); use it for larger or
integer-heavy state spaces with bounded depth.

## 3. Spec-writing rules

- Every action specifies every variable: primed or in `UNCHANGED`. A missing one makes the
  variable unconstrained (TLC errors) or silently wrong in hand-written reasoning.
- Model the environment explicitly: message loss = an action that removes a message from the
  network set; duplication = messages stay in the set after delivery; crashes = an action that
  resets volatile state; clocks = bounded integer drift.
- Keep state finite: bound message counters, terms, values (`MaxTerm == 3`) with `CONSTRAINT`
  in the cfg, and say so in the report.
- Symmetry: `Perms == Permutations(Procs)` (EXTENDS TLC) and `SYMMETRY Perms` in the cfg. Do not
  use symmetry while checking liveness (it can hide violations).
- Liveness needs fairness: `WF_vars(A)` (weak: continuously enabled ⇒ eventually taken) or
  `SF_vars(A)` (strong: repeatedly enabled). No fairness ⇒ every liveness property fails trivially
  by stuttering.
- Vacuity check: add a deliberately false invariant (e.g. `counter < 2`) and confirm TLC violates
  it, proving the interesting states are actually reached.
- Refinement: show the protocol implements a simpler spec (`Impl => AbstractSpec` via a refinement
  mapping) when the property is "behaves like a single atomic register / a log".

Typical invariants for replication protocols:

```tla
ElectionSafety == \A s, t \in Server :
    (state[s] = "Leader" /\ state[t] = "Leader" /\ currentTerm[s] = currentTerm[t]) => s = t
LogMatching == \A s, t \in Server : \A i \in 1..Min({Len(log[s]), Len(log[t])}) :
    log[s][i].term = log[t][i].term => SubSeq(log[s], 1, i) = SubSeq(log[t], 1, i)
StateMachineSafety == \A s, t \in Server : \A i \in 1..Min({commitIndex[s], commitIndex[t]}) :
    log[s][i] = log[t][i]
```

(`Min` over a set must be defined in the spec, e.g. `Min(S) == CHOOSE x \in S : \A y \in S : x <= y`.)

## 4. Dafny (verified function)

```dafny
method Max(a: array<int>) returns (m: int)
  requires a.Length > 0
  ensures forall i :: 0 <= i < a.Length ==> a[i] <= m
  ensures exists i :: 0 <= i < a.Length && a[i] == m
{
  m := a[0];
  var j := 1;
  while j < a.Length
    invariant 1 <= j <= a.Length
    invariant forall i :: 0 <= i < j ==> a[i] <= m
    invariant exists i :: 0 <= i < j && a[i] == m
  {
    if a[j] > m { m := a[j]; }
    j := j + 1;
  }
}
```

`dafny verify max.dfy`. Loop invariants are the proof; when verification fails, strengthen the
invariant, do not add `assume`.

## 5. Kani (bounded model checking for Rust)

```rust
#[cfg(kani)]
#[kani::proof]
fn midpoint_in_range() {
    let a: u32 = kani::any();
    let b: u32 = kani::any();
    kani::assume(a <= b);
    let m = a + (b - a) / 2;          // (a + b) / 2 would overflow; Kani finds that
    assert!(a <= m && m <= b);
}
```

`cargo kani --harness midpoint_in_range`. Loops need `#[kani::unwind(n)]`; report the bound.

## 6. loom (exhaustive interleavings, Rust)

```rust
#[cfg(loom)]
#[test]
fn racy_increment() {
    use loom::sync::Arc;
    use loom::sync::atomic::{AtomicUsize, Ordering::SeqCst};
    loom::model(|| {
        let c = Arc::new(AtomicUsize::new(0));
        let hs: Vec<_> = (0..2).map(|_| {
            let c = c.clone();
            loom::thread::spawn(move || { let v = c.load(SeqCst); c.store(v + 1, SeqCst); })
        }).collect();
        for h in hs { h.join().unwrap(); }
        assert_eq!(c.load(SeqCst), 2);   // fails: loom finds the lost-update interleaving
    });
}
```

`RUSTFLAGS="--cfg loom" cargo test --release racy_increment`. Fix with `fetch_add(1, SeqCst)`.

## 7. Reporting a formal result

| Field | Example |
|---|---|
| Artifact | `specs/Replication.tla`, cfg `Replication.cfg` |
| Properties | ElectionSafety, LogMatching, StateMachineSafety (invariants); EventuallyCommitted (liveness, WF on Deliver) |
| Bounds | 3 servers, MaxTerm 3, MaxLogLen 3, network bag ≤ 6 messages |
| Result | invariants hold on 4.2M distinct states (TLC, 6 min, 8 workers); liveness holds |
| Vacuity | false invariant `commitIndex[s1] < 2` violated as expected |
| Not covered | reconfiguration; unbounded terms; disk corruption |
| Status | Model-checked within bounds (not a proof for all sizes) |
