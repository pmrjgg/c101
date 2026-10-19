# Jina MCP reference

Server: `jina` (hosted, `https://mcp.jina.ai/v1`). Schemas verified against `jina-ai/MCP` source,
October 2026. Server-side options (`max_tokens`, `include_tools`, `exclude_tools`, tags) are fixed in
the endpoint URL by `.mcp.json`; agents cannot change them per call.

## Search tools

| Tool | Params | Key? |
|---|---|---|
| `search_web` | `query` (string or array of 1-5), `num` (1-10, default 10), `tbs`, `location`, `gl`, `hl` | yes |
| `search_arxiv` | `query` (string or array of 1-5), `num` (1-10), `tbs` | yes |
| `search_ssrn` | `query` (string or array of 1-5), `num` (1-10), `tbs` | yes |
| `search_images` | `query` (single string), `num`, `return_url` (default false), `tbs`, `location`, `gl`, `hl` | yes |
| `search_jina_blog` | Jina's own blog; not useful for general research | no |

- `tbs`: Google-style time filter: `qdr:h`, `qdr:d`, `qdr:w`, `qdr:m`, `qdr:y`.
- `gl`: country code for results (`us`, `de`, `jp`); `hl`: interface language (`en`, `de`);
  `location`: free-text location for local results.
- An array of queries returns grouped results per query: dedup across groups before triage.

## Read tools

### read_url

| Param | Notes |
|---|---|
| `url` | string or array of 1-5 URLs |
| `question` | switches output from full page to the top passages answering it |
| `chunk_size` | words per passage, 1-4096, default 100 (with `question`) |
| `topk` | passages returned, 1-50, default 1 (with `question`) |
| `withAllLinks` | append every link on the page (link maps, pagination discovery) |
| `withAllImages` | append image URLs |
| `ocr` | OCR a scanned PDF; requires `page` |
| `page` | page number for OCR, default 1, one page per call |

Time budget: 30 s for a plain read, 60 s for a question-scoped read. Works without a key at low rate
limits. Typical settings:
- Triage a long page: `question: "<sub-question>", topk: 3, chunk_size: 150`.
- Full read for citation: no `question`; one or two URLs per call to stay under the output cap.
- PDF: `read_url` on the PDF URL; for arXiv prefer `https://arxiv.org/abs/<id>` for metadata and
  `https://arxiv.org/html/<id>` (when it exists) or `/pdf/<id>` for text.

### extract_pdf
`id` (arXiv id) or `url` (one is required), `type` (comma list of `figure`, `table`, `equation`),
`max_edge` (image size, default 1024). Use for tables and equations a text read garbles.

### capture_screenshot_url
`url`, `firstScreenOnly` (default false = full page), `return_url` (return a hosted URL instead of
image data). Use for visual checks and for evidence that a page showed something at a time.

### guess_datetime_url
`url`. Returns an estimated published or updated datetime with a confidence. Record both; below
moderate confidence, corroborate with page metadata or `curl -sI` Last-Modified.

### primer
No params. Current time and context; use it for as-of stamps when Bash is unavailable.

## Utility tools

| Tool | Params | Use |
|---|---|---|
| `sort_by_relevance` | `query`, `documents` (1-1024 strings), `top_n` | rerank candidate sources: pass `"title - snippet - domain"` strings, keep the index mapping |
| `deduplicate_strings` | `strings` (1-1000), `k` (must be at most the number of strings) | top-k semantically unique strings: collapse syndicated titles or near-duplicate claims |

Dedup pattern: set `k` to roughly the number of distinct items you expect (for 60 titles, start at
k = 30); compare which inputs were dropped; if two distinct items were merged, raise k.
