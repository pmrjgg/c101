# Null policy setup: JSpecify + Error Prone + NullAway

Versions on Maven Central as of October 2026: `org.jspecify:jspecify` 1.0.1,
`com.google.errorprone:error_prone_core` 2.50.0, `com.uber.nullaway:nullaway` 0.14.2. Pin your
own versions in the BOM or version catalog and check release notes before bumping.
Error Prone must run on JDK 21 or newer (it can still compile older `--release` targets).

## 1. Mark the code

```java
// src/main/java/com/acme/payments/package-info.java
@NullMarked
package com.acme.payments;

import org.jspecify.annotations.NullMarked;
```

```java
public interface CustomerRepository {
    Optional<Customer> findById(CustomerId id);              // absence as Optional return
    @Nullable Customer findByEmailOrNull(String email);      // or as a @Nullable return
    List<@Nullable String> legacyCodes();                    // nullable elements
    String @Nullable [] aliases();                           // nullable array reference
    Map.@Nullable Entry<String, Integer> lastEntry();        // nested type: annotation after the dot
}
```

| Annotation | Scope | Meaning |
|---|---|---|
| `@NullMarked` | module, package, class, method | unannotated types are non-null |
| `@Nullable` | type use | this type includes null |
| `@NonNull` | type use | rarely needed inside `@NullMarked`; for generic type variables |
| `@NullUnmarked` | package, class, method, constructor | opt a region back out (legacy code) |

Rollout: mark one package at a time (leaf packages first), fix NullAway errors, then move up.
Generated code (MapStruct, protobuf) stays unmarked or is excluded from NullAway.

## 2. Maven

`.mvn/jvm.config` (javac internals Error Prone needs):

```
--add-exports jdk.compiler/com.sun.tools.javac.api=ALL-UNNAMED
--add-exports jdk.compiler/com.sun.tools.javac.file=ALL-UNNAMED
--add-exports jdk.compiler/com.sun.tools.javac.main=ALL-UNNAMED
--add-exports jdk.compiler/com.sun.tools.javac.model=ALL-UNNAMED
--add-exports jdk.compiler/com.sun.tools.javac.parser=ALL-UNNAMED
--add-exports jdk.compiler/com.sun.tools.javac.processing=ALL-UNNAMED
--add-exports jdk.compiler/com.sun.tools.javac.tree=ALL-UNNAMED
--add-exports jdk.compiler/com.sun.tools.javac.util=ALL-UNNAMED
--add-opens jdk.compiler/com.sun.tools.javac.code=ALL-UNNAMED
--add-opens jdk.compiler/com.sun.tools.javac.comp=ALL-UNNAMED
```

`pom.xml` (maven-compiler-plugin configuration):

```xml
<configuration>
  <release>25</release>
  <compilerArgs>
    <arg>-XDcompilePolicy=simple</arg>
    <arg>--should-stop=ifError=FLOW</arg>
    <!-- all Error Prone options must be in ONE arg -->
    <arg>-Xplugin:ErrorProne -Xep:NullAway:ERROR -XepOpt:NullAway:OnlyNullMarked=true -XepOpt:NullAway:JSpecifyMode=true</arg>
  </compilerArgs>
  <annotationProcessorPaths>
    <path>
      <groupId>com.google.errorprone</groupId>
      <artifactId>error_prone_core</artifactId>
      <version>${error-prone.version}</version>
    </path>
    <path>
      <groupId>com.uber.nullaway</groupId>
      <artifactId>nullaway</artifactId>
      <version>${nullaway.version}</version>
    </path>
  </annotationProcessorPaths>
</configuration>
```

Error Prone documents `-XDaddTypeAnnotationsToSymbol=true` as needed only when building on
JDK 21. `jspecify` itself is an ordinary `compile`-scope dependency.

## 3. Gradle (Kotlin DSL) with net.ltgt.errorprone

```kotlin
import net.ltgt.gradle.errorprone.CheckSeverity
import net.ltgt.gradle.errorprone.errorprone

plugins { java; id("net.ltgt.errorprone") version "<plugin version>" }

dependencies {
    implementation("org.jspecify:jspecify:1.0.1")
    errorprone("com.google.errorprone:error_prone_core:<version>")
    errorprone("com.uber.nullaway:nullaway:<version>")
}

tasks.withType<JavaCompile>().configureEach {
    options.errorprone {
        check("NullAway", CheckSeverity.ERROR)
        option("NullAway:OnlyNullMarked", "true")
        option("NullAway:JSpecifyMode", "true")
    }
    if (name.lowercase().contains("test")) options.errorprone.disable("NullAway")   // optional
}
```

## 4. NullAway flags

| Flag | Effect |
|---|---|
| `-XepOpt:NullAway:OnlyNullMarked=true` | check only `@NullMarked` code (JSpecify semantics); 0.12.3+ |
| `-XepOpt:NullAway:AnnotatedPackages=com.acme` | older package-prefix mode; with 0.12.3+ use one of the two |
| `-XepOpt:NullAway:JSpecifyMode=true` | fuller JSpecify checking (generics, arrays); needs a recent javac, see NullAway's compatibility page |
| `-XepOpt:NullAway:ExcludedClassAnnotations=...` | skip classes carrying the given annotations (generated code) |

## 5. Typical NullAway errors and fixes

| Error (shortened) | Fix |
|---|---|
| dereferenced expression `x` is `@Nullable` | check for null first, or use `Objects.requireNonNullElse` / an `Optional` return upstream |
| returning `@Nullable` expression from method with `@NonNull` return type | annotate the return `@Nullable`, or return `Optional`/empty collection |
| passing `@Nullable` parameter where `@NonNull` is required | validate at the boundary with `Objects.requireNonNull` |
| initializer method does not guarantee `@NonNull` field is initialized | assign in every constructor, or make the field `@Nullable` and handle it |
| unannotated library method returns null at run time | treat third-party returns as nullable; wrap in an adapter |

Avoid suppressing with `@SuppressWarnings("NullAway")` except on generated or test fixtures;
each suppression is a place a production NPE can come from.
