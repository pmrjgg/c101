# Extraction schemas and validation

## Schema template

Write it to `<corpus>/schema.json` before extracting. Every field gets a sibling evidence field so a
reviewer can check any value without re-reading the page.

```json
{
  "record": "conference_talk",
  "key": ["url"],
  "fields": {
    "url":          {"type": "string", "required": true},
    "title":        {"type": "string", "required": true},
    "speakers":     {"type": "array",  "items": "string", "required": true},
    "date":         {"type": "string", "format": "YYYY-MM-DD", "required": false},
    "track":        {"type": "string", "enum": ["research", "industry", "tutorial", null], "required": false},
    "video_url":    {"type": "string", "required": false},
    "abstract_len": {"type": "integer", "required": false, "derived": true}
  },
  "evidence": "each non-null field f (except url and derived fields) has evidence.f = verbatim snippet under 15 words",
  "units": "normalised values go in *_norm fields; raw text kept in *_raw"
}
```

Record example:

```json
{"url": "https://conf.example.org/talks/123", "title": "Lock-free queues in practice",
 "speakers": ["A. Rivera"], "date": "2026-05-14", "track": "industry", "video_url": null,
 "abstract_len": 142,
 "evidence": {"title": "Lock-free queues in practice", "speakers": "Speaker: A. Rivera",
              "date": "Thursday, 14 May 2026", "track": "Industry track"}}
```

## Rules

- `null` when the page does not state it. Never infer a date from a URL unless the brief allows,
  and then mark `date_source: "url"`.
- Keep raw and normalised values separate (`price_raw: "EUR 1.299,00"`, `price_eur: 1299.00`).
- One record per entity, keyed; duplicates resolved by the key, newest `fetched_at` wins.
- Personal data: only fields the brief needs; no emails or phone numbers unless explicitly required
  and lawful.

## Validator (stdlib Python)

Save as `<scratch>/validate.py` and run `python3 -I validate.py schema.json extraction.jsonl`.

```python
import json, random, sys

schema = json.load(open(sys.argv[1]))
fields = schema["fields"]
types = {"string": str, "integer": int, "number": (int, float), "array": list, "boolean": bool}
rows, errors = [], []
for n, line in enumerate(open(sys.argv[2]), 1):
    try:
        r = json.loads(line)
    except ValueError as e:
        errors.append(f"line {n}: bad json {e}")
        continue
    rows.append(r)
    for f, spec in fields.items():
        v = r.get(f)
        if v is None:
            if spec.get("required"):
                errors.append(f"line {n}: missing required {f}")
            continue
        if not isinstance(v, types[spec["type"]]):
            errors.append(f"line {n}: {f} has type {type(v).__name__}")
        if "enum" in spec and v not in spec["enum"]:
            errors.append(f"line {n}: {f}={v!r} not in enum")
        if f != "url" and not spec.get("derived") and f not in (r.get("evidence") or {}):
            errors.append(f"line {n}: {f} has no evidence")
print(f"records: {len(rows)}  errors: {len(errors)}")
for f in fields:
    nulls = sum(1 for r in rows if r.get(f) is None)
    print(f"null-rate {f}: {nulls}/{len(rows)}")
for e in errors[:50]:
    print(e)
random.seed(7)
print("spot-check:", [r.get("url") for r in random.sample(rows, min(5, len(rows)))])
sys.exit(1 if errors else 0)
```

Spot-check: open each sampled URL (or its saved page file) and confirm every non-null field. One
wrong value in the sample: fix the extractor, re-extract everything, re-validate.
