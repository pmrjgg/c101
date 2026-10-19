---
name: social-asset-kit
description: "Social and marketing asset sets built with the image MCP server: a campaign matrix of placements and sizes, platform safe zones, one master per idea derived by crop or outpaint, typeset text and logo composited over generated art, contrast measured over pixels with solved scrims, batch naming, a manifest, export caps and a kit QA sheet. Load when producing a multi-format campaign, ad set or launch kit."
when_to_use: "Producing or auditing social posts, story or reel covers, OG link images, YouTube thumbnails or IAB display ads in several sizes from one idea; resizing a hero to many placements; a headline over a photo failing contrast; ad file-size caps (150 kB); writing the manifest or contact sheet for a kit; A/B creative variants."
---

# Social asset kit

A kit is done when every cell of the matrix exists at its exact size, every file derives from one
accepted master per idea, text and logo are typeset (never generated), every text box passes
contrast measured over the real pixels, names and manifest agree, exports meet their caps, and
the contact-sheet QA passed.

Deep material: [placements and safe zones](references/placements-and-safe-zones.md) (full size
table, IAB weights, kit JSON template, safe-zone maths) |
[templates and compositing](references/templates-and-compositing.md) (SVG and HTML text
templates, rendering, logo rules, compositing code). Helper: [kitcheck.py](scripts/kitcheck.py),
plus the image skills' `masktool.py` and `imgcheck.py`.

```bash
STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"
PY="$STACK/.venv/bin/python"; KC="$STACK/.claude/skills/social-asset-kit/scripts/kitcheck.py"
MT="$STACK/.claude/skills/image-editing/scripts/masktool.py"; IMG="$STACK/.claude/skills/image-generation/scripts/imgcheck.py"
"$PY" "$KC" --help          # plan, derive, resize, contrast, scrim, export, manifest
```

Shell variables do not persist between Bash calls: repeat these lines in every call.

## 1. Kit matrix

Rows are messages or variants, columns are placements, each cell is one file. Write it as a kit
file before generating anything; `kitcheck` reads it.

| Placement | Aspect | Pixels | Notes |
|---|---|---|---|
| Feed portrait (Instagram, Facebook, LinkedIn) | 4:5 | 1080 x 1350 | Instagram's profile grid shows a centred 3:4 crop (1012 x 1350 of it) since January 2025 |
| Square feed | 1:1 | 1080 x 1080 | grid crop 3:4 = centre 810 x 1080 |
| Story / Reel / Shorts | 9:16 | 1080 x 1920 | platform UI over top and bottom (section 2) |
| Profile-grid tile | 3:4 | 1080 x 1440 | upload 3:4 to fill the tile; otherwise it is a crop check |
| OG / link preview | 1.91:1 | 1200 x 630 | text >= 48 px; some surfaces crop it square |
| YouTube thumbnail | 16:9 | 1280 x 720 | >= 640 px wide, under 2 MB, JPG/PNG/GIF; duration badge bottom right |
| IAB medium rectangle | 6:5 | 300 x 250 | 150 kB initial load |
| IAB leaderboard | 8.1:1 | 728 x 90 | 150 kB |
| IAB wide skyscraper | 1:3.75 | 160 x 600 | 150 kB |
| IAB smartphone banner | 6.4:1 | 320 x 50 | 50 kB |

Platform specs change: before launch have `quick-researcher` confirm each placement against the
platform's own help page and record the check date in the delivery notes (`notes.md` beside the
manifest). Half page, billboard,
portrait and interstitial sizes: [placements and safe zones](references/placements-and-safe-zones.md).

```json
{"campaign": "orbit", "message": "launch", "version": 1,
 "master": {"file": "master.png", "w": 3840, "h": 2160, "focus": [2000, 430, 3300, 1730]},
 "copy": {"headline": "Orbit 2 is here", "sub": "Sync every device in one tap", "cta": "Get Orbit"},
 "alt": "Coral and blue Orbit disc on a navy-to-grey studio gradient",
 "placements": [
  {"name": "square", "w": 1080, "h": 1080, "safe": {"left": 0.125, "right": 0.125}},
  {"name": "story",  "w": 1080, "h": 1920, "fill": 0.74, "anchor": [0.5, 0.64],
   "safe": {"top": 0.14, "bottom": 0.35, "left": 0.06, "right": 0.06}}]}
```

`focus` is the focal box in master pixels (read it off the accepted master); `fill` is the share
of the safe width the focal box should span; `anchor` places its centre inside the safe box.

## 2. Safe zones

| Placement | Keep text, logo, faces and product out of |
|---|---|
| Story / Reel, organic | top ~14% (269 px) and bottom ~20% (384 px) |
| Instagram Stories ad (Meta ads guide, checked Oct 2026) | top 14%, bottom 35% (672 px), 6% each side (65 px); Meta draws its own CTA in the bottom zone |
| Feed 4:5 | the 34 px strips each side that the 3:4 grid crop removes; where a surface shows it square, the 135 px bands top and bottom |
| Feed 1:1 | the 135 px strips each side that the 3:4 grid crop removes |
| Display ads | a padding of >= 4% inside the frame for logo and CTA; IAB asks that ads be distinguishable from page content (a 1 px border or a non-white ground) |
| YouTube thumbnail | the bottom-right duration badge |
| OG image | outside the central 630 px square when the link may show as a square thumbnail |

Compute, do not eyeball: `"$PY" "$KC" plan kit.json` maps each placement's crop window and
keep-out insets into master pixels, unions the keep-out zones and reports what survives all of
them as `safe_in_all_master_px` (the master's copy- and focus-safe box), checks the focal box
against every placement (`focus_ok`, exit 1 if any fails) and lists free copy bands per
placement in placement pixels.

## 3. Master-first rule

1. One master per idea, generated at the widest aspect the kit needs (16:9, or wider when
   banners dominate) and the largest size tier the configured model offers. Get it to PASS with
   `visual-reviewer` (or the `visual-iterate` saved workflow from the main thread) before
   deriving anything.
2. Derive every placement by crop (window inside the master) or outpaint (window larger than the
   master). Never regenerate per format: new rolls drift in subject, light, palette and grain.
3. `plan` picks the method per placement and reports `pads_master_px` and `new_area_share`.
   Keep new area under ~40% (heuristic: past that the model invents most of the frame); if a
   placement needs more, lower its `fill`, move the anchor, or make a wider master.
4. Outpaint (image-editing recipe): `"$PY" "$KC" derive kit.json out` writes the in-bounds crop
   `<name>_prepad.png` and prints the pad command → `"$PY" "$MT" pad prepad.png padded.png
   padmask.png --top 467 --bottom 467 --overlap 24` → `image-editor` (FLUX Fill on fal or
   another native-mask model honours the mask; OpenRouter approximates) runs `image_edit {image:
   padded.png, mask: padmask.png, preserve_unmasked: false, instruction: "Extend the background
   naturally into the masked area, same light and gradient; add no objects or text"}` →
   `masktool feather padmask.png feather.png --px 12` and `masktool composite padded.png edited.png
   feather.png joined.png` → `"$PY" "$KC" resize joined.png final.png 1080x1350`.
5. Verify: `masktool grow padmask.png diffmask.png --px 13`, then `masktool diff padded.png
   joined.png --mask diffmask.png --max-outside 0.5` (outside the grown pad mask the original
   pixels must be unchanged); joins invisible on a 100% crop.

## 4. Generation

- Write the master's brief with the `image-brief-writing` skill, stating the copy-safe box from
  `plan` numerically ("left 45% plain, low-detail navy gradient").
- Preflight `mcp__image__image_ops_status`. Each op uses the endpoint and model tag the user
  configured; you cannot switch models per call. State the capability, then check the tag:

| Need | Op | Fits (model matrix in the `image-generation` skill) |
|---|---|---|
| extreme ratio in one generation (banner, skyscraper) | GEN / REF | Nano Banana 2.1 `google/gemini-nano-banana-2.1` (ratios to 8:1 and 1:8) |
| photoreal materials and light | GEN / REF | FLUX 3 `black-forest-labs/flux-3-image` |
| product or character identical across the kit | REF | any tag whose reference limit covers your references |
| outpaint with an honoured mask | EDIT | native-mask models (fal FLUX Fill, Ideogram edit, GPT Image 2.5 on Opper); OpenRouter approximates |

  A weak or missing op is an Open doubt naming the variables `image_ops_status` lists and a tag
  that fits; never route around it.
- Exploration n = 3-4; then fix the seed of the chosen master and record it; later rolls (a
  second idea, an alternate background for an A/B test) reuse the seed and pass the accepted
  hero as a reference: "image 1 sets palette, light, grain and style; keep them".

## 5. Text and logo: typeset, then composite

Never put copy, logos or UI into a generation: models misspell, invent logos, and baked text
cannot be edited, translated or A/B-tested. Per placement:

1. Template (SVG or HTML) with slots `{headline}`, `{sub}`, `{cta}`, `{logo}`, brand fonts, and
   positions taken from the `plan` copy bands; escape copy before substitution.
2. Render a transparent text layer at the placement size: `resvg_py.svg_to_bytes(svg_string=svg,
   width=1080, height=1080, font_files=["fonts/Inter-Bold.otf"])` (in the stack venv), or
   `rsvg-convert -w 1080 -h 1080 -o text.png text.svg`, or Playwright
   `page.screenshot(path="text.png", omit_background=True)` for HTML.
3. Composite: `Image.alpha_composite(art.convert("RGBA"), text_layer)` (Pillow) or
   `"$PY" "$MT" over text.png art.png out.png --x 0 --y 0`.
4. Logo: the supplied vector, at or above its minimum size with its clear space (brand
   guidelines); reversed or mono version on busy or dark art. A generated look-alike is never
   placed.

## 6. Contrast over pixels

1. Box = the text's bounding box plus about 8 px (anti-aliasing reaches past the glyphs).
2. `"$PY" "$KC" contrast art.png --box 135,900,945,1044 --text '#FFFFFF'` blurs the region by
   1 px (a single noisy pixel should not decide), computes the WCAG 2.x ratio for every pixel and
   reports the worst point (value and location), the 5th percentile and the mean. Targets: 4.5:1
   text, 3:1 large text (>= 24 px regular or >= 18.66 px bold) and meaningful graphics.
3. Fails: move the copy to a quieter band, re-crop, or solve a scrim:
   `"$PY" "$KC" scrim art.png out.png --box ... --text '#FFFFFF' --target 4.5 --margin 0.3`
   searches the smallest black alpha that lifts the worst point to 4.8:1 (flat behind the box to
   the image edge, linear fade over 0.6 x box height), applies it with the same integer
   compositing it searched with, and re-measures. A solid panel is the fallback for photos too
   busy for a light scrim.
4. Measure the art without the text layer; keep every `contrast` / `scrim` JSON beside the
   manifest as the accessibility record.

## 7. Batch production

- Names: `<campaign>_<message>[-<variant>]_<placement>_<W>x<H>_v<n>.<ext>`, lowercase, no
  spaces or underscores inside fields (`orbit_launch-b_feed_1080x1350_v2.png`). `derive` writes
  them; `manifest` refuses names that do not parse and pixel sizes that differ from the name.
- Manifest: `"$PY" "$KC" manifest kit.json final/manifest.csv final/*` (or `.json`) writes per
  file: campaign, message, variant, variable, placement, width, height, format, bytes, headline,
  sub, cta, alt, model, seed, references, derived_from. Model, seed and references come from the
  file's router sidecar (`<file>.json`) or else the master's.
- More than 8 assets: fan out per placement group (the `fanout` saved workflow from the main
  thread, or parallel `image-editor` agents for the outpaints), but keep master acceptance,
  templates, contrast checks and the manifest in one place.

## 8. A/B variants

- One variable per variant: headline, image (a second master idea) or CTA colour. Same master,
  crops, template, sizes and export settings for everything else.
- Kit JSON `"variants": {"b": {"variable": "headline", "headline": "Meet Orbit 2"}}`; derive with
  `--variant b`; the manifest records variant and variable, so results stay attributable.
- A CTA-colour variant re-runs the contrast check for the button label (WCAG 1.4.3) and the
  button against its ground (1.4.11, 3:1).

## 9. Export

| Destination | Format | Rule |
|---|---|---|
| social upload | PNG for flat art and text, JPEG quality 85-90 for photos | platforms re-encode: upload the best quality they accept |
| web (OG, site) | WebP or AVIF plus a JPEG fallback | |
| IAB display | JPEG / PNG / GIF within the initial-load weight | 150 kB for 300 x 250, 728 x 90, 160 x 600; 50 kB for 320 x 50; 250 kB for 970 x 250 (IAB LEAN fixed-size spec; weights in kB after gzip; ad servers may be stricter) |
| YouTube thumbnail | JPG or PNG | under 2 MB |

`"$PY" "$KC" export in.png out.jpg --max-kb 150` converts any embedded profile (Display P3,
Adobe RGB) to sRGB, drops EXIF, XMP, ICC and text chunks, and steps quality down by 4 (to
`--min-quality 60`) until the file fits; exit 1 if it cannot. Add `--subsampling 0` for small
coloured text in JPEG. Provenance stays outside the pixels: keep the router sidecars and the
manifest; if content credentials are required, sign last (`c2patool -m c2pa.json -o signed.jpg
final.jpg`; any re-encode strips them; its built-in test certificate is for development only).
Apply the platform's AI-content label or the client's disclosure where required and note it in
the delivery notes.

## 10. QA contact sheet

`"$PY" "$IMG" sheet qa/sheet.png final/*.png final/*.jpg --cols 3 --cell 400`, then Read it
(each 400 px cell approximates a phone feed tile). Checklist per asset:

- [ ] Size and name match the matrix; a manifest row exists.
- [ ] Logo is the supplied file, at or above minimum size, clear space respected, undistorted.
- [ ] Headline legible in the 400 px cell; nothing inside a safe-zone strip.
- [ ] Worst-point contrast recorded and >= target for every text box.
- [ ] Focal point intact in every crop (`plan` said `focus_ok`); no cut product edges.
- [ ] Palette and grade consistent across placements; no outpaint seams or repeated texture.
- [ ] No generation artefacts (hands, text-like noise, warped lines).
- [ ] Format, sRGB, weight cap and metadata rules met.

## 11. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| subject or light differs between sizes | regenerated per placement | one master; crop or outpaint only |
| outpaint seam or repeated texture | tight join, hard edge, > 40% new area | `--overlap 24`, feather 8-16 px, lower `fill`, plainer master ground |
| headline unreadable over the art | contrast judged by eye or by the mean | worst-point measurement, solved scrim or panel |
| copy under story UI or Meta's CTA | safe zones ignored | `plan` with the platform insets |
| misspelled copy or fake logo | text or logo in the prompt | typeset text, supplied logo |
| A/B result not attributable | several variables changed | one variable per variant, recorded in the manifest |
| ad rejected for weight | PNG photo, metadata, unoptimised 2x asset | `export --max-kb` to JPEG or WebP |
| colours shift after upload | Display P3 or untagged export | sRGB conversion on export |
| grid crop cuts the headline | copy set to the 4:5 edges | keep copy inside the centred 3:4 area |
| manifest disagrees with files | hand-renamed files | names from `derive`; regenerate the manifest from the files |

## 12. Worked example: launch kit, 1 message x 6 placements from one 16:9 master

1. Matrix: message `launch` (headline "Orbit 2 is here", sub, CTA "Get Orbit") x placements
   `yt` 1280 x 720, `og` 1200 x 630, `square` 1080 x 1080, `feed` 1080 x 1350, `story`
   1080 x 1920 (ad-safe 14/35/6%), `mrec` 300 x 250.
2. Master: brief via `image-brief-writing` (product disc right of centre, plain navy-to-grey
   gradient, nothing in the left 45%); REF with the product reference, `aspect_ratio: "16:9"`,
   `size: "4K"`, `n: 3`, `seed: 4242`; `visual-reviewer` PASS; `master.png` 3840 x 2160, focal
   box (2000, 430)-(3300, 1730).
3. `kitcheck plan kit.json`:

| Placement | Method | Window or pads (master px) | New area | Focal box (placement px) |
|---|---|---|---|---|
| yt | resize | full frame, scale 0.333 | 0 | 667-1100 x 143-577 |
| og | crop | y 72-2088, scale 0.3125 | 0 | 625-1031 x 112-518 |
| square | crop | x 1570-3730 | 0 | 215-865 x 215-865 |
| feed | outpaint | x 1365-3840, pad top 467 / bottom 467 | 30.2% | 277-844 x 391-959 |
| story | outpaint | x 1652-3648, pad top 575 / bottom 814 | 39.1% | 188-892 x 544-1247 |
| mrec | crop | x 1248-3840 | 0 | 87-238 x 50-200 |

   Safe in all placements: (1840, 173)-(3460, 1732), which contains the focal box. The story's
   free band is the top (269-544 px) for headline and sub; Meta supplies the CTA below.
4. `kitcheck derive kit.json out` wrote four crops and two prepads; the feed and story pads
   (`--top 467 --bottom 467`, `--top 575 --bottom 814`, overlap 24) went to `image-editor` with
   "Extend the navy-to-grey studio gradient upward and downward; add no objects", then feather
   12, composite and `kitcheck resize` to 1080 x 1350 and 1080 x 1920.
5. Text layers from the SVG templates (copy in the plan's bands). Square: headline in the bottom
   band, box (135, 900)-(945, 1044), white: `contrast` → worst 3.90:1 at (135, 1042), pixel
   #748297; fails 4.5. `scrim --target 4.5 --margin 0.3` → black at alpha 0.114 from y 900 down
   with an 86 px fade above → worst 4.80:1, pass. The other boxes sit on the darker upper
   gradient and passed the same check unchanged.
6. `kitcheck export` per file: PNG for feed, story and OG; JPEG for yt; JPEG with
   `--max-kb 150` for the mrec (a few kB, far under the cap); EXIF and ICC removed.
7. `kitcheck manifest kit.json final/manifest.csv final/orbit_launch_*` → 6 rows, model
   `google/gemini-nano-banana-2.1`, seed 4242, references `[{"path": "refs/orbit-disc.png",
   "role": "product"}]`, `derived_from` master.png; then `imgcheck sheet` → Read → checklist
   passed.
8. Deliver `final/` (6 assets), `manifest.csv`, `sheet.png`, `kit.json`, the `plan` JSON and the
   contrast results; the master and its sidecar stay with the source files.

Related: `image-brief-writing`, `image-generation`, `image-editing`, `visual-review`,
`layout-grids-posters-editorial`, `visual-accessibility-audit`, `brand-guidelines-system`,
`photo-retouch-composite`, hub `graphic-design`.
