# Debugging tools cheat-sheet

Commands are for local or test environments you are entitled to inspect. Attaching debuggers or tracers
to production processes needs the caller's explicit go-ahead (it can pause or slow the process).

## Native debuggers

Agents have no TTY: run debuggers in batch mode only. The interactive forms below are for humans.
```
gdb -q -batch -ex run -ex 'thread apply all bt full' --args ./prog arg1 arg2
lldb --batch -o run -o 'bt all' -- ./prog arg1
rr replay -- -batch -ex continue -ex 'watch -l x' -ex reverse-continue -ex bt
```

### gdb (Linux)
```
gdb --args ./prog arg1 arg2
(gdb) run
(gdb) bt full                         # backtrace with locals
(gdb) thread apply all bt             # every thread (hangs, deadlocks)
(gdb) break file.c:120 if n > 1000    # conditional breakpoint
(gdb) watch -l obj->count             # hardware watchpoint on the location
(gdb) catch throw                     # stop where a C++ exception is thrown
(gdb) info registers / x/16xb ptr     # raw memory
gdb -p <pid>                          # attach
gdb ./prog core                       # post-mortem on a core dump
```

### lldb (macOS, also Linux)
```
lldb -- ./prog arg1
(lldb) run
(lldb) bt all
(lldb) breakpoint set -f file.c -l 120 -c 'n > 1000'
(lldb) watchpoint set expression -- &obj->count
(lldb) frame variable
(lldb) process attach --pid <pid>
(lldb) target create ./prog --core core.1234
```

### rr (record and replay, Linux x86-64; some AMD and ARM configurations supported)
```
rr record ./prog args          # or: rr record --chaos ./prog  (randomized scheduling to expose races)
rr replay                      # gdb interface on the recording
(rr) continue                  # run to the failure
(rr) watch -l x                # then:
(rr) reverse-continue          # back to the last write of x
(rr) reverse-next / reverse-step / reverse-finish
```
Deterministic: every replay is identical, so you can iterate on the same failing execution.

## Language debuggers and runtime dumps

| Language | Interactive | Dump all stacks of a live process | Notes |
|---|---|---|---|
| Python | `breakpoint()`, `python -m pdb -c continue app.py`, debugpy in IDEs | `py-spy dump --pid <pid>` | `python -X faulthandler` prints tracebacks on segfaults; `faulthandler.dump_traceback_later(30)` for hangs |
| Go | `dlv debug ./cmd/app`, `dlv test ./pkg -- -test.run TestX`, `dlv attach <pid>` | `kill -QUIT <pid>` (prints goroutines, exits), `curl localhost:6060/debug/pprof/goroutine?debug=2` | `GOTRACEBACK=all` or `crash` for core dumps; `goroutines` and `goroutine <n> bt` in dlv |
| Rust | `rust-lldb`/`rust-gdb target/debug/app` | gdb/lldb `thread apply all bt` | `RUST_BACKTRACE=1` or `full`; `RUST_LOG=debug` with `env_logger`/`tracing-subscriber` |
| JVM | `-agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address=*:5005` + IDE | `jcmd <pid> Thread.print`, `jstack <pid>` | `-XX:+HeapDumpOnOutOfMemoryError`; analyse `.hprof` with Eclipse MAT |
| Node | `node --inspect-brk app.js` + Chrome DevTools | `kill -USR1 <pid>` enables the inspector on a running process | `--trace-warnings`, `--unhandled-rejections=strict`, `--trace-uncaught` |
| Haskell | GHCi debugger (`:break`, `:trace`) | `+RTS -xc` (profiling build) prints cost-centre stacks on exceptions | `Debug.Trace` for quick probes; `HasCallStack` constraints for call stacks |
| Julia | Debugger.jl `@enter f(x)`, Infiltrator.jl `@infiltrate` | `kill -USR1 <pid>` / `Ctrl-T` prints a profile peek (Julia 1.8+, platform dependent) | `@show`, `@which`, `@code_warntype` |

## Sanitizers and memory checkers

```bash
# C/C++ (clang or gcc)
-fsanitize=address,undefined -fno-omit-frame-pointer -g      # ASan + UBSan
-fsanitize=thread -g                                         # TSan (separate build; not with ASan)
-fsanitize=memory -fsanitize-memory-track-origins -g         # MSan (clang, Linux, needs instrumented deps)
ASAN_OPTIONS=detect_leaks=1:abort_on_error=1 UBSAN_OPTIONS=print_stacktrace=1 ./prog
valgrind --leak-check=full --track-origins=yes ./prog        # slower, no rebuild needed

# Rust
cargo +nightly miri test                                     # UB in unsafe code, interpreted (slow)
RUSTFLAGS="-Zsanitizer=address" cargo +nightly test --target x86_64-unknown-linux-gnu
RUSTFLAGS="--cfg loom" cargo test --release --test <loom_test> # loom: exhaustive interleavings (models behind #[cfg(loom)])

# Go
go test -race ./...                                          # data race detector
GODEBUG=gctrace=1,schedtrace=1000 ./app                      # GC and scheduler tracing

# Java
java -XX:+UnlockDiagnosticVMOptions -XX:+LogCompilation ...  # JIT issues (rare)
```

## System-level tracing

```bash
strace -f -tt -e trace=file,network -o trace.txt ./prog     # Linux: files and sockets, with timestamps
strace -f -c ./prog                                         # syscall counts and time
ltrace -f ./prog                                            # library calls
lsof -p <pid>                                               # open files, sockets
ss -tanp | grep <pid>                                       # TCP connections (Linux)
# macOS fs_usage/dtruss need root (dtruss also needs SIP disabled): never run them unattended; return the
# need as an Open doubt for the user and use `lsof -p <pid>` and
# `sample <pid> 10 -file .stack/out/<agent>/<YYYYMMDD-HHMM>-sample.txt` meanwhile
tcpdump -i any -w cap.pcap port 5432                        # packets; open in Wireshark
bpftrace -e 'tracepoint:syscalls:sys_enter_openat /comm == "app"/ { printf("%s\n", str(args->filename)); }'
```

## Logs and traces

- Correlation IDs through every hop; log at boundaries (request in/out, external calls) with durations.
- Compare a good and a bad request's trace span trees (OpenTelemetry/Jaeger/Tempo): the first span whose
  attributes or timing diverge localizes the fault.
- Raise log level for one module only (`RUST_LOG=app::billing=trace`, `logging.getLogger("app.billing").setLevel`)
  to avoid drowning the signal.

## Reducers and bisection helpers

```bash
git bisect run ./repro.sh                    # exit 0 good, 1 bad, 125 skip
cvise ./interesting.sh case.c                # interesting.sh exits 0 while the bug is still present
creduce ./interesting.sh case.c
shrinkray ./interesting.sh input.txt         # general-purpose test-case reducer
cargo fuzz tmin <target> <crash-file>
./fuzzer -minimize_crash=1 -runs=100000 crash-file
```

Manual ddmin for line-based inputs (when no tool fits):
```python
def ddmin(lines, fails):
    """fails(list_of_lines) -> True when the bug reproduces. Returns a 1-minimal failing subset."""
    n = 2
    while len(lines) >= 2:
        chunk = max(1, len(lines) // n)
        subsets = [lines[i:i + chunk] for i in range(0, len(lines), chunk)]
        reduced = False
        for i, s in enumerate(subsets):
            complement = [x for j, t in enumerate(subsets) if j != i for x in t]
            if fails(s):
                lines, n, reduced = s, 2, True
                break
            if fails(complement):
                lines, n, reduced = complement, max(n - 1, 2), True
                break
        if not reduced:
            if n >= len(lines):
                break
            n = min(len(lines), n * 2)
    return lines
```
