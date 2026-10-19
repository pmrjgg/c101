# Collector, tail sampling, local stack, SLO rules

Image tags as of October 2026 (`otel/opentelemetry-collector-contrib:0.163.1`, `grafana/otel-lgtm:0.37.0`).
Validate collector files with `otelcol-contrib validate --config=collector.yaml` and rule files with
`promtool check rules` before deploying; component configuration keys change between collector
releases, so check the component README for the version you run.

## 1. Collector with tail sampling

```yaml
# collector.yaml (sampling tier)
receivers:
  otlp:
    protocols:
      grpc: { endpoint: 0.0.0.0:4317 }
      http: { endpoint: 0.0.0.0:4318 }

processors:
  memory_limiter:                       # first: refuse data before the process is OOM-killed
    check_interval: 1s
    limit_percentage: 80
    spike_limit_percentage: 20
  filter/health:                        # drop health-check spans entirely
    error_mode: ignore
    traces:
      span:
        - 'attributes["http.route"] == "/healthz"'
  tail_sampling:
    decision_wait: 10s                  # longer than your slowest normal trace
    num_traces: 50000                   # >= traces/s x decision_wait x 2
    expected_new_traces_per_sec: 2000
    policies:                           # a trace is kept when any policy samples it
      - { name: errors, type: status_code, status_code: { status_codes: [ERROR] } }
      - { name: slow, type: latency, latency: { threshold_ms: 800 } }
      - { name: baseline, type: probabilistic, probabilistic: { sampling_percentage: 10 } }
  batch: {}                             # last

exporters:
  otlphttp/traces: { endpoint: "http://tempo:4318" }
  otlphttp/metrics: { endpoint: "http://prometheus:9090/api/v1/otlp" }
  debug: { verbosity: basic }

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, filter/health, tail_sampling, batch]
      exporters: [otlphttp/traces]
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlphttp/metrics]
```

The `otlphttp/metrics` endpoint assumes Prometheus 3.x started with `--web.enable-otlp-receiver`
(the exporter appends `/v1/metrics`).

Sizing `num_traces`: at 2,000 new traces/s with a 10 s decision wait, about 20,000 traces are in flight;
keep headroom (x2). Too small evicts traces before their decision and loses spans.

All spans of a trace must reach the same sampling collector. With more than one replica, put a
stateless routing tier in front:
```yaml
# collector-router.yaml (routing tier)
exporters:
  loadbalancing:
    routing_key: traceID
    protocol:
      otlp:
        tls: { insecure: true }
    resolver:
      dns: { hostname: otel-sampler-headless.observability.svc.cluster.local, port: 4317 }
service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter]
      exporters: [loadbalancing]
```
Metrics computed from spans (span metrics, service graphs) must be generated before tail sampling,
in the routing tier, or they undercount everything that was dropped.

Scrubbing in the collector (backstop for SDK mistakes): the `redaction` processor (allowlist of
attribute keys, blocked value patterns) or `transform` with OTTL, e.g.
`replace_pattern(attributes["url.full"], "token=[^&]+", "token=REDACTED")`.

## 2. Local stack

```yaml
# compose.observability.yaml
services:
  lgtm:
    image: grafana/otel-lgtm:0.37.0     # collector + Prometheus + Tempo + Loki + Pyroscope + Grafana
    ports: ["3000:3000", "4317:4317", "4318:4318"]
  api:
    build: { context: ./apps/api }
    environment:
      OTEL_SERVICE_NAME: checkout-api
      OTEL_RESOURCE_ATTRIBUTES: deployment.environment.name=local,service.version=dev
      OTEL_EXPORTER_OTLP_ENDPOINT: http://lgtm:4318
      OTEL_EXPORTER_OTLP_PROTOCOL: http/protobuf
      OTEL_TRACES_SAMPLER: parentbased_always_on
      OTEL_METRIC_EXPORT_INTERVAL: "5000"          # ms; faster feedback locally
      PAYMENT_FAULT_DELAY_MS: "1200"                # fault flag used by the worked example
      PAYMENT_FAULT_RATE: "0.2"
    ports: ["8000:8000"]
    depends_on: [lgtm]
```
`docker compose -f compose.observability.yaml up --build`, then Grafana at http://localhost:3000
(admin/admin). Generate load: `hey -z 5m -c 20 -m POST http://localhost:8000/checkout/c1` (or `oha`,
`k6`).

Checks in Grafana Explore:
- Tempo, TraceQL: `{ resource.service.name = "checkout-api" && name = "checkout.charge" && duration > 1s }`.
- Prometheus: `sum by (http_response_status_code) (rate(http_server_request_duration_seconds_count{job="checkout-api"}[1m]))`.
  Metric and label names depend on the backend's OTLP name translation; confirm them with the
  metrics browser before writing rules.
- Exemplars: enable the exemplar toggle on a histogram query; Prometheus stores them only with
  `--enable-feature=exemplar-storage`.

## 3. SLO recording and alerting rules (99.5%, 800 ms, 30 days)

```yaml
# slo-rules.yaml
groups:
  - name: checkout-slo-recording
    interval: 30s
    rules:
      - record: checkout:sli_bad_ratio:rate5m
        expr: |
          1 - (
            sum(rate(http_server_request_duration_seconds_bucket{job="checkout-api",http_route="/checkout/{cart_id}",le="0.8",http_response_status_code!~"5.."}[5m]))
            /
            sum(rate(http_server_request_duration_seconds_count{job="checkout-api",http_route="/checkout/{cart_id}"}[5m]))
          )
      # identical rules with [30m], [1h], [6h] and [3d] windows:
      - record: checkout:sli_bad_ratio:rate30m
        expr: |
          1 - (
            sum(rate(http_server_request_duration_seconds_bucket{job="checkout-api",http_route="/checkout/{cart_id}",le="0.8",http_response_status_code!~"5.."}[30m]))
            /
            sum(rate(http_server_request_duration_seconds_count{job="checkout-api",http_route="/checkout/{cart_id}"}[30m]))
          )
      - record: checkout:sli_bad_ratio:rate1h
        expr: |
          1 - (
            sum(rate(http_server_request_duration_seconds_bucket{job="checkout-api",http_route="/checkout/{cart_id}",le="0.8",http_response_status_code!~"5.."}[1h]))
            /
            sum(rate(http_server_request_duration_seconds_count{job="checkout-api",http_route="/checkout/{cart_id}"}[1h]))
          )
      - record: checkout:sli_bad_ratio:rate6h
        expr: |
          1 - (
            sum(rate(http_server_request_duration_seconds_bucket{job="checkout-api",http_route="/checkout/{cart_id}",le="0.8",http_response_status_code!~"5.."}[6h]))
            /
            sum(rate(http_server_request_duration_seconds_count{job="checkout-api",http_route="/checkout/{cart_id}"}[6h]))
          )
      - record: checkout:sli_bad_ratio:rate3d
        expr: |
          1 - (
            sum(rate(http_server_request_duration_seconds_bucket{job="checkout-api",http_route="/checkout/{cart_id}",le="0.8",http_response_status_code!~"5.."}[3d]))
            /
            sum(rate(http_server_request_duration_seconds_count{job="checkout-api",http_route="/checkout/{cart_id}"}[3d]))
          )

  - name: checkout-slo-alerts
    rules:
      - alert: CheckoutSLOFastBurn          # 2% of the 30-day budget in 1 hour
        expr: |
          checkout:sli_bad_ratio:rate1h > (14.4 * 0.005)
          and checkout:sli_bad_ratio:rate5m > (14.4 * 0.005)
        labels: { severity: page }
        annotations:
          summary: "Checkout SLO fast burn (>14.4x)"
          runbook_url: "https://runbooks.example.com/checkout-slo"
      - alert: CheckoutSLOSlowBurn          # 5% of the budget in 6 hours
        expr: |
          checkout:sli_bad_ratio:rate6h > (6 * 0.005)
          and checkout:sli_bad_ratio:rate30m > (6 * 0.005)
        labels: { severity: page }
        annotations:
          summary: "Checkout SLO slow burn (>6x)"
          runbook_url: "https://runbooks.example.com/checkout-slo"
      - alert: CheckoutSLOBudgetDrain       # 10% of the budget in 3 days
        expr: |
          checkout:sli_bad_ratio:rate3d > 0.005
          and checkout:sli_bad_ratio:rate6h > 0.005
        labels: { severity: ticket }
        annotations:
          summary: "Checkout SLO budget draining (>1x)"
          runbook_url: "https://runbooks.example.com/checkout-slo"
```
Notes:
- `le="0.8"` must be an actual bucket boundary (section 6 of the skill). Check the exact `le` string the
  backend stores (`0.8`, and `1` vs `1.0` for whole numbers) in the metrics browser.
- No traffic gives `NaN`, which never exceeds a threshold, so idle periods are silent. For low traffic add
  `and sum(rate(http_server_request_duration_seconds_count{job="checkout-api"}[5m])) > 0.1` (at least
  6 requests/min) to the page rules.
- Native or exponential histograms: replace the bucket ratio with
  `histogram_fraction(0, 0.8, sum(rate(http_server_request_duration_seconds{...}[5m])))`, which
  interpolates within buckets, so the threshold need not be a boundary.

Unit test the rules:
```yaml
# slo-rules.test.yaml   run: promtool test rules slo-rules.test.yaml
rule_files: [slo-rules.yaml]
evaluation_interval: 1m
tests:
  - interval: 1m
    input_series:
      - series: 'http_server_request_duration_seconds_count{job="checkout-api",http_route="/checkout/{cart_id}"}'
        values: "0+100x180"             # 100 requests/min for 3 h
      - series: 'http_server_request_duration_seconds_bucket{job="checkout-api",http_route="/checkout/{cart_id}",le="0.8",http_response_status_code="200"}'
        values: "0+80x180"              # 80 good/min: 20% bad
    alert_rule_test:
      - eval_time: 70m
        alertname: CheckoutSLOFastBurn
        exp_alerts:
          - exp_labels: { severity: page }
            exp_annotations:
              summary: "Checkout SLO fast burn (>14.4x)"
              runbook_url: "https://runbooks.example.com/checkout-slo"
```
Add a second test with 99.8% good traffic and `exp_alerts: []` so the rule is shown not to fire below
the threshold.

## 4. Budget arithmetic reference

| SLO | Budget (30 d) | Bad-ratio page (14.4x) | Page (6x) | Ticket (1x) |
|---|---|---|---|---|
| 99% | 7.2 h | 14.4% | 6% | 1% |
| 99.5% | 3.6 h | 7.2% | 3% | 0.5% |
| 99.9% | 43.2 min | 1.44% | 0.6% | 0.1% |
| 99.95% | 21.6 min | 0.72% | 0.3% | 0.05% |
| 99.99% | 4.32 min | 0.144% | 0.06% | 0.01% |

Time to exhaust the whole budget at burn rate B: 30 d / B (14.4x: about 50 hours; 6x: 5 days).
Budget in requests: (1 - SLO) x expected requests per window (99.5% of 2,000,000 monthly checkouts
allows 10,000 bad ones).
