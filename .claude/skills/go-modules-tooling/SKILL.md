---
name: go-modules-tooling
description: "Go modules, workspaces and toolchain hygiene. Covers go and toolchain directives, GOTOOLCHAIN, upgrades and tidy, go.work, tool directives, private modules, major versions and retract, golangci-lint v2 configuration, govulncheck and SBOMs, go fix modernizers, build flags, cross-compilation, and releases with goreleaser or ko. Load when managing Go dependencies, linters, builds or releases."
when_to_use: "Editing go.mod, go.sum or go.work; 'go: go.mod requires go >= 1.N (running go 1.M; GOTOOLCHAIN=local)', 'missing go.sum entry', 'unknown revision', 410 Gone from the proxy for private repos; bumping the go line; .golangci.yml v1 to v2; govulncheck findings; static or cross builds, -ldflags version stamping, goreleaser/ko/distroless images."
---

# Go modules and tooling

Baseline: Go 1.26/1.27 (supported releases in October 2026: 1.26 and 1.27; 1.27.2 current).
golangci-lint v2 (v2.15 current). Commands assume a module root; outputs that agents keep go to
`.stack/out/<agent>/`.

Deep material: [golangci-lint v2 configuration](references/golangci-v2.md) |
[release pipelines](references/release-pipelines.md) (goreleaser, ko, Dockerfile, CI gate script).

Orient first; record the `go` and `toolchain` lines, linter config, generators, and whether the module
is a library (API and `go` line are promises) or a service:

```bash
go version; go env GOVERSION GOFLAGS GOEXPERIMENT GOTOOLCHAIN
head -5 go.mod; ls go.work 2>/dev/null; grep -n '^tool' go.mod
go list -m all | wc -l                                   # dependency count
ls .golangci.yml .golangci.yaml 2>/dev/null; grep -rn 'go:generate' --include=*.go . | head
go list ./... | head -30                                 # package layout
```

## 1. Directive semantics

| Line | Meaning |
|---|---|
| `go 1.26.0` | minimum Go version (hard requirement since 1.21) and the language version of the module's files |
| `toolchain go1.27.2` | suggested toolchain; only consulted when this is the main module |
| `godebug default=go1.21` (1.23+) | GODEBUG defaults independent of the language version (main module only) |
| `tool golang.org/x/tools/cmd/stringer` (1.24+) | executable dependency, run with `go tool` |
| `ignore ./node_modules` (1.25+) | directories excluded from `./...` and `all` |

`GOTOOLCHAIN` (default `auto` = `local+auto` from `$GOROOT/go.env`): `local` never switches and
refuses to build a module whose `go` line is newer; `go1.27.2` always uses that release (downloaded
if missing); `go1.27.2+auto` starts there and may switch higher; `path`/`+path` never downloads.
`go env GOTOOLCHAIN`, `go version` and `go env -changed` (1.23) show what is in effect.

What the `go` line controls, and therefore what changes when you raise it:

| Area | Examples |
|---|---|
| language features | range over int (1.22), range over func (1.23), generic type aliases (1.24), `new(expr)` (1.26), generic methods (1.27) |
| semantics | per-iteration loop variables (1.22) |
| GODEBUG defaults (main module) | `httpmuxgo121` (ServeMux patterns, 1.22), `asynctimerchan` (synchronous timer channels, 1.23); list with `go list -f '{{.DefaultGODEBUG}}' ./cmd/app` |
| vet | printf flags non-constant format strings at 1.24+; `stdversion` (run by `go test` since 1.27) flags std APIs newer than the line |
| modernizers | `go fix` only proposes features the file's version allows |
| tidy | 1.27+ merges duplicate require blocks into one direct and one indirect block |
| consumers | everyone building against your module needs at least this toolchain |

Rules: libraries raise the `go` line only when they use a feature or API that needs it (it is a
breaking change for consumers on older toolchains) and keep it at the oldest release CI tests;
services track the newest supported release. `go get go@1.26.0` writes the release form; a bare
`go 1.26` also admits 1.26 release candidates. `go mod init` on 1.26 writes `go 1.25.0` (previous minor).
Services pin `toolchain` to the CI version for reproducible builds; libraries usually drop it
(`go get toolchain@none`). Since 1.27 a `godebug` or `//go:debug` setting whose support was removed
fails the build if set to an old value.

## 2. Dependency commands

| Task | Command |
|---|---|
| add or move one module | `go get example.com/pkg@v1.4.2` (`@latest`, `@patch`, a commit hash gives a pseudo-version) |
| remove | `go get example.com/pkg@none && go mod tidy` |
| patch upgrades of the build list | `go get -u=patch ./...` |
| minor and patch upgrades | `go get -u ./...` (add `-t` for test deps); review the go.mod diff and changelogs |
| available upgrades | `go list -m -u all` (`[v1.5.0]` suffix), `go list -m -u -json all` for tooling |
| all versions of a module | `go list -m -versions example.com/pkg` |
| why is it here | `go mod why -m example.com/pkg`; `go mod graph \| grep 'example.com/pkg@'` |
| sync go.mod/go.sum with imports | `go mod tidy`; CI gate `go mod tidy -diff` (1.23+, non-zero exit when changes are needed) |
| check the module cache | `go mod verify` |
| block a bad version | `exclude example.com/pkg v1.3.0` (main module only) |
| temporary fork | `go mod edit -replace=example.com/pkg=../pkg` then `-dropreplace` before release |

`replace` and `exclude` apply only in the main module: a library's replaces never reach its
consumers. Minimal version selection picks the highest version any module requires, never "latest",
so versions move only when you run `go get` or a dependency starts requiring a newer one. Count dependencies with `go list -m all | wc -l`.

## 3. Workspaces

```bash
go work init ./svc ./lib            # go.work with use directives
go work use ./tools                 # add one; go work use -r . adds every module below
go work sync                        # write the workspace build list back to each go.mod
GOWORK=off go test ./...            # prove a module builds alone (run this in CI per module)
```

- Use a workspace for local multi-module development instead of committing `replace` lines; a
  forgotten `replace ../lib` breaks every consumer and release.
- Do not commit `go.work` (and `go.work.sum`) for modules that are built or published on their own;
  CI must see what consumers see. A monorepo whose modules always build together may commit it and
  still runs `GOWORK=off` checks for published modules.
- In a workspace, `godebug` lines come from `go.work`, and `go.mod` `godebug` lines are ignored.
  `go work vendor` (1.22) vendors the whole workspace.

## 4. Tools as dependencies (1.24+)

```bash
go get -tool golang.org/x/tools/cmd/stringer       # adds `tool` and `require` lines
go tool stringer -type=State ./internal/order      # runs it; binary cached in the build cache
go get tool                                        # upgrade every tool (= go get tool@upgrade)
go install tool                                    # install all tools into GOBIN
go get -tool golang.org/x/tools/cmd/stringer@none  # remove the tool line
```

`//go:generate go tool stringer -type=State` replaces `tools.go` blank imports. Tool requirements join
your build list and MVS: a tool can raise a dependency your code uses. Isolate heavy tools in their own
modfile: `go get -tool -modfile=tools.mod <pkg>@<ver>` and `go tool -modfile=tools.mod <name>`.
golangci-lint recommends its binary installer over any `go install`/`go tool` route.

## 5. Private modules

```bash
go env -w GOPRIVATE='github.com/acme/*,*.corp.example.com'   # skips proxy.golang.org and sum.golang.org
git config --global url."git@github.com:acme/".insteadOf "https://github.com/acme/"  # SSH for git fetches
```

- `GOPRIVATE` is the default for `GONOPROXY` and `GONOSUMDB`; set those separately only when a
  private proxy should still serve private modules (`GOPROXY=https://goproxy.corp.example.com`,
  `GONOPROXY=none`, `GONOSUMDB=*.corp.example.com`). Athens or Artifactory as `GOPROXY` cache public
  modules too and keep builds working during upstream outages.
- HTTPS auth: `GOAUTH` (1.24, default `netrc`) reads `~/.netrc` (`machine github.com login <user> password <token>`,
  mode 0600, token from the CI secret store); `GOAUTH='git /path/to/repo'` uses `git credential fill`.
  Never commit tokens or echo them in logs.
- Symptoms: `410 Gone` or `unknown revision` from the public proxy, or `verifying module: ... not found`
  from the checksum DB, mean the path is missing from `GOPRIVATE`. Never set `GOSUMDB=off` or
  `GOINSECURE` globally to "fix" it.

## 6. Versioning and compatibility

- Tags are semver `vMAJOR.MINOR.PATCH`; a module in a subdirectory is tagged `sub/v1.2.3`. `v0` makes
  no promises; `v1` freezes the API; pre-releases `v1.5.0-rc.1` are never chosen by `@latest`.
- Major version 2+: the module path ends in `/v2` (major branch: edit the `module` line; or major
  subdirectory `v2/`), every import path changes, and old majors keep working side by side. Tags
  `v2+` without `/v2` resolve as `+incompatible`.
- Retract: add `retract v1.3.0 // data loss on Close` (or a range `[v1.3.0, v1.3.2]`) to go.mod and
  publish a higher version containing it; consumers see the reason in `go list -m -u` and `go get`.
  Tags are immutable once the proxy has fetched them: never move or re-push a tag.
- Deprecate a whole module with a `// Deprecated: use example.com/mod/v2 instead.` comment directly
  above the `module` line; deprecate identifiers with a `Deprecated:` paragraph in their doc comment
  plus `//go:fix inline` on simple wrappers so `go fix` (1.26+) rewrites callers.
- Before tagging a library: `gorelease -base=v1.4.0 -version=v1.5.0` (golang.org/x/exp/cmd/gorelease,
  experimental) checks the proposed version against API changes; `apidiff` (golang.org/x/exp/cmd/apidiff)
  lists breaking changes: `apidiff -m -w .stack/out/old.api example.com/mod` on the old tag, then
  `apidiff -m -incompatible .stack/out/old.api example.com/mod` on the candidate.
- After tagging: `GOPROXY=proxy.golang.org go list -m example.com/mod@v1.5.0` makes the proxy and
  pkg.go.dev fetch it. Pushing a tag (including a retraction release) is irreversible once the proxy
  caches it: agents prepare the commit and return the push as an Open doubt for the user.

## 7. Linting and the CI gate

| Step | Command | Blocks when |
|---|---|---|
| format | `test -z "$(gofmt -l .)"` or, with configured formatters, `test -z "$(golangci-lint fmt --diff)"` | any output |
| vet + lint | `go vet ./... && golangci-lint run ./...` (or `staticcheck ./...`) | any finding |
| build | `go build ./...` | failure |
| test | `go test -race -shuffle=on -count=1 ./...` | failure or race report |
| tidy | `go mod tidy -diff` | non-empty diff |
| vulnerabilities | `govulncheck ./...` | a reachable vulnerable symbol |
| fuzz (changed parsers) | `go test -run='^$' -fuzz='^FuzzX$' -fuzztime=60s ./pkg` | new crasher |

Cheap rows first; script in [release pipelines](references/release-pipelines.md).

```yaml
version: "2"
linters:
  default: standard            # errcheck, govet, ineffassign, staticcheck, unused
  enable: [bodyclose, copyloopvar, errorlint, gosec, intrange, modernize, nilerr, noctx, revive, sloglint, usetesting]
  settings:
    govet:
      enable: [shadow]
  exclusions:
    generated: lax
    presets: [comments, std-error-handling, common-false-positives]
formatters:
  enable: [gofumpt, goimports]
  settings:
    goimports:
      local-prefixes: [example.com/svc]
```

- v2 moved formatters out of `linters`, folded `gosimple` and `stylecheck` into `staticcheck`, removed
  `tenv` (use `usetesting`), and replaced `issues.exclude-rules` with `linters.exclusions.rules`.
  Convert with `golangci-lint migrate` (comments are lost, the old file is kept as a `.bck` copy);
  check with `golangci-lint config verify`; format with `golangci-lint fmt`.
- `run.timeout` defaults to 0 (disabled) in v2; `issues.max-issues-per-linter` (50) and
  `issues.max-same-issues` (3) hide findings: set both to 0 in CI.
- Adopting on a legacy codebase: `golangci-lint run --new-from-rev=origin/main` (or
  `--new-from-merge-base`) gates only new issues; burn down the rest one linter at a time.
- `go vet ./...` stays in the gate (fast, no config); `staticcheck ./...` standalone when
  golangci-lint is not used. Every `//nolint:linter // reason` names the linter and the reason
  (enforce with `nolintlint`). Linter names change between releases: check them with
  `golangci-lint linters` before committing a config. Annotated config: [golangci-lint v2](references/golangci-v2.md).

## 8. Security

```bash
govulncheck ./...                          # source mode: reports only vulnerabilities your code can reach
govulncheck -show verbose ./...            # plus imported-but-unreachable and required-but-unused findings
govulncheck -mode=binary ./bin/app         # what actually shipped (no call stacks; may over-report)
govulncheck -format sarif ./... > .stack/out/vuln.sarif   # code scanning upload; exits 0 in this mode
```

- Gate on text mode (non-zero exit on findings); JSON, SARIF and OpenVEX output always exit 0.
- Fix: `go get example.com/mod@<fixed version>` from the report; standard library findings are fixed
  by a newer toolchain (bump `toolchain` or the CI image). There is no suppression mechanism: document
  unreachable findings in the PR rather than pinning old tools.
- Dependency review for every new `require`: `go mod why -m`, maintenance activity, licence, transitive
  weight (`go mod graph | grep -c '^example.com/new@'`), and whether the stdlib or an existing dependency
  already covers it.
- SBOM: `cyclonedx-gomod app -json -output .stack/out/sbom.cdx.json -licenses -main cmd/app .`
  (only modules the binary links; set GOOS/GOARCH/CGO_ENABLED as for the real build) or `bin` mode on a
  built binary; `go version -m -json ./bin/app` (1.25) dumps the embedded build info.

## 9. Modernization

- `go fix ./...` (1.26+) runs the modernize analyzers: `any`, `forvar` (drops `v := v`), `rangeint`,
  `minmax`, `slicescontains`, `stringscut`, `stringsseq`, `testingcontext`, `waitgroupgo` (`wg.Go`),
  `errorsastype` (`errors.AsType`), `newexpr`, `omitzero` and more; 1.27 added `atomictypes`,
  `embedlit`, `slicesbackward`, `unsafefuncs`, renamed `waitgroup` to `waitgroupgo` and removed
  `fmtappendf`. Some (`bloop`, `appendclipped`, `slicesdelete`) are off by default.
- Review first: `go fix -diff ./... > .stack/out/gofix.diff` (non-zero exit when there is a diff), then
  apply; land it as its own commit, separate from behaviour changes. Run twice if fixes conflict.
- Newer analyzers than your toolchain ships: `go run golang.org/x/tools/go/analysis/passes/modernize/cmd/modernize@latest -fix ./...`
  (not a supported interface); gopls shows the same diagnostics with quick fixes in the editor.
- Loop variables when crossing 1.22: raise the `go` line, list loops whose semantics changed with
  `go build -gcflags=-d=loopvar=2 ./... 2>&1 | grep 'now per-iteration'`, and if a test fails,
  `go install golang.org/x/tools/cmd/bisect@latest && bisect -compile=loopvar go test ./pkg` names the
  loop. Failures are almost always tests that passed by accident (shared variable with `t.Parallel`).

## 10. Builds and releases

```bash
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath \
  -ldflags="-s -w -X main.version=$(git describe --tags --always --dirty)" -o bin/app ./cmd/app
go version -m bin/app            # toolchain, module versions, -ldflags, vcs.revision, vcs.modified
```

| Concern | Rule |
|---|---|
| static binary | `CGO_ENABLED=0` (pure-Go DNS resolver and os/user); cgo is off by default when cross-compiling or when no C compiler is found |
| targets | `go tool dist list`; `GOAMD64=v3` for newer x86 (1.25+ uses FMA there, floats may differ in the last bit) |
| version stamping | `-X` sets only package-level `string` vars that are uninitialized or constant-initialized; 1.24+ also stamps the main module version from the VCS tag (`+dirty` on modified trees), readable via `debug.ReadBuildInfo()`; `-buildvcs=false` omits VCS info |
| size | `-s -w` drop the symbol table and DWARF (stack traces and pprof still work) |
| build tags | `//go:build linux && !cgo` as the first line; `go build -tags=integration`; `go vet` checks the syntax |
| assets | `//go:embed static` into `embed.FS`; directory patterns skip files starting with `.` or `_` unless written `all:static` |
| reproducible | same toolchain (pin `toolchain`), `-trimpath`, same env (`CGO_ENABLED`, `GOAMD64`, `GOFLAGS`), no timestamps in `-ldflags`, clean tree; verify by building twice in different directories and comparing `sha256sum` |
| PGO | `default.pgo` in the main package directory is used automatically; merge profiles with `go tool pprof -proto a.pprof b.pprof > default.pgo` (`go-profiling-pprof`) |
| air-gapped / vendored | `go mod vendor`; with a consistent `vendor/` the go command uses `-mod=vendor` automatically; elsewhere `GOFLAGS=-mod=readonly` (the default) keeps builds from editing go.mod |

Releases: goreleaser (`version: 2` config; `goreleaser check`, `goreleaser release --snapshot --clean`
locally, `goreleaser release --clean` on a tag; `mod_timestamp: "{{ .CommitTimestamp }}"` and
`{{.CommitDate}}` keep artefacts reproducible); ko for container-only services
(`KO_DOCKER_REPO=ghcr.io/acme/app ko build --bare --platform=linux/amd64,linux/arm64 ./cmd/app`,
default base `cgr.dev/chainguard/static`, no Dockerfile); otherwise a multi-stage Dockerfile ending in
`gcr.io/distroless/static-debian13:nonroot`. Full configs: [release pipelines](references/release-pipelines.md).

## 11. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `go: go.mod requires go >= 1.26.0 (running go 1.25.4; GOTOOLCHAIN=local)` | old local toolchain with switching disabled | `GOTOOLCHAIN=auto`, or install the version |
| a `toolchain` line appeared after `go get` | commands that update the `go` line record their own toolchain | keep it for services, `go get toolchain@none` for libraries |
| `missing go.sum entry for module providing package` | go.sum out of sync | `go mod tidy`; gate with `go mod tidy -diff` |
| `410 Gone` / `unknown revision` on a private repo | not in `GOPRIVATE` | `go env -w GOPRIVATE=...` plus git auth |
| consumers break after a minor release | `go` line raised or API removed | gorelease/apidiff before tagging; retract |
| routing, timer or TLS behaviour changed after raising the `go` line | GODEBUG defaults follow the `go` line | diff `go list -f '{{.DefaultGODEBUG}}'` before and after; pin with a `godebug` block while fixing |
| `-X main.version` has no effect | wrong package path or the var is not a plain string | `-X 'example.com/app/internal/build.Version=...'` on a `var Version string` |
| binary needs glibc in a scratch image | cgo on by default for native builds | `CGO_ENABLED=0` |
| golangci-lint finds nothing after migration | v1 config keys silently dropped | `golangci-lint config verify`; `migrate` |
| CI green, release build differs | workspace `go.work` used locally | `GOWORK=off` in CI and release builds |

## 12. Worked example: a service from `go 1.21` to `go 1.26.0`

Start: `module example.com/orders`, `go 1.21`, no toolchain line; Go 1.27.2 installed and in CI.

```bash
git switch -c go126
mkdir -p .stack/out/go-expert
go list -f '{{.DefaultGODEBUG}}' ./cmd/orders > .stack/out/go-expert/godebug-before.txt
go test -race -count=1 ./... > .stack/out/go-expert/test-before.txt 2>&1   # baseline must be green

go get go@1.26.0                         # go line -> 1.26.0; may also record "toolchain go1.27.2"
go mod tidy && go mod tidy -diff         # empty diff
go list -f '{{.DefaultGODEBUG}}' ./cmd/orders > .stack/out/go-expert/godebug-after.txt
diff .stack/out/go-expert/godebug-before.txt .stack/out/go-expert/godebug-after.txt
```

The GODEBUG diff lists defaults that flipped with the line (for example `httpmuxgo121` and
`asynctimerchan` disappear because the new behaviour is now default); each is a behaviour change to
test, or to pin temporarily with a `godebug` block while fixing.

Loop-variable audit:

```bash
go build -gcflags=-d=loopvar=2 ./... 2>&1 | grep 'now per-iteration' | tee .stack/out/go-expert/loopvar.txt
# internal/batch/run.go:48:7: loop variable job now per-iteration, heap-allocated
go test -race -shuffle=on -count=1 ./...
bisect -compile=loopvar go test ./internal/pricing   # only for a package whose tests now fail
```

Classify each reported loop: closure or goroutine capture (an old bug now fixed: add a regression
test), `&v` stored across iterations (pointers are now distinct: check code that relied on aliasing),
heap-allocated in a hot loop (benchmark with `-count=10` and benchstat; usually noise). Example
outcome: 14 loops, 1 table test that had silently checked only its last case, 0 hot-path regressions.

Vet, modernize, lint, vulnerabilities:

```bash
go vet ./...
# internal/notify/mail.go:57:13: non-constant format string in call to fmt.Errorf
#   fix: fmt.Errorf("%s", msg) or errors.New(msg)
go fix -diff ./... > .stack/out/go-expert/gofix.diff; go fix ./...    # forvar, rangeint, minmax, any, ...
golangci-lint run ./...                  # copyloopvar/intrange leftovers, errorlint
govulncheck ./...                        # stdlib findings vanish with the newer toolchain;
go get example.com/dep@v1.8.3            # module findings: the "Fixed in" version from the report
```

Final gate and commits:

```bash
go build ./... && go vet ./... && go test -race -shuffle=on -count=1 ./... \
  && go mod tidy -diff && govulncheck ./... && golangci-lint run ./...
git commit -am "go: raise go line to 1.26.0"                   # bump + tidy + loopvar test fixes
git commit -am "go fix: apply 1.26 modernizers"                # mechanical, review by skimming
git commit -am "lint and vet fixes after go 1.26 bump"
```

Three commits keep the behaviour change reviewable apart from the mechanical rewrite. Roll back
by reverting the first commit only if a GODEBUG-driven behaviour change cannot be fixed in time.

Related: `go-testing-fuzzing` (race, shuffle and fuzz gates), `go-http-services` (ServeMux and
GODEBUG-sensitive behaviour), `go-profiling-pprof` (PGO, benchmarks), `go-concurrency-context`,
`go-interfaces-generics`, `security-review`; hub `go-craft`.
