# Multi-arch CI build, scanning, signing

Versions and SHAs as of October 2026; re-pin with `pinact run` or Renovate. Pipeline-level concerns
(caching strategy, required checks, OIDC) are covered by the `ci-pipelines` skill.

## 1. Native multi-arch build, merged by digest (GitHub Actions)

Each platform builds on its own native runner and pushes an untagged image by digest; a merge job
creates the tagged multi-platform index, scans it, signs it and attests it.

```yaml
# .github/workflows/image.yml
name: image
on:
  push:
    branches: [main]
    tags: ["v*"]
permissions:
  contents: read
env:
  IMAGE: ghcr.io/acme/checkout-api
jobs:
  build:
    strategy:
      fail-fast: true
      matrix:
        include:
          - { platform: linux/amd64, runner: ubuntu-24.04 }
          - { platform: linux/arm64, runner: ubuntu-24.04-arm }
    runs-on: ${{ matrix.runner }}
    timeout-minutes: 30
    permissions: { contents: read, packages: write }
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with: { persist-credentials: false }
      - uses: docker/login-action@dbcb813823bdd20940b903addbd779551569679f # v4.6.0
        with: { registry: ghcr.io, username: "${{ github.actor }}", password: "${{ secrets.GITHUB_TOKEN }}" }
      - uses: docker/setup-buildx-action@f87e5991a6d7451dcb8d9637bfbc97413f497069 # v4.4.1
      - id: build
        uses: docker/build-push-action@c3c9e263c25d99ce0380d002d59b67737d91b0dc # v7.4.0
        with:
          context: apps/api
          platforms: ${{ matrix.platform }}
          outputs: type=image,name=${{ env.IMAGE }},push-by-digest=true,name-canonical=true,push=true
          cache-from: type=gha,scope=api-${{ matrix.runner }}
          cache-to: type=gha,mode=max,scope=api-${{ matrix.runner }}
          provenance: mode=max
          sbom: true
      - env: { DIGEST: "${{ steps.build.outputs.digest }}" }
        run: mkdir -p digests && touch "digests/${DIGEST#sha256:}"
      - uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2
        with: { name: "digest-${{ matrix.runner }}", path: "digests/*", retention-days: 1 }

  merge:
    needs: build
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    permissions:
      contents: read
      packages: write
      id-token: write
      attestations: write
      artifact-metadata: write
    steps:
      - uses: actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333 # v8.0.2
        with: { pattern: "digest-*", path: digests, merge-multiple: true }
      - uses: docker/login-action@dbcb813823bdd20940b903addbd779551569679f # v4.6.0
        with: { registry: ghcr.io, username: "${{ github.actor }}", password: "${{ secrets.GITHUB_TOKEN }}" }
      - uses: docker/setup-buildx-action@f87e5991a6d7451dcb8d9637bfbc97413f497069 # v4.4.1
      - id: merge
        working-directory: digests
        env: { REF: "${{ github.ref_name }}" }
        run: |
          # shellcheck disable=SC2046  # word splitting of the digest list is intended
          docker buildx imagetools create -t "$IMAGE:$REF" -t "$IMAGE:sha-$GITHUB_SHA" \
            $(printf "$IMAGE@sha256:%s " *)
          digest=$(docker buildx imagetools inspect "$IMAGE:$REF" --format '{{json .Manifest}}' | jq -r .digest)
          echo "digest=$digest" >> "$GITHUB_OUTPUT"
      - name: scan (block on fixable critical)
        env: { DIGEST: "${{ steps.merge.outputs.digest }}" }
        run: |
          docker run --rm aquasec/trivy:0.76.0 image --severity CRITICAL --ignore-unfixed \
            --exit-code 1 "$IMAGE@$DIGEST"
      - uses: sigstore/cosign-installer@6f9f17788090df1f26f669e9d70d6ae9567deba6 # v4.1.2
      - env: { DIGEST: "${{ steps.merge.outputs.digest }}" }
        run: cosign sign --yes "$IMAGE@$DIGEST"
      - uses: actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6 # v4.2.2
        with:
          subject-name: ${{ env.IMAGE }}
          subject-digest: ${{ steps.merge.outputs.digest }}
          push-to-registry: true
```

Notes:
- Separate GHA cache scopes per runner; one shared scope makes the two platforms evict each other.
- The scan runs before signing: an image that fails the gate is never signed, and admission policies
  that require a signature will refuse it.
- Private repos: `ubuntu-24.04-arm` standard runners have 2 vCPU / 8 GB (public repos get 4 / 16).
- Pin the scanner image by digest as well; scanner images are themselves supply-chain inputs.

## 2. Local equivalents

```bash
# one-off multi-arch build from a laptop (arm64 native on Apple Silicon, amd64 via QEMU)
docker buildx create --name multi --driver docker-container --use
docker buildx build --platform linux/amd64,linux/arm64 \
  --provenance=mode=max --sbom=true -t ghcr.io/acme/checkout-api:dev --push apps/api

# inspect what was pushed
docker buildx imagetools inspect ghcr.io/acme/checkout-api:dev
docker buildx imagetools inspect ghcr.io/acme/checkout-api:dev --format '{{json .Provenance}}' | jq 'keys'  # present?
docker buildx imagetools inspect ghcr.io/acme/checkout-api:dev --format '{{json .SBOM}}' | jq 'keys'

# run the other architecture locally (slow, emulated)
docker run --rm --platform linux/amd64 ghcr.io/acme/checkout-api:dev python -c 'import platform; print(platform.machine())'
```
The default `docker` driver cannot build multi-platform images unless the containerd image store is
enabled; the `docker-container` driver always can.

## 3. Scanner gates and triage

| Tool | Command | Exit code control |
|---|---|---|
| trivy | `trivy image --severity CRITICAL,HIGH --ignore-unfixed --exit-code 1 <img>` | `--exit-code`; `.trivyignore` with an expiry comment per ID |
| grype | `grype <img> --fail-on critical --only-fixed` | `--fail-on`; `.grype.yaml` ignore rules |
| docker scout | `docker scout cves --exit-code --only-severity critical,high --only-fixed <img>` | `--exit-code` returns 2 on findings |
| hadolint | `hadolint --failure-threshold error Dockerfile` | `.hadolint.yaml` with `ignored:` list and reasons |
| dive | `CI=true dive <img>` with `.dive-ci` | rules fail the run |

Triage rule: a finding is suppressed only with an ID, a reason (not reachable, not shipped, no fix)
and a review date. Base-image CVEs are fixed by bumping the base digest (Renovate), not by
`apt-get upgrade` in the Dockerfile, which makes builds non-reproducible.

## 4. Compose patterns

| Need | Compose |
|---|---|
| Start order with readiness | `depends_on: { db: { condition: service_healthy } }` + a real `healthcheck` on `db` |
| One-shot migrations before app | `migrate` service with `depends_on: { db: { condition: service_healthy } }`; app depends on `migrate: { condition: service_completed_successfully }` |
| Optional services | `profiles: [tracing]`; `docker compose --profile tracing up` |
| Hot reload | `develop.watch` with `sync` for source, `rebuild` for lockfiles, `sync+restart` for config files |
| Persistent data | named volumes (`pgdata:`), never bind-mount database files from macOS |
| Local secrets | `env_file: [.env]` (gitignored, dockerignored) or compose `secrets:` from files |
| Prod parity | same Dockerfile, `target:` selects `dev` vs runtime stage |
| Overrides | `compose.override.yaml` is merged automatically; CI uses `-f compose.yaml -f compose.ci.yaml` |

```yaml
  migrate:
    build: { context: ./apps/api, target: builder }
    command: ["/app/.venv/bin/alembic", "upgrade", "head"]
    depends_on:
      db: { condition: service_healthy }
  api:
    depends_on:
      migrate: { condition: service_completed_successfully }
```
