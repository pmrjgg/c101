# Spider MCP: search and read tools

Server: `spider` (hosted spider.cloud, `https://mcp.spider.cloud/mcp`). MCP tools accept the same
parameters as the matching Spider API endpoint. Crawling (`spider_crawl`, scoping, budgets, corpora)
lives in the scraping-crawling skill; this file covers the tools a searcher or reader needs.

## Core tools

| Tool | Use | Key params |
|---|---|---|
| `spider_search` | web search, optionally fetching result pages | `search` (required query; `site:`, `intitle:`, `filetype:` work), `search_limit` (results to process), `fetch_page_content` (true = also scrape each result), plus `return_format` |
| `spider_scrape` | one URL to clean content | `url`, `return_format`, `request`, `readability`, `metadata`, `root_selector`, `exclude_selector`, `wait_for`, `cache` |
| `spider_links` | all links on a page or within a small crawl | `url`, `limit`, `depth` |
| `spider_screenshot` | page screenshot | `url` |
| `spider_transform` | HTML you hold to markdown or text | HTML input + `return_format` |
| `spider_get_credits` | remaining credit balance | none |

Common parameter values (Spider API, October 2026):

| Param | Default | Values / notes |
|---|---|---|
| `return_format` | `raw` | `markdown`, `commonmark`, `raw`, `text`, `xml`, `bytes`, `empty`; use `markdown` for reading |
| `request` | `smart` | `smart` picks HTTP or a headless browser per page; a browser mode exists for JS-only pages |
| `readability` | false | Mozilla Readability preprocessing: good for articles, can drop code blocks and tables in docs |
| `filter_output_main_only` | true | strips nav, aside, footer |
| `metadata` | false | title, description, keywords |
| `root_selector` / `exclude_selector` | none | CSS to keep / drop parts of the page |
| `wait_for` | 500 ms network idle | object with `selector`, `delay`, `dom` conditions; capped at 60 s |
| `cache` | true (`maxAge` 48 h) | `false` or `{maxAge: <ms>}` for fresh content |
| `respect_robots` | true | never set to false |
| `request_timeout` | 60 s | 5-255 |

## Remote browser tools (billed while open)

`spider_browser_open` returns a `session_id`; `spider_browser_navigate`, `_click` (`selector`),
`_fill` (`selector`, `value`), `_screenshot`, `_content` (`format: html|text`), `_evaluate`
(`expression`), `_wait_for` all take that `session_id`; `spider_browser_close` ends it.
Limits: 5 concurrent sessions per connection; idle sessions close after 5 minutes but bill until then.
Prefer local Playwright (browser-automation) unless the page needs Spider's network. Always close the
session in the same turn you opened it, including on error paths.

## AI tools

`spider_ai_crawl`, `spider_ai_scrape`, `spider_ai_search`, `spider_ai_browser`, `spider_ai_links`
need an AI subscription on the account. If a call fails with a plan or subscription error, fall back
to `spider_scrape` + your own extraction; do not retry.

## Credits

10,000 credits = US$1. Residential/stealth proxies bill 1.5-2x. Check `spider_get_credits` before and
after a calibration run to measure the real per-page cost.
