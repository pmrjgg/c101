# Dockerfile templates

Tags were current in October 2026; add `@sha256:<digest>` to every `FROM` in real files. Every
template: `# syntax=docker/dockerfile:1`, dependency layer before source, non-root runtime, exec-form
entrypoint. The Python + uv template is in the main skill (section 2).

## Node + pnpm (monorepo package `api`)

```dockerfile
# syntax=docker/dockerfile:1
FROM node:24-slim AS build
RUN npm install -g pnpm@12.14.0          # Corepack is not bundled with Node 25+; pin pnpm explicitly
WORKDIR /repo
# 1) fetch the whole store from the lockfile only: cached until pnpm-lock.yaml changes
COPY pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm fetch
# 2) link from the store without network, build, then prune to one deployable package
COPY . .
RUN pnpm install --offline --frozen-lockfile
RUN pnpm --filter=api run build
RUN pnpm --filter=api --prod deploy /prod/api

FROM gcr.io/distroless/nodejs24-debian13:nonroot
WORKDIR /app
COPY --from=build /prod/api /app
ENV NODE_ENV=production
EXPOSE 3000
CMD ["dist/server.js"]                   # distroless entrypoint is node; never npm/pnpm start
```

App-side shutdown (Node does not exit gracefully on SIGTERM by itself when it is PID 1):
```js
const server = app.listen(3000);
for (const sig of ["SIGTERM", "SIGINT"]) {
  process.on(sig, () => {
    server.close(() => process.exit(0));          // stop accepting, finish in-flight requests
    setTimeout(() => process.exit(1), 10_000).unref();
  });
}
```
Private registry token: `RUN --mount=type=secret,id=npmrc,target=/root/.npmrc pnpm fetch` and build
with `--secret id=npmrc,src=$HOME/.npmrc`.
Single-package repo: skip `deploy`; copy `node_modules` from a `pnpm install --prod --frozen-lockfile`
stage plus `dist/` from the build stage (pnpm docs, example 1).

## Go (static binary)

```dockerfile
# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM golang:1.27 AS build
ARG TARGETOS TARGETARCH
WORKDIR /src
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=bind,source=go.mod,target=go.mod \
    --mount=type=bind,source=go.sum,target=go.sum \
    go mod download
COPY . .
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH \
    go build -trimpath -ldflags='-s -w' -tags timetzdata -o /out/app ./cmd/app

FROM gcr.io/distroless/static-debian13:nonroot
COPY --from=build /out/app /app
USER 65532:65532
ENTRYPOINT ["/app"]
```
- `--platform=$BUILDPLATFORM` runs the compiler natively and cross-compiles for each target platform;
  no QEMU.
- `scratch` instead of distroless: also `COPY --from=build /etc/ssl/certs/ca-certificates.crt
  /etc/ssl/certs/` and set `USER 65532:65532`; there is no `/tmp`, so mount one if the app needs it.
- `-tags timetzdata` embeds the zoneinfo database (about 450 KB) so `time.LoadLocation` works without
  tzdata; or `import _ "time/tzdata"` in `main`.
- CGO needed (sqlite, some DNS setups): build with `CGO_ENABLED=1` and use `distroless/base-debian13`
  or `cc-debian13`.

## Rust (cargo-chef)

```dockerfile
# syntax=docker/dockerfile:1
FROM lukemathwalker/cargo-chef:0.1.78-rust-slim-trixie AS chef
WORKDIR /app

FROM chef AS planner
COPY . .
RUN cargo chef prepare --recipe-path recipe.json

FROM chef AS builder
COPY --from=planner /app/recipe.json recipe.json
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    cargo chef cook --release --recipe-path recipe.json      # deps only: cached until Cargo.lock changes
COPY . .
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    cargo build --release --locked --bin app

FROM gcr.io/distroless/cc-debian13:nonroot
COPY --from=builder /app/target/release/app /app
ENTRYPOINT ["/app"]
```
- Do not mount a cache over `target/`: the cooked dependencies must persist in the image layer for the
  next stage to reuse them.
- Builder glibc must be the same or older than the runtime's (trixie builder -> debian13 runtime).
- Fully static: add the `x86_64-unknown-linux-musl` (or aarch64) target and run on
  `distroless/static-debian13`; benchmark first, musl's allocator is slower (use mimalloc/jemalloc).
- `cargo chef cook` must use the same profile, features and target as the final `cargo build`, or the
  cache is not reused.

## JVM (Spring Boot layered jar)

```dockerfile
# syntax=docker/dockerfile:1
FROM eclipse-temurin:25-jdk AS build
WORKDIR /src
COPY mvnw pom.xml ./
COPY .mvn .mvn
RUN --mount=type=cache,target=/root/.m2 ./mvnw -q dependency:go-offline
COPY src src
RUN --mount=type=cache,target=/root/.m2 ./mvnw -q -DskipTests package \
 && cp target/*.jar application.jar \
 && java -Djarmode=tools -jar application.jar extract --layers --destination extracted

FROM eclipse-temurin:25-jre
WORKDIR /application
COPY --from=build /src/extracted/dependencies/ ./
COPY --from=build /src/extracted/spring-boot-loader/ ./
COPY --from=build /src/extracted/snapshot-dependencies/ ./
COPY --from=build /src/extracted/application/ ./
USER 10001:10001
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-jar", "application.jar"]
```
- Layers ordered by change frequency: a code change rebuilds only `application/` (a few hundred KB).
- `-XX:MaxRAMPercentage=75` sizes the heap from the container memory limit, leaving headroom for
  metaspace, threads and direct buffers.
- Gradle: `./gradlew bootJar` and `build/libs/*.jar`; cache mount on `/root/.gradle`.
- Smaller runtime: `jdeps --print-module-deps` on the extracted classpath, then `jlink --add-modules
  <list> --strip-debug --no-man-pages --no-header-files --output /jre`, copied onto a slim Debian base.
  Verify every code path that loads modules reflectively (JDBC drivers, `jdk.crypto.ec`) before shipping.
- CDS/AOT cache: Spring Boot's extracted layout is CDS-friendly; training runs are version-specific,
  check the Spring Boot and JDK docs for the current flags before enabling.
