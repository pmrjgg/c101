---
name: resilience-patterns
description: "Robust remote calls under failure and load: timeout and deadline budgets, retry classification with full-jitter backoff, retry budgets, idempotency keys and dedup, bounded concurrency and backpressure sized by Little's law, rate limiting (token bucket, GCRA), circuit breakers, bulkheads, hedged requests and graceful shutdown, with per-language libraries. Load when code calls networks, queues, databases or third-party APIs, or fans out work."
when_to_use: "Writing or reviewing an HTTP/gRPC/DB/queue client, a retry decorator or loop, asyncio.gather/Promise.all/goroutine fan-out over input-sized lists, webhook or payment handlers, consumers with at-least-once delivery; incidents with retry storms, thundering herds, duplicate charges or emails, pool exhaustion, 'context deadline exceeded', 429 Too Many Requests, or slow shutdowns dropping requests."
---

# Resilience patterns

Every remote call can be slow, fail, or succeed without you hearing about it. This skill turns that
into numbers: deadlines, attempts, jitter windows, pool sizes, breaker thresholds. Distributed-systems
theory (consensus, delivery guarantees) lives in `cs-foundations`; latency profiling in
`performance-optimization`; test design in `testing-strategy`. Transactional outbox and saga design
choices belong to the `architect` agent.

Deep material: [library snippets per language](references/library-snippets.md) |
[worked example: payment client, outage simulation and toxiproxy runbook](references/payment-client-example.md)

## 1. Timeouts first

No timeout means a hung dependency holds your thread, connection and memory forever. Every network call
gets a connect timeout and an overall timeout, and the request carries one deadline end to end.

| Rule | Value |
|---|---|
| Connect timeout | 0.5-2 s (LAN: 100-500 ms) |
| Per-try timeout | `min(1.5 x dependency p99.9, remaining_deadline - margin)` |
| Margin per hop | 10-50 ms for your own work after the call returns |
| Deadline source | set once at the edge from the user-facing SLO, propagated, never extended downstream |
| Propagation | gRPC deadlines (`grpc-timeout`), Go `context.WithTimeout`, JS `AbortSignal.timeout(ms)` combined with `AbortSignal.any([...])`, Python `asyncio.timeout()` / `asyncio.timeout_at()`, Kotlin `withTimeout`, HTTP: a deadline header your services agree on |
| Expired on arrival | reject immediately (504 / DEADLINE_EXCEEDED) without doing work |

Budget for a 3-hop chain with an 800 ms edge deadline (p99.9 measured per callee):

| Hop | Callee p99.9 | Remaining at call | Per-try timeout | Attempts |
|---|---|---|---|---|
| edge -> orders | 400 ms | 800 ms | min(600, 780) = 600 ms | 1 |
| orders -> payments | 300 ms | 600 - 30 (own work) = 570 ms | min(450, 550) = 450 ms | 1 |
| payments -> bank API | 120 ms | 450 - 10 = 440 ms | min(180, 420) = 180 ms | 2: second try gets min(180, remaining - 20) |

Worst case inside payments: 10 (own work) + 180 + 100 (max jitter) + 140 = 430 ms, inside its 450 ms
budget with the 20 ms margin left. Retries happen only at the bottom hop (section 4); the upper hops
would otherwise multiply them.

## 2. What to retry

| Outcome | Retry? | Condition |
|---|---|---|
| Connect refused / DNS failure / connect timeout (request never sent) | yes | any method |
| Timeout or connection reset after the request was sent | only if idempotent | GET/PUT/DELETE, or a POST with an idempotency key |
| HTTP 502, 503, 504 | yes | idempotent or keyed |
| HTTP 429 | yes, after `Retry-After` | if `Retry-After` exceeds the remaining deadline, fail now |
| HTTP 408 | yes | idempotent or keyed |
| HTTP 500 | no by default | the server failed deterministically more often than not |
| HTTP 400, 401, 403, 404, 409, 422 | **never** | retrying cannot change the answer (refresh credentials once on 401, then stop) |
| gRPC UNAVAILABLE | yes | |
| gRPC DEADLINE_EXCEEDED | no at this layer | the budget is spent; the caller decides |
| gRPC RESOURCE_EXHAUSTED | only with server pushback / backoff | |
| gRPC ABORTED, DB serialization failure (SQLSTATE 40001), deadlock (40P01) | yes, the **whole transaction** | |
| DB unique violation (23505), check violation | never | |

Attempts: 3-4 total at most. The client's own bugs (serialization errors, `TypeError`) are never retried.

## 3. Backoff

| Strategy | Sleep before retry `n` (n = 0, 1, ...) | Use |
|---|---|---|
| Full jitter (default) | `random(0, min(cap, base * 2**n))` | contention and overload: spreads clients uniformly |
| Equal jitter | `t = min(cap, base * 2**n); t/2 + random(0, t/2)` | when a minimum wait is required |
| Decorrelated jitter | `min(cap, random(base, prev_sleep * 3))` | alternative to full jitter; cockatiel's default |
| Fixed or un-jittered exponential | `base * 2**n` | never for shared resources |

Defaults: `base` 100 ms, `cap` 10-20 s for background work; inside a request, the cap is whatever the
remaining deadline allows. Windows with base 100 ms: [0, 100), [0, 200), [0, 400), [0, 800) ms.

Why jitter: after an outage every client failed at the same moment; un-jittered backoff makes them
retry at the same moments too, so the recovering service sees synchronized spikes (thundering herd)
and falls over again. Full jitter turns the spike into a uniform spread over the window.

## 4. Retry amplification and budgets

- Retry at **one** layer, the one closest to the failing dependency. 3 layers x 3 attempts = 3^3 =
  27 requests at the bottom for one user action, exactly when the bottom is already failing.
- Retry budget: retries may add at most 10-20 % load. Token bucket form (gRPC `retryThrottling`
  `{"maxTokens": 10, "tokenRatio": 0.1}`): each failure costs 1 token, each success earns 0.1, and
  retries stop while tokens <= maxTokens / 2. Sustained failure above roughly 1 per 10 successes
  drains it, so retries switch off during real outages and stay on for blips.
- No retries while the circuit is open (section 8); an open breaker means "stop sending".
- Log and count attempts as a metric (`attempt` label): retries hide failures from dashboards.

## 5. Idempotency

| Piece | Rule |
|---|---|
| Key | generated by the client per business operation (`charge-{order_id}` or a UUID stored with the order), identical on every retry, sent as `Idempotency-Key` |
| Server dedup table | `(key PRIMARY KEY, request_hash, status, response_code, response_body, created_at, expires_at)`; the unique constraint is the lock |
| Same key, different body | reject (422); it is a client bug |
| Same key, still in progress | 409, client retries later |
| Same key, done | replay the stored response, do not re-execute |
| Expiry | longer than the longest client retry horizon; Stripe prunes keys after at least 24 h |

```sql
INSERT INTO idempotency_keys (key, request_hash, status, expires_at)
VALUES ($1, $2, 'in_progress', now() + interval '48 hours')
ON CONFLICT (key) DO NOTHING
RETURNING key;            -- no row returned: someone already owns this key, read it and branch
```

Write the side effect and the stored response in the same database transaction when possible.

At-least-once consumers (queues, webhooks, CDC): insert the message id into `processed_messages`
(primary key) in the same transaction as the side effect, or make the write an idempotent upsert
(`INSERT ... ON CONFLICT (id) DO UPDATE ... WHERE t.version < excluded.version`). "Write to the DB, then
publish" without an outbox loses or duplicates messages on crash; the transactional-outbox design is
the `architect` agent's call.

## 6. Bounded concurrency and backpressure

Little's law: in-flight requests `L = lambda x W` (arrival rate x time in system).

| Quantity | Formula | Example |
|---|---|---|
| Pool / semaphore size | `rate x latency x 1.2-1.5` | 200 rps x 0.060 s x 1.3 = 15.6 -> 16 |
| Degraded latency | `W = (1-p) x normal + p x timeout` | 10 % of calls hit a 0.5 s timeout: W = 0.104 s, L = 20.8 > 16 |
| Queue wait budget | `queue_len / service_rate` must fit inside the deadline | 64 queued / 200 per s = 320 ms |

When degraded `L` exceeds the pool, requests wait or are rejected; size for the degraded case, cut the
per-try timeout, or shed (the section 13 simulation shows exactly this).

- Bound every fan-out over input-sized collections: no bare `asyncio.gather(*(f(x) for x in items))`,
  `Promise.all(items.map(f))`, or `go f(x)` per item. Use `asyncio.Semaphore` / `TaskGroup` with a
  limit, `p-limit`, `errgroup.Group.SetLimit(n)`, a worker pool.
- Every queue is bounded and has an explicit overflow policy: **block** (backpressure to a caller that
  can wait), **reject** (429/503 with `Retry-After`), or **drop oldest** (telemetry, latest-value
  streams). Drop items whose deadline already passed before starting them.
- Priority load shedding: tag requests (critical / default / batch) and shed from the bottom when
  in-flight or queue delay crosses a threshold; health checks and control traffic are never shed.

## 7. Rate limiting

| Algorithm | State | Rule | Use |
|---|---|---|---|
| Token bucket | tokens, last refill | refill `r`/s up to burst `b`; a request takes 1 token; empty-to-full takes `b / r` | client-side quota pacing, per-tenant limits |
| GCRA | one timestamp (TAT) per key | `T = 1/r`, `tau = (b - 1) x T`; `tat = max(TAT, now)`; allow if `tat - now <= tau`, then `TAT = tat + T`; else retry after `tat - tau - now` | distributed limits in Redis (one atomic Lua script or the redis-cell module) |
| Sliding-window counter | two counters | `prev x (1 - elapsed/window) + curr <= limit` | public APIs, cheap and smooth enough |
| Fixed window | one counter | resets each window | avoid: 2x burst at window edges |

Example: provider quota 50 req/s with bursts of 100: token bucket `r = 50, b = 100`, full refill 2 s;
GCRA `T = 20 ms`, `tau = 99 x 20 ms = 1.98 s`. Client side, pace below the provider's limit
(`aiolimiter.AsyncLimiter(45, 1)`, `rate.NewLimiter(45, 90)` with `Wait(ctx)`) and still honour 429 and
`Retry-After`, because other clients share the quota.

## 8. Circuit breakers and bulkheads

| Setting | Starting value | Note |
|---|---|---|
| Failure-rate threshold | 50 % | count timeouts and 5xx; never 4xx caused by the caller |
| Sliding window | last 20-100 calls, or 10-60 s | |
| Minimum calls before evaluating | 20 | avoids opening on 1 of 2 failures |
| Slow-call threshold | calls slower than the per-try timeout's 80 % count as failures | resilience4j `slowCallDurationThreshold` |
| Open duration | 30 s (5-60 s) | fail fast with a typed error, no network call |
| Half-open probes | 3-10 calls; close on success, reopen on failure | |

Library defaults differ wildly (resilience4j: 50 %, window 100, minimum 100 calls, 60 s open,
10 half-open calls; Polly v8: failure ratio 0.1, minimum throughput 100, 30 s sampling, 5 s break), so
always set every value explicitly. A breaker needs a fallback decision per call site: cached value,
degraded response, queue for later, or a clear error.

Bulkheads: one pool per dependency (HTTP connection pool, semaphore, thread pool) so a slow
dependency exhausts only its own slots. Size each with section 6; reject (do not queue unboundedly)
when full.

## 9. Tail latency and shutdown

Hedged requests: when an idempotent read has not answered by the p95 latency, send a second copy to
another replica, take the first answer and cancel the other. Cost is about 5 % extra load; it cuts p99
sharply when slowness is per-replica (Dean and Barroso, "The Tail at Scale"). Never hedge writes. gRPC
has it built in (`hedgingPolicy` with `maxAttempts`, `hedgingDelay`, `nonFatalStatusCodes`).

Graceful shutdown on SIGTERM:

1. Fail the readiness probe so endpoints stop routing new traffic.
2. Keep serving while removal propagates: Kubernetes `lifecycle.preStop` sleep 5-10 s (`sleep` action
   beta since 1.30, stable 1.34; otherwise `exec: {command: ["sleep", "5"]}`).
3. Stop accepting new connections; let in-flight requests finish (Go `http.Server.Shutdown(ctx)`, Node
   `server.close()` plus `server.closeIdleConnections()`).
4. Drain within `terminationGracePeriodSeconds` (default 30 s) minus the preStop sleep; consumers stop
   fetching and finish or nack the current message.
5. Close pools, flush telemetry, exit 0. SIGKILL arrives when the grace period ends.

## 10. Library map

| Language | Retry / backoff | Concurrency, rate | Breaker / bulkhead / timeout |
|---|---|---|---|
| Python | `tenacity` (`wait_random_exponential` is full jitter), `stamina` (opinionated; `on=` hook may return a delay, e.g. from `Retry-After`) | `asyncio.Semaphore`, `asyncio.TaskGroup`, `aiolimiter.AsyncLimiter(max_rate, time_period)` | `asyncio.timeout`; small breakers are often hand-written (see the example) |
| TypeScript | `p-retry` (jitter off by default; set `randomize: true`), cockatiel `retry` | `p-limit`, cockatiel `bulkhead(limit, queue)` | cockatiel `circuitBreaker`, `timeout`, `wrap`; `AbortSignal.timeout` |
| Go | failsafe-go `retrypolicy` (`WithBackoff`, `WithJitterFactor`, `WithMaxAttempts`) | `errgroup.Group.SetLimit`, `golang.org/x/time/rate` | failsafe-go `circuitbreaker`, `timeout`, `bulkhead`; `context.WithTimeout` |
| JVM | resilience4j `Retry`, Failsafe | resilience4j `Bulkhead`, `RateLimiter` | resilience4j `CircuitBreaker`, `TimeLimiter`; Kotlin `withTimeout` |
| Rust | `backon` (`ExponentialBuilder::default().with_jitter()`), tower `retry` | tower `concurrency_limit`, `rate_limit`, `load_shed`, `buffer` | tower `timeout`; `tokio::time::timeout` |
| .NET | Polly v8 `ResiliencePipelineBuilder().AddRetry(...)` | `AddConcurrencyLimiter`, `System.Threading.RateLimiting` | `AddCircuitBreaker`, `AddTimeout`; `AddStandardResilienceHandler()` for HttpClient |

Snippets for each in [library snippets](references/library-snippets.md).

## 11. Testing resilience

- Fault injection: toxiproxy between the service and the dependency (`latency`, `timeout`,
  `reset_peer`, `bandwidth`, `slicer`, `limit_data`, and disabling the proxy for a hard outage), or a fake
  transport in unit tests (`httpx.MockTransport`, `httptest.Server`, `nock`, WireMock).
- Fake clocks for backoff schedules: inject `sleep` and `random` (or `stamina.set_testing(True)`) and
  assert the exact sequence of waits; no real sleeping in unit tests.
- Assert attempt counts (exactly 3 on 503, exactly 1 on 400) and the **absence of duplicate side
  effects**: count server-side executions per idempotency key.
- Deadline tests: a dependency that hangs forever must produce an error within deadline + 50 ms.
- Chaos under load before launch: kill a dependency for 30 s at expected peak rps and check p99, error
  rate, recovery time and duplicates. Detail of test levels: `testing-strategy`.

## 12. Pitfalls

- Retrying non-idempotent POSTs without a key: duplicate charges, emails, orders.
- Generating the idempotency key per attempt (inside the retry loop) instead of per operation.
- Timeouts at every layer equal to each other (30 s everywhere): the caller times out while the callee
  keeps working, and retries pile on top.
- Library timeouts that do not cover everything: `requests` has no total timeout, only connect/read;
  some mock transports ignore timeouts entirely. Wrap with `asyncio.timeout` or a context deadline.
- Retry inside a loop that already retries (SDK default retries + your decorator + service-mesh retries).
- Catching `Exception` in the retry predicate, so programming errors are retried three times.
- Unbounded in-memory queues: latency grows until OOM; the queue hides overload instead of shedding it.
- Breaker counting caller errors (400/404) as failures and opening on bad input.
- Health checks that call dependencies: one slow database restarts every pod.
- Shutdown that exits on SIGTERM immediately: in-flight requests get connection resets.

## 13. Worked example: payment-provider client

Requirements: charges at 200 rps; provider latency 60 ms (p99.9 about 300 ms); each order is charged
at most once; callers need an answer within 2 s.

| Decision | Value | Derivation |
|---|---|---|
| Overall deadline | 2 s | caller SLO |
| Per-try timeout | 0.5 s | ~1.5 x provider p99.9, and 3 tries + jitter fit in 2 s |
| Attempts | 3, full jitter, window `min(1 s, 0.1 s x 2**n)` | retry only 503, timeouts, connect errors |
| Idempotency | `Idempotency-Key: charge-{order_id}` on every attempt | derived from the order, not the attempt |
| Breaker | open at >= 50 % failures over the last 20 calls, 10 s open, 3 probes | |
| Bulkhead | 16 slots, wait at most 100 ms for one | 200 x 0.060 x 1.3 = 15.6 |
| Retry budget | +0.1 token per call, 1 token per retry, cap 10 | <= ~10 % extra load |

Core of the client (full code with breaker and budget classes in the
[payment-client example](references/payment-client-example.md)):

```python
async def charge(self, order_id: str, amount_cents: int) -> dict:
    idem_key = f"charge-{order_id}"
    self.budget.on_call()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + DEADLINE_S
    try:
        await asyncio.wait_for(self.bulkhead.acquire(), timeout=0.1)
    except TimeoutError:
        raise ProviderUnavailable("bulkhead full") from None
    try:
        async with asyncio.timeout_at(deadline):
            for attempt in range(ATTEMPTS):
                if not self.breaker.allow():
                    raise ProviderUnavailable("circuit open")
                per_try = min(PER_TRY_S, deadline - loop.time() - MARGIN_S)
                try:
                    async with asyncio.timeout(per_try):      # enforced even if the transport is not
                        r = await self.http.post("/v1/charges",
                                                 json={"amount": amount_cents, "reference": order_id},
                                                 headers={"Idempotency-Key": idem_key},
                                                 timeout=per_try)
                except (TimeoutError, httpx.TimeoutException, httpx.ConnectError):
                    self.breaker.record(False)
                else:
                    if r.status_code not in RETRYABLE_STATUS:      # {503} for this provider
                        self.breaker.record(r.status_code < 500)
                        r.raise_for_status()                    # 4xx: never retried
                        return r.json()
                    self.breaker.record(False)
                if attempt == ATTEMPTS - 1 or not self.budget.try_spend():
                    break
                await asyncio.sleep(random.uniform(0, min(1.0, 0.1 * 2**attempt)))
    except TimeoutError:
        raise ProviderUnavailable("deadline exceeded") from None
    finally:
        self.bulkhead.release()
    raise ProviderUnavailable("retries exhausted")
```

Simulation run (in-process fake provider, open-loop 200 rps for 40 s: 5 s healthy, 30 s fault,
5 s recovery; numbers from an actual run on Python 3.13, they vary by a few percent between runs):

| Scenario | Upstream calls during fault | p99 during fault | Max latency | Duplicate charges |
|---|---|---|---|---|
| Hard outage (50 % 503, 50 % hang; 10 % of calls processed but response lost) | 24 in 30 s (0.8/s vs 200/s offered): breaker open | 0 ms (fail fast) | 662 ms | 0 |
| Brownout (20 % 503, 10 % processed but response lost), with keys | 4,711 (157/s) | 720 ms | 899 ms | **0** |
| Same brownout, keys removed | 4,627 (154/s) | 732 ms | 1,426 ms | **193** |

Readings: the breaker cut load on the dead provider by 250x, kept latency bounded, and closed again
about 1.7 s after the provider recovered; the keys, not the retry policy, prevent duplicates; and the
brownout produced 1,571 bulkhead rejections because 10 % of calls hold a slot for the full 0.5 s
timeout (degraded Little's law, section 6). Re-runs of the brownout: pool 24 gives 0 rejections and
6,604 successes instead of 5,338, with upstream load at 217/s (the retry budget held the extra load to
about 9 %); `PER_TRY_S = 0.3` instead cuts rejections from 1,571 to 240.

Production rehearsal with toxiproxy (commands in the reference): proxy the provider sandbox, run 200 rps,
add a `timeout` toxic (`timeout=0`, connection hangs) for 30 s, remove it, then assert: zero duplicate
charges in the sandbox per order reference, p99 <= 2 s throughout, breaker closed again within open
duration + probe time after recovery.

Related: `zero-downtime-migrations`, `regex-engineering`, `dependency-upgrades`,
`docs-and-adr-writing`, `cs-foundations`, `performance-optimization`, `testing-strategy`,
hub `coding-general`.
