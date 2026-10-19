# Worked example: scripts and measured numbers

Reproduces the CSV aggregation case from the skill on synthetic data. Measured on an Apple Silicon
laptop with CPython 3.13.16, pandas 3.0.6, Polars 2.0.0, Numba 0.68.0, pyperf 2.10.0 and memray 1.20.0.
Absolute numbers differ on other machines; the ratios and the shape of the profiles carry over.

## Data

```python
# gen.py: python gen.py 1000000 events.csv  (53.6 MB; 4,000,000 rows = 216 MB)
import sys
import numpy as np, polars as pl
n = int(sys.argv[1])
rng = np.random.default_rng(42)
start = np.datetime64("2026-01-01T00:00:00", "ms")
pl.DataFrame({
    "customer_id": rng.integers(1, n // 50, n),
    "ts": start + (rng.integers(0, 90 * 86400, n) * 1000).astype("timedelta64[ms]"),
    "amount": np.round(rng.gamma(2.0, 40.0, n), 2),
    "merchant": rng.choice([f"merchant-{i:05d}" for i in range(20_000)], n),
    "country": rng.choice(["PT", "ES", "FR", "DE", "US"], n),
}).write_csv(sys.argv[2])
```

## Before: pandas with iterrows

```python
# before.py
import math, sys
import pandas as pd

TAU, CAP = 3600.0, 5_000.0

def main(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["ts"]).sort_values(["customer_id", "ts"])
    rows, prev_c, prev_t, s = {}, None, 0.0, 0.0
    for _, row in df.iterrows():                       # py-spy: ~80% of samples here
        c, t, a = row["customer_id"], row["ts"].timestamp(), row["amount"]
        s = 0.0 if c != prev_c else s * math.exp(-(t - prev_t) / TAU)
        s = min(CAP, s + a)                            # capped, time-decayed velocity score
        key = (c, row["ts"].date())
        tot, n, mx = rows.get(key, (0.0, 0, 0.0))
        rows[key] = (tot + a, n + 1, max(mx, s))
        prev_c, prev_t = c, t
    return pd.DataFrame([(c, d, *v) for (c, d), v in rows.items()],
                        columns=["customer_id", "day", "total", "n", "max_score"])

if __name__ == "__main__":
    print(len(main(sys.argv[1])))
```

## After: Polars lazy scan, Numba kernel for the stateful score, Polars group_by

```python
# after.py
import sys
import numpy as np
import polars as pl
from numba import njit

TAU, CAP = 3600.0, 5_000.0

@njit(cache=True)
def velocity(cust, t, amt, tau, cap):
    out = np.empty(amt.size)
    s = 0.0
    for i in range(amt.size):
        if i == 0 or cust[i] != cust[i - 1]:
            s = 0.0
        else:
            s *= np.exp(-(t[i] - t[i - 1]) / tau)
        s = min(cap, s + amt[i])
        out[i] = s
    return out

def main(path: str) -> pl.DataFrame:
    df = (pl.scan_csv(path, try_parse_dates=True)
            .select("customer_id", "ts", "amount")          # projection pushdown: skip text columns
            .sort("customer_id", "ts", maintain_order=True)   # stable: same tie order as pandas
            .collect(engine="streaming"))
    score = velocity(df["customer_id"].to_numpy(), df["ts"].dt.epoch("s").to_numpy().astype(np.float64),
                     df["amount"].to_numpy(), TAU, CAP)
    return (df.lazy()
              .with_columns(score=pl.Series(score), day=pl.col("ts").dt.date())
              .group_by("customer_id", "day")
              .agg(total=pl.col("amount").sum(), n=pl.len(), max_score=pl.col("score").max())
              .collect(engine="streaming"))

if __name__ == "__main__":
    print(len(main(sys.argv[1])))
```

Equivalence check before any timing (both produce 766,843 groups at 1 M rows):

```python
a = pl.from_pandas(before.main("events.csv")).with_columns(pl.col("day").cast(pl.Date)).sort("customer_id", "day")
b = after.main("events.csv").sort("customer_id", "day")
assert a.shape == b.shape
assert np.allclose(a["total"].to_numpy(), b["total"].to_numpy(), rtol=1e-9, atol=1e-6)
assert np.allclose(a["max_score"].to_numpy(), b["max_score"].to_numpy(), rtol=1e-9, atol=1e-6)
```

`maintain_order=True` on the sort matters: rows with the same customer and timestamp must be scored
in the same order as before, or `max_score` can differ legitimately and the check fails for the
wrong reason.

## Commands and results

```bash
# 1. Where does the time go? (cProfile on a 200k-row sample, since py-spy needs sudo on macOS)
head -200001 events.csv > events200k.csv
python -m cProfile -o before.prof before.py events200k.csv
python -c "import pstats; pstats.Stats('before.prof').sort_stats('cumulative').print_stats(12)"
```

| Function (cumulative) | Time | Share |
|---|---|---|
| `before.py:main` | 7.26 s | 97% |
| `pandas DataFrame.iterrows` | 4.61 s | 61% |
| `pandas Series.__init__` (one Series per row) | 4.01 s | 53% |
| `pandas Series.__getitem__` (800,000 calls) | 1.88 s | 25% |

The run took 7.5 s under cProfile versus about 2.5 s without it: deterministic profiling roughly
triples the cost of call-heavy code. Use it for the shape of the profile, not for absolute times.
`sudo py-spy record -o before.svg -- python before.py events.csv` gives the same picture without the
distortion.

```bash
# 2. Wall time, whole program, 5 processes (1 M rows)
python -m pyperf command -p 5 -n 1 -w 0 -l 1 -o before.json -- python before.py events.csv
python -m pyperf command -p 5 -n 1 -w 1 -l 1 -o after.json  -- python after.py events.csv
python -m pyperf compare_to before.json after.json --table --table-format md
```

| Benchmark | before | after |
|---|:---:|:---:|
| command | 12.5 sec | 389 ms: 32.19x faster |

(before: 12.5 s +- 0.2 s; after: 389 ms +- 18 ms. One warm-up run keeps the Numba compile, about
0.4 s on first use, out of the measured values; `cache=True` stores the machine code in `__pycache__`.)

```bash
# 3. Memory (4 M rows): peak resident set size
/usr/bin/time -l python before.py events4m.csv   # Linux: /usr/bin/time -v
/usr/bin/time -l python after.py events4m.csv
```

| Version (4 M rows) | Wall | Max RSS |
|---|---|---|
| before (pandas, all 5 columns, Python objects per row) | 51.6 s | 3.33 GB |
| after (lazy scan, 3 projected columns, streaming engine) | 0.54 s | 1.48 GB |
| interpreter + polars + numba + numpy imports only | | 0.10 GB |

```bash
# 4. memray: who allocates (1 M rows)
memray run -f -o before.bin before.py events.csv && memray stats before.bin
memray run -f -o after.bin after.py events.csv && memray stats after.bin
```

| Version (1 M rows) | memray peak | Max RSS | Note |
|---|---|---|---|
| before | 1.70 GB | 0.93 GB | Python-heavy; memray sees every allocation with a Python stack |
| after | 4.91 GB | 0.82 GB | 4.93 GB attributed to `<stack trace unavailable>` (Polars' Rust worker threads) |

memray counts the bytes requested through malloc and mmap, not resident pages. Native thread pools
that reserve and recycle large regions show up far above their real footprint, and macOS also
compresses memory, which keeps RSS low. Compare like with like (memray to memray for Python-level
changes, RSS for native-heavy code), and look at the flame graph (`memray flamegraph after.bin`)
before believing a peak.

## Where the remaining time goes

With the pandas row machinery gone, `after.py` at 4 M rows takes 0.54 s of wall time. Timing each
stage in-process (Numba already warm):

| Stage | Time |
|---|---|
| `scan_csv` + parse + projection (streaming collect) | 0.117 s |
| sort by customer and timestamp | 0.063 s |
| Numba `velocity` kernel | 0.027 s |
| `group_by` + aggregation | 0.031 s |
| pipeline total | 0.238 s |

The rest of the 0.54 s is interpreter start-up and imports (polars and numba). At this point
`python -X importtime` matters as much as the kernel. The next levers, in order: convert the input
to Parquet once (no text parsing, column projection inside the file), have the producer pre-sort so
the job can drop the sort, and run the job inside an already-warm process when it runs often.
