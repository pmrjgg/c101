# OpenAPI 3.1 components and lint rules

Reusable components for the conventions in `SKILL.md`. OpenAPI 3.1 uses JSON Schema 2020-12:
nullable is `type: [string, "null"]` (the 3.0 `nullable: true` keyword is gone), `examples` is an
array, `exclusiveMinimum` is a number. In YAML flow mappings (`{ ... }`) quote any value containing
a comma: `description: RFC 3339, UTC` silently creates a key named `UTC`.

## Components

```yaml
openapi: 3.1.1
info: { title: Payments API, version: 1.4.0 }
security: [{ bearerAuth: [] }]          # root default; redocly's security-defined rule requires it
components:
  securitySchemes:
    bearerAuth: { type: http, scheme: bearer }
  parameters:
    IdempotencyKey:
      name: Idempotency-Key
      in: header
      required: true
      description: >
        Client-generated unique key (UUID recommended). Retries with the same key and body replay
        the first response for 24 h. Same key with a different body -> 422; while the first request
        is in flight -> 409.
      schema: { type: string, minLength: 8, maxLength: 255 }
    IfMatch:
      name: If-Match
      in: header
      required: true
      description: Strong ETag from a previous GET. Mismatch -> 412; missing -> 428.
      schema: { type: string }
    Limit:
      name: limit
      in: query
      schema: { type: integer, minimum: 1, maximum: 100, default: 50 }
    Cursor:
      name: cursor
      in: query
      description: Opaque cursor from `next_cursor` of the previous page.
      schema: { type: string, maxLength: 512 }

  headers:
    ETag: { schema: { type: string }, description: Strong entity tag of the returned representation }
    Location: { schema: { type: string, format: uri-reference } }
    RetryAfter: { schema: { type: integer, minimum: 0 }, description: Seconds to wait before retrying }

  schemas:
    Problem:
      type: object
      required: [type, title, status]
      properties:
        type: { type: string, format: uri-reference, default: about:blank }
        title: { type: string }
        status: { type: integer, minimum: 400, maximum: 599 }
        detail: { type: string }
        instance: { type: string, format: uri-reference }
        code: { type: string, description: Stable machine-readable error code }
        request_id: { type: string }
        errors:
          type: array
          items:
            type: object
            required: [detail]
            properties:
              pointer: { type: string, description: JSON Pointer (RFC 6901) into the request body }
              parameter: { type: string, description: Name of the offending query or path parameter }
              header: { type: string }
              code: { type: string }
              detail: { type: string }
    Money:
      type: object
      required: [amount, currency]
      properties:
        amount: { type: integer, minimum: 1, description: Minor units (cents) }
        currency: { type: string, pattern: '^[A-Z]{3}$', description: ISO 4217 code }
    CreatePayment:
      type: object
      required: [amount, currency, customer_id]
      properties:
        amount: { type: integer, minimum: 1 }
        currency: { type: string, pattern: '^[A-Z]{3}$' }
        customer_id: { type: string, maxLength: 64 }
        description: { type: [string, "null"], maxLength: 500 }
        metadata:
          type: object
          maxProperties: 20
          additionalProperties: { type: string, maxLength: 500 }
    Payment:
      type: object
      required: [id, amount, currency, status, created_at]
      properties:
        id: { type: string, examples: [pay_01JABCXYZ] }
        amount: { type: integer }
        currency: { type: string }
        status:
          type: string
          description: Open enum; clients must handle unknown values.
          enum: [pending, succeeded, failed, refunded]
        created_at: { type: string, format: date-time, description: 'RFC 3339, UTC' }
    PaymentPage:
      type: object
      required: [data, next_cursor, has_more]
      properties:
        data: { type: array, items: { $ref: '#/components/schemas/Payment' } }
        next_cursor: { type: [string, "null"] }
        has_more: { type: boolean }

  responses:
    Problem:
      description: Error (RFC 9457)
      content:
        application/problem+json:
          schema: { $ref: '#/components/schemas/Problem' }
    PaymentCreated:
      description: Created (or replayed for a repeated Idempotency-Key)
      headers:
        Location: { $ref: '#/components/headers/Location' }
        ETag: { $ref: '#/components/headers/ETag' }
      content:
        application/json:
          schema: { $ref: '#/components/schemas/Payment' }
    PaymentPage:
      description: One page of payments, newest first
      content:
        application/json:
          schema: { $ref: '#/components/schemas/PaymentPage' }
    TooManyRequests:
      description: Rate limited
      headers:
        Retry-After: { $ref: '#/components/headers/RetryAfter' }
      content:
        application/problem+json:
          schema: { $ref: '#/components/schemas/Problem' }
```

`enum` in a response schema makes many generators emit closed enums (a new value then fails
deserialization). Either document the enum as open and configure generators for it, or declare the
field as `type: string` with `examples` and keep the list in the description.

## Spectral ruleset (team conventions)

```yaml
# .spectral.yaml
extends: ["spectral:oas"]
rules:
  operation-operationId: error
  operation-tag-defined: off
  paths-kebab-case:
    description: Path segments are kebab-case
    severity: error
    given: $.paths[*]~
    then: { function: pattern, functionOptions: { match: "^(/[a-z0-9-]+|/\\{[a-z_]+\\})+$" } }
  error-responses-use-problem-json:
    description: 4xx/5xx responses use application/problem+json
    severity: error
    given: $.paths[*][*].responses[?(@property.match(/^[45]/))].content
    then: { field: application/problem+json, function: truthy }
  no-offset-pagination:
    description: Use cursor pagination
    severity: warn
    given: $.paths[*][*].parameters[?(@.in == 'query')].name
    then: { function: pattern, functionOptions: { notMatch: "^(offset|page)$" } }
```

```bash
npx @stoplight/spectral-cli lint api/openapi.yaml --ruleset .spectral.yaml --fail-severity warn
npx @redocly/cli lint api/openapi.yaml          # recommended ruleset; configure in redocly.yaml
```

The `error-responses-use-problem-json` rule only sees inline `content`; responses defined via
`$ref` are resolved by Spectral before rules run, so it also covers them.

## Status code checklist per operation

| Operation | Declare at least |
|---|---|
| create (POST) | 201, 400, 401, 403, 409, 422, 429 |
| read (GET one) | 200, 304 (if ETags), 401, 403, 404 |
| list (GET many) | 200, 400 (bad cursor/filter), 401, 403, 429 |
| update (PATCH/PUT) | 200 or 204, 400, 401, 403, 404, 409, 412, 422, 428 |
| delete | 204, 401, 403, 404, 409, 412 |

Every 4xx/5xx response references `#/components/responses/Problem` (or a more specific problem
response) so clients have one error type.
