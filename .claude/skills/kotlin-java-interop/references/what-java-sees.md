# What Java sees: Kotlin constructs in bytecode

Companion to `kotlin-java-interop`. Verify any row on your own build with
`javap -cp build/classes/kotlin/main <fqcn>` (public and protected members) or `javap -p` (all members).
Bytecode names below are stable compiler conventions; hash suffixes and module suffixes vary per build.

## 1. Declarations

| Kotlin (file `Strings.kt`, package `com.acme.text`) | Java view |
|---|---|
| `fun slug(s: String): String` | `StringsKt.slug(String)` (static) |
| `@file:JvmName("Strings")` on the file | `Strings.slug(String)` |
| several files with `@file:JvmName("Strings")` + `@file:JvmMultifileClass` | one facade `Strings` |
| `fun String.slug(): String` (extension) | `StringsKt.slug(String receiver)`: receiver becomes the first parameter |
| `val version = "1.0"` (top level) | `StringsKt.getVersion()` |
| `const val VERSION = "1.0"` | `public static final String VERSION` (value inlined into Java callers) |
| `fun f(a: Int, b: Int = 1)` | `f(int, int)` plus synthetic `f$default(...)`; `@JvmOverloads` adds `f(int)` |
| `vararg xs: String` | `String...` |
| `operator fun plus(o: Money)` | `plus(Money)` |
| `infix fun to(...)`, `tailrec`, `inline` | ordinary methods; inline bodies are not inlined into Java |
| function with `reified` type parameter | not usable from Java: add an overload taking `Class<T>` |

## 2. Classes and objects

| Kotlin | Java view |
|---|---|
| `class User(val name: String, var age: Int)` | `getName()`, `getAge()`, `setAge(int)`; classes are `final` unless `open` |
| `val isAdmin: Boolean` / `var isAdmin` | `isAdmin()` / `isAdmin()` + `setAdmin(boolean)` |
| `@JvmField val id: String` | `public final String id` field, no getter |
| `lateinit var repo: Repo` | public field with the setter's visibility, plus accessors |
| `data class Point(val x: Int, val y: Int)` | getters, `component1()`, `component2()`, `copy(int, int)`, `equals`, `hashCode`, `toString` |
| `@JvmRecord data class Point(...)` | a `java.lang.Record` with accessors `x()`, `y()` |
| `companion object { fun create() }` | `static final User.Companion Companion`; call `User.Companion.create()` |
| `@JvmStatic` in the companion | additionally `static User create()` on `User` |
| `object Registry { fun lookup() }` | `Registry.INSTANCE.lookup()`; `@JvmStatic` makes `Registry.lookup()` |
| `const val` / `@JvmField val` in a companion | static fields on the outer class |
| `enum class Color { RED }` | a Java enum; `entries` appears as `getEntries()` returning `EnumEntries` |
| `sealed class Shape` / `sealed interface` | abstract class / interface; Java switches get no exhaustiveness from Kotlin |
| `inner class Node` | non-static inner class (needs an outer instance) |
| nested `class Node` | static nested class |
| `internal fun recompute()` | public `recompute$<module>`; public members of an `internal` class keep plain names |
| `private` top-level function | private static in the facade class |

## 3. Types

| Kotlin | Java |
|---|---|
| `Int`, `Long`, `Boolean` | `int`, `long`, `boolean` |
| `Int?`, `List<Int>`, generic `T` with `Int` | `Integer` (boxed) |
| `Any` / `Unit` return / `Nothing` return | `Object` / `void` / `Void` |
| `List<T>`, `MutableList<T>` | both `java.util.List<T>` |
| `Array<String>` / `IntArray` | `String[]` / `int[]` |
| `(String) -> Int` | `kotlin.jvm.functions.Function1<String, Integer>` |
| `(String) -> Unit` | `Function1<String, Unit>`: a Java lambda must `return Unit.INSTANCE` |
| `fun interface Validator { fun validate(s: String): Boolean }` | ordinary functional interface: plain Java lambdas |
| `suspend fun load(id: Int): User` | `Object load(int, Continuation<? super User>)` |
| value class parameter `AccountId` | function renamed `load-<hash>(String)`: not callable |
| `List<Animal>` parameter (open `Animal`) | `List<? extends Animal>`; return types never get wildcards; final types (`String`) never do |

## 4. Nullness in the bytecode

- Public Kotlin signatures carry `@org.jetbrains.annotations.NotNull`/`@Nullable`, so Java IDEs and
  null checkers see Kotlin's nullability.
- Non-null parameters of public functions are checked on entry. A Java caller passing `null` gets
  `NullPointerException: Parameter specified as non-null is null: method com.acme.Foo.bar, parameter name`,
  which points at the Java call site; do not disable these checks.
- Values flowing from Java into non-null Kotlin types are checked where they are assigned:
  `NullPointerException: getName(...) must not be null`.

## 5. Exceptions

| Situation | Effect | Fix |
|---|---|---|
| Kotlin throws `IOException`, Java wraps the call in `try/catch (IOException e)` | javac: "exception IOException is never thrown in body of corresponding try statement" | `@Throws(IOException::class)` on the Kotlin function |
| Java lambda implementing a Kotlin `fun interface` throws a checked exception | javac: "unreported exception ...; must be caught or declared to be thrown" | `@Throws` on the interface method |
| `suspend` function exposed through `future { }` throws | `ExecutionException` with the original cause from `get()`; `CompletionException` from `join()` | document it; unwrap `getCause()` |

## 6. Checklist: a Java-friendly Kotlin API

- [ ] No value classes, `suspend` functions, `reified` functions or Unit-returning function types in
      Java-facing signatures (or Java-friendly twins exist: boxed/`@JvmName`, `...Async`, `Class<T>`,
      `fun interface`).
- [ ] Defaulted parameters last, `@JvmOverloads` on functions and constructors Java calls.
- [ ] Factories and constants are static (`@JvmStatic`, `const val`, `@JvmField`).
- [ ] Facade classes named (`@file:JvmName`), no `...Kt` in Java code.
- [ ] Checked exceptions declared with `@Throws`.
- [ ] Collections returned as copies or unmodifiable views; parameters copied on entry.
- [ ] `java.time` types in the Java-facing surface (not `kotlin.time.Duration`, which is a value class).
- [ ] A Java test in `src/test/java` exercises every public entry point.
- [ ] The ABI dump (`apiDump` or `updateKotlinAbi`) is committed and reviewed.
