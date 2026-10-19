# Model matrix: what each router can do per operation

Snapshot of the OpenRouter and Opper catalogues and the fal endpoints the server supports,
verified 2026-10-19 (live listings, API schemas and probes). Catalogues change monthly: confirm a
tag on the live listing before recommending it ([configuration.md](configuration.md) section 7).
The user's `~/.claude/stack.env` decides which tag each op uses; this file only helps you know
what the configured tag can do and what to recommend.

Legend: **native** = the router has a model built for the op; **approx** = the server emulates the
op with a generative model (results are re-renders, not pixel-exact; the server's fidelity
post-processing limits the damage); **none** = the adapter refuses the op.

## Summary

| Op | OpenRouter | Opper | fal | local |
|---|---|---|---|---|
| GEN | native | native | native | - |
| REF | native | native | native | - |
| EDIT (instruction) | native (source as first input reference) | native (`image`) | native | - |
| EDIT (mask) | approx (mask as an extra reference + composite) | native on mask-capable models | native | - |
| TRANSPARENT | native on alpha models | native on GPT Image | per endpoint | - |
| SEGMENT | approx (`render` mask by an image model, or `detect` boxes) | none | native (SAM 3) | - |
| BG_REMOVAL | approx (transparent re-render + alpha transfer) | approx (same) | native (BRIA, BiRefNet) | - |
| UPSCALE | approx (regenerate at 4K) | approx (regenerate large) | native (Topaz) | Lanczos |
| VECTOR | native (Recraft `*-vector`) | unverified (Recraft V3 vector style) | native (Recraft text-to-vector) | - |
| TRACE | approx (Recraft vector re-draw from 1 reference) | none | native (Recraft vectorize) | vtracer |
| VECTOR_MANIPULATION | any chat model via `/chat/completions` | any chat model via `/v3/compat/chat/completions` | - | `claude` (default) |

## GEN: `image_generate`

| Router | Tags (best first) | Notes |
|---|---|---|
| OpenRouter | `openai/gpt-image-2.5-sunburst`, `google/gemini-nano-banana-2.1`, `black-forest-labs/flux-3-image`, `microsoft/mai-image-2.6`, `bytedance-seed/seedream-5-0-pro`, `qwen/qwen-image-3-pro`; budget `recraft/recraft-v4.1-flash` (~$0.007), `black-forest-labs/flux-3-image-klein` | knobs: `aspect_ratio`, `resolution` (512, 768, 1K, 1.5K, 2K, 4K), `size` (tier or WxH; explicit pixels win, conflicts are 400), `quality` (auto, low, medium, high, xhigh, max), `n` <= 10, `seed`, `output_format`, `output_compression`; send only what the endpoint declares |
| Opper | `openai/gpt-image-2.5-flare`, `vertexai/gemini-3.1-flash-image`, `fal/flux-2-pro`, `bytedance:ap/seedream-5`, `fal/ideogram-v4.5`, `xai/grok-imagine-image-quality`; budget `gemini/gemini-3.1-flash-lite-image`, `pruna/p-image` (~$0.002) | `size` WxH for pixel-sized models (GPT Image, FLUX, Seedream, Ideogram), `aspect_ratio` for Gemini, Pruna, xAI (xAI also `resolution` 1k/2k); `n` <= 4; style keys go in `parameters`, not top level |
| fal | the text-to-image endpoint of the chosen family (find the id on fal.ai/models) | parameters mapped from the endpoint schema; `n` → `num_images` where the endpoint has it |

## REF: `image_generate_with_references`

Maximum input references (OpenRouter, per endpoint): `tencent/hy-image-v3.5-preview` 20;
`openai/gpt-image-*` and `gpt-5*-image` 16; Gemini image models and Seedream 4.5/5.0 14;
`black-forest-labs/flux-3-image`, `flux-3-image-klein`, `riverflow-v2(.5)-pro`, `recraft-v4-styles*`
10 (styles models need at least 1); `krea/k3-edit` 1-8 (needs 1); FLUX.2 pro/flex/max 8;
`microsoft/mai-image-2.6` and `-flash` 5; Qwen Image 3 / 3 Pro / 2.1, riverflow fast and FLUX.2
klein 4b 4; Grok Imagine 3; `gemini-2.5-flash-image` 3; Recraft V3/V4/V4.1 0-1; MAI 2.5 and Krea 2
1; `recraft/recraft-v4.1-flash` none (text only).

| Router | Tags | Notes |
|---|---|---|
| OpenRouter | `google/gemini-nano-banana-2.1` (14), `openai/gpt-image-2.5-sunburst` (16), `bytedance-seed/seedream-5-0-pro` (14), `black-forest-labs/flux-3-image` (10), `tencent/hy-image-v3.5-preview` (20), `recraft/recraft-v4-styles-pro` (style references) | references are objects with `image_url`; address them by order in the prompt ("image 1", "image 2"); some providers bill each reference |
| Opper | `vertexai/gemini-3-pro-image`, `vertexai/gemini-3.1-flash-image`, `openai/gpt-image-2.5-flare`, `bytedance:ap/seedream-5`, `fal/flux-2-pro`, `pruna/p-image-edit` (1-5), `fal/ideogram-v4.5-edit` (4, or 3 with a mask) | text-to-image-only models return 400 when sent images: filter the listing on capability `image_edit` and input modality `image` |
| fal | endpoints with `image_urls` / `reference_image_urls` | count limits in the schema |

## EDIT: `image_edit`

| Router | Instruction edits | Masked edits | Notes |
|---|---|---|---|
| OpenRouter | `krea/k3-edit`, `openai/gpt-image-2.5-sunburst`, `google/gemini-nano-banana-2.1`, `black-forest-labs/flux-3-image`, `qwen/qwen-image-3-pro`, `bytedance-seed/seedream-5-0-pro` | approx: no mask parameter exists; the server sends the mask as a second input reference with "edit only the white region of the mask image", then composites so unmasked pixels stay identical | no `/images/edits` endpoint (404); outputs are full re-renders; with a mask the model needs room for at least 2 references (Recraft and MAI 2.5 cannot) |
| Opper | `openai/gpt-image-2.5-sunburst`, `fal/flux-kontext-pro`, `vertexai/gemini-3.1-flash-image`, `bytedance:ap/seedream-5`, `xai/grok-imagine-image-2.0`, `pruna/p-image-edit`, `fal/recraft-v3-edit` | native: `fal/ideogram-v4.5-edit` (documented mask support), `openai/gpt-image-2.5-sunburst`, `openai/gpt-image-2.5-flare`, `openai/gpt-image-1.5` (GPT Image masks upstream: alpha-transparent = edit) | Opper does not document mask-format conversion between models; the server converts and reports it in `notes`; a mask sent to a non-mask model is a 400 |
| fal | `fal-ai/nano-banana-2.1/edit` and other edit endpoints | `fal-ai/flux-pro/v1/fill` (white = edit), Ideogram edit (black = edit) | the server converts the canonical mask per endpoint |
| openai-compatible | `/images/edits` | alpha-transparent mask | |

Passthrough worth knowing: FLUX Kontext `guidance_scale`, `seed`, `safety_tolerance`; Recraft V3 edit
`style`, `strength` 0-1, `negative_prompt`; GPT Image 1/1.5 `input_fidelity` low/high; Krea K3 edit
`preserve_references`, `skip_prompt_expansion`, `thinking_mode` (OpenRouter `provider.options.krea`);
Ideogram `edit_precision`.

## TRANSPARENT: `image_generate_transparent`

| Router | Tags with native alpha | Avoid |
|---|---|---|
| OpenRouter | `openai/gpt-image-2.5-sunburst`, `openai/gpt-image-2.5-flare`, `openai/gpt-image-1-mini`, `openai/gpt-5-image`, `openai/gpt-5-image-mini`, `sourceful/riverflow-v2.5-pro` | `openai/gpt-image-2` and `openai/gpt-5.4-image-2` (auto/opaque only); `sourceful/riverflow-v2.5-fast` (declares transparent but only outputs JPEG) |
| Opper | `openai/gpt-image-2.5-flare`, `openai/gpt-image-2.5-sunburst`, `openai/gpt-image-1.5`, `openai/gpt-image-1-mini` (via `parameters.background=transparent`) | `openai/gpt-image-2`; `openai/gpt-image-1` (retires 2026-10-23) |
| fal | endpoints whose schema has a transparent background option | |

Alpha needs `output_format` png or webp. Check the OpenRouter endpoint's `background.values` or the
Opper `parameters[name=background].enum` for `transparent`.

## SEGMENT: `image_segment`

| Router | How | Fidelity |
|---|---|---|
| fal | `fal-ai/sam-3/image` (text-prompted SAM 3) | true object masks |
| OpenRouter, strategy `render` (default) | the configured image model is asked to paint a pure black/white mask from the source; the server thresholds and resizes it to the source size | approximate edges; check the overlay every time |
| OpenRouter, strategy `detect` (`IMAGE_SEGMENT_PARAMS='{"strategy":"detect"}'`) | a vision chat model (`moondream/moondream3.1-9b-a2b`, `/detect`) returns normalised boxes; the server rasterises them | rectangles, not shapes: fine for removals with generous masks, poor for cutouts |
| Opper | none (only bounding-box answers from vision LLMs) | configure SEGMENT elsewhere |

## BG_REMOVAL: `image_remove_background`

| Router | Tags | Notes |
|---|---|---|
| fal | `fal-ai/bria/background/remove` (BRIA RMBG 2.0, trained on licensed data), BiRefNet endpoints | true matting |
| OpenRouter | approx: `openai/gpt-image-2.5-sunburst`, `sourceful/riverflow-v2.5-pro` with the source as reference and `background: transparent` | re-render; the server keeps only the returned alpha and puts it on the original pixels (`preserve_pixels`), measuring drift |
| Opper | approx: `openai/gpt-image-2.5-sunburst`, `openai/gpt-image-1.5` (+ `input_fidelity: high`) with `parameters.background=transparent` | same post-processing |

## UPSCALE: `image_upscale`

| Router | Tags | Notes |
|---|---|---|
| fal | `fal-ai/topaz/upscale/image` | true super-resolution |
| local | `IMAGE_UPSCALE_API=local` | Pillow Lanczos: exact, no invented detail, soft at 4x; fine for flat graphics and previews |
| OpenRouter | approx: `black-forest-labs/flux-3-image` (4K; ~$0.61 per image at 4K vs ~$0.05 at 1K), `google/gemini-nano-banana-2.1` (4K), `sourceful/riverflow-v2.5-pro` (4K), `bytedance-seed/seedream-5-0-lite` | regeneration: text, faces and fine texture can change; output size is the model's tier, not an exact multiple |
| Opper | approx: `openai/gpt-image-2` (`size` up to 3840 on the long edge, multiple of 16), `vertexai/gemini-3.1-flash-image` / `gemini-3-pro-image` (`quality: 4k`), `tencent:sg/hy-image-3.5-preview` (4096x4096) | same caveats; use `async` for slow jobs |

## VECTOR: `vector_generate`

| Router | Tags | Notes |
|---|---|---|
| OpenRouter | `recraft/recraft-v4.1-vector` (~$0.08), `recraft/recraft-v4.1-pro-vector` (~$0.30, complex illustrations), `recraft/recraft-v4-vector`, `recraft/recraft-v4-pro-vector`, `recraft/recraft-v4-styles-vector` (~$0.05, needs 1-10 style references), `recraft/recraft-v4-styles-pro-vector` (~$0.12) | the only OpenRouter models with `output_format: svg`; response media type `image/svg+xml`; aspect ratios 1:1, 4:3, 3:4, 16:9, 9:16, auto; `n` <= 6; passthrough `provider.options.recraft`: `style`, `controls`, `text_layout` |
| fal | `fal-ai/recraft/v4.1/text-to-vector` | native SVG |
| Opper | `fal/recraft-v3` with `parameters.style` `vector_illustration` is unverified to return SVG (it may return a raster); `deepinfra/Bria/Bria-3.2-vector` returns WebP, not SVG | if the result is not SVG, reconfigure VECTOR on OpenRouter or fal |

## TRACE: `image_vectorize`

| Router | Tags | Notes |
|---|---|---|
| fal | `fal-ai/recraft/vectorize` | real trace; PNG/JPG/WEBP under 5 MB and 16 MP, 256-4096 px per side |
| local | `IMAGE_TRACE_API=local` (vtracer) | real trace, free, deterministic; palette follows the input, so pre-quantise |
| OpenRouter | approx: `recraft/recraft-v4.1-vector` or `-pro-vector` with the raster as the single reference | a redraw "in the style of" the input, not a trace: shapes and proportions drift; never use for logos that must stay identical |
| Opper | none | |

## VECTOR_MANIPULATION: `svg_transform`

Default `claude` (no tool; agents edit the SVG). External: any capable chat model behind an
OpenAI-compatible `{URL}/chat/completions`, e.g. URL `https://openrouter.ai/api/v1` with a chat
model tag, or URL `https://api.opper.ai/v3/compat` with a model from `GET /v3/models`. The server
validates that the reply is well-formed SVG before writing it.

## Model families (what to expect from the configured tag)

| Family | Strengths | Weak spots and limits |
|---|---|---|
| GPT Image 2.5 (sunburst = quality, flare = fast/cheap) | instruction following, in-image text, precise edits, native alpha, 16 references | sizes multiples of 16, ratio 1:3..3:1, edges <= 3840; no seed determinism; `max` quality takes minutes and costs about 16x `medium` |
| GPT Image 2 | strong general quality | no transparent background |
| Nano Banana 2.1 / Gemini 3.1 Flash Image / Gemini 3 Pro Image | cheap and fast (Pro: professional finish, text), long-prompt understanding, multi-reference fusion (14), 4K, ratios down to 1:8 and up to 8:1 | opaque only; Opper returns JPEG |
| FLUX 3 Image (Klein = budget) / FLUX.2 Pro | photoreal materials and light, layout control by position, 10 references | opaque; 4K is about 12x the 1K price |
| Seedream 5 (pro, lite, flash) | multi-reference consistency, coherent image sets | opaque |
| Qwen Image 3 (Pro) | ordered references addressed as image 1..4, good value | few references |
| Ideogram 4.5 (and edit) | typography, posters, logos as raster; mask edits on Opper | 4 references, 3 with a mask |
| Recraft V4.1 (raster, `-vector`, `-pro-vector`, styles) | brand and flat illustration, house styles, native SVG | 0-1 references (styles: 1-10 style references required) |
| Krea K3 edit | instruction edits that keep references | needs at least 1 reference |
| MAI Image 2.6 | high general quality (ranked near the top in mid-2026 arenas) | 5 references |
| Riverflow 2.5 pro | 4K, alpha | fast variant: JPEG only |
| HY Image 3.5 preview | most references (20), large sizes | preview model |

## Prices (catalogue, 2026-10-19; per image unless noted)

OpenRouter: `recraft-v4.1-flash` ~$0.007; FLUX 3 ~$0.048 at 1K, ~$0.607 at 4K; Recraft vector $0.08
(pro $0.30; styles $0.05 / $0.12 plus $0.005 per reference). Opper: `pruna/p-image` $0.002,
`pruna/p-image-edit` $0.01, Seedream 5 flash $0.018, Seedream 5 $0.035, FLUX Kontext Pro $0.04,
Recraft V3 $0.04 ($0.08 vector styles), Ideogram 4.5 $0.03 / $0.06 / $0.22 (low / medium / high),
GPT Image 1.5 $0.009-$0.133 at 1024²; GPT Image 2.5 token-billed ($30 per million output image
tokens); Gemini 3.1 Flash Image $60 and Gemini 3 Pro Image $120 per million output image tokens.

## Lifecycle (2026-10)

- `openai/gpt-image-1` retires 2026-10-23; GPT Image 1.5 and 1-mini retire 2026-12-01 (OpenAI).
- Opper retired Imagen (`gemini/imagen-4.0-*` and `*-image-preview` names 2026-10-18,
  `vertexai/imagen-*-eu` 2026-06-30) and DALL-E 2/3 (2026-05-12).
- OpenRouter lists `meta/muse-image` but it has no routable endpoint; newest entries (Oct 2026):
  `qwen/qwen-image-2.1-pro`/`-turbo`, `krea/k3-edit`, `black-forest-labs/flux-3-image(-klein)`,
  `google/gemini-nano-banana-2.1`, `tencent/hy-image-v3.5-preview`, `bytedance-seed/seedream-5-0-flash`.
- A 404 "model not found" from a configured tag means rename or retirement: recommend a current
  tag in an Open doubt; never edit the user's configuration.
