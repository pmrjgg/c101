# Worked example: payment-provider client

Full code for `resilience-patterns` section 13: the client (`payclient.py`), the in-process outage
simulation (`sim.py`) whose numbers appear in the skill, and a toxiproxy runbook for the same test
against real infrastructure. Verified with Python 3.13 and httpx; run with
`uv run --with httpx python sim.py [--brownout] [--no-key]` from the directory holding both files.

## `payclient.py`

```python
"""Payment-provider client: deadline, classified retries, idempotency, breaker, bulkhead."""
from __future__ import annotations

import asyncio
import collections
import random
import time

import httpx

RETRYABLE_STATUS = {503}          # this provider: 503 only; never 4xx
DEADLINE_S = 2.0                  # whole call, all attempts included
PER_TRY_S = 0.5                   # cap per attempt (provider p99.9 ~300 ms x 1.5)
MARGIN_S = 0.05                   # keep for our own response handling
ATTEMPTS = 3
POOL = 16                         # ceil(200 rps x 0.060 s x 1.3)


class ProviderUnavailable(Exception):
    """Fail fast: breaker open, bulkhead full or retries exhausted."""


class Breaker:
    """Count-based: open when >= 50% of the last 20 calls failed; 3 half-open probes."""

    def __init__(self, window=20, rate=0.5, open_s=10.0, probes=3, clock=time.monotonic):
        self.calls = collections.deque(maxlen=window)
        self.rate, self.open_s, self.probes, self.clock = rate, open_s, probes, clock
        self.opened_at: float | None = None
        self.in_probe = 0

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        if self.clock() - self.opened_at < self.open_s:
            return False
        if self.in_probe < self.probes:          # half-open: let a few through
            self.in_probe += 1
            return True
        return False

    def record(self, ok: bool) -> None:
        if self.opened_at is not None:            # result of a half-open probe
            self.in_probe = max(0, self.in_probe - 1)
            if ok:
                self.opened_at, self.in_probe = None, 0
                self.calls.clear()
            else:
                self.opened_at = self.clock()     # re-open, restart the timer
            return
        self.calls.append(ok)
        fails = self.calls.count(False)
        if len(self.calls) == self.calls.maxlen and fails / len(self.calls) >= self.rate:
            self.opened_at = self.clock()


class RetryBudget:
    """Retries may add at most ~10% load: +0.1 token per call, -1 per retry, cap 10."""

    def __init__(self, ratio=0.1, cap=10.0):
        self.tokens, self.ratio, self.cap = cap, ratio, cap

    def on_call(self):
        self.tokens = min(self.cap, self.tokens + self.ratio)

    def try_spend(self) -> bool:
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class PaymentClient:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http
        self.breaker = Breaker()
        self.budget = RetryBudget()
        self.bulkhead = asyncio.Semaphore(POOL)

    async def charge(self, order_id: str, amount_cents: int) -> dict:
        idem_key = f"charge-{order_id}"          # derived from the business operation, not per attempt
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
                        async with asyncio.timeout(per_try):          # enforce even if the transport does not
                            r = await self.http.post(
                                "/v1/charges",
                                json={"amount": amount_cents, "reference": order_id},
                                headers={"Idempotency-Key": idem_key},  # same key on every attempt
                                timeout=per_try,
                            )
                    except (TimeoutError, httpx.TimeoutException, httpx.ConnectError):
                        self.breaker.record(False)
                    else:
                        if r.status_code not in RETRYABLE_STATUS:
                            self.breaker.record(r.status_code < 500)
                            r.raise_for_status()                      # 4xx: never retried
                            return r.json()
                        self.breaker.record(False)
                    if attempt == ATTEMPTS - 1 or not self.budget.try_spend():
                        break
                    window = min(1.0, 0.1 * 2**attempt)               # full jitter
                    await asyncio.sleep(random.uniform(0, window))
        except TimeoutError:
            raise ProviderUnavailable("deadline exceeded") from None
        finally:
            self.bulkhead.release()
        raise ProviderUnavailable("retries exhausted")
```

Design notes:

- The breaker is count-based over the last 20 calls and only evaluates a full window, which doubles as
  the "minimum 20 calls" rule. Half-open admits 3 probes; one success closes, one failure re-opens.
- `RetryBudget` deposits 0.1 token per call and spends 1 per retry, so sustained retries cannot exceed
  about 10 % of call volume; the cap of 10 tokens allows short bursts.
- `asyncio.timeout(per_try)` wraps the request even though httpx has its own `timeout=`: some
  transports (including `httpx.MockTransport`) do not enforce it, and DNS or pool waits can escape
  per-phase timeouts.
- The bulkhead waits at most 100 ms for a slot and then fails fast; queueing longer only converts
  overload into latency.

## `sim.py`

```python
"""Outage simulation for payclient.py: 200 rps for 40 s (5 s healthy, 30 s fault, 5 s recovery).

    python sim.py                      # hard outage: 50 % 503, 50 % hang (10 % processed, response lost)
    python sim.py --brownout           # 20 % 503, 10 % processed but response lost, 70 % healthy
    python sim.py --brownout --no-key  # same, provider cannot deduplicate
"""
import asyncio
import collections
import json
import random
import statistics
import sys
import time

import httpx

from payclient import PaymentClient, ProviderUnavailable

RPS, HEALTHY_S, OUTAGE_S, RECOVER_S = 200, 5.0, 30.0, 5.0
USE_KEY = "--no-key" not in sys.argv
BROWNOUT = "--brownout" in sys.argv
random.seed(7)

executions = collections.Counter()   # order reference -> charges actually created
store: dict[str, dict] = {}          # provider-side idempotency store
upstream_per_s = collections.Counter()
T0 = 0.0


async def provider(request: httpx.Request) -> httpx.Response:
    t = time.monotonic() - T0
    upstream_per_s[int(t)] += 1
    key = request.headers.get("Idempotency-Key") if USE_KEY else None
    ref = json.loads(request.content)["reference"]
    if key and key in store:                        # replay, do not re-execute
        await asyncio.sleep(0.06)
        return httpx.Response(200, json=store[key])
    if HEALTHY_S <= t < HEALTHY_S + OUTAGE_S:
        roll = random.random()
        p503, plost = (0.2, 0.3) if BROWNOUT else (0.5, 0.6)
        if roll < p503:
            await asyncio.sleep(0.005)
            return httpx.Response(503)
        if roll < plost:                            # charge created, response never arrives
            executions[ref] += 1
            if key:
                store[key] = {"id": ref}
            await asyncio.sleep(5)
        elif not BROWNOUT:
            await asyncio.sleep(5)                  # hard outage: hang
    await asyncio.sleep(random.uniform(0.04, 0.08))
    executions[ref] += 1
    if key:
        store[key] = {"id": ref}
    return httpx.Response(200, json={"id": ref})


async def main() -> None:
    global T0
    by_phase: dict[str, list[float]] = collections.defaultdict(list)
    outcomes = collections.Counter()
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider),
                                 base_url="https://psp.test") as http:
        client = PaymentClient(http)

        async def one(i: int) -> None:
            start = time.monotonic()
            t = start - T0
            phase = "healthy" if t < HEALTHY_S else "fault" if t < HEALTHY_S + OUTAGE_S else "recovery"
            try:
                await client.charge(f"o{i}", 1999)
                outcomes["ok"] += 1
            except ProviderUnavailable as e:
                outcomes[str(e)] += 1
            by_phase[phase].append(time.monotonic() - start)

        T0 = time.monotonic()
        total = int(RPS * (HEALTHY_S + OUTAGE_S + RECOVER_S))
        tasks = []
        for i in range(total):
            tasks.append(asyncio.create_task(one(i)))
            await asyncio.sleep(max(0.0, T0 + (i + 1) / RPS - time.monotonic()))   # open-loop load
        await asyncio.gather(*tasks)

    print(f"brownout={BROWNOUT} keys={USE_KEY} requests={total} outcomes={dict(outcomes)}")
    for phase, xs in by_phase.items():
        q = statistics.quantiles(xs, n=100)
        print(f"  {phase:8s} n={len(xs)} p99={q[98] * 1000:.0f} ms max={max(xs) * 1000:.0f} ms")
    fault = sum(v for s, v in upstream_per_s.items() if HEALTHY_S <= s < HEALTHY_S + OUTAGE_S)
    print(f"  upstream calls during fault={fault} ({fault / OUTAGE_S:.1f}/s vs {RPS}/s offered)")
    print(f"  duplicate charges={sum(1 for v in executions.values() if v > 1)}")


asyncio.run(main())
```

Results (one run each; expect a few percent of run-to-run variation):

| Run | ok | Fail-fast (circuit open) | Bulkhead full | Retries exhausted | Upstream during fault | Fault p99 | Max | Duplicates |
|---|---|---|---|---|---|---|---|---|
| hard outage, keys | 1,669 | 6,331 | 0 | 0 | 24 | 0 ms | 662 ms | 0 |
| brownout, keys | 5,338 | 332 | 1,571 | 759 | 4,711 | 720 ms | 899 ms | 0 |
| brownout, no keys | 5,256 | 555 | 1,413 | 776 | 4,627 | 732 ms | 1,426 ms | 193 |
| brownout, keys, pool 24 | 6,604 | 85 | 0 | 1,311 | 6,520 | 645 ms | 872 ms | 0 |
| brownout, keys, per-try 0.3 s | 6,239 | 410 | 240 | 1,111 | 5,946 | 496 ms | 734 ms | 0 |

The pool and per-try variants were run by overriding `payclient.POOL` / `payclient.PER_TRY_S` before
`sim.py` starts.

## Toxiproxy runbook (real network, provider sandbox)

```bash
toxiproxy-server &                                            # API on :8474
toxiproxy-cli create -l localhost:26443 -u sandbox.psp.example:443 psp
# point the service's provider base URL at localhost:26443 (TLS SNI/host header as the sandbox needs)

# load: 200 rps for 60 s with any open-loop generator (k6 constant-arrival-rate, vegeta, wrk2)
vegeta attack -rate=200/s -duration=60s -targets=targets.txt | vegeta report &

sleep 15
toxiproxy-cli toxic add -t timeout -a timeout=0 psp           # connections hang, data dropped
sleep 30
toxiproxy-cli toxic remove -n timeout_downstream psp          # name printed by "toxic add"
wait
```

Other faults to rehearse: `-t latency -a latency=400 -a jitter=200` (brownout), `-t reset_peer
-a timeout=100` (connection resets), `-t limit_data -a bytes=512` (truncated responses), and disabling
the proxy through the HTTP API (`POST /proxies/psp` with `{"enabled": false}`) for refused connections.
`POST /reset` removes all toxics. Never expose the toxiproxy API port outside the test network.

Pass criteria, checked from the provider sandbox and the service's metrics:

| Check | Pass |
|---|---|
| Charges per order reference in the sandbox | exactly 1 for every successful order, 0 or 1 for failed ones |
| p99 latency of the charge endpoint during the fault | <= 2 s (the deadline) |
| Upstream request rate during the fault | <= 1/s per instance once the breaker is open |
| Recovery | breaker closed and success rate back to baseline within open duration + 5 s |
| Retries | attempts metric shows <= 3 per call and total retry volume <= ~10 % of calls |
