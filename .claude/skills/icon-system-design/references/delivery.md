# Icon delivery formats

## 1. Individual SVG (source of truth)

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none"
     stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M6 5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v15l-6-4-6 4z"/>
</svg>
```

Checklist: `viewBox="0 0 24 24"`; paints are `currentColor` or `none`; no ids, classes, inline
styles, transforms, editor metadata or embedded rasters; <= 2 decimals; passes
`svgcheck.py check --budget icon`. Filled sets put `fill="currentColor"` on the root and no stroke.

## 2. Symbol sprite

Build (stdlib, from the folder of icons):

```python
import pathlib, re
out = ['<svg xmlns="http://www.w3.org/2000/svg" style="display:none">']
for f in sorted(pathlib.Path("icons").glob("*.svg")):
    body = re.sub(r"(?s)^.*?<svg[^>]*>|</svg>\s*$", "", f.read_text())
    out.append('<symbol id="i-%s" viewBox="0 0 24 24">%s</symbol>' % (f.stem, body.strip()))
out.append("</svg>")
pathlib.Path("dist/icons.svg").write_text("\n".join(out))
```

Use:

```html
<style>
  .icon { width: 24px; height: 24px; fill: none; stroke: currentColor; stroke-width: 2;
          stroke-linecap: round; stroke-linejoin: round; flex: none; }
</style>
<!-- inline sprite at the top of <body>, or same-origin external file -->
<button type="button" aria-label="Delete">
  <svg class="icon" aria-hidden="true"><use href="#i-trash"/></svg>
</button>
<svg class="icon" aria-hidden="true"><use href="/static/icons.svg#i-trash"/></svg>
```

Presentation properties set on the `<svg class="icon">` (or on the symbol) inherit into the
`<use>` content. External sprites only work from the same origin; serve them with a long cache
lifetime and a versioned file name.

## 3. React components with SVGR

```bash
npx @svgr/cli --icon --typescript --jsx-runtime automatic \
  --replace-attr-values '#000=currentColor' --title-prop \
  --out-dir src/icons -- icons/
```

| Flag | Effect |
|---|---|
| `--icon [size]` | replaces width/height with 1em (or the given value): the icon follows font-size |
| `--typescript` | `.tsx` output with typed props |
| `--replace-attr-values old=new` | e.g. hard-coded colours to `currentColor` |
| `--title-prop` | optional `title` prop rendered as `<title>` for meaningful icons |
| `--ref`, `--memo` | forward refs, wrap in React.memo |
| `--filename-case kebab` | output file names (default PascalCase) |
| `--ignore-existing` | keep hand-edited output files |

Usage: `<TrashIcon aria-hidden="true" />` inside a labelled button; `<WarningIcon title="Warning" />`
when the icon itself carries meaning.

## 4. Iconify JSON

```json
{
  "prefix": "acme",
  "width": 24,
  "height": 24,
  "icons": {
    "bookmark": { "body": "<path fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" d=\"M6 5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v15l-6-4-6 4z\"/>" }
  },
  "aliases": { "save-later": { "parent": "bookmark" } }
}
```

`body` is the inner SVG content without the `<svg>` wrapper; root `width`/`height` apply to icons
that do not set their own. Presentation attributes must live in the body (there is no root
`<svg>` to carry them).

## 5. Package and versioning

```text
icons/            source SVGs (24 and 16 px variants)
dist/icons.svg    sprite
dist/react/       SVGR output
dist/iconify.json
icons.meta.json   [{name, variants, sizes, tags, category, since, deprecated?, replacedBy?}]
CHANGELOG.md      added / changed / deprecated / removed per release
```

Semver: MAJOR for renames, removals, grid or stroke changes; MINOR for new icons and variants;
PATCH for path fixes without visible change. Deprecated names stay as aliases for one MAJOR.
