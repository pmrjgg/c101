# Per-tool command crib

Every tool: dry run first, apply to one package, verify, then scale. Flags were checked against
current docs or `--help` in October 2026; where a detail is version-dependent it says so.

## comby (any delimiter-balanced language)

```bash
comby 'foo(:[a], :[b])' 'bar(:[b], :[a])' .py -diff              # preview over files ending .py
comby 'foo(:[a], :[b])' 'bar(:[b], :[a])' .py -review            # accept per change (y/n/e/q)
comby 'foo(:[a], :[b])' 'bar(:[b], :[a])' .py -i                 # in place
comby 'foo(:[a])' 'bar(:[a])' -matcher .js -d src -exclude-dir vendor,node_modules -i
comby 'old_name' '' .go -match-only -json-lines | jq -r .uri     # find only
```

Holes: `:[a]` matches lazily across balanced delimiters (including newlines), `:[[a]]` matches an
identifier-like word, `:[_]` matches without binding. Comby knows strings and comments per
`-matcher` language but has no types or scopes.

## semgrep

```yaml
rules:
  - id: requests-timeout
    languages: [python]
    severity: WARNING
    message: requests call without timeout
    pattern: requests.get($URL)
    fix: requests.get($URL, timeout=10)
```

```bash
semgrep --config rules/ --autofix --dryrun src/     # show fixes, do not write
semgrep --config rules/ --autofix src/              # write
```

`fix-regex: {regex, replacement, count}` applies a regex replacement inside the match.

## OpenRewrite (Java, Kotlin, Gradle, Maven, YAML, XML)

Maven, without editing the pom:

```bash
mvn org.openrewrite.maven:rewrite-maven-plugin:dryRun \
  -Drewrite.recipeArtifactCoordinates=org.openrewrite.recipe:rewrite-testing-frameworks:RELEASE \
  -Drewrite.activeRecipes=org.openrewrite.java.testing.junit5.JUnit4to5Migration
mvn org.openrewrite.maven:rewrite-maven-plugin:run   -D...same properties...
```

`dryRun` writes a `rewrite.patch` under the module's `target/` directory (exact subdirectory is
version-dependent; the build log prints it). Gradle: apply the `org.openrewrite.rewrite` plugin,
set `rewrite { activeRecipe(...) }`, run `./gradlew rewriteDryRun` then `./gradlew rewriteRun`.

| Migration | Recipe | Artifact |
|---|---|---|
| JUnit 4 -> 5 | `org.openrewrite.java.testing.junit5.JUnit4to5Migration` | `org.openrewrite.recipe:rewrite-testing-frameworks` |
| Java 21 | `org.openrewrite.java.migrate.UpgradeToJava21` | `org.openrewrite.recipe:rewrite-migrate-java` |
| Spring Boot 3.x | `org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_<minor>` (check the catalogue for the newest) | `org.openrewrite.recipe:rewrite-spring` |

Recipe test:

```java
class UseBarTest implements RewriteTest {
    @Override public void defaults(RecipeSpec spec) { spec.recipe(new UseBar()); }
    @Test void rewritesFoo() {
        rewriteRun(java("class A { void m() { Lib.foo(1); } }",
                        "class A { void m() { Lib.bar(1); } }"));
    }
}
```

## jscodeshift (JS/TS)

```js
// transforms/foo-to-bar.js
export const parser = "tsx";
export default function transformer(file, api) {
  const j = api.jscodeshift;
  return j(file.source)
    .find(j.CallExpression, { callee: { name: "foo" } })
    .forEach((p) => { p.node.callee.name = "bar"; p.node.arguments.reverse(); })
    .toSource({ quote: "double" });
}
```

```bash
npx jscodeshift -t transforms/foo-to-bar.js --parser=tsx --extensions=ts,tsx --dry --print src/
npx jscodeshift -t transforms/foo-to-bar.js --parser=tsx --extensions=ts,tsx src/
```

Tests: `defineTest` / `defineInlineTest` from `jscodeshift/dist/testUtils` with
`__testfixtures__/<name>.input.ts` and `.output.ts`.

## ts-morph (TypeScript with types)

```ts
import { Project, SyntaxKind } from "ts-morph";
const project = new Project({ tsConfigFilePath: "tsconfig.json" });
for (const sf of project.getSourceFiles("src/**/*.ts")) {
  for (const call of sf.getDescendantsOfKind(SyntaxKind.CallExpression)) {
    const expr = call.getExpression();
    if (expr.getText() !== "legacyFetch") continue;
    // type-aware guard: only the symbol imported from our http module
    const decl = expr.getSymbol()?.getDeclarations()[0];
    if (!decl?.getSourceFile().getFilePath().endsWith("/http/legacy.ts")) continue;
    expr.replaceWithText("fetchJson");
    sf.addImportDeclaration({ moduleSpecifier: "./http/client", namedImports: ["fetchJson"] });
  }
  sf.organizeImports();
}
await project.save();
```

Run `tsc --noEmit` afterwards; `organizeImports` also removes now-unused imports.

## LibCST (Python, formatting-preserving)

```python
# codemods/utcnow.py
import libcst as cst
import libcst.matchers as m
from libcst.codemod import VisitorBasedCodemodCommand
from libcst.codemod.visitors import AddImportsVisitor

UTCNOW = m.Call(func=m.Attribute(value=m.Name("datetime"), attr=m.Name("utcnow")), args=[])

class UtcNowCommand(VisitorBasedCodemodCommand):
    DESCRIPTION = "datetime.utcnow() -> datetime.now(UTC)"

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.BaseExpression:
        if not m.matches(updated_node, UTCNOW):
            return updated_node
        AddImportsVisitor.add_needed_import(self.context, "datetime", "UTC")
        return updated_node.with_changes(
            func=updated_node.func.with_changes(attr=cst.Name("now")),
            args=[cst.Arg(cst.Name("UTC"))],
        )
```

```bash
python -m libcst.tool initialize .        # writes .libcst.codemod.yaml
# edit it: add 'codemods' under modules:, set formatter: ['ruff', 'format', '-']
python -m libcst.tool codemod utcnow.UtcNowCommand src --unified-diff=1   # preview
python -m libcst.tool codemod utcnow.UtcNowCommand src                    # apply
```

Tested with LibCST 1.9: `from datetime import datetime` became `from datetime import UTC, datetime`.
Write `--unified-diff=1` with `=` or after the paths: `-u 1 utcnow.UtcNowCommand` parses `1` as the
command. Tests: subclass `libcst.codemod.CodemodTest`, set `TRANSFORM`, call
`self.assertCodemod(before, after)`. Use `ScopeProvider` / `QualifiedNameProvider` metadata to tell
`datetime` the class from a local variable of the same name.

## Go

```bash
gofmt -r 'bytes.Compare(a, b) == 0 -> bytes.Equal(a, b)' -d .    # single lowercase letters are wildcards
gofmt -r 'bytes.Compare(a, b) == 0 -> bytes.Equal(a, b)' -l -w .
gopls rename -d internal/billing/tax.go:#1234 ComputeTax          # diff; position :line:col or :#byte-offset
gopls rename -w internal/billing/tax.go:42:6 ComputeTax           # write
go fix -diff ./...                                                # Go 1.26+: modernizers, preview
go fix ./...                                                      # apply
go tool fix help                                                  # list fixers; enable one with -<name>
```

Go 1.26 rewrote `go fix` on the `go vet` analysis framework; modernizers only offer fixes in files
whose Go version (go.mod `go` directive or build constraint) is new enough for the feature.
`//go:fix inline` on a function or constant lets `go fix` inline calls to it at every use site:
the library-author route for API migrations (mark the old function as a wrapper around the new one).

## Rust

```bash
cargo clippy --fix --allow-dirty --allow-staged -- -W clippy::<lint>     # lint-driven fixes
cargo fix --edition                                                      # edition migration
rust-analyzer ssr '$a.foo($b) ==>> bar($a, $b)'                          # structural replace (CLI)
rust-analyzer search '$a.foo($b)'                                        # matches only
```

SSR is type-aware (paths resolve, so `foo` must be the same item). The editor command
"rust-analyzer: Structural Search Replace" is the documented entry point; CLI behaviour details are
version-dependent, so commit before running and inspect `git diff`.

## C / C++

```text
// kzalloc.cocci
@@
expression E, F;
@@
- kmalloc(E, F | __GFP_ZERO)
+ kzalloc(E, F)
```

```bash
spatch --sp-file kzalloc.cocci --dir src/              # unified diff on stdout
spatch --sp-file kzalloc.cocci --dir src/ --in-place
cmake -B build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON       # clang-tidy needs compile_commands.json
run-clang-tidy -p build -checks='-*,modernize-use-nullptr,modernize-use-override' -fix
clang-tidy -p build --checks='-*,modernize-use-nullptr' --fix src/foo.cpp
```

## Linter fixers

```bash
ruff check --select UP --fix .                  # pyupgrade rules; honours target-version
ruff check --fix --unsafe-fixes --select <RULE> # unsafe fixes may change behaviour: review the diff
ruff check --statistics --select <RULE> .       # counts per rule (inventory)
pyupgrade --py312-plus $(git ls-files '*.py')
npx eslint --fix 'src/**/*.{ts,tsx}'
golangci-lint run --fix ./...
```

A rule's documentation says whether a fix exists and whether it is safe: `ruff rule <CODE>` prints
"Fix is always/sometimes available" when there is one.
