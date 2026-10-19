# Image server configuration: one endpoint per operation, no fallbacks

Shared reference for the image-generation, image-editing and vector-art skills. It explains how
the `image` MCP server is configured, how to read `image_ops_status`, how to word an Open doubt
when an operation is missing, and how to pick model tags on OpenRouter, Opper and fal.
Facts about the routers were verified on 2026-10-19; per-model capabilities are in
[model-matrix.md](model-matrix.md).

## 1. How the server works

- One stdio MCP server named `image`, declared in `.mcp.json`, launched as
  `bin/mcp-run bin/image-router`. `bin/mcp-run` parses `~/.claude/stack.env` (path overridable with
  `CLAUDE_STACK_ENV`) and never sources it. Tool ids are `mcp__image__<tool>`.
- Each operation (op) has its own block of variables. The server evaluates them at start-up
  (the env file plus the process environment): an op's tool is registered only when its URL, KEY
  and MODEL are all set, or when `IMAGE_<OP>_API=local` for the two ops that allow it (TRACE,
  UPSCALE). An op that is not configured has no tool at all; there is nothing to call by mistake.
- Every call uses exactly the configured endpoint and model tag, and nothing else: if that model
  fails, the call fails with the router's error, and nothing is retried on another provider.
- Local tools need no configuration and are always registered: `image_ops_status`,
  `image_info`, `mask_convert`, `svg_inspect`, `svg_optimize`, `svg_render`, `svg_layers`,
  `svg_layerize`, `layers_compose`, `export_pdf`.
- After the user edits `stack.env`, a newly configured op appears when the server re-evaluates
  its configuration. If the MCP client supports `tools/list_changed` the server refreshes when the
  file changes; otherwise the user reconnects the server (`/mcp` in interactive Claude Code, or a
  new `bin/stack-sdk run`). Subagents cannot do this themselves.
- Outputs go to `output_dir` (default `.stack/images/<YYYYMMDD>/` under `CLAUDE_PROJECT_DIR` or
  the working directory). Each file gets a `<file>.json` sidecar: op, adapter, URL host, model tag,
  prompt or instruction, params (without secrets or base64), inputs, created time.
- Keys never leave the server: results, errors and sidecars show only the URL host and the model
  tag. Agents never read, print or quote `~/.claude/stack.env`; `image_ops_status` is their only view
  of the configuration (names only via `bin/stack keys` for the user).

## 2. Operations

| Op (env prefix) | Tool | Purpose | `_API=local` |
|---|---|---|---|
| `IMAGE_GEN` | `image_generate` | text to image | no |
| `IMAGE_REF` | `image_generate_with_references` | generation guided by 1..N reference images | no |
| `IMAGE_EDIT` | `image_edit` | instruction edit; masked inpaint when `mask` is given, with unmasked pixels preserved | no |
| `IMAGE_TRANSPARENT` | `image_generate_transparent` | RGBA output (stickers, cutout assets, UI art) | no |
| `IMAGE_SEGMENT` | `image_segment` | prompt to white-on-black mask at the source size (`IMAGE_MASK_*` is a deprecated alias) | no |
| `IMAGE_BG_REMOVAL` | `image_remove_background` | RGBA cutout; alpha transferred onto the original pixels | no |
| `IMAGE_UPSCALE` | `image_upscale` | enlargement | yes: Pillow Lanczos, deterministic, no detail synthesis |
| `IMAGE_VECTOR` | `vector_generate` | native SVG generation, optionally layered | no |
| `IMAGE_TRACE` | `image_vectorize` | raster to SVG tracing, optionally one layer per colour | yes: vtracer (MIT), deterministic |
| `IMAGE_VECTOR_MANIPULATION` | `svg_transform` | SVG edit by an external model; registered only when the model is set and is not `claude` | no |

`IMAGE_VECTOR_MANIPULATION_MODEL=claude` is the default: agents edit SVG text themselves with Read
and Edit, checked with `svg_inspect`, `svg_render` and `svg_optimize` (vector-art skill).

## 3. Variables per op

| Variable | Required | Meaning |
|---|---|---|
| `IMAGE_<OP>_URL` | yes (not with `_API=local`) | base URL of the router: `https://openrouter.ai/api/v1`, `https://api.opper.ai`, `https://queue.fal.run`, or any OpenAI-compatible base URL |
| `IMAGE_<OP>_KEY` | yes (not with `_API=local`) | the router's API key (OpenRouter key, Opper runtime key `op-...`, fal key) |
| `IMAGE_<OP>_MODEL` | yes | the model tag exactly as the router lists it (`openai/gpt-image-2.5-sunburst`, `fal/ideogram-v4.5-edit`, `fal-ai/bria/background/remove`) |
| `IMAGE_<OP>_API` | no | force the adapter: `openrouter`, `opper`, `openai`, `fal`, `local` (local only for TRACE and UPSCALE) |
| `IMAGE_<OP>_PARAMS` | no | JSON object merged into every request of that op, e.g. `'{"quality":"high"}'` |

Parsing follows `stack/envfile.py`: `KEY=VALUE` lines, optional `export `, single or double
quotes, an inline ` # comment` after whitespace is ignored. Quote JSON values in single quotes.

Adapter detection when `_API` is unset: host `openrouter.ai` → `openrouter`; `opper.ai` → `opper`;
`fal.run`, `queue.fal.run` or `*.fal.ai` → `fal`; anything else → `openai` (generic
OpenAI-compatible).

## 4. Adapters

| Adapter | Endpoint and auth | Inputs | Masks | Output | Ops it serves |
|---|---|---|---|---|---|
| `openrouter` | `POST {URL}/images`, `Authorization: Bearer KEY` (+ `HTTP-Referer`, `X-OpenRouter-Title`) | `input_references: [{"type":"image_url","image_url":{"url":"data:..."}}]` (objects, never bare strings; png, jpeg, webp, gif) | none in the API: the mask is sent as an extra input reference with an explicit "edit only the white region" instruction, then the server composites (image-editing skill, section 5) | `data[].b64_json` + `media_type` (SVG arrives as base64 UTF-8 markup); synchronous, no URLs | GEN, REF, EDIT, TRANSPARENT (`background: transparent`), VECTOR (`output_format: svg`); SEGMENT, BG_REMOVAL, UPSCALE, TRACE only as approximations |
| `opper` | `POST {URL}/v3/images`, `Authorization: Bearer KEY` (runtime key `op-...`; `op-mak-` management keys are rejected) | `image` (string), `mask` (string), `reference_images` (array): data URIs, https URLs or `file_<id>` | `mask` field; honoured by mask-capable models (`fal/ideogram-v4.5-edit`, GPT Image edit models); a non-mask model returns 400 | `data[].b64_json` + `mime_type` (Gemini returns JPEG); sync deadline 3 min (504, not billed), `async: true` → 202 and polling of `/v3/artifacts/{id}/status` | GEN, REF, EDIT, TRANSPARENT (`parameters.background`); BG_REMOVAL, UPSCALE only as approximations; no segmentation or tracing model |
| `openai` | `POST {URL}/images/generations` (JSON) and `{URL}/images/edits` (multipart `image[]`, `mask`, `prompt`, `model`, `background`, `output_format`, `size`, `n`) | multipart files | alpha-transparent = edit | `data[].b64_json` or `url` | GEN, REF, EDIT, TRANSPARENT; `svg_transform` uses `{URL}/chat/completions` |
| `fal` | queue API: `POST {URL}/{model}` with `Authorization: Key KEY`, poll `status_url`, fetch `response_url`, download every returned URL | data URIs mapped to the endpoint's fields (`image_url`, `image_urls`, `reference_image_urls`, `mask_url`) from its live OpenAPI schema | per endpoint (FLUX Fill white = edit, Ideogram black = edit), converted by the server | files downloaded from fal | every op natively when the endpoint exists: background removal, SAM segmentation, Topaz upscale, Recraft vectorize, Recraft text-to-vector, FLUX Fill |
| `local` | none | local files | n/a | deterministic | UPSCALE (Lanczos), TRACE (vtracer) |

Each adapter declares the ops it supports. An op configured against an adapter that cannot do
it fails with a clear message (for example SEGMENT on Opper); it never silently goes elsewhere.
Unknown or unsupported parameters are dropped and reported in the result's `notes` / `warnings` (fal maps by the
endpoint schema; OpenRouter accepts unknown keys without complaint, so check the result).

## 5. Reading `image_ops_status`

For every op it returns: whether the tool is exposed, the adapter, the URL host, the model tag and
the exact env names that are missing. Decide with this table:

| Status | Meaning | Action |
|---|---|---|
| exposed, adapter and tag as expected | ready | proceed; check the tag in the model matrix for limits |
| not exposed, `missing: [IMAGE_X_URL, ...]` | the user has not configured it | Open doubt naming exactly those variables, with a suggested URL and tag |
| configured but the tool is not in your tool list | server started before the edit | Open doubt: reconnect the `image` server |
| exposed but the adapter cannot do this op (e.g. SEGMENT with `opper`) | misconfiguration | the call fails with a message; Open doubt suggesting a router that can (fal, or OpenRouter's approximation) |
| exposed with a model tag that lacks a needed feature (no alpha, no mask, too few references, raster-only for VECTOR) | wrong model | try once only if the brief can still pass; otherwise Open doubt with a tag that has the feature |
| `IMAGE_VECTOR_MANIPULATION` model `claude` | default | edit SVG yourself; `svg_transform` does not exist |

## 6. Open doubt templates

Use the doubt-escalation line format, route `user`, `Status: partial` (or `blocked` when nothing
else can proceed). Name only variables; never ask for, accept or repeat a key value.

```
- [scope|high] IMAGE_SEGMENT is not configured (image_segment not exposed; missing IMAGE_SEGMENT_URL, IMAGE_SEGMENT_KEY, IMAGE_SEGMENT_MODEL) - the mask for the removal cannot be made by prompt; I used a hand-drawn polygon instead / the step is blocked - resolve: set them in ~/.claude/stack.env, e.g. URL https://queue.fal.run with MODEL fal-ai/sam-3/image, then reconnect the image server (/mcp) - route: user
- [scope|med] IMAGE_EDIT_MODEL=<tag> on OpenRouter has no native masks (approximated) - fine detail at the mask edge drifted twice - resolve: point IMAGE_EDIT at Opper (https://api.opper.ai, fal/ideogram-v4.5-edit) or fal (fal-ai/flux-pro/v1/fill) for true inpainting - route: user
- [scope|med] image_generate_transparent is configured but not in my tool list - the server started before the edit - resolve: reconnect the image server (/mcp) - route: user
```

Substituting one op for another (GEN on a flat colour + `image_remove_background` instead of
TRANSPARENT; a regenerated "upscale" instead of a real upscaler) changes the quality of the
deliverable. Offer it in the Open doubt; do it only when the caller approved it.

## 7. Choosing a model tag

Procedure (for your recommendation in an Open doubt, or when the user asks which tag to set):

1. Name the op and the hard requirements: alpha, mask, number of references, SVG output,
   maximum aspect ratio, resolution, in-image text, price ceiling.
2. Read the op's table in [model-matrix.md](model-matrix.md) for the shortlist per router.
3. Confirm on the live listing (public, no key needed) that the tag still exists and declares the
   feature. Run these yourself only if you have network access in Bash; otherwise ask
   `quick-researcher` with the exact question.

```bash
# OpenRouter: catalogue of image models, then one model's per-endpoint parameters
curl -s https://openrouter.ai/api/v1/images/models | jq -r '.data[].id' | sort
curl -s https://openrouter.ai/api/v1/images/models/openai/gpt-image-2.5-sunburst/endpoints \
  | jq '.data.endpoints[] | {provider_tag, supported_parameters}'
# Opper: catalogue with per-model params (sizes or aspect ratios, qualities, passthrough enums)
curl -s https://api.opper.ai/v3/images/models | jq -r '.models[] | .name // .id' | sort
curl -s https://api.opper.ai/v3/images/models | jq '.models[] | select((.name // .id) == "fal/ideogram-v4.5-edit")'
# fal: endpoint schema (inputs, enums, defaults); browse ids at https://fal.ai/models
curl -s 'https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=fal-ai/bria/background/remove' | jq '.components.schemas | keys'
```

Response shapes change; if a `jq` path returns null, print `keys` of the top object first.

What to check per router:

| Router | Where the truth is | Check |
|---|---|---|
| OpenRouter | `GET /api/v1/images/models/{author}/{slug}/endpoints` → `endpoints[].supported_parameters` (typed: enum values, ranges, booleans; a missing key means unsupported); the model-level map is only a union | `input_references` {min,max}; `background.values` contains `transparent`; `output_format` has `svg` (VECTOR) or png/webp (alpha); `aspect_ratio`/`resolution`/`size` values; price per image |
| Opper | `GET /v3/images/models` → `models[].params.image` (allowed sizes or aspect ratios, qualities, size constraints, passthrough `parameters` with enums), `capabilities` (`image_edit`), `input_modalities` (`image`); `?deprecated=true` shows `retired_at` | `parameters[name=background].enum` has `transparent`; edit capability for EDIT/REF; mask support in the description; size vocabulary |
| fal | OpenAPI schema per endpoint id | input field names (`image_url`, `mask_url`, `image_urls`), enum values, output shape; mask convention in the endpoint docs |

Quick-start blocks the user can paste (keys elided):

```bash
# Everything generative on OpenRouter, precision ops on fal, tracing local
IMAGE_GEN_URL=https://openrouter.ai/api/v1
IMAGE_GEN_KEY=...
IMAGE_GEN_MODEL=google/gemini-nano-banana-2.1
IMAGE_REF_URL=https://openrouter.ai/api/v1
IMAGE_REF_KEY=...
IMAGE_REF_MODEL=openai/gpt-image-2.5-sunburst
IMAGE_TRANSPARENT_URL=https://openrouter.ai/api/v1
IMAGE_TRANSPARENT_KEY=...
IMAGE_TRANSPARENT_MODEL=openai/gpt-image-2.5-flare
IMAGE_EDIT_URL=https://api.opper.ai          # true masks via Ideogram edit
IMAGE_EDIT_KEY=...
IMAGE_EDIT_MODEL=fal/ideogram-v4.5-edit
IMAGE_SEGMENT_URL=https://queue.fal.run
IMAGE_SEGMENT_KEY=...
IMAGE_SEGMENT_MODEL=fal-ai/sam-3/image
IMAGE_BG_REMOVAL_URL=https://queue.fal.run
IMAGE_BG_REMOVAL_KEY=...
IMAGE_BG_REMOVAL_MODEL=fal-ai/bria/background/remove
IMAGE_UPSCALE_API=local                      # or fal-ai/topaz/upscale/image on fal
IMAGE_VECTOR_URL=https://openrouter.ai/api/v1
IMAGE_VECTOR_KEY=...
IMAGE_VECTOR_MODEL=recraft/recraft-v4.1-vector
IMAGE_TRACE_API=local                        # or fal-ai/recraft/vectorize on fal
IMAGE_VECTOR_MANIPULATION_MODEL=claude
```

`IMAGE_<OP>_PARAMS` examples:

| Use | Value |
|---|---|
| Higher quality on every GEN call | `IMAGE_GEN_PARAMS='{"quality":"high"}'` |
| Keep an OpenRouter request on one upstream provider | `IMAGE_GEN_PARAMS='{"provider":{"only":["openai"],"allow_fallbacks":false}}'` |
| Recraft style for SVG generation (OpenRouter) | `IMAGE_VECTOR_PARAMS='{"provider":{"options":{"recraft":{"style":"<style>"}}}}'` |
| Detect-box segmentation on OpenRouter (chat vision model) | `IMAGE_SEGMENT_PARAMS='{"strategy":"detect"}'` with `IMAGE_SEGMENT_MODEL=moondream/moondream3.1-9b-a2b` |
| Higher input fidelity for GPT Image 1.5 edits on Opper | `IMAGE_EDIT_PARAMS='{"parameters":{"input_fidelity":"high"}}'` |
| Slow, high-quality Opper jobs (avoids the 3-minute 504) | `IMAGE_GEN_PARAMS='{"async":true}'` (one image per request) |

## 8. Bring your own key (BYOK)

| Router | What `IMAGE_<OP>_KEY` is | Provider keys | Notes |
|---|---|---|---|
| OpenRouter | the OpenRouter API key | attached to the OpenRouter workspace (settings, integrations, or `POST /api/v1/byok` with a management key); never sent per request | BYOK keys are tried before shared capacity; set `is_required` or `is_byok_only` on the key to forbid falling back to shared capacity; fee 5% of list price; `usage.is_byok` in responses shows which key paid |
| Opper | an Opper runtime key (`op-...`) | registered as project "custom models" (dashboard or `/v2/models/custom`); whether `/v3/images` uses them is undocumented | image models are premium: a card and credits are needed; no markup, a fee on credit purchases |
| fal | the fal key | n/a | billed per endpoint |
| openai-compatible | that service's key | n/a | |

OpenRouter's provider routing (several upstream hosts of the same model) is internal to one model
tag; pin it with `provider.only` and `allow_fallbacks: false` if the user wants one host only.

## 9. Errors

| Error | Meaning | Action |
|---|---|---|
| "not configured" naming env vars | op has no URL/KEY/MODEL | Open doubt with those names |
| 400 schema or parameter error | parameter value outside the model's enum, conflicting `size` and `aspect_ratio` (OpenRouter), image or mask sent to a text-to-image-only model (Opper) | fix or drop the parameter; if the model cannot take the input, Open doubt for a tag that can |
| 401 / 403 | key missing, wrong or the wrong kind (Opper management key) | Open doubt: `IMAGE_<OP>_KEY` rejected by `<host>`; never echo it |
| 402 | out of credits | Open doubt to the user |
| 404 model not found | tag misspelled or retired | Open doubt with a current tag from the listing |
| 413 | request too large (references as data URIs) | downscale references locally (long side 2048 px) and retry once |
| 429 | rate limited (`Retry-After`) | wait, retry once, then report |
| 502 (OpenRouter), 524/529 | upstream generation failed (not billed) | retry once, then report |
| 504 (Opper) | 3-minute synchronous deadline (not billed) | retry with `params: {"async": true}` or a lower `quality` |
| Result is raster where SVG was expected | VECTOR/TRACE model is not a vector model | Open doubt: pick a `*-vector` tag or fal Recraft |
