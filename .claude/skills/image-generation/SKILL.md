---
name: image-generation
description: "Raster image generation through the single image MCP server (mcp__image__image_generate, image_generate_with_references, image_generate_transparent, image_ops_status, image_info) - per-operation BYOK configuration (IMAGE_GEN, IMAGE_REF, IMAGE_TRANSPARENT URL, KEY and MODEL on OpenRouter, Opper, fal or an OpenAI-compatible endpoint, no fallbacks), image_ops_status preflight and Open doubts naming the missing env vars, model tags and their limits, prompt structure, reference roles, aspect and size per adapter, seeds and cost, sidecar provenance, and the produce, review, revise loop with visual-reviewer."
when_to_use: "Before any mcp__image__ generation call, when writing an image brief, when a generated image fails review, when an image operation is not configured, or when recommending which model tag a user should configure for a visual deliverable."
---

# Image generation

You turn a visual brief into raster files on disk that pass review. The `image` server sends each
operation to exactly the endpoint and model tag the user configured; you cannot choose a model per
call and nothing falls back to another provider. Your job: check what is configured, write the
prompt, handle references, verify, iterate with `visual-reviewer`, and record provenance.

Deep material: [configuration and adapters](references/configuration.md) (env names, adapters,
model listings, BYOK, errors), [model matrix](references/model-matrix.md) (what each router and
tag can do per operation), [prompt patterns](references/prompt-patterns.md) (skeletons per
deliverable).

## 1. The image server

One stdio MCP server, `image` (tool ids `mcp__image__<tool>`), started by `bin/image-router` via
`bin/mcp-run`, which parses `~/.claude/stack.env`. Each operation has its own variables
`IMAGE_<OP>_URL`, `IMAGE_<OP>_KEY`, `IMAGE_<OP>_MODEL` (optional `IMAGE_<OP>_API` to force the
adapter, `IMAGE_<OP>_PARAMS` as a JSON object merged into every request). A tool exists only when
its op has all three, or `_API=local` where allowed.

| Op (env prefix) | Tool | Covered by |
|---|---|---|
| `IMAGE_GEN` | `image_generate` | this skill |
| `IMAGE_REF` | `image_generate_with_references` | this skill |
| `IMAGE_TRANSPARENT` | `image_generate_transparent` | this skill |
| `IMAGE_EDIT` | `image_edit` | image-editing |
| `IMAGE_SEGMENT` | `image_segment` | image-editing |
| `IMAGE_BG_REMOVAL` | `image_remove_background` | image-editing |
| `IMAGE_UPSCALE` | `image_upscale` (`_API=local` = Lanczos) | image-editing |
| `IMAGE_VECTOR` | `vector_generate` | vector-art |
| `IMAGE_TRACE` | `image_vectorize` (`_API=local` = vtracer) | vector-art |
| `IMAGE_VECTOR_MANIPULATION` | `svg_transform` (only when the model is not `claude`) | vector-art |

Always present, local, free: `image_ops_status`, `image_info`, `mask_convert`, `svg_inspect`,
`svg_optimize`, `svg_render`, `svg_layers`, `svg_layerize`, `layers_compose`, `export_pdf`.

Adapters, detected from the URL host: `openrouter` (`https://openrouter.ai/api/v1`, `POST /images`),
`opper` (`https://api.opper.ai`, `POST /v3/images`), `fal` (`https://queue.fal.run`, queue API),
`openai` (any other host, OpenAI-compatible `/images/generations` and `/images/edits`), `local`.

Every model tool returns JSON with `ok`, `files` (path, mime, bytes, width, height), the op,
adapter, URL host and model tag that answered, `notes` (approximations, conversions, fidelity
measurements) and `warnings` (including parameters the adapter or endpoint ignored or snapped).
Read both after every call. Files land in `output_dir` (default `.stack/images/<YYYYMMDD>/`) with a
`<file>.json` sidecar (op, adapter, URL host, model tag, prompt, params without secrets or base64,
inputs, created). The tool's input schema as your client shows it is authoritative: the parameter
tables here follow the server specification; if the schema lacks a parameter, leave it out.

Helper script (Pillow, run with the stack venv):

```bash
STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"
PY="$STACK/.venv/bin/python"; IMG="$STACK/.claude/skills/image-generation/scripts/imgcheck.py"
"$PY" "$IMG" info out.png                       # size, aspect, alpha coverage, sha
"$PY" "$IMG" expect out.png --aspect 16:9 --min-side 1024 [--alpha]   # exit 1 on failure
"$PY" "$IMG" sidecar out.png --set review='{"overall":8.6}'           # merge provenance under "agent"
"$PY" "$IMG" sheet .stack/images/review/sheet.png v1.png v2.png v3.png  # one image to Read
```

## 2. Preflight (once per task)

1. Call `mcp__image__image_ops_status`. Per op it reports: exposed or not, adapter, URL host, model
   tag, and the exact env names that are missing. It never shows keys. Never read, print or quote
   `~/.claude/stack.env` yourself.
2. Map the brief to ops: new picture from text → GEN; must match given images (character,
   product, style) → REF; cutout asset, sticker, UI art on transparency → TRANSPARENT; a later local
   fix → EDIT (image-editing skill).
3. A needed op is not exposed: do not improvise. No other provider, no optional MCP server, no
   direct API calls, no local stand-in, and no other op imitating it (for example dropping the
   references and using GEN) unless the caller approved that substitution. Do what the configured
   ops allow, return `Status: partial` (or `blocked`) with an Open doubt naming the variables.
4. Look up the configured tag in the [model matrix](references/model-matrix.md): native or
   approximated, reference limit, alpha support, size vocabulary, price, retirement date. A tag that
   cannot do the job (TRANSPARENT on `openai/gpt-image-2`; 12 references on a 10-reference model):
   Open doubt with a tag that can. A weak fit (lettering on a model weak at text): try, and recommend
   a better tag if review fails twice on that criterion.
5. Pin the deliverable spec before spending, in 6 lines:
   `subject | use (where shown) | aspect + min pixels | background (scene, flat colour, transparent) |
   text in image (exact strings or none) | references (paths + role each)`.
   A field that is unknowable and costly to guess (brand colours, exact copy, a real person's
   likeness) → Open doubt to the caller before generating.
6. Output location: pass `output_dir` and `filename_prefix` when the brief names a destination or a
   series (`hero-v`, `icon-cart`); never write into source trees unless asked.

Open doubt lines (doubt-escalation format; name only the variables `image_ops_status` reports):

```
- [scope|high] IMAGE_REF is not configured (image_generate_with_references not exposed; missing IMAGE_REF_URL, IMAGE_REF_KEY, IMAGE_REF_MODEL) - the mascot cannot be kept consistent with the reference sheet - resolve: set them in ~/.claude/stack.env, e.g. https://openrouter.ai/api/v1 with google/gemini-nano-banana-2.1, then reconnect the image server (/mcp) - route: user
- [scope|med] IMAGE_GEN_MODEL=<tag> garbles lettering (headline failed 2 review rounds) - resolve: configure openai/gpt-image-2.5-sunburst (OpenRouter) or fal/ideogram-v4.5 (Opper) - route: user
```

If `image_ops_status` says an op is configured but its tool is not in your tool list, the server
started before the edit: Open doubt asking the user to reconnect the `image` server.

## 3. Tools and parameters

| Tool | Required | Optional |
|---|---|---|
| `image_generate` | `prompt` | `aspect_ratio`, `size`, `quality`, `n`, `seed`, `output_format`, `output_dir`, `filename_prefix`, `params` |
| `image_generate_with_references` | `prompt`, `references` (1..N local paths, http(s) URLs or data URIs, in "image N" order) | as `image_generate` |
| `image_generate_transparent` | `prompt` | as `image_generate` (png or webp only; `references` only if the schema offers it) |
| `image_info` | `image` | returns size, mode, has alpha, format, file size |
| `image_ops_status` | none | |

How the adapters map the common parameters (unsupported ones are reported in `notes` / `warnings`):

| Parameter | Meaning | OpenRouter | Opper | fal |
|---|---|---|---|---|
| `aspect_ratio` | '1:1', '16:9', '21:9', 'auto' | `aspect_ratio` | `aspect_ratio` (Gemini, Pruna, xAI); normalised to `size` for pixel-sized models against the model listing | `aspect_ratio` or `image_size` per endpoint schema |
| `size` | tier '1K', '2K', '4K' or exact 'WxH' | `size`; explicit pixels win; conflicting `aspect_ratio`/`resolution` = 400 | `size` WxH | `image_size` |
| `quality` | low, medium, high; xhigh, max, auto where declared | `quality` | `quality` (`4k` on Gemini) | endpoint field if any |
| `n` | variants, each billed | 1-10 | 1-4 (1 with `async`) | `num_images` |
| `seed` | reproducibility where supported | `seed` | in `parameters` where declared | `seed` |
| `output_format` | png (default), webp, jpeg | `output_format` | `parameters.output_format` | endpoint field |
| `params` | adapter-native extras, merged last | `{"provider":{"options":{"<slug>":{...}}}}` | `{"parameters":{...}}`, `{"async":true}` | native field names |

`IMAGE_<OP>_PARAMS` from the user's configuration is merged into every request of that op; per-call
`params` win on conflict.

## 4. Know the configured model

| Family (example tags) | Strong at | Watch out |
|---|---|---|
| GPT Image 2.5 (`openai/gpt-image-2.5-sunburst`, `-flare`) | instruction following, in-image text, native alpha, 16 refs | sizes multiples of 16, ratio 1:3..3:1, edge <= 3840; no seed determinism; `max` quality slow and ~16x `medium` cost |
| Nano Banana 2.1 / Gemini image (`google/gemini-nano-banana-2.1`; Opper `vertexai/gemini-3.1-flash-image`, `vertexai/gemini-3-pro-image`) | cheap, fast, long prompts, 14-reference fusion, 4K, ratios to 8:1 | opaque; JPEG on Opper |
| FLUX 3 / FLUX.2 Pro (`black-forest-labs/flux-3-image`, Opper `fal/flux-2-pro`) | photoreal materials and light, layout by position, 10 refs | opaque; 4K ~12x the 1K price; front-load the prompt |
| Seedream 5 (`bytedance-seed/seedream-5-0-pro`, Opper `bytedance:ap/seedream-5`) | multi-reference consistency, image sets | opaque; front-load the prompt |
| Ideogram 4.5 (Opper `fal/ideogram-v4.5`) | typography, posters | 4 refs |
| Recraft V4.1 (`recraft/recraft-v4.1-flash`) | flat brand illustration, cheapest drafts | 0-1 refs; for SVG use vector-art |
| MAI Image 2.6, Qwen Image 3 Pro, HY Image 3.5, Riverflow 2.5 | see the model matrix | |

Prompt length: GPT Image and Gemini reason over long prompts (80-120 words help); FLUX and
Seedream dilute after ~40 words, so put subject, light and style first.

## 5. Write the prompt

Natural sentences, most important first. None of these models takes a separate negative prompt:
describe what should be there.

```text
[Subject + action]   A matte-black ceramic pour-over coffee dripper on a walnut counter,
[Composition]        three-quarter view from slightly above, subject centred, generous empty space on the left for headline copy,
[Setting]            minimal Scandinavian kitchen, softly out of focus,
[Light]              late-morning window light from the right, soft shadows, warm highlights on the glaze,
[Style/medium]       editorial product photography, 85 mm lens look, shallow depth of field, natural colour,
[Palette]            warm neutrals with one sage-green accent (#9CAF88) in the background,
[Text]               no text, no logos,
[Constraints]        clean surfaces, single dripper, physically plausible steam.
```

Checklist before sending:
- [ ] One subject focus; counts as numbers ("three cups", not "some cups").
- [ ] Camera/viewpoint and framing stated (close-up, full body, top-down, isometric 30 degrees).
- [ ] Light direction and quality stated; it is the cheapest realism lever.
- [ ] Style named concretely (medium, era, technique), not "beautiful, high quality, 8k".
- [ ] Colours as names plus hex for brand colours.
- [ ] Text: exact string in double quotes, short (under ~6 words per element), font character
      ("bold geometric sans"), placement ("centred top third"); otherwise "no text".
- [ ] Exclusions phrased positively ("plain light-grey seamless background", not "no clutter").
- [ ] No real person's likeness, no third-party logos or trademarks unless supplied as references
      with rights, no living artist's name as a style shortcut.

## 6. References (REF)

Give each reference one role and say it in the prompt, addressing references by position:

| Role | Prompt phrasing | Prep |
|---|---|---|
| Identity (character, face, mascot) | "the character in image 1, same face, hair and outfit" | clean front view, neutral light, nobody else, short side >= 1024 px |
| Product/object fidelity | "the bottle from image 2, keep label layout and colours exactly" | packshot on plain background, tight crop with 5% margin |
| Style | "in the illustration style of image 3 (line weight, palette, texture)" | one or two style refs; more averages the style away |
| Composition/pose | "match the pose and camera angle of image 4" | simple silhouette |
| Palette | "use only the colours of image 5" | swatch strip or mood image |

- Count against the configured tag's limit (model matrix): over the limit is an error, not a silent
  trim. Trim to the strongest references yourself and log what you dropped.
- Large references: data URIs inflate requests (413 on some routers). Downscale to a 2048 px long
  side locally first; it does not hurt conditioning.
- Consistency series: generate the hero, get it to PASS, then add the accepted hero as an extra
  reference for every later frame; keep seed and the style sentence identical, vary only the scene.
- Identity drift after 2 rounds: reduce to the single best identity reference plus the accepted
  hero and move the identity sentence first.

## 7. Transparent assets (TRANSPARENT)

- `image_generate_transparent` returns RGBA when the configured model has native alpha: OpenRouter
  `openai/gpt-image-2.5-sunburst`, `-flare`, `gpt-image-1-mini`, `gpt-5-image(-mini)`,
  `sourceful/riverflow-v2.5-pro`; Opper `openai/gpt-image-2.5-flare`, `-sunburst`, `gpt-image-1.5`,
  `gpt-image-1-mini`. Not `openai/gpt-image-2`, not `riverflow-v2.5-fast` (JPEG only).
- Prompt: "isolated <subject>, <view>, soft even studio light, transparent background, no ground,
  no frame". Native alpha handles soft edges (hair, glass, smoke) and semi-transparent shadows; ask
  for a "soft contact shadow" only if the layout wants one.
- Verify: `expect out.png --alpha`; `info` → `alpha_partial_frac` (soft edge share; above ~0.05 on a
  hard-edged product means fringing); Read it on the contact sheet checkerboard.
- Result opaque: the model ignored the background request (see `notes`); Open doubt with an alpha
  tag. TRANSPARENT not configured: Open doubt; offer GEN on a flat contrasting colour (state the
  hex) followed by `image_remove_background` only as an alternative the caller must approve, since
  the matte depends on the BG_REMOVAL model (approximated on OpenRouter/Opper).

## 8. Aspect ratio and size

Default: `aspect_ratio` plus a `size` tier ('1K', '2K', '4K'). Need exact pixels: pass `size`
'WxH' alone (OpenRouter rejects an exact size that conflicts with `aspect_ratio` or `resolution`;
Opper normalises against the model listing; fal maps it to `image_size`). Also use 'WxH' when
`notes` / `warnings` show the ratio was dropped.

| Use | Aspect | Minimum pixels |
|---|---|---|
| Social square, avatar, product tile | 1:1 | 1024 x 1024 |
| Feed portrait, product card | 4:5 | 1080 x 1350 |
| Story, reel cover, phone wallpaper | 9:16 | 1080 x 1920 |
| Slide, video thumbnail, web hero | 16:9 | 1920 x 1080 |
| Cinematic banner | 21:9 | 2520 x 1080 |
| Web header strip | 4:1 to 8:1 | 3200 px wide |
| Print A-series portrait | 5:7 (~1:1.414) | 300 dpi x print size in inches |

Exact size for M megapixels at ratio r = W/H: `W = round16(sqrt(M * 1e6 * r))`, `H = round16(W / r)`
(round16 = nearest multiple of 16; required by GPT Image, harmless elsewhere). 2.1 MP at 16:9 →
W = round16(1932.4) = 1936, H = round16(1089) = 1088. Validate against the model's allowed sizes
(Opper listing `params.image`, OpenRouter `supported_parameters`).

Slightly different ratio back: crop locally (Pillow via `$PY`) instead of regenerating. Much
smaller than needed: accept the content first, then upscale (image-editing, `image_upscale`; check
whether UPSCALE is native, local or a regeneration).

## 9. Seeds, variants and cost

- Exploration: `n: 3-4`, no seed, `quality` low/medium where the model has it.
- Refinement: fix the seed of the best draft, change one prompt factor per round.
- Final: `n: 1-2`, the accepted prompt verbatim, `quality` high.
- `n` limits: OpenRouter 10, Opper 4 (1 with `async`), fal per endpoint; some models make one call per
  image, so `n` multiplies cost. GPT Image ignores seeds; FLUX on some endpoints has no seed;
  `notes` / `warnings` tell you.
- Reproducibility = same op configuration (adapter + tag) + seed + prompt + references; best effort.
- Budget: at most 4 review rounds and 12 generations per deliverable; then return the best attempt
  with the blocking defect named. At `budget="soft"` finish the current round only.

## 10. Provenance sidecar

The server writes `<file>.json` beside each output. Add your fields under `agent` (the script never
drops the server's keys) right after accepting or rejecting a file:

```bash
"$PY" "$IMG" sidecar .stack/images/20261019/dripper-hero-142233.png \
  --set brief="hero for coffee landing page" --set seed=1234 \
  --set references='[{"path":"refs/dripper.png","role":"product"}]' \
  --set review='{"round":2,"overall":8.6,"verdict":"PASS","reviewer":"visual-reviewer"}'
```

Minimum fields: `brief`, `seed`, `references` (paths + roles), `review` (round, overall, verdict,
reviewer), `supersedes` (previous candidate path for a revision).

## 11. Review loop with visual-reviewer

Every deliverable goes produce → review → revise until it passes. Rubric, anchors, artefact
checklists, revision grammar and stop rules live in the `visual-review` skill that
`visual-reviewer` loads; you supply evidence, apply its revisions and enforce the round count.

1. Self-check first (free): `expect` (aspect, min side, alpha), Read every candidate (a contact
   sheet when n > 2). Drop obvious failures; reviewing a wrong-aspect image is waste.
2. Spawn `visual-reviewer` with Agent and `run_in_background: false` (you need the verdict before
   the next step), one call per round with all surviving candidates:
   ```
   Goal: review these candidates against the brief; verdict PASS, REVISE or STOP with revisions.
   Brief: <the 6-line spec + where it will be used; weights or threshold if the caller set them>
   Outputs: <paths>   References: <paths + role each>   Sidecars: <paths> (they hold the exact prompt)
   Produced by: op=REF adapter=openrouter model=<tag>; approximations from notes: <...>
   Round <k> of 4. Previous review JSON: <path or none>. Threshold 8, no criterion below 6.
   ```
   It writes `.stack/out/visual-reviewer/<stamp>-<slug>-r<k>.md` plus a `.json` (scores, overall,
   lowest, verdict, ordered revisions, KEEP list, trend, best round) and replies with the paths.
3. PASS (overall >= threshold, default 8, and every applicable criterion >= 6): deliver.
4. REVISE: apply the revisions in order, blocking first, without touching anything on the KEEP list.
   Each names an action, owner, tool, op, target, region and the check that proves it:

| Action | Your move |
|---|---|
| `prompt-delta` | edit the exact previous prompt from the sidecar (ADD, REPLACE, REMOVE as given, at most 3), same op, same seed where honoured |
| `param` | same prompt, changed parameter (size, ratio, format, n, seed) |
| References (inside a delta) | swap, crop, reorder or trim references; re-run REF |
| `region-edit`, `cutout-fix`, `upscale` (owner `image-editor`) | do it with `image_edit` / `image_remove_background` / `image_upscale` only if that op is exposed and you know the image-editing procedure; otherwise keep the best candidate and add an Open doubt for `image-editor` with the revision id, file and region |
| `pipeline` (approach cannot reach the brief) | stop and return it to the caller as a scope Open doubt |
| a revision needing an unexposed op | Open doubt naming its env vars; never substitute another op |

5. STOP (or rules you enforce yourself): 4 rounds done; `budget="hard"`; `budget="soft"` unless the
   reviewer allows one cheap local fix; plateau (best overall up < 0.3 in each of the last two rounds); the same
   blocking defect after two strategies (Open doubt: model choice). Regression (overall below the
   best by more than 0.5): revert to the best round's inputs before the next change. Deliver the best
   round (highest overall with no criterion < 6, else highest overall), not the last one.
6. Trail: one JSON line per round in `<output_dir>/review-trail.jsonl`
   (`{"round":2,"files":["..."],"review":"<json path>","overall":8.6,"lowest":7,"verdict":"PASS","change":"R1 spout delta, seed 4242"}`)
   and the final review in the sidecar. The Result lists rounds, scores, the chosen file and every
   revision you could not apply.
7. No spawning possible (`remaining_depth="0"`, spawn denied by policy, or the brief says the review
   happens elsewhere, e.g. you are the produce stage of the `visual-iterate` workflow): do not
   spawn. Self-review with the same seven criteria (brief fidelity, composition and hierarchy,
   typography and legibility, colour and contrast, artefacts, technical spec, consistency with
   references), label it `self-review` in the trail, and unless a workflow reviews you add an Open
   doubt recommending a `visual-reviewer` pass. The main thread can run the whole loop with
   `Workflow name=visual-iterate args={brief, kind: "image", references, threshold: 8, maxRounds: 4}`.

## 12. Worked example

Brief: "Landing-page hero, 16:9, our ceramic dripper (ref provided), warm morning mood, space on
the left for a headline; plus a transparent steam-and-beans illustration for the pricing card."

1. `image_ops_status`: REF exposed (openrouter, `google/gemini-nano-banana-2.1`), TRANSPARENT
   exposed (openrouter, `openai/gpt-image-2.5-flare`), GEN exposed. Matrix: Nano Banana takes 14
   references and seeds; flare has native alpha.
2. Spec pinned. Hero: `image_generate_with_references {prompt: "The dripper from image 1, keep its
   shape, spout and glaze exactly, <section 5 prompt>", references: ["refs/dripper.png"],
   aspect_ratio: "16:9", size: "2K", n: 3, filename_prefix: "hero-v1"}`. No ignored parameters in `notes`.
3. Sheet, Read: one candidate has a cropped handle, dropped. `visual-reviewer` round 1 on the other
   two: best overall 7.2, REVISE; references 5 ("spout visibly shorter than image 1"); R1
   [blocking] prompt-delta ADD "short angled spout exactly as in image 1"; KEEP light and framing.
4. Round 2: the sidecar prompt with R1 applied, `seed: 4242`, `n: 2`.
   Review: overall 8.6, lowest 7, PASS. `expect hero.png --aspect 16:9 --min-side 1080` passes;
   sidecar and trail written.
5. Pricing art: `image_generate_transparent {prompt: "isolated illustration of three roasted coffee
   beans and a curl of steam, flat warm browns #6F4E37 and cream #F3E9DC, soft edges, transparent
   background, no ground, no text", size: "1024x1024"}`. `expect --alpha`
   passes; `alpha_partial_frac` 0.03 (steam only). Review round 1: overall 8.3, PASS.
6. Return both paths, review trail path, scores, seed and tag per file.

## 13. Failure modes

| Symptom | Cause | Action |
|---|---|---|
| Tool absent from your tool list | op not configured, or server not reconnected | `image_ops_status`; Open doubt naming the missing variables or asking for a reconnect |
| Error "not configured" naming env vars | same | Open doubt with those names; never try another route |
| 400 on a parameter | value outside the model's enum, or `size` conflicting with `aspect_ratio` | send fewer knobs (ratio only, or exact size only) |
| 400 when sending references (Opper) | text-to-image-only model | Open doubt for an edit-capable tag on REF |
| 401/403 | key rejected (Opper management keys `op-mak-` are refused) | Open doubt: `IMAGE_<OP>_KEY` rejected by `<host>`; never echo it |
| 402 | out of credits (Opper image models need a card) | Open doubt to the user |
| 404 model not found | tag misspelled or retired (`openai/gpt-image-1` retires 2026-10-23) | Open doubt with a current tag from the listing |
| 413 | references too large as data URIs | downscale references, retry once |
| 429, 502 (OpenRouter), 524/529 | rate limit or upstream failure (not billed) | wait, retry once, then report |
| 504 (Opper) | 3-minute synchronous deadline | retry with `params: {"async": true}` or lower `quality` |
| Aspect ignored | reported in `notes` / `warnings`, or the model snaps to its sizes | pass `size` 'WxH'; within 2% accept (`expect --tol 0.02`) or crop |
| One image although `n` > 1 | `n` ignored by the endpoint | separate calls |
| Opaque although transparency was asked | model has no alpha | Open doubt with an alpha-capable tag |
| Every candidate fails the same criterion | prompt or model limit, not luck | restructure the prompt once; then Open doubt for a better tag; never repeat the same call |
| Output path outside `.stack/images` | `output_dir` mis-set | move each file with its `<file>.json` sidecar; report the new paths |
