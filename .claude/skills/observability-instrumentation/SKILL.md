---
name: observability-instrumentation
description: "Instrumenting code so production behaviour is explainable: structured logging with correlation IDs and redaction, OpenTelemetry traces, metrics and context propagation (zero-code and manual, semantic conventions, sampling), RED/USE metric design with histogram and cardinality budgets, SLOs with multiwindow burn-rate alerts, local verification. Load when adding logging, tracing, metrics or alerts, or when debugging needs better telemetry."
when_to_use: "Adding or reviewing log statements, logger config, OpenTelemetry SDK/agent setup, spans, metrics, dashboards, SLOs or alert rules; OTEL_* environment variables; traces missing spans or broken across a queue or thread pool; a TSDB cardinality explosion; alerts that page on CPU instead of user impact; a bug that cannot be explained from existing telemetry."
---

# Observability instrumentation

Goal: any production question ("why was this checkout slow?", "who is affected?") answerable from
telemetry without a new deploy. Performance measurement method lives in `performance-optimization`;
using telemetry to localize a bug lives in `debugging-method`; this skill is about emitting it.
APIs below were checked against OpenTelemetry Python SDK 1.45 / instrumentation 0.66b1 (October 2026).

Deep material:
[logging setup per language](references/logging-setup.md) |
[collector, tail sampling, local stack, SLO rules](references/collector-and-alerts.md)

## 1. Signal choice

| Question | Signal | Why |
|---|---|---|
| What happened in this request/job, with full context? | structured log, one wide event per unit of work | arbitrary fields, exact values |
| How often, how slow, how many errors, trending? | metrics (counters, histograms, gauges) | cheap aggregates, alerting, long retention |
| Where did the time go across services and hops? | traces (spans) | causality and latency breakdown |
| Which code burns CPU or allocates? | continuous profiles (pprof, Pyroscope, async-profiler) | line-level hot spots |
| Is the system meeting its promise? | SLI metrics + burn-rate alerts | user-visible impact |

Default debugging unit: one wide structured event per request or job, 20-50 fields, emitted once at the
end: route, status, duration, caller identity class, feature flags, cache hits, retries, row counts,
error type, trace_id. One rich event beats twenty "entering function" lines and joins to traces by
`trace_id`.

## 2. Structured logging rules

| Key | Content |
|---|---|
| `timestamp` | RFC 3339 UTC with milliseconds or better |
| `level` | `ERROR` / `WARN` / `INFO` / `DEBUG` |
| `message` (or `event`) | stable, greppable event name: `order.placed`, not a sentence with values inside |
| `service.name`, `service.version`, `deployment.environment.name` | from resource config, same as traces |
| `trace_id`, `span_id` | from the active span (32 and 16 lowercase hex) |
| `request_id` | inbound `X-Request-Id` or generated; echoed in the response |
| `error.type`, `error.message`, `error.stack` | on failures; `error.type` is a class or code, low cardinality |
| `duration_ms` | on every boundary event |

| Level | Meaning | Production |
|---|---|---|
| ERROR | needs a human: data loss, failed request the system could not handle | always on, each one actionable |
| WARN | degraded but handled: retry succeeded, fallback used, approaching a limit | on; review weekly |
| INFO | business events and boundaries: request finished, job done, config loaded | on, sampled if volume demands |
| DEBUG | developer detail | off; enable per module or per request via flag |

Rules:
- JSON in production, human format locally (same logger, renderer switched by env).
- Log at boundaries (inbound request, outbound call, job start/end) with durations, not in loops.
- Log once where an error is handled, with context; do not log-and-rethrow at every layer.
- Redaction: allowlist what may be logged (headers: `user-agent`, `content-type`, `content-length`),
  and add a redaction processor for known secret keys (`password`, `token`, `authorization`, `cookie`,
  `api_key`, `card_number`) as a backstop. Never log full request bodies, URLs with query strings
  containing tokens, or emails/phones unless policy allows and they are hashed.
- Lazy formatting: pass fields, not pre-built strings (`log.info("order.placed", order_id=oid)`;
  stdlib `logger.debug("x=%s", x)`), and guard expensive values (`if logger.isEnabledFor(DEBUG)`).

## 3. Per-language setup (full configs in [logging setup](references/logging-setup.md))

| Language | Library | Essentials |
|---|---|---|
| Python | structlog | `merge_contextvars`, `add_log_level`, `TimeStamper(fmt="iso", utc=True)`, trace-id processor, redaction processor, `JSONRenderer()`; `bind_contextvars(request_id=...)` per request |
| Python (stdlib) | `logging` + python-json-logger | `pythonjsonlogger.json.JsonFormatter` (3.x+ import path), context via `extra={...}` and a `logging.Filter` adding trace ids |
| Node | pino | `pino({ redact: { paths: [...], censor: "[REDACTED]" }, timestamp: pino.stdTimeFunctions.isoTime })`, `logger.child({ request_id })`; trace ids via `@opentelemetry/instrumentation-pino` |
| Go | `log/slog` | `slog.New(slog.NewJSONHandler(os.Stdout, opts))`, always `InfoContext(ctx, ...)`; a wrapping handler adds trace ids from `trace.SpanContextFromContext(ctx)`; `ReplaceAttr` for redaction |
| Rust | `tracing` + `tracing-subscriber` (features `json`, `env-filter`) | `fmt().json().with_current_span(true).flatten_event(true)`; `#[instrument(skip(password))]`; OTel via `tracing-opentelemetry` |
| JVM | SLF4J + Logback/Log4j2 JSON | Spring Boot: `logging.structured.format.console=ecs` (also `logstash`, `gelf`); MDC for request ids; the OTel Java agent injects `trace_id`/`span_id` into MDC |

## 4. OpenTelemetry setup

Configure by environment so the same build runs everywhere:

| Variable | Example | Notes |
|---|---|---|
| `OTEL_SERVICE_NAME` | `checkout-api` | required in practice; otherwise `unknown_service` |
| `OTEL_RESOURCE_ATTRIBUTES` | `service.version=1.4.0,deployment.environment.name=prod` | comma-separated `k=v` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4318` | base URL; HTTP exporters append `/v1/traces` etc. gRPC uses port 4317 |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` or `grpc` | default differs by SDK; set it |
| `OTEL_TRACES_SAMPLER` / `_ARG` | `parentbased_traceidratio` / `0.1` | keep 10% of new traces, follow parent decisions |
| `OTEL_SEMCONV_STABILITY_OPT_IN` | `http,database` | Python instrumentation 0.66b1 still emits old names by default (`http.server.duration` in ms); opt in for stable names |
| `OTEL_METRICS_EXEMPLAR_FILTER` | `trace_based` | exemplars only from sampled spans |
| `OTEL_SDK_DISABLED` | `true` | tests and local runs without a collector |

Zero-code first, then manual spans for business operations:

| Runtime | Zero-code |
|---|---|
| Python | `uv add opentelemetry-distro opentelemetry-exporter-otlp`, then `uv run opentelemetry-bootstrap -a requirements \| uv add --requirement -` (the docs advise this over `-a install` under uv; re-run after dependency changes), start with `opentelemetry-instrument uvicorn app:app` |
| Node | `npm install @opentelemetry/auto-instrumentations-node`, run `node --require @opentelemetry/auto-instrumentations-node/register app.js` (or via `NODE_OPTIONS`) |
| Java | `java -javaagent:opentelemetry-javaagent.jar -jar app.jar` |
| Go | no agent by default: wrap handlers/clients (`otelhttp.NewHandler`, `otelhttp.NewTransport`, `otelgrpc`, `otelsql`) |
| .NET | `OpenTelemetry.AutoInstrumentation` |

Pre-fork servers (gunicorn workers): zero-code metrics can break with several workers; initialize the
SDK after fork (gunicorn `post_fork` hook) or programmatically in the app.

Frameworks with native OpenTelemetry: recent FastAPI releases (0.148 checked) record HTTP spans, the
stable `http.server.request.duration` metric and error logs through the global providers, plus
`fastapi.dependencies`/`fastapi.endpoint` spans; configure with `FastAPI(telemetry={...})` (`tracing`,
`metrics`, `logs`, `exclude`). FastAPI switches its native telemetry off when it detects the contrib
ASGI middleware (`opentelemetry-instrumentation-fastapi`), so pick one; on older FastAPI use the
contrib instrumentor with `OTEL_SEMCONV_STABILITY_OPT_IN=http`.

## 5. Manual tracing rules

```python
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

tracer = trace.get_tracer("checkout_api")

async def charge(order: Order) -> Receipt:
    with tracer.start_as_current_span("checkout.charge", kind=SpanKind.CLIENT) as span:
        span.set_attribute("payment.provider", provider.name)
        span.set_attribute("checkout.amount_minor", order.total_minor)
        try:
            receipt = await provider.charge(order)
        except CardDeclined as e:                       # expected outcome: record, mark, return
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, "card declined"))
            annotate(**{"error.type": "card_declined"})  # wide event (section 11)
            return Receipt.declined(order.id)            # handler maps it to HTTP 402
        span.add_event("payment.authorized", {"auth.code_present": bool(receipt.auth_code)})
        return receipt
```
- One span per meaningful operation (outbound call, DB transaction, queue publish, business step), not
  per function. Span names are low-cardinality: `checkout.charge`, `GET /orders/{id}`; never include ids.
- `start_as_current_span` records escaping exceptions and sets ERROR by default; call `record_exception`
  yourself only when you catch.
- Status: ERROR for failures; leave UNSET on success. HTTP server spans: 5xx is an error, 4xx is not.
- Attributes: semantic-convention names where one exists, else a namespaced custom key (`checkout.*`).
  High-cardinality values (order id) are fine on spans, never on metrics.
- Events for milestones inside a span; links for fan-in (a batch consumer span links to each message's
  producer context) instead of picking one arbitrary parent.

| Area | Attributes (stable unless noted) |
|---|---|
| HTTP server | `http.request.method`, `http.route` (template), `http.response.status_code`, `url.scheme`, `url.path`, `error.type` |
| HTTP client | `http.request.method`, `server.address`, `server.port`, `url.full` (strip credentials and secret query params), `http.response.status_code` |
| Database | `db.system.name`, `db.namespace`, `db.collection.name`, `db.operation.name`, `db.query.text` (sanitized: literals replaced by `?`), `db.query.summary`, `db.response.status_code` |
| Messaging (development status) | `messaging.system`, `messaging.destination.name`, `messaging.operation.type`, `messaging.message.id` |
| Errors | `error.type` (exception class or code), plus the `exception` event from `record_exception` |

Context propagation (W3C `traceparent`/`tracestate`):

| Boundary | Do |
|---|---|
| HTTP | instrumented clients and servers inject/extract automatically |
| Queues (Kafka, SQS, RabbitMQ) | producer: `inject(headers)` into message headers; consumer: `ctx = extract(headers)`, then `start_as_current_span("orders process", context=ctx, kind=SpanKind.CONSUMER)`; batches use links |
| Python threads | `ThreadPoolExecutor` does not copy contextvars: `ctx = contextvars.copy_context(); pool.submit(ctx.run, fn)`, or `opentelemetry-instrumentation-threading` |
| Python asyncio | `create_task` copies context; tasks that outlive the request keep a parent span that already ended: start a new trace with a link instead |
| Go | pass `ctx` into every goroutine and call; never `context.Background()` mid-request |
| Rust | `tokio::spawn(fut.instrument(tracing::Span::current()))` (`tracing::Instrument`) |
| Java | `Context.taskWrapping(executor)` or `Context.current().wrap(runnable)`; the agent covers common executors |
| Node | AsyncLocalStorage-based context manager covers promises; callback-based emitters may need `context.bind` |

## 6. Metric design

| Method | Per | Instruments |
|---|---|---|
| RED | endpoint / RPC / consumer | Rate: request counter; Errors: same counter by `error.type` or status class; Duration: histogram |
| USE | resource (pool, queue, CPU, disk) | Utilization (busy fraction), Saturation (queue length, wait time), Errors |

- Histograms, never averages: averages hide the tail and cannot be aggregated into percentiles.
- Buckets: put boundaries at the SLO threshold and around it (for an 800 ms SLO: `0.05, 0.1, 0.25, 0.5,
  0.8, 1, 2.5` s); a quantile between two distant buckets is interpolated, so an SLO bound that is not a
  bucket boundary cannot be measured exactly. Alternative: exponential (OTel base2) histograms to
  Prometheus native histograms (stable since Prometheus 3.8; per-job `scrape_native_histograms: true`).
- Naming: OTel style `http.server.request.duration` with unit `s`; Prometheus exposition becomes
  `http_server_request_duration_seconds_{bucket,sum,count}`. Counters are monotonic and end in `_total`
  in Prometheus; base units only (`_seconds`, `_bytes`), never `_ms`.
- Gauges for current state (queue depth, pool in use); up-down counters for things you increment and
  decrement.

Cardinality budget: series per metric = (buckets + 2 for histograms) x product of distinct values of
every label. Example `http.server.request.duration`, 7 boundaries (8 buckets + sum + count = 10):
10 x 60 route-method pairs x 6 status codes x 12 instances = 43,200 series. Adding `user_id` (100k users)
multiplies that by 100,000. Budget per service (e.g. 10k-50k series) and enforce it:
- No `user_id`, `request_id`, `order_id`, email, raw path or full URL as labels; use `http.route`
  templates and status classes.
- Drop or aggregate at the source with SDK Views (`View(instrument_name=..., attribute_keys={...})`) or
  in the collector (`transform`/`filter` processors).

## 7. SLOs and burn-rate alerts

- SLI = good events / valid events over the window. Valid excludes traffic that says nothing about
  users (health checks, synthetic probes); client 4xx are either excluded or counted as good, never as
  bad. Good = not 5xx AND faster than the latency target.
- Error budget = (1 - SLO) x window. 99.9% over 30 d = 0.1% x 43,200 min = 43.2 min of full outage,
  or 1 bad request per 1,000.
- Burn rate = observed bad ratio / (1 - SLO). Burn rate 1 consumes exactly the budget in the window.

Multiwindow, multi-burn-rate alerts (Google SRE workbook), for a 30-day SLO:

| Severity | Burn rate | Long window | Short window | Budget spent when it fires | Bad-ratio threshold at 99.9% |
|---|---|---|---|---|---|
| page | 14.4 | 1 h | 5 min | 2% | 1.44% |
| page | 6 | 6 h | 30 min | 5% | 0.6% |
| ticket | 1 | 3 d | 6 h | 10% | 0.1% |

Both windows must exceed the threshold: the long window proves significance, the short window makes
the alert resolve quickly after recovery. Alert on symptoms users feel (SLI burn), not causes (CPU,
memory, pod restarts); cause metrics belong on dashboards. Every alert links a runbook and a dashboard.
Low-traffic services: add a minimum request-rate condition or use longer windows, or single requests
page someone. Rule files: [SLO rules](references/collector-and-alerts.md).

## 8. Sampling and cost

| Mechanism | Where | Keeps | Cost |
|---|---|---|---|
| Head sampling (`parentbased_traceidratio`) | SDK, at trace start | a fixed fraction, decided before the outcome is known | cheapest; loses rare errors |
| Tail sampling (`tail_sampling` processor) | collector, after `decision_wait` | all errors, all slow traces, a percentage of the rest | memory for buffered traces; all spans of a trace must reach the same collector (`loadbalancing` exporter tier in front) |
| Log volume budget | logger and collector | INFO events sampled per route, DEBUG dropped, duplicate errors rate-limited | |
| Drop rules | collector `filter` processor | removes health checks, noisy spans, unused metrics | |
| Exemplars | SDK -> TSDB | trace ids attached to histogram buckets, so a slow bucket links to an example trace | Prometheus needs `--enable-feature=exemplar-storage` |

Rule of thumb: head-sample at 100% in low-volume services and let the collector tail-sample; at high
volume, head-sample (e.g. 10%) and tail-sample errors and slow traces from what remains.

## 9. Local verification

```bash
docker run --rm -p 3000:3000 -p 4317:4317 -p 4318:4318 grafana/otel-lgtm:0.37.0   # Grafana admin/admin
OTEL_SERVICE_NAME=checkout-api OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf OTEL_SEMCONV_STABILITY_OPT_IN=http,database \
  uv run uvicorn checkout_api.main:app --port 8000
```
Exercise the endpoint, then check in Grafana Explore: Tempo (TraceQL
`{ resource.service.name = "checkout-api" && name = "checkout.charge" }`), Prometheus
(`http_server_request_duration_seconds_bucket`), and the JSON log lines on stdout. otel-lgtm bundles
the collector, Prometheus, Tempo, Loki and Pyroscope; Jaeger (`jaegertracing/jaeger`, UI on 16686) is a
lighter trace-only option.

Tests assert telemetry like any other output:
- Spans: one session-wide `TracerProvider` with `InMemorySpanExporter` + `SimpleSpanProcessor`;
  `exporter.clear()` per test (a provider can only be set once per process).
- Metrics: `InMemoryMetricReader().get_metrics_data()`.
- Logs: structlog `structlog.testing.capture_logs()`; stdlib `caplog`; pino with a destination stream
  that collects lines; Go `slog.NewJSONHandler(&buf, nil)`.

## 10. Pitfalls

| Pitfall | Consequence | Fix |
|---|---|---|
| High-cardinality labels (`user_id`, raw path) | TSDB memory blow-up, slow queries, bills | route templates, View attribute filters, budget per metric |
| Logging inside hot loops | CPU and log bill dominated by logs | aggregate into the wide event, count instead of log |
| Lost context across executors, goroutines, spawned tasks | orphan spans, broken traces | section 5 propagation table |
| Two instrumentations of the same call (framework-native + contrib, or auto + manual) | duplicate nested spans, double-counted metrics | one HTTP instrumentation; manual spans only for business steps; `exclude_spans=["receive", "send"]` for contrib ASGI noise |
| Clock skew between hosts | child spans appear before parents | trust durations within a host; NTP everywhere |
| PII in span attributes, URLs, `db.query.text` with literals | data leak into a wider-access system | sanitize, allowlist headers, scrub in the collector (`redaction`/`transform` processor) |
| Alerting on causes (CPU > 80%) | noisy pages without user impact | SLO burn-rate alerts; causes on dashboards |
| Old vs stable semconv names mixed | dashboards empty after upgrades | set `OTEL_SEMCONV_STABILITY_OPT_IN`, migrate queries (use `/dup` during migration) |
| SDK never flushed in short-lived jobs | last spans lost | `provider.shutdown()` / `force_flush()` before exit |

## 11. Worked example: checkout endpoint

Service: FastAPI `POST /checkout/{cart_id}`, Postgres via SQLAlchemy, external payment API.
SLO: 99.5% of valid checkout requests over 30 days complete without a 5xx in under 800 ms.

1. Telemetry bootstrap (`checkout_api/telemetry.py`), called before the app is created:
```python
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SLO_BUCKETS = (0.05, 0.1, 0.25, 0.5, 0.8, 1.0, 2.5)          # 0.8 s is a boundary

def setup_telemetry() -> None:
    resource = Resource.create()                             # OTEL_SERVICE_NAME, OTEL_RESOURCE_ATTRIBUTES
    tp = TracerProvider(resource=resource)                   # sampler from OTEL_TRACES_SAMPLER
    tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tp)
    metrics.set_meter_provider(MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())],
        views=[View(instrument_name="http.server.request.duration",
                    aggregation=ExplicitBucketHistogramAggregation(SLO_BUCKETS))],
    ))
```
2. Auto-instrumentation: FastAPI native telemetry picks up the global providers;
   `app = FastAPI(telemetry={"exclude": lambda scope: scope.get("path") == "/healthz"})` keeps health
   checks out. DB: `SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)`. (Older FastAPI:
   `FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz", exclude_spans=["receive", "send"])`.)
3. Manual spans `checkout.price` (attributes `checkout.items`, `checkout.currency`) and
   `checkout.charge` (section 5 code, `payment.provider`, `checkout.amount_minor`); a decline maps to
   HTTP 402, so the server span stays UNSET while `checkout.charge` is ERROR.
4. Wide event: middleware stores a mutable dict in a `ContextVar`, handlers call
   `annotate(cart_items=3, order_total_minor=4599)`, middleware logs it once in `finally` (full code in
   [logging setup](references/logging-setup.md)). A plain `bind_contextvars` inside the handler would
   not reach the middleware: `call_next` runs the endpoint in a child task with a copied context.
5. Burn-rate thresholds for 99.5%: budget 0.5%; page at 14.4 x 0.005 = 7.2% bad over 1 h and 5 min,
   page at 6 x 0.005 = 3% over 6 h and 30 min, ticket at 0.5% over 3 d and 6 h. Recording and alerting
   rules in [SLO rules](references/collector-and-alerts.md); check them with `promtool check rules` and
   the `promtool test rules` unit test there (20% bad traffic must fire the fast-burn page).

Verification, step 1: in-process with `TestClient`, `InMemorySpanExporter` and `InMemoryMetricReader`,
payment provider stubbed to decline, FastAPI 0.148.0, SDK 1.45.1 (actual output):
```
metrics: ['http.server.active_requests', 'http.server.request.duration']
bounds (0.05, 0.1, 0.25, 0.5, 0.8, 1.0, 2.5) unit s
attrs {'url.scheme': 'http', 'http.request.method': 'POST', 'network.protocol.version': '1.1',
       'http.route': '/checkout/{cart_id}', 'http.response.status_code': 402}
spans: [('fastapi.dependencies', 'UNSET'), ('checkout.price', 'UNSET'), ('checkout.charge', 'ERROR'),
        ('fastapi.endpoint', 'UNSET'), ('POST /checkout/{cart_id}', 'UNSET')]
wide event: {"request_id": "22e0...", "http.request.method": "POST", "cart_items": 3,
             "order_total_minor": 4599, "error.type": "card_declined",
             "http.route": "/checkout/{cart_id}", "http.response.status_code": 402, "duration_ms": 0.9}
```
The SDK View applied the SLO buckets to the framework's histogram. The 402 leaves the server span
UNSET while `checkout.charge` is ERROR, as section 5 requires. Cross-check with the contrib
instrumentor instead: without `OTEL_SEMCONV_STABILITY_OPT_IN=http` it emitted `http.server.duration`
in milliseconds, which would silently break every query on the 0.8 s bucket.

Step 2, end to end in otel-lgtm (section 9 commands): send traffic with a fault flag that delays 20%
of payment calls to 1.2 s, e.g. `hey -z 5m -c 20 -m POST http://localhost:8000/checkout/c1`. Check:
- Tempo: `{ resource.service.name = "checkout-api" && name = "checkout.charge" && duration > 1s }`
  returns the delayed spans with `payment.provider` set, under the `fastapi.endpoint` span of the
  request trace and next to its SQLAlchemy spans.
- Prometheus: the fast-burn expression from the rules file evaluates to about 0.20 (20% of requests
  exceed 0.8 s), above the 0.072 threshold on both windows, so the page fires; with the flag off it
  drops below 0.072 within the 5-minute window and the alert resolves.
- Exemplars on the 1 s bucket open individual slow traces.
- stdout: `jq -R 'fromjson? | select(.event == "http.request" and .duration_ms > 800)'` (skips non-JSON
  server lines) lists the matching wide events,
  each carrying the `trace_id` of the trace above.

Related: `ci-pipelines`, `container-images`, `resilience-patterns`, `fastapi-pydantic-services`,
`go-http-services`, `rust-axum-services`, `node-runtime-patterns`, `python-asyncio`,
`performance-optimization`, `debugging-method`, `security-review`, hub `coding-general`.
