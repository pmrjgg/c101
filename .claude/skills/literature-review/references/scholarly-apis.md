# Scholarly APIs for search and citation chaining

Public HTTP APIs reachable with `curl` from Bash. No keys are configured for these in this stack:
use the unauthenticated tiers politely, back off on HTTP 429, and never add or request keys
yourself. Pipe JSON through `python3 -I -m json.tool` or a small `python3 -I -c` filter; save raw
responses under your `out_dir` when you will reuse them.

Policies change; if a call returns a policy or quota error, record it in Open doubts and fall back
to Jina `search_arxiv` / Exa.

## arXiv API (Atom XML)

```bash
# search: field prefixes ti: abs: au: cat: all: ; boolean AND OR ANDNOT ; URL-encode quotes and spaces
curl -s 'https://export.arxiv.org/api/query?search_query=abs:%22speculative%20decoding%22+AND+cat:cs.CL&start=0&max_results=50&sortBy=submittedDate&sortOrder=descending' -o arxiv.xml
# metadata for known ids (latest version unless vN given)
curl -s 'https://export.arxiv.org/api/query?id_list=1706.03762,2211.17192' -o ids.xml
```

Etiquette: at most one request every 3 seconds; batch ids in `id_list`. Abstract page
`https://arxiv.org/abs/<id>`, HTML full text `https://arxiv.org/html/<id>` (when available), PDF
`https://arxiv.org/pdf/<id>`; append `v<n>` to pin a version.

## Semantic Scholar Graph API (JSON)

```bash
S2=https://api.semanticscholar.org/graph/v1
# keyword search with filters
curl -s "$S2/paper/search?query=kv+cache+compression&year=2024-2026&fields=title,year,venue,externalIds,citationCount&limit=50"
# one paper by external id: arXiv:<id>, DOI:<doi>, CorpusId:<n>, or the S2 paper id
curl -s "$S2/paper/arXiv:1706.03762?fields=title,year,venue,externalIds,citationCount,referenceCount"
# backward chaining (what it cites) and forward chaining (who cites it), paginated with offset
curl -s "$S2/paper/arXiv:1706.03762/references?fields=title,year,externalIds&limit=100&offset=0"
curl -s "$S2/paper/arXiv:1706.03762/citations?fields=title,year,externalIds,citationCount&limit=100&offset=0"
```

Unauthenticated requests share a global pool and are throttled under load: expect 429 and some 500s;
retry with backoff (wait several seconds, at most 3 tries). Request only the fields you need.

## OpenAlex (JSON)

```bash
OA=https://api.openalex.org
# single record by DOI (single-record lookups are free)
curl -s "$OA/works/doi:10.48550/arXiv.1706.03762"
# search with filters (metered: list and search calls consume the small no-key daily allowance)
curl -s "$OA/works?search=kv%20cache%20compression&filter=from_publication_date:2024-01-01,type:article|preprint&per-page=25"
# arXiv records are typed "preprint" in OpenAlex: never filter CS/ML topics on type:article alone
# forward citations of work W<id>; backward = the referenced_works field of the record
curl -s "$OA/works?filter=cites:W2741809807&per-page=50"
```

Since 2026 OpenAlex meters usage: lookups by id are free, list and search calls draw on a small
no-key daily allowance. Prefer single-record lookups and S2 for bulk chaining; if you hit the
allowance (429), stop using OpenAlex for the run and note it.

## Crossref (JSON) for DOI metadata

```bash
curl -s "https://api.crossref.org/works/10.1145/3292500.3330701" | python3 -I -c 'import json,sys; m=json.load(sys.stdin)["message"]; print(m["title"][0], m.get("container-title"), m["issued"]["date-parts"])'
```

Use for authoritative venue, year, volume, pages when building `refs.bib`.

## DOI and id hygiene

- DOI case-insensitive; store lowercase. arXiv DOIs have the form `10.48550/arXiv.<id>`.
- Strip arXiv version suffixes for identity, keep them for citations of specific content.
- One paper can have: arXiv id, DOI of the published version, S2 id, OpenAlex W id, CorpusId. Store
  all on the card; dedup on DOI, then arXiv id, then normalized title + first author + year.

## Small helper: extract titles and ids from an S2 response

```bash
python3 -I -c '
import json,sys
d=json.load(open(sys.argv[1]))
for r in d.get("data",[]):
    p=r.get("citingPaper") or r.get("citedPaper") or r
    ids=p.get("externalIds") or {}
    print(p.get("year"), ids.get("ArXiv") or ids.get("DOI") or "-", p.get("title"), sep="\t")
' citations.json
```
