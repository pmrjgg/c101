# Query recipes by domain

Each recipe: where the primary source lives, a keyword pattern (Jina/WebSearch), a neural pattern
(Exa) and pitfalls. Replace `<...>`. Prefer the primary-pinned variant for the final citation even
when a secondary source found it first.

## Software versions, releases, changelogs
- Primary: project release notes, GitHub Releases/tags, the package registry (PyPI, npm, crates.io,
  Maven Central), official docs "What's new".
- Keyword: `"<pkg>" release notes <version>`, `site:github.com/<org>/<repo> releases`,
  `"<pkg>" changelog "breaking"`.
- Neural: `The official release notes page for <pkg> version <N> listing breaking changes`.
- Registry pages are authoritative for "latest version" and release date; blog posts are not.
- Pitfall: docs sites default to "latest"; pin the versioned URL you cite.

## Security advisories
- Primary: NVD (`nvd.nist.gov/vuln/detail/CVE-...`), the vendor advisory, GitHub Security Advisories
  (`github.com/advisories`), OSV (`osv.dev`), CISA KEV catalog for exploitation status.
- Keyword: `"CVE-2026-<n>"`, `"<product>" security advisory <month year>`, `GHSA-<id>`.
- Exa: `includeText: ["CVE-2026-<n>"]` for exact matching.
- Pitfall: CVSS scores differ between NVD and vendor; report both with their source.

## Standards and protocols
- Primary: IETF RFCs (`rfc-editor.org`, `datatracker.ietf.org`), W3C (`w3.org/TR`), WHATWG
  (`*.spec.whatwg.org`), ISO (abstracts only; full text paywalled), IEEE, Unicode, ECMA (`tc39.es`).
- Keyword: `site:rfc-editor.org <topic>`, `"RFC <n>" obsoletes`, `site:datatracker.ietf.org draft <topic>`.
- Pitfall: check "Obsoleted by" / "Updated by" headers; drafts are not standards.

## Law and regulation
- Primary: EUR-Lex (`eur-lex.europa.eu`), `congress.gov`, `federalregister.gov`, `ecfr.gov`,
  `legislation.gov.uk`, national gazettes, regulator sites, court opinions.
- Keyword: `site:eur-lex.europa.eu "<regulation name>" article <n>`, `"<act>" effective date`.
- Pitfall: consolidated versus original text; the effective date differs from the adoption date. Not
  legal advice: report what the text says and its date.

## Companies and finance
- Primary: SEC EDGAR (`sec.gov/cgi-bin/browse-edgar`, full-text search `efts.sec.gov`), Companies
  House, investor-relations pages, annual reports.
- Exa: `category: "financial report"`, `includeDomains: ["sec.gov"]`.
- Pitfall: press-release numbers are often non-GAAP; filings are authoritative. No investment advice.

## Science and medicine
- Primary: the paper (DOI landing page), PubMed (`pubmed.ncbi.nlm.nih.gov`), arXiv/bioRxiv/medRxiv
  (preprints: flag as not peer reviewed), Cochrane reviews, WHO/CDC/EMA/FDA documents.
- Jina `search_arxiv` for CS/physics/math; Exa `category: "publication"`.
- Pitfall: press coverage overstates effect sizes; trace to the paper's own numbers and sample size.

## Official statistics
- Primary: national statistics offices (BLS, Census, Eurostat, ONS, Destatis), World Bank
  (`data.worldbank.org`), OECD (`data.oecd.org`), IMF, UN data.
- Keyword: `site:<office> "<indicator>" <year>`, `filetype:csv <indicator>`.
- Pitfall: revisions; vintage dates; seasonally adjusted versus not. Record table id and vintage.

## Datasets and models
- Primary: Hugging Face Hub, Zenodo, Kaggle, the dataset's paper and data card, GitHub.
- Keyword: `"<dataset>" dataset card license`, `site:huggingface.co/datasets <topic>`.
- Pitfall: licence on the card versus licence of the underlying sources.

## Error messages and debugging
- Keyword: exact error string in quotes, trimmed of paths, ids and line numbers:
  `"error: could not compile" "<crate>"`; add the library version.
- Sources by trust: the project's issue tracker and maintainer replies > official docs > Q&A sites
  > blogs. Check the issue's closing commit or release, not just the thread.
- Exa: `category: "github"`, `includeText: ["<distinct error token>"]`.

## Product and API documentation
- Primary: the vendor docs (versioned), API reference, OpenAPI spec, SDK source.
- Neural: `The API reference page documenting the <endpoint> parameters for <product>`.
- For libraries prefer context7 (`resolve-library-id` then `query-docs`) when your agent has it.

## News and current events
- Exa advanced: `category: "news"`, `startPublishedDate` = the window start, `maxAgeHours` small.
- Jina: `tbs: "qdr:d"` or `"qdr:w"`.
- Corroborate with at least two outlets that do their own reporting (not syndicating one wire story);
  prefer the primary statement (company filing, court docket, agency release) when it exists.
