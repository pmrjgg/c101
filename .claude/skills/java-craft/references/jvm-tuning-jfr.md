# JVM tuning, GC selection, JFR and profiling

## 1. GC selection

| Workload | Collector | Flags | Notes |
|---|---|---|---|
| general services, heaps 1-32 GB | G1 (default) | `-XX:MaxGCPauseMillis=200` (default) | tune pause goal, not region internals |
| latency-sensitive, p99 pause < 1-10 ms, heaps up to TBs | generational ZGC | `-XX:+UseZGC` | generational is the only mode since JDK 24; give 10-20% heap headroom |
| low-pause alternative | generational Shenandoah (product in 25) | `-XX:+UseShenandoahGC -XX:ShenandoahGCMode=generational` | availability depends on the JDK vendor build |
| batch throughput, pauses irrelevant | Parallel | `-XX:+UseParallelGC` | best raw throughput |
| tiny containers (< 2 CPUs or < ~1.8 GB) | Serial (JVM auto-selects) | `-XX:+UseSerialGC` | do not fight it; give the container more CPU if pauses matter |

Rule: pick the collector from the latency SLO, then size the heap; tune further only with GC
logs showing a specific problem.

## 2. Container and memory flags (baseline for services)

```bash
JAVA_OPTS="
  -XX:MaxRAMPercentage=75.0            # heap share of the container limit; leave room for native
  -XX:InitialRAMPercentage=75.0        # avoid resize churn for steady services
  -XX:+ExitOnOutOfMemoryError          # let the orchestrator restart a broken JVM
  -XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/dumps
  -Xlog:gc*,safepoint:file=/logs/gc.log:time,uptime,level,tags:filecount=5,filesize=20m
  -XX:NativeMemoryTracking=summary     # small overhead; enables jcmd VM.native_memory
"
```

Native memory budget = heap + metaspace (class count) + code cache (240 MB max default) + thread
stacks (~1 MB per platform thread; virtual threads live on the heap) + direct buffers (Netty)
+ GC structures (G1 ~ several % of heap) + malloc arenas. When the container is OOM-killed with
the heap well under `-Xmx`, compare `jcmd <pid> VM.native_memory summary` snapshots over time.

`-XX:ActiveProcessorCount=N` when CPU quotas mislead the JVM's ergonomics (thread pool and GC
thread sizing). `-XX:+UseCompactObjectHeaders` (product in 25) cuts object header size from
12 to 8 bytes: often 10-20% less heap for object-heavy workloads; test before enabling widely.

## 3. Reading GC logs

| Log signal (G1) | Meaning | Action |
|---|---|---|
| frequent `Pause Young (Normal)` with high promotion | short-lived objects survive | larger young gen (raise heap), reduce allocation |
| `Pause Young (Concurrent Start)` then `Pause Remark` long | marking pressure | more heap headroom, check `InitiatingHeapOccupancyPercent` (adaptive by default) |
| `To-space exhausted` / evacuation failure | not enough free regions | more heap, lower live set |
| `Humongous` allocations | objects >= half a region (e.g. huge arrays/strings) | `-XX:G1HeapRegionSize=16m/32m`, or avoid giant arrays |
| `Pause Full (G1 Compaction)` | fallback full GC | live set too large for heap; heap dump and analyze |
| ZGC `Allocation Stall` | allocation outran concurrent collection | more heap headroom, more CPU, lower allocation rate |

Tools: GCeasy-style analyzers, JMC's GC view, or `jfr view gc` (JDK 21+ `jfr view`).

## 4. JFR

```bash
# start at launch
java -XX:StartFlightRecording=duration=0,filename=/rec/app.jfr,settings=profile,maxage=1h -jar app.jar
# on a running JVM
jcmd <pid> JFR.start name=perf settings=profile duration=120s filename=/tmp/perf.jfr
jcmd <pid> JFR.dump name=perf filename=/tmp/now.jfr      # snapshot of a continuous recording
jcmd <pid> JFR.stop name=perf
# analyze from the command line (JDK 21+)
jfr summary /tmp/perf.jfr
jfr view hot-methods /tmp/perf.jfr
jfr view allocation-by-site /tmp/perf.jfr
jfr view gc /tmp/perf.jfr
jfr help view                                             # list of all predefined views
jfr print --events jdk.VirtualThreadPinned /tmp/perf.jfr
```

`settings=default` (~1% overhead) for always-on; `settings=profile` (~2%) for investigations.
Key events: `jdk.ExecutionSample` (CPU), `jdk.ObjectAllocationSample` (allocation),
`jdk.JavaMonitorEnter`/`jdk.ThreadPark` (contention), `jdk.GarbageCollection`,
`jdk.VirtualThreadPinned`, `jdk.SocketRead`/`jdk.FileRead` (I/O latency). JDK 25 adds
experimental CPU-time sampling on Linux and method timing/tracing events
(`jdk.MethodTiming`, `jdk.MethodTrace`) configured by method filters; check `jfr configure --help`
on the JDK in use.

JDK Mission Control (JMC) gives the automated analysis page ("Rules") that flags common issues.

## 5. async-profiler

```bash
asprof -e cpu -d 30 -f cpu.html <pid>             # CPU flame graph incl. native and kernel frames
asprof -e alloc -d 30 -f alloc.html <pid>          # allocation flame graph
asprof -e wall -t -d 30 -f wall.html <pid>         # wall clock per thread: finds blocking
asprof -e lock -d 30 -f lock.html <pid>            # lock contention
```

Needs `perf_event_paranoid <= 1` (or falls back to itimer) and `-XX:+UnlockDiagnosticVMOptions
-XX:+DebugNonSafepoints` for accurate inlined frames. JMH integrates it with
`-prof async:libPath=/path/libasyncProfiler.so;output=flamegraph`.

## 6. Diagnostic commands

| Question | Command |
|---|---|
| JVM flags actually in effect | `jcmd <pid> VM.flags -all | grep -v default` or `java -XX:+PrintFlagsFinal -version` |
| heap usage summary | `jcmd <pid> GC.heap_info` |
| what fills the heap (quick) | `jcmd <pid> GC.class_histogram | head -30` |
| full heap dump | `jcmd <pid> GC.heap_dump /tmp/heap.hprof` → Eclipse MAT (dominator tree, leak suspects) |
| thread dump incl. virtual threads | `jcmd <pid> Thread.dump_to_file -format=json /tmp/threads.json` |
| classic thread dump | `jcmd <pid> Thread.print` |
| native memory | `jcmd <pid> VM.native_memory summary` (needs NMT flag at start) |
| system properties / command line | `jcmd <pid> VM.system_properties`, `VM.command_line` |
| JIT compilation issues | `-Xlog:jit+compilation=debug`, JITWatch |

## 7. Startup and warm-up

| Technique | JDK | How | Gain |
|---|---|---|---|
| Class Data Sharing (AppCDS) | 10+ | `-XX:ArchiveClassesAtExit=app.jsa` then `-XX:SharedArchiveFile=app.jsa` | 10-30% startup |
| AOT class loading and linking cache | 24 (JEP 483) | `-XX:AOTMode=record -XX:AOTConfiguration=app.aotconf` → `-XX:AOTMode=create -XX:AOTConfiguration=app.aotconf -XX:AOTCache=app.aot` → run with `-XX:AOTCache=app.aot` | up to ~40% startup |
| one-step AOT cache creation | 25 (JEP 514) | training run with `-XX:AOTCacheOutput=app.aot`, then `-XX:AOTCache=app.aot` | same, simpler |
| AOT method profiles | 25 (JEP 515) | stored in the AOT cache from the training run | faster warm-up to peak |
| GraalVM native image | GraalVM / Mandrel | `native-image` (Quarkus `-Dnative`, Spring Boot `nativeCompile`) | ms startup, lower RSS; closed-world constraints, reflection config |
| CRaC checkpoint/restore | vendor JDKs with CRaC | framework support in Spring/Quarkus | near-instant warm start |

The training run must exercise representative code paths; a cache from an idle start helps
startup only.

## 8. JIT and code-level performance notes

- Megamorphic call sites (> 2 receiver types) are not inlined; in hot loops prefer final
  classes, sealed hierarchies with switch, or splitting loops by type.
- Escape analysis removes allocations of objects that do not escape; it fails across
  non-inlined calls. Small hot methods inline when under `-XX:MaxInlineSize` (35 bytecodes) or
  `FreqInlineSize` (325) for hot ones.
- Autoboxing in generic collections and streams of wrappers (`Stream<Integer>`) allocates:
  use `IntStream`, primitive arrays, or primitive collections.
- String concatenation in loops is compiled to `StringConcatFactory` per expression; build with
  `StringBuilder` (presized) across iterations.
- `String.format` is slow; use concatenation or `StringBuilder` in hot paths, and parameterized
  logging (`log.debug("x={}", x)`) so disabled levels cost nothing.
- Exceptions with stack traces are expensive; do not use them for control flow.
- False sharing in hot counters: `LongAdder`, or `@jdk.internal.vm.annotation.Contended`
  (requires `--add-exports` and `-XX:-RestrictContended`), or manual padding.
