---
name: distributed-consensus-consistency
description: "Replication protocols and their real guarantees: failure and timing models, FLP/CAP/PACELC, quorum arithmetic, Raft and Multi-Paxos safety checklists, linearizable reads (ReadIndex, leases), fencing, consistency models and session guarantees, clocks, CRDTs, idempotency/outbox/sagas, and testing with deterministic simulation, Jepsen, Elle and Porcupine. Load when designing, reviewing or debugging replicated state or a consistency claim."
when_to_use: "A design doc or PR touching Raft/Paxos, leader election, quorum sizes or replica placement; 'follower reads', 'read from replica', 'linearizable', 'exactly-once' or 'strongly consistent' claims; leases, distributed locks or fencing tokens; LWW conflict resolution, vector clocks or CRDTs; outbox, saga or 2PC designs; Jepsen, Elle or Porcupine results; split-brain or stale-read incidents."
---

# Distributed consensus and consistency

How to state, achieve and test the guarantee a replicated system gives. The fact table stays in
`cs-foundations` section 9; transactional isolation inside one database lives in
`database-transactions-isolation`; retries, timeouts and breakers in `resilience-patterns`; protocol
model checking in `formal-verification-tla-dafny`.

## 1. Declare the model before any claim

| Dimension | Options | Why it matters |
|---|---|---|
| Timing | synchronous (known bounds), partially synchronous (bounds hold eventually), asynchronous | FLP applies to deterministic async consensus |
| Process failures | crash-stop, crash-recovery (stable storage), omission, Byzantine | quorum sizes: 2f+1 vs 3f+1 |
| Network | reliable, fair-loss, partitions, reordering, duplication | idempotence and retries |
| Clocks | none, NTP-synchronised (ms), bounded uncertainty (PTP/TrueTime-like, µs-ms) | leases and timestamps are only as safe as the bound |
| Storage | fsync honoured or not, torn writes | crash-recovery correctness |

Write one line per dimension in the design doc. A claim without a model ("it's consistent") is not
reviewable.

## 2. Impossibility results and quorum arithmetic

- **FLP**: no deterministic protocol reaches consensus in an asynchronous system if one process may
  crash. Real protocols keep safety always and get liveness from partial synchrony (timeouts) or
  randomisation.
- **CAP**: during a partition, a linearizable object cannot stay available on both sides. **PACELC**:
  else (no partition) you still trade latency against consistency, which is the everyday choice.

```text
crash faults:     n = 2f + 1,  quorum q = f + 1 (majority)
Byzantine:        n = 3f + 1,  quorum q = 2f + 1 (two quorums share >= f + 1 nodes, >= 1 honest)
leaderless R/W:   R + W > N for read-your-latest; W > N/2 to serialise concurrent writes
availability:     a majority quorum tolerates f = floor((n-1)/2); even n adds cost, not tolerance
flexible Paxos:   only phase-1 and phase-2 quorums must intersect: |Q1| + |Q2| > n
```

| n (crash) | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|
| tolerated f | 1 | 1 | 2 | 2 | 3 |

Commit latency = one round trip from the leader to the median-fastest majority, plus fsync. Placement:
3 regions with 1 replica each survive a region loss and commit at the RTT to the nearest other region;
2 regions cannot survive the loss of the region holding the majority (add a witness in a third
region); 5 replicas as 2-2-1 across 3 regions survive one region and commit within the leader's
region plus its nearest neighbour. Put the leader near the writers.

## 3. Raft safety checklist (review any Raft-based design against it)

1. Election restriction: vote only for candidates whose log is at least as up to date (last term,
   then last index).
2. Commit rule: the leader marks an entry committed only when an entry from its current term is on
   a majority; earlier entries commit implicitly (Figure 8: a term-2 entry replicated to a majority
   by the term-4 leader can still be overwritten by a server holding a term-3 entry).
3. Persistent state (`currentTerm`, `votedFor`, log) fsynced before responding to RPCs.
4. Membership change one server at a time, or joint consensus; never jump directly between disjoint
   majorities. With single-server changes, the leader must commit an entry of its own term before
   starting a change.
5. Linearizable reads: ReadIndex (confirm leadership with a heartbeat round) or leases (bounded clock
   drift); otherwise even leader reads may be stale after a partition.
6. Client retries carry a unique request id; the state machine deduplicates.

Frequent implementation bugs:

- No pre-vote or check-quorum: a partitioned node inflates its term and deposes a healthy leader on
  rejoin; a leader cut off from the majority keeps serving. Lease reads are unsafe without
  check-quorum.
- Snapshot install races: applying a snapshot older than the applied index, or keeping log entries
  that conflict with the snapshot's last included index and term.
- Truncating committed entries: a delayed `AppendEntries` must truncate only at the first index whose
  term actually conflicts, never unconditionally after `prevLogIndex + len(entries)`.
- `votedFor` not persisted: after a restart the node votes twice in one term, giving two leaders.
- Acknowledging a client before the entry is applied, or applying before it is committed.

## 4. Paxos family and alternatives

```text
Phase 1a  proposer -> acceptors: Prepare(b)            b: unique, increasing ballot
Phase 1b  acceptor: if b > promised { promised = b; persist; reply Promise(b, acc_ballot, acc_value) }
Phase 2a  on a majority of promises: v = value with the highest acc_ballot, else own value; Accept(b, v)
Phase 2b  acceptor: if b >= promised { promised = b; accepted = (b, v); persist; reply Accepted(b, v) }
Chosen    a majority accepted the same (b, v)
Invariant once v is chosen at b, every Accept with a ballot above b carries v
```

Multi-Paxos runs phase 1 once for all future slots under a distinguished leader, then one round trip
per command.

| Protocol | Fault model | Notes |
|---|---|---|
| Paxos / Multi-Paxos | crash, 2f+1 | prepare/promise, accept/accepted; leader for liveness |
| Raft | crash, 2f+1 | Multi-Paxos variant with strong leader, log matching, membership changes |
| Viewstamped Replication | crash, 2f+1 | close relative of Raft; VR Revisited is a readable spec |
| EPaxos / leaderless | crash, 2f+1 | commuting commands commit in one round trip; complex recovery |
| Zab | crash, 2f+1 | ZooKeeper's atomic broadcast |
| PBFT | Byzantine, 3f+1 | O(n^2) messages per decision |
| HotStuff / Tendermint | Byzantine, 3f+1 | HotStuff has a linear view change |
| Chain replication | crash + external configuration master | writes at head, reads at tail; CRAQ reads anywhere |
| Primary-backup | crash + failure detector + fencing | simplest; split brain without fencing tokens |

## 5. Use, don't write

| Library | Language | Notes |
|---|---|---|
| etcd-io/raft | Go | core state machine; you supply storage and transport; `PreVote`, `CheckQuorum`, `ReadOnlySafe` (ReadIndex) or `ReadOnlyLeaseBased` reads |
| hashicorp/raft | Go | batteries included; Consul, Nomad, Vault |
| openraft / raft-rs | Rust | async (tokio) / TiKV's port of etcd raft |
| Apache Ratis | Java | Apache Ozone |
| NuRaft | C++ | ClickHouse Keeper |

Prefer delegating coordination entirely: etcd (leases, revisions usable as fencing tokens), ZooKeeper
(ephemeral sequential znodes), Consul sessions. Evaluate a library on: a published Jepsen analysis and
its fixes; read semantics offered and the default; snapshots, log compaction and `InstallSnapshot`;
membership-change algorithm; pre-vote and check-quorum; the storage contract (what is fsynced before
an ack); a deterministic test harness; production users and release activity.

## 6. Consistency models and what provides them

Single-object, strongest first: linearizable > sequential > causal > PRAM/FIFO > eventual. Session
guarantees (per client): read-your-writes, monotonic reads, monotonic writes, writes-follow-reads.
Name the exact model and test it; marketing terms ("strong", "eventual") are not specifications.

| Requirement | Minimum model | Mechanism |
|---|---|---|
| Unique names, locks, leader election, "everyone sees an acknowledged write" | linearizable | consensus log + ReadIndex or lease reads; CAS in etcd/ZooKeeper |
| A user sees their own edits | read-your-writes | client carries its last write index; replica waits until applied >= token, or sticky routing |
| A feed never jumps backwards | monotonic reads | session token or sticky replica |
| A reply never appears before the post it answers | causal | dependency tracking (vector clocks, causal+ stores) |
| Offline edits, counters, sets converge | strong eventual consistency | CRDTs (section 8) |
| Multi-row invariants (balance never negative) | serializable transactions | `database-transactions-isolation` |
| Dashboards tolerate seconds of lag | bounded staleness | follower reads with an advertised maximum lag |

R + W > N is not linearizable. N = 3, W = R = 2: a write of x = 1 has reached only A. Reader 1 reads
{A, B}, returns 1 and finishes; reader 2 starts later, reads {B, C} and returns 0. A new value then an
old one: a real-time violation. ABD makes a register linearizable without consensus: a read queries a
majority, takes the highest (timestamp, value), writes it back to a majority, then returns; a write
queries a majority for the highest timestamp and writes a higher one. Read-modify-write (CAS) still
needs consensus.

## 7. Time, leases and fencing

| Mechanism | Gives | Limits |
|---|---|---|
| Lamport clock | a -> b implies L(a) < L(b) | not the converse; cannot detect concurrency |
| Vector clock | a -> b iff V(a) < V(b); detects concurrency | O(n) per timestamp |
| Version vectors / dotted version vectors | per-replica causality for objects | sibling explosion without dots |
| Hybrid logical clock | timestamps close to physical time, with causality | closeness needs bounded skew |
| Bounded-uncertainty time | commit wait gives external consistency | needs GPS/atomic clocks; wait about 2*eps |
| Leases | time-bounded ownership | unsafe if drift exceeds the margin; pair with fencing |

Lease arithmetic with duration D and maximum clock-rate drift rho: the holder measures from the
moment it sent the request, on a monotonic clock, and stops at start + D(1 - rho) minus a margin; the
grantor waits D(1 + rho) after the last grant before granting again. Wall-clock jumps (NTP steps, VM
migration) break leases built on wall time.

Fencing token procedure (protects against GC pauses, VM freezes and slow ex-leaders):

1. The lock or lease service returns a token that increases with every grant (an etcd revision, a
   ZooKeeper sequence number or zxid).
2. The client attaches the token to every write made under the lock.
3. Storage keeps the highest token seen per resource and rejects lower ones atomically with the write
   (`UPDATE ... WHERE fence <= :token`).
4. Test it: pause the holder (`SIGSTOP`) past expiry, let a second client acquire and write, resume
   the first; its write must be rejected.

## 8. CRDTs

Merge must form a join-semilattice: commutative, associative, idempotent, so any delivery order and
any duplication converge.

| Type | Merge | Note |
|---|---|---|
| G-Counter | element-wise max | grow only |
| PN-Counter | two G-Counters | increments and decrements |
| LWW-Register | highest timestamp wins | silently drops concurrent writes; needs good clocks |
| MV-Register | keep concurrent values | application resolves |
| OR-Set | add-wins with unique tags | tombstone growth; causal compaction |
| Sequence (RGA, Logoot, Fugue) | collaborative text | interleaving anomalies differ by algorithm |

```rust
#[derive(Clone, Default, PartialEq, Debug)]
struct GCounter(std::collections::BTreeMap<u32, u64>);   // replica id -> count
impl GCounter {
    fn inc(&mut self, me: u32) { *self.0.entry(me).or_default() += 1; }
    fn value(&self) -> u64 { self.0.values().sum() }
    fn merge(&mut self, o: &Self) {
        for (r, n) in &o.0 { let e = self.0.entry(*r).or_default(); *e = (*e).max(*n); }
    }
}
```

Delta-state CRDTs ship small deltas that are joined like full states. Libraries: Automerge (JSON
documents, Rust core with JS/WASM), Yjs (and the Rust port Yrs), Loro. Test with property-based runs:
random operations at several replicas, delivery in random order with duplicates, then assert
convergence plus the three merge laws.

## 9. End-to-end effects

- Exactly-once effect = at-least-once delivery + idempotent processing. "Exactly-once delivery" does
  not exist end to end.
- Idempotency keys: the client generates one key per logical operation; the server stores key ->
  (request hash, response) in the same transaction as the effect, rejects a reused key with a
  different payload, and keeps keys longer than the whole retry horizon (client retries + queue
  redelivery + clock skew).
- Outbox: write the state change and an outbox row in one local transaction; a relay (polling or
  CDC) publishes; consumers deduplicate by event id.
- Sagas: every step has an explicit compensation; list the anomalies you accept (other transactions
  see intermediate states) and use pending states as semantic locks.
- 2PC blocks when the coordinator dies after prepare (participants hold locks in doubt); replicate
  the coordinator (Paxos Commit, Spanner-style groups) or avoid cross-shard atomicity.
- Retries, backoff and retry budgets: `caching-and-system-tradeoffs` and `resilience-patterns`.

## 10. Testing

- Deterministic simulation: the whole system in one process with simulated network, disk and clock,
  reproducible from a seed (FoundationDB, TigerBeetle VOPR, Antithesis; madsim and turmoil for Rust).
- Jepsen: real nodes plus nemeses (partitions, clock skew, process pauses, kills, disk faults that
  lose unsynced writes); histories checked by Knossos or Porcupine (linearizability) and Elle
  (transactional anomalies through dependency cycles).
- Model checking: TLA+ spec of the protocol, then trace validation of implementation logs against it
  (`formal-verification-tla-dafny`).

## 11. Pitfalls

- Promising "exactly-once delivery" instead of idempotent effects.
- Leader leases without fencing tokens, or leases measured on wall clocks.
- A majority quorum split across 2 regions: losing the bigger region stops writes.
- LWW with skewed clocks silently dropping writes; use MV-registers or CRDTs where loss matters.
- Follower or replica reads labelled linearizable.
- Reconfiguration that jumps between disjoint majorities, or two concurrent membership changes.
- Retrying non-idempotent RPCs after a timeout (the first attempt may have succeeded).

## 12. Worked example: review a "follower reads" PR on a Raft KV store

The PR serves `GET` from any replica's local state machine to offload the leader, and the API docs
still say "linearizable".

1. **Stale-read history.** Nodes n1 (leader), n2, n3; a partition isolates n3. Client A: `put(x, 2)`
   through n1, committed on {n1, n2}, acknowledged at t1. Client B at t2 > t1: `get(x)` on n3
   returns 1. The write completed before the read began, yet the read missed it: not linearizable,
   and not even read-your-writes if A does the read. The same history arises on a deposed leader
   serving local reads without ReadIndex.
2. **Fix options.**

| Option | Guarantee | Cost | Assumptions |
|---|---|---|---|
| Forward to leader + ReadIndex | linearizable | client hop + one leader-to-majority round trip | leader has committed an entry in its term |
| Follower ReadIndex (as etcd) | linearizable | follower asks leader for the read index (same round trip), waits until applied >= index, serves locally | same; moves read bandwidth to followers |
| Leader lease reads | linearizable while the lease holds | no quorum round | check-quorum on, drift bound rho stated, lease < election timeout x (1 - rho) |
| Bounded-staleness API | stale by at most max_lag | none | documented; response carries the applied index |

3. **Check with Porcupine.** Record every operation's call and return times in a Jepsen-style test
   with partitions and a client pinned to the isolated follower:

```go
type kvIn struct{ Op, Value string }
type kvOut struct{ Value string }

var register = porcupine.Model{
	Init: func() any { return "0" },
	Step: func(state, in, out any) (bool, any) {
		i, o := in.(kvIn), out.(kvOut)
		if i.Op == "put" {
			return true, i.Value
		}
		return o.Value == state.(string), state // a get must return the current value
	},
}

// history: []porcupine.Operation{ClientId, Input: kvIn{...}, Call: t0, Output: kvOut{...}, Return: t1}
if !porcupine.CheckOperations(register, history) {
	t.Fatal("history is not linearizable")
}
```

   The PR as written fails; the follower-ReadIndex fix passes the same nemesis schedule. Keep the
   test in CI with fixed seeds.
4. **State the guarantee in the API docs:** "`GET` (default) is linearizable: it reflects every write
   acknowledged before the request started; cost is one leader quorum round trip. `GET
   ?consistency=stale&max_lag=5s` may return data up to 5 s old and reports `X-Applied-Index`."

Related: `database-transactions-isolation`, `formal-verification-tla-dafny`, `caching-and-system-tradeoffs`, `concurrent-data-structures`, `resilience-patterns`, `observability-instrumentation`, hub `cs-foundations`
