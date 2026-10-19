# CI workflow and documentation templates

Overflow from SKILL.md sections 6 (API surface and docs) and 8 (CI).

## Docstring with a doctest

````julia
"""
    scale(x, k)

Multiply `x` by `k`.

```jldoctest
julia> scale(2, 3)
6
```
"""
scale(x, k) = x * k
````

## docs/make.jl

```julia
# docs/make.jl
using Documenter, MyPkg
DocMeta.setdocmeta!(MyPkg, :DocTestSetup, :(using MyPkg); recursive = true)
makedocs(; modules = [MyPkg], sitename = "MyPkg.jl",
         pages = ["Home" => "index.md", "API" => "api.md"], checkdocs = :exports)
deploydocs(; repo = "github.com/me/MyPkg.jl.git", devbranch = "main")
```

`makedocs` runs the doctests; `checkdocs = :exports` fails the build when an exported name has
no docstring in the manual.

## .github/workflows/CI.yml

```yaml
# .github/workflows/CI.yml
name: CI
on:
  push: {branches: [main], tags: ['*']}
  pull_request:
jobs:
  test:
    runs-on: ${{ matrix.os }}
    continue-on-error: ${{ matrix.version == 'pre' }}
    strategy:
      fail-fast: false
      matrix:
        version: ['lts', '1', 'pre']        # LTS, latest release, latest prerelease
        os: [ubuntu-latest]
        include:
          - {version: '1', os: macos-latest}
          - {version: '1', os: windows-latest}
    steps:
      - uses: actions/checkout@v4
      - uses: julia-actions/setup-julia@v2
        with: {version: '${{ matrix.version }}'}
      - uses: julia-actions/cache@v2
      - uses: julia-actions/julia-buildpkg@v1
      - uses: julia-actions/julia-runtest@v1
      - uses: julia-actions/julia-processcoverage@v1
      - uses: codecov/codecov-action@v5
        with: {files: lcov.info, token: '${{ secrets.CODECOV_TOKEN }}'}
  docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: julia-actions/setup-julia@v2
        with: {version: '1'}
      - uses: julia-actions/cache@v2
      - uses: julia-actions/julia-docdeploy@v1
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          DOCUMENTER_KEY: ${{ secrets.DOCUMENTER_KEY }}
```

The `pre` entry may fail without failing the workflow (`continue-on-error`); the docs job
deploys from `main` and from tags once the `DOCUMENTER_KEY` deploy-key secret exists.
