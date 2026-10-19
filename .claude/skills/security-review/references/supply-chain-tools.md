# Supply chain and scanner reference

Scanners produce leads. Every reported item needs: is the vulnerable code reachable from our usage,
is the input attacker-controlled, and what is the fixed version or mitigation.

## Static analysis (SAST)

```bash
semgrep scan --config p/default --config p/security-audit --metrics=off --sarif -o semgrep.sarif
semgrep scan --config p/owasp-top-ten --metrics=off --error             # non-zero exit on findings
codeql database create codeql-db --language=python --source-root .
codeql database analyze codeql-db codeql/python-queries:codeql-suites/python-security-extended.qls \
  --download --format=sarif-latest --output=codeql.sarif
bandit -r src -ll -f json -o bandit.json                                # Python, medium+ severity
gosec -fmt sarif -out gosec.sarif ./...                                 # Go
brakeman -o brakeman.json                                               # Ruby on Rails
npx eslint .                                                            # with eslint-plugin-security's recommended config enabled
cargo clippy -- -W clippy::undocumented_unsafe_blocks -W clippy::unwrap_used
```
JVM: SpotBugs with the FindSecBugs plugin. Infrastructure: `trivy config .`, `checkov -d infra/`,
`hadolint Dockerfile`, `kube-linter lint k8s/`.

Triage each SARIF result into: true positive (finding), false positive (reason: not reachable,
sanitized at X, constant input), or needs runtime check (route to `tester`). Keep the dismissal list.

## Dependency vulnerabilities (SCA)

| Ecosystem | Command | Notes |
|---|---|---|
| Multi | `osv-scanner scan source -r .` (v2; v1 used `osv-scanner -r .`) | Uses lockfiles; OSV database |
| Multi | `trivy fs --scanners vuln .` | Also images: `trivy image <ref>` |
| Multi | `syft dir:. -o cyclonedx-json > sbom.json && grype sbom:sbom.json` | SBOM then match |
| Go | `govulncheck ./...` | Reports only vulnerabilities in functions actually called |
| Rust | `cargo audit`; `cargo deny check advisories bans licenses sources` | deny also enforces license and source policy |
| Python | `pip-audit -r requirements.txt` or in the active environment | Supports `--fix` for upgrades |
| JS | `npm audit --omit=dev`, `pnpm audit --prod`, `yarn npm audit` | Dev-only vulnerabilities rarely matter in production |
| JVM | OWASP Dependency-Check (`mvn org.owasp:dependency-check-maven:check`) | CPE matching produces false positives; verify |

Rating a dependency vulnerability:
1. Is the vulnerable package in the production dependency graph (not dev/test only)?
2. Is the vulnerable function or feature used? (`govulncheck` does this for Go; elsewhere grep for the
   API named in the advisory.)
3. Is the input reaching it attacker-controlled?
4. Is there a fixed version, and does upgrading break compatibility (major version)?
Report as: package, installed version, advisory ID (GHSA/CVE/RUSTSEC/GO-), fixed version, reachable
(yes/no/unknown with reason), recommended action.

## New dependency review

- [ ] Purpose cannot be met with the standard library or an existing dependency in a few lines.
- [ ] Maintenance: recent releases, multiple maintainers or a backing organization, issues triaged.
- [ ] Popularity relative to name: typosquats mimic popular names (`reqeusts`, `colourama`); check the
      registry page and repository link match.
- [ ] Install-time code: npm `preinstall`/`install`/`postinstall` scripts, Python `setup.py` builds
      (prefer wheels), Rust `build.rs`, Go `//go:generate` (not run on install). Inspect with
      `npm install --ignore-scripts` or `npm pack` and read the tarball.
- [ ] Transitive footprint: `npm ls --all`, `cargo tree`, `pipdeptree`, `go mod graph`.
- [ ] License compatible with the project's distribution model.
- [ ] Provenance and signatures where available (npm provenance attestations, Sigstore, Maven Central
      signatures), and lockfile integrity hashes committed (`package-lock.json` `integrity`,
      `pip install --require-hashes`, `Cargo.lock`, `go.sum`).
- [ ] Dependency confusion: internal package names reserved or scoped; registry configuration pins
      scopes to the internal registry.

## CI/CD (GitHub Actions focus)

```bash
zizmor .github/workflows/            # security audit of workflows
actionlint                           # correctness, including expression injection hints
```
Checklist:
- [ ] Third-party actions pinned to full commit SHA (tags are mutable); Dependabot/Renovate keeps pins fresh.
- [ ] Top-level `permissions: {}` or `contents: read`; jobs request only what they need.
- [ ] No untrusted context (`github.event.issue.title`, `github.event.pull_request.head.ref`,
      `github.head_ref`, comment bodies) interpolated into `run:`; pass via `env:` and quote.
- [ ] `pull_request_target` and `workflow_run` workflows do not check out and execute PR code with
      secrets or write tokens.
- [ ] Secrets scoped to environments with required reviewers for deploys; OIDC federation to clouds
      instead of long-lived cloud keys.
- [ ] Self-hosted runners not used for public-fork PRs; ephemeral runners preferred.
- [ ] Caches and artifacts: untrusted jobs cannot poison caches used by release jobs.
- [ ] Release artifacts built in CI, signed, with provenance (SLSA build level appropriate to risk).

## Containers and infrastructure

- Base images pinned by digest, minimal (distroless/alpine/wolfi), rebuilt regularly; non-root user;
  no secrets in layers (`docker history`), multi-stage builds.
- Kubernetes: no privileged pods, `readOnlyRootFilesystem`, dropped capabilities, resource limits,
  network policies, secrets not in plain ConfigMaps, service account tokens not auto-mounted when unused.
- Cloud IAM: least privilege, no wildcard `*` actions on sensitive services, no public storage buckets,
  encryption at rest, logging enabled.
- Terraform: review `plan` output for public exposure (security groups `0.0.0.0/0` on admin ports,
  public IPs, bucket ACLs).

## Secret scanning

```bash
gitleaks git --redact -v                 # git history (gitleaks 8.19+; older: gitleaks detect --redact -v)
gitleaks dir --redact path/              # a directory without git
trufflehog git file://. --no-verification
trufflehog filesystem path/ --no-verification
trivy fs --scanners secret .
```
Use `--no-verification` (or equivalent) always: verification sends the found secret to its provider.
