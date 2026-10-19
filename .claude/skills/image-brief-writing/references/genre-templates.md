# Genre templates

Each template gives the route (op and tool), the brief fields that matter most, a compiled
skeleton to fill in, and the checks that decide acceptance. Square brackets are slots. Keep the
compile order of the skill (subject → setting → composition → style → light → palette → mood →
exclusions) and stay under ~120 words.

## Product on seamless

- Route: REF `image_generate_with_references` with a clean packshot as image 1 (plain ground,
  tight crop with ~5% margin, short side >= 1024 px).
- Skeleton: "[Product] from image 1, keep its shape, label layout, text and colours exactly,
  standing on a seamless [colour, hex] backdrop. Three-quarter view at eye level, product fills
  [60]% of the frame height, centred [or: right third, left 40% empty]. 85 mm lens look, f/8,
  everything sharp. Large softbox key light from the left, white fill card on the right, soft
  contact shadow under the product. Clean, premium mood. No other objects, no text besides the
  label."
- Checks: label text character by character against the reference; edges and cap geometry;
  reflections plausible. Small label defects: `image_segment` "the label" (or a box mask) →
  `image_edit` with the exact strings; never regenerate for a small defect.

## Editorial portrait (fictional person)

- Route: GEN; REF with an identity sheet for a recurring character.
- Skeleton: "Head-and-shoulders portrait of a [age range] [description] with [expression],
  wearing [wardrobe], [environment, softly out of focus]. Eye level, subject on the right third,
  looking toward the empty left side. 85 mm lens look, f/2, shallow depth of field. Soft window
  light from the left at 45°, gentle fill, slight rim light. Muted warm grade, natural skin
  texture. No text, no logos."
- Checks: hands, eyes (matching catchlights, symmetric pupils), teeth, ears, jewellery
  symmetry; skin not plastic. Never generate or edit a real, identifiable person without
  documented consent.

## Isometric illustration

- Route: GEN for the first image; REF with the accepted image as style reference for the set.
- Skeleton: "Isometric illustration of [scene], true isometric 30° angles, no perspective
  distortion. Flat colours with one level of shading, 2 px dark outlines [#hex]. Palette
  [3-5 hexes with roles]. Plain white background, generous margins. Friendly, clear mood. No
  text."
- Checks: all receding edges at 30°; consistent light side; outline weight equal across the set.
  Set consistency: fixed seed, same skeleton, first accepted image as reference.

## Flat spot illustration or icon set

- Route: VECTOR `vector_generate {prompt, style, aspect_ratio}`; `layered: true` when the
  deliverable needs editable layers.
- Skeleton (prompt): "[Object] as a [line | filled] icon on a 24 x 24 grid, [2] px strokes with
  round caps and joins, [2] px corner radius, single colour [#hex], centred with 2 px padding,
  no text." `style`: "flat icon" or "line art".
- Checks: `svg_inspect` (path count, palette), `svg_optimize`, render at 16, 24 and 48 px; the
  set audit (stroke, caps, radii, visual mass) belongs to sibling `icon-system-design`.

## Logo exploration

- Route: VECTOR for directions, or sketches; never raster generation for finals.
- Skeleton: "[N] distinct logo mark directions for [brand], [concept words], [geometric |
  organic] construction, single colour [#hex] on white, no text, no gradients."
- Rules: generated marks are mood material; the final is drawn and refined as clean vector
  geometry by `vector-artist` (sibling `logo-design-process`); check the direction does not
  resemble an existing trademark before investing in it.

## Abstract background for text

- Route: GEN.
- Skeleton: "[Abstract motif] in [style], concentrated in the [right 50%]; the [left 50%] is a
  smooth, low-detail [colour] gradient. [Light]. Palette [hexes]; background value [dark | mid |
  light] so that [white | black] text reads on it. Calm mood. No text, letters or logos."
- Checks: worst-point contrast of the real text colour over the copy area after placement
  (sibling `social-asset-kit`, `kitcheck.py contrast`); scrim or panel if it fails.

## Seamless pattern or texture

- Route: GEN for the tile; EDIT for seam repair.
- Skeleton: "Seamless tileable pattern of [motif] at [small | medium] scale, evenly distributed,
  [density], on a [colour] ground; flat [medium]; palette [hexes]; no single dominant element,
  no border, no text."
- Checks: 2 x 2 tile test, half-offset seam repair (skill section 5), repeat visibility at the
  intended display size (a motif that is too distinctive shows the repeat).

## Transparent cut-out (sticker, product on alpha)

- Route: `image_generate_transparent` on a native-alpha tag; otherwise GEN on a flat contrasting
  colour (state the hex) and `image_remove_background` (only with the caller's approval when the
  transparent op is missing).
- Skeleton: "Isolated [subject], [view], soft even studio light, transparent background, no
  ground, no frame, no shadow [or: soft contact shadow]."
- Checks: `imgcheck.py expect out.png --alpha`; `alpha_partial_frac` above ~0.05 on a hard-edged
  product means fringing; inspect on black and on white for halos; hair, fur and glass need
  matting-quality removal.

## Food

- Route: GEN (REF for a specific dish or brand tableware).
- Skeleton: "[Dish] in a [bowl or plate, material, colour], [overhead | 45°] view, [garnish],
  minimal props: [two at most]. Natural window light from behind and to the side so steam and
  texture show, soft fill. 50 mm look, f/4. Palette [hexes]. Fresh, appetising mood. No text."
- Checks: plausible food structure, utensils correct and countable, no duplicated garnish, no
  melted plate edges.

## Interior or architecture

- Route: GEN; REF for a real floor plan or material board.
- Skeleton: "[Room or building], [style era], [materials]. Two-point perspective from [corner],
  camera at 1.2-1.5 m height, verticals perfectly parallel. 24 mm look, f/8. [Time of day]
  daylight through [windows] balanced with warm interior lamps. Palette [hexes]. No people, no
  text."
- Checks: straight verticals, plausible furniture scale and door heights, window exposure not
  blown out, no impossible geometry at corners.

## Device or UI mockup

- Route: GEN or REF for the device scene only; the real UI is composited afterwards.
- Skeleton: "[Device] on [surface], [angle], screen showing a plain flat [#hex] colour,
  [environment], [light]. No text, no interface, no logos on screen or device."
- Rules: never generate interface text or real product UI; composite the actual screenshot with
  a perspective transform in layout; keep the screen corners clearly visible for the transform.

## Character or mascot sheet

- Route: GEN for the first design, then REF with that sheet as the identity reference.
- Skeleton: "Character sheet of [character]: front, three-quarter and side views in a row, same
  outfit and proportions, neutral pose, flat neutral grey background, even light, [style]. No
  text."
- Checks: proportions identical across views; later scenes pass the sheet as image 1 with "the
  character in image 1, same face, hair and outfit"; identity drift after 2 rounds → single
  best identity reference plus the accepted hero, identity sentence first.

## Landscape or environment hero

- Route: GEN.
- Skeleton: "[Landscape], horizon on the lower third, [foreground anchor] at the [left third],
  atmospheric depth with haze in the distance, [weather], [time of day] light from [direction].
  The sky in the upper [40]% is calm and low-detail for a headline. 35 mm look, f/11. Palette
  [hexes]. No people, no text, no buildings."
- Checks: copy area contrast measured, horizon level, no repeated cloud or tree patterns.
