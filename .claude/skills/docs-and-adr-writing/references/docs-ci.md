# Docs CI: configs and workflow

Companion to `docs-and-adr-writing` section 8. The markdownlint-cli2, typos, pytest-markdown-docs,
pydoclint and interrogate configs below were run on the worked example (October 2026); Vale and lychee
settings follow their documentation (not run locally).

## `.markdownlint-cli2.jsonc`

```jsonc
{
  "config": {
    "MD013": { "line_length": 110, "code_blocks": false, "tables": false },  // match the repo's wrap width
    "MD033": { "allowed_elements": ["details", "summary", "br"] }
  },
  "ignores": [".changeset/**", "node_modules/**", ".venv/**", "CHANGELOG.md"]
}
```

Run: `npx markdownlint-cli2 "**/*.md"` (add `--fix` locally for auto-fixable rules). Changeset files
start with front matter and no heading, so MD041 fails on them; ignore the directory rather than
disabling MD041 globally.

## Vale (`.vale.ini` + vocabulary)

```ini
StylesPath = .github/styles
MinAlertLevel = warning
Packages = Google
Vocab = Project

[*.md]
BasedOnStyles = Vale, Google
Google.Will = NO              ; example of turning off one rule with a reason in the PR
```

```text
.github/styles/config/vocabularies/Project/accept.txt   one term per line: retrykit, uv, PostgreSQL
.github/styles/config/vocabularies/Project/reject.txt   terms to flag: simply, obviously
```

`vale sync` downloads `Packages` into `StylesPath` (commit the result or cache it in CI), then
`vale README.md docs/`. Start with `MinAlertLevel = error` on an old repo and tighten over time.

## Spelling: `_typos.toml`

```toml
[default.extend-words]
retrykit = "retrykit"

[files]
extend-exclude = ["*.lock", "CHANGELOG.md", "tests/fixtures/**"]
```

`typos` (exit code 2 on findings, verified), `typos --write-changes` to fix. `codespell -w` is the alternative.

## Links: `lychee.toml`

```toml
exclude = ['^https?://example\.com', '^http://localhost']   # regexes
exclude_path = ['(^|/)node_modules/', '(^|/)\.venv/']          # regexes
accept = ["200..=206", "429"]                                   # strings; ranges allowed
max_concurrency = 16
cache = true
max_cache_age = "1d"
include_fragments = "anchor-only"                               # none | anchor-only | text-only | full
```

PRs: `lychee --offline --no-progress './**/*.md'` checks relative links and anchors without network.
Scheduled job: `lychee --no-progress './**/*.md'` with the cache for external URLs; open an issue on
failure instead of blocking unrelated PRs.

## Python docstrings and executable docs (`pyproject.toml`)

```toml
[tool.pytest.ini_options]
addopts = "--doctest-modules --markdown-docs"
testpaths = ["src", "README.md", "docs"]
pythonpath = ["src"]

[tool.pydoclint]
style = "google"
arg-type-hints-in-docstring = false   # types live in the signature
check-return-types = false

[tool.interrogate]
fail-under = 90
ignore-init-method = true
ignore-private = true
```

## Documentation site builds with warnings as errors

| Generator | Setting / command |
|---|---|
| Sphinx | `sphinx-build -W --keep-going -b html docs docs/_build` (`-n` nitpicky for missing references) |
| MkDocs | `mkdocs build --strict` |
| Docusaurus | `onBrokenLinks: 'throw'` (default) and `onBrokenAnchors: 'throw'`; since v3.9 broken Markdown links are configured with `markdown.hooks.onBrokenMarkdownLinks` |
| TypeDoc | `treatWarningsAsErrors: true` in `typedoc.json` |
| rustdoc | `RUSTDOCFLAGS="-D warnings" cargo doc --no-deps` |
| Javadoc | `-Xdoclint:all -Werror` |

## GitHub Actions workflow (`.github/workflows/docs.yml`)

```yaml
name: docs
on:
  pull_request:
    paths: ["**/*.md", "docs/**", "src/**", "pyproject.toml", ".github/workflows/docs.yml"]
  schedule:
    - cron: "0 5 * * 1"            # weekly external link check
permissions:
  contents: read
jobs:
  docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5             # pin actions to a full commit SHA in production
      - uses: astral-sh/setup-uv@v6
      - name: Executable docs (doctests + README blocks)
        run: uv run --with pytest --with pytest-markdown-docs pytest -q
      - name: Docstrings
        run: |
          uvx pydoclint src
          uvx interrogate -v src
      - name: Markdown lint
        run: npx --yes markdownlint-cli2 "**/*.md"
      - name: Spelling
        run: uvx typos
      - name: Prose
        uses: errata-ai/vale-action@reviewdog
        with:
          files: '["README.md", "docs"]'
      - name: Links (offline on PRs, online on schedule)
        uses: lycheeverse/lychee-action@v2
        with:
          args: >-
            --no-progress
            ${{ github.event_name == 'pull_request' && '--offline' || '--cache --max-cache-age 1d' }}
            './**/*.md'
          fail: true
```

Keep the job under two minutes: doc checks that are slow get skipped by habit. Run the scheduled
external-link job separately if it routinely takes longer.
