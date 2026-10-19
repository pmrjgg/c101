# Spider crawl and scrape parameters

MCP tools take the same parameters as the Spider API endpoint they wrap. Values below are the API
defaults documented by spider.cloud (October 2026). If the MCP rejects a parameter, read the tool
schema in your tool list; do not guess alternatives.

## Scope and size

| Param | Default | Notes |
|---|---|---|
| `url` | required | root URL; comma-separate several roots where the API allows |
| `limit` | 0 (no limit) | max pages per website. ALWAYS set it |
| `depth` | 25 | max link depth (0 = no limit). 2-4 is usual for a section crawl. Not used by scrape |
| `whitelist` | none | regex list: only crawl matching paths |
| `blacklist` | none | regex list: skip matching paths |
| `budget` | none | per-path page caps, e.g. `{"*": 300}`; `{"*": 1}` = root page only |
| `subdomains` | false | include subdomains |
| `tld` | false | include other TLDs of the same name |
| `external_domains` | none | domains treated as the same site; `*` = all (avoid) |
| `sitemap` | false | include URLs from the sitemap |
| `respect_robots` | true | never set false |
| `delay` | 0 | ms between requests, max 60 s; disables concurrency |
| `request_timeout` | 60 | seconds, 5-255 |

## Fetching and rendering

| Param | Default | Notes |
|---|---|---|
| `request` | `smart` | picks HTTP or a headless browser per page; a browser mode exists for JS-only sites |
| `wait_for` | 500 ms network idle | object: `selector`, `delay`, `dom` conditions; capped at 60 s |
| `cache` | true | or `{maxAge: <ms>, allowStale, period, skipBrowser}`; default max age 48 h. `false` for fresh |
| `proxy` | auto | `residential` or `isp`; costs more. Do not use to defeat a deliberate block |
| `stealth` | true | residential pool when standard IPs are blocked; 1.5-2x cost. Always pass `false`: a block is a stop sign (SKILL.md section 2) |
| `country_code` / `locale` | none | geo-specific content (`locale: "en-US"`) |

## Output shaping

| Param | Default | Notes |
|---|---|---|
| `return_format` | `raw` | `markdown`, `commonmark`, `raw`, `text`, `xml`, `bytes`, `empty`; may be an array |
| `readability` | false | Mozilla Readability; articles yes, docs no |
| `filter_output_main_only` | true | drops nav, aside, footer |
| `root_selector` | none | CSS root of the content to keep |
| `exclude_selector` | none | CSS of content to drop |
| `metadata` | false | title, description, keywords |
| `return_page_links` | false | links found on each page (builds the link map during the crawl) |
| `css_extraction_map` | none | per-field CSS/XPath extraction |
| `chunking_alg` | none | e.g. `{"type": "bysentence", "value": 2}` |

## Cost controls

| Param | Notes |
|---|---|
| `max_credits_allowed` | hard cap on credits for the run |
| `max_credits_per_page` | skip pages that would cost more (expensive renders) |

10,000 credits = US$1. Measure real per-page cost with a 5-page calibration (SKILL.md section 3).

## Payload examples

Section crawl of a documentation site (300 pages will exceed the 50,000-character result limit:
the result arrives as a tool-results file path; split it with corpus-tools' splitter, never Read it):

```json
{"url": "https://docs.example.com/", "limit": 300, "depth": 4, "stealth": false,
 "whitelist": ["^https://docs\\.example\\.com/(guide|reference)/"],
 "blacklist": ["\\?", "/print/", "/v[12]/"],
 "return_format": "markdown", "metadata": true, "return_page_links": true,
 "max_credits_allowed": 20000}
```

Polite crawl of a small site:

```json
{"url": "https://small-project.org/", "limit": 60, "depth": 3, "delay": 1500, "stealth": false,
 "return_format": "markdown", "readability": true}
```

Single JS-heavy page, wait for the table:

```json
{"url": "https://example.com/stats", "request": "smart", "stealth": false,
 "wait_for": {"selector": {"selector": "table#results", "timeout": {"secs": 15, "nanos": 0}}},
 "return_format": "markdown", "root_selector": "main"}
```

The exact shape of `wait_for` sub-objects varies by API version; if rejected, fall back to
`{"wait_for": {"delay": {"timeout": {"secs": 3, "nanos": 0}}}}` or use Playwright.

Field extraction with selectors:

```json
{"url": "https://shop.example.com/catalog", "limit": 50, "stealth": false,
 "whitelist": ["/product/"],
 "css_extraction_map": {"/product/": [
   {"name": "title", "selectors": ["h1.product-title"]},
   {"name": "price", "selectors": ["[itemprop=price]"]}]}}
```

Verify the `css_extraction_map` shape against the tool schema on first use with `limit: 2`.
