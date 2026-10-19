# Exa MCP reference

Server: `exa` (hosted, `https://mcp.exa.ai/mcp?tools=web_search_exa,web_fetch_exa,web_search_advanced_exa,agent_run`).
The `tools=` list in `.mcp.json` replaces Exa's defaults, so only these four tools exist in this stack.
Other Exa tools you may read about (code context, company research, people search, deep researcher
start/check) are NOT enabled here.

Schemas verified against `exa-labs/exa-mcp-server` source, October 2026. "Lenient" numbers and
booleans also accept their string forms.

## web_search_exa

| Param | Type | Notes |
|---|---|---|
| `query` | string, required | Describe the ideal page in natural language. May embed `category:<type>` (company, publication, news, personal site, people) |
| `numResults` | number | default 10 |

Returns titles, URLs and clean content. Search type (auto/fast/instant) is a server setting, not a
call parameter.

## web_fetch_exa

| Param | Type | Notes |
|---|---|---|
| `urls` | string array, required | Batch several URLs in one call. A single string is wrapped into an array |
| `maxCharacters` | positive number | per page; default 3000. Raise to 15000-30000 for full articles, mind the 40k-token MCP cap |

## web_search_advanced_exa

| Param | Type | Notes |
|---|---|---|
| `query` | string, required | |
| `numResults` | number | 1-100, default 10 |
| `type` | `auto` / `fast` / `instant` | default `auto`; `fast`/`instant` trade recall for latency |
| `category` | `company`, `publication`, `news`, `pdf`, `github`, `personal site`, `people`, `financial report` | one category |
| `includeDomains` / `excludeDomains` | string arrays | bare domains, e.g. `"arxiv.org"` |
| `startPublishedDate` / `endPublishedDate` | `YYYY-MM-DD` | published window |
| `startCrawlDate` / `endCrawlDate` | `YYYY-MM-DD` | when Exa crawled it; useful for "new on the web since" |
| `includeText` | string array | results must contain ALL strings |
| `excludeText` | string array | results must contain NONE |
| `userLocation` | two-letter country code | geo-targeting |
| `moderation` | boolean | filter unsafe content |
| `additionalQueries` | string array | extra phrasings run inside the same request |
| `textMaxCharacters` | positive number | page text returned per result |
| `contextMaxCharacters` | positive number | combined context string (off by default) |
| `enableSummary` + `summaryQuery` | boolean + string | per-result summary focused on `summaryQuery` |
| `enableHighlights` + `highlightsQuery` + `highlightsMaxCharacters` | boolean + string + number | query-relevant excerpts; `highlightsNumSentences`/`highlightsPerUrl` are deprecated |
| `maxAgeHours` | number | max cache age; `0` forces a fresh fetch |
| `livecrawlTimeout` | number (ms) | timeout for fresh fetches |
| `subpages` | number 1-10 | also crawl subpages of each result (cost multiplier) |
| `subpageTarget` | string array | keywords that pick which subpages |

### Recipes

```json
{"query": "Official changelog entry announcing deprecation of the v1 REST API",
 "includeDomains": ["docs.example.com", "github.com"], "includeText": ["deprecat"],
 "startPublishedDate": "2025-01-01", "enableHighlights": true,
 "highlightsQuery": "deprecation date and migration deadline", "numResults": 8}
```

```json
{"query": "Peer-reviewed or preprint paper evaluating speculative decoding speedups on large language models",
 "category": "publication", "startPublishedDate": "2025-01-01", "numResults": 15,
 "additionalQueries": ["draft model verification decoding speedup LLM", "Medusa EAGLE lookahead decoding comparison"]}
```

```json
{"query": "Engineering blog post with production numbers on migrating from Elasticsearch to OpenSearch",
 "excludeDomains": ["elastic.co", "opensearch.org", "aws.amazon.com"], "textMaxCharacters": 4000}
```

Summaries and highlights are Exa-generated condensations: good for triage, not citable as the
source's words. Quote only from text you read verbatim.

## agent_run

Asynchronous research agent. Use for list-building, entity enrichment and multi-step lookups whose
output fits a JSON schema. Treat its output as leads: cite the underlying URLs after you have read
them, never "according to Exa Agent".

| Param | Type | Notes |
|---|---|---|
| `query` | string | the objective, plain language. Give `query` OR `runId`, never both |
| `runId` | string starting `agent_run_` | resume or poll an existing run; must be the ONLY field |
| `systemPrompt` | string | guidance on how to research or judge |
| `outputSchema` | JSON Schema object | prefer a top-level object, bounded arrays (`maxItems`), and a `source_url`/evidence field per row |
| `input.data` | array of records | rows or entities to enrich |
| `input.exclusion` | array of records | entities not to return again (use for pagination across runs) |
| `dataSources` | up to 5 `{provider}` | Exa Connect providers: `fiber`, `financial_datasets`, `similarweb`, `baselayer`, `affiliate`, `particle`, `jinko` (availability depends on the account) |
| `previousRunId` | string `agent_run_...` | build on a completed run |
| `effort` | `minimal`, `low`, `medium`, `high`, `xhigh`, `auto` | default `low` on a new query |

Lifecycle:
1. Call with `query` (+ schema, effort). A call waits up to about 750 s.
2. `status: "running"`, `outputReady: false` plus an id: call again with `{runId: "<id>"}` only.
   An interrupted call is not a cancellation; the run continues and keeps billing.
3. `completed` returns output, usage and cost. `failed` returns an error. `cancelled` only if asked.
4. If the call errors before any run id came back, a retry may start a duplicate run: check with the
   caller before retrying a high-effort run.

Enrichment pattern:

```json
{"query": "For each company, find the year founded and current CEO with a source URL",
 "input": {"data": [{"name": "Acme Robotics"}, {"name": "Globex Analytics"}]},
 "outputSchema": {"type": "object", "properties": {"rows": {"type": "array", "maxItems": 50,
   "items": {"type": "object", "required": ["name", "source_url"], "properties": {
     "name": {"type": "string"}, "founded": {"type": "integer"}, "ceo": {"type": "string"},
     "source_url": {"type": "string"}}}}}},
 "effort": "medium"}
```

Verification after any agent_run: sample at least 3 rows (or 10%, whichever is larger), read each
`source_url`, compare. Any mismatch: verify every row, or drop the field.
