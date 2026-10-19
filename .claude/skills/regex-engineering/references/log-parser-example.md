# Worked example: log-line parser in Python and Go

Full code for `regex-engineering` section 12. Both suites read the same `cases.json`; both pass all 12
rows plus the linear-time checks (verified with Python 3.13 + pytest 9 and Go 1.27).

## Shared table: `cases.json`

Each row is `[line, expected]`; `expected` is `null` for "must not match".

```json
[
 ["2026-10-19T08:15:02.123Z INFO [req=7f3a9c] user login ok", {"ts":"2026-10-19T08:15:02.123Z","level":"INFO","req":"7f3a9c","msg":"user login ok"}],
 ["2026-10-19T08:15:02Z WARN disk 91% full", {"ts":"2026-10-19T08:15:02Z","level":"WARN","req":null,"msg":"disk 91% full"}],
 ["2026-10-19T08:15:02.123456+02:00 ERROR [req=a-1] upstream 503", {"ts":"2026-10-19T08:15:02.123456+02:00","level":"ERROR","req":"a-1","msg":"upstream 503"}],
 ["2026-10-19T08:15:02Z INFO [cache] warmed in 3 ms", {"ts":"2026-10-19T08:15:02Z","level":"INFO","req":null,"msg":"[cache] warmed in 3 ms"}],
 ["2026-10-19T08:15:02Z DEBUG [req=abc] [req=def] echoed", {"ts":"2026-10-19T08:15:02Z","level":"DEBUG","req":"abc","msg":"[req=def] echoed"}],
 ["2026-10-19T08:15:02Z INFO [req=] boot", null],
 ["2026-10-19T08:15:02Z INFO [req=abc]", null],
 ["2026-10-19T08:15:02Z info lowercase level", null],
 ["2026-10-19T08:15:02Z NOTICE unknown level", null],
 ["INFO no timestamp", null],
 ["2026-10-19T08:15:02Z INFO trailing newline\n", null],
 ["٢٠٢٦-10-19T08:15:02Z INFO arabic-indic year", null]
]
```

## Python: `logline.py`

```python
import re

LOG_LINE = re.compile(
    r"""
    (?P<ts>
        [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}  # date T time, ASCII digits only
        (?:\.[0-9]{1,9})?                                      # optional fraction
        (?:Z|[+-][0-9]{2}:[0-9]{2})                            # UTC or offset
    )
    \x20(?P<level>TRACE|DEBUG|INFO|WARN|ERROR|FATAL)
    \x20(?:
        \[req=(?P<req>[A-Za-z0-9-]{1,64})\]\x20                # a valid request tag
      | (?!\[req=)                                             # or no tag at all
    )
    (?P<msg>\S.*)                                              # rest of line, starts non-blank
    """,
    re.VERBOSE,
)


def parse(line: str) -> dict | None:
    m = LOG_LINE.fullmatch(line)
    return m.groupdict() if m else None
```

## Python tests: `test_logline.py`

```python
import json, pathlib, time
import pytest
from logline import LOG_LINE, parse

CASES = json.loads(pathlib.Path(__file__).with_name("cases.json").read_text())

@pytest.mark.parametrize("line,expected", CASES)
def test_table(line, expected):
    assert parse(line) == expected

ADVERSARIAL = [
    "2026-10-19T08:15:02Z INFO " + "[req=" * 10_000,
    "2026-10-19T08:15:02." + "1" * 50_000,
    "2026-10-19T08:15:02Z INFO " + " " * 50_000 + "!",
    "0" * 50_000,
    "2026-10-19T08:15:02Z INFO x" + "\n" * 50_000,
]

@pytest.mark.parametrize("payload", ADVERSARIAL)
def test_linear_time(payload):
    t0 = time.perf_counter()
    for _ in range(10):
        parse(payload)
    assert (time.perf_counter() - t0) / 10 < 0.1
```

Run: `uv run --with pytest pytest -q test_logline.py` (17 tests: 12 table rows + 5 timing rows).
ReDoS scan: `uvx --from regexploit regexploit-py .` (no findings).

## Go: `logline.go`

```go
package logline

import "regexp"

// logLine is the RE2 port of the Python LOG_LINE pattern. RE2 has no lookahead,
// so the "(?!\[req=)" branch becomes a capturing branch (badtag) that the
// caller rejects. Go's leftmost-first semantics prefer the valid-tag branch.
var logLine = regexp.MustCompile(`^` +
	`(?P<ts>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}` +
	`(?:\.[0-9]{1,9})?(?:Z|[+-][0-9]{2}:[0-9]{2}))` +
	` (?P<level>TRACE|DEBUG|INFO|WARN|ERROR|FATAL)` +
	` (?:\[req=(?P<req>[A-Za-z0-9-]{1,64})\] |(?P<badtag>\[req=))?` +
	`(?P<msg>\S.*)$`)

var (
	iTS     = logLine.SubexpIndex("ts")
	iLevel  = logLine.SubexpIndex("level")
	iReq    = logLine.SubexpIndex("req")
	iBadTag = logLine.SubexpIndex("badtag")
	iMsg    = logLine.SubexpIndex("msg")
)

type Entry struct {
	TS, Level, Msg string
	Req            *string
}

func Parse(line string) *Entry {
	loc := logLine.FindStringSubmatchIndex(line)
	if loc == nil || loc[2*iBadTag] >= 0 { // no match, or a malformed [req=...] tag
		return nil
	}
	get := func(i int) string { return line[loc[2*i]:loc[2*i+1]] }
	e := &Entry{TS: get(iTS), Level: get(iLevel), Msg: get(iMsg)}
	if loc[2*iReq] >= 0 {
		r := get(iReq)
		e.Req = &r
	}
	return e
}
```

## Go tests: `logline_test.go`

```go
package logline

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"
)

type want struct {
	TS    string  `json:"ts"`
	Level string  `json:"level"`
	Req   *string `json:"req"`
	Msg   string  `json:"msg"`
}

func TestTable(t *testing.T) {
	raw, err := os.ReadFile("cases.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases [][2]json.RawMessage
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	for _, c := range cases {
		var line string
		_ = json.Unmarshal(c[0], &line)
		var w *want
		_ = json.Unmarshal(c[1], &w)
		got := Parse(line)
		switch {
		case w == nil && got != nil:
			t.Errorf("%q: want no match, got %+v", line, got)
		case w != nil && got == nil:
			t.Errorf("%q: want match, got none", line)
		case w != nil:
			if got.TS != w.TS || got.Level != w.Level || got.Msg != w.Msg ||
				(got.Req == nil) != (w.Req == nil) || (got.Req != nil && *got.Req != *w.Req) {
				t.Errorf("%q: got %+v want %+v", line, got, w)
			}
		}
	}
}

func TestLinearTime(t *testing.T) {
	for _, p := range []string{
		"2026-10-19T08:15:02Z INFO " + strings.Repeat("[req=", 10000),
		"2026-10-19T08:15:02." + strings.Repeat("1", 50000),
		strings.Repeat("0", 50000),
	} {
		start := time.Now()
		Parse(p)
		if d := time.Since(start); d > 100*time.Millisecond {
			t.Errorf("took %v", d)
		}
	}
}
```

Run: `go test ./...` with `go.mod` declaring `go 1.22` or later.

## Porting notes

| Python construct | RE2 / Go replacement | Why it is equivalent here |
|---|---|---|
| `(?!\[req=)` as the "no tag" branch | `(?P<badtag>\[req=)` branch + reject when it participated | leftmost-first prefers the valid-tag branch, then `badtag`, then skipping the group; a line whose tag is malformed always takes `badtag` |
| `re.fullmatch` | `^...$` (Go `$` is end of text without `(?m)`) | row 11 (trailing newline) fails in both |
| `re.VERBOSE` with comments | concatenated raw-string pieces | RE2 has no `(?x)` |
| `m.groupdict()` | `FindStringSubmatchIndex` + `SubexpIndex` | indices distinguish "group did not participate" (-1) from "matched empty" |
| `[0-9]` instead of `\d` | same | Python `\d` accepts Arabic-Indic digits (row 12); Go `\d` is ASCII, but writing `[0-9]` keeps both identical |

Other lookaround rewrites that keep RE2 compatibility:

| Lookaround | RE2 approach |
|---|---|
| `foo(?=bar)` (need `foo` only) | match `foo(bar)` and use the first group's span |
| `(?<=\$)\d+` | `\$(\d+)` and take group 1 |
| `^(?!.*secret).*$` (line must not contain) | match `secret` and invert the decision in code |
| `\b(\w+)\s+\1\b` (backreference: doubled word) | tokenize with `\w+` and compare neighbours in code |
| Possessive or atomic groups | unnecessary: RE2 never backtracks |
