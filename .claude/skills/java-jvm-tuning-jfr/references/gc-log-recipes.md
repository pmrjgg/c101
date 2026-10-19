# GC log recipes

## 1. Logging selectors

```bash
-Xlog:gc*,safepoint:file=/logs/gc-%p.log:time,uptime,level,tags:filecount=5,filesize=20m   # baseline
-Xlog:gc+phases=debug          # per-phase times inside pauses (object copy, ref processing)
-Xlog:gc+heap=debug            # region and space details before/after each GC
-Xlog:gc+age=trace             # tenuring distribution (G1/Parallel)
-Xlog:gc+humongous=debug       # humongous object handling (G1)
-Xlog:gc*:stderr               # quick look at startup: chosen GC, region size, heap bounds
```

`%p` and `%t` in file names expand to PID and start time. `filecount=0` disables rotation.
Change logging on a running JVM with `jcmd <pid> VM.log what=gc+phases=debug output=/logs/gc.log`
(`VM.log list` shows current outputs). Keep `time,uptime` decorators: wall time lines up with
incidents, uptime makes rate calculations easy.

## 2. Line shapes (JDK 25, G1)

```
[...][5123.441s][info][gc,start    ] GC(4211) Pause Young (Concurrent Start) (G1 Humongous Allocation)
[...][5123.818s][info][gc,heap     ] GC(4211) Humongous regions: 612->38
[...][5123.818s][info][gc          ] GC(4211) Pause Young (Concurrent Start) (G1 Humongous Allocation) 6210M->3020M(8192M) 377.120ms
[...][5124.012s][info][gc          ] GC(4212) Pause Young (Normal) (G1 Evacuation Pause) (Evacuation Failure: Allocation) 7800M->7700M(8192M) 12.500ms
[...][5125.000s][info][gc          ] GC(4213) Pause Full (G1 Compaction Pause) 8100M->2900M(8192M) 1890.333ms
```

Young pause name = `Pause Young (<type>) (<cause>)` with type `Normal`, `Concurrent Start`,
`Prepare Mixed` or `Mixed`; an evacuation failure appends `(Evacuation Failure: Allocation)`
and/or `Pinned`. Every pause has a `gc,start` line without timing and a `gc` line ending in
`ms`: count only the latter or totals double.

## 3. Pauses by type and cause

```bash
grep -E 'Pause .*[0-9]ms$' gc.log | grep -oE 'Pause [A-Za-z]+( \([^)]*\))*' | sort | uniq -c | sort -rn

grep -E 'Pause .*[0-9]ms$' gc.log \
  | sed -E 's/.*(Pause [A-Za-z]+( \([^)]*\))*) .* ([0-9.]+)ms$/\3|\1/' \
  | awk -F'|' '{ n[$2]++; s[$2] += $1; if ($1 > m[$2]) m[$2] = $1 }
      END { for (k in n) printf "%6d %10.1fms total %9.1fms max  %s\n", n[k], s[k], m[k], k }' \
  | sort -k2 -rn
```

## 4. Pause percentiles (nearest rank)

```bash
grep -E 'Pause .*[0-9]ms$' gc.log | grep -oE '[0-9.]+ms$' | sed 's/ms$//' | sort -n | awk '
function pct(p,  i) { i = int(p * NR); if (i < p * NR) i++; if (i < 1) i = 1; return a[i] }
{ a[NR] = $1; s += $1 }
END { printf "pauses=%d total=%.1fms p50=%s p90=%s p99=%s max=%s\n", NR, s, pct(0.50), pct(0.90), pct(0.99), a[NR] }'
```

## 5. GC pause share of wall time

```bash
awk -F'[][]' '/Pause .*[0-9]ms$/ { up = $4; sub(/s$/, "", up); if (first == "") first = up; last = up
    ms = $NF; sub(/.* /, "", ms); sub(/ms$/, "", ms); total += ms }
  END { if (last > first) printf "GC pauses: %.1f ms over %.0f s = %.2f%% of wall time\n", total, last - first, total / 10 / (last - first) }' gc.log
```

Assumes the `time,uptime,level,tags` decorators (uptime is the second bracket). Below 2% is
healthy for most services; above 5% means allocation or heap sizing needs work. Concurrent
phases (G1 marking, ZGC) do not appear here but consume CPU: compare with process CPU.

## 6. Reading the result

| Finding | Next step |
|---|---|
| most pause time in `Pause Young (Normal)`, many per second | allocation rate: JFR `jfr view allocation-by-site`, async-profiler `-e alloc` |
| `G1 Humongous Allocation` causes, high `Humongous regions` before counts | find arrays/strings >= half a region (JFR `jdk.ObjectAllocationOutsideTLAB` with `gc=high`) |
| `Evacuation Failure` followed by `Pause Full` | heap too small for live set plus allocation bursts; leak check with histograms |
| `Pause Full (System.gc())` | find the caller (RMI DGC, libraries, `jcmd GC.run`); `-XX:+ExplicitGCInvokesConcurrent` or `-XX:+DisableExplicitGC` once understood |
| long `Pause Remark` | `-Xlog:gc+phases=debug`; reference processing (soft/weak refs, finalizers), class unloading |
| `Pause Young (Mixed)` long | old regions with large remembered sets; more heap or fewer cross-region references |
| ZGC `Allocation Stall` lines or JFR `jdk.ZAllocationStall` | more heap headroom, more concurrent GC threads, lower allocation |
| ZGC `Major Collection` frequent | live set close to max heap: raise heap or cut retention |

## 7. Heap occupancy after GC (leak trend)

```bash
grep -E '\]\[gc +\] GC\([0-9]+\) Pause (Young|Full)' gc.log \
  | sed -E 's/.*\]\[([0-9.]+)s\].* [0-9]+M->([0-9]+)M\([0-9]+M\).*/\1 \2/' > after-gc.txt
# columns: uptime_seconds heap_after_MB; plot or eyeball: a rising floor after Full/Mixed GCs is a leak
```
