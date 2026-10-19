# Migrations and releases

## 1. Tailwind v3 config to v4 CSS-first

1. Branch, commit, then `npx @tailwindcss/upgrade` (needs Node 20+). Review its diff; it rewrites
   templates and moves configuration into CSS.
2. Theme values: `theme.extend.colors.brand[500]` becomes `@theme { --color-brand-500: ...; }`; when
   the values come from tokens, use the `@theme inline` mapping to `--ds-*` variables instead of
   copying values (SKILL.md section 5).
3. A JS config can stay during the transition: `@config "../../tailwind.config.js";` in the CSS.
   `corePlugins`, `safelist` and `separator` are not supported in v4; safelists become
   `@source inline("...")`.
4. `theme(colors.red.500)` in CSS becomes `var(--color-red-500)`; in media queries use
   `theme(--breakpoint-xl)`.
5. The v3 `darkMode` setting becomes `@custom-variant dark (&:where([data-theme=dark], [data-theme=dark] *));`
   (or `(&:where(.dark, .dark *))` for a class).
6. Screenshot-diff key screens before and after the upgrade and note every intended difference.

## 2. SCSS/LESS variables to DTCG

```
python3 -I scss_to_dtcg.py src/styles/_variables.scss > tokens/primitive.tokens.json
skip shadow-card: unsupported value '0 1px 2px rgba(0,0,0,.2)'      <- convert these by hand
```

Then: split the output into tiers (raw palette and scales stay primitive; anything named by role
moves to `semantic.<mode>.tokens.json` as an alias), run the validator, build, and point the old
variables at the new CSS variables for one release (`$color-link: var(--ds-color-accent-fg);`).
Search-and-replace usages per file with review; `$var` arithmetic (`$space-4 * 2`) needs a new token
or `calc()`.

```python
"""scss_to_dtcg.py - convert flat SCSS/LESS variables to a DTCG 2025.10 token file (review the output).

python3 -I scss_to_dtcg.py _variables.scss > primitive.tokens.json
Handles: $name / @name, hex colours, px/rem dimensions, ms/s durations, unitless numbers, font stacks,
references to other variables (become {aliases}), !default. Anything else is reported on stderr.
"""
import json
import re
import sys

DECL = re.compile(r"^\s*[$@]([\w-]+)\s*:\s*(.+?)\s*(!default)?\s*;", re.M)
HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
NUM_UNIT = re.compile(r"^(-?\d*\.?\d+)(px|rem|ms|s)?$")


def path_of(name):
    return name.split("-", 1)[0:1] + ([name.split("-", 1)[1]] if "-" in name else [])


def token(value, names):
    v = value.strip()
    ref = re.fullmatch(r"[$@]([\w-]+)", v)
    if ref:
        if ref.group(1) not in names:
            raise ValueError("unknown reference %s" % v)
        return {"$value": "{%s}" % ".".join(path_of(ref.group(1)))}
    if HEX.match(v):
        h = v[1:] if len(v) == 7 else "".join(c * 2 for c in v[1:])
        comps = [round(int(h[i:i + 2], 16) / 255, 4) for i in (0, 2, 4)]
        return {"$type": "color", "$value": {"colorSpace": "srgb", "components": comps, "hex": "#" + h.lower()}}
    m = NUM_UNIT.match(v)
    if m:
        num, unit = float(m.group(1)), m.group(2)
        num = int(num) if num.is_integer() else num
        if unit in ("px", "rem"):
            return {"$type": "dimension", "$value": {"value": num, "unit": unit}}
        if unit in ("ms", "s"):
            return {"$type": "duration", "$value": {"value": num, "unit": unit}}
        return {"$type": "number", "$value": num}
    if "," in v and "(" not in v and not re.search(r"\d(px|rem|em|%)", v):
        return {"$type": "fontFamily", "$value": [p.strip().strip("'\"") for p in v.split(",")]}
    raise ValueError("unsupported value %r" % v)


def main(path):
    src = open(path, encoding="utf-8").read()
    decls = DECL.findall(src)
    names, out = {n for n, _, _ in decls}, {}
    for name, value, _ in decls:
        try:
            t = token(value, names)
        except ValueError as e:
            print("skip %s: %s" % (name, e), file=sys.stderr)
            continue
        node = out
        *groups, leaf = path_of(name)
        for g in groups:
            node = node.setdefault(g, {})
        node[leaf] = t
    json.dump(out, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main(sys.argv[1])
```

The converter splits names at the first hyphen only (`$color-brand-500` -> `color.brand-500`), so
nothing collides; regroup by hand when you want `color.brand.500`.

## 3. Figma Variables to DTCG

| Figma | DTCG |
|---|---|
| variable collection | a tier (primitives collection, semantic collection) or a resolver set |
| mode (Light, Dark) | `semantic.<mode>.tokens.json` or a resolver context |
| `resolvedType: COLOR` | `color` (Figma stores RGBA 0-1: `colorSpace: "srgb"`, `components` = r, g, b, `alpha` = a) |
| `FLOAT` | `dimension` (`px`) for sizes, radii and spacing; `number` for opacity, line-height multipliers, z |
| `STRING` | `fontFamily` when it is a family; otherwise leave it out of tokens |
| `BOOLEAN` | no DTCG type: keep in `$extensions` or out of tokens |
| value `{"type": "VARIABLE_ALIAS", "id": ...}` | `"{group.token}"` alias (map ids to names first) |
| scopes, code syntax, description | `$extensions["com.figma"]`, `$description` |

Routes, best first:

1. Figma's native DTCG export/import of variables: announced late 2025 and rolling out per
   account; look for it in the Variables panel before using anything else.
2. `npx tz import https://www.figma.com/design/<file-key>/... --o tokens.figma.json`
   (`--unpublished`, `--skip-styles`, `--skip-variables`). Needs `FIGMA_ACCESS_TOKEN` (personal
   access token) or `FIGMA_OAUTH_TOKEN` in the environment: ask the user to export it in their own
   shell; never write the token into a file or a command line that is logged.
3. The Tokens Studio plugin with its DTCG format setting, synced to Git.
4. REST: `GET https://api.figma.com/v1/files/:file_key/variables/local` (all modes; the
   `/variables/published` endpoint omits modes). Enterprise plan, full seat, token scope
   `file_variables:read`; response under `meta.variables` and `meta.variableCollections`, values in
   `valuesByMode`, collections carry `modes` and `defaultModeId`.

After import: run the validator, fix tier violations (Figma files often alias primitives straight
from components), and diff against the code tokens before switching the source of truth.

## 4. Release: diff, changelog, visual regression

```
$ python3 -I token_diff.py tokens@v1/ tokens/ --public-prefix color.
## Tokens (minor)

### Added
- `color.pink.400`
- `color.pink.600`

### Value changed
- `color.accent.fg` (dark) "{color.pink.500}" -> "{color.pink.400}"
- `color.accent.fg` (light) "{color.pink.500}" -> "{color.pink.600}"
- `color.accent.fill` (dark) "{color.pink.500}" -> "{color.pink.600}"
- `color.accent.fill` (light) "{color.pink.500}" -> "{color.pink.600}"
```

`tokens@v1/` is the previous release's token directory (for example a `git worktree add` of the
last tag). Removed or retyped public tokens make the bump major; additions and new deprecations
minor; value changes patch.

```python
"""token_diff.py - classify a token change for semver and print a changelog section.

python3 -I token_diff.py old_tokens_dir new_tokens_dir [--public-prefix color. --public-prefix space.]
Reads every *.tokens.json in each directory (all modes), compares name -> (type, value, deprecated).
"""
import glob
import json
import os
import sys


def flat(node, path=(), gtype=None, out=None, mode=""):
    out = {} if out is None else out
    gtype = node.get("$type", gtype)
    for k, v in node.items():
        if k.startswith("$") and k != "$root" or not isinstance(v, dict):
            continue
        if "$value" in v:
            out[(".".join(path + (k,)), mode)] = (v.get("$type", gtype), json.dumps(v["$value"], sort_keys=True),
                                                  bool(v.get("$deprecated")))
        else:
            flat(v, path + (k,), gtype, out, mode)
    return out


def load(d):
    out = {}
    for f in sorted(glob.glob(os.path.join(d, "*.tokens.json"))):
        mode = os.path.basename(f).split(".")[1] if os.path.basename(f).startswith("semantic.") else ""
        flat(json.load(open(f, encoding="utf-8")), out=out, mode=mode)
    return out


def main(argv):
    old, new = load(argv[0]), load(argv[1])
    prefixes = [argv[i + 1] for i, a in enumerate(argv) if a == "--public-prefix"] or [""]
    public = lambda key: any(key[0].startswith(p) for p in prefixes)
    removed = sorted(k for k in old if k not in new and public(k))
    retyped = sorted(k for k in old if k in new and old[k][0] != new[k][0] and public(k))
    added = sorted(k for k in new if k not in old)
    deprecated = sorted(k for k in new if k in old and new[k][2] and not old[k][2])
    changed = sorted(k for k in new if k in old and old[k][1] != new[k][1] and old[k][0] == new[k][0])
    bump = "major" if removed or retyped else "minor" if added or deprecated else "patch" if changed else "none"
    print("## Tokens (%s)" % bump)
    for title, keys in (("Removed (breaking)", removed), ("Type changed (breaking)", retyped),
                        ("Added", added), ("Deprecated", deprecated), ("Value changed", changed)):
        if keys:
            print("\n### %s" % title)
            for name, mode in keys:
                extra = " %s -> %s" % (old[(name, mode)][1], new[(name, mode)][1]) if title == "Value changed" else ""
                print("- `%s`%s%s" % (name, " (%s)" % mode if mode else "", extra))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

Visual regression after any semantic change (Playwright test runner, `baseURL` set in config):

```ts
// visual/tokens.spec.ts
import { test, expect } from '@playwright/test';

for (const scheme of ['light', 'dark'] as const) {
  test(`settings ${scheme}`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto('/settings');
    await expect(page).toHaveScreenshot(`settings-${scheme}.png`, {
      fullPage: true, animations: 'disabled', maxDiffPixelRatio: 0.01,
    });
  });
}
```

Baselines are created on the first run; after a reviewed, intended change accept them with
`npx playwright test --update-snapshots` (modes `all`, `changed`, `missing`, `none`). Compare
screenshots only from the same OS and browser build; fonts render differently across platforms.

Deprecation window: mark `$deprecated: "Use color.accent.fg"`, keep the token through the next
major, let the validator warn on aliases to deprecated tokens, and grep consumers before removal.
