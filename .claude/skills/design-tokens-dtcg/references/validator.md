# Token validator (stdlib Python)

Copy the script into your out_dir (or `tools/` in the token repo) and run it with
`python3 -I validate_tokens.py tokens/`. It needs no packages. Tested on the worked example of
SKILL.md section 10 and on a deliberately broken fixture (12 errors found, listed below).

## Directory convention

```
tokens/
  primitive.tokens.json          shared by every mode (several primitive*.tokens.json files are merged)
  semantic.light.tokens.json     one semantic file per mode; identical token names in each
  semantic.dark.tokens.json
  component.tokens.json          aliases of semantics only
  contrast-pairs.json            the pairs that must pass, per mode
```

`contrast-pairs.json` (the minimum is the WCAG 2.x ratio for the pair's use: 4.5 text, 3.0 large
text and non-text, 7.0 AAA text):

```json
[
  { "fg": "color.text.default",   "bg": "color.bg.surface",  "min": 4.5, "use": "body text" },
  { "fg": "color.accent.fg",      "bg": "color.bg.surface",  "min": 4.5, "use": "links, accent text" },
  { "fg": "color.accent.on-fill", "bg": "color.accent.fill", "min": 4.5, "use": "16 px button label" }
]
```

## Output on the broken fixture

```
ERROR color.blue.600: colour is a string '#2563eb'; 2025.10 expects {colorSpace, components}
ERROR [light] color.loopA: cycle color.loopA -> color.loopB -> color.loopA
ERROR space.4: dimension must be {value, unit in ['px', 'rem']}, got '16px'
ERROR space.x: dimension must be {value, unit in ['px', 'rem']}, got {'value': 16}
ERROR motion.ease: cubicBezier needs [x1, y1, x2, y2] with x in [0, 1]
ERROR [light] font.size: no $type (own, group or alias target)
ERROR [light] color.action.primary-bg (semantic) aliases higher tier button.bg (component)
ERROR [light] color.text.link: $type dimension but alias chain ends in color
ERROR [light] color.text.gone: missing target {color.nope}
ERROR [light] button.bg: component skips the semantic tier -> color.blue.600
ERROR [light] color.action.primaryBg and color.action.primary-bg both become --color-action-primary-bg
```

## What `--emit-css` produces

A preview stylesheet for mockups and quick checks (real builds use Style Dictionary or Terrazzo):
primitives on `:root`; base-mode semantics and component aliases on `:root, [data-theme]`; every
other mode on `[data-theme="<mode>"]`; the `dark` mode also under
`@media (prefers-color-scheme: dark) { :root:not([data-theme]) { ... } }`. `--prefix ds` turns
`--color-x` into `--ds-color-x`. Composite values become CSS: typography as the `font` shorthand
(letterSpacing has no slot there, add it separately), shadows as `x y blur spread color`, fontWeight
aliases as numbers, srgb colours with alpha as `color(srgb r g b / a)`.

## Limits

- Converts `srgb`, `oklch`, `oklab` and hex fallbacks to sRGB for contrast; other colour spaces
  need a `hex` fallback or are reported.
- Does not follow `$extends` or `$ref` pointers and does not read resolver documents. Keep the
  per-mode files as the source and let the resolver reference them (SKILL.md section 4 does
  exactly that), so the same files feed the validator and the resolver.
- Group-level `$deprecated` is not inherited by the tokens inside the group.

## Source

```python
"""validate_tokens.py - stdlib validator for a DTCG 2025.10 token directory.

Layout convention (one directory):
  primitive*.tokens.json        tier "primitive" (shared by every mode)
  semantic.<mode>.tokens.json   tier "semantic", one file per mode (light, dark, hc, ...)
  component*.tokens.json        tier "component" (shared by every mode)
  contrast-pairs.json           [{"fg": "color.text.default", "bg": "color.bg.surface", "min": 4.5, "use": "body"}]

Run: python3 -I validate_tokens.py tokens/ [--emit-css out.css] [--prefix ds]
Exit 1 on any error. Warnings do not fail the run.
"""
import glob
import json
import math
import os
import re
import sys

COLOR_SPACES = {"srgb", "srgb-linear", "hsl", "hwb", "lab", "lch", "oklab", "oklch", "display-p3",
                "a98-rgb", "prophoto-rgb", "rec2020", "xyz-d65", "xyz-d50"}
DIM_UNITS, DUR_UNITS = {"px", "rem"}, {"ms", "s"}
ALIAS = re.compile(r"^\{([^{}]+)\}$")
TIER_RANK = {"primitive": 0, "semantic": 1, "component": 2}
errors, warnings = [], []


def flatten(node, path, tier, src, out, inherited=None):
    gtype = node.get("$type", inherited)
    for key, child in node.items():
        if key.startswith("$") and key != "$root":
            continue
        if not isinstance(child, dict):
            errors.append("%s: %s is not an object" % (src, ".".join(path + [key])))
            continue
        if key != "$root" and any(c in key for c in "{}."):
            errors.append("%s: illegal character in name %r" % (src, key))
        p = path + [key]
        if "$value" in child:
            out[".".join(p)] = {"value": child["$value"], "type": child.get("$type", gtype),
                                "tier": tier, "src": src, "deprecated": child.get("$deprecated")}
        else:
            flatten(child, p, tier, src, out, gtype)


def load(paths, tier, out):
    for f in paths:
        with open(f, encoding="utf-8") as fh:
            flatten(json.load(fh), [], tier, os.path.basename(f), out)


def resolve(name, toks, seen=()):
    """Return (final token, chain). Raises ValueError on missing target or cycle."""
    if name in seen:
        raise ValueError("cycle " + " -> ".join(seen + (name,)))
    if name not in toks:
        raise ValueError("missing target {%s}" % name)
    v = toks[name]["value"]
    m = ALIAS.match(v) if isinstance(v, str) else None
    return resolve(m.group(1), toks, seen + (name,)) if m else (toks[name], seen + (name,))


def lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def to_srgb(v):
    """Return (r, g, b) in 0..1 and an in-gamut flag, for srgb, oklch or oklab values."""
    if isinstance(v, str):
        h = v.lstrip("#")
        return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)], True
    cs, comp = v.get("colorSpace"), v.get("components")
    if cs == "srgb":
        return list(comp), all(0 <= c <= 1 for c in comp)
    if cs in ("oklch", "oklab"):
        L, a, b = comp if cs == "oklab" else (comp[0], comp[1] * math.cos(math.radians(comp[2])),
                                              comp[1] * math.sin(math.radians(comp[2])))
        l, m, s = ((L + 0.3963377774 * a + 0.2158037573 * b) ** 3,
                   (L - 0.1055613458 * a - 0.0638541728 * b) ** 3,
                   (L - 0.0894841775 * a - 1.2914855480 * b) ** 3)
        rl = [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
              -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
              -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s]
        ok = all(-1e-4 <= c <= 1 + 1e-4 for c in rl)
        enc = [12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
               for c in (min(max(x, 0.0), 1.0) for x in rl)]
        return [round(c * 255) / 255 for c in enc], ok      # measure the 8-bit colour that is drawn
    if v.get("hex"):
        return to_srgb(v["hex"])[0], True
    raise ValueError("no sRGB conversion for colorSpace %r and no hex fallback" % cs)


def lum(v):
    r, g, b = map(lin, v)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def check_value(name, t):
    v, typ = t["value"], t["type"]
    if typ == "color":
        if isinstance(v, str):
            errors.append("%s: colour is a string %r; 2025.10 expects {colorSpace, components}" % (name, v))
        elif v.get("colorSpace") not in COLOR_SPACES or len(v.get("components", [])) != 3:
            errors.append("%s: bad colour object %r" % (name, v))
    elif typ in ("dimension", "duration"):
        units = DIM_UNITS if typ == "dimension" else DUR_UNITS
        if not (isinstance(v, dict) and isinstance(v.get("value"), (int, float)) and v.get("unit") in units):
            errors.append("%s: %s must be {value, unit in %s}, got %r" % (name, typ, sorted(units), v))
    elif typ == "cubicBezier":
        if not (isinstance(v, list) and len(v) == 4 and 0 <= v[0] <= 1 and 0 <= v[2] <= 1):
            errors.append("%s: cubicBezier needs [x1, y1, x2, y2] with x in [0, 1]" % name)
    elif typ == "fontWeight" and isinstance(v, (int, float)) and not 1 <= v <= 1000:
        errors.append("%s: fontWeight out of 1..1000" % name)


def sub_aliases(v):
    """Alias targets used inside composite values (typography, shadow, border, gradient...)."""
    if isinstance(v, dict):
        return [a for x in v.values() for a in sub_aliases(x)]
    if isinstance(v, list):
        return [a for x in v for a in sub_aliases(x)]
    m = ALIAS.match(v) if isinstance(v, str) else None
    return [m.group(1)] if m else []


def validate(toks, label):
    used = set()
    for name, t in toks.items():
        v = t["value"]
        m = ALIAS.match(v) if isinstance(v, str) else None
        if not m:
            for target in sub_aliases(v):
                if target in toks:
                    used.add(target)
                else:
                    errors.append("[%s] %s: missing target {%s} inside composite" % (label, name, target))
        try:
            final, chain = resolve(name, toks)
        except ValueError as e:
            errors.append("[%s] %s: %s" % (label, name, e))
            continue
        used.update(chain[1:])
        if t["type"] is None:
            t["type"] = final["type"]
        if t["type"] is None:
            errors.append("[%s] %s: no $type (own, group or alias target)" % (label, name))
        elif final["type"] != t["type"]:
            errors.append("[%s] %s: $type %s but alias chain ends in %s" % (label, name, t["type"], final["type"]))
        if m:
            target = toks[m.group(1)]
            a, b = TIER_RANK[t["tier"]], TIER_RANK[target["tier"]]
            if b > a:
                errors.append("[%s] %s (%s) aliases higher tier %s (%s)" % (label, name, t["tier"], m.group(1), target["tier"]))
            if t["tier"] == "component" and target["tier"] == "primitive":
                errors.append("[%s] %s: component skips the semantic tier -> %s" % (label, name, m.group(1)))
            if target["deprecated"]:
                warnings.append("[%s] %s aliases deprecated %s" % (label, name, m.group(1)))
        else:
            if t["tier"] != "primitive":
                warnings.append("[%s] %s: literal value in %s tier; alias a primitive" % (label, name, t["tier"]))
            check_value(name, t)
    kebab = {}
    for name in toks:
        k = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name.replace("$root", "")).replace(".", "-").lower().strip("-")
        if k in kebab and kebab[k] != name:
            errors.append("[%s] %s and %s both become --%s" % (label, kebab[k], name, k))
        kebab[k] = name
    for name, t in toks.items():
        if t["tier"] == "primitive" and name not in used:
            warnings.append("[%s] primitive %s is not referenced by any semantic or component token" % (label, name))


def check_pairs(toks, pairs, label):
    rows = []
    for p in pairs:
        try:
            fg, bg = (resolve(p[k], toks)[0]["value"] for k in ("fg", "bg"))
            (f, okf), (b, okb) = to_srgb(fg), to_srgb(bg)
        except (ValueError, KeyError) as e:
            errors.append("[%s] pair %s/%s: %s" % (label, p.get("fg"), p.get("bg"), e))
            continue
        if not (okf and okb):
            warnings.append("[%s] %s/%s: out of sRGB gamut, measured after clipping" % (label, p["fg"], p["bg"]))
        r = contrast(f, b)
        ok = r >= p.get("min", 4.5)
        rows.append("%-6s %-24s on %-22s %6.2f:1  min %.1f  %s" % (label, p["fg"], p["bg"], r, p.get("min", 4.5),
                                                                    "pass" if ok else "FAIL"))
        if not ok:
            errors.append("[%s] contrast %s on %s = %.2f < %.1f" % (label, p["fg"], p["bg"], r, p.get("min", 4.5)))
    return rows


PREFIX = ""


def var_name(name):
    return PREFIX + name.replace(".$root", "").replace(".", "-")


WEIGHTS = {"thin": 100, "hairline": 100, "extra-light": 200, "ultra-light": 200, "light": 300, "normal": 400,
           "regular": 400, "book": 400, "medium": 500, "semi-bold": 600, "demi-bold": 600, "bold": 700,
           "extra-bold": 800, "ultra-bold": 800, "black": 900, "heavy": 900, "extra-black": 950, "ultra-black": 950}


def css_of(v, typ):
    """CSS text for a $value (aliases become var()). Preview quality; real builds use SD or Terrazzo."""
    m = ALIAS.match(v) if isinstance(v, str) else None
    if m:
        return "var(--%s)" % var_name(m.group(1))
    if typ == "color":
        a = "" if v.get("alpha", 1) == 1 else " / %s" % v["alpha"]
        if v["colorSpace"] == "oklch":
            return "oklch(%s %s %s%s)" % (*v["components"], a)
        return v["hex"] if v.get("hex") and not a else "color(%s %s%s)" % (
            v["colorSpace"], " ".join(map(str, v["components"])), a)
    if typ in ("dimension", "duration"):
        return "%s%s" % (v["value"], v["unit"])
    if typ == "cubicBezier":
        return "cubic-bezier(%s)" % ", ".join(map(str, v))
    if typ == "fontFamily":
        return ", ".join('"%s"' % x if " " in x else x for x in ([v] if isinstance(v, str) else v))
    if typ == "fontWeight":
        return str(WEIGHTS.get(v, v))
    if typ == "shadow":
        return ", ".join(("inset " if s.get("inset") else "") + " ".join(
            css_of(s[k], "dimension") for k in ("offsetX", "offsetY", "blur", "spread")) + " " + css_of(s["color"], "color")
            for s in (v if isinstance(v, list) else [v]))
    if typ == "typography":            # font shorthand; letterSpacing has no slot in it
        return "%s %s/%s %s" % (css_of(v["fontWeight"], "fontWeight"), css_of(v["fontSize"], "dimension"),
                                css_of(v["lineHeight"], "number"), css_of(v["fontFamily"], "fontFamily"))
    return str(v)


def css_value(t, toks):
    return css_of(t["value"], t["type"])


def main(argv):
    global PREFIX
    d = argv[0]
    if "--prefix" in argv:
        PREFIX = argv[argv.index("--prefix") + 1].rstrip("-") + "-"
    prim = sorted(glob.glob(os.path.join(d, "primitive*.tokens.json")))
    comp = sorted(glob.glob(os.path.join(d, "component*.tokens.json")))
    modes = {re.match(r"semantic\.(.+)\.tokens\.json", os.path.basename(f)).group(1): f
             for f in sorted(glob.glob(os.path.join(d, "semantic.*.tokens.json")))}
    pairs_f = os.path.join(d, "contrast-pairs.json")
    pairs = json.load(open(pairs_f, encoding="utf-8")) if os.path.exists(pairs_f) else []
    if not modes:
        errors.append("no semantic.<mode>.tokens.json files in %s" % d)
    table, per_mode = [], {}
    for mode, f in modes.items():
        toks = {}
        load(prim, "primitive", toks)
        load([f], "semantic", toks)
        load(comp, "component", toks)
        validate(toks, mode)
        table += check_pairs(toks, pairs, mode)
        per_mode[mode] = toks
    sem = {m: {n for n, t in toks.items() if t["tier"] == "semantic"} for m, toks in per_mode.items()}
    for m in sem:
        for other in sem:
            for missing in sorted(sem[other] - sem[m]):
                errors.append("[%s] semantic %s is defined in mode %s but missing here" % (m, missing, other))
    if "--emit-css" in argv and per_mode:
        out = argv[argv.index("--emit-css") + 1]
        base = "light" if "light" in per_mode else next(iter(per_mode))

        def block(sel, toks, tiers, indent=""):
            body = ["%s  --%s: %s;" % (indent, var_name(n), css_value(t, toks))
                    for n, t in toks.items() if t["tier"] in tiers]
            return ["%s%s {" % (indent, sel)] + body + ["%s}" % indent]
        # Semantic and component aliases are re-declared on every [data-theme] element so that
        # var() chains re-resolve inside themed subtrees (custom properties inherit computed values).
        lines = block(":root", per_mode[base], {"primitive"})
        lines += block(":root, [data-theme]", per_mode[base], {"semantic", "component"})
        for mode, toks in per_mode.items():
            if mode == base:
                continue
            if mode == "dark":
                lines += ["@media (prefers-color-scheme: dark) {"]
                lines += block(":root:not([data-theme])", toks, {"semantic"}, "  ") + ["}"]
            lines += block('[data-theme="%s"]' % mode, toks, {"semantic"})
        open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(table))
    for w in dict.fromkeys(warnings):
        print("WARN ", w)
    for e in dict.fromkeys(errors):
        print("ERROR", e)
    print("%d error(s), %d warning(s)" % (len(set(errors)), len(set(warnings))))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```
