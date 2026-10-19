# jcmd, native memory and heap diagnostics

`jcmd` must run as the same user as the target JVM (inside the container: `kubectl exec`), and
`jcmd <pid> help` lists the commands that JVM supports. `%p` in file names expands to the PID.

## 1. jcmd cheat sheet (JDK 25)

| Question | Command | Cost |
|---|---|---|
| flags in effect | `jcmd <pid> VM.flags` (`-all` for every flag); offline: `java -XX:+PrintFlagsFinal -version` | low |
| command line, properties, uptime, version | `VM.command_line`, `VM.system_properties`, `VM.uptime`, `VM.version` | low |
| heap layout, G1 region size | `GC.heap_info` | low |
| live objects by class | `GC.class_histogram` (`-all` includes unreachable, skips the full GC) | high: full GC |
| full heap dump | `GC.heap_dump [-all] [-gz=1] [-parallel=4] [-overwrite] /dumps/heap.hprof` | high: full GC + pause, file ~ live set |
| thread dump incl. virtual threads | `Thread.dump_to_file -format=json /tmp/threads.json` | medium |
| classic thread dump, j.u.c. locks, deadlocks | `Thread.print -l` | medium |
| native memory by category | `VM.native_memory summary scale=MB` (needs `-XX:NativeMemoryTracking=summary` at start) | medium |
| native growth | `VM.native_memory baseline`, later `VM.native_memory summary.diff scale=MB` | medium |
| metaspace by class loader | `VM.metaspace` | low |
| code cache fill and fragmentation | `Compiler.CodeHeap_Analytics aggregate` | low |
| return free malloc memory to the OS (glibc) | `System.trim_native_heap` | low |
| change logging live | `VM.log what=gc+phases=debug output=/logs/gc-debug.log`, `VM.log list` | low |
| JFR | `JFR.start`, `JFR.dump`, `JFR.stop`, `JFR.check`, `JFR.view`, `JFR.configure` | low |
| end an AOT training run (25) | `AOT.end_recording` | low |

## 2. NMT categories (summary mode)

| Category | Contains | Grows when |
|---|---|---|
| Java Heap | the heap reservation | `-Xmx` / `MaxRAMPercentage` |
| Class, Metaspace | class metadata | class-loader leaks, generated proxies, redeploys |
| Thread | platform thread stacks and structures | thread leaks, oversized pools |
| Code | JIT code cache | many hot methods; near `ReservedCodeCacheSize` disables the JIT |
| GC | card table, remembered sets, mark bitmaps | larger heaps, many cross-region references (G1) |
| Compiler | JIT compiler arenas | compilation storms |
| Internal, Symbol, Arena Chunk | VM internals, interned symbols | unusual unless string/symbol churn |
| Other | direct `ByteBuffer`s (`Unsafe.allocateMemory`) | Netty/NIO buffer leaks |

NMT does not see third-party native code or memory malloc'ed by native libraries. Compare its
total committed with container RSS (`cat /sys/fs/cgroup/memory.current` on cgroup v2, or the
pod's working set): a large gap points at glibc arenas or native libraries.

## 3. Heap dumps safely

- A dump stops the JVM for seconds per GB and writes roughly the live set to disk: take it from
  an instance removed from the load balancer, with enough disk on the target volume.
- `-XX:+HeapDumpOnOutOfMemoryError` covers only Java-heap OOMs, not container kills.
- Dumps contain every string in memory (tokens, personal data): store and share them like
  production secrets; delete after analysis.

## 4. Eclipse MAT

```bash
# headless reports (zip of HTML next to the dump); raise -Xmx in MemoryAnalyzer.ini above the dump size
./ParseHeapDump.sh /dumps/heap.hprof org.eclipse.mat.api:suspects
./ParseHeapDump.sh /dumps/heap.hprof org.eclipse.mat.api:overview
./ParseHeapDump.sh /dumps/heap.hprof org.eclipse.mat.api:top_components
```

| Step | Where in MAT | Look for |
|---|---|---|
| 1 | Leak Suspects report | one object or class retaining a large share of the heap |
| 2 | Dominator Tree, sort by Retained Heap | the few objects keeping most memory alive |
| 3 | Path to GC Roots, exclude weak/soft/phantom references | the static field, thread or cache holding the suspect |
| 4 | Histogram, group by class loader | duplicate class loaders: metaspace and redeploy leaks |
| 5 | OQL, e.g. `SELECT * FROM java.util.HashMap h WHERE h.size > 100000` | oversized collections |
| 6 | Collections > Fill Ratio / Hash Entries | wasted capacity in collections |

Typical culprits: unbounded caches (maps without eviction), listeners never removed,
`ThreadLocal` values on pooled threads, request-scoped objects captured by static fields or
long-lived lambdas, per-tenant class loaders never released.

## 5. Histogram diff without a full dump

```bash
jcmd <pid> GC.class_histogram > /tmp/h1.txt      # under steady load
# wait 10-30 minutes, same load
jcmd <pid> GC.class_histogram > /tmp/h2.txt
python3 histodiff.py /tmp/h1.txt /tmp/h2.txt 20   # top 20 classes by byte growth
```

`histodiff.py`:

```python
import re, sys
ROW = re.compile(r"\s*\d+:\s+(\d+)\s+(\d+)\s+(\S+)")      # " 1:  120000  96000000  [B (java.base@25)"
def load(path):
    rows = {}
    for line in open(path):
        m = ROW.match(line)
        if m:
            rows[m.group(3)] = (int(m.group(1)), int(m.group(2)))
    return rows
old, new = load(sys.argv[1]), load(sys.argv[2])
deltas = []
for cls, (inst, size) in new.items():
    oi, ob = old.get(cls, (0, 0))
    deltas.append((size - ob, inst - oi, cls))
for dbytes, dinst, cls in sorted(deltas, reverse=True)[:int(sys.argv[3]) if len(sys.argv) > 3 else 20]:
    print(f"{dbytes / 1e6:+10.1f} MB {dinst:+12d} inst  {cls}")
```

`[B` (byte arrays) and `java.lang.String` usually top the list; the lead is the first
application class that keeps growing across three or more diffs.
