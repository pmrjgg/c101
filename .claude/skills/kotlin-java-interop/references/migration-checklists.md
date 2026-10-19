# Java-to-Kotlin migration checklists

Companion to `kotlin-java-interop`: the J2K review list, Lombok mapping and ABI tooling in full.

## 1. Per-class loop

1. Pick a class whose Java dependents you can compile in the same PR (leaf classes, tests, DTOs first).
2. Baseline the API: `./gradlew apiDump` or `./gradlew updateKotlinAbi` (commit the dump), plus
   `javap -cp build/classes/java/main com.acme.Foo > /tmp/Foo.before` for a Java class.
3. Delombok it if needed (section 3), then Code | Convert Java File to Kotlin File.
4. Walk the review list (section 2); fix interop annotations.
5. `javap -cp build/classes/kotlin/main com.acme.Foo > /tmp/Foo.after && diff /tmp/Foo.before /tmp/Foo.after`.
6. `./gradlew check` (runs `apiCheck` or `checkKotlinAbi`), Java callers compile, tests pass.
7. Commit the conversion separately from behaviour changes so reviewers can diff semantics.

## 2. J2K review list

Nullability
- [ ] Every `!!` inserted by J2K replaced by a decision: non-null type, `?:` default, `requireNotNull`, or
      an explicit nullable type.
- [ ] Fields initialised later: constructor parameter, nullable, or `lateinit` (framework injection only;
      not allowed on primitives).
- [ ] Values from unannotated Java APIs typed explicitly at the boundary.

Statics and API shape
- [ ] Static methods: top-level functions (with `@file:JvmName`) or companion members with `@JvmStatic`.
- [ ] Constants: `const val` (primitives and String) or `@JvmField`.
- [ ] Overloads merged into default arguments only where Java callers get `@JvmOverloads`.
- [ ] Builders kept (or replaced by a static factory) when Java callers use them.
- [ ] `@Throws` on functions whose checked exceptions Java callers catch or declare.
- [ ] Visibility: package-private Java members became `internal` or `public`; nothing became more visible
      than intended (Kotlin has no package-private).
- [ ] Classes Spring or Mockito must subclass are open (compiler plugin or explicit `open`).

Semantics
- [ ] `equals`/`hashCode`/`toString`: kept as written, or a `data class` only for value types (never JPA
      entities); `data class` changes `toString` output, which logs and tests may parse.
- [ ] `==` on boxed numbers: Java `Integer ==` (identity) became Kotlin `==` (equality); check intent.
- [ ] Integer division, `char` arithmetic and implicit widening (`int` to `long`) converted explicitly.
- [ ] `switch` fall-through rewritten correctly in `when`.
- [ ] `synchronized` methods use `@Synchronized`; `synchronized (lock)` blocks use `synchronized(lock) { }`;
      `volatile` fields use `@Volatile`.
- [ ] Streams: `stream().map().collect()` became eager collection operations; long or infinite pipelines
      use `asSequence()`.
- [ ] `Optional<T>` in internal code became `T?`; Java-facing signatures may keep `Optional`.
- [ ] Static nested vs inner classes preserved (`inner` only when the outer instance is used).
- [ ] Anonymous classes became lambdas only for SAM types; listeners needing `this` stay objects.
- [ ] Annotations on constructor properties have the intended use-site target (`@field:`, `@param:`,
      `@get:`); Kotlin 2.4 defaults to param plus property or field.
- [ ] `MutableList` vs `List`, `MutableMap` vs `Map` chosen on purpose for each field and return type.

## 3. Lombok to Kotlin

Inventory first:

```bash
grep -rhoE '@(Getter|Setter|Data|Value|Builder|SuperBuilder|With|Slf4j|Log4j2|RequiredArgsConstructor|AllArgsConstructor|NoArgsConstructor|SneakyThrows|EqualsAndHashCode|ToString|NonNull)\b' \
  --include=*.java src | sort | uniq -c | sort -rn
java -jar lombok.jar delombok src/main/java/com/acme/billing -d build/delombok/com/acme/billing
```

| Lombok | Kotlin | Java-caller note |
|---|---|---|
| `@Getter` / `@Setter` | `val` / `var` properties | names stay `getX`/`setX` (`isX` for `isX` booleans) |
| `@Value` | `data class` with `val`s | getters unchanged; `copy` is awkward from Java |
| `@Data` on DTOs | class or `data class` with `var`s | not for JPA entities |
| `@Builder` | named and default arguments | keep a builder or add `@JvmOverloads`/static factories for Java callers |
| `@SuperBuilder` | constructor chains, or keep the Java hierarchy until the end | convert the hierarchy together |
| `@With` | `copy(x = ...)` | add `fun withX(x: T) = copy(x = x)` for Java |
| `@RequiredArgsConstructor` / `@AllArgsConstructor` | primary constructor | `@JvmOverloads` if defaults exist |
| `@NoArgsConstructor` (JPA, Jackson) | `kotlin("plugin.jpa")`/`plugin.noarg`, jackson-module-kotlin | synthetic, reflection-only constructor |
| `@Slf4j` | `private val log = LoggerFactory.getLogger(Foo::class.java)` (top-level private or companion) | |
| `@SneakyThrows` | delete (no checked exceptions in Kotlin) | add `@Throws` where Java catches |
| `@EqualsAndHashCode` / `@ToString` | `data class`, or explicit overrides | entity rules from the skill apply |
| `@NonNull` | non-null Kotlin type | Kotlin also reads `lombok.NonNull` on Java code |

While both languages coexist, `kotlin("plugin.lombok")` lets Kotlin in the same module see generated
members; supported annotations are `@Getter`, `@Setter`, `@Builder`, `@SuperBuilder`, the three constructor
annotations, `@Data`, `@With`, `@Value` (not `@Tolerate`).

## 4. ABI tooling

| Tool | Setup | Tasks | Notes |
|---|---|---|---|
| binary-compatibility-validator | `id("org.jetbrains.kotlinx.binary-compatibility-validator") version "0.18.2"` on the root | `apiDump`, `apiCheck` (wired into `check`) | maintenance mode; `apiValidation { ignoredPackages; ignoredClasses; nonPublicMarkers }`; dumps in `api/` |
| KGP ABI validation, Kotlin 2.4 | `kotlin { @OptIn(ExperimentalAbiValidation::class) abiValidation() }` | `updateKotlinAbi`, `checkKotlinAbi` (run by `check`) | `filters { excluded { byNames.add("**.internal.**"); annotatedWith.add("com.acme.InternalApi") } }` |
| KGP ABI validation, Kotlin 2.2-2.3 | `abiValidation { enabled.set(true) }` | `updateLegacyAbi`, `checkLegacyAbi` | experimental; DSL streamlined in 2.4 |
| japicmp | Gradle plugin `me.champeau.gradle.japicmp` or the CLI | compare the new jar with the last released jar | catches Java-visible breaks from either language |

Breaking changes Java callers feel even when Kotlin callers do not: adding a default parameter (signature
change; use `@IntroducedAt` from Kotlin 2.3, or keep the old overload), moving a function between files
(facade class name), changing `const val` values (inlined), adding `@JvmRecord` (accessors become
`x()`), adding a value class to a signature (mangling), and making a top-level function `internal`.
