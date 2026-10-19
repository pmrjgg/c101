# Update-bot and release-age configurations

Companion to `dependency-upgrades` section 7. Policy encoded below: patch and minor updates batched
weekly, majors one per PR, dev-tool patches automerged on green CI, nothing installed until it is at
least 3 days old, security fixes allowed through faster by explicit exception.

## Renovate (`renovate.json`)

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:recommended"],
  "timezone": "Europe/Lisbon",
  "schedule": ["before 6am on monday"],
  "minimumReleaseAge": "3 days",
  "internalChecksFilter": "strict",
  "dependencyDashboard": true,
  "prConcurrentLimit": 10,
  "lockFileMaintenance": { "enabled": true, "schedule": ["before 6am on the first day of the month"] },
  "packageRules": [
    {
      "description": "Batch non-major updates of production deps (>= 1.0 only: 0.x minors are breaking)",
      "matchDepTypes": ["dependencies"],
      "matchCurrentVersion": ">=1.0.0",
      "matchUpdateTypes": ["minor", "patch"],
      "groupName": "prod non-major"
    },
    {
      "description": "Automerge dev tooling patches and minors on green CI",
      "matchDepTypes": ["devDependencies"],
      "matchCurrentVersion": ">=1.0.0",
      "matchUpdateTypes": ["minor", "patch"],
      "groupName": "dev tooling",
      "automerge": true
    },
    {
      "description": "Majors one by one, with the dashboard approval gate",
      "matchUpdateTypes": ["major"],
      "dependencyDashboardApproval": true
    }
  ]
}
```

- `config:best-practices` extends `config:recommended` and adds, among others, digest pinning for
  Docker and GitHub Actions and `security:minimumReleaseAgeNpm` (3 days for npm).
- `internalChecksFilter: "strict"` keeps branches from being created while `minimumReleaseAge` is
  still pending, instead of opening a PR with a pending status check.
- Security PRs bypass the gate by default: Renovate's `vulnerabilityAlerts` defaults set
  `minimumReleaseAge: null`, `schedule: []` and `prCreation: "immediate"`.
- Validate locally: `npx --package renovate renovate-config-validator renovate.json`.

## Dependabot (`.github/dependabot.yml`)

```yaml
version: 2
updates:
  - package-ecosystem: "npm"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 10
    cooldown:
      default-days: 3
      semver-major-days: 14
      semver-minor-days: 3
      semver-patch-days: 3
    groups:
      dev-tooling:
        dependency-type: "development"
        update-types: ["minor", "patch"]
      prod-non-major:
        dependency-type: "production"
        update-types: ["minor", "patch"]

  - package-ecosystem: "uv"
    directory: "/"
    schedule:
      interval: "weekly"
    cooldown:
      default-days: 3

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "monthly"
```

Cooldown values are days (the documented range is 1-90); semver-specific values apply only to
ecosystems that support semver. Check the current docs for how cooldown interacts with security
updates in your setup.

## pnpm 11+ (`pnpm-workspace.yaml`)

```yaml
packages:
  - "apps/*"
  - "packages/*"
minimumReleaseAge: 4320          # minutes; 3 days (default since pnpm 11: 1440 = 1 day)
minimumReleaseAgeExclude:
  - "@acme/*"                    # our own packages publish and install the same day
allowBuilds:                     # dependency lifecycle scripts run only when listed true
  esbuild: true
  sharp: true
  core-js: false
overrides:
  "postcss@<8.5": "^8.5.0"       # CVE fix in a transitive dep; remove when upstream bumps (#412)
```

Behaviour to expect: setting `minimumReleaseAge` explicitly turns `minimumReleaseAgeStrict` on
(resolution fails instead of falling back to an older version); a lockfile entry younger than the gate
fails `pnpm install --frozen-lockfile` with `ERR_PNPM_MINIMUM_RELEASE_AGE_VIOLATION`; an unreviewed
build script fails install with `ERR_PNPM_IGNORED_BUILDS` while `strictDepBuilds` is true (default).
`pnpm approve-builds` reviews pending packages and writes `allowBuilds` entries.

## npm 11.10+ (`.npmrc`)

```ini
min-release-age=3                 ; days; default null (off)
min-release-age-exclude=@acme/*
ignore-scripts=true               ; only if the project builds nothing natively; otherwise allowlist
```

Do not combine `min-release-age` with `--before` in one invocation.

## Yarn 4.10+ (`.yarnrc.yml`)

```yaml
npmMinimalAgeGate: "3d"           # duration; early 4.10 releases accepted only minutes as a number
npmPreapprovedPackages:
  - "@acme/*"
enableScripts: false
```

## uv (`pyproject.toml`)

```toml
[tool.uv]
exclude-newer = "3 days"                       # also RFC 3339 dates or ISO 8601 durations ("P3D")
exclude-newer-package = { acme-sdk = "24 hours" }   # per-package gate (PACKAGE = date or duration)
```

## Vulnerability exceptions with an expiry

```toml
# osv-scanner.toml
[[IgnoredVulns]]
id = "GHSA-xxxx-xxxx-xxxx"
ignoreUntil = 2026-12-31
reason = "dev-only dependency, never receives untrusted input; revisit when 3.x ships"
```

```toml
# deny.toml (cargo-deny)
[advisories]
ignore = [
  { id = "RUSTSEC-2026-0000", reason = "affected function unused: we never call parse_untrusted (checked 2026-10-19)" },
]
```

```bash
uv audit --ignore-until-fixed GHSA-xxxx-xxxx-xxxx      # ignored only while no fix exists
pip-audit --ignore-vuln GHSA-xxxx-xxxx-xxxx
```

Every exception names the reason, the date checked, and when to revisit; CI fails once `ignoreUntil`
passes, forcing a re-decision.
