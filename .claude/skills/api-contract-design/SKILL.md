---
name: api-contract-design
description: "Designing and evolving service contracts: HTTP method and status semantics, RFC 9457 problem errors, cursor pagination, idempotency keys, ETag concurrency, additive evolution and deprecation headers, OpenAPI 3.1/TypeSpec and protobuf/gRPC rules, breaking-change gates (oasdiff, buf) and client/server code generation from specs with drift checks. Load when adding or changing an endpoint, RPC, event schema or SDK."
when_to_use: "Editing openapi.yaml/.json, *.tsp, *.proto, Avro/JSON Schema event schemas or generated SDKs; choosing status codes or an error format; adding pagination, retries/idempotency or optimistic locking; deprecating or versioning an endpoint; a CI gate fails on oasdiff or buf breaking; generated client drift."
---

# API contract design

The contract is the spec file, not the code. Design and review the spec diff first; code and
clients follow from it. Review-time checks for an existing diff stay in `code-review-checklist`
("API design and compatibility"); this skill is how to design the contract those checks verify.
Test levels and strategy are in `testing-strategy`; auth and injection review in `security-review`.

Standards referenced (verified October 2026): RFC 9110 (HTTP semantics), RFC 9457 (problem
details, obsoletes 7807), RFC 9745 (Deprecation header, March 2025), RFC 8594 (Sunset), RFC 8288
(Link), RFC 3339 (timestamps), OpenAPI 3.1 (JSON Schema 2020-12; OpenAPI 3.2 was published
September 2025, check tool support before adopting it). The Idempotency-Key header is an IETF
draft (draft-ietf-httpapi-idempotency-key-header-07, expired, not an RFC); its semantics are
widely implemented anyway.

Deep material:
[OpenAPI components and lint rules](references/openapi-components.md) |
[code generation and CI gates](references/codegen-and-ci-gates.md)

## 1. Spec-first workflow

1. Write or change the contract: OpenAPI 3.1 YAML, TypeSpec (`tsp compile . --emit @typespec/openapi3`),
   or `.proto`.
2. Lint: `npx @redocly/cli lint openapi.yaml`, or `npx @stoplight/spectral-cli lint openapi.yaml`
   with a team ruleset; `buf lint` for protobuf.
3. Breaking-change gate against main (section 8).
4. Review the contract diff with consumers before writing handlers.
5. Generate server stubs/types and clients (section 9); implement; contract tests (section 10).

Code-first frameworks (FastAPI, NestJS, springdoc, utoipa) are acceptable only when the exported
spec is committed and diffed in CI:

```bash
uv run python -c 'import json; from app.main import app; print(json.dumps(app.openapi(), indent=2, sort_keys=True))' > api/openapi.json
git diff --exit-code api/openapi.json   # fails when code changed the contract without committing it
```

## 2. HTTP semantics

| Method | Safe | Idempotent | Success | Typical errors |
|---|---|---|---|---|
| GET / HEAD | yes | yes | 200; 304 with `If-None-Match` | 404, 400 bad query |
| POST (create) | no | no (make it so with `Idempotency-Key`) | 201 + `Location`; 202 + status URL for async work | 409 duplicate/state, 422 validation |
| POST (action) | no | no | 200 with result, 202 async, 204 nothing | 409 invalid state transition |
| PUT (replace / upsert) | no | yes | 200 or 204; 201 when it created the resource | 409, 412, 422 |
| PATCH | no | not by definition | 200 or 204 | 409, 412, 415 wrong patch format, 422 |
| DELETE | no | yes | 204 (repeat: 204 or 404, pick one and document it) | 409 dependents exist |

| Choose between | Rule |
|---|---|
| 400 vs 422 | 400: request cannot be parsed (malformed JSON, wrong content type of a field, bad query syntax); 422: well-formed but fails validation or business rules |
| 401 vs 403 | 401: no or invalid credentials (send `WWW-Authenticate`); 403: authenticated, not allowed. Return 404 instead of 403 when existence itself is secret |
| 409 vs 412 | 409: conflicts with current state (duplicate, illegal transition); 412: an `If-Match`/`If-Unmodified-Since` precondition failed |
| 429 / 503 | rate limited / temporarily unavailable: both with `Retry-After` (seconds or HTTP-date) |
| 404 vs 410 | 410 only for resources deliberately and permanently removed |

Never return 200 with an error body (`{"ok": false}`): caches, retries, monitoring and generated
clients all key on the status code.

## 3. Error model: RFC 9457 problem details

Media type `application/problem+json`. Members: `type` (URI; the primary identifier clients switch
on; `about:blank` when absent), `title` (stable per type), `status`, `detail` (this occurrence),
`instance` (URI of this occurrence). Add extension members for machine use:

```json
{
  "type": "https://api.example.com/problems/validation",
  "title": "Request validation failed",
  "status": 422,
  "detail": "2 fields are invalid",
  "instance": "/v1/payments/req_01JABCXYZ",
  "code": "validation_failed",
  "errors": [
    {"pointer": "#/currency", "code": "invalid_format", "detail": "must be a 3-letter ISO 4217 code"},
    {"pointer": "#/amount", "code": "out_of_range", "detail": "must be > 0"}
  ],
  "request_id": "req_01JABCXYZ"
}
```

- `errors[].pointer` is a JSON Pointer (RFC 6901) into the request body; RFC 9457's own example uses
  `errors` with `detail` + `pointer`. Query/header problems: use `parameter` / `header` instead.
- Stable `code` strings are part of the contract: document them, never rename them.
- Never put stack traces, SQL, internal hostnames or secrets in `detail`; log them under `request_id`.
- One error schema for every endpoint and status, including 401/403/404/429/500 from gateways.

## 4. Pagination and filtering

Keyset (cursor) pagination for anything that can grow:

```text
GET /v1/payments?limit=50&cursor=eyJjIjoiMjAyNi0xMC0xOVQxMDowMDowMFoiLCJpIjoicGF5XzEyMyJ9
200 {"data": [...50 items...], "next_cursor": "eyJj...", "has_more": true}
Link: <https://api.example.com/v1/payments?limit=50&cursor=eyJj...>; rel="next"
```

- Cursor = base64url of the last item's sort key plus a unique tiebreaker
  (`{"c": "2026-10-19T10:00:00Z", "i": "pay_123"}`); opaque to clients; validate on input (400 on
  garbage); sign it (HMAC) if clients must not craft cursors.
- Server query: `WHERE (created_at, id) < ($c, $i) ORDER BY created_at DESC, id DESC LIMIT $limit + 1`
  (the extra row sets `has_more`); index design in `sql-query-tuning`.
- `limit`: default 50, max 100 (reject or clamp above max; document which).
- Offset pagination only for small bounded admin lists: cost grows with depth, pages shift on inserts.
- One filter/sort grammar for every list endpoint (e.g. `status=a,b`, `created_after=`,
  `created_before=`, `sort=-created_at`); unknown filter parameters -> 400, not silently ignored.
- Totals are optional (`include_total=true`) because `COUNT(*)` on large filtered sets is expensive.

## 5. Idempotency and concurrency

Idempotency-Key on non-idempotent POST (and PATCH where retries are common):

| Situation | Response |
|---|---|
| key missing on an endpoint that requires it | 400 problem |
| first request with key | process; store `(scope, key) -> request hash, status, response` |
| retry, same key, same request hash, completed | replay the stored status code and body exactly |
| same key, different request body | 422 problem (key reuse) |
| same key while the first is still in flight | 409 problem; client retries later |
| key older than the retention window (publish it; ~24 h is common) | treated as new |

Scope keys per client or tenant; hash a canonical form of the body (sorted keys); store the record
in the same transaction as the side effect, or use an `in_progress` row inserted with
`INSERT ... ON CONFLICT DO NOTHING` before calling external systems.

Optimistic concurrency with ETags:
- `GET` returns `ETag: "v7"` (from a version column or content hash).
- `PATCH`/`PUT`/`DELETE` send `If-Match: "v7"`; mismatch -> 412; a missing `If-Match` where you
  require one -> 428 Precondition Required.
- Weak ETags (`W/"..."`) never satisfy `If-Match` (strong comparison); use strong ones for writes.
- `If-None-Match: *` on PUT means create only if absent.

## 6. Evolution rules

| Change | Breaking? |
|---|---|
| add endpoint, add optional request field or query parameter, add response field | no |
| add enum value in a response | yes for clients with closed enums: declare enums open from day one and say so in the spec |
| remove or rename field, endpoint or parameter | yes |
| optional -> required (request), required -> optional (response) | yes |
| narrow validation (shorter `maxLength`, new `pattern`, smaller `maximum`) | yes for requests that used to pass (except rejecting values that used to cause 5xx) |
| change type, format, units, default value or meaning of a field | yes (never repurpose a field: add a new one) |
| change error status or `code` for a case | yes |
| change pagination order or page size default | yes |

- Additive-only within a version; clients are tolerant readers (ignore unknown fields, unknown enum
  values map to an "unknown" branch).
- Deprecate before removing, in the spec (`deprecated: true`) and on the wire:
  ```text
  Deprecation: @1792368000
  Sunset: Fri, 30 Apr 2027 23:59:59 GMT
  Link: <https://developer.example.com/deprecations/v1-charges>; rel="deprecation"; type="text/html"
  ```
  `Deprecation` is a structured-field date (`@` + Unix seconds, here 2026-10-19T00:00:00Z, RFC 9745);
  `Sunset` is an HTTP-date (RFC 8594) and must not be earlier than the deprecation date. Add a changelog entry and track usage
  of the deprecated operation; remove only after usage is zero or the sunset passed.
- URL major version (`/v2/`) only for a breaking redesign; never version per endpoint ad hoc.

## 7. Protobuf and gRPC rules

- Never renumber or reuse field numbers or names; on removal: `reserved 4, 7; reserved "legacy_id";`.
- Enum zero value is `<ENUM>_UNSPECIFIED = 0` (AIP-126) and is never a meaningful state.
- `optional` (proto3) when presence matters (distinguish 0/"" from unset); wrapper messages for
  every RPC (`CreatePaymentRequest`/`Payment`), never bare scalars or `google.protobuf.Empty`
  returns you may later need to extend.
- Deadlines on every call (client-side timeout propagated); servers check cancellation.
- Google AIPs as the house style: AIP-158 pagination (`page_size`, `page_token`, `next_page_token`),
  AIP-180 backwards compatibility, AIP-193 errors (`google.rpc.Status` with `ErrorInfo` details),
  AIP-154 ETags, AIP-155 request IDs for idempotency.
- Changing a field's type, moving fields into/out of a `oneof`, or changing `package` breaks wire or
  generated code; `buf breaking` catches these (section 8).
- Browsers: Connect RPC (connect-go, connect-es) serves Connect, gRPC and gRPC-Web from one handler
  with plain HTTP/JSON debugging.
- Protobuf editions (`edition = "2023"`) replace `syntax = "proto3"` in newer toolchains; feature
  defaults differ, so migrate with `buf` tooling, not by hand (version-dependent).

## 8. Breaking-change gates in CI

```bash
git show origin/main:api/openapi.yaml > /tmp/base.yaml
oasdiff breaking /tmp/base.yaml api/openapi.yaml --fail-on ERR   # exit 1 on definite breaks; WARN = possible
oasdiff changelog /tmp/base.yaml api/openapi.yaml                # human-readable changelog for the PR
buf breaking --against '.git#branch=main'                        # default category FILE
```

Event schemas (Avro, Protobuf or JSON Schema subjects in a schema registry) get the same gate:

| Registry compatibility mode | Guarantees | Upgrade order |
|---|---|---|
| BACKWARD (Confluent default) | new schema reads data written with the previous schema | consumers first |
| FORWARD | previous schema reads data written with the new one | producers first |
| FULL | both | any order |
| `*_TRANSITIVE` | against all earlier versions, not just the last | same as base mode |
| NONE | nothing | avoid |

Set per subject (`PUT /config/<subject>` with `{"compatibility": "FULL"}`) and test a candidate with
`POST /compatibility/subjects/<subject>/versions/latest` in CI before deploying the producer.
Gate config and workflow YAML: [code generation and CI gates](references/codegen-and-ci-gates.md).

## 9. Code generation from specs

| Target | Tool | Command |
|---|---|---|
| TS types + fetch client | openapi-typescript + openapi-fetch | `npx openapi-typescript api/openapi.yaml -o web/src/api/schema.d.ts`; `createClient<paths>({ baseUrl })` |
| TS clients with hooks (React Query, SWR) | orval | `npx orval --config orval.config.ts` |
| Go server/client | oapi-codegen v2 | `go tool oapi-codegen -config oapi.yaml api/openapi.yaml` (module `github.com/oapi-codegen/oapi-codegen/v2`) |
| many languages | openapi-generator, Kiota | `npx @openapitools/openapi-generator-cli generate -i api/openapi.yaml -g python -o clients/py`; `kiota generate -l TypeScript -d api/openapi.yaml -c PaymentsClient -o src/client` |
| protobuf / Connect | buf | `buf generate` with `buf.gen.yaml` v2 (`protocolbuffers/go`, `connectrpc/go`, `bufbuild/es`) |
| Python models | datamodel-code-generator | `datamodel-codegen --input api/openapi.yaml --input-file-type openapi --output-model-type pydantic_v2.BaseModel --output app/models.py` |
| SQL -> typed code | sqlc | `sqlc generate`; `sqlc diff` exits non-zero on drift |

Committed vs build-time output: commit generated code when consumers build without the generator
(SDK repos, Go modules) or when reviewers should see the effect of a spec change; generate at build
time when the toolchain is always present. Either way add a drift check:

```bash
make generate && git diff --exit-code -- web/src/api internal/api clients/   # CI fails on stale output
```

Pin generator versions (lockfile, `go tool`, `buf.gen.yaml` plugin versions): unpinned generators
produce drift with no spec change.

## 10. Contract testing

- Schemathesis (provider side, property-based from the spec): `st run api/openapi.yaml --url
  http://localhost:8000 --checks all --max-examples 200` (`--mode positive|negative|all`, default all).
  Checks include `not_a_server_error`, `status_code_conformance`, `response_schema_conformance`,
  `negative_data_rejection` (invalid input must get 4xx), `use_after_free`. Every finding prints a
  reproducing request; turn it into a regression test.
- Pact (consumer-driven, across teams): consumer tests produce a pact file -> broker -> provider
  verification in the provider's CI -> `pact-broker can-i-deploy` gates each deploy.
- Schemathesis checks conformance to the spec; Pact checks the interactions consumers rely on. Use
  both when separate teams own each side.

## 11. Pitfalls

- Leaking the database schema: column names, internal IDs, join tables and nullable-everything
  become permanent API.
- Booleans that later need a third state (`is_active` -> active/suspended/closed): use an enum.
- Timestamps without offset or as local time: RFC 3339 in UTC (`2026-10-19T10:00:00Z`).
- int64 IDs as JSON numbers: JavaScript loses precision above 2^53 - 1; send them as strings.
- Money as floats: integer minor units plus currency, or decimal strings.
- Unbounded list endpoints: add pagination before the first release (adding it later breaks clients).
- Chatty N+1 APIs (client fetches each child separately): offer batch endpoints (`?ids=a,b,c`) or
  `expand=` parameters with a documented limit.
- Credentials or personal data in query strings: they end up in logs, proxies and browser history.
- `additionalProperties: false` on response schemas used by generated clients: any added field breaks them.
- Validating only in the handler, not in the spec: generated clients and contract tests cannot see the rules.

## 12. Worked example: payments endpoints

Goal: `POST /v1/payments` (idempotent create) and cursor-paginated `GET /v1/payments`.

1. Spec first (excerpt; full components in [the reference](references/openapi-components.md)):

```yaml
/v1/payments:
  post:
    operationId: createPayment
    parameters: [{ $ref: '#/components/parameters/IdempotencyKey' }]
    requestBody:
      required: true
      content: { application/json: { schema: { $ref: '#/components/schemas/CreatePayment' } } }
    responses:
      '201': { $ref: '#/components/responses/PaymentCreated' }   # Location + ETag headers
      '400': { $ref: '#/components/responses/Problem' }
      '409': { $ref: '#/components/responses/Problem' }
      '422': { $ref: '#/components/responses/Problem' }
  get:
    operationId: listPayments
    parameters:
      - { name: limit, in: query, schema: { type: integer, minimum: 1, maximum: 100, default: 50 } }
      - { name: cursor, in: query, schema: { type: string, maxLength: 512 } }
    responses:
      '200': { $ref: '#/components/responses/PaymentPage' }       # data, next_cursor, has_more
```

   First draft of `CreatePayment`: `amount: {type: integer, minimum: 1}`, `currency: {type: string}`.

2. Lint and gate: `npx @redocly/cli lint api/openapi.yaml` clean; `oasdiff breaking /tmp/base.yaml
   api/openapi.yaml --fail-on ERR` exits 0 (only additions). Contract diff reviewed by the web and
   mobile owners before any handler code.
3. Client: `npx openapi-typescript api/openapi.yaml -o web/src/api/schema.d.ts`; the web app calls
   `client.POST("/v1/payments", { params: { header: { "Idempotency-Key": key } }, body })` and gets
   typed `data` / `error`. Drift check added to CI.
4. Server: idempotency table `(tenant_id, key) PRIMARY KEY, request_hash, status, response_code,
   response_body, created_at`; retention 24 h by a cleanup job; list query uses keyset on
   `(created_at, id)`.
5. Contract test:

```bash
st run api/openapi.yaml --url http://localhost:8000 --checks all --max-examples 200 \
   -H 'Authorization: Bearer test-token-from-fixtures'
# not_a_server_error failed on POST /v1/payments
#   500 Internal Server Error, body {"currency": "", "amount": 1}
#   KeyError: '' in fx_rates lookup
```

   The spec allowed `""`, the handler assumed a valid code. Fix both sides:
   `currency: {type: string, pattern: '^[A-Z]{3}$'}` in the spec, validation in the handler that
   returns 422 problem+json with `errors: [{pointer: "#/currency", code: "invalid_format"}]`, and a
   regression test for `""`. Rerun: all checks pass; `negative_data_rejection` confirms `""`, `"usd"`
   and `"EURO"` now get 422. Rejecting values that previously crashed is not a breaking change;
   `oasdiff` reports the new pattern as a WARN, accepted in the PR with that reasoning.
6. Merge with: spec diff, oasdiff output, generated client diff, Schemathesis summary in the PR.

Related: `code-review-checklist` (review checks), `testing-strategy` (contract test level),
`security-review` (authz, injection), `sql-query-tuning` (keyset indexes), `codemod-automation`
(client migrations after deprecations), `refactoring-playbook` (parallel change), hub `coding-general`.
