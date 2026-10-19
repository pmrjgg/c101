# Evidence recipes by deliverable type

How to produce E3-E5 evidence efficiently for each kind of deliverable. Record command, exit code,
revision and the decisive output lines; put long logs in the gate file and cite line anchors.

## Code feature

1. Build and type check: `make build`, `cargo build`, `go build ./...`, `npx tsc --noEmit`, `mvn -q compile`.
2. Targeted tests for each functional criterion: find them (`rg -n "def test_.*json" tests/`) and read
   them; confirm each asserts the criterion's observable outcome. Missing test: write a minimal one under
   `.stack/out/<agent>/` (or ask `tester`).
3. End-to-end check of the main path with the real entry point (CLI invocation, HTTP request against a
   local server with `curl -sS -o /dev/null -w '%{http_code}'`, UI step via `tester` and Playwright).
4. Edge and error criteria: run with an invalid input and assert the documented error and exit code.
5. Diff coverage if the brief sets a threshold: `diff-cover coverage.xml --compare-branch=origin/main`.

## Bug fix

1. Repro script or test from the bug report.
2. Run on the base revision: must FAIL for the reported reason (read the assertion).
3. Run on head: must PASS. For intermittent bugs, repeat per the rule-of-three bound
   (n >= ln(0.05)/ln(1 - p) clean runs for a pre-fix failure rate p).
4. Regression test exists in the suite and is part of the default test command.

## Refactor (behaviour must not change)

1. Full test suite on base and head: identical pass set.
2. Differential run: same inputs through old and new code paths, outputs compared byte-for-byte or
   with a documented tolerance (`diff <(old_cmd) <(new_cmd)`).
3. Public API surface unchanged: compare exported symbols or API docs (`cargo public-api`, `api-extractor`,
   `japicmp`, `go doc` output diff) when available.
4. If the refactor claims metric improvements, re-run the metrics commands (code-quality-metrics) and
   report deltas.

## Performance change

Benchmark both revisions with the same harness and enough samples; compare medians with bootstrap CI
(`performance-optimization` compare script). PASS only when the CI supports the target.

## Documentation

1. Every claim in the docs that describes behaviour is checked against the code or by running the
   documented command (copy-paste the example, run it, compare output).
2. Links resolve (relative links: check files exist; external links: fetch or delegate a quick check).
3. Required sections present (`rg -n "^## " doc.md`); terminology consistent with the code (flag
   names, defaults).

## Research report or analysis

1. Every load-bearing claim has a citation with URL and access date; spot-check at least the top 5
   claims against the sources (or batch them to `fact-checker`).
2. Numbers recomputed where possible (sums, percentages, unit conversions).
3. The question in the brief is answered directly; scope boundaries and uncertainty are stated.
4. Completeness against the brief's sub-questions: one row per sub-question in the matrix.
5. `quality-control` for overall quality and source evaluation when stakes are high.

## UI and visual deliverables

1. Screenshots at each viewport named in the brief (via `tester` with
   `mcp__playwright__browser_resize` and `mcp__playwright__browser_take_screenshot`), saved under
   `.stack/playwright/` and cited.
2. Accessibility snapshot (`mcp__playwright__browser_snapshot`) to confirm labels and roles.
3. Interaction criteria: scripted steps with assertions (element visible, text present, URL after
   submit), not a visual impression.
4. Console errors: `mcp__playwright__browser_console_messages` shows none at error level.

## Data and migrations

1. Run the migration on a copy of realistic data (or a fixture of realistic size); record duration and
   lock behaviour.
2. Row counts and invariants before and after (`SELECT count(*)`, uniqueness, null rates, sums of
   money columns).
3. Down-migration or restore path exercised once when the brief requires reversibility.
4. Application tests run against the migrated schema.

## Infrastructure and configuration

1. `terraform plan` (or equivalent) output reviewed: no unexpected destroy/replace, no public exposure.
2. Config loads and validates at startup (`app --check-config`, `nginx -t`, `docker compose config`,
   `kubectl apply --dry-run=server`).
3. Policy/lint tools clean (`trivy config`, `checkov`, `hadolint`, `actionlint`).

## Agent stack content (this repository)

1. `bin/stack doctor` errors before vs after; zero new errors in changed files
   (`bin/stack doctor 2>&1 | grep -E "<changed paths>"`).
2. Frontmatter keys follow docs/CONVENTIONS.md section 2; `model` equals the tier id in
   config/models.json, and `effort`/`maxTurns` equal its initial values or learned values within
   config/learning.json bounds (drift shows in `bin/stack doctor`; fix with `bin/stack agents tiers
   --apply`, never by hand); skills and color as specified; description is one physical line.
3. Agent bodies contain the required sections in order (`rg -n "^## " <file>`); skills stay under the
   line budget and every `references/` link resolves.
4. Saved workflows: `meta` literal first, no `Date.now()`/`Math.random()`/`new Date()`, every
   `agentType` exists.
5. Referenced agent and skill names exist (`ls .claude/skills`, `bin/stack agents list`).

## Images and generated media

1. File exists, dimensions and format match the brief (`sips -g pixelWidth -g pixelHeight img.png` on
   macOS, `python3 -c` with a header read, or the generator's sidecar metadata).
2. Transparency required: alpha channel present (check mode/sidecar).
3. Content criteria judged by viewing the image (Read the file) against each brief item; text in
   images spelled exactly as specified.
4. Vector output: well-formed XML (`python3 -c "import xml.dom.minidom,sys; xml.dom.minidom.parse(sys.argv[1])" file.svg`),
   `viewBox` present.
