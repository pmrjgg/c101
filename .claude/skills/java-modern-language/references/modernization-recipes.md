# Modernization recipes: OpenRewrite, Error Prone, JDK tools

## 1. OpenRewrite

Recipe module: `org.openrewrite.recipe:rewrite-migrate-java`. As of 2026 OpenRewrite releases are
published to the Code Genome Project Maven repository (`https://artifacts.codegenomeproject.org/maven`),
which requires an account and a download token: add a `codegenome` server plus a profile with that
URL as both `repository` and `pluginRepository` in `~/.m2/settings.xml` (Gradle: credentials in the
init script). Never commit the token. Recent `rewrite-migrate-java` releases are published under the
Moderne Source Available License; check that it fits your use.

Maven, without editing the POM (dry run first, then apply):

```bash
mvn -U org.openrewrite.maven:rewrite-maven-plugin:dryRun \
  -Drewrite.recipeArtifactCoordinates=org.openrewrite.recipe:rewrite-migrate-java:RELEASE \
  -Drewrite.activeRecipes=org.openrewrite.java.migrate.UpgradeToJava25
# review the generated rewrite.patch (path printed by the plugin), then:
mvn -U org.openrewrite.maven:rewrite-maven-plugin:run \
  -Drewrite.recipeArtifactCoordinates=org.openrewrite.recipe:rewrite-migrate-java:RELEASE \
  -Drewrite.activeRecipes=org.openrewrite.java.migrate.UpgradeToJava25
```

Plugin goals: `run`, `dryRun`, `runNoFork`, `dryRunNoFork`, `discover`. `-Drewrite.exclusions=docs/**`
skips paths; `failOnDryRunResults=true` makes `dryRun` a CI gate that fails when changes remain.

Gradle: apply `id("org.openrewrite.rewrite")`, add `rewrite("org.openrewrite.recipe:rewrite-migrate-java:<version>")`,
set `rewrite { activeRecipe("org.openrewrite.java.migrate.UpgradeToJava25") }`, then
`./gradlew rewriteDryRun` and `./gradlew rewriteRun` (or an init script with `--init-script`).

| Recipe | What it does |
|---|---|
| `org.openrewrite.java.migrate.UpgradeToJava21` | includes UpgradeToJava17, build upgrade to 21, `SequencedCollection` adoption, `Locale.of`, `URI.create(..).toURL()`, if-else-if to switch, switch statements to switch expressions, arrow-form `yield`, switch pattern matching (JEP 441), `NullCheckAsSwitchCase`, plugin upgrades, `actions/setup-java` version bump |
| `org.openrewrite.java.migrate.UpgradeToJava25` | includes UpgradeToJava21, build upgrade to 25, plugin upgrades, `System.out.print` to `IO`, `Process#waitFor(Duration)`, `Inflater`/`Deflater` `close()`, `Reader.of(CharSequence)`, Security Manager removal clean-ups, `ZipException` for `ZipError`, dangling doc comments to block comments, Kotlin compatibility steps |
| `org.openrewrite.java.migrate.UpgradeJavaVersion` | only bumps the build's Java version (Maven compiler settings, Gradle toolchain) |
| `org.openrewrite.staticanalysis.InstanceOfPatternMatch` | `instanceof` + cast to pattern `instanceof` |
| `org.openrewrite.java.migrate.lang.UseTextBlocks` | concatenated multi-line strings to text blocks |
| `org.openrewrite.java.migrate.lang.var.UseVarForObject` | `var` for local object declarations (review: not always clearer) |
| `org.openrewrite.java.migrate.util.SequencedCollection` | `list.get(0)` / `get(size()-1)` to `getFirst()` / `getLast()` |

Sub-recipe lists change between releases: read the recipe page for the version you resolve.

## 2. Error Prone suggested fixes

```text
-XepPatchChecks:PatternMatchingInstanceof,StatementSwitchToExpressionSwitch,MissingOverride
-XepPatchLocation:IN_PLACE            # edit sources directly
-XepPatchLocation:/abs/path/to/src    # or write error-prone.patch (unified diff) there
```

Add these to the single `-Xplugin:ErrorProne ...` argument (see [null-policy setup](null-policy-setup.md)
for the build wiring), compile once, review `git diff`, then remove the patch flags.

| Check | Default | Modernizes |
|---|---|---|
| `PatternMatchingInstanceof` | on, warning | `instanceof` + cast |
| `StatementSwitchToExpressionSwitch` | on, warning | old `case:` statements to arrow / expression switches |
| `BoxedPrimitiveEquality` | on, error | `==` on boxed values |
| `BigDecimalEquals` | on, warning | `BigDecimal.equals` misuse |
| `StringCaseLocaleUsage` | on, warning | `toUpperCase()` without `Locale` |
| `JavaTimeDefaultTimeZone` | on, warning | `LocalDateTime.now()` with the default zone |
| `ArrayRecordComponent` | on, warning | arrays in records |
| `MixedMutabilityReturnType` | on, warning | methods returning both mutable and immutable collections |
| `InterruptedExceptionSwallowed` | experimental | catch blocks that swallow interrupts |
| `UnnecessaryDefaultInEnumSwitch` | experimental | `default` that hides missing enum cases |
| `Varifier` | experimental | suggests `var` |

Enable experimental checks explicitly: `-Xep:InterruptedExceptionSwallowed:WARN`.

## 3. JDK tools for an upgrade

```bash
jdeps --jdk-internals --multi-release 25 target/app.jar        # use of internal APIs
jdeprscan --release 25 target/app.jar                          # deprecated / for-removal APIs
javac -Xlint:all -Werror ...                                   # deprecation, removal, preview, this-escape
java -XX:+PrintFlagsFinal -version | grep -i <flag>            # removed or renamed JVM flags
```

## 4. Breaking changes by hop

| Hop | Watch for |
|---|---|
| 8 -> 11 | Java EE and CORBA modules removed (JEP 320): add JAXB, JAX-WS, `javax.annotation` as dependencies |
| 11 -> 17 | strong encapsulation of JDK internals (JEPs 396, 403): `--illegal-access` gone, use `--add-opens` only as a stopgap; Security Manager deprecated for removal (JEP 411) |
| 17 -> 21 | UTF-8 default charset (JEP 400, since 18); dynamic agent loading warns (JEP 451): run Mockito/ByteBuddy as `-javaagent`; `new URL(String)` deprecated |
| 21 -> 25 | annotation processing no longer implicit (JDK 23): configure processor paths or `-proc:full`; Security Manager permanently disabled (JEP 486); `sun.misc.Unsafe` memory access warns (JEP 498); JNI use warns (JEP 472); 32-bit x86 removed (JEP 503) |
| 25 -> 26 | warnings for reflective mutation of `final` fields (JEP 500); Applet API removed (JEP 504) |
| 26 -> 27 | G1 is the default collector everywhere (JEP 523); compact object headers on by default (JEP 534); `-XX:AOTMode=on` renamed `required` |

Order of work for a large codebase: build tooling and plugins first, then the JDK in CI with the
old `--release`, then raise `--release`, then language modernization recipes, one PR each.
