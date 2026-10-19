---
name: java-craft
description: "Modern Java (21 to 25 LTS) expertise pack covering records, sealed types, pattern matching, virtual threads and structured concurrency, streams and gatherers, collections, JVM GC tuning and JFR, JMH, Maven and Gradle, JUnit 5/6 with AssertJ, Spring Boot and Quarkus essentials, and common pitfalls. Load when writing, reviewing, debugging, profiling or tuning Java code and JVM services."
when_to_use: "Any task touching .java files, pom.xml, build.gradle(.kts), JVM flags, GC logs or JFR recordings, Spring/Quarkus services, thread dumps, Java benchmarks, or Java CI gates."
---

# Java craft

Baseline: Java 21 LTS and Java 25 LTS (September 2025). Final in 25 and usable without flags:
records, sealed types, pattern matching for `switch` and record patterns, virtual threads,
sequenced collections, unnamed variables `_` (22), FFM API (22), stream gatherers (24), class-file
API (24), virtual threads no longer pinned by `synchronized` (24), scoped values, flexible
constructor bodies, module import declarations, compact source files and instance `main`
(all 25), compact object headers as a product option (25). Still preview in 25 (needs
`--enable-preview`): structured concurrency (API reshaped in 25), primitive types in patterns,
stable values. Check the target release (`maven.compiler.release` / toolchain) before using any
of these, and look up framework APIs with `mcp__context7__resolve-library-id` then `mcp__context7__query-docs` (Spring Boot 4 moved to
Jackson 3 and JSpecify nullness).

Deep material:
[JVM tuning, GC, JFR and profiling](references/jvm-tuning-jfr.md) |
[concurrency: virtual threads, structured concurrency, JMM](references/concurrency-loom.md) |
[build, test and framework recipes](references/build-test-frameworks.md)

## 1. Orient in a repo

```bash
java -version; ./mvnw -v 2>/dev/null || ./gradlew -v
grep -nE '<release>|maven.compiler.release|<java.version>' pom.xml 2>/dev/null
grep -nE 'languageVersion|JavaLanguageVersion|sourceCompatibility' build.gradle* 2>/dev/null
grep -n 'enable-preview' pom.xml build.gradle* 2>/dev/null
grep -rn 'spring-boot\|quarkus' pom.xml build.gradle* gradle/libs.versions.toml 2>/dev/null | head -5
```

Record: release level, build tool and wrapper version, framework and version, test stack,
static analysis (Error Prone, NullAway, SpotBugs, Checkstyle), whether preview is enabled.

## 2. The gate

| Step | Maven | Gradle | Blocks when |
|---|---|---|---|
| Compile with lint | `-Xlint:all -Werror` in compiler args | `options.compilerArgs += ["-Xlint:all", "-Werror"]` | warnings |
| Unit + integration tests | `./mvnw -B -ntp verify` | `./gradlew build` | failure |
| Static analysis | Error Prone + NullAway, SpotBugs | same plugins | new findings |
| Format | `spotless:check` | `spotlessCheck` | diff |
| Dependency convergence | enforcer `dependencyConvergence` | `failOnVersionConflict()` or dependency analysis plugin | conflicts |
| Vulnerabilities | OWASP dependency-check or `osv-scanner` on the lockfile/SBOM | same | high/critical reachable CVE |

## 3. Data modelling with records and sealed types

| Need | Construct |
|---|---|
| immutable data carrier, value equality | `record` |
| closed set of alternatives | `sealed interface` + `record` implementations |
| validation / normalization on construction | compact canonical constructor |
| defensive copies of collections | `List.copyOf(list)` in the compact constructor |
| entity with identity and lifecycle (JPA) | class, not record (proxies, mutability) |
| fixed set of constants with behavior | `enum` |

```java
public sealed interface PaymentResult permits Approved, Declined, Pending {}
public record Approved(String authCode, Money amount) implements PaymentResult {}
public record Declined(String reason, boolean retryable) implements PaymentResult {}
public record Pending(Instant retryAt) implements PaymentResult {}

public record Money(BigDecimal amount, Currency currency) {
    public Money {                                         // compact constructor
        Objects.requireNonNull(currency, "currency");
        if (amount.scale() > currency.getDefaultFractionDigits())
            throw new IllegalArgumentException("scale " + amount.scale() + " > currency digits");
    }
}

static String describe(PaymentResult r) {
    return switch (r) {                                   // exhaustive: no default
        case Approved(var code, var amt)      -> "approved " + code + " " + amt;
        case Declined(var reason, var retry) when retry -> "retryable decline: " + reason;
        case Declined(var reason, _)          -> "declined: " + reason;
        case Pending(var at)                  -> "pending until " + at;
    };
}
```

Rules:
- No `default` branch on switches over sealed types: adding a permitted subtype must break
  compilation at every switch that needs updating.
- Guards (`when`) must come before the unguarded case for the same type (dominance is a compile error).
- `case null` is explicit; without it, `switch` throws `NullPointerException` on null.
- Records with array components get reference equality for the array: wrap or override.
- `Optional` only as a return type; never fields, parameters, or collection elements.

## 4. Virtual threads and structured concurrency (summary; details in [concurrency-loom](references/concurrency-loom.md))

| Workload | Use |
|---|---|
| many concurrent blocking I/O calls (HTTP, JDBC, RPC) | virtual threads: `Executors.newVirtualThreadPerTaskExecutor()` |
| CPU-bound parallel work | platform threads: `ForkJoinPool`, parallel streams, fixed pool sized to cores |
| bounded concurrency against a resource | `Semaphore` around the call (do not pool virtual threads) |
| request-scoped context | `ScopedValue` (final in 25) instead of `ThreadLocal` |
| fan-out with cancellation and error propagation | `StructuredTaskScope` (preview) or `ExecutorService` in try-with-resources + `Future`s |

Rules: never pool virtual threads; size connection pools deliberately (they become the real
limit); on Java 21-23 replace `synchronized` around blocking I/O in hot paths with
`ReentrantLock` (pinning); detect pinning with the JFR `jdk.VirtualThreadPinned` event; thread
dumps via `jcmd <pid> Thread.dump_to_file -format=json dump.json`.

## 5. Streams, gatherers and collections

Use streams for declarative transformations; use loops for complex control flow, checked
exceptions, early exits with side effects, or measured hot paths.

```java
Map<Status, Long> counts = orders.stream()
    .collect(Collectors.groupingBy(Order::status, () -> new EnumMap<>(Status.class), Collectors.counting()));

Map<String, User> byEmail = users.stream()
    .collect(Collectors.toMap(User::email, Function.identity(), (a, b) -> a));  // merge fn: duplicates otherwise throw

List<List<Event>> batches = events.stream().gather(Gatherers.windowFixed(100)).toList();  // 24+

List<Response> rs = urls.stream()
    .gather(Gatherers.mapConcurrent(16, this::fetch))      // virtual threads, max 16 in flight, order kept
    .toList();
```

- `Stream.toList()` returns an unmodifiable list; `Collectors.toList()` makes no guarantee.
- Parallel streams run on the common pool; use them only for CPU-bound work on splittable
  sources (arrays, `ArrayList`, `IntStream.range`) with N x Q (elements x cost per element)
  above ~10,000, and never with blocking calls or shared mutable state.

| Need | Collection |
|---|---|
| default list | `ArrayList` (presize with `new ArrayList<>(n)`) |
| stack/queue/deque | `ArrayDeque` (not `Stack`, not `LinkedList`) |
| insertion-ordered map, LRU | `LinkedHashMap` (`removeEldestEntry`, access-order constructor) |
| sorted, range queries | `TreeMap` / `TreeSet` (`NavigableMap`) |
| enum keys | `EnumMap` / `EnumSet` |
| concurrent map | `ConcurrentHashMap` (`computeIfAbsent` must be short and not touch the map) |
| read-mostly listeners | `CopyOnWriteArrayList` |
| immutable constants | `List.of`, `Map.of`, `Set.of` (null-hostile, unspecified iteration order for sets/maps) |
| first/last/reversed views | `SequencedCollection` methods `getFirst`, `getLast`, `reversed` (21) |
| primitive-heavy hot path | `int[]`, fastutil / Eclipse Collections primitive maps |

Presize hash maps with `HashMap.newHashMap(expectedSize)` (19+), which accounts for load factor.

## 6. Errors and exceptions

- Checked exceptions for recoverable conditions the caller must handle at the API boundary;
  unchecked for programming errors. Do not wrap everything in `RuntimeException` without the cause.
- Always chain causes: `throw new ConfigException("loading " + path, e);`.
- Never swallow `InterruptedException`: restore with `Thread.currentThread().interrupt()` and
  exit or rethrow.
- try-with-resources for every `AutoCloseable` (streams from `Files.lines`, JDBC, HTTP responses).
- For domain results with several expected outcomes, prefer a sealed result type (section 3)
  over exceptions for control flow.

## 7. Performance procedure (details in [jvm-tuning-jfr](references/jvm-tuning-jfr.md))

1. Reproduce with a load test or JMH benchmark; warm up (JIT) before measuring.
2. Record JFR in production-like conditions:
   `jcmd <pid> JFR.start name=perf settings=profile duration=120s filename=/tmp/perf.jfr`.
3. Inspect: `jfr view hot-methods /tmp/perf.jfr`, `jfr summary`, JDK Mission Control for
   allocation, lock contention and GC; async-profiler (`asprof -e cpu,alloc -d 60 -f out.jfr <pid>`,
   then `jfrconv` to flame graphs; multiple events need JFR output, or run two HTML captures
   `-e cpu` and `-e alloc`) for flame graphs including native frames.
4. Fix the top item; confirm with JMH (`-prof gc` for bytes/op) or the load test.

| Symptom | First move |
|---|---|
| high allocation rate (> 1 GB/s) | find top allocation sites in JFR; reuse buffers, avoid boxing, streams in hot loops |
| long GC pauses on G1 with big heap | check humongous allocations, `MaxGCPauseMillis`; consider generational ZGC |
| CPU high in `HashMap.get` / `equals` | poor `hashCode`, mutable keys, oversized keys |
| lock contention in JFR (`jdk.JavaMonitorEnter`) | shrink critical sections, `ConcurrentHashMap`, `LongAdder` for counters |
| slow startup | AOT cache (`-XX:AOTCacheOutput` training run, 25), CDS, lazy init, fewer classpath scans |
| container OOM-killed with heap below `-Xmx` | native memory: threads, direct buffers, metaspace; NMT (`-XX:NativeMemoryTracking=summary`) |

## 8. JMH essentials

```java
@State(Scope.Benchmark)
@BenchmarkMode(Mode.AverageTime) @OutputTimeUnit(TimeUnit.NANOSECONDS)
@Warmup(iterations = 5, time = 1) @Measurement(iterations = 10, time = 1) @Fork(2)
public class ParseBench {
    @Param({"16", "4096"}) int size;
    String input;
    @Setup public void setup() { input = Inputs.json(size); }
    @Benchmark public Doc parse() { return Parser.parse(input); }      // return value defeats DCE
}
```

Run `java -jar target/benchmarks.jar ParseBench -prof gc` and read `gc.alloc.rate.norm`
(bytes/op). Never benchmark with `System.nanoTime()` loops; JIT dead-code elimination and
constant folding invalidate them.

## 9. Pitfalls (symptom → cause → fix)

| Symptom | Cause | Fix |
|---|---|---|
| `Integer` equality false for 1000 | `==` on boxed values (cache only -128..127) | `equals` or primitives |
| `BigDecimal` equality surprises | `equals` compares scale (`2.0` vs `2.00`) | `compareTo == 0` or normalize scale |
| entries "vanish" from `HashSet` | mutable fields in `hashCode` changed after insertion | immutable keys (records) |
| `UnsupportedOperationException` on add | `List.of`, `Arrays.asList` (fixed size), `stream.toList()` | copy into `ArrayList` |
| `ConcurrentModificationException` | modifying while iterating | `removeIf`, iterator `remove`, collect then modify |
| thread pool starvation / deadlock | blocking on futures of the same bounded pool; `parallelStream` with I/O | separate pools, virtual threads, no blocking in common pool |
| `CompletableFuture` runs on common pool | default async executor | pass an explicit executor |
| interrupt lost, shutdown hangs | swallowed `InterruptedException` | re-interrupt |
| wrong uppercase in Turkish locale | `toUpperCase()` default locale | `toUpperCase(Locale.ROOT)` |
| dates off by hours | `java.util.Date`, `SimpleDateFormat`, default zone | `java.time` with explicit `ZoneId`, `Instant` for timestamps |
| `ThreadLocal` memory leak | pooled threads keep values | `remove()` in `finally`, or `ScopedValue` |
| pinned virtual threads (21-23) | `synchronized` around blocking I/O | upgrade to 24+ or `ReentrantLock` |
| Mockito agent warnings or failures on 21+ | dynamic agent loading restrictions | configure Mockito as `-javaagent` in the test JVM args |
| reflection on `final` fields warns (26+) | deep reflection mutation of finals being restricted | constructor injection, no field mutation via reflection |

## 10. Review checklist

- [ ] Data types are records/sealed hierarchies where they model data; switches exhaustive without `default`.
- [ ] Null policy explicit (JSpecify `@NullMarked` + NullAway, or documented); no `Optional` fields/params.
- [ ] Resources in try-with-resources; exceptions chained; `InterruptedException` honored.
- [ ] Concurrency: no shared mutable state without synchronization; virtual threads not pooled;
      bounded concurrency to downstream resources; timeouts on every remote call.
- [ ] Collections chosen per section 5; no `LinkedList`/`Stack`/`Vector`/`Hashtable` in new code.
- [ ] Hot paths measured with JMH or JFR evidence; allocation per op known.
- [ ] Dependencies converge; no new CVEs; versions managed in a BOM or version catalog.
- [ ] Tests: AssertJ assertions, parameterized where tables fit, Testcontainers for real infra.

## 11. Worked example: thread-pool fan-out to virtual threads with bounded concurrency

Before: fixed pool of 200 platform threads, unbounded queue, no timeouts, interrupt swallowed.

```java
ExecutorService pool = Executors.newFixedThreadPool(200);
List<Future<Quote>> fs = suppliers.stream().map(s -> pool.submit(() -> client.quote(s))).toList();
List<Quote> quotes = new ArrayList<>();
for (Future<Quote> f : fs) {
    try { quotes.add(f.get()); } catch (Exception e) { /* ignored */ }
}
```

After (Java 21+):

```java
private static final Semaphore SUPPLIER_LIMIT = new Semaphore(64);   // downstream capacity

List<Quote> fetchQuotes(List<Supplier> suppliers) throws InterruptedException {
    try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {   // close() waits for tasks
        List<Future<Quote>> futures = suppliers.stream()
            .map(s -> executor.submit(() -> {
                SUPPLIER_LIMIT.acquire();
                try { return client.quote(s, Duration.ofSeconds(2)); }    // per-call timeout
                finally { SUPPLIER_LIMIT.release(); }
            }))
            .toList();
        List<Quote> quotes = new ArrayList<>(futures.size());
        for (var f : futures) {
            try {
                quotes.add(f.get());
            } catch (ExecutionException e) {
                log.warn("quote failed", e.getCause());                   // partial results are acceptable here
            }
        }
        return quotes;
    }
}
```

`InterruptedException` propagates; each supplier call has a timeout; concurrency against the
supplier API is capped at 64 regardless of how many virtual threads exist. With structured
concurrency (preview) the same shape becomes `StructuredTaskScope.open(...)` with a joiner that
collects successful results and cancels stragglers when the scope closes.

## Delegation hints

- GC log or JFR analysis for an incident: `debugger` with recording paths and JVM flags.
- Throughput/latency optimization with a JMH or load-test target: `code-optimizer`.
- Spring Security, deserialization and dependency CVE review: `security-auditor`.

## Granular skills

Deeper, task-specific playbooks. Load one with the Skill tool by name when the task matches; they are
listed by name only (to keep every session's context lean), so this table is their description.
A skill whose pack is not enabled in this install is off: work from this hub and say so.

| skill | load when |
|---|---|
| `java-jvm-tuning-jfr` | JVM performance and memory diagnosis: choosing a GC by latency SLO, container memory flags and native-memory budgets, OOMKilled triage with NMT, reading G1/Z... |
| `java-modern-language` | writing or reviewing Java domain code, or modernizing pre-17 code |
| `java-virtual-threads` | migrating to virtual threads or debugging Java concurrency |
