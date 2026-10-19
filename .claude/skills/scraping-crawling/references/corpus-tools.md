# Corpus tools

Stdlib-only helpers. Keep them in your scratch or `out_dir`, never inside a downloaded corpus
directory, and run with `python3 -I` so nothing in the corpus can shadow a module.

## Canonical URLs

```python
# canon.py: python3 -I canon.py < urls.txt > canon.tsv   (prints original<TAB>canonical)
import sys
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

DROP = {"gclid", "fbclid", "msclkid", "ref", "ref_src", "mc_cid", "mc_eid", "igshid", "_hsenc", "_hsmi"}

def canon(u: str) -> str:
    s = urlsplit(u.strip())
    host = (s.hostname or "").lower()
    if host.startswith("m.") or host.startswith("amp."):
        host = host.split(".", 1)[1]
    if s.port and s.port not in (80, 443):
        host = f"{host}:{s.port}"
    q = [(k, v) for k, v in parse_qsl(s.query, keep_blank_values=True)
         if not k.lower().startswith("utm_") and k.lower() not in DROP]
    path = s.path or "/"
    if path.endswith("/amp"):
        path = path[:-4] or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return urlunsplit(("https", host, path, urlencode(sorted(q)), ""))

for line in sys.stdin:
    if line.strip():
        print(line.strip(), canon(line), sep="\t")
```

Caveat: some sites treat a trailing slash or query order as meaningful. If a canonicalised URL
returns different content, prefer the page's own `rel=canonical`.

## Content hash and index build

```python
# index.py: python3 -I index.py <corpus_dir>   (rebuilds index.jsonl from pages/*.md)
import hashlib, json, os, re, sys

root = sys.argv[1]
pages = os.path.join(root, "pages")
seen, out = {}, []
for name in sorted(os.listdir(pages)):
    text = open(os.path.join(pages, name), encoding="utf-8").read()
    head, _, body = text.partition("\n---\n") if text.startswith("---") else ("", "", text)
    meta = dict(re.findall(r"^(\w+): (.*)$", head, re.M))
    norm = re.sub(r"\s+", " ", body).strip()
    h = hashlib.sha256(norm.encode()).hexdigest()
    rec = {"id": name.split("-", 1)[0], "url": meta.get("url"), "title": meta.get("title"),
           "path": f"pages/{name}", "fetched_at": meta.get("fetched_at"), "bytes": len(body.encode()),
           "sha256": h, "status": "ok"}
    if h in seen:
        rec["status"] = f"duplicate_of:{seen[h]}"
    else:
        seen[h] = rec["id"]
    out.append(rec)
with open(os.path.join(root, "index.jsonl"), "w", encoding="utf-8") as fh:
    for r in out:
        fh.write(json.dumps(r) + "\n")
dups = sum(1 for r in out if r["status"] != "ok")
print(f"pages: {len(out)} unique: {len(out) - dups} duplicates: {dups}")
```

## Split a spilled crawl result

A crawl result over 50,000 characters arrives as a tool-results file path. Split it without reading
it, then run `index.py`:

```python
# split.py: python3 -I split.py <spilled_result_file> <corpus_dir>   (then run index.py)
import json, os, re, sys
from datetime import datetime, timezone

src, root = sys.argv[1], sys.argv[2]
raw = open(src, encoding="utf-8").read()
try:
    data = json.loads(raw)
except ValueError:
    data = [json.loads(l) for l in raw.splitlines() if l.strip().startswith("{")]
if isinstance(data, dict):
    data = data.get("data") or data.get("results") or data.get("content") or [data]
os.makedirs(os.path.join(root, "pages"), exist_ok=True)
now, n = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), 0
for rec in data:
    body = rec.get("content") or rec.get("markdown") or rec.get("text") or ""
    url = rec.get("url") or ""
    if not body or not url:
        continue
    n += 1
    slug = re.sub(r"[^a-z0-9]+", "-", url.split("://", 1)[-1].lower()).strip("-")[:60]
    with open(os.path.join(root, "pages", f"{n:04d}-{slug}.md"), "w", encoding="utf-8") as fh:
        fh.write(f"---\nurl: {url}\nfetched_at: {now}\ntool: spider_crawl\n---\n{body}\n")
print(f"pages written: {n} of {len(data)} records")
```

## Shell one-liners

```bash
# pages per path prefix from a link list (prioritise the whitelist)
cut -f2 links.tsv | awk -F/ '{print $4"/"$5}' | sort | uniq -c | sort -rn | head -30
# robots.txt rules for all agents
# (field names are case-insensitive, RFC 9309; or use urllib.robotparser under python3 -I)
curl -s https://example.com/robots.txt | tr -d '\r' | awk 'tolower($0) ~ /^user-agent:[ \t]*\*/{f=1;next} tolower($0) ~ /^user-agent:/{f=0} f'
# corpus size and largest pages
du -sh pages && ls -S pages | head -5
# grep the corpus instead of reading it
grep -rln "rate limit" pages | head
```
