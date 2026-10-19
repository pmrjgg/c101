# SVG cleanup reference

## What a clean deliverable looks like

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
     stroke-width="2" stroke-linecap="round" stroke-linejoin="round" role="img" aria-labelledby="ic-cart-title">
  <title id="ic-cart-title">Cart</title>
  <path d="M3 4h2l2.4 10.2a2 2 0 0 0 2 1.6h7.7a2 2 0 0 0 2-1.5L21 8H6.2"/>
  <circle cx="10" cy="20" r="1.5"/>
  <circle cx="17" cy="20" r="1.5"/>
</svg>
```

Properties: SVG namespace only, `viewBox` present, paint inherited from the root, numbers with at
most 1-2 decimals, no editor metadata (except Inkscape layer attributes on a layered deliverable),
no ids except the title (prefixed), no width/height (the
consumer sizes it) unless the brief needs intrinsic size.

## Root attributes policy

| Use | width/height | viewBox | Notes |
|---|---|---|---|
| UI icon (inline or sprite) | omit, or equal to the grid (24) | `0 0 24 24` | Consumers size with CSS; keep stroke-width in grid units |
| Responsive illustration | omit | art bounds | Add `preserveAspectRatio="xMidYMid meet"` (default) |
| Fixed-size asset (email, OG image source) | px values | art bounds | Some clients ignore viewBox scaling |
| Print / plotter / cutter | physical units (`210mm`) | art bounds in mm units | Keep 1 user unit = 1 mm for sanity |

## Safety: what sanitize removes and why

| Construct | Risk |
|---|---|
| `<script>` | Executes when the SVG is opened directly or inlined |
| `on*` attributes (`onload`, `onclick`, ...) | Same, without a script element |
| `<foreignObject>` | Embeds arbitrary HTML |
| `href` / `xlink:href` to `http:`, `https:`, `//`, `file:` | Tracking, mixed content, local file probing |
| `javascript:` hrefs | Script execution on click |
| `<animate>`/`<set>` targeting `href` | Turns a harmless link into `javascript:` at runtime |
| `<style>` with `@import` or `url(http...)` | External loads |
| `<!ENTITY>` declarations | Entity expansion (billion laughs); `check` refuses the file |
| `<metadata>`, editor namespaces (inkscape, sodipodi, sketch, serif, figma) | Bloat and leaked file paths/usernames. Sanitize removes Inkscape layer attributes too: sanitize before layering, never after (see [layers](layers.md)) |

An SVG served through `<img>` cannot run scripts, but inline SVG and direct navigation can.
Sanitise every SVG from a model, a tracer or the web before it reaches a repo.

## Optimisation

Preferred: `mcp__image__svg_optimize {svg_path, precision: 2, output_path?}` (local tool of the
`image` server, always present, free; writes `<name>.min.svg` unless `output_path` is given; it
checks well-formedness, strips comments, metadata and editor data, rounds numbers and adds a
missing viewBox from numeric width/height; it does not remove scripts or event handlers, so
sanitize first). Run it before layering, or confirm afterwards with `svg_layers` that the layers
survived. Local alternative with svgo (needs Node and the caller's approval to fetch it),
pinned to the 3.x line so this config's semantics hold (4.x changed preset defaults):

```js
// svgo.config.mjs
export default {
  multipass: true,
  floatPrecision: 2,
  plugins: [
    { name: 'preset-default', params: { overrides: { removeViewBox: false } } },
    'removeDimensions',          // drop width/height for responsive use; omit this line for fixed-size assets
    'sortAttrs',
  ],
};
```

```bash
npx -y svgo@3 in.svg -o out.svg --config svgo.config.mjs
```

What the optimiser does that matters: path data conversion to relative and shorthand commands,
number rounding, merging paths with identical paint, collapsing useless groups, removing hidden
elements and empty containers. Afterwards run `svgcheck.py check` again; optimisers occasionally
change rendering at very low precision (rounded arc flags, collapsed tiny shapes). Render-check at
512 px after any precision below 2.

## Palette normalisation

1. `svgcheck.py palette file.svg` lists colours by number of uses.
2. Map to exact brand values first: `remap in.svg out.svg --map '#d32f2f=#d42f2e,#1a1a1a=#111111'`.
3. Merge anti-aliasing shades: `--merge D` with RGB euclidean distance D. Rough guide:
   D 10-20 merges shades that differ only by tracing noise; D 24-40 merges visibly similar tones;
   above 50 merges distinct colours (only for deliberate flattening).
4. Cap the palette: `--max-colors K` keeps the K most used colours and maps the rest to the
   nearest kept colour. Run it after `--merge`.
5. Theming: monochrome icons use `currentColor` (`currentcolor` subcommand). Two-tone icons: keep
   one colour as `currentColor` and set the accent as `var(--icon-accent, #e11d48)` by hand.

## Ids

- `prefix-ids` before inlining several SVGs on one page; gradients, clipPaths, masks and `<use>`
  resolve ids document-wide and silently pick the wrong one on collision.
- Duplicate ids inside one file (`check` ERROR) usually come from concatenating files; rename by
  hand with Edit, then re-check dangling references.

## Strokes versus fills

- Icon systems: keep strokes (themeable width, crisp at small sizes); `vector-effect="non-scaling-stroke"`
  when the icon is scaled by transform but stroke width must stay constant.
- Logos and cutter files: convert strokes to filled outlines so rendering never depends on
  stroke support. Inkscape 1.x can do it headless through its `--actions` interface (only when it
  is installed and the caller approves); confirm the action name with
  `inkscape --action-list | grep -i stroke` before scripting it. With an external
  `svg_transform` model configured, ask it for outlines and verify with `svg_inspect` and a render
  ([svg-editing](svg-editing.md) section 5). Never hand-edit path geometry to fake an outline.
- `<text>`: depends on installed fonts. For logos and illustrations, convert text to outlines in a
  design tool; for UI, keep live text outside the SVG.

## Embedding choices

| Method | Scripts run | Styling from page CSS | Notes |
|---|---|---|---|
| `<img src>` / CSS `background` | no | no | Safest; no `currentColor` inheritance |
| Inline `<svg>` | yes | yes | Needs sanitise + prefix-ids; best for icons |
| `<use href="sprite.svg#id">` | no external script | partly (`currentColor` works) | Same-origin sprite files only |

## Fabrication outputs

| Target | Requirements |
|---|---|
| Vinyl / laser cutter | Closed paths, no overlaps (cut-out stacking), fills ignored, units mm, hairline strokes as the tool expects |
| Pen plotter | Strokes only, no fills; order paths to minimise pen travel (tool-specific) |
| Embroidery | Usually a separate digitising step; deliver clean flat-colour SVG with few colours |
| Print | `export_pdf` (vector PDF, layered as OCGs when the SVG has layers; RGB only); CMYK, spot colours and EPS come from a design tool or the print shop |
