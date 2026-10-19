# Logging setup per language

All configurations emit one JSON object per line on stdout with `timestamp`, `level`, a stable event
name, `trace_id`/`span_id` when a span is active, and redaction of known secret keys. The Python
snippets were run against structlog 26.1, python-json-logger 4.2, FastAPI 0.148 and the OpenTelemetry
SDK 1.45 (October 2026). Go, Rust and JVM snippets use long-stable APIs; compile them in your project
before relying on them.

## 1. Python: structlog with wide events

```python
# checkout_api/logging_setup.py
import logging
import os
import sys
import time
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from opentelemetry import trace

SENSITIVE = {"password", "token", "access_token", "authorization", "cookie", "set-cookie",
             "api_key", "secret", "card_number", "cvv"}


def add_trace_ids(_logger: Any, _name: str, event: dict) -> dict:
    ctx = trace.get_current_span().get_span_context()
    if ctx.is_valid:
        event["trace_id"] = format(ctx.trace_id, "032x")
        event["span_id"] = format(ctx.span_id, "016x")
    return event


def redact(_logger: Any, _name: str, event: dict) -> dict:
    for key in list(event):
        if key.lower() in SENSITIVE:
            event[key] = "[REDACTED]"
    return event


def setup_logging() -> None:
    json_logs = os.getenv("LOG_FORMAT", "json") == "json"
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            add_trace_ids,
            redact,
            structlog.processors.dict_tracebacks if json_logs else structlog.dev.set_exc_info,
            structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


# wide event: one log line per request, fields added from anywhere in the request
_event: ContextVar[dict] = ContextVar("wide_event")
log = structlog.get_logger("checkout_api")


def annotate(**fields: Any) -> None:
    event = _event.get(None)
    if event is not None:
        event.update(fields)


def install_wide_event(app: FastAPI) -> None:
    @app.middleware("http")
    async def wide_event(request: Request, call_next):
        event: dict[str, Any] = {
            "request_id": request.headers.get("x-request-id") or uuid4().hex,
            "http.request.method": request.method,
        }
        _event.set(event)  # the dict is shared with the child task that runs the endpoint
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["x-request-id"] = event["request_id"]
            return response
        finally:
            route = request.scope.get("route")
            event["http.route"] = getattr(route, "path", None)
            event["http.response.status_code"] = status
            event["duration_ms"] = round((time.perf_counter() - start) * 1000, 1)
            (log.error if status >= 500 else log.info)("http.request", **event)
```

Output of one request whose handler called `annotate(cart_items=3, password="hunter2")` inside a span:
```json
{"request_id": "40b868be7b4b4ee09c78d75158d091a4", "http.request.method": "POST", "cart_items": 3,
 "password": "[REDACTED]", "http.route": "/checkout/{cart_id}", "http.response.status_code": 200,
 "duration_ms": 0.8, "event": "http.request", "level": "info",
 "timestamp": "2026-10-19T14:22:38.417410Z", "trace_id": "1ebf659673fd8467b0a6011bc3f5d039",
 "span_id": "7e55848a0d7d1d63"}
```
Notes:
- Why a mutable dict in a `ContextVar`: `call_next` runs the endpoint in a child task with a copy of the
  context, so values the handler binds with `bind_contextvars` never reach the middleware, but
  mutations of a shared dict do.
- The middleware's `trace_id` is the request's server span when FastAPI native telemetry or the contrib
  instrumentor is active.
- Exceptions: `log.exception("payment.failed")` inside `except`; `dict_tracebacks` renders structured
  frames in JSON mode.
- Tests: `with structlog.testing.capture_logs() as logs: ...` returns the event dicts before rendering.
- Third-party stdlib loggers (uvicorn, sqlalchemy): route them through `structlog.stdlib.ProcessorFormatter`
  if they must share the JSON format, or set them to WARNING.

## 2. Python: stdlib logging with JSON

```python
import logging
import sys

from opentelemetry import trace
from pythonjsonlogger.json import JsonFormatter   # python-json-logger >= 3.1 import path


class TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        ctx = trace.get_current_span().get_span_context()
        record.trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else None
        record.span_id = format(ctx.span_id, "016x") if ctx.is_valid else None
        return True


handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter("{levelname}{name}{message}", style="{", timestamp=True,
                                   rename_fields={"levelname": "level"}))
handler.addFilter(TraceIdFilter())
logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)

logging.getLogger("checkout").info("order.placed", extra={"order_id": "o1"})
# {"level": "INFO", "name": "checkout", "message": "order.placed", "order_id": "o1",
#  "trace_id": "fa9d...", "span_id": "988d...", "timestamp": "2026-10-19T14:24:55.044214+00:00"}
```
`extra` keys must not collide with `LogRecord` attributes (`message`, `name`, `args`...), or logging
raises `KeyError`. pytest's `caplog.records` exposes the extra fields as attributes.

## 3. Node: pino

```js
import pino from "pino";

export const logger = pino({
  level: process.env.LOG_LEVEL ?? "info",
  base: { "service.name": "checkout-api" },
  messageKey: "message",
  timestamp: pino.stdTimeFunctions.isoTime,
  formatters: { level: (label) => ({ level: label }) },
  redact: {
    paths: ["req.headers.authorization", "req.headers.cookie", "*.password", "*.token", "card.number"],
    censor: "[REDACTED]",
  },
});

// per request: a child logger carries request-scoped fields
const log = logger.child({ request_id: req.headers["x-request-id"] ?? crypto.randomUUID() });
log.info({ order_id: order.id, duration_ms: elapsed }, "order.placed");
```
- Trace correlation: `@opentelemetry/instrumentation-pino` (part of `auto-instrumentations-node`)
  injects `trace_id`, `span_id`, `trace_flags` into each record.
- Redact paths are resolved at logger creation (fast), `*` matches one level; redact by structure, not
  by scanning strings.
- Tests: pass a destination stream and parse lines:
  ```js
  import { Writable } from "node:stream";
  const lines = [];
  const sink = new Writable({ write(chunk, _enc, cb) { lines.push(JSON.parse(chunk)); cb(); } });
  const testLogger = pino({ redact: ["password"] }, sink);
  testLogger.info({ password: "x" }, "login");   // lines[0].password === "[Redacted]" (default censor)
  ```

## 4. Go: log/slog

```go
package logging

import (
	"context"
	"log/slog"
	"os"
	"strings"

	"go.opentelemetry.io/otel/trace"
)

type traceHandler struct{ slog.Handler }

func (h traceHandler) Handle(ctx context.Context, r slog.Record) error {
	if sc := trace.SpanContextFromContext(ctx); sc.IsValid() {
		r.AddAttrs(
			slog.String("trace_id", sc.TraceID().String()),
			slog.String("span_id", sc.SpanID().String()),
		)
	}
	return h.Handler.Handle(ctx, r)
}

func (h traceHandler) WithAttrs(as []slog.Attr) slog.Handler { return traceHandler{h.Handler.WithAttrs(as)} }
func (h traceHandler) WithGroup(name string) slog.Handler    { return traceHandler{h.Handler.WithGroup(name)} }

var sensitive = map[string]bool{"password": true, "token": true, "authorization": true, "cookie": true, "api_key": true}

func New(level slog.Level) *slog.Logger {
	h := slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: level,
		ReplaceAttr: func(_ []string, a slog.Attr) slog.Attr {
			if sensitive[strings.ToLower(a.Key)] {
				return slog.String(a.Key, "[REDACTED]")
			}
			return a
		},
	})
	return slog.New(traceHandler{h}).With(slog.String("service.name", "checkout-api"))
}
```
Usage: `logger.InfoContext(ctx, "order.placed", slog.String("order_id", id), slog.Int64("duration_ms", ms))`.
Without the `Context` variants the handler never sees the span. Alternative: the
`go.opentelemetry.io/contrib/bridges/otelslog` bridge sends records to the OTel Logs SDK
(`otelslog.NewLogger(name, otelslog.WithLoggerProvider(lp))`) instead of stdout JSON.
Tests: `slog.New(slog.NewJSONHandler(&buf, nil))` and decode `buf` line by line.

## 5. Rust: tracing

```rust
// Cargo.toml: tracing-subscriber = { version = "0.3", features = ["json", "env-filter"] }
use tracing_subscriber::EnvFilter;

pub fn init_logging() {
    tracing_subscriber::fmt()
        .json()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")))
        .with_current_span(true)
        .with_span_list(false)
        .flatten_event(true)
        .with_target(false)
        .init();
}

#[tracing::instrument(skip(card), fields(order_id = %order.id))]
async fn charge(order: &Order, card: &Card) -> Result<Receipt, PayError> {
    tracing::info!(provider = %provider_name, "payment.attempt");
    // ...
}
```
- `skip(...)` keeps secrets and large values out of span fields; `skip_all` plus explicit `fields(...)`
  is the safest default for handlers.
- Exporting spans to OTel: `tracing-opentelemetry` layer with an `opentelemetry-otlp` exporter. The fmt
  JSON output does not include OTel trace ids by itself; add them with a custom formatter or send logs
  through `opentelemetry-appender-tracing`. Check current builder APIs in the crate docs; they change
  between releases.
- Spawned tasks: `tokio::spawn(fut.instrument(tracing::Span::current()))`.

## 6. JVM: SLF4J with Logback or Spring Boot

Spring Boot structured logging:
```properties
logging.structured.format.console=ecs        # or logstash, gelf
logging.level.root=INFO
```
Every MDC entry is added to the JSON object; SLF4J fluent key-values too:
```java
try (var ignored = MDC.putCloseable("request_id", requestId)) {   // removed even on exceptions
    log.atInfo().addKeyValue("order_id", order.id()).addKeyValue("duration_ms", ms).log("order.placed");
}
```
Plain Logback with logstash-logback-encoder:
```xml
<configuration>
  <appender name="JSON" class="ch.qos.logback.core.ConsoleAppender">
    <encoder class="net.logstash.logback.encoder.LogstashEncoder"/>
  </appender>
  <root level="INFO"><appender-ref ref="JSON"/></root>
</configuration>
```
- The OpenTelemetry Java agent injects `trace_id`, `span_id` and `trace_flags` into the MDC, so they
  appear in JSON output without code.
- MDC is thread-local: work handed to executors loses it unless the executor is wrapped (the agent's
  context propagation covers OTel context; copy MDC explicitly with `MDC.getCopyOfContextMap()` and
  `MDC.setContextMap(...)` for your own keys).
- Log4j2: `JsonTemplateLayout` with the `EcsLayout.json` template is the equivalent.
