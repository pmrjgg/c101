# Distributed systems reference

## 1. Models first

| Dimension | Options | Why it matters |
|---|---|---|
| Timing | synchronous (known bounds), partially synchronous (bounds hold eventually), asynchronous | FLP impossibility applies to deterministic async consensus |
| Process failures | crash-stop, crash-recovery (stable storage), omission, Byzantine | quorum sizes: 2f+1 vs 3f+1 |
| Network | reliable links, fair-loss, partitions, reordering, duplication | idempotence and retries |
| Clocks | none, loosely synchronised (NTP: ms), bounded uncertainty (PTP/TrueTime-like: µs-ms) | leases and timestamps are only as safe as the bound |
| Storage | fsync honoured or not, torn writes | crash-recovery correctness |

## 2. Consistency models

Single-object (register / key) models:

| Model | Guarantee | Typical system / mechanism |
|---|---|---|
| Linearizable | every operation appears atomic at a point between invocation and response, respecting real time | consensus-replicated logs (Raft/Paxos), leader reads with lease or read-index |
| Sequential | one total order consistent with each process's program order, not real time | some caches, ZooKeeper writes + sync reads |
| Causal | causally related ops seen in order by all; concurrent ops may differ | causal+ stores (COPS-style), vector clocks |
| PRAM / FIFO | each writer's ops seen in its order | per-session pipelines |
| Read-your-writes, monotonic reads, monotonic writes, writes-follow-reads | session guarantees | sticky sessions, client tokens |
| Eventual | replicas converge if writes stop | Dynamo-style stores, CRDTs (strong eventual consistency) |

Transactional models (multi-object):

| Model | Prevents | Allows |
|---|---|---|
| Strict serializable | everything below + real-time violations | - |
| Serializable | all anomalies relative to some serial order | real-time reordering (stale reads in some systems) |
| Snapshot isolation | dirty/non-repeatable reads, lost updates | write skew (two transactions read overlapping data, write disjoint data) |
| Repeatable read (ANSI) | non-repeatable reads | phantoms (implementation-specific) |
| Read committed | dirty reads | non-repeatable reads, lost updates |
| Read uncommitted | dirty writes | dirty reads |

Vendor names lie: PostgreSQL "REPEATABLE READ" is snapshot isolation; its "SERIALIZABLE" is SSI;
MySQL InnoDB "REPEATABLE READ" differs again. Test with history checkers (Jepsen's Elle) rather
than trusting names.

## 3. Consensus and replication

| Protocol | Fault model | Notes |
|---|---|---|
| Paxos / Multi-Paxos | crash, 2f+1 | prepare/promise, accept/accepted; leader (distinguished proposer) for liveness |
| Raft | crash, 2f+1 | understandable Multi-Paxos variant; leader election, log replication, membership changes |
| Viewstamped Replication | crash, 2f+1 | close relative of Raft |
| EPaxos / leaderless variants | crash, 2f+1 | commutative commands commit in one round trip; complex recovery |
| Zab | crash, 2f+1 | ZooKeeper's atomic broadcast |
| PBFT | Byzantine, 3f+1 | O(n²) messages per decision |
| HotStuff / Tendermint | Byzantine, 3f+1 | linear view change (HotStuff), blockchain settings |
| Chain replication | crash, needs external configuration master | high throughput reads at tail |
| Primary-backup | crash, needs failure detector + fencing | simplest; split brain without fencing tokens |

Raft safety checklist (review any Raft-based design against it):
1. Election restriction: vote only for candidates whose log is at least as up to date (last term,
   then last index).
2. Commit rule: leader marks an entry committed only when an entry from its current term is on a
   majority; earlier entries commit implicitly (Figure 8 scenario).
3. Persistent state (currentTerm, votedFor, log) fsynced before responding to RPCs.
4. Membership change one server at a time, or joint consensus; never jump directly between
   disjoint majorities.
5. Linearizable reads: ReadIndex (confirm leadership with a heartbeat round) or leases (require
   bounded clock drift); otherwise reads from the leader may be stale after a partition.
6. Client retries carry a unique request id; the state machine deduplicates (exactly-once
   semantics on top of at-least-once).

## 4. Quorum arithmetic

```
crash faults:     n = 2f + 1,  quorum q = f + 1 (majority)
Byzantine:        n = 3f + 1,  quorum q = 2f + 1 (any two quorums intersect in ≥ f + 1 nodes, ≥ 1 honest)
leaderless R/W:   R + W > N for read-your-latest; W > N/2 to serialise concurrent writes
availability:    a majority quorum tolerates f = floor((n-1)/2) failures; even n adds cost but no tolerance (4 nodes tolerate 1, same as 3)
flexible Paxos:  only phase-1 and phase-2 quorums must intersect: |Q1| + |Q2| > n
```

Latency: a commit costs one round trip to the median-fastest majority; across regions, place a
majority within one low-latency group or accept WAN round trips (e.g. 3 regions ~ 60-150 ms RTT).

## 5. Time and ordering

| Mechanism | Gives | Limits |
|---|---|---|
| Lamport clock | if a → b then L(a) < L(b) | not the converse; cannot detect concurrency |
| Vector clock | a → b iff V(a) < V(b); detects concurrency | O(n) size per timestamp |
| Version vectors / dotted version vectors | per-replica causality for objects | sibling explosion without dots |
| Hybrid logical clock | physical-time-close timestamps with causality | depends on bounded skew for closeness |
| Bounded-uncertainty time (TrueTime-like) | commit wait gives external consistency | needs GPS/atomic clocks; wait ≈ 2ε |
| Leases | time-bounded ownership | unsafe if clock drift exceeds margin; always pair with fencing tokens |

## 6. Failure handling patterns

- Fencing tokens: monotonically increasing token with each lease/lock; storage rejects older tokens.
  Without them, a paused (GC, VM migration) ex-leader can corrupt state.
- Idempotency keys + dedup table with TTL longer than max retry horizon.
- Outbox pattern: write the event in the same transaction as the state change; a relay publishes.
- Sagas: compensating actions instead of distributed transactions; define compensation for every
  step and the isolation anomalies you accept.
- Two-phase commit blocks if the coordinator fails after prepare; use consensus-replicated
  coordinators (e.g. Spanner-style Paxos groups) or avoid cross-shard atomicity.
- Backpressure and timeouts: timeout > p99.9 latency; retries with exponential backoff and jitter,
  bounded retry budget (e.g. ≤ 10% extra load) to avoid retry storms.
- Failure detectors: phi-accrual or heartbeat with suspicion timeouts; tune for false-positive
  rate vs detection time.

## 7. CRDTs (strong eventual consistency)

| Type | Merge | Note |
|---|---|---|
| G-Counter | element-wise max | grow only |
| PN-Counter | two G-Counters | increments and decrements |
| LWW-Register | highest timestamp wins | silently drops concurrent writes; needs good clocks |
| MV-Register | keep concurrent values | application resolves |
| OR-Set | add-wins with unique tags | tombstone growth; causal compaction |
| Sequence CRDTs (RGA, Logoot, Fugue) | collaborative text | interleaving anomalies differ by algorithm |

Requirements: merge is commutative, associative, idempotent (a join-semilattice). Test with
randomised operation orders and duplicate deliveries.

## 8. Testing distributed systems

- Deterministic simulation (FoundationDB-style, TigerBeetle VOPR, Antithesis): run the whole
  system in one process with simulated network/disk/clock and injected faults; reproduce from a seed.
- Jepsen-style black-box testing: real nodes, nemesis (partitions, clock skew, process pauses,
  disk faults), history checked by Knossos (linearizability) or Elle (transactional anomalies).
- Model checking the protocol (TLA+), then trace validation: check that implementation logs are
  behaviours of the spec.
- Chaos in staging: kill leaders, partition minority/majority, fill disks, inject latency at the
  99th percentile.
