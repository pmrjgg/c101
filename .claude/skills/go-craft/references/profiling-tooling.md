# Go profiling, GC tuning and tooling cheat-sheet

## 1. Collecting profiles

From tests and benchmarks:

```bash
go test -run=^$ -bench=Hot -benchmem -cpuprofile cpu.out -memprofile mem.out ./pkg
go test -run=^$ -bench=Hot -mutexprofile mutex.out -blockprofile block.out ./pkg
go test -run=^$ -bench=Hot -trace trace.out ./pkg
```

From a running service (admin listener only, never the public port):

```go
import _ "net/http/pprof"
go func() { log.Println(http.ListenAndServe("127.0.0.1:6060", nil)) }()
// for mutex/block profiles, opt in at startup:
runtime.SetMutexProfileFraction(5)     // sample 1/5 contention events
runtime.SetBlockProfileRate(10_000)    // ~1 sample per 10µs spent blocked (rate is in ns)
```

```bash
curl -o cpu.pprof   'http://127.0.0.1:6060/debug/pprof/profile?seconds=30'
curl -o heap.pprof  'http://127.0.0.1:6060/debug/pprof/heap'
curl -o allocs.pprof 'http://127.0.0.1:6060/debug/pprof/allocs'
curl -o gor.txt     'http://127.0.0.1:6060/debug/pprof/goroutine?debug=2'
curl -o trace.out   'http://127.0.0.1:6060/debug/pprof/trace?seconds=5'
```

## 2. Reading profiles

```bash
go tool pprof -http=:0 cpu.pprof                       # web UI (blocks, needs a browser): humans only
go tool pprof -top -cum cpu.pprof | head -30           # cumulative hot paths
go tool pprof -list 'pkg.(*T).Method' cpu.pprof        # line-level
go tool pprof -sample_index=alloc_space -top heap.pprof | head -30   # total bytes allocated
go tool pprof -sample_index=inuse_space -top heap.pprof | head -30   # live bytes (leaks)
go tool pprof -diff_base=before.pprof -top after.pprof | head -30    # regression diff
```

| Heap sample index | Answers |
|---|---|
| `inuse_space` / `inuse_objects` | what is retained now (memory leaks, cache sizing) |
| `alloc_space` / `alloc_objects` | what churns (GC pressure, CPU in mallocgc) |

Execution trace: agents run `go tool trace -pprof=sched trace.out > sched.pprof` (also `sync`,
`syscall`, `net`), then `go tool pprof -top sched.pprof | head -30`. The `go tool trace trace.out`
web UI (blocks; humans only) shows "Goroutine analysis" for scheduler
latency, "Synchronization blocking" and "Syscall" profiles, GC pauses and mark assists. Use the
flight recorder (`runtime/trace.FlightRecorder`, 1.25) to keep the last few seconds of trace in
memory and write it out when a slow request is detected.

## 3. Escape analysis and inlining

```bash
go build -gcflags='-m' ./pkg 2>&1 | grep -E 'escapes to heap|moved to heap'
go build -gcflags='-m=2' ./pkg 2>&1 | grep 'cannot inline'          # why not inlined
go build -gcflags='-d=ssa/check_bce/debug=1' ./pkg                   # bounds checks left in
```

Common escape causes: returning a pointer to a local, storing into an interface (`any`,
`fmt.Println` args), closures capturing variables that outlive the frame, slices whose size is
not a compile-time constant (`make([]byte, n)`), sending pointers on channels.

## 4. GC and memory tuning

| Knob | Effect | Guidance |
|---|---|---|
| `GOGC` (default 100) | heap grows to live*(1+GOGC/100) before next cycle | raise (200-400) to trade memory for less GC CPU |
| `GOMEMLIMIT` (e.g. `900MiB`) | soft limit; GC works harder near it | set to ~90% of the container memory limit; combine with `GOGC=off` only with a hard limit and headroom |
| `GOMAXPROCS` | OS threads running Go code | 1.25+ respects cgroup CPU limits automatically; older versions use `go.uber.org/automaxprocs` |
| `GODEBUG=gctrace=1` | one line per GC with heap sizes and CPU | quick diagnosis of GC frequency |
| Green Tea GC | default in 1.26 (10-40% less GC overhead reported) | opt out with `GOEXPERIMENT=nogreenteagc` at build if regressions appear (removal planned) |

Programmatic metrics: `runtime/metrics` (`/gc/cycles/total:gc-cycles`, `/memory/classes/heap/objects:bytes`,
`/sched/latencies:seconds`); export via Prometheus client's Go collector.

Memory leak triage: two `inuse_space` heap profiles minutes apart, `-diff_base` the first;
growth concentrated in one allocation site is the leak. Goroutine leaks show up as a growing
goroutine count with identical stacks.

## 5. Static analysis and linters

```bash
go vet ./...
staticcheck ./...                                      # honnef.co/go/tools
golangci-lint run ./...                                # v2 config format (`version: "2"`)
govulncheck ./...                                      # reachability-aware vuln scan
go fix ./...                                           # 1.26 modernizers (review the diff)
```

A reasonable golangci-lint v2 baseline:

```yaml
version: "2"
linters:
  default: standard            # errcheck, govet, ineffassign, staticcheck, unused
  enable: [bodyclose, contextcheck, errorlint, gosec, noctx, nilerr, prealloc, revive, unconvert, copyloopvar]
  settings:
    govet:
      enable: [shadow]
formatters:
  enable: [gofumpt, goimports]
```

Verify linter names against the installed golangci-lint version (`golangci-lint linters`)
before committing the config.

## 6. Coverage

```bash
go test -coverprofile=cover.out -covermode=atomic -coverpkg=./... ./...
go tool cover -func=cover.out | tail -1
go tool cover -html=cover.out -o .stack/out/<agent>/cover.html   # writes a file, no browser
# integration/binary coverage (1.20+)
go build -cover -o app ./cmd/app && GOCOVERDIR=covdata ./app ... && go tool covdata percent -i=covdata
```

## 7. Builds and binaries

| Task | Command |
|---|---|
| static Linux binary | `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags='-s -w' ./cmd/app` |
| embed version | `-ldflags="-X main.version=$(git describe --tags)"` or read `debug.ReadBuildInfo()` |
| build info of a binary | `go version -m ./app` |
| PGO | place `default.pgo` (merged CPU profiles: `go tool pprof -proto a.pprof b.pprof > default.pgo`) in main package dir |
| reproducible | `-trimpath`, pinned `toolchain` line, `GOFLAGS=-mod=readonly` |
| vendoring (air-gapped) | `go mod vendor`; CI uses `-mod=vendor` automatically when vendor/ is consistent |

## 8. Debugging

- Delve is interactive; agents script it: `printf 'break pkg/file.go:42\ncontinue\nprint x\nexit\n' |
  dlv test ./pkg --allow-non-terminal-interactive=true -- -test.run TestX`; `dlv core ./app core.123`
  the same way. `dlv attach <pid>` (and any dlv run on macOS without Developer Tools access
  enabled) needs an OS approval dialog: return it as an Open doubt.
- Hung process: `kill -QUIT <pid>` prints all goroutine stacks (set `GOTRACEBACK=all` or `crash`
  for core dumps).
- Race report reading: the two stacks are the conflicting accesses; "Previous write at" plus the
  goroutine creation stacks tell you which goroutines to synchronize.
