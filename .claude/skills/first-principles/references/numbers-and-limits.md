# Numbers and limits for bound derivations

Orders of magnitude for 2025-2026 commodity hardware. They are for bounds and Fermi estimates, not
for capacity plans: when a decision depends on a factor of 2, measure on the target hardware (code-
optimizer or tester) or cite the datasheet (quick-researcher). Ranges are deliberate.

## Latency ladder

| Operation | Order of magnitude | Note |
|---|---|---|
| CPU cycle at 3-5 GHz | 0.2-0.3 ns | |
| L1 hit | ~1 ns | 4-5 cycles |
| L2 hit | ~3-5 ns | |
| L3 hit | ~10-20 ns | grows with core count and chiplet hops |
| branch mispredict | ~5 ns | 15-20 cycles |
| uncontended mutex lock/unlock | ~10-25 ns | contended: microseconds |
| DRAM access | ~80-120 ns | remote NUMA node: +50-100% |
| context switch | ~1-5 us | plus cache pollution |
| syscall (simple) | ~0.1-1 us | mitigations raise it |
| NVMe 4 KiB random read | ~10-100 us | device and queue depth dependent |
| same-host loopback RTT | ~10-50 us | kernel TCP; less with kernel bypass |
| same-datacenter RTT | ~0.1-0.5 ms | |
| cross-zone RTT, same region (cloud) | ~0.5-2 ms | |
| HDD seek | ~5-10 ms | |
| intercontinental RTT | ~70-250 ms | fibre floor = distance / 100 km per ms RTT, plus path stretch |
| TLS 1.3 full handshake | +1 RTT | 0-RTT resumption possible with replay caveats |
| TCP connect | +1 RTT | |

## Bandwidth ladder

| Path | Order of magnitude |
|---|---|
| DRAM (DDR5) per channel | ~40-60 GB/s; a server socket with 8-12 channels: ~300-600 GB/s |
| GPU HBM (data-centre GPU) | ~2-8 TB/s |
| PCIe 4.0 x16 / 5.0 x16 | ~32 / ~64 GB/s per direction |
| NVMe SSD sequential (PCIe 4 / 5) | ~7 / ~12-14 GB/s |
| 10 / 25 / 100 / 400 GbE | 1.25 / 3.1 / 12.5 / 50 GB/s |
| home broadband / mobile | ~10-1000 Mbit/s; assume the low end for global users |
| GPU-to-GPU links (NVLink class) | hundreds of GB/s to ~1+ TB/s per GPU |

## Compute

| Unit | Order of magnitude |
|---|---|
| one CPU core, scalar | a few GFLOP/s; SIMD (AVX-512) tens of GFLOP/s fp64 |
| server CPU socket | ~1-5 TFLOP/s fp64 with SIMD |
| data-centre GPU, fp32 (non-tensor) | ~20-80 TFLOP/s |
| data-centre GPU, bf16/fp8 tensor | ~0.5-5 PFLOP/s dense, generation-dependent |
| ridge point (GPU) | fp32: ~10-30 FLOP/B; tensor-core low precision: hundreds of FLOP/B |

## Storage and data sizes

| Item | Size |
|---|---|
| UUID / 128-bit ID | 16 B binary, 36 B as text |
| fp32 / fp64 / bf16 | 4 / 8 / 2 B |
| typical JSON overhead vs packed binary | 2-10x |
| 1 million rows x 1 KB | 1 GB |
| one LLM token (English) | ~4 characters, ~0.75 words |

## Physical constants and conversions

| Quantity | Value |
|---|---|
| speed of light, vacuum | 299,792 km/s |
| speed of light in fibre (n ~ 1.47) | ~204,000 km/s; use 200,000 for bounds |
| Boltzmann k | 1.380649 x 10^-23 J/K |
| kT ln 2 at 300 K | ~2.87 x 10^-21 J |
| Earth circumference | ~40,000 km; max great-circle distance ~20,000 km (fibre RTT floor ~200 ms) |
| seconds per year | ~3.156 x 10^7 |
| 1 Gbit/s | 125 MB/s |

Great-circle distance (haversine), for RTT floors:

```python
import math
def km(lat1, lon1, lat2, lon2, R=6371.0):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))
# RTT floor in ms = 2 * km(...) / 200000 * 1000
```

Examples (to northern Virginia): London ~5,900 km (floor ~59 ms), Tokyo ~10,900 km (~109 ms),
Sydney ~15,700 km (~157 ms).

## Availability arithmetic

| Availability | Downtime per year | per 30 days |
|---|---|---|
| 99% | 3.65 days | 7.2 h |
| 99.9% | 8.76 h | 43.2 min |
| 99.95% | 4.38 h | 21.6 min |
| 99.99% | 52.6 min | 4.3 min |
| 99.999% | 5.26 min | 26 s |

Series of k components each at A: A^k (five services at 99.9% each: ~99.5%). Two independent
replicas at 99%: 1 - 0.01^2 = 99.99%, but only if failures are truly independent; shared power,
network, deploys or config make them correlated and the real figure far lower.

## Queueing quick table (M/M/1, response time as multiple of service time)

| rho | W / (1/mu) |
|---|---|
| 0.5 | 2 |
| 0.7 | 3.3 |
| 0.8 | 5 |
| 0.9 | 10 |
| 0.95 | 20 |
| 0.99 | 100 |

Heavy-tailed service times and bursty arrivals make it worse (Kingman's approximation for G/G/1:
W_q ~ (rho / (1 - rho)) x ((c_a^2 + c_s^2) / 2) x (1/mu), with c the coefficients of variation).

## Fermi template

```markdown
Target: <quantity, unit>
Route 1: <factor 1 (low-high, geo mean)> x <factor 2 ...> = <point> (spread x<r>)
Route 2: <independent decomposition> = <point>
Agreement: within <ratio>x -> usable / not usable
Decision it informs: <decision>, threshold <value>; estimate is <above/below/straddles>
```

Spread for a product of factors with ranges r_i (high/low): total ratio either side of the point
estimate is about `exp(sqrt(sum((ln r_i / 2)^2)))`. Three factors each known within 10x
(r = 10) give exp(sqrt(3) x 1.15) ~ 7x either side: enough to decide only if the threshold is far away.
