# gRPC and Connect services

Two stacks over the same protobuf contract: grpc-go (HTTP/2 only, the reference implementation)
and connect-go (`net/http` handlers that speak Connect, gRPC and gRPC-Web over HTTP/1.1 or HTTP/2).
Pick connect-go when browsers, curl-able JSON or a plain `http.ServeMux` matter; grpc-go when you need
its ecosystem (xDS, ORCA load reporting, advanced balancing) or already run it.

## 1. buf layout and generation

```yaml
# buf.yaml
version: v2
modules:
  - path: proto
lint:
  use: [STANDARD]
breaking:
  use: [FILE]
```

```yaml
# buf.gen.yaml
version: v2
managed:
  enabled: true
  override:
    - file_option: go_package_prefix
      value: example.com/svc/gen
plugins:
  - local: ["go", "tool", "protoc-gen-go"]
    out: gen
    opt: paths=source_relative
  - local: ["go", "tool", "protoc-gen-go-grpc"]          # or protoc-gen-connect-go
    out: gen
    opt: paths=source_relative
```

```bash
go get -tool google.golang.org/protobuf/cmd/protoc-gen-go google.golang.org/grpc/cmd/protoc-gen-go-grpc
# connect-go v1: connectrpc.com/connect/cmd/protoc-gen-connect-go; v2: connectrpc.com/connect/v2/cmd/protoc-gen-connect-go
buf format -w && buf lint
buf breaking --against '.git#branch=main'                # CI gate on every proto change
buf generate
```

Contract rules: never reuse or renumber a field; `reserved` removed numbers and names; add fields
instead of changing types; version packages (`items.v1`) and add `v2` side by side for breaking
changes.

## 2. grpc-go server

```go
func newGRPCServer(log *slog.Logger, items itemsv1.ItemsServer) (*grpc.Server, *health.Server) {
    s := grpc.NewServer(
        grpc.StatsHandler(otelgrpc.NewServerHandler()),   // tracing and metrics (interceptors are deprecated there)
        grpc.ChainUnaryInterceptor(recoverUnary(log), logUnary(log), authUnary),
        grpc.KeepaliveParams(keepalive.ServerParameters{
            MaxConnectionAge:      5 * time.Minute,      // clients reconnect and rebalance across pods
            MaxConnectionAgeGrace: 30 * time.Second,
        }),
    )
    itemsv1.RegisterItemsServer(s, items)
    hs := health.NewServer()
    healthpb.RegisterHealthServer(s, hs)                 // grpc_health_v1
    hs.SetServingStatus("", healthpb.HealthCheckResponse_SERVING)
    return s, hs
}

func recoverUnary(log *slog.Logger) grpc.UnaryServerInterceptor {
    return func(ctx context.Context, req any, info *grpc.UnaryServerInfo, next grpc.UnaryHandler) (resp any, err error) {
        defer func() {
            if v := recover(); v != nil {
                log.ErrorContext(ctx, "panic", slog.String("method", info.FullMethod), slog.Any("panic", v),
                    slog.String("stack", string(debug.Stack())))
                err = status.Error(codes.Internal, "internal error")
            }
        }()
        return next(ctx, req)
    }
}
```

Shutdown: `hs.Shutdown()` (marks NOT_SERVING so balancers drain), wait the drain delay, then

```go
done := make(chan struct{})
go func() { s.GracefulStop(); close(done) }()            // waits for in-flight RPCs, including streams
select {
case <-done:
case <-time.After(cfg.ShutdownTimeout):
    s.Stop()                                             // force-close long streams
}
```

Reflection (`reflection.Register(s)`) helps grpcurl but exposes the schema: internal listeners only.

## 3. Errors and deadlines

```go
func toStatus(err error) error {
    var ve *ValidationError
    switch {
    case err == nil:
        return nil
    case errors.Is(err, ErrNotFound):
        return status.Error(codes.NotFound, "not found")
    case errors.As(err, &ve):
        return status.Error(codes.InvalidArgument, ve.Error())
    case errors.Is(err, ErrConflict):
        return status.Error(codes.AlreadyExists, "already exists")
    case errors.Is(err, context.DeadlineExceeded), errors.Is(err, context.Canceled):
        return status.FromContextError(err).Err()
    default:
        return status.Error(codes.Internal, "internal error")   // log err with the request ID first
    }
}
```

Clients inspect with `status.Code(err)` or `status.Convert(err)`. Deadlines: set one at the edge
(`ctx, cancel := context.WithTimeout(ctx, 800*time.Millisecond)`), pass ctx everywhere; grpc-go sends
it as `grpc-timeout` and the server's handler ctx carries the remaining budget. Retries belong in the
service config, not in hand loops:

```go
grpc.WithDefaultServiceConfig(`{"methodConfig":[{"name":[{"service":"items.v1.Items"}],
  "retryPolicy":{"maxAttempts":3,"initialBackoff":"0.1s","maxBackoff":"1s",
  "backoffMultiplier":2,"retryableStatusCodes":["UNAVAILABLE"]}}]}`)
```

Only retry methods that are idempotent; `UNAVAILABLE` is the safe default code.

## 4. connect-go

v1 (`connectrpc.com/connect`), still the most common in existing code:

```go
path, handler := itemsv1connect.NewItemsServiceHandler(svc, connect.WithInterceptors(authInterceptor))
mux.Handle(path, handler)

func (s *ItemsService) GetItem(ctx context.Context, req *connect.Request[itemsv1.GetItemRequest]) (*connect.Response[itemsv1.GetItemResponse], error) {
    it, err := s.store.Get(ctx, req.Msg.GetId())
    if errors.Is(err, ErrNotFound) {
        return nil, connect.NewError(connect.CodeNotFound, err)   // v1: (code, error)
    }
    if err != nil { return nil, connect.NewError(connect.CodeInternal, errors.New("internal error")) }
    return connect.NewResponse(&itemsv1.GetItemResponse{Item: toProto(it)}), nil
}

client := itemsv1connect.NewItemsServiceClient(httpClient, "https://items.internal", connect.WithGRPC())
```

v2 (`connectrpc.com/connect/v2`, stable v2.0.x released October 2026) per its getting-started guide:
handlers use plain message signatures (`GetItem(ctx, *itemsv1.GetItemRequest) (*itemsv1.GetItemResponse, error)`);
`server := connect.NewServer(interceptors...)`, `itemsv1connect.RegisterItemsServiceHandler(server, svc)`,
`connecthttp.Mount(mux, server)`; clients `itemsv1connect.NewItemsServiceClient(connect.NewClient(
connecthttp.NewTransport(httpClient, baseURL, connecthttp.WithGRPC())))`; errors
`connect.NewError(code, "message").WithCause(err)` or `connect.Errorf(code, format, args...)` (the cause
is never serialized), inspected with `connect.CodeOf(err)` and `errors.As(err, &connectErr)`. Migrating
from v1 means a new module path, regenerated code, new handler signatures and error constructors:
migrate one service at a time and read the v2 upgrade notes first.

Serving: Connect over HTTP/1.1 works out of the box; for gRPC clients without TLS enable cleartext
HTTP/2 on the `http.Server` with `Protocols.SetUnencryptedHTTP2(true)` (Go 1.24+). The Connect protocol
carries deadlines in `Connect-Timeout-Ms` and maps codes to HTTP statuses (not_found 404,
invalid_argument 400, unauthenticated 401, permission_denied 403, resource_exhausted 429,
unavailable 503, deadline_exceeded 504, canceled 499, internal and unknown 500).

## 5. Testing

grpc-go: real server on `bufconn` with fakes behind the service interface, interceptors tested as
plain functions (harness in `go-testing-fuzzing`). connect-go: the handler is an `http.Handler`, so
`httptest.NewServer(mux)` plus a generated client pointed at `srv.URL` exercises routing,
interceptors and serialization in-process.
