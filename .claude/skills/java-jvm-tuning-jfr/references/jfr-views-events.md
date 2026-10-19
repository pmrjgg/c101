# JFR views, events and settings (JDK 25)

Values below come from the JDK 25 GA `default.jfc`, `profile.jfc` and `jfr view` definitions.
`jfr view` and `jcmd <pid> JFR.view` exist since JDK 21; `jfr view all-views <file>` lists them.

## 1. Views worth knowing

| Question | `jfr view <name>` | Source events |
|---|---|---|
| where does CPU go (Java frames) | `hot-methods` | `jdk.ExecutionSample` |
| CPU-time sampler result (25, Linux) | `cpu-time-hot-methods`, `cpu-time-statistics` | `jdk.CPUTimeSample` |
| who allocates | `allocation-by-site`, `allocation-by-class`, `allocation-by-thread` | `jdk.ObjectAllocationSample` |
| which code triggered GCs | `gc-allocation-trigger` | `jdk.AllocationRequiringGC` (needs `gc=high`) |
| GC list and pause statistics | `gc`, `gc-pauses` (P90/P95/P99/P99.9/max), `gc-pause-phases`, `gc-concurrent-phases` | GC events |
| GC and heap configuration | `gc-configuration`, `heap-configuration` | |
| lock contention | `contention-by-site`, `contention-by-class`, `contention-by-thread`, `contention-by-address` | `jdk.JavaMonitorEnter` |
| blocking latencies by kind | `latencies-by-type` | monitor wait/enter, park, sleep, socket and file I/O |
| slow I/O | `file-reads-by-path`, `file-writes-by-path`, `socket-reads-by-host`, `socket-writes-by-host` | |
| pinned virtual threads | `pinned-threads` | `jdk.VirtualThreadPinned` |
| exceptions | `exception-count`, `exception-by-type`, `exception-by-message`, `exception-by-site` | |
| method timing (25) | `method-timing`, `method-calls` | `jdk.MethodTiming`, `jdk.MethodTrace` |
| leaks over time | `memory-leaks-by-class`, `memory-leaks-by-site` | `jdk.OldObjectSample` |
| JIT behaviour | `longest-compilations`, `compiler-statistics`, `deoptimizations-by-reason`, `deoptimizations-by-site` | |
| safepoints and VM operations | `safepoints`, `vm-operations` | |
| native memory (NMT on) | `native-memory-committed`, `native-memory-reserved` | |
| container limits and throttling | `container-configuration`, `container-cpu-usage`, `container-cpu-throttling`, `container-memory-usage` | |
| flags and environment | `jvm-flags`, `system-properties`, `environment-variables`, `jvm-information` | |
| threads | `thread-count`, `thread-cpu-load`, `thread-allocation`, `thread-start` | |

`jfr view --width 200 --cell-height 10 contention-by-site rec.jfr` widens tables and shows more
stack frames; any event type name also works as a view (`jfr view GarbageCollection rec.jfr`).
`jfr view --verbose <view>` prints the underlying query.

## 2. Key events: default vs profile settings

| Event | `default` | `profile` | Notes |
|---|---|---|---|
| `jdk.ExecutionSample` | every 20 ms | every 10 ms | Java CPU samples (safepoint-bias reduced; cooperative sampling in 25) |
| `jdk.CPUTimeSample` | off, throttle 500/s | off, throttle 10ms | enable explicitly; Linux only; experimental in 25 |
| `jdk.ObjectAllocationSample` | 150/s | 300/s | weighted samples; `allocation-profiling=high` = 1000/s |
| `jdk.JavaMonitorEnter`, `jdk.ThreadPark` | threshold 20 ms | 10 ms | `locking-threshold` option |
| `jdk.SocketRead`, `jdk.FileRead` | threshold 1 ms, 100/s | 1 ms, 300/s | |
| `jdk.VirtualThreadPinned` | threshold 20 ms | 20 ms | lower with `jdk.VirtualThreadPinned#threshold=1ms` |
| `jdk.OldObjectSample` | on, no stack traces | on, stack traces | `memory-leaks=gc-roots` + `path-to-gc-roots=true` for leak paths (costly) |
| `jdk.GarbageCollection`, `jdk.GCPhasePause` | on, threshold 0 | on | `cause` field names the GC trigger |
| `jdk.ObjectAllocationOutsideTLAB`, `jdk.AllocationRequiringGC` | off | off | on with `gc=high` |
| `jdk.ZAllocationStall` | on, threshold 0 | on | ZGC only |
| `jdk.MethodTiming`, `jdk.MethodTrace` | on, empty filter | on, empty filter | active only with a `method-timing`/`method-trace` filter |
| `jdk.ThreadDump` | once per chunk | every 60 s | `thread-dump` option |

## 3. Options usable on `-XX:StartFlightRecording`, `jcmd JFR.start` and `jfr configure`

| Option | Values (default.jfc default) |
|---|---|
| `gc` | off, normal (default), detailed, high, all |
| `allocation-profiling` | off, low (150/s, default), medium (300/s), high (1000/s), maximum |
| `method-profiling` | off, normal (default), high, max |
| `compiler` | off, normal (default), detailed, all |
| `exceptions` | off, throttled (default: errors + 100 exceptions/s), all |
| `memory-leaks` | off, types (default), stack-traces, gc-roots |
| `thread-dump` | off, once (default), 60s, 10s, 1s |
| `locking-threshold` | timespan, default 20 ms |
| `method-timing`, `method-trace` | filters: `com.acme.Foo`, `com.acme.Foo::bar`, `::<clinit>`, `::<init>`, `@com.acme.Timed`; `;` separates |
| `class-loading` | false (default) / true |

```bash
jfr configure --input profile.jfc gc=high locking-threshold=5ms jdk.VirtualThreadPinned#threshold=1ms --output /tmp/investigate.jfc
java -XX:StartFlightRecording:settings=/tmp/investigate.jfc,filename=/tmp/i.jfr -jar app.jar
jcmd <pid> JFR.start settings=profile allocation-profiling=high duration=5m filename=/tmp/alloc.jfr
jcmd <pid> JFR.view maxage=5m gc-pauses        # query the in-memory recording of a live JVM
```

## 4. Recording management

| Task | Command |
|---|---|
| continuous recording kept on disk | `-XX:StartFlightRecording:name=cont,settings=default,maxage=6h,maxsize=1g,dumponexit=true,filename=/rec/app.jfr` |
| snapshot the last 10 minutes | `jcmd <pid> JFR.dump name=cont maxage=10m filename=/tmp/last10m.jfr` |
| list recordings | `jcmd <pid> JFR.check` |
| repository and buffer settings | `jcmd <pid> JFR.configure repositorypath=/rec stackdepth=128` (stack depth above 64 costs) |
| recover after a crash | `jfr assemble <repository-dir> recovered.jfr` |
| split or shrink | `jfr disassemble --max-chunks 5 big.jfr`; `jfr scrub --include-events 'jdk.GC*' in.jfr out.jfr` |
| remove sensitive data before sharing | `jfr scrub --exclude-events InitialEnvironmentVariable,InitialSystemProperty in.jfr out.jfr` |
| machine-readable output | `jfr print --json --events jdk.GarbageCollection rec.jfr`; `jfr summary rec.jfr` |

## 5. Streaming JFR inside the application (JDK 14+)

```java
var rs = new RecordingStream();                         // keep a reference; close() on shutdown
rs.enable("jdk.GCPhasePause").withThreshold(Duration.ofMillis(10));
rs.enable("jdk.VirtualThreadPinned").withStackTrace();
rs.onEvent("jdk.GCPhasePause", e -> gcPauseTimer.record(e.getDuration()));
rs.onEvent("jdk.VirtualThreadPinned", e -> log.warn("pinned {} ms", e.getDuration().toMillis()));
rs.startAsync();
```

Use this to export pause and pinning metrics continuously; keep handlers cheap (they run on
the stream's thread).

## 6. JDK Mission Control

Open `.jfr` (JFR or async-profiler output). Order of reading: Automated Analysis Results
(rules flag GC pressure, contention, hot methods, exceptions), Method Profiling (flame view),
Memory (allocation by class and stack), Lock Instances, Threads (timeline of blocking), Garbage
Collections, Environment (flags, container limits). Compare two recordings side by side by
opening both and using the same page on each.
