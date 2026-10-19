# Primary source catalog

Where the owner of a fact usually publishes it. Pin searches to these with Exa `includeDomains` or
`site:` before accepting a secondary source.

| Domain | Primary sources | Notes |
|---|---|---|
| Software releases | project GitHub Releases/tags, official changelog, package registry (pypi.org, npmjs.com, crates.io, central.sonatype.com, pkg.go.dev, rubygems.org) | registry publish time is authoritative for "released on" |
| Software behaviour | versioned docs, source code at a tagged commit, maintainer comments in the issue tracker | permalink with SHA |
| Security | nvd.nist.gov, vendor advisories, github.com/advisories, osv.dev, CISA KEV | CVSS differs by scorer |
| Internet standards | rfc-editor.org, datatracker.ietf.org, w3.org/TR, spec.whatwg.org, tc39.es, unicode.org | check obsoleted/updated-by |
| Industry standards | iso.org (abstracts), ieee.org, ecma-international.org, NIST publications (csrc.nist.gov) | full ISO text paywalled; cite clause numbers |
| Law (EU) | eur-lex.europa.eu, official journal | consolidated vs original text |
| Law (US) | congress.gov, federalregister.gov, ecfr.gov, govinfo.gov, supremecourt.gov, courtlistener.com | effective vs enacted dates |
| Law (UK) | legislation.gov.uk, judiciary.uk, bailii.org | |
| Companies | sec.gov EDGAR, Companies House, investor-relations pages, annual reports | filings over press releases |
| Science | DOI landing pages (doi.org), publisher sites, PubMed, arXiv, bioRxiv, medRxiv, OpenReview | preprints are not peer reviewed |
| Health | who.int, cdc.gov, ema.europa.eu, fda.gov, nice.org.uk, Cochrane Library | guideline version and date |
| Statistics | national statistics offices (bls.gov, census.gov, ec.europa.eu/eurostat, ons.gov.uk), data.worldbank.org, data.oecd.org, imf.org | vintage and revision |
| Datasets and models | dataset paper + card, huggingface.co, zenodo.org, kaggle.com, the maintainer's repo | licence of card vs sources |
| Cloud and SaaS limits | the provider's quota/limits pages and changelog | region and tier specific |
| People in roles | the organisation's own leadership page, filings, official announcements | high volatility |
| Events and incidents | the organisation's status page, incident postmortem, official statement | update timestamps |

When no primary exists (for example, adoption rates), say so and describe what proxy evidence is
available and its bias.
