---
name: formal-verification-tla-dafny
description: "Formal verification: choosing the tool (TLA+ with TLC/Apalache, PlusCal, P, Alloy 6, Z3/cvc5, CBMC, Kani, Dafny, Verus, Lean 4), writing specs with complete actions, environment models, invariants and fairness, bounds and symmetry, vacuity checks, refinement and trace validation, loop invariants, bounded model checking harnesses, and reporting bounds. Load when a protocol, design or function must be shown correct beyond testing."
when_to_use: "Writing or reviewing a .tla/.cfg, PlusCal, Dafny (.dfy), Alloy, P or Verus model; a TLC counterexample ('Invariant ... is violated') or deadlock report; Dafny 'postcondition could not be proved' or verification timeouts; Kani or CBMC harnesses; proving a bit trick or overflow freedom with Z3; deciding whether a protocol, ledger invariant or parser needs formal methods; reporting what a model check actually covered."
---

# Formal verification with TLA+, Dafny and friends

Getting a trustworthy "this is correct" for designs and functions, and saying exactly what was
checked. The tool table stays in `cs-foundations` section 11; protocol knowledge in
`distributed-consensus-consistency`; loom/Shuttle for Rust concurrency in `concurrent-data-structures`;
mathematical proofs in `mathematics-toolkit`; test design in `testing-strategy`.

Deep material: [Counter worked example: fixed spec, configs, Go port and trace-replay test](references/counter-lock-example.md)

## 1. Tool choice and when it pays off

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

It pays off for concurrency and distributed protocols (interleavings tests never reach),
security-critical parsers and decoders, money and ledger invariants (conservation, no negative
balance, no double spend), and any subsystem with repeated production incidents. It does not pay
off for UI code or for properties nobody can state.

## 2. Workflow

1. Specify state and actions (including the environment: loss, crashes, clocks).
2. Write safety invariants: `TypeOK` plus the property.
3. Model check small configurations (3 nodes, 2-3 values) with symmetry.
4. Add liveness with explicit fairness (no symmetry while checking liveness).
5. Turn every counterexample trace into a regression test in the real code.
6. Validate implementation logs against the spec (trace validation) so the spec cannot drift.

Model checking proves properties of the model at the bounds checked; report the bounds.

## 3. TLA+ skeleton (finds a lost update)

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
java -cp tla2tools.jar tlc2.TLC -simulate -depth 100 -config Big.cfg Big.tla   # random behaviours of a big spec
java -cp tla2tools.jar tlc2.TLC -coverage 1 -config Counter.cfg Counter.tla    # per-action coverage each minute
java -cp tla2tools.jar pcal.trans Algo.tla                                     # translate PlusCal to TLA+
apalache-mc check --config=Counter.cfg --inv=NoLostUpdate --length=10 Counter.tla
```

`-coverage` lists how often each action fired: an action with zero distinct states is dead (usually
an over-strong guard). `-simulate` samples long behaviours when the state space is too big for
exhaustive search; a clean simulation run is evidence, not a proof. Apalache needs type annotations
on constants and variables (`\* @type: Int;` comments, e.g. `Str -> Int` for `tmp`) and suits
integer-heavy specs at bounded depth. The TLA+ extension for VS Code runs TLC and renders traces.

## 4. Spec-writing rules

- Every action specifies every variable: primed or in `UNCHANGED`. A missing one leaves the variable
  unconstrained (TLC errors) or silently wrong in hand reasoning.
- Model the environment explicitly: message loss = an action that removes a message from the network
  set; duplication = messages stay in the set after delivery; crash = an action that resets volatile
  state; clocks = bounded integer drift.
- Keep state finite: bound counters, terms and values (`MaxTerm == 3`) with a `CONSTRAINT` in the
  cfg, and say so in the report.
- Symmetry: `Perms == Permutations(Procs)` (EXTENDS TLC) and `SYMMETRY Perms` in the cfg, for safety
  only; symmetry can hide liveness violations.
- Liveness needs fairness: `WF_vars(A)` (continuously enabled implies eventually taken) or
  `SF_vars(A)` (repeatedly enabled). Without fairness every liveness property fails by stuttering.
- Vacuity: add a deliberately false invariant (`counter < 2`) and confirm TLC violates it, proving the
  interesting states are reached.
- Refinement: show the protocol implements a simpler spec (`Impl => AbstractSpec` under a refinement
  mapping) when the property is "behaves like one atomic register / one log".

## 5. Replication invariants (templates)

```tla
ElectionSafety == \A s, t \in Server :
    (state[s] = "Leader" /\ state[t] = "Leader" /\ currentTerm[s] = currentTerm[t]) => s = t
LogMatching == \A s, t \in Server : \A i \in 1..Min({Len(log[s]), Len(log[t])}) :
    log[s][i].term = log[t][i].term => SubSeq(log[s], 1, i) = SubSeq(log[t], 1, i)
StateMachineSafety == \A s, t \in Server : \A i \in 1..Min({commitIndex[s], commitIndex[t]}) :
    log[s][i] = log[t][i]
Min(S) == CHOOSE x \in S : \A y \in S : x <= y
```

The Raft checklist and read-path guarantees these protect are in `distributed-consensus-consistency`.

## 6. Dafny

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

Finding loop invariants: take the postcondition and replace the constant bound (`a.Length`) with the
loop variable (`j`); add the variable's range (`1 <= j <= a.Length`); add a conjunct for every
variable the loop modifies; check that invariant plus negated guard implies the postcondition. When
verification fails, strengthen the invariant or add an intermediate `assert` to locate the failing
step; never add `assume`.

- `decreases` gives the termination measure when Dafny cannot guess it (recursion on non-structural
  arguments, loops counting up to a bound it cannot see).
- `ghost` variables and functions exist only for the proof; lemmas are ghost methods whose
  `ensures` you invoke as facts.
- `opaque function` plus `reveal F();` (older versions: `{:opaque}`) stops the verifier unfolding a
  definition everywhere, which tames brittle proofs.
- Brittleness: `dafny verify --resource-limit <n>` gives deterministic limits (unlike time limits);
  split proofs with `assert P by { ... }` blocks and, in recent versions, the `{:isolate_assertions}`
  attribute.
- Commands: `dafny verify max.dfy`, `dafny run main.dfy`, `dafny build --target:go main.dfy` (other
  targets include C#, Java, JavaScript and Python; see `dafny build --help`).
- Verus is the Rust counterpart: `requires`/`ensures`/`invariant` on Rust code inside `verus!`, ghost
  code erased at compile time.

## 7. SMT directly (Z3 from Python)

```python
# uv run --with z3-solver python prove.py
from z3 import And, BitVecs, Extract, Implies, Ints, LShR, Not, Solver, ZeroExt, sat, unsat

def prove(claim, timeout_ms=10_000):
    s = Solver(); s.set(timeout=timeout_ms); s.add(Not(claim))
    r = s.check()
    if r == unsat: return "proved"
    if r == sat: return f"counterexample: {s.model()}"
    return f"unknown ({s.reason_unknown()}): NOT a proof"

a, b = BitVecs("a b", 32)
exact = Extract(31, 0, LShR(ZeroExt(1, a) + ZeroExt(1, b), 1))      # floor((a+b)/2) in 33 bits
print(prove((a & b) + LShR(a ^ b, 1) == exact))   # proved: overflow-free unsigned average
print(prove(LShR(a + b, 1) == exact))             # counterexample: a + b wraps at 2^32

x, y = Ints("x y")
print(prove(Implies(And(x >= 0, y >= 0), (x + y) / 2 >= 0)))   # proved over mathematical integers
p, q = BitVecs("p q", 32)
print(prove(Implies(And(p >= 0, q >= 0), (p + q) / 2 >= 0)))   # counterexample: 32-bit signed overflow
```

Overflow exists only in `BitVec` sorts (signed `/`, `>=` and `>>` on BitVecs; `LShR`, `UDiv`, `ULT`
for unsigned). Quantified formulas need triggers (`ForAll([x], f(x) > 0, patterns=[f(x)])`) and still
time out; `unknown` is never success. Cross-check important results in cvc5: export with
`s.to_smt2()` and run `cvc5 query.smt2`.

## 8. Bounded model checking

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

`cargo kani --harness midpoint_in_range`. Loops need `#[kani::unwind(n)]` on the harness; Kani adds
unwinding assertions, so a bound that is too small fails instead of passing silently. Function
contracts (unstable, `cargo kani -Z function-contracts`) verify a function once and reuse it as a stub:

```rust
#[kani::requires(a <= b)]
#[kani::ensures(|m: &u32| a <= *m && *m <= b)]
fn midpoint(a: u32, b: u32) -> u32 { a + (b - a) / 2 }

#[kani::proof_for_contract(midpoint)]
fn midpoint_contract() { midpoint(kani::any(), kani::any()); }
```

CBMC for C: `cbmc harness.c --function harness --bounds-check --pointer-check
--signed-overflow-check --unwind 10 --unwinding-assertions` (recent releases enable several of these
checks by default; passing them explicitly documents intent). Without unwinding assertions, paths
deeper than the bound are silently dropped. Always report the unwind bound.

## 9. Other modelling tools

- Alloy 6: relational logic plus temporal operators (`always`, `eventually`, primed relations) for
  data models, permissions and access policies; analysis within explicit scopes.
- P: communicating state machines for event-driven services, with model checking and systematic
  testing of the same code.
- loom and Shuttle for Rust concurrency: `concurrent-data-structures`.
- Lean 4 with Mathlib for mathematical lemmas behind an algorithm: `mathematics-toolkit`.

## 10. Reporting a formal result

| Field | Example |
|---|---|
| Artifact | `specs/Replication.tla`, cfg `Replication.cfg` |
| Properties | ElectionSafety, LogMatching, StateMachineSafety (invariants); EventuallyCommitted (liveness, WF on Deliver) |
| Bounds | 3 servers, MaxTerm 3, MaxLogLen 3, network bag <= 6 messages |
| Result | invariants hold on 4.2M distinct states (TLC, 6 min, 8 workers); liveness holds |
| Vacuity | false invariant `commitIndex[s1] < 2` violated as expected |
| Not covered | reconfiguration; unbounded terms; disk corruption |
| Status | Model-checked within bounds (not a proof for all sizes) |

## 11. Pitfalls

- Vacuous specs: an over-constrained `Init` or guard makes every invariant hold; run the vacuity check.
- Unrealistic fairness (strong fairness on a lossy network) proving liveness the system lacks.
- An abstraction gap: the spec models an atomic step the code performs in two.
- `assume` or `{:verify false}` left in final Dafny; `kani::assume` that excludes real inputs.
- Unbounded quantifiers timing out, read as success; `unknown` reported as "no counterexample".
- A spec that silently drifts from the code: keep trace validation or spec-derived tests in CI.

## 12. Worked example: the lost update, end to end

1. **Find it.** TLC on `Counter.tla` with `Procs = {p1, p2}` reports `Invariant NoLostUpdate is
   violated` and a 5-state trace such as: Init (counter 0), `Read(p1)` (tmp p1 = 0), `Read(p2)` (tmp p2 = 0),
   `Write(p1)` (counter 1), `Write(p2)` (counter 1), all done with counter 1.
2. **Fix the spec first.** Add `lock \in BOOLEAN` and the path `acq -> read -> write -> rel -> done`
   with `Acq(p) == pc[p] = "acq" /\ ~lock /\ lock' = TRUE /\ ...` and `Rel(p)` resetting it; every
   action lists `lock` in `UNCHANGED` where it does not change it. Add
   `MutualExclusion == \A p, q \in Procs : (pc[p] \in {"read", "write", "rel"} /\ pc[q] \in {"read", "write", "rel"}) => p = q`.
   (Alternative fix: one atomic `Inc(p)` action replacing `Read` and `Write`.) Full module in
   [the reference](references/counter-lock-example.md).
3. **Re-check and report counts.** Expected: no error, with 17 distinct states for 2 processes and 61
   for 3 (the atomic-increment variant: 4 and 8). These counts come from an independent enumeration
   of the same actions; if TLC disagrees, the spec differs from the one described. Termination holds
   under `WF_vars(Next)`.
4. **Vacuity.** A second cfg with `INVARIANT VacuityProbe` where
   `VacuityProbe == counter < Cardinality(Procs)` must be reported violated: the final state is
   reachable, so the passing run was not vacuous.
5. **Port to code with a regression test that replays the trace.** The Go service used get-then-put.
   The fix is a versioned compare-and-set that retries on conflict (it refines the atomic increment).
   A test seam between read and write lets the test force the TLC schedule p1 read, p2 read, p1 write,
   p2 write; on the old code it fails with counter = 1, on the fix it passes with 2 (p2's CAS fails,
   it re-reads 1 and writes 2). Code in [the reference](references/counter-lock-example.md).
6. **Report** with the template in section 10: artifact, properties (TypeOK, NoLostUpdate,
   MutualExclusion, Termination), bounds (2 and 3 processes), result with state counts and time,
   vacuity probe violated as expected, not covered (crashes while holding the lock), status
   "model-checked within bounds, not a proof for all sizes".

Related: `distributed-consensus-consistency`, `concurrent-data-structures`, `mathematics-toolkit`, `testing-strategy`, `rust-unsafe-soundness`, `cpp-ub-sanitizers`, hub `cs-foundations`
