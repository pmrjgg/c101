# Release pipelines for Go services and CLIs

Gate script, goreleaser, ko, a distroless Dockerfile, a reproducibility check and a CI sketch.
Names (`itemsd`, `example.com/svc`, `ghcr.io/acme`) are placeholders.

## 1. Gate script

```bash
#!/usr/bin/env bash
# scripts/gate.sh: cheap checks first; exits non-zero on the first failure.
set -euo pipefail
export GOWORK=off                                   # prove the module builds without a local go.work
unformatted=$(gofmt -l .)
if [ -n "$unformatted" ]; then echo "gofmt needed:"; echo "$unformatted"; exit 1; fi
go vet ./...
golangci-lint run ./...
go build ./...
go test -race -shuffle=on -count=1 ./...
go mod tidy -diff
govulncheck ./...
```

Run it locally before pushing and as the single CI entry point, so local and CI gates cannot drift.
Integration tests (`-tags=integration`) and nightly fuzzing run as separate jobs (`go-testing-fuzzing`).

## 2. goreleaser (CLIs and binaries)

```yaml
# .goreleaser.yaml
version: 2
project_name: itemsd
before:
  hooks:
    - go mod tidy -diff                             # refuse to release an untidy module
builds:
  - id: itemsd
    main: ./cmd/itemsd
    binary: itemsd
    env: [CGO_ENABLED=0]
    goos: [linux, darwin, windows]
    goarch: [amd64, arm64]
    flags: [-trimpath]
    ldflags:
      - -s -w -X main.version={{.Version}} -X main.commit={{.Commit}} -X main.date={{.CommitDate}}
    mod_timestamp: "{{ .CommitTimestamp }}"         # reproducible file times
checksum:
  name_template: checksums.txt
```

```bash
goreleaser check                                    # validate the config
goreleaser build --single-target --snapshot --clean # quick local binary for this platform
goreleaser release --snapshot --clean               # full dry run into dist/, nothing published
goreleaser release --clean                          # on a pushed tag in CI only
```

`{{.CommitDate}}` instead of `{{.Date}}` and no `time` template calls keep builds reproducible.
Publishing (GitHub release, Homebrew tap, signing) needs tokens from the CI secret store, never from
files in the repository. Tag pushes are irreversible: prepare, then hand the push to the user.

## 3. ko (container images without a Dockerfile)

```yaml
# .ko.yaml
defaultBaseImage: gcr.io/distroless/static-debian13:nonroot   # ko's own default: cgr.dev/chainguard/static
defaultPlatforms: [linux/amd64, linux/arm64]
builds:
  - id: itemsd
    main: ./cmd/itemsd
    env: [CGO_ENABLED=0]
    flags: [-trimpath]
    ldflags: ["-s -w -X main.version={{.Git.Tag}}"]
```

```bash
KO_DOCKER_REPO=ko.local ko build ./cmd/itemsd                 # local Docker daemon
KO_DOCKER_REPO=ghcr.io/acme/itemsd ko build --bare ./cmd/itemsd   # push; prints the image digest
```

Naming: the default appends an MD5 of the import path; `--bare` uses `KO_DOCKER_REPO` as is,
`-B/--base-import-paths` uses the last path element, `-P/--preserve-import-paths` the full path.
Deploy by digest (`image@sha256:...`), not by tag.

## 4. Multi-stage Dockerfile ending in distroless

```dockerfile
# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM golang:1.27 AS build
ARG TARGETOS TARGETARCH VERSION=dev
WORKDIR /src
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH \
    go build -trimpath -ldflags="-s -w -X main.version=${VERSION}" -o /out/itemsd ./cmd/itemsd

FROM gcr.io/distroless/static-debian13:nonroot
COPY --from=build /out/itemsd /itemsd
USER nonroot:nonroot
ENTRYPOINT ["/itemsd"]
```

`docker buildx build --platform linux/amd64,linux/arm64 --build-arg VERSION=$(git describe --tags) .`
cross-compiles natively on the build platform (no emulation). The static image carries CA
certificates and tzdata but no shell: debug with the `:debug` tag variant, never by adding a shell to
production images. If go.mod pins a newer `toolchain` than the image, `GOTOOLCHAIN=auto` downloads it
during the build: keep the image tag in step with the `toolchain` line.

## 5. Reproducibility check

```bash
out=.stack/out/repro; rm -rf "$out"; mkdir -p "$out"
for d in a b; do
  git worktree add --detach "$out/$d" HEAD
  (cd "$out/$d" && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w -X main.version=v1.2.3" -o "../$d.bin" ./cmd/itemsd)
done
shasum -a 256 "$out"/*.bin                              # sha256sum on Linux; hashes must match
git worktree remove "$out/a"; git worktree remove "$out/b"
```

Differences come from: a different toolchain (check `go version -m`), a missing `-trimpath`,
environment (`CGO_ENABLED`, `GOAMD64`, `GOFLAGS`), timestamps or random values in `-ldflags`, or a
dirty tree (`vcs.modified=true` in `go version -m`).

## 6. CI sketch (GitHub Actions)

```yaml
name: ci
on: [push, pull_request]
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4                       # pin actions to commit SHAs in real pipelines
      - uses: actions/setup-go@v5
        with:
          go-version-file: go.mod
      - run: curl -sSfL https://golangci-lint.run/install.sh | sh -s -- -b "$(go env GOPATH)/bin" v2.15.0
      - run: go install golang.org/x/vuln/cmd/govulncheck@latest
      - run: bash scripts/gate.sh
```

Pin `govulncheck` to a version for reproducible CI if its output format is parsed. Release jobs
run on tag pushes only, with `goreleaser release --clean` or `ko build`, plus an SBOM step
(`cyclonedx-gomod app ...`) attached to the release.
