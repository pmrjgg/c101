# golangci-lint v2 configuration

Install the pinned binary (the project recommends its installer over `go install` or `go tool`):
`curl -sSfL https://golangci-lint.run/install.sh | sh -s -- -b "$(go env GOPATH)/bin" v2.15.0`
(v2.15.0 was current in October 2026; pin whatever CI uses). If it must live in go.mod, isolate it:
`go get -tool -modfile=golangci-lint.mod github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.15.0`
and run `go tool -modfile=golangci-lint.mod golangci-lint run`.

## 1. Annotated service config

```yaml
version: "2"

run:
  timeout: 5m                       # v2 default is 0 = no timeout
  relative-path-mode: gomod         # paths in reports relative to go.mod (default: cfg)

linters:
  default: standard                 # errcheck, govet, ineffassign, staticcheck, unused
  enable:
    - bodyclose                     # unclosed http.Response.Body
    - contextcheck                  # functions that drop the incoming ctx
    - copyloopvar                   # redundant v := v copies (go >= 1.22)
    - errorlint                     # == on errors, %v instead of %w, type switches on errors
    - gosec                         # security smells: G112 ReadHeaderTimeout, G114 ListenAndServe, ...
    - intrange                      # for i := 0; i < n; i++ -> for i := range n
    - modernize                     # the go fix modernizers as diagnostics
    - nilerr                        # returns nil while holding a non-nil err
    - noctx                         # HTTP requests or DB calls without ctx
    - nolintlint                    # //nolint must name linters and give a reason
    - prealloc                      # slices that could be preallocated (advisory)
    - revive                        # style rules, configurable
    - sloglint                      # consistent slog usage (attrs vs key-value pairs)
    - unconvert                     # unnecessary conversions
    - usetesting                    # os.Setenv/os.MkdirTemp/context.Background in tests -> t.Setenv/t.TempDir/t.Context
  settings:
    govet:
      enable: [shadow]
    errorlint:
      errorf: true                  # require %w when wrapping
    nolintlint:
      require-explanation: true
      require-specific: true
    revive:
      rules:
        - name: exported            # exported identifiers need doc comments
        - name: context-as-argument
        - name: error-return
    staticcheck:
      checks: ["all", "-ST1000"]    # all SA/S/ST/QF checks except the package-comment rule
  exclusions:
    generated: lax                  # skip files with generated headers
    presets: [comments, std-error-handling, common-false-positives]
    rules:
      - path: _test\.go
        linters: [gosec, prealloc]
      - path: internal/store/       # sqlc output
        linters: [revive]

formatters:
  enable: [gofumpt, goimports]
  settings:
    goimports:
      local-prefixes: [example.com/svc]
    gofumpt:
      module-path: example.com/svc

issues:
  max-issues-per-linter: 0          # default 50 hides findings
  max-same-issues: 0                # default 3 hides findings
```

Libraries add `exhaustive` (switches over enums), `wrapcheck` (errors from other packages wrapped at
the boundary) and stricter `revive` rules; services with SQL add `rowserrcheck` and `sqlclosecheck`;
OpenTelemetry users add `spancheck`; protobuf users add `protogetter`.

Check names and settings against the installed release before committing: `golangci-lint linters`,
`golangci-lint formatters`, `golangci-lint config verify`.

## 2. Migrating a v1 config

1. `golangci-lint migrate` (add `--format yaml` to change format): writes v2, keeps the old file as
   `<name>.bck.<ext>`, drops comments, deprecated options and unknown keys.
2. Re-add comments; review what moved:

| v1 | v2 |
|---|---|
| `linters.disable-all: true` + `enable` | `linters.default: none` + `enable` |
| `enable-all: true` | `linters.default: all` |
| `gofmt`, `gofumpt`, `goimports`, `gci` under linters | `formatters.enable` |
| `gosimple`, `stylecheck` | part of `staticcheck` |
| `tenv` | removed (use `usetesting`) |
| `issues.exclude-rules` | `linters.exclusions.rules` |
| `issues.exclude-use-default` | `linters.exclusions.presets` |
| `issues.exclude-dirs`, `exclude-files` | `linters.exclusions.paths` |
| `issues.exclude-case-sensitive` | removed: use `(?i)` in the regex |
| `linters-settings` | `linters.settings` |
| `gas`, `goerr113`, `gomnd`, `megacheck`, `vet` | `gosec`, `err113`, `mnd`, `staticcheck`, `govet` |

3. `golangci-lint config verify`, then compare finding counts before and after on the same commit:
   a large drop usually means a silently dropped key.

## 3. Running

```bash
golangci-lint run ./...                               # lint + check formatting
golangci-lint fmt                                     # rewrite files with the configured formatters
golangci-lint fmt --diff                              # show what fmt would change
golangci-lint run --new-from-merge-base ./...         # only issues introduced on this branch
golangci-lint run --fix ./...                         # apply autofixes (review the diff)
golangci-lint run --output.text.path=stdout --output.sarif.path=.stack/out/lint.sarif ./...
golangci-lint cache clean                             # after upgrading golangci-lint or Go
```

## 4. Suppression policy

- `//nolint:gosec // G304: path is joined under os.Root, cannot escape` - always a linter name and a
  reason; `nolintlint` with `require-specific` and `require-explanation` enforces it.
- Prefer a path rule in `linters.exclusions.rules` for whole categories (generated code, tests) over
  scattering `//nolint`.
- Never disable `errcheck`, `govet` or `staticcheck` globally; exclude specific functions or checks.
