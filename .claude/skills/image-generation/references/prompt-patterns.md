# Prompt patterns by deliverable

Each pattern: the operation and tool, the model families that do it best (you cannot pick the
model per call: it is the tag configured for the op; when the configured family is a poor fit,
say so in an Open doubt), aspect, a prompt skeleton (fill the angle brackets), and the defects to
look for first. Skeletons follow the order subject, composition, setting, light,
style, palette, text, constraints. Replace every bracket; leftover brackets end up in the image.

## Product packshot (e-commerce, white background)

- GEN `image_generate` (FLUX 3, GPT Image 2.5, Nano Banana); for a cutout use TRANSPARENT
  `image_generate_transparent` (GPT Image 2.5 native alpha) and drop the white background sentence.
- Aspect 1:1 or 4:5. Min 2048 px short side for zoomable listings.

```text
<Product, material, colour> standing upright, front three-quarter view at eye level, centred
with 10% margin on every side, on a seamless pure white (#FFFFFF) studio background, soft
diffused key light from upper left with a subtle contact shadow directly beneath, high-end
catalogue photography, true-to-life colour, crisp edges, no props, no text.
```
Check first: label text and logo fidelity (use the real packshot as reference 1), symmetry of
round objects, shadow direction consistent with highlights.

## Lifestyle product shot

- REF `image_generate_with_references` with the packshot as image 1 (Nano Banana 2.1, FLUX 3,
  GPT Image 2.5).
- Aspect 16:9 (hero) or 4:5 (feed).

```text
The <product> from image 1, exactly as shown, <in use / placed> on <surface> in <setting>,
<camera angle>, <framing>, <time of day> light from <direction>, <mood> atmosphere, editorial
lifestyle photography, shallow depth of field, <palette>, empty area on the <side> third for
copy, no text.
```
Check first: product scale against the environment, hands interacting with the product.

## Character sheet (turnaround) for later consistency

- GEN (Nano Banana 2.1, GPT Image 2.5). Aspect 16:9 or 21:9.

```text
Character turnaround sheet of <name-free description: age range, build, hair, outfit, signature
accessory>, four full-body views in a row (front, three-quarter, side, back), same scale, neutral
standing pose, arms slightly away from the body, flat light-grey background, consistent colours
across views, clean <style: 3D render / cel-shaded / watercolour> style, no text, no labels.
```
Then crop single views locally (Pillow via `$PY`) and use the front view as the identity reference.
Check first: outfit details identical across views, proportions constant.

## Consistent character across scenes

- REF (Nano Banana 2.1 fuses up to 4 characters; Seedream 5 and GPT Image 2.5 also hold identity),
  refs: identity crop(s) + accepted hero frame.

```text
The character from image 1 (same face, hair, outfit and colours), <action> in <scene>,
<camera>, <light>, in the same visual style as image 2.
```
Keep the style sentence and seed fixed across the series; change only the action and scene.

## Poster, flyer, infographic with text

- GEN on a text-strong family: GPT Image 2.5, Ideogram 4.5 (Opper), Gemini 3 Pro Image. On a
  weak-text family, leave the text slots empty and typeset later. Aspect per medium (2:3 poster, 4:5 social).

```text
<Style> poster for <event>. Headline "<EXACT HEADLINE>" in <font character> at the top third,
centred, <colour>. Subheading "<exact subheading>" below it in smaller <weight>. Central
illustration of <subject>, <style>. Footer line "<exact date and venue>" bottom centre.
<Palette with hex>. Generous margins, strong hierarchy, no other text.
```
Rules: at most 3 text elements; each under ~6 words; numbers written as digits. Proofread every
character; if one string keeps failing, generate with that slot empty and set the text in a
layout tool or via a masked edit.

## UI or editorial spot illustration (flat)

- GEN (Recraft V4.1 raster, Nano Banana); if it must scale, use the vector-art skill
  (`vector_generate`). Aspect 4:3 or 1:1.

```text
Flat vector-style illustration of <scene>, simple geometric shapes, <n> colours only:
<hex list>, no gradients, no outlines / <2 px> uniform outlines, plenty of negative space,
centred composition on a plain <hex> background, friendly modern tech illustration style, no text.
```

## Isometric diagram or scene

- GEN (GPT Image 2.5, Gemini 3 Pro Image). Aspect 1:1 or 4:3.

```text
Isometric 30-degree illustration of <system or room>, <components listed with positions:
left, centre, right, back>, clean edges, soft ambient occlusion, <palette>, white background,
no text labels (labels added later).
```
Check first: isometric angle consistency, parallel lines, component count.

## Architecture or interior visualisation

- GEN (FLUX 3, MAI Image 2.6). Aspect 3:2 or 16:9.

```text
<Room type> with <materials: oak floor, lime-washed walls, brass fixtures>, viewed from
<corner/doorway> at 1.5 m eye height, 24 mm wide-angle look with vertical lines kept vertical,
<time of day> daylight through <window position>, <furnishing list>, photorealistic
architectural photography, natural colour grading.
```
Check first: verticals, window light direction vs shadows, furniture scale.

## Food

- GEN (FLUX 3, Gemini 3 Pro Image). Aspect 4:5 or 1:1.

```text
<Dish with 3-4 concrete ingredients visible>, on <plate/board> on <surface>, overhead / 45-degree
view, <props: linen napkin, fork>, soft window light from behind-left, gentle steam, appetising
editorial food photography, <palette>.
```

## Seamless texture or pattern

- GEN (Nano Banana 2.1, Recraft V4.1). Aspect 1:1.

```text
Seamless tileable pattern of <motif>, evenly distributed, no element touching the edges in a
way that breaks tiling, <n> colours: <hex>, flat <medium>, no border, no text.
```
Verify tiling: build a 2x2 repeat and Read it; seams show as lines or broken motifs at the centre cross.

```bash
"$PY" -c "from PIL import Image; t=Image.open('tile.png'); c=Image.new(t.mode,(t.width*2,t.height*2)); [c.paste(t,(x,y)) for x in (0,t.width) for y in (0,t.height)]; c.save('tile-2x2.png')"
```

## Hero banner with copy space

- GEN (Nano Banana 2.1 handles ratios beyond 3:1; GPT Image stops at 3:1, so generate 3:1 and
  extend with an outpaint in image-editing). Aspect 21:9 to 4:1.

```text
Wide panoramic <scene>, main subject <subject> placed on the right third, the left half calm
and uncluttered (<sky / soft gradient wall>) for headline text, <light>, <style>, no text.
```

## Storyboard frames

- REF with the character refs; `n: 1` per frame, fixed seed and style sentence.

```text
Storyboard frame <k> of <N>: <shot type: wide/medium/close-up> of the character from image 1
<action>, <location>, <camera direction>, rough cinematic sketch style, greyscale with
<one accent colour>, 16:9 frame, no text.
```

## Vocabulary that moves results

| Lever | Words that work | Words that do nothing |
|---|---|---|
| Light | "soft window light from the left", "rim light", "overcast diffuse", "golden hour backlight", "single hard spotlight" | "good lighting", "perfect light" |
| Camera | "85 mm portrait", "24 mm wide", "macro", "top-down flat lay", "low angle", "eye level" | "professional camera" |
| Medium | "risograph print", "gouache", "cel-shaded 3D", "linocut", "editorial photography", "isometric vector" | "artistic", "masterpiece" |
| Detail | concrete nouns and materials ("brushed aluminium", "linen") | "highly detailed", "8k", "ultra realistic" |
| Mood | "quiet", "tense", "playful" plus a light/palette choice that implies it | "amazing", "stunning" |
