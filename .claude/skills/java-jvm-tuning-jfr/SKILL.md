---
name: java-jvm-tuning-jfr
description: "JVM performance and memory diagnosis: choosing a GC by latency SLO, container memory flags and native-memory budgets, OOMKilled triage with NMT, reading G1/ZGC logs, JFR recordings with jfr view, JDK 25 CPU-time sampling and method timing, async-profiler 4 flame graphs, heap dumps in Eclipse MAT, JMH, startup with the AOT cache, CDS and compact object headers. Load for Java latency, throughput, GC, OOM or startup problems."
when_to_use: "p99 latency spikes or GC pauses in a JVM service; GC logs (Pause Young, G1 Humongous Allocation, Evacuation Failure, Pause Full, ZGC Allocation Stall); OutOfMemoryError or a container OOMKilled (exit 137) with heap below -Xmx; .jfr recordings, jcmd, jfr view, JMC, async-profiler/asprof flame graphs; .hprof heap dumps; JMH benchmarks; slow JVM startup, AOT cache or CDS; choosing JVM flags for Kubernetes."
---

# JVM tuning, GC and JFR

Rule zero: measure, change one thing, measure again. Pick the collector from the latency SLO,
size memory from a budget, and stop tuning flags without log or JFR evidence of a specific
problem. Event and view catalogue: [JFR views and events](references/jfr-views-events.md);
jcmd, NMT and MAT details: [jcmd and heap diagnostics](references/jcmd-heap-diagnostics.md);
log parsing scripts: [GC log recipes](references/gc-log-recipes.md).

Procedure: reproduce with a load test or JMH benchmark after JIT warm-up; record JFR under
production-like load; read the top item (CPU, allocation, locks, GC); fix that one item;
confirm with the same measurement.

| Symptom | First move |
|---|---|
| allocation rate above ~1 GB/s | top allocation sites (JFR `allocation-by-site`, `asprof -e alloc`); reuse buffers, remove boxing and streams from hot loops |
| long G1 pauses on a big heap | GC log signals (section 4): humongous allocations, pause goal; generational ZGC if the SLO is single-digit ms |
| CPU in `HashMap.get` / `equals` | poor `hashCode`, mutable or oversized keys |
| contention (`jdk.JavaMonitorEnter`, `jdk.ThreadPark`) | shrink critical sections; `ConcurrentHashMap`, `LongAdder` |
| slow startup | AOT cache or CDS, lazy initialization, fewer classpath scans (section 9) |
| container OOM-killed with heap below `-Xmx` | native memory budget and NMT (section 3) |

## 1. Choose the collector from the SLO

| SLO and shape | Collector | Flags | Notes |
|---|---|---|---|
| p99 GC pause budget ~100-200 ms, heap up to tens of GB, general service | G1 (default) | `-XX:MaxGCPauseMillis=200` (default) | tune the pause goal and heap size, not region internals |
| p99 pause budget < 10 ms, or large heaps with a latency SLO | generational ZGC | `-XX:+UseZGC` | pauses typically < 1 ms, independent of heap size (8 MB-16 TB); costs some throughput and CPU; size the heap 10-20% or more above the peak live set. On 21 add `-XX:+ZGenerational`; generational is default in 23 and the only mode from 24 |
| same latency goal, vendor build with Shenandoah | generational Shenandoah | `-XX:+UseShenandoahGC -XX:ShenandoahGCMode=generational` | product in 25 (JEP 521); Oracle builds omit Shenandoah: test `java -XX:+UseShenandoahGC -version` |
| batch or ETL throughput, pauses irrelevant | Parallel | `-XX:+UseParallelGC` | highest raw throughput |
| heap below ~100 MB, one CPU, CLI tools | Serial | `-XX:+UseSerialGC` | before 27 auto-selected with 1 CPU or < 1792 MB RAM; JDK 27 picks G1 everywhere (JEP 523) |
| benchmarks of allocation-free code only | Epsilon | `-XX:+UnlockExperimentalVMOptions -XX:+UseEpsilonGC` | never collects |

Check what the JVM actually chose: `java -Xlog:gc*:stdout -version | head` (with the same flags) or
`jcmd <pid> VM.flags | tr ' ' '\n' | grep -E 'Use.*GC|MaxHeapSize|G1HeapRegionSize'`.

## 2. Container baseline flags

| Flag | Why |
|---|---|
| `-XX:MaxRAMPercentage=75.0` | heap share of the container limit (default 25); 50-60 with heavy native use |
| `-XX:InitialRAMPercentage=75.0` | no resize churn in steady services (or `-Xms` = `-Xmx`) |
| `-XX:+ExitOnOutOfMemoryError` | let the orchestrator restart a broken JVM |
| `-XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/dumps` | evidence for heap OOMs; the volume needs free space >= heap |
| `-Xlog:gc*,safepoint:file=/logs/gc-%p.log:time,uptime,level,tags:filecount=5,filesize=20m` | rotating GC log with wall time and uptime |
| `-XX:NativeMemoryTracking=summary` | enables `jcmd VM.native_memory`; Oracle cites 5-10% overhead, so measure or enable while investigating |

```bash
# Dockerfile: ENV JDK_JAVA_OPTIONS="..." (no comments inside the value: the JVM would parse them)
JDK_JAVA_OPTIONS="-XX:MaxRAMPercentage=75.0 -XX:InitialRAMPercentage=75.0 -XX:+ExitOnOutOfMemoryError -XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/dumps -Xlog:gc*,safepoint:file=/logs/gc-%p.log:time,uptime,level,tags:filecount=5,filesize=20m -XX:NativeMemoryTracking=summary"
```

- Use `JDK_JAVA_OPTIONS` (read by the `java` launcher only) rather than `JAVA_TOOL_OPTIONS`,
  which every JVM in the container picks up, including `jcmd` itself.
- `-XX:ActiveProcessorCount=N` when the CPU limit misleads ergonomics (GC threads, common pool,
  virtual-thread carriers). Since JDK 19 (backported to 17u) CPU shares, i.e. Kubernetes
  requests, are ignored; only the CPU limit (quota) lowers the count.
- Verify inside the pod: `jcmd <pid> VM.flags`, `jcmd <pid> GC.heap_info` (shows G1 region size).

## 3. Native memory budget and OOMKilled triage

Container RSS = heap + metaspace + code cache + thread stacks + direct buffers + GC structures
+ malloc arenas and native libraries.

| Component | Default ceiling | Control | Example, 4 GiB limit |
|---|---|---|---|
| Java heap | 25% of RAM | `-XX:MaxRAMPercentage`, `-Xmx` | 2.5 GiB (`MaxRAMPercentage=62.5`) |
| metaspace (class metadata) | unlimited | `-XX:MaxMetaspaceSize` | 150 MB |
| code cache | 240 MB reserved (48 MB without tiered) | `-XX:ReservedCodeCacheSize` | 120 MB used |
| platform thread stacks | 1 MB reserved each (Linux x64), committed as touched | `-Xss`, fewer threads; virtual-thread stacks are on the heap | 300 threads: up to 300 MB |
| direct `ByteBuffer`s (Netty, NIO) | about max heap when unset | `-XX:MaxDirectMemorySize` | 256 MB |
| GC structures (G1 card table, remembered sets) | a few % of heap | heap size, region count | 100 MB |
| malloc arenas, JNI libraries, NMT-untracked | none | `MALLOC_ARENA_MAX=2`, fewer native libs | 150 MB |

Sum for the example: about 3.6 GiB, leaving ~10% slack under 4 GiB. Budget before raising
`MaxRAMPercentage`.

| Symptom | Meaning | First move |
|---|---|---|
| `OutOfMemoryError: Java heap space` | live set exceeds heap | heap dump + MAT (section 7) |
| `OutOfMemoryError: Metaspace` | class leak (redeploys, generated proxies) | `jcmd <pid> VM.metaspace`, MAT class loaders |
| `OutOfMemoryError: Direct buffer memory` | `MaxDirectMemorySize` reached | find buffer owners (Netty leak detector), raise cap deliberately |
| `OutOfMemoryError: unable to create native thread` | thread or process limit | thread dump count, pool sizes, `ulimit -u`, pids limit |
| pod `OOMKilled`, exit code 137, no Java OOM | RSS over the limit: native growth | NMT procedure below |

```bash
jcmd <pid> VM.native_memory baseline                    # right after warm-up
jcmd <pid> VM.native_memory summary.diff scale=MB       # hours later: which category grows
jcmd <pid> VM.native_memory summary scale=MB | head -40
```

Read the diff: `Thread` growing means thread leak; `Class`/`Metaspace` means class-loader leak;
`Other` holds direct buffers (`Unsafe.allocateMemory`); `Code` near the cap shows code cache
pressure. If container RSS exceeds NMT's committed total by hundreds of MB, the growth is
outside NMT (glibc arenas, native libraries): try `MALLOC_ARENA_MAX=2`, `jcmd <pid>
System.trim_native_heap` (Linux), and async-profiler `-e nativemem` to find the caller.

## 4. GC log signals

| Log signal (`-Xlog:gc*`) | Meaning | Action |
|---|---|---|
| `Pause Young (Normal) (G1 Evacuation Pause)` adds up to > 5% of wall time | high allocation rate or small young gen | cut allocation (JFR allocation-by-site); more heap lets G1 grow young gen |
| `Pause Young (Concurrent Start) (G1 Humongous Allocation)`, large `Humongous regions: N->M` | objects >= half a region (region = heap/2048 rounded up to a power of 2, 1-32 MB) | chunk buffers below half a region; or `-XX:G1HeapRegionSize=16m` (manual values up to 512 MB since 18) |
| `(Evacuation Failure...)` suffix on the pause line (`: Allocation` or `: Pinned` on recent JDKs; a separate `To-space exhausted` line before 18) | no free regions to copy survivors into | more heap headroom, `-XX:G1ReservePercent` (default 10), reduce live set and humongous churn |
| `Pause Full (G1 Compaction Pause)` | fallback stop-the-world full GC | live set too large for heap or a leak: heap dump; `Pause Full (System.gc())` means explicit calls |
| long `Pause Remark` | reference processing or class unloading during marking | `-Xlog:gc+phases=debug`, fewer soft/weak refs, fewer generated classes |
| frequent concurrent cycles, mixed GCs reclaim little | live set close to heap, IHOP adapts late | more heap; check leak trend |
| ZGC `Allocation Stall` (JFR `jdk.ZAllocationStall`) | allocation outran concurrent collection | more heap headroom and CPU (`-XX:ConcGCThreads`), lower allocation rate |

```bash
grep -E 'Pause .*[0-9]ms$' gc.log | grep -oE 'Pause [A-Za-z]+( \([^)]*\))*' | sort | uniq -c | sort -rn
grep -E 'Evacuation Failure|To-space exhausted|Pause Full|Allocation Stall' gc.log | tail
```

Pause percentiles and GC overhead from a log: [GC log recipes](references/gc-log-recipes.md).

## 5. JFR

```bash
java -XX:StartFlightRecording:name=cont,settings=default,maxage=6h,maxsize=1g,dumponexit=true,filename=/rec/app.jfr -jar app.jar
jcmd <pid> JFR.dump name=cont maxage=10m filename=/tmp/last10m.jfr   # slice of the continuous recording
jcmd <pid> JFR.stop name=cont filename=/tmp/final.jfr                # stop and write (no filename: discard)
jcmd <pid> JFR.start name=perf settings=profile duration=120s filename=/tmp/perf.jfr
jfr summary /tmp/perf.jfr                                            # event counts and sizes
jfr view hot-methods /tmp/perf.jfr
jfr view gc-pauses /tmp/perf.jfr                                     # P90/P95/P99/P99.9/max pause
jfr print --events jdk.ObjectAllocationSample --stack-depth 20 /tmp/perf.jfr
```

Other first-look views: `allocation-by-site`, `gc`, `contention-by-site`, `latencies-by-type`,
`pinned-threads`, `exception-count`, `jvm-flags` (all listed in
[JFR views and events](references/jfr-views-events.md)).

`settings=default` is the always-on profile ("typically less than 1 %" overhead), `profile` the
investigation profile ("around 2 %"): execution samples every 20 vs 10 ms, allocation samples
150/s vs 300/s, lock and park thresholds 20 vs 10 ms. Options override parts:
`settings=profile,gc=high` (adds `jdk.AllocationRequiringGC`, `jdk.ObjectAllocationOutsideTLAB`),
`jdk.JavaMonitorEnter#threshold=1ms`, or a file from `jfr configure`.

Key events: `jdk.ExecutionSample` (CPU), `jdk.ObjectAllocationSample` (allocation pressure),
`jdk.JavaMonitorEnter` / `jdk.ThreadPark` (contention), `jdk.GarbageCollection` and
`jdk.GCPhasePause` (pauses, with `cause`), `jdk.SocketRead` / `jdk.FileRead` (I/O latency),
`jdk.VirtualThreadPinned`, `jdk.OldObjectSample` (leak candidates), `jdk.ZAllocationStall`.

JDK 25 additions:
- CPU-time sampling (JEP 509, experimental, Linux only): `-XX:StartFlightRecording=jdk.CPUTimeSample#enabled=true,filename=cpu.jfr`
  then `jfr view cpu-time-hot-methods cpu.jfr`; rate via `jdk.CPUTimeSample#throttle=10ms` (one
  sample per 10 ms of CPU per thread) or `=500/s` (the default).
- Method timing and tracing (JEP 520): `-XX:StartFlightRecording:method-timing=com.acme.ExportService::render,filename=t.jfr`
  then `jfr view method-timing t.jfr`; filters accept `Class`, `Class::method`, `::<clinit>`,
  `@annotation`; `jcmd <pid> JFR.start method-timing=@jakarta.ws.rs.GET` on a live JVM.
- Cooperative sampling (JEP 518) makes stack sampling safer; no flags needed.

Recordings contain environment variables and system properties: run
`jfr scrub --exclude-events InitialEnvironmentVariable,InitialSystemProperty in.jfr out.jfr`
before sharing (JDK 27 adds in-process redaction, JEP 536).

## 6. async-profiler 4 and JMC

```bash
asprof -d 30 -f /tmp/cpu.html <pid>                        # CPU flame graph incl. native + kernel frames
asprof -e alloc -d 30 -f /tmp/alloc.html <pid>             # allocation flame graph (TLAB sampling)
asprof -e lock -d 30 -f /tmp/lock.html <pid>               # contended monitors and locks
asprof -e wall -t -i 50ms -d 30 -f /tmp/wall.html <pid>    # wall clock per thread: blocking, sleeping
asprof -e cpu --alloc 512k --lock 10ms -d 60 -f /tmp/all.jfr <pid>   # several events: JFR output only
jfrconv --alloc /tmp/all.jfr /tmp/alloc.html                # pick one event type per flame graph
jfrconv --diff before.jfr after.jfr /tmp/diff.html          # differential flame graph
```

- Start the JVM with `-XX:+UnlockDiagnosticVMOptions -XX:+DebugNonSafepoints` for accurate
  inlined frames (not needed when the profiler is loaded at startup via
  `-agentpath:/opt/async-profiler/lib/libasyncProfiler.so=start,event=cpu,file=/tmp/p.jfr`).
- Kernel stacks for non-root need `sysctl kernel.perf_event_paranoid=1` and
  `kernel.kptr_restrict=0`. Containers block `perf_event_open` by default: relax seccomp
  (`--security-opt seccomp=unconfined`, possibly `--cap-add SYS_ADMIN`), use `--fdtransfer`, or
  fall back to `-e ctimer`. From the host, pass the host PID.
- `--all` turns on cpu, wall, alloc, live, lock and nativemem together: not for production.
- JDK Mission Control opens `.jfr` files from both JFR and async-profiler; start with its
  Automated Analysis page, then Method Profiling, Memory, Lock Instances and the GC views.

## 7. Heap analysis

```bash
jcmd <pid> GC.class_histogram > /tmp/h1.txt       # live objects (forces a full GC); repeat later -> h2
jcmd <pid> GC.heap_dump /dumps/heap.hprof         # full GC + pause; file ~ live set; -gz=1 to compress
./ParseHeapDump.sh /dumps/heap.hprof org.eclipse.mat.api:suspects   # headless MAT leak report (zip)
```

Eclipse MAT procedure: give MAT more `-Xmx` (in `MemoryAnalyzer.ini`) than the dump size;
open Leak Suspects; then Dominator Tree sorted by retained heap; on the top suspect use
Path to GC Roots excluding weak/soft/phantom references; group the histogram by class loader
for metaspace leaks. Trend without dumps: diff two histograms taken 10-30 min apart under
steady load (script in [jcmd and heap diagnostics](references/jcmd-heap-diagnostics.md)); a class
whose bytes grow monotonically across several diffs is the lead.

## 8. JMH

```java
@State(Scope.Benchmark)
@BenchmarkMode(Mode.AverageTime) @OutputTimeUnit(TimeUnit.NANOSECONDS)
@Warmup(iterations = 5, time = 1) @Measurement(iterations = 10, time = 1) @Fork(2)
public class ParseBench {
    @Param({"16", "4096"}) int size;              // non-final state: no constant folding
    String input;
    @Setup public void setup() { input = Inputs.json(size); }
    @Benchmark public Doc parse() { return Parser.parse(input); }        // returned: no dead-code elimination
    @Benchmark public void parseTwice(Blackhole bh) { bh.consume(Parser.parse(input)); bh.consume(Parser.parse(input)); }
}
```

```bash
mvn archetype:generate -DinteractiveMode=false -DarchetypeGroupId=org.openjdk.jmh \
  -DarchetypeArtifactId=jmh-java-benchmark-archetype -DgroupId=com.acme -DartifactId=bench -Dversion=1.0
mvn -q clean verify && java -jar target/benchmarks.jar ParseBench -prof gc -rf json -rff /tmp/parse.json
java -jar target/benchmarks.jar ParseBench -p size=4096 \
  -prof 'async:libPath=/opt/async-profiler/lib/libasyncProfiler.so;output=flamegraph;dir=/tmp/prof'
```

Read `gc.alloc.rate.norm` (bytes per operation) from `-prof gc`; 0 B/op means escape analysis
removed the allocation. Report the score with its error column; a difference inside the
overlap of the error bars is noise. Rules: at least 2 forks, warm-up before measurement, no
manual loops inside a benchmark, no `System.nanoTime()` harnesses, inputs from `@State` fields,
results returned or sunk into a `Blackhole`. `-lprof` lists profilers (`gc`, `jfr`, `stack`, `async`).

## 9. Startup

| Technique | JDK | How | Gain / cost |
|---|---|---|---|
| default CDS archive | 12+ | on by default | baseline |
| AppCDS dynamic archive | 13+ (auto-create 19+) | `-XX:ArchiveClassesAtExit=app.jsa`, run with `-XX:SharedArchiveFile=app.jsa`; or `-XX:+AutoCreateSharedArchive -XX:SharedArchiveFile=app.jsa` | modest startup gain |
| AOT cache (class loading + linking) | 24 (JEP 483) | `-XX:AOTMode=record -XX:AOTConfiguration=app.aotconf`, then `-XX:AOTMode=create ... -XX:AOTCache=app.aot`, run with `-XX:AOTCache=app.aot` | Spring PetClinic 4.486 s -> 2.604 s (42%) |
| one-step AOT cache | 25 (JEP 514) | training run `java -XX:AOTCacheOutput=app.aot -jar app.jar`, then `-XX:AOTCache=app.aot` | needs about 2x heap memory during creation |
| AOT method profiles | 25 (JEP 515) | stored automatically from the training run | faster warm-up to peak |
| AOT cache with ZGC | 26 (JEP 516) | any GC; `-XX:+AOTStreamableObjects` forces the GC-agnostic format | |
| GraalVM native image | GraalVM / Mandrel | `native-image`, Spring Boot `nativeCompile`, Quarkus `-Dnative` | ms startup, low RSS; closed world, reflection config, long builds, lower peak without PGO |
| CRaC checkpoint/restore | vendor JDKs with CRaC | framework support in Spring and Quarkus | near-instant warm start |

AOT cache rules: same JDK build, OS and CPU architecture; class path of JAR files only (no
directories), identical or extended at the end; no `--add-opens`/`--add-exports` differences;
an unusable cache is ignored with a warning (`-XX:AOTMode=on`, renamed `required` in 27, makes
it fatal). The training run must exercise real code paths: a cache from an idle start helps
startup only. Spring Boot on Java 25+: `java -Djarmode=tools -jar app.jar extract --destination
application`, then in `application/` run `java -XX:AOTCacheOutput=app.aot
-Dspring.context.exit=onRefresh -jar app.jar`, and start with `-XX:AOTCache=app.aot`.
Spring AOT processing (`process-aot`, required for native images) precomputes bean
definitions; on the JVM it is used only with `-Dspring.aot.enabled=true`. Lazy initialization
(`spring.main.lazy-initialization=true`) trades startup for first-request latency and later
failure detection.

## 10. Code-level performance

- Compact object headers: `-XX:+UseCompactObjectHeaders` (product in 25, JEP 519; on by default
  in 27, JEP 534, opt out with `-XX:-UseCompactObjectHeaders`) shrinks headers from 12 to 8
  bytes; JEP figures for SPECjbb2015: 22% less heap, 8% less CPU. Measure on your workload.
- Allocation: presize collections and `StringBuilder`s, reuse buffers, avoid `Stream<Integer>`
  and boxing in hot loops (`IntStream`, primitive arrays), no `String.format` on hot paths,
  parameterized logging (`log.debug("id={}", id)`), no exceptions for control flow.
- Escape analysis scalar-replaces objects that do not escape, but only after inlining: small
  hot methods inline under `MaxInlineSize` (35 bytecodes) or `FreqInlineSize` (325); call sites
  seeing more than two receiver types (megamorphic) do not inline. Verify with `-prof gc`.
- JIT logs only to answer a specific question: `-XX:+PrintCompilation`,
  `-XX:+UnlockDiagnosticVMOptions -XX:+PrintInlining`, `-XX:+LogCompilation` for JITWatch.
  "CodeCache is full. Compiler has been disabled" means raise `-XX:ReservedCodeCacheSize`.
- String `+=` in a loop allocates per iteration: one presized `StringBuilder` across the loop.
- False sharing on hot counters: `LongAdder`, manual padding, or `@jdk.internal.vm.annotation.Contended`
  (needs `--add-exports java.base/jdk.internal.vm.annotation=ALL-UNNAMED` and `-XX:-RestrictContended`).

## 11. Pitfalls

| Pitfall | Consequence | Instead |
|---|---|---|
| copying flag sets from blog posts | conflicting ergonomics, worse pauses | baseline flags + evidence-driven changes |
| `-Xmx` equal to the container limit | OOMKilled from native memory | budget per section 3 |
| lowering `MaxGCPauseMillis` to 10 on G1 | throughput loss, still misses the goal | ZGC for single-digit ms SLOs |
| profiling a cold JVM | interpreter and JIT noise | warm up, then record |
| heap dump on a 30 GB heap in production without planning | multi-second pause, disk full | histogram diffs first; dump from a drained instance |
| microbenchmark without JMH | dead-code elimination, constant folding | JMH with forks and blackholes |
| JFR or asprof output shared as-is | leaks env vars, hostnames, paths | `jfr scrub` |
| AOT cache from a different JDK build or class path | silently ignored | rebuild the cache in the image build; `AOTMode=on`/`required` in CI |

## 12. Worked example: p99 spikes -> humongous allocations -> chunked output

Setup: order-export service, JDK 21, G1, `-Xms8g -Xmx8g`; `jcmd <pid> GC.heap_info` reports
`region size 4096K`, so any object of 2 MB or more is humongous. Symptom: p50 35 ms, p99 920 ms
in bursts; CPU normal.

Step 1, GC log evidence:

```bash
grep -E 'Pause .*[0-9]ms$' gc.log | grep -oE 'Pause [A-Za-z]+( \([^)]*\))*' | sort | uniq -c | sort -rn
#  1874 Pause Young (Normal) (G1 Evacuation Pause)
#   214 Pause Young (Concurrent Start) (G1 Humongous Allocation)
#     3 Pause Full (G1 Compaction Pause)
grep -E 'Humongous regions:' gc.log | tail -2         # e.g. "Humongous regions: 612->38"
grep -E 'Evacuation Failure|Pause Full' gc.log        # evacuation failures precede the full GCs
```

Hundreds of regions of humongous objects die within one cycle: short-lived giant arrays.

Step 2, find the allocation site with JFR (gc=high enables the outside-TLAB events):

```bash
jcmd <pid> JFR.start name=before settings=profile gc=high duration=10m filename=/tmp/before.jfr
jfr view gc-allocation-trigger /tmp/before.jfr      # top application frame: ExportController.export
jfr print --events jdk.ObjectAllocationOutsideTLAB --stack-depth 12 /tmp/before.jfr | less
# byte[] of 2-16 MB: Arrays.copyOf <- ByteArrayOutputStream.ensureCapacity <- ... <- ExportService.render
```

Step 3, fix the code: the export was built in a `ByteArrayOutputStream`, which doubles its
array (2, 4, 8, 16 MB: all humongous) and copies once more in `toByteArray()`.

```java
byte[] render(List<Order> orders) throws IOException {                   // before
    var buf = new ByteArrayOutputStream();
    try (var w = new OutputStreamWriter(buf, StandardCharsets.UTF_8)) {
        for (Order o : orders) w.write(o.toCsvLine());
    }
    return buf.toByteArray();
}

void render(List<Order> orders, OutputStream response) throws IOException {   // after: stream, 64 KiB buffer
    try (var w = new BufferedWriter(new OutputStreamWriter(response, StandardCharsets.UTF_8), 64 * 1024)) {
        for (Order o : orders) w.write(o.toCsvLine());
    }
}
```

If a full body must stay in memory, keep it as a list of 1 MiB chunks (below the 2 MB
threshold). Raising `-XX:G1HeapRegionSize=16m` would only move the threshold to 8 MB and cut
the region count to 512: a mitigation, not a fix.

Step 4, confirm with the same recording settings after deploying:

```bash
jcmd <pid> JFR.start name=after settings=profile gc=high duration=10m filename=/tmp/after.jfr
jfr view gc-pauses /tmp/before.jfr; jfr view gc-pauses /tmp/after.jfr       # compare P99 and Maximum
jfr print --events jdk.GarbageCollection /tmp/after.jfr | grep -c 'G1 Humongous Allocation'
```

Illustrative outcome for this scenario: humongous-triggered GCs 214 -> 0 per 10 min, GC pause
P99 377 ms -> 21 ms, no full GCs, service p99 920 ms -> 61 ms. Keep the before/after `.jfr`
files and the gc.log excerpts with the change for review.

Related: `java-virtual-threads`, `java-modern-language`, `java-spring-boot`,
`java-build-maven-gradle`, `java-testing-junit`, `performance-optimization`, hub `java-craft`.
