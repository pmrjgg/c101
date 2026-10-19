# Profiler command reference

Checked on macOS with py-spy 0.4.2, Scalene 2.3.0, memray 1.20.0, line_profiler 5.1.0, pyperf 2.10.0
and CPython 3.13 / 3.14 / 3.15.0. On macOS, py-spy and `profiling.sampling` need `sudo` ("This
program requires root on OSX"). On Linux, launching a program under the profiler needs no root;
attaching to a PID depends on `kernel.yama.ptrace_scope`, and containers need the `SYS_PTRACE`
capability.

## py-spy (sampling, out of process, attach without code changes)

```bash
py-spy record -o flame.svg -- python app.py args          # launch and record
py-spy record -o flame.svg --pid 4242 --duration 30       # attach to a running process
py-spy record -o prof.json -f speedscope --pid 4242       # open in speedscope.app
py-spy record --rate 250 --subprocesses -o f.svg -- python -m app   # higher rate, include children
py-spy record --native -o f.svg --pid 4242                # C/C++/Rust frames (Linux and Windows only)
py-spy record --gil -o gil.svg --pid 4242                 # only samples holding the GIL
py-spy record --idle -o all.svg --pid 4242                # include waiting threads (I/O, locks)
py-spy top --pid 4242                                     # live top-like view
py-spy dump --pid 4242 --locals                           # one stack snapshot per thread (hangs!)
```

Formats: `flamegraph` (default SVG), `speedscope`, `raw` (collapsed stacks), `chrometrace`. Idle
threads are excluded by default, so a program that mostly waits looks fast. Add `--idle` when wall
time is far above CPU time.

## profiling.sampling (CPython 3.15+, "Tachyon", stdlib)

```bash
python -m profiling.sampling run --flamegraph -o flame.html app.py      # HTML flame graph
python -m profiling.sampling run --pstats app.py                        # pstats-style table (default)
python -m profiling.sampling run --gecko -o prof.json app.py            # Firefox Profiler format
python -m profiling.sampling run --mode cpu -a app.py                   # CPU time only, all threads
python -m profiling.sampling run --mode wall --async-aware app.py       # wall time with asyncio task stacks
python -m profiling.sampling attach 4242 --flamegraph -o live.html      # attach to a PID
python -m profiling.sampling dump 4242                                  # current stacks of a PID
python -m profiling.sampling run --live app.py                          # interactive TUI
python -m profiling.sampling run --binary -o base.bin app.py            # save a baseline...
python -m profiling.sampling run --diff-flamegraph base.bin -o diff.html app.py   # ...and diff after the change
```

Modes: `wall`, `cpu`, `gil`, `exception`. Other useful flags: `--native` (adds `<native>` marker frames),
`--subprocesses`, `-r/--sampling-rate`, `-d/--duration`. The deterministic profiler is also importable
as `profiling.tracing` in 3.15; `cProfile` remains.

## Scalene 2.x (Python vs native vs system time per line)

```bash
scalene run app.py args                      # writes scalene-profile.json
scalene run -o prof.json --cpu-only app.py   # CPU only, lowest overhead
scalene run --memory app.py                  # add allocation attribution per line
scalene run --profile-only mypkg app.py      # restrict to matching files
scalene view prof.json                       # browser UI
scalene view --cli -r prof.json              # terminal, only lines with activity
scalene view --html --standalone prof.json   # self-contained HTML to attach to a ticket
```

Scalene 1.x used `scalene app.py --cli`; 2.x split it into `run` and `view`. Read the columns:
high "Python" time is interpreter work you can vectorise or compile; high "native" time is already
in C, so look for fewer calls or a better algorithm; high "system" time means I/O or memory pressure.

## cProfile, pstats, snakeviz (deterministic: exact counts, distorted times)

```bash
python -m cProfile -o out.prof -s cumtime app.py      # 3.15+: python -m profiling.tracing ...
snakeviz out.prof                                     # icicle chart in the browser
```

```python
import pstats
p = pstats.Stats("out.prof")
p.sort_stats("cumulative").print_stats(20)            # who includes the time
p.sort_stats("tottime").print_stats(20)               # who spends it themselves
p.print_callers("iterrows")                           # who calls the hot function
```

Overhead scales with the number of Python calls: about 3x on the pandas iterrows baseline in the
worked example. Use the shape of the profile, then time the change with pyperf.

## line_profiler (per-line times inside chosen functions)

```bash
kernprof -l -v app.py                      # functions decorated with @profile (kernprof injects it)
kernprof -l -p mypkg.scoring -v app.py     # profile a module without decorating (--prof-mod)
python -m line_profiler app.py.lprof       # re-read saved results
```

```python
from line_profiler import profile          # no-op unless run under kernprof or with LINE_PROFILE=1

@profile
def score(rows): ...
```

`LINE_PROFILE=1 python app.py` writes `profile_output.txt` and `profile_output.lprof` without kernprof.

## tracemalloc (stdlib, Python allocations, works everywhere)

```python
import tracemalloc
tracemalloc.start(25)                            # keep 25 frames per allocation
base = tracemalloc.take_snapshot()
run_batch()
snap = tracemalloc.take_snapshot()
for stat in snap.compare_to(base, "lineno")[:10]:     # or "traceback" for full stacks
    print(stat)
current, peak = tracemalloc.get_traced_memory()       # bytes
tracemalloc.reset_peak()                              # measure the peak of the next phase only
```

It does not see allocations made by C or Rust libraries outside the Python allocator (most
NumPy/Polars buffers). Use memray with `--native`, or RSS, for those.

## memray (every allocation, Python and native, Linux and macOS)

```bash
memray run -o run.bin app.py args            # -m module also works; -f overwrites
memray run --native -o run.bin app.py        # native stacks (C, C++, Rust)
memray run --follow-fork -o run.bin app.py   # multiprocessing children
memray run --trace-python-allocators -o run.bin app.py   # see pymalloc-level allocations
memray stats run.bin                         # peak, totals, size histogram, allocator mix
memray summary run.bin                       # top allocating functions
memray tree run.bin                          # terminal tree at the peak
memray flamegraph run.bin                    # HTML flame graph of memory held at the peak
memray flamegraph --temporal run.bin         # peak over time
memray flamegraph --leaks run.bin            # still allocated at exit (run with PYTHONMALLOC=malloc)
memray table run.bin                         # sortable HTML table
memray run --live app.py                     # live TUI
memray attach 4242                           # attach to a running process (uses gdb or lldb)
```

pytest-memray:

```bash
pytest --memray tests/perf
```

```python
@pytest.mark.limit_memory("200 MB")         # fails: "Test was limited to 1.0MiB but allocated 4.8MiB"
def test_import_batch_memory(): ...

@pytest.mark.limit_leaks("1 MB")
def test_no_leak_per_request(): ...
```

## objgraph and gc (reference leaks and cycles)

```python
import gc, objgraph
gc.collect()
objgraph.show_growth(limit=10)              # call before and after the suspect operation
objgraph.show_most_common_types(limit=15)
leaked = objgraph.by_type("Session")
objgraph.show_backrefs(leaked[:1], max_depth=6, filename="refs.png")   # needs graphviz
gc.get_referrers(leaked[0])                  # quick look without graphviz
```

Typical culprits: module-level caches and registries, `functools.lru_cache` on methods (it holds
`self`), closures stored in callbacks, exceptions kept with their tracebacks (frames hold locals).

## Linux perf and import time

```bash
python -X perf app.py & perf record -F 999 -g -p $! -- sleep 30; perf report   # 3.12+: Python frames in perf
python -X importtime -c "import app.main" 2> import.log    # self and cumulative microseconds per import
sort -t'|' -k2 -n import.log | tail -20                     # slowest cumulative imports
tuna import.log                                             # optional visualiser (pip install tuna)
```
