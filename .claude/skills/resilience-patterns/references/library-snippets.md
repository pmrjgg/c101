# Library snippets per language

Companion to `resilience-patterns` section 10. Each snippet encodes the same policy: retry only
transient failures, at most 3 attempts with jittered exponential backoff, an overall deadline, bounded
concurrency. API names were checked against current docs or source (tenacity 9.2, stamina 26.1,
aiolimiter 1.3, cockatiel, p-retry, failsafe-go, resilience4j, Polly v8, tower, backon); pin versions and
re-check before copying into an old codebase.

## Python

```python
# tenacity: wait_random_exponential is AWS "full jitter": random(0, min(max, multiplier * 2**n))
import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, stop_after_delay, wait_random_exponential

def transient(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (502, 503, 504)
    return isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout))

@retry(stop=stop_after_attempt(3) | stop_after_delay(2),
       wait=wait_random_exponential(multiplier=0.1, max=1),
       retry=retry_if_exception(transient), reraise=True)
def get_rates() -> dict:
    r = httpx.get("https://rates.example/v1", timeout=httpx.Timeout(0.5, connect=0.2))
    r.raise_for_status()
    return r.json()
```

```python
# stamina: bounded by attempts and total time; jitter is additive (wait_jitter), not full jitter.
# Since 25.2 the `on` hook may return a float/timedelta to dictate the wait (Retry-After).
import stamina

def retry_on(exc: Exception) -> bool | float:
    if isinstance(exc, httpx.HTTPStatusError):
        ra = exc.response.headers.get("Retry-After")
        if exc.response.status_code == 429 and ra and ra.isdigit():
            return float(ra)                     # seconds form only; HTTP-date form: parse it
        return exc.response.status_code in (502, 503, 504)
    return isinstance(exc, httpx.TransportError)

@stamina.retry(on=retry_on, attempts=3, timeout=2.0)
async def fetch(client: httpx.AsyncClient, url: str) -> bytes:
    r = await client.get(url)
    r.raise_for_status()
    return r.content

# tests: stamina.set_testing(True, attempts=3) disables backoff sleeps
```

```python
# bounded fan-out + client-side rate limit
import asyncio
from aiolimiter import AsyncLimiter

limiter = AsyncLimiter(45, 1)         # 45 requests per 1 s, below the provider's 50/s
sem = asyncio.Semaphore(16)

async def one(client, item):
    async with sem, limiter:
        return await fetch(client, item.url)

async def all_items(client, items):
    async with asyncio.timeout(30):                       # whole batch deadline
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(one(client, it)) for it in items]
    return [t.result() for t in tasks]
```

For millions of items, replace the task-per-item list with N workers reading a bounded
`asyncio.Queue(maxsize=1000)` so memory stays flat.

## TypeScript / Node

```ts
import pLimit from "p-limit";
import pRetry, { AbortError } from "p-retry";

const limit = pLimit(16);

async function getJson(url: string, outer: AbortSignal): Promise<unknown> {
  return pRetry(async () => {
    const signal = AbortSignal.any([outer, AbortSignal.timeout(500)]);   // per-try 500 ms + caller's deadline
    const res = await fetch(url, { signal });
    if ([400, 401, 403, 404, 409, 422].includes(res.status)) throw new AbortError(res.statusText);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }, { retries: 2, minTimeout: 100, maxTimeout: 1000, randomize: true, signal: outer });
}

const deadline = AbortSignal.timeout(2000);
const results = await Promise.all(urls.map((u) => limit(() => getJson(u, deadline))));
```

`p-retry` jitter is off by default (`randomize: false`) and, when on, multiplies by 1-2 rather than
full jitter; `retries` counts retries, not attempts.

```ts
import { retry, circuitBreaker, timeout, bulkhead, wrap, handleWhen, ExponentialBackoff,
         SamplingBreaker, TimeoutStrategy } from "cockatiel";

const transient = handleWhen((e) => e instanceof TransientError);
const policy = wrap(
  bulkhead(16, 32),                                               // 16 in flight, 32 queued
  circuitBreaker(transient, { halfOpenAfter: 30_000,
    breaker: new SamplingBreaker({ threshold: 0.5, duration: 30_000, minimumRps: 5 }) }),
  retry(transient, { maxAttempts: 2, backoff: new ExponentialBackoff({ initialDelay: 100, maxDelay: 1000 }) }),
  timeout(500, TimeoutStrategy.Aggressive),
);
const data = await policy.execute(({ signal }) => callProvider(signal));
```

`ExponentialBackoff` defaults to decorrelated jitter; `wrap` applies policies outermost first.

## Go

```go
// bounded fan-out
g, ctx := errgroup.WithContext(ctx)
g.SetLimit(16)
for _, it := range items { // Go 1.22+: it is per-iteration
	g.Go(func() error { return process(ctx, it) })
}
if err := g.Wait(); err != nil { return err }

// client-side rate limit: 45/s, burst 90
lim := rate.NewLimiter(rate.Limit(45), 90)
if err := lim.Wait(ctx); err != nil { return err } // respects ctx deadline

// deadline propagation
ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
defer cancel()
req, _ := http.NewRequestWithContext(ctx, http.MethodPost, url, body)
```

```go
// failsafe-go: retry inside breaker inside timeout (failsafe.With lists outermost first)
rp := retrypolicy.NewBuilder[*http.Response]().
	HandleErrors(ErrTransient).
	WithBackoff(100*time.Millisecond, time.Second).
	WithJitterFactor(.5).
	WithMaxAttempts(3).
	AbortOnErrors(context.Canceled).
	Build()
cb := circuitbreaker.NewBuilder[*http.Response]().
	HandleErrors(ErrTransient).
	WithFailureRateThreshold(.5, 20, time.Minute). // rate as a fraction, min executions, period
	WithDelay(30 * time.Second).
	WithSuccessThreshold(3).
	Build()
to := timeout.New[*http.Response](500 * time.Millisecond)
resp, err := failsafe.With(rp, cb, to).Get(func() (*http.Response, error) { return call(ctx) })
```

## JVM (Java / Kotlin)

```java
CircuitBreaker cb = CircuitBreaker.of("psp", CircuitBreakerConfig.custom()
    .failureRateThreshold(50)
    .slidingWindowType(CircuitBreakerConfig.SlidingWindowType.COUNT_BASED)
    .slidingWindowSize(20)
    .minimumNumberOfCalls(20)
    .slowCallDurationThreshold(Duration.ofMillis(400))
    .waitDurationInOpenState(Duration.ofSeconds(30))
    .permittedNumberOfCallsInHalfOpenState(3)
    .build());

Retry retry = Retry.of("psp", RetryConfig.custom()
    .maxAttempts(3)                                                     // includes the first call
    .intervalFunction(IntervalFunction.ofExponentialRandomBackoff(Duration.ofMillis(100), 2.0, 0.5))
    .retryOnException(e -> e instanceof IOException)
    .build());

Supplier<Charge> guarded = Retry.decorateSupplier(retry,
    CircuitBreaker.decorateSupplier(cb, () -> provider.charge(req)));
```

resilience4j defaults (failure rate 50 %, window 100, minimum 100 calls, 60 s open, 10 half-open calls,
retry 3 attempts with 500 ms fixed wait) are rarely right; set them explicitly. Kotlin coroutines:
`withTimeout(2.seconds) { client.charge(req) }` cancels the coroutine; `withTimeoutOrNull` returns null.

## Rust

```rust
use std::time::Duration;
use backon::{ExponentialBuilder, Retryable};
use tower::ServiceBuilder;

// retry with jitter (backon defaults: factor 2, min 1 s, max 60 s, 3 times, no jitter)
let body = (|| async { fetch(&client, &url).await })
    .retry(ExponentialBuilder::default()
        .with_jitter()
        .with_min_delay(Duration::from_millis(100))
        .with_max_delay(Duration::from_secs(1))
        .with_max_times(2))
    .when(|e: &reqwest::Error| e.is_timeout() || e.is_connect())
    .await?;

// tower middleware stack around a Service (features: limit, timeout, load-shed)
let svc = ServiceBuilder::new()
    .load_shed()                       // reject immediately when the inner service is not ready
    .concurrency_limit(16)
    .rate_limit(45, Duration::from_secs(1))
    .timeout(Duration::from_millis(500))
    .service(inner);
```

## .NET (Polly v8)

```csharp
var pipeline = new ResiliencePipelineBuilder<HttpResponseMessage>()
    .AddTimeout(TimeSpan.FromSeconds(2))                                  // outer: whole call
    .AddRetry(new RetryStrategyOptions<HttpResponseMessage>
    {
        MaxRetryAttempts = 2,                                             // retries after the first call
        BackoffType = DelayBackoffType.Exponential,
        UseJitter = true,                                                 // decorrelated jitter for exponential
        Delay = TimeSpan.FromMilliseconds(100),
        MaxDelay = TimeSpan.FromSeconds(1),
        ShouldHandle = new PredicateBuilder<HttpResponseMessage>()
            .Handle<HttpRequestException>()
            .HandleResult(r => r.StatusCode == HttpStatusCode.ServiceUnavailable),
    })
    .AddCircuitBreaker(new CircuitBreakerStrategyOptions<HttpResponseMessage>
    {
        FailureRatio = 0.5, MinimumThroughput = 20,
        SamplingDuration = TimeSpan.FromSeconds(30), BreakDuration = TimeSpan.FromSeconds(30),
    })
    .AddTimeout(TimeSpan.FromMilliseconds(500))                           // inner: per try
    .Build();
```

Polly defaults (retry: 3 retries, constant 2 s, no jitter; breaker: failure ratio 0.1, minimum
throughput 100, 30 s sampling, 5 s break) differ from resilience4j; set them explicitly. For
`HttpClient`, `Microsoft.Extensions.Http.Resilience` provides `AddStandardResilienceHandler()` with a
preconfigured rate limiter, total timeout, retry, breaker and per-attempt timeout.
