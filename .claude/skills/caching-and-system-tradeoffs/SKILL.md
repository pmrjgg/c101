---
name: caching-and-system-tradeoffs
description: "Caching and systems-design trade-offs backed by numbers: cache patterns, eviction (LRU, LFU, ARC, W-TinyLFU, SIEVE, S3-FIFO), hit-ratio math and miss-ratio curves, TTL and invalidation, stampede protection, cache consistency races, partitioning (consistent, rendezvous, jump, Maglev hashing), fan-out tail latency, queueing and utilisation, and ADRs. Load when adding or debugging a cache or justifying a design trade-off quantitatively."
when_to_use: "Adding Redis/Valkey/Memcached, Caffeine, moka, a CDN rule or an in-process memo cache; a low or falling hit ratio; latency or DB load spikes at TTL expiry or after a deploy or flush (stampede); stale data after writes; choosing an eviction policy or cache size; hot keys or resharding; capacity estimates (QPS, bandwidth, Little's law, utilisation); an ADR trading latency, consistency and cost."
---

# Caching and system trade-offs

Quantitative design: state the workload, compute, then choose. Latency constants and benchmarking
method live in `performance-optimization`; timeouts, retries with jitter, breakers and rate limits in
`resilience-patterns`; replication guarantees in `distributed-consensus-consistency`; database-side
concurrency in `database-transactions-isolation`; ADR format in `docs-and-adr-writing`.

## 1. Frame the trade-off

- Axes: latency (p50 and p99), throughput, consistency (maximum staleness), cost, durability,
  availability, operability (failure modes, on-call load).
- Workload: read/write ratio, number of keys N, popularity skew (fit Zipf s from the log-log
  rank-frequency slope of an access log), object size distribution, peak QPS, update rate, and the
  staleness each endpoint tolerates.
- SLOs the design must meet, per endpoint.
- Write every decision as "accept X to gain Y, measured by Z", and note whether it is reversible and
  at what cost.

## 2. Back-of-envelope procedure

| Quantity | Formula | Example |
|---|---|---|
| Bandwidth | QPS x object size | 20k/s x 4 KB = 80 MB/s, about 640 Mbit/s |
| Working set | distinct keys per window x size | 200k x 4 KB = 0.8 GB |
| Concurrency (Little's law) | L = lambda x W | 20k/s x 50 ms = 1,000 requests in flight |
| Queueing (M/M/1) | W = S / (1 - rho), rho = lambda / mu | rho 0.5: 2S; 0.7: 3.3S; 0.8: 5S; 0.9: 10S; 0.95: 20S |
| Fan-out tail | P(some call slow) = 1 - p^n | 100 calls at p99: 1 - 0.99^100 = 63% of requests |
| Hedged requests | extra load = share of calls slower than the hedge delay | hedge at p95: at most about 5% extra |

Keep latency-sensitive services at 70-80% utilisation: past the knee, waiting time explodes.
M/M/1 is optimistic for variable service times; M/G/1 multiplies queueing delay by (1 + C^2)/2,
where C is the service time's coefficient of variation.

## 3. Cache patterns and tiers

| Pattern | Read | Write | Consistency risk |
|---|---|---|---|
| Cache-aside | read cache; on miss load the DB and fill | write DB, then delete the key | the fill race (section 8); stale until TTL if a delete is lost |
| Read-through | the cache's loader fills on miss | as cache-aside | same; central place for stampede control |
| Write-through | read cache | write cache and DB synchronously | slower writes; a failed dual write leaves them diverged |
| Write-behind | read cache | write cache, flush the DB later | loss on cache failure; reordered writes |
| Refresh-ahead | read cache | background refresh before expiry | DB load spent on keys nobody reads again |

Tiers, nearest first: in-process near cache (Caffeine, moka, Ristretto: nanoseconds to
microseconds, duplicated per instance, invalidation must fan out); remote cache (Valkey/Redis,
Memcached: sub-millisecond in-zone); CDN and HTTP caches (`Cache-Control: max-age, s-maxage,
stale-while-revalidate, stale-if-error`, `ETag` with `If-None-Match`); the database buffer pool.
Never cache authorisation decisions without an invalidation path (revoked access lingers), per-user
data under shared keys, responses carrying `Set-Cookie` at a CDN, or one-time tokens.

## 4. Eviction policies

| Policy | Idea | Good at | Weak at | Implementations |
|---|---|---|---|---|
| LRU | evict least recently used | recency | scans pollute it | most libraries; Memcached (segmented LRU) |
| CLOCK | LRU approximation with a reference bit | cheap, concurrent | same as LRU | OS page caches, PostgreSQL clock sweep |
| LFU | evict least frequently used | stable skew | stale popularity | Redis `allkeys-lfu` (decaying counters) |
| ARC | balances recency and frequency lists using ghost entries | scan resistance, self-tuning | complexity | ZFS |
| LIRS | inter-reference recency | scan resistance | complexity | some DB and OS caches |
| W-TinyLFU | small LRU window, frequency-sketch admission, segmented LRU main | skewed web and KV workloads | sketch sizing | Caffeine, moka, Ristretto (TinyLFU admission) |
| SIEVE (2024) | FIFO with a visited bit and a moving hand | simple, high hit ratio on web traces | newer, fewer libraries | ports in many languages |
| S3-FIFO (2023) | small FIFO + main FIFO + ghost FIFO, quick demotion | scalable (no locking on hit), web and KV traces | newer | libCacheSim and ports |
| Redis/Valkey approximate LRU/LFU | evict the best of `maxmemory-samples` (default 5) random keys | no per-key list overhead | approximate | Redis, Valkey |

Choose by scan resistance (batch jobs and crawlers: W-TinyLFU, ARC, S3-FIFO), frequency skew
(TinyLFU family), and concurrency and simplicity (SIEVE, S3-FIFO, CLOCK). Replay a real trace in
libCacheSim at 3-4 sizes before deciding. Redis and Valkey default to `maxmemory-policy noeviction`:
when full, writes fail. Set `maxmemory` and an `allkeys-*` policy for a pure cache.

## 5. Hit ratio and sizing math

- Effective latency = h x t_hit + (1 - h) x t_miss. Backend load = (1 - h) x QPS, so going from 99%
  to 99.9% cuts backend load 10x. Required h = 1 - backend budget / QPS.
- Expiry misses: a key read at rate lambda_i with TTL T misses about lambda_i / (1 + lambda_i T)
  times per second, so expiry alone costs up to N_live / T misses per second, whatever the cache
  size. TTL is a load knob.
- Zipf with s near 1: an ideal frequency-based cache holding the top C of N keys hits about
  H(C) / H(N), where H(n) is about ln n + 0.577.
- Che approximation for LRU under independent requests: solve sum_i (1 - exp(-lambda_i T_C)) = C for
  the characteristic time T_C; key i hits with probability 1 - exp(-lambda_i T_C).
- Miss-ratio curves from traces: SHARDS samples keys by hash (keep k when hash(k) mod P < R x P),
  computes reuse distances on the sample and scales cache sizes by 1/R; about 1% sampling is
  usually enough to see the knee.
- Measure byte hit ratio (bandwidth) and cost-weighted hit ratio (expensive misses weigh more),
  per endpoint and tenant, not only one global request hit ratio.

## 6. TTL and invalidation

- Jitter every TTL by +/-10-20% (`ttl * (1 + j * (2 * rand() - 1))`) so keys filled together do not
  expire together.
- CDC-driven invalidation: Debezium (PostgreSQL logical decoding, MySQL binlog) to Kafka to a
  consumer that deletes keys or writes versioned tombstones (section 8). Monitor consumer lag; it is
  your staleness bound.
- Versioned or generation keys: `product:{id}:v{row_version}`, or a namespace generation counter
  embedded in keys (`catalog:g{gen}:...`) bumped to invalidate a whole namespace.
- Negative caching: cache "not found" for 30-60 s to stop miss storms on absent keys; never forever.
- Key design: tenant, schema or serialiser version, locale and currency, normalised parameters
  (sorted, canonical case); bounded cardinality (no raw user input or timestamps in keys).

## 7. Stampede protection

```go
var group singleflight.Group // golang.org/x/sync/singleflight: one load per key per instance

func Product(ctx context.Context, id string) (any, error) {
	if p, ok := near.Get(id); ok {
		return p, nil
	}
	v, err, _ := group.Do(id, func() (any, error) {
		if p, err := valkeyGet(ctx, id); err == nil {
			return p, nil
		}
		p, err := db.LoadProduct(ctx, id)
		if err == nil {
			valkeySet(ctx, id, p, jitter(5*time.Minute, 0.15))
		}
		return p, err
	})
	return v, err
}
```

```python
def fetch(key, recompute, ttl, beta=1.0):          # XFetch: probabilistic early recomputation
    hit = cache.get(key)                           # (value, delta, expiry) or None
    if hit is None or time.time() - hit[1] * beta * math.log(1.0 - random.random()) >= hit[2]:
        start = time.time()
        value = recompute(key)
        delta = time.time() - start                # recompute cost drives how early to refresh
        cache.set(key, (value, delta, time.time() + ttl), ttl)
        return value
    return hit[0]
```

Also: Caffeine `AsyncLoadingCache` and moka `get_with` coalesce concurrent loads per key;
stale-while-revalidate (HTTP, or soft and hard TTLs in the app) serves the old value while one
refresh runs; memcache-style leases give the filler a token and make other readers wait or take
stale data; after a deploy or flush, pre-warm the top-K keys from access logs and ramp traffic.

## 8. Cache consistency races

```text
reader R                               writer W
GET k            -> miss
SELECT row       -> v1
                                       UPDATE row = v2; COMMIT
                                       DEL k
SET k = v1       -> stale until the TTL expires
```

| Fix | How | Residual risk |
|---|---|---|
| Leases (memcache) | a miss issues a token; `DEL` invalidates it; a `SET` with a stale token is dropped | needs cache support |
| Versioned compare-and-set | values carry the row version (or LSN); `SET` only if newer; invalidation writes a tombstone with the new version instead of deleting | needs a monotonic version |
| Delete after commit, delayed second delete | `DEL` right after commit and again after the maximum read-path latency | narrows the window only |
| TTL safety net | every key expires | bounds how long staleness lasts |

Versioned set as a Valkey/Redis script (`KEYS[1]` key, `ARGV` version, payload, TTL in ms; a
tombstone is the same call with an empty payload):

```lua
local cur = redis.call('HGET', KEYS[1], 'v')
if cur and tonumber(cur) >= tonumber(ARGV[1]) then return 0 end
redis.call('HSET', KEYS[1], 'v', ARGV[1], 'p', ARGV[2])
redis.call('PEXPIRE', KEYS[1], ARGV[3])
return 1
```

Read-your-writes for the writer: write the new value through (with its version), or bypass the
cache for that session for a few seconds.

## 9. Partitioning and hot keys

- Mod-N: changing the server count moves about (N-1)/N of keys (adding one server to N moves
  N/(N+1)): a full cold start.
- Consistent hashing: adding a server moves about 1/(N+1) of keys; with V virtual nodes per server
  the load spread is about 1/sqrt(V) (100 vnodes about 10%, 200 about 7%).
- Rendezvous (HRW): pick argmax over servers of hash(server, key); O(N) per lookup, minimal movement,
  easy weights.
- Jump consistent hash: O(ln N), no memory, even load, but servers can only be added or removed at
  the end of the numbering (map logical shards to physical servers):

```go
func Jump(key uint64, buckets int32) int32 { // Lamping and Veach
	var b, j int64 = -1, 0
	for j < int64(buckets) {
		b = j
		key = key*2862933555777941757 + 1
		j = int64(float64(b+1) * (float64(int64(1)<<31) / float64((key>>33)+1)))
	}
	return int32(b)
}
```

- Maglev: a precomputed lookup table (prime size much larger than N, e.g. 65537) filled from
  per-backend permutations; O(1) lookups, near-even load, small disruption; built for load balancers.
- Hot keys: find them by sampling or top-k sketches (`redis-cli --hotkeys` needs an LFU policy);
  mitigate with a near cache, key splitting (`k#0..k#(n-1)`: read one random copy, write all), or
  read replicas.

## 10. Cache-specific degradation

- Serve stale on backend errors: keep entries past a soft TTL until a hard TTL (`stale-if-error`).
- Short-TTL negative caching for absent keys.
- Cache tier down: never let all traffic fall through. Cap DB admissions at its budget (per-instance
  concurrency limit = budget / instances), serve near-cache or stale entries, shed the rest with a
  fast degraded response. Timeouts and breakers on the cache client: `resilience-patterns`.
- After a flush: bounded refill concurrency (a semaphore around loads) and pre-warming.

## 11. Pitfalls

- Caches without eviction or `maxmemory`; caching errors or nulls forever.
- The cache as the source of truth (write-behind without durability, data only in Redis).
- Unbounded key cardinality from raw parameters; serialisation cost dominating the hit path.
- Cold start after a flush or failover melting the database.
- Hit ratio on the wrong denominator (excluding bypassed requests, or counting near-cache hits twice).
- Correctness that silently relies on the cache (rate limits, locks, dedup) during a cache outage.

## 12. Worked example: product pages at 20k RPS

Inputs: 20k RPS peak; catalogue N = 200k products, about 4 KB each; Zipf s about 1 (fitted from logs);
20 product updates/s; the DB sustains 2k QPS, so the budget at 70% is 1.4k QPS.

1. **Required hit ratio**: misses <= 1.4k / 20k = 7%, so h >= 93%.
2. **Tier 1, in-process W-TinyLFU (Caffeine or moka), 10k items** (about 40 MB per instance, TTL 60 s
   to bound cross-instance staleness): top-10k share is about H(10^4) / H(2x10^5) = 9.79 / 12.78,
   about 77% of requests. Its misses go to Valkey, not the DB.
3. **Tier 2, Valkey cluster holding the whole catalogue** (0.8 GB, plus a replica): no capacity
   misses. TTL 5 min +/-15%. Expiry misses: a = 20k / H(N) = 1565/s; misses = a x ln((N + aT)/(aT))
   with T = 300 s gives about 555/s. CDC invalidations add at most 20/s. DB load is about 575 QPS:
   h is about 97%, below budget. With T = 30 s the same formula gives about 2.6k/s, over budget; the
   break-even TTL is about 90 s. TTL is the load knob.
4. **Stampede and consistency**: singleflight per instance, XFetch or refresh-ahead for the hottest
   keys, Debezium CDC writing versioned tombstones (section 8), jittered TTLs.
5. **Validate**: build a miss-ratio curve from a 1% SHARDS sample of a day's trace and replay it in
   libCacheSim for LRU, W-TinyLFU and S3-FIFO. Under the Zipf fit, 93% needs about 82k items
   (H(C) >= 0.93 x H(N)); the trace, not the fit, decides.
6. **Valkey-down mode**: the near cache still serves about 77%; the remaining 4.6k RPS exceeds the
   1.4k budget, so cap DB loads per instance (1.4k / instances), serve stale near-cache entries past
   their TTL, and shed the rest with a fast degraded page. Test it in a game day.
7. **ADR**: context (numbers above); decision; "accept up to 60 s cross-instance staleness and 5 min
   staleness on missed CDC events to gain a 97% hit ratio and DB load near 0.6k QPS, measured by
   hit-ratio and DB QPS dashboards"; alternatives (read replicas, CDN-only); reversibility (feature
   flag per tier); validation plan (MRC, game day).

Related: `resilience-patterns`, `performance-optimization`, `distributed-consensus-consistency`, `database-transactions-isolation`, `observability-instrumentation`, `docs-and-adr-writing`, hub `cs-foundations`
