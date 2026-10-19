# Tool commands per language

Verify tool availability first (`command -v lizard jscpd scc tokei`); install into a project-local or
scratch environment, never globally without the caller's consent. Record tool versions in Evidence,
because counting rules change between versions.

## Multi-language

```bash
scc --by-file -s complexity --format csv > scc.csv     # size + rough per-file complexity
tokei --sort code                                       # size by language
lizard --csv src/ > lizard.csv                          # per-function NLOC, CCN, tokens, params
lizard -C 15 -L 80 -a 6 -w src/                         # print only functions over thresholds
lizard -m src/                                          # modified CCN: switch counts once
npx jscpd --min-tokens 70 --threshold 3 --reporters console,json --output dup/ src/
pmd cpd --minimum-tokens 100 --dir src --language java  # PMD 7 copy-paste detector
```
lizard supports C/C++, Java, C#, JavaScript/TypeScript, Python, Go, Rust, Kotlin, Swift, Scala, Ruby,
PHP, Lua and others (`lizard -l <lang>` restricts languages).

## Python

```bash
radon cc -s -a -nc src/                   # CCN per block, average, only grade C and worse
radon mi -s src/                          # maintainability index (trend only)
xenon --max-absolute B --max-modules A --max-average A src/   # CI gate on radon grades
complexipy src/ --max-complexity-allowed 15                   # cognitive complexity (flag names vary by version)
ruff check --select C901,PLR0911,PLR0912,PLR0913,PLR0915 --statistics src/
mypy --strict src/ --linecount-report "$M/mypy-report"  # typed vs untyped lines; $M = metrics dir (SKILL.md section 2)
lint-imports                                                  # import-linter contracts (layers, forbidden, independence)
pydeps mypkg --show-cycles --no-output                        # import cycles
rg -c "type: ignore" src/ | sort -t: -k2 -rn | head           # escape-hatch counts
```

## JavaScript / TypeScript

```bash
npx eslint . --rule '{"complexity": ["warn", 15]}' -f json -o eslint.json
npx eslint . --suppress-all                 # ESLint 9.24+: writes eslint-suppressions.json baseline
npx eslint . --prune-suppressions           # drop suppressions that no longer occur
npx madge --circular --extensions ts,tsx src/
npx depcruise src --config .dependency-cruiser.js --output-type err      # rule violations incl. no-circular
npx depcruise src --config .dependency-cruiser.js --output-type dot | dot -T svg > deps.svg
npx type-coverage --detail --at-least 95
npx tsc --noEmit -p .
rg -c "\bas any\b|: any\b" src/ | sort -t: -k2 -rn | head
```
Cognitive complexity: `eslint-plugin-sonarjs` rule `sonarjs/cognitive-complexity` (default 15).

## Go

```bash
gocyclo -over 15 .
gocognit -over 15 .
golangci-lint run --enable gocognit,gocyclo,dupl,funlen,nestif
golangci-lint run --new-from-rev=origin/main          # only issues introduced since main
go list -f '{{.ImportPath}} {{join .Imports " "}}' ./... > imports.txt   # edges for coupling analysis
go mod graph | wc -l                                  # module dependency count
rg -c "interface\{\}|\bany\b" --type go | sort -t: -k2 -rn | head
```
The Go compiler forbids import cycles between packages, so focus on layering violations and coupling.

## Rust

```bash
cargo clippy --all-targets -- -W clippy::cognitive_complexity -W clippy::too_many_lines -W clippy::too_many_arguments
# thresholds in clippy.toml: cognitive-complexity-threshold = 15, too-many-lines-threshold = 80
cargo tree -e normal --depth 1                        # direct dependencies
cargo tree --duplicates                               # duplicate versions of the same crate
cargo geiger                                          # unsafe usage across the dependency tree
cargo modules --help                                  # module graph (cargo-modules; subcommands differ by version)
lizard -l rust --csv src/ > lizard.csv
```
Clippy's lints are warnings by default here (`-W`); use `-D` to make them errors in CI.

## Java / Kotlin

```bash
pmd check -d src/main/java -R category/java/design.xml/CognitiveComplexity,category/java/design.xml/CyclomaticComplexity -f text
jdeps -summary -recursive target/app.jar
jdeps --dot-output deps/ target/classes
./gradlew detekt                                       # Kotlin: complexity, length, nesting rules
./gradlew detektBaseline                               # create the baseline (ratchet existing debt)
```
ArchUnit test for cycles and layering:
```java
@ArchTest
static final ArchRule noCycles = SlicesRuleDefinition.slices()
    .matching("com.acme.(*)..").should().beFreeOfCycles();
```

## C / C++

```bash
lizard -l cpp --csv src/ > lizard.csv
clang-tidy -checks='-*,readability-function-cognitive-complexity' -p build/ src/*.cpp
cmake --graphviz=deps.dot build/ && dot -T svg deps.dot > deps.svg     # target-level graph
include-what-you-use (via CMAKE_CXX_INCLUDE_WHAT_YOU_USE)              # header coupling
```
clang-tidy option: `readability-function-cognitive-complexity.Threshold` (default 25).

## Haskell / Julia

- Haskell: `hlint .` for lint debt; `homplexity-cli` for complexity metrics; module graph from
  `graphmod` (`graphmod | dot -T svg`). Type coverage is not a concept; track `unsafePerformIO`,
  partial functions (`head`, `fromJust`) with `rg`.
- Julia: `JET.jl` (`report_package`) for type-instability and error reports; `Aqua.jl` for ambiguities,
  unbound type parameters, stale dependencies.

## Churn

```bash
git log --since=12.months --no-merges --format= --name-only | sort | uniq -c | sort -rn | head -30
git log --since=12.months --no-merges --numstat --format= | awk '{a[$3]+=$1+$2} END {for (f in a) print a[f], f}' | sort -rn | head -30
# defect signal, whole words as in hotspots.py (POSIX classes: git's ERE has no \b on macOS; --grep also scans bodies)
git log --since=12.months --no-merges -i -E --grep='(^|[^[:alnum:]_])(fix(es|ed)?|bug|hotfix|regression|patch)([^[:alnum:]_]|$)' --format= --name-only | sort | uniq -c | sort -rn | head
git shortlog -sn --since=12.months -- billing/          # contributors per area (knowledge risk)
```

## Change coupling

Files that change together in the same commits, with coupling = shared / min(commits_a, commits_b):

```bash
git log --since=12.months --no-merges --format='@@' --name-only | python3 -c '
import sys, itertools, collections
commits, cur = [], []
for line in sys.stdin:
    line = line.strip()
    if line == "@@":
        if cur: commits.append(cur)
        cur = []
    elif line:
        cur.append(line)
if cur: commits.append(cur)
n = collections.Counter(); pair = collections.Counter()
for files in commits:
    files = sorted(set(files))
    if len(files) > 30:      # skip mass reformatting commits
        continue
    n.update(files)
    pair.update(itertools.combinations(files, 2))
rows = [(s / min(n[a], n[b]), s, a, b) for (a, b), s in pair.items() if s >= 10]
for c, s, a, b in sorted(rows, reverse=True)[:30]:
    print(f"{c:.2f}\t{s}\t{a}\t{b}")'
```
High coupling between files with no import relationship (two services, code and its hand-written
schema copy) is a design finding.

## Lint baselines and ratchets

| Ecosystem | Baseline mechanism |
|---|---|
| ESLint 9.24+ | `--suppress-all` / `--suppress-rule <rule>` writes `eslint-suppressions.json` (per-file, per-rule counts); commit it; `--prune-suppressions` after fixes |
| golangci-lint | `--new-from-rev=<base>` or `--new-from-patch=<file>` reports only new issues |
| detekt / Android lint | baseline XML files generated by the tool |
| basedpyright | `--writebaseline` stores current errors; new ones fail |
| ruff, mypy, clippy | no built-in count baseline: store per-rule counts in a JSON file and compare in CI (SKILL.md section 6) |
