# Standard library errors and how to test for them

Always test with `errors.Is` / `errors.As` / `errors.AsType`: callers in between may have wrapped.

| Error | Test | Meaning and handling |
|---|---|---|
| `io.EOF` | `errors.Is(err, io.EOF)` (Readers return it unwrapped, so `==` also works at the source) | normal end of input; not a failure |
| `io.ErrUnexpectedEOF` | `errors.Is` | input truncated mid-record: client error for request bodies |
| `fs.ErrNotExist`, `fs.ErrExist`, `fs.ErrPermission` | `errors.Is(err, fs.ErrNotExist)` | `os.IsNotExist` and friends predate wrapping and do not unwrap |
| `*fs.PathError` (`os.PathError`) | `errors.AsType[*fs.PathError](err)` | fields `Op`, `Path`, `Err` |
| `os.ErrDeadlineExceeded` | `errors.Is` | an I/O deadline set with `SetDeadline` passed |
| `context.Canceled`, `context.DeadlineExceeded` | `errors.Is`; `context.Cause(ctx)` for the recorded reason | caller gave up / budget exhausted |
| `sql.ErrNoRows` | `errors.Is` | `QueryRow(...).Scan` found nothing: translate to a domain `ErrNotFound` |
| `sql.ErrTxDone`, `sql.ErrConnDone` | `errors.Is` | use of a finished transaction or closed connection: programming error |
| `net.Error` (interface with `Timeout() bool`) | `var ne net.Error; errors.As(err, &ne) && ne.Timeout()` | `Temporary()` is deprecated (1.18): do not use it for retry decisions |
| `*net.OpError` | `errors.AsType[*net.OpError](err)` | `Op`, `Net`, `Addr`, wrapped `Err` |
| `*net.DNSError` | `errors.AsType[*net.DNSError](err)` | `IsNotFound`, `IsTimeout` fields |
| `net.ErrClosed` | `errors.Is` | "use of closed network connection": expected during shutdown |
| `syscall.ECONNREFUSED`, `ECONNRESET`, `EPIPE` | `errors.Is(err, syscall.ECONNREFUSED)` | wrapped inside `*net.OpError` / `*os.SyscallError` |
| `*url.Error` | `errors.AsType[*url.Error](err)` | every `http.Client` error; has `Timeout()`; `Err` holds the cause |
| `http.ErrServerClosed` | `errors.Is` | returned by `ListenAndServe` after `Shutdown`: not a failure |
| `*http.MaxBytesError` | `errors.AsType[*http.MaxBytesError](err)` | body over the `MaxBytesReader` limit: 413 |
| `http.ErrAbortHandler` | panic value | abort a handler without the server logging a stack |
| `*json.SyntaxError` | `errors.AsType[*json.SyntaxError](err)` | `Offset` of the bad byte: 400 |
| `*json.UnmarshalTypeError` | `errors.AsType[*json.UnmarshalTypeError](err)` | wrong JSON type for a field: 400 |
| `*strconv.NumError` | `errors.AsType[*strconv.NumError](err)`; `errors.Is(err, strconv.ErrRange)` | `Func`, `Num`, `Err` (`ErrSyntax` or `ErrRange`) |
| `*exec.ExitError` | `errors.AsType[*exec.ExitError](err)` | `ExitCode()`, `Stderr` when using `Output()` |
| `exec.ErrNotFound` | `errors.Is` | binary not in `PATH` |
| `errors.ErrUnsupported` | `errors.Is` | 1.21: operation not supported by this implementation |
| `*runtime.PanicNilError` | value returned by `recover()` | 1.21+: `panic(nil)` |

## Wrapping chains produced by common calls

| Call | Typical chain (outer to inner) |
|---|---|
| `http.Client.Do` timeout | `*url.Error` -> `context.DeadlineExceeded` or a `net.Error` with `Timeout()` true |
| `net.Dial` refused | `*net.OpError` -> `*os.SyscallError` -> `syscall.ECONNREFUSED` |
| `os.Open` missing file | `*fs.PathError` -> `syscall.ENOENT` (`errors.Is(err, fs.ErrNotExist)` is true) |
| `db.QueryContext` after cancel | driver-specific wrapper -> often `context.Canceled` (driver dependent: check `ctx.Err()` too) |

## Conventions worth copying from the standard library

- Sentinels are variables created once with `errors.New` (`io.EOF`), never recreated per call.
- Structured types carry the operation and the operand (`Op`, `Path`, `Addr`) and `Unwrap` to the
  cause, so a single `Error()` string reads `open /etc/x: permission denied`.
- Behaviour interfaces (`Timeout() bool`) let callers decide without importing concrete types.
