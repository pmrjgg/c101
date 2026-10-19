---
name: java-modern-language
description: "Modern Java 21-25 language and core library: feature availability by release, records, sealed hierarchies, exhaustive pattern-matching switch, record patterns and guards, unnamed variables, flexible constructor bodies, module imports, compact source files, JSpecify null policy with NullAway, exceptions, streams with gatherers, collection choice, OpenRewrite upgrades. Load when writing or reviewing Java domain code, or modernizing pre-17 code."
when_to_use: "Editing or reviewing .java domain code; instanceof/cast chains, switch on type codes, mutable DTOs or Lombok @Value to replace with records; 'the switch expression does not cover all possible input values', 'is dominated by a preceding case label', '--enable-preview' errors; NullAway or JSpecify warnings; Collectors.toMap IllegalStateException duplicate key; upgrading a codebase from Java 8/11/17 to 21 or 25."
---

# Modern Java language (21-25)

Baseline is Java 21 LTS and Java 25 LTS (GA 16 Sep 2025). JDK 26 (Mar 2026) and JDK 27
(Sep 2026) are non-LTS feature releases. Code below compiles on 21 except where it uses a feature
the table dates later (`_` 22, gatherers 24, flexible constructors and compact files 25).
Setup files for the null-checking toolchain: [null-policy setup](references/null-policy-setup.md);
migration commands and recipe lists: [modernization recipes](references/modernization-recipes.md).

## 1. Feature availability: check before you use

| Feature | Final in | Notes |
|---|---|---|
| switch expressions, text blocks | 14, 15 | |
| records, pattern `instanceof` | 16 | |
| sealed classes and interfaces | 17 | |
| pattern matching for `switch`, record patterns, sequenced collections, virtual threads | 21 | JEPs 441, 440, 431, 444 |
| unnamed variables and patterns `_`, FFM API | 22 | JEPs 456, 454; `_` is preview-only on 21 |
| stream gatherers, class-file API | 24 | JEPs 485, 484 |
| scoped values, module import declarations, compact source files + instance `main`, flexible constructor bodies | 25 | JEPs 506, 511, 512, 513 |
| primitive types in patterns / `instanceof` / `switch` | preview | 507 (25), 530 (26), 532 (27) |
| stable values, renamed lazy constants in 26 | preview | 502 (25, `StableValue`), 526 (26, `LazyConstant`), 531 (27) |
| structured concurrency | preview | 505 (25), 525 (26), 533 (27): API changes every release |

```bash
grep -nE '<release>|maven.compiler.release|<java.version>' pom.xml 2>/dev/null
grep -nE 'languageVersion|options.release|sourceCompatibility' build.gradle* 2>/dev/null
grep -rn -- '--enable-preview' pom.xml build.gradle* .mvn 2>/dev/null
javap -v target/classes/com/acme/Order.class | grep -E 'major version|minor version'
```

Class-file major version: 65 = 21, 66 = 22, 67 = 23, 68 = 24, 69 = 25, 70 = 26, 71 = 27; minor
65535 marks preview classes, which run only on the exact feature release that compiled them
(`javac --release 25 --enable-preview` output will not start on 26). Never use a preview feature
in a library or a service that upgrades JDKs independently of its code.

## 2. Data modelling: records, sealed types, enums

| Need | Use | Why |
|---|---|---|
| immutable value, equality by state (value object, DTO, event, map key) | `record` | final fields, `equals`/`hashCode`/`toString` generated |
| closed set of alternatives carrying different data | `sealed interface` + `record`s | exhaustive `switch`, compiler-checked |
| fixed set of singletons, optionally with behaviour | `enum` (may implement a sealed interface) | `EnumMap`/`EnumSet`, `switch` exhaustive |
| identity and lifecycle, JPA entity, lazy proxies | class | records are final and immutable |
| state shared by subtypes through inheritance | class | records cannot extend classes |
| invariants maintained across mutation, caches | class with private state | |

```java
public record Order(OrderId id, List<LineItem> items, Money total) {
    public Order {                                   // compact canonical constructor
        Objects.requireNonNull(id, "id");
        Objects.requireNonNull(total, "total");
        items = List.copyOf(items);                  // defensive + unmodifiable; NPE on null elements
        if (items.isEmpty()) throw new IllegalArgumentException("order " + id + " has no items");
    }
}

public record Money(BigDecimal amount, Currency currency) {
    public Money {
        Objects.requireNonNull(currency, "currency");
        if (amount.scale() > currency.getDefaultFractionDigits())
            throw new IllegalArgumentException("scale " + amount.scale() + " > " + currency);
    }
}
```

Rules:
- The compact constructor assigns parameters, not fields; fields are set after it returns.
- Array components get reference equality in `equals` (Error Prone `ArrayRecordComponent`):
  use `List<T>` or override `equals`, `hashCode` and `toString` together.
- `toString` prints every component: override it for records holding secrets or personal data.
- Permitted subtypes are `final`, `sealed` or `non-sealed`, and live in the same module (or the
  same package on the class path). Omit `permits` when all subtypes sit in the same file.
- No `default` branch on a `switch` over a sealed type: adding a permitted subtype must break
  compilation at every switch that needs updating. If a separately compiled subtype appears
  at run time, the compiler-generated fallthrough throws `MatchException`.
- A `default` belongs only where the input set is open: strings, codes from external systems.

## 3. Pattern matching

```java
sealed interface Shape {}
record Point(double x, double y) {}
record Circle(Point center, double radius) implements Shape {}
record Rect(Point topLeft, Point bottomRight) implements Shape {}
record Group(List<Shape> children) implements Shape {}

static double area(Shape s) {                                    // in final class Shapes
    return switch (s) {
        case Circle(Point _, double r)                           -> Math.PI * r * r;
        case Rect(Point(var x1, var y1), Point(var x2, var y2))  -> Math.abs((x2 - x1) * (y2 - y1));
        case Group(var children) -> children.stream().mapToDouble(Shapes::area).sum();
    };
}
```

| Rule | Example | Compiler says |
|---|---|---|
| a supertype pattern dominates a later subtype pattern | `case CharSequence cs` before `case String s` | "this case label is dominated by a preceding case label" |
| an unguarded pattern dominates a guarded one of the same type | `case Declined d` before `case Declined d when d.retryable()` | same; put guarded cases first |
| constant labels before the type pattern of the same type | `case 0 ->` before `case Integer i ->` | same |
| `default` goes last once patterns are present | | same |
| guards see bindings and must be side-effect free | `case Rect r when r.isSquare()` | |
| `switch` without `case null` throws `NullPointerException` on null | `case null, default -> "other";` combines both | |
| nested record patterns never match `null` components | `Rect(Point(var x1, var y1), var br)` with a null `topLeft` | nothing at compile time; at run time the value falls through and throws `MatchException`: reject nulls in compact constructors |

Unnamed `_` (22): unused components `case Declined(var code, _, _)`, several patterns in one
label when none binds `case Circle _, Rect _ -> "simple"`, `catch (NumberFormatException _)`,
lambda parameters `(_, v) -> v`, `for (var _ : items) count++`, `try (var _ = lock.acquire())`.

`instanceof` with patterns: `if (r instanceof Approved(var code, var amt) && amt.signum() > 0)`.
Bindings flow into the rest of the condition and, for `!(x instanceof T t)` with an early
return, into the following statements.

## 4. Newer syntax

Flexible constructor bodies (25): statements may precede `super(...)`/`this(...)` if they do not
touch `this` (no instance method calls, no field reads); simple assignments to this class's own
uninitialized fields are allowed, so overridden methods called by the superclass see them.

```java
public class PositiveBigInteger extends BigInteger {
    public PositiveBigInteger(long value) {
        if (value <= 0) throw new IllegalArgumentException("non-positive: " + value);  // fail fast
        super(Long.toString(value));
    }
}
```

Module import declarations (25): `import module java.base;` imports every public top-level type
of the packages the module exports (and those of modules it requires transitively). Works on the
class path too. Ambiguous simple names (`Date` after `import module java.base; import module
java.sql;`) need a single-type import (`import java.sql.Date;`), which shadows module imports.
Use in scripts, tests and teaching code; library code keeps explicit imports.

Compact source files and instance `main` (25): a file without a class declaration gets an
implicit final class and an implicit `import module java.base;`; `java.lang.IO` provides
`print`, `println`, `readln`; run with `java Hello.java` (multi-file source launch since 22).

```java
void main() {                                // no public, static or String[] needed
    String name = IO.readln("Name: ");
    IO.println("Hello, " + name);
}
```

Text blocks: indentation is stripped relative to the closing `"""`; `\` joins lines, `\s` keeps
a trailing space; `.formatted(args)` for templating; never build SQL with it, bind parameters.

`var` guidelines: use it when the initializer names the type (`var orders = new ArrayList<Order>()`),
for long generic types and loop variables; avoid it when the type is not obvious from a method
name (`var x = service.load()`); `var list = new ArrayList<>()` infers `ArrayList<Object>`;
`var n = 1` is `int`, so write `1L` for longs. Not allowed for fields, method parameters or return types.

## 5. Null policy: JSpecify plus NullAway

| Rule | How |
|---|---|
| non-null by default | `@NullMarked` (org.jspecify.annotations, JSpecify 1.0) on `package-info.java` or `module-info.java` |
| mark the exceptions | `@Nullable` in type-use position: `@Nullable String`, `List<@Nullable String>`, `String @Nullable []`, `Map.@Nullable Entry<K, V>` |
| enforce at compile time | NullAway as an Error Prone plugin: `-Xep:NullAway:ERROR -XepOpt:NullAway:OnlyNullMarked=true` (NullAway 0.12.3+); add `-XepOpt:NullAway:JSpecifyMode=true` for generics checking |
| legacy code inside a marked package | `@NullUnmarked` on the class or method |
| absence as a return value | `Optional<T>` return only; never fields, parameters, collection elements or `Optional<List<T>>` (return an empty list) |
| fail fast at boundaries | `Objects.requireNonNull(x, "x")` in public constructors and API entry points; `Objects.requireNonNullElse(x, dflt)` for defaults |
| unannotated third-party returns | treat as nullable; wrap at the boundary |

`Optional` usage: `orElseThrow()` instead of `get()`, `map`/`flatMap`/`orElse` instead of
`isPresent()` + `get()`, `OptionalInt`/`OptionalLong` for primitives. Spring Framework 7 and
Spring Boot 4 ship JSpecify annotations, so NullAway sees their nullness.

## 6. Exceptions

| Situation | Use |
|---|---|
| expected business outcomes (declined, not found, invalid input) | sealed result type, not exceptions |
| caller can and must recover at an API boundary (I/O, remote failure) | checked exception, or unchecked with a documented contract |
| programming error | `IllegalArgumentException`, `IllegalStateException`, `NullPointerException` via `requireNonNull` |
| checked exception inside a lambda | wrap in `UncheckedIOException` or a domain unchecked exception with the cause |
| infrastructure failure deep in the stack | translate once at the layer boundary, keep the cause |

```java
try {
    return parser.parse(Files.readString(path));
} catch (IOException e) {
    throw new ConfigException("reading " + path, e);                // always chain the cause
}

try {
    queue.put(event);
} catch (InterruptedException e) {
    Thread.currentThread().interrupt();                              // restore the flag
    throw new IllegalStateException("interrupted while enqueueing " + event.id(), e);
}

try (var in = Files.newInputStream(src); var out = Files.newOutputStream(dst)) {
    in.transferTo(out);                                              // closed in reverse order
}
```

Prefer declaring `throws InterruptedException` over catching it. Never `catch (Exception e) {}`,
never log and rethrow (duplicate logs), catch `Throwable` only at a top-level boundary. Close
failures are attached via `getSuppressed()`. Stack traces are expensive: no exceptions for
control flow.

## 7. Streams and gatherers

```java
// import static java.util.stream.Collectors.*;
Map<Status, Long> counts = orders.stream()
    .collect(groupingBy(Order::status, () -> new EnumMap<>(Status.class), counting()));

Map<String, User> byEmail = users.stream()                          // duplicate keys throw otherwise
    .collect(toMap(User::email, Function.identity(), (first, dup) -> first, LinkedHashMap::new));

List<String> names = users.stream().map(User::name).toList();       // unmodifiable, allows nulls;
                                                                    // Collectors.toList(): no type or mutability guarantee

List<List<Event>> batches = events.stream().gather(Gatherers.windowFixed(100)).toList(); // last may be shorter
List<List<Integer>> pairs = Stream.of(1, 2, 3, 4).gather(Gatherers.windowSliding(2)).toList(); // [[1,2],[2,3],[3,4]]
Optional<BigDecimal> total = amounts.stream()
    .gather(Gatherers.fold(() -> BigDecimal.ZERO, BigDecimal::add)).findFirst();
List<BigDecimal> running = amounts.stream()
    .gather(Gatherers.scan(() -> BigDecimal.ZERO, BigDecimal::add)).toList();
List<Quote> quotes = vendors.stream()
    .gather(Gatherers.mapConcurrent(16, client::quote)).toList();    // virtual threads, <= 16 in flight
```

`mapConcurrent` keeps encounter order (a slow element delays later ones), rethrows a mapper
failure as a `RuntimeException` and cancels the remaining tasks; the mapper cannot throw
checked exceptions. A custom gatherer:

```java
static <T, K> Gatherer<T, ?, T> distinctBy(Function<? super T, ? extends K> key) {
    return Gatherer.<T, Set<K>, T>ofSequential(
        HashSet::new,
        (seen, element, downstream) -> !seen.add(key.apply(element)) || downstream.push(element));
}
```

| Use a loop instead of a stream when | Use a parallel stream only when |
|---|---|
| checked exceptions are thrown per element | CPU-bound, N x Q (elements x cost per element) above ~10,000 |
| several accumulators or early exit with side effects | source splits well: arrays, `ArrayList`, `IntStream.range` (not `LinkedList`, `Stream.iterate`, `Files.lines`) |
| index arithmetic or neighbour access (or use `windowSliding`) | stateless, non-interfering lambdas; associative reduction |
| a measured hot path allocates (lambdas, boxing, `Stream<Integer>`) | no blocking I/O: it runs on the common pool (cores - 1 workers) |
| debugging clarity matters more than brevity | a JMH run shows the speedup |

## 8. Collections

| Need | Collection | Note |
|---|---|---|
| default list | `ArrayList`, presized `new ArrayList<>(n)` | no `LinkedList`, `Vector`, `Hashtable` in new code |
| stack, queue, deque | `ArrayDeque` | not `Stack`; rejects nulls |
| insertion order, LRU cache | `LinkedHashMap` with `accessOrder = true` + `removeEldestEntry` | not thread-safe |
| sorted keys, range queries | `TreeMap` / `TreeSet` (`floorKey`, `headMap`, `subMap`) | comparator must agree with `equals` |
| enum keys | `EnumMap`, `EnumSet` | array-backed, ordered by ordinal |
| concurrent map | `ConcurrentHashMap` (`merge`, `computeIfAbsent`) | compute functions short, never touch the map |
| read-mostly listeners | `CopyOnWriteArrayList` | every write copies the array |
| immutable constants | `List.of`, `Set.of`, `Map.of` (`Map.ofEntries` above 10 pairs) | null-hostile; set/map iteration order unspecified |
| copy into an immutable collection | `List.copyOf`, `Map.copyOf` | no copy if already immutable |
| first, last, reversed view | `SequencedCollection.getFirst/getLast/reversed`, `SequencedMap.firstEntry/pollLastEntry` (21) | |
| presized hash map/set | `HashMap.newHashMap(n)`, `HashSet.newHashSet(n)` (19) | accounts for load factor 0.75 |
| primitive-heavy hot path | `int[]`, `BitSet`, fastutil or Eclipse Collections primitive maps | avoids boxing |

```java
final class Lru<K, V> extends LinkedHashMap<K, V> {
    private final int max;
    Lru(int max) { super(16, 0.75f, true); this.max = max; }        // access order
    @Override protected boolean removeEldestEntry(Map.Entry<K, V> eldest) { return size() > max; }
}
```

## 9. Pitfalls (symptom -> cause -> fix)

| Symptom | Cause | Fix |
|---|---|---|
| `Integer` equality false for 1000, true for 100 | `==` on boxed values; cache covers -128..127 | `equals`, or primitives (Error Prone `BoxedPrimitiveEquality`) |
| `new BigDecimal("2.0").equals(new BigDecimal("2.00"))` is false; `HashSet` keeps both, `TreeSet` one | `equals` compares scale, `compareTo` does not | `compareTo(...) == 0`, or normalize with `setScale`/`stripTrailingZeros` before hashing |
| `new BigDecimal(0.1)` prints 0.1000000000000000055... | binary double constructor | `new BigDecimal("0.1")` or `BigDecimal.valueOf(0.1)` |
| entries "vanish" from a `HashSet`/`HashMap` | key mutated after insertion changed `hashCode` | immutable keys (records of immutable fields) |
| `UnsupportedOperationException` on `add` | `List.of`, `Arrays.asList` (fixed size), `Stream.toList()`, `Collections.unmodifiable*` | `new ArrayList<>(list)` when mutation is intended |
| NPE from `List.of(...).contains(null)` | immutable collections reject null queries too | guard nulls before querying |
| `IllegalStateException: Duplicate key` | `Collectors.toMap` without merge function | pass a merge function; NPE also on null values |
| `"title".toUpperCase()` gives "TİTLE", `"TITLE".toLowerCase()` gives "tıtle" | default-locale case mapping (Turkish locale) | `toUpperCase(Locale.ROOT)` / `toLowerCase(Locale.ROOT)` (Error Prone `StringCaseLocaleUsage`) |
| dates off by hours around DST or between servers | `java.util.Date`, `SimpleDateFormat`, `LocalDateTime.now()` with the default zone | `Instant` for timestamps, `ZonedDateTime` with explicit `ZoneId`, inject a `Clock` |
| `MatchException` at run time | a sealed subtype added in a separately compiled module | recompile switch sites; never add `default` to hide it |
| stderr warning about mutating a `final` field through reflection (26+) | JEP 500 prepares to block `Field.set` on finals | constructor injection; `--enable-final-field-mutation=ALL-UNNAMED` only as a stopgap; test with `--illegal-final-field-mutation=deny` |
| `ConcurrentModificationException` | structural change while iterating | `removeIf`, `Iterator.remove`, collect then modify |

## 10. Modernizing pre-17 code

1. Raise the toolchain first (`maven.compiler.release` / Gradle toolchain), compile with
   `-Xlint:all -Werror`, fix deprecations; `jdeps --jdk-internals app.jar` and
   `jdeprscan --release 25 app.jar` list internal and removed API use.
2. Run OpenRewrite as a dry run, review the patch, then apply:
   `org.openrewrite.java.migrate.UpgradeToJava21` or `...UpgradeToJava25` (artifact
   `org.openrewrite.recipe:rewrite-migrate-java`; switch, sequenced-collection and build
   upgrades included). Recent OpenRewrite releases resolve from the Code Genome Project
   repository, which needs a download token in `~/.m2/settings.xml`: check the OpenRewrite docs.
3. Apply Error Prone suggested fixes for language idioms:
   `-XepPatchChecks:PatternMatchingInstanceof,StatementSwitchToExpressionSwitch -XepPatchLocation:IN_PLACE`.
4. Hand-convert type hierarchies to sealed interfaces + records (section 11); tools do not.
5. Commit each recipe separately so reviewers see mechanical diffs apart from design changes.
Commands, recipe lists and the Error Prone setup: [modernization recipes](references/modernization-recipes.md).

## 11. Worked example: instanceof chain -> sealed `PaymentResult`

Before: the gateway adapter returns `Object`; every caller repeats a cast chain and the
`else` branch is discovered in production.

```java
Object result = gateway.charge(request);
if (result instanceof ApprovedResponse) {
    ApprovedResponse a = (ApprovedResponse) result;
    ledger.record(a.getAuthCode(), a.getAmount());
    return new HttpReply(200, a.getAuthCode());
} else if (result instanceof DeclinedResponse) {
    DeclinedResponse d = (DeclinedResponse) result;
    return d.isRetryable() ? new HttpReply(503, "retry later") : new HttpReply(402, d.getReason());
} else if (result instanceof PendingResponse) {
    return new HttpReply(202, "pending");
} else {
    throw new IllegalStateException("unknown gateway result " + result);
}
```

Step 1, find every chain: `grep -rnE 'instanceof (Approved|Declined|Pending)Response' src/main/java`.

Step 2, model the closed set once (no `permits`: all subtypes in one file):

```java
public sealed interface PaymentResult {
    record Approved(String authCode, Money amount) implements PaymentResult {
        public Approved { Objects.requireNonNull(authCode, "authCode"); Objects.requireNonNull(amount, "amount"); }
    }
    record Declined(DeclineCode code, String reason, boolean retryable) implements PaymentResult {}
    record Pending(Instant retryAt) implements PaymentResult {}
}
record HttpReply(int status, String body) {}
```

Step 3, translate at the boundary, where the input really is open (a `default` is right here):

```java
static PaymentResult fromGateway(GatewayResponse r) {
    return switch (r.status()) {                                      // String from the vendor SDK
        case "APPROVED" -> new Approved(r.authCode(), new Money(r.amount(), Currency.getInstance(r.currency())));
        case "DECLINED" -> new Declined(DeclineCode.parse(r.code()), r.message(), r.retryable());
        case "PENDING"  -> new Pending(r.retryAt());
        default -> throw new GatewayProtocolException("unknown status " + r.status());
    };
}
```

Step 4, replace each chain with an exhaustive switch and no `default`:

```java
import com.acme.pay.PaymentResult.*;                                // nested record types

HttpReply toHttp(PaymentResult result) {
    return switch (result) {
        case Approved(var authCode, var amount) -> {
            ledger.record(authCode, amount);
            yield new HttpReply(200, authCode);
        }
        case Declined d when d.retryable()      -> new HttpReply(503, "retry later");
        case Declined(var code, var reason, _)  -> new HttpReply(402, code + ": " + reason);
        case Pending(var retryAt)               -> new HttpReply(202, "pending until " + retryAt);
    };
}
```

Step 5, prove exhaustiveness pays off: add `record ChargedBack(String caseId) implements
PaymentResult {}` and run `./mvnw -q compile`; javac fails at every switch with
`error: the switch expression does not cover all possible input values`, which is the
work list. Step 6, test each branch with a parameterized test (one row per subtype plus the
guarded case) and keep `-Xlint:all -Werror` plus NullAway in the build so the new code stays
null-safe.

## 12. Review checklist

- [ ] Data is records or sealed hierarchies; switches over them exhaustive without `default`.
- [ ] Compact constructors validate and copy collections; no arrays or secrets leaking through records.
- [ ] Null policy explicit (`@NullMarked` + NullAway); `Optional` only as a return type.
- [ ] Exceptions chained, `InterruptedException` honored, every `AutoCloseable` in try-with-resources.
- [ ] Collections per section 8; `toMap` has a merge function; locale and zone explicit.
- [ ] Preview features only where the JDK version is pinned with the code.

Related: `java-virtual-threads`, `java-jvm-tuning-jfr`, `java-build-maven-gradle`,
`java-testing-junit`, `java-spring-boot`, hub `java-craft`.
