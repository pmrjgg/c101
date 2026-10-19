# Code generation and CI gates

Pin every generator version; an unpinned generator produces drift without a spec change.

## TypeScript: openapi-typescript + openapi-fetch

```bash
npm i -D openapi-typescript && npm i openapi-fetch
npx openapi-typescript api/openapi.yaml -o web/src/api/schema.d.ts
```

```ts
import createClient from "openapi-fetch";
import type { paths } from "./api/schema";

const client = createClient<paths>({ baseUrl: "https://api.example.com" });

const { data, error, response } = await client.POST("/v1/payments", {
  params: { header: { "Idempotency-Key": crypto.randomUUID() } },
  body: { amount: 1999, currency: "EUR", customer_id: "cus_42" },
});
if (error) {
  // error is typed from the problem+json schema for the declared 4xx responses
  console.warn(response.status, error.code, error.errors);
}

const page = await client.GET("/v1/payments", { params: { query: { limit: 50 } } });
```

Checked with openapi-typescript 7.13: header parameters are generated under
`parameters.header`, nullable 3.1 types (`type: [string, "null"]`) become `string | null`.
Add `tsc --noEmit` to CI so spec changes that break callers fail the build.

## Go: oapi-codegen v2

```bash
go get -tool github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen   # Go 1.24+ tool directive
go tool oapi-codegen -config api/oapi.yaml api/openapi.yaml
```

```yaml
# api/oapi.yaml
package: api
output: internal/api/api.gen.go
generate:
  models: true
  std-http-server: true     # net/http ServeMux (Go 1.22+ routing patterns)
  strict-server: true       # typed request/response objects per operation
  embedded-spec: true       # for request validation middleware
```

Request validation against the spec at runtime: `github.com/oapi-codegen/nethttp-middleware`
(module path version-dependent; check the oapi-codegen README).

## Python: datamodel-code-generator

```bash
uvx --from datamodel-code-generator datamodel-codegen \
  --input api/openapi.yaml --input-file-type openapi \
  --output-model-type pydantic_v2.BaseModel --output app/models.py
```

Code-first FastAPI services export the spec instead (see `SKILL.md` section 1) and diff it in CI.

## Multi-language: openapi-generator, Kiota

```bash
npx @openapitools/openapi-generator-cli generate -i api/openapi.yaml -g python -o clients/python \
  --additional-properties=packageName=payments_client
npx @openapitools/openapi-generator-cli list            # available generators
kiota generate -l TypeScript -d api/openapi.yaml -c PaymentsClient -n payments -o src/client
```

## Protobuf / Connect: buf

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
plugins:
  - remote: buf.build/protocolbuffers/go
    out: gen/go
    opt: paths=source_relative
  - remote: buf.build/connectrpc/go
    out: gen/go
    opt: paths=source_relative
  - remote: buf.build/bufbuild/es
    out: web/src/gen
```

```bash
buf lint
buf breaking --against '.git#branch=main'
buf generate
```

Pin remote plugin versions (`buf.build/protocolbuffers/go:v<version>`) once the output is committed.

## SQL: sqlc

```bash
sqlc generate      # typed query functions from queries/*.sql and the schema
sqlc diff          # non-zero exit when generated code is out of date
sqlc vet           # lint rules over queries
```

## Drift check (any generator)

```make
generate:
	npx openapi-typescript api/openapi.yaml -o web/src/api/schema.d.ts
	go tool oapi-codegen -config api/oapi.yaml api/openapi.yaml
	buf generate

check-generated: generate
	git diff --exit-code -- web/src/api internal/api gen web/src/gen
```

## CI workflow (GitHub Actions)

```yaml
name: api-contract
on: [pull_request]
jobs:
  contract:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - name: Lint OpenAPI
        run: npx @redocly/cli lint api/openapi.yaml
      - name: Breaking changes (OpenAPI)
        run: |
          git show origin/${{ github.base_ref }}:api/openapi.yaml > /tmp/base.yaml
          oasdiff breaking /tmp/base.yaml api/openapi.yaml --fail-on ERR
          oasdiff changelog /tmp/base.yaml api/openapi.yaml > changelog.txt
      - name: Breaking changes (protobuf)
        run: |
          git fetch origin "${{ github.base_ref }}:${{ github.base_ref }}"
          buf breaking --against ".git#branch=${{ github.base_ref }}"
      - name: Generated code is current
        run: make check-generated
```

Install `oasdiff` and `buf` with their official setup actions or release binaries pinned to a
version. A PR that must break the contract (new major version) gets an explicit label that skips
the breaking job, plus a migration note; never disable the job globally.

## Contract tests in CI

```bash
uv run uvicorn app.main:app --port 8000 &          # or docker compose up -d api
st run api/openapi.yaml --url http://localhost:8000 --checks all --max-examples 100 \
  --report junit --report-dir reports/
```

Seed the database with fixtures first so `GET` by id and `use_after_free` have resources to work
with; give the test user a token through `-H 'Authorization: Bearer ...'` read from CI secrets,
never committed.

Pact (cross-team):

```bash
# consumer CI: tests write pacts/*.json, then
pact-broker publish pacts/ --consumer-app-version "$GIT_SHA" --branch "$BRANCH"
# provider CI: verify against pacts from the broker (framework-specific verifier), then before deploy:
pact-broker can-i-deploy --pacticipant payments-api --version "$GIT_SHA" --to-environment production
```

## Event schema registry checks

```bash
# Confluent-compatible registry: test a candidate schema against the latest registered version
curl -s -X POST -H 'Content-Type: application/vnd.schemaregistry.v1+json' \
  --data "{\"schema\": $(jq -Rs . < schemas/payment_created.avsc)}" \
  "$REGISTRY_URL/compatibility/subjects/payments.payment_created-value/versions/latest"
# -> {"is_compatible": true}
```

Fail the producer's CI when `is_compatible` is false; set the subject's mode once with
`PUT /config/<subject>` (`{"compatibility": "FULL_TRANSITIVE"}` for long-retention topics).
