export const meta = {
  name: 'visual-iterate',
  description: 'Visual iteration loop over the image MCP server: each round a producer (image-generator, image-editor or vector-artist) makes an attempt from the brief, the previous best and the reviewer revision instructions; visual-reviewer scores it with the visual-review rubric (fidelity, composition, typography, colour, artefacts, technical, references; weight profile fixed in round 1); the weighted overall and the PASS rule are recomputed in code; the best attempt is kept; stops on PASS, maxRounds, a plateau (best overall up < 0.3 in two consecutive rounds), a reviewer STOP or a low token budget; optional layered SVG and layered PDF export of the best attempt.',
  whenToUse: 'A picture or an SVG must reach a quality bar and is worth several produce-review rounds: hero images, logos, icons, product cutouts, edits that must leave the rest untouched, editable layered deliverables. Main thread only. args {brief, kind: "image"|"vector", mode?: "generate"|"edit" (default edit when source is given), source?: path, references?: [path or URL], output?: {layered?: bool, pdf?: bool}, threshold?: 8 (1-10), maxRounds?: 4 (1-6), runTag?}. Needs the operations the job uses configured in ~/.claude/stack.env (IMAGE_<OP>_URL/KEY/MODEL); an unconfigured operation stops the run with an Open doubt naming the variables, never a fallback. For a single quick image call the image agent directly.',
  phases: [
    { title: 'Produce', detail: 'the producer starts with image_ops_status, makes 1-3 candidates for the round into its own output directory (round 1 from the brief and source, later rounds from the previous best plus the reviewer revision instructions) and returns paths; an unconfigured operation returns status blocked with the missing env names' },
    { title: 'Review', detail: 'visual-reviewer inspects every candidate (image_info, svg_inspect, svg_render, Read), scores the best one 0-10 per criterion with the visual-review anchors and caps, writes its report (.md + .json) to disk and returns verdict PASS, REVISE or STOP with precise revision instructions; overall and pass are recomputed in code (weighted mean of applicable criteria >= threshold, no applicable criterion below 6, no blocker, reviewer agrees)' },
    { title: 'Export', detail: 'optional: the producer (image-editor when a raster must be split into layers) turns the best attempt into a layered SVG (svg_layerize or layers_compose) and/or a PDF (export_pdf, one Optional Content Group per layer) without changing its appearance' },
  ],
}

// ---------------------------------------------------------------------------
// Sequential loop (each round depends on the previous review):
//   Produce(r) -> Review(r) -> keep best (pass, no criterion < 6, overall, fewer
//   blocking revisions, later round) -> stop on pass, maxRounds, a reviewer STOP,
//   or STALL_LIMIT consecutive rounds that raise the best overall by < MIN_GAIN.
// Rubric, weight profiles, PASS rule and plateau rule are the visual-review
// skill's (sections 3, 5 and 9); scores are recomputed in code so the stop rule
// is deterministic. The weight profile is fixed by the first review.
// ---------------------------------------------------------------------------

const notes = []
function note(msg) { notes.push(msg); log(msg) }

// ---------------------------------------------------------------------------- constants
const CRITERIA = ['fidelity', 'composition', 'typography', 'colour', 'artefacts', 'technical', 'references']
// visual-review skill section 3 (percent; null = not applicable for that output type)
const PROFILES = {
  'default':         { fidelity: 25, composition: 15, typography: 10, colour: 10, artefacts: 15, technical: 15, references: 10 },
  'photoreal':       { fidelity: 25, composition: 15, typography: 5, colour: 10, artefacts: 20, technical: 10, references: 15 },
  'illustration':    { fidelity: 25, composition: 20, typography: 5, colour: 15, artefacts: 15, technical: 10, references: 10 },
  'typography-logo': { fidelity: 20, composition: 15, typography: 25, colour: 10, artefacts: 10, technical: 15, references: 5 },
  'icon-vector':     { fidelity: 20, composition: 15, typography: 5, colour: 15, artefacts: 15, technical: 25, references: 5 },
  'cutout':          { fidelity: 15, composition: 5, typography: null, colour: 5, artefacts: 35, technical: 25, references: 15 },
  'mask':            { fidelity: 30, composition: null, typography: null, colour: null, artefacts: 30, technical: 30, references: 10 },
  'edit':            { fidelity: 25, composition: 10, typography: 5, colour: 10, artefacts: 20, technical: 10, references: 20 },
  'upscale':         { fidelity: 10, composition: null, typography: 5, colour: 10, artefacts: 35, technical: 20, references: 20 },
}
const PROFILE_NAMES = Object.keys(PROFILES)
const LAYERED_TECHNICAL_BONUS = 10   // layered SVG/PDF deliverables: content profile with technical +10
const OPTIONAL_CRITERIA = ['typography', 'references']   // a reviewer may mark these N/A (references only with no reference and no source)
const MIN_CRITERION = 6        // no applicable criterion may score below this for a pass
const MIN_GAIN = 0.3           // plateau: a gain of the best overall smaller than this does not count as an improvement
const STALL_LIMIT = 2          // consecutive non-improving rounds before the loop stops
const DEFAULT_THRESHOLD = 8
const DEFAULT_ROUNDS = 4
const MAX_ROUNDS_CAP = 6
const MAX_CANDIDATES = 4       // candidates per round the reviewer looks at
const MAX_REFERENCES = 8
const MAX_REVISIONS = 10
const BRIEF_CAP = 6000
const ROUND_MIN_BUDGET = 150000   // tokens; below this (with a budget set) no new round starts
const EXPORT_MIN_BUDGET = 60000
const RASTER_EXT = /\.(png|jpe?g|webp|gif|tiff?|bmp|avif|heic)$/i
const SVG_EXT = /\.svgz?$/i
const SIDECAR_EXT = /\.(json|md|txt|log|yaml|yml)$/i
const ENV_RE = /^IMAGE_[A-Z][A-Z_]*_(URL|KEY|MODEL|API|PARAMS)$/
const OP_TOOLS = {
  GEN: 'image_generate', REF: 'image_generate_with_references', EDIT: 'image_edit', TRANSPARENT: 'image_generate_transparent',
  SEGMENT: 'image_segment', BG_REMOVAL: 'image_remove_background', UPSCALE: 'image_upscale', VECTOR: 'vector_generate',
  TRACE: 'image_vectorize', VECTOR_MANIPULATION: 'svg_transform',
}
const LOCAL_TOOLS = ['image_ops_status', 'image_info', 'mask_convert', 'svg_inspect', 'svg_optimize', 'svg_render', 'svg_layers', 'svg_layerize', 'layers_compose', 'export_pdf']
const PRODUCERS = { 'image:generate': 'image-generator', 'image:edit': 'image-editor', 'vector:generate': 'vector-artist', 'vector:edit': 'vector-artist' }

// ---------------------------------------------------------------------------- helpers
function isStr(v) { return typeof v === 'string' && v.trim().length > 0 }
function clip(s, n) { s = String(s == null ? '' : s); return s.length > n ? s.slice(0, n) + '…' : s }
function oneLine(s, n) { return clip(String(s == null ? '' : s).replace(/\s+/g, ' ').trim(), n) }
function round2(x) { return Math.round(x * 100) / 100 }
function toNum(v) {
  if (v === null || v === undefined || v === '' || typeof v === 'boolean') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}
function slugify(s, max) {
  const n = max || 40
  const t = String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
  if (t.length <= n) return t || 'visual'
  const cut = t.slice(0, n)
  const at = cut.lastIndexOf('-')
  return (at >= n / 2 ? cut.slice(0, at) : cut).replace(/-+$/g, '') || 'visual'
}
function parseMaybeJson(v) {
  if (typeof v !== 'string') return { ok: true, value: v }
  const t = v.trim()
  if (!t.startsWith('{') && !t.startsWith('[')) return { ok: true, value: v }
  try { return { ok: true, value: JSON.parse(t) } } catch (e) { return { ok: false, error: e.message } }
}
function strList(v, cap, each) {
  if (!Array.isArray(v)) return []
  const out = []
  const seen = new Set()
  for (const x of v) {
    if (!isStr(x)) continue
    const s = oneLine(x, each)
    if (seen.has(s)) continue
    seen.add(s)
    out.push(s)
    if (out.length >= cap) break
  }
  return out
}
function lowBudget(min) { return !!(typeof budget !== 'undefined' && budget && budget.total && budget.remaining() < min) }
function cleanOpts(o) {
  const r = {}
  for (const k of Object.keys(o)) if (o[k] !== undefined && o[k] !== null && o[k] !== '') r[k] = o[k]
  return r
}
async function call(prompt, opts) {
  try {
    return await agent(prompt, cleanOpts(opts))
  } catch (e) {
    note(`${opts.label}: agent call failed (${oneLine((e && e.message) || e, 160)})`)
    return null
  }
}
function envNames(op) { return ['IMAGE_' + op + '_URL', 'IMAGE_' + op + '_KEY', 'IMAGE_' + op + '_MODEL'] }
function srcType(p) { return !isStr(p) ? 'none' : (SVG_EXT.test(p) ? 'svg' : (RASTER_EXT.test(p) ? 'raster' : 'unknown')) }

// ---------------------------------------------------------------------------- args
const EXAMPLE = '{"brief": "16:9 hero image of a lighthouse at dusk, warm light, empty left third for a headline", "kind": "image", "output": {"pdf": true}}'
const USAGE = 'Main thread only: call the Workflow tool with name "visual-iterate" and args {brief, kind: "image"|"vector", mode?: "generate"|"edit" (default edit when source is given), source?: path, references?: [path or URL], output?: {layered?: bool, pdf?: bool}, threshold?: 8 (1-10), maxRounds?: 4 (1-6), runTag?}. Example: ' + EXAMPLE
function bad(reason) { return { started: false, reason, next: USAGE } }

let A = args
if (A === undefined || A === null || A === '') A = {}
if (typeof A === 'string') {
  const pa = parseMaybeJson(A)
  if (!pa.ok) return bad('args is a string that looks like JSON but does not parse: ' + pa.error)
  A = typeof pa.value === 'string' ? { brief: pa.value } : pa.value
}
if (!A || typeof A !== 'object' || Array.isArray(A)) return bad('args must be a JSON object')

const BRIEF_RAW = isStr(A.brief) ? A.brief.trim() : ''
if (!BRIEF_RAW) return bad('args.brief (non-empty string) is required: what the picture or SVG must show, its size or aspect ratio, style, text, and what must not change')
const BRIEF = clip(BRIEF_RAW, BRIEF_CAP)
if (BRIEF_RAW.length > BRIEF_CAP) note(`brief clipped to ${BRIEF_CAP} characters; put long specifications in a file and reference its path in the brief`)

const KIND = isStr(A.kind) ? A.kind.trim().toLowerCase() : ''
if (KIND !== 'image' && KIND !== 'vector') return bad('args.kind must be "image" (raster PNG/JPEG/WebP) or "vector" (SVG); got ' + JSON.stringify(A.kind === undefined ? null : A.kind))

let SOURCE = isStr(A.source) ? A.source.trim() : ''
if (A.source !== undefined && A.source !== null && A.source !== '' && !SOURCE) return bad('args.source must be a path string')
if (/^data:/i.test(SOURCE)) return bad('args.source must be a path or URL, not an inline data URI (context policy: pass paths)')

let MODE = isStr(A.mode) ? A.mode.trim().toLowerCase() : (SOURCE ? 'edit' : 'generate')
if (MODE !== 'generate' && MODE !== 'edit') return bad('args.mode must be "generate" or "edit"; got ' + JSON.stringify(A.mode))
if (MODE === 'edit' && !SOURCE) return bad('mode "edit" needs args.source: the path of the image or SVG to change')

let refsIn = A.references
if (typeof refsIn === 'string') {
  const pr = parseMaybeJson(refsIn)
  if (!pr.ok) return bad('args.references is a string that looks like JSON but does not parse: ' + pr.error)
  refsIn = pr.value
}
if (isStr(refsIn)) refsIn = [refsIn]
if (refsIn !== undefined && refsIn !== null && refsIn !== '' && !Array.isArray(refsIn)) return bad('args.references must be an array of paths or URLs')
let REFS = []
{
  const seen = new Set()
  for (const r of Array.isArray(refsIn) ? refsIn : []) {
    if (!isStr(r)) { note('references: dropped a non-string entry'); continue }
    const t = r.trim()
    if (/^data:/i.test(t)) { note('references: dropped an inline data URI (pass a path or URL)'); continue }
    if (seen.has(t)) continue
    seen.add(t)
    REFS.push(t)
  }
}
if (MODE === 'generate' && SOURCE) {
  note(`mode "generate" with a source: ${SOURCE} is used as a reference image, not edited`)
  if (!REFS.includes(SOURCE)) REFS.unshift(SOURCE)
  SOURCE = ''
}
if (REFS.length > MAX_REFERENCES) {
  note(`references capped at ${MAX_REFERENCES}; dropped ${REFS.slice(MAX_REFERENCES).join(', ')}`)
  REFS = REFS.slice(0, MAX_REFERENCES)
}
const SRC_TYPE = srcType(SOURCE)
if (KIND === 'image' && SRC_TYPE === 'svg') return bad('source is an SVG: use kind "vector" to edit it, or render it to PNG first (svg_render) and pass that PNG as source')

let outIn = A.output
if (typeof outIn === 'string') {
  const po = parseMaybeJson(outIn)
  if (!po.ok || typeof po.value === 'string') return bad('args.output must be an object {layered?: bool, pdf?: bool}')
  outIn = po.value
}
if (outIn !== undefined && outIn !== null && (typeof outIn !== 'object' || Array.isArray(outIn))) return bad('args.output must be an object {layered?: bool, pdf?: bool}')
const OUT = { layered: false, pdf: false }
for (const k of Object.keys(outIn || {})) {
  if (k !== 'layered' && k !== 'pdf') { note(`output.${k} is not a known option (layered, pdf); ignored`); continue }
  const v = outIn[k]
  OUT[k] = v === true || v === 'true' || v === 1
}

const thrRaw = A.threshold === undefined || A.threshold === null || A.threshold === '' ? DEFAULT_THRESHOLD : toNum(A.threshold)
if (thrRaw === null) return bad('args.threshold must be a number between 1 and 10 (default 8)')
const THRESHOLD = Math.max(1, Math.min(10, thrRaw))
if (THRESHOLD !== thrRaw) note(`threshold ${thrRaw} clamped to ${THRESHOLD} (allowed 1-10)`)

const mrRaw = A.maxRounds === undefined || A.maxRounds === null || A.maxRounds === '' ? DEFAULT_ROUNDS : toNum(A.maxRounds)
if (mrRaw === null) return bad('args.maxRounds must be an integer between 1 and ' + MAX_ROUNDS_CAP + ' (default 4)')
const MAX_ROUNDS = Math.max(1, Math.min(MAX_ROUNDS_CAP, Math.round(mrRaw)))
if (MAX_ROUNDS !== mrRaw) note(`maxRounds ${mrRaw} set to ${MAX_ROUNDS} (allowed integers 1-${MAX_ROUNDS_CAP})`)

const PRODUCER = PRODUCERS[KIND + ':' + MODE]
const TAG = isStr(A.runTag) ? '-' + slugify(A.runTag, 24) : ''
const SLUG = slugify(BRIEF, 40) + TAG
const RUN_DIR = '.stack/out/visual-iterate/' + SLUG
const IMG_DIR = '.stack/images/visual-iterate/' + SLUG
if (!TAG) note(`outputs go to ${IMG_DIR} and reviews to ${RUN_DIR}; pass runTag to keep separate runs of the same brief apart`)

// Operations the job needs at minimum (used to name env vars when a blocked producer names none).
function requiredOps() {
  if (KIND === 'image') return MODE === 'generate' ? [REFS.length ? 'REF' : 'GEN'] : ['EDIT']
  if (MODE === 'generate') return ['VECTOR']
  return SRC_TYPE === 'svg' ? [] : ['TRACE']
}
const REQUIRED_OPS = requiredOps()
const HAS_REFERENCE = REFS.length > 0 || !!SOURCE   // then `references` is never N/A
function fallbackProfile() { return KIND === 'image' && MODE === 'edit' ? 'edit' : 'default' }
function weightsFor(profile) {
  const base = PROFILES[profile] || PROFILES[fallbackProfile()]
  const w = {}
  for (const c of CRITERIA) w[c] = base[c] === undefined ? null : base[c]
  if (OUT.layered && w.technical !== null) w.technical += LAYERED_TECHNICAL_BONUS
  return w
}
function fmtWeights(w) { return CRITERIA.map(c => c + ' ' + (w[c] === null ? 'n/a' : w[c])).join(', ') }
let PROFILE = null   // fixed by the first successful review; later rounds reuse it unchanged
log(`visual-iterate: kind ${KIND}, mode ${MODE}, producer ${PRODUCER}, threshold ${THRESHOLD}, maxRounds ${MAX_ROUNDS}` +
  (SOURCE ? `, source ${SOURCE} (${SRC_TYPE})` : '') + (REFS.length ? `, ${REFS.length} reference(s)` : '') +
  (OUT.layered || OUT.pdf ? `, export ${[OUT.layered ? 'layered SVG' : '', OUT.pdf ? (OUT.layered ? 'layered PDF' : 'PDF') : ''].filter(Boolean).join(' + ')}` : ''))

// ---------------------------------------------------------------------------- schemas
const SCORE = { type: ['number', 'null'], minimum: 0, maximum: 10, description: 'integer 0-10 from the visual-review anchors after caps; null only when the criterion is not applicable' }
const PRODUCE_SCHEMA = {
  type: 'object',
  properties: {
    status: { type: 'string', enum: ['ok', 'blocked', 'failed'], description: 'ok: candidates written; blocked: an operation you need is not configured (fill missing_env); failed: the operation ran but produced nothing usable' },
    outputs: { type: 'array', items: { type: 'string' }, description: 'paths of this round\'s candidate files (PNG/JPEG/WebP/SVG), your pick first; no sidecar JSON' },
    primary: { type: 'string', description: 'path of your own pick among outputs' },
    ops_used: { type: 'array', items: { type: 'string' }, description: 'operations used, e.g. GEN, EDIT, SEGMENT, or CLAUDE_SVG_EDIT for hand edits of SVG text' },
    approach: { type: 'string', description: '<= 3 sentences: what you did and what changed versus the previous best' },
    missing_env: { type: 'array', items: { type: 'string' }, description: 'when blocked: exact env names to set, e.g. IMAGE_EDIT_URL, IMAGE_EDIT_KEY, IMAGE_EDIT_MODEL' },
    notes: { type: 'string', description: '<= 3 sentences: caveats (approximated ops, fidelity notes from the tools)' },
  },
  required: ['status', 'outputs', 'primary'],
}
const REVIEW_SCHEMA = {
  type: 'object',
  properties: {
    scores: {
      type: 'object',
      properties: { fidelity: SCORE, composition: SCORE, typography: SCORE, colour: SCORE, artefacts: SCORE, technical: SCORE, references: SCORE },
      required: CRITERIA.slice(),
      description: '0-10 per criterion for the best candidate of this round (visual-review keys; null = N/A)',
    },
    profile: { type: 'string', enum: PROFILE_NAMES.slice(), description: 'visual-review weight profile; round 1 picks it from the deliverable, later rounds repeat the one given in the brief' },
    overall: { type: 'number', minimum: 0, maximum: 10, description: 'weighted mean of the applicable criteria with the profile weights, from the aggregation snippet' },
    pass: { type: 'boolean', description: 'true only when overall >= threshold, no applicable criterion < 6 and no blocker' },
    verdict: { type: 'string', enum: ['PASS', 'REVISE', 'STOP'], description: 'visual-review stop rules (section 9), evaluated in order' },
    revisions: { type: 'array', items: { type: 'string' }, description: 'one line each, blocking first: R1 [blocking|major|minor] <owner>/<tool> (IMAGE_<OP>): <exact instruction> | region <box or element id> | mask grow G feather F | keep <...> | verify <check>' },
    best_path: { type: 'string', description: 'the candidate path these scores belong to (one of the listed candidates)' },
    not_applicable: { type: 'array', items: { type: 'string', enum: CRITERIA.slice() }, description: 'criteria scored null: typography when no text is requested or present, references when there is no reference and no source, plus the N/A criteria of the profile' },
    blockers: { type: 'array', items: { type: 'string' }, description: 'hard-gate (cap) failures that forbid a pass whatever the overall (wrong size, missing alpha, invalid SVG, misspelled required text, pixels changed outside the mask)' },
    keep: { type: 'array', items: { type: 'string' }, description: 'KEEP list: what scored >= 8 and must not regress' },
    report: { type: 'string', description: 'path of the review report .md you wrote' },
    summary: { type: 'string', description: '<= 2 sentences' },
  },
  required: ['scores', 'profile', 'overall', 'pass', 'verdict', 'revisions', 'best_path'],
}
const EXPORT_SCHEMA = {
  type: 'object',
  properties: {
    status: { type: 'string', enum: ['ok', 'blocked', 'failed'] },
    layered_svg: { type: 'string', description: 'path of the layered SVG, empty when not requested or not produced' },
    pdf: { type: 'string', description: 'path of the PDF, empty when not requested or not produced' },
    layers: { type: 'array', items: { type: 'string' }, description: 'layer labels in z-order, bottom first (as svg_layers / export_pdf report them)' },
    missing_env: { type: 'array', items: { type: 'string' } },
    notes: { type: 'string', description: '<= 3 sentences' },
  },
  required: ['status'],
}

// ---------------------------------------------------------------------------- prompt blocks
const OP_LINE = Object.keys(OP_TOOLS).map(op => op + ' -> ' + OP_TOOLS[op]).join(' | ')
const SERVER_RULES = [
  'IMAGE SERVER RULES (MCP server "image"; tool ids mcp__image__<tool>):',
  '1. Call mcp__image__image_ops_status first. It lists every operation, whether its tool is exposed, its adapter, URL host and model tag, and the exact env names it is missing. Operations and their tools: ' + OP_LINE + '. Local tools, always present: ' + LOCAL_TOOLS.join(', ') + '.',
  '2. Use only operations it reports as configured. If one you need is missing, stop and return status "blocked" with missing_env listing the exact IMAGE_<OP>_URL / IMAGE_<OP>_KEY / IMAGE_<OP>_MODEL names (TRACE and UPSCALE may instead set IMAGE_<OP>_API=local). There are no fallbacks: never call another provider, an HTTP API, a CLI generator or a different MCP server in its place. Switching to another configured operation of this server is fine when it serves the brief equally well.',
  '3. Vector manipulation is done by you, editing the SVG text with Read/Edit (copy the file into your output directory first), unless image_ops_status shows svg_transform exposed and the change is a wholesale restyle. Check every edited SVG with mcp__image__svg_inspect and look at mcp__image__svg_render output with Read.',
  '4. Never read, print or echo ~/.claude/stack.env or any key; the server handles credentials.',
].join('\n')

function taskText() {
  if (KIND === 'image' && MODE === 'generate') {
    return 'Generate a new raster image that satisfies the brief. Operations: GEN (image_generate); REF (image_generate_with_references) when references are given; TRANSPARENT (image_generate_transparent) when the brief needs a transparent background. From round 2 choose the route that applies the revision instructions best: regenerate with a revised prompt (keep the seed when only details change), or fix the previous best locally with EDIT (image_edit, with a mask from SEGMENT image_segment for regional fixes) when those operations are configured.'
  }
  if (KIND === 'image') {
    return 'Edit the source image so it satisfies the brief while everything the brief does not mention stays unchanged. Operations: EDIT (image_edit; pass a mask for regional changes so unmasked pixels are preserved), SEGMENT (image_segment) to make masks, BG_REMOVAL (image_remove_background) for cutouts, UPSCALE (image_upscale) last. Never modify the source file. From round 2 apply local fixes to the previous best; restart from the original source when the reviewer says the edit approach itself was wrong (repeated edits accumulate artefacts).'
  }
  if (MODE === 'generate') {
    return 'Generate an SVG that satisfies the brief with VECTOR (vector_generate). From round 2 fix the previous best by editing its SVG text yourself (Claude is the default vector manipulator; svg_transform only when exposed); regenerate with vector_generate only when the reviewer asks for a different composition. Finish each candidate with svg_optimize (keep ids that name logical parts).'
  }
  if (SRC_TYPE === 'svg') {
    return 'Modify the source SVG so it satisfies the brief by editing its text yourself (copy it into the round directory first; never modify the source). No generation operation is needed; svg_transform only when exposed and the change is a wholesale restyle. Finish with svg_inspect, svg_render and svg_optimize.'
  }
  const trace = 'Trace the source raster into SVG with TRACE (image_vectorize), then clean the SVG by editing its text (palette reduction, node count, ids, viewBox) and svg_optimize. Never modify the source.'
  return SRC_TYPE === 'raster' ? trace : 'Inspect the source first (image_info or svg_inspect). If it is an SVG, modify it by editing its text yourself (copy first; svg_transform only when exposed). If it is a raster: ' + trace
}
function layeredHint() {
  if (!OUT.layered && !OUT.pdf) return ''
  const want = [OUT.layered ? 'a layered SVG' : '', OUT.pdf ? (OUT.layered ? 'a layered PDF' : 'a PDF') : ''].filter(Boolean).join(' and ')
  return KIND === 'vector'
    ? `DELIVERABLE NOTE: a final step turns the best attempt into ${want}. Keep the artwork layer-friendly: logical parts (background, main shapes, details, text) as top-level <g> groups with meaningful ids, no needless nesting.`
    : (MODE === 'edit'
      ? `DELIVERABLE NOTE: a final step turns the best attempt into ${want}. Keep region borders of your edits clean (no halos or soft seams) so subject and background can be split into layers cleanly.`
      : `DELIVERABLE NOTE: a final step turns the best attempt into ${want}. Prefer compositions with a clearly separable subject and background (clean edges, no subject cropped by the frame) so the layers can be split cleanly.`)
}
function fmtScores(s, na) {
  if (!s) return 'none'
  return CRITERIA.map(c => c + ' ' + (na && na.includes(c) ? 'n/a' : (typeof s[c] === 'number' ? s[c] : '?'))).join(', ')
}
function weakest(s, na) {
  if (!s) return []
  return CRITERIA.filter(c => !(na && na.includes(c)) && typeof s[c] === 'number' && s[c] < Math.max(MIN_CRITERION + 1, THRESHOLD))
    .sort((a, b) => s[a] - s[b] || CRITERIA.indexOf(a) - CRITERIA.indexOf(b)).slice(0, 3)
}

// ---------------------------------------------------------------------------- producer prompt
function producerPrompt(r, best, last) {
  const dir = `${IMG_DIR}/round-${r}`
  const L = []
  L.push(`You are the producer for round ${r} of at most ${MAX_ROUNDS} in the visual-iterate workflow (a saved workflow run by the main thread). The workflow reviews every round with visual-reviewer and keeps the best-scoring attempt, so: do NOT spawn visual-reviewer, do NOT run your own multi-round review loop, do NOT launch saved workflows. Make this round's attempt (1-3 candidates; the reviewer scores the best), check it once yourself, and return the schema.`)
  L.push('')
  L.push('BRIEF:\n' + BRIEF)
  L.push('')
  L.push(`KIND: ${KIND}. MODE: ${MODE}.`)
  L.push('TASK: ' + taskText())
  if (SOURCE) L.push(`SOURCE: ${SOURCE} (${SRC_TYPE}). Never modify it; work on copies.`)
  if (REFS.length) L.push('REFERENCES (match subject, style or palette as the brief says): ' + REFS.join(', '))
  L.push(`OUTPUT DIRECTORY: ${dir}/ (mkdir -p; pass it as output_dir to every mcp__image__* tool that writes files; write hand-edited SVG copies there too). Never overwrite files from earlier rounds or the source.`)
  const lh = layeredHint()
  if (lh) L.push(lh)
  if (best) {
    L.push('')
    L.push(`PREVIOUS BEST: ${best.path} (round ${best.round}, overall ${best.overall}/10 against threshold ${THRESHOLD}; scores ${fmtScores(best.scores, best.not_applicable)}).`)
    const wk = weakest(best.scores, best.not_applicable)
    if (wk.length) L.push('WEAKEST CRITERIA: ' + wk.map(c => `${c} ${best.scores[c]}`).join(', ') + '.')
    if (best.blockers.length) L.push('BLOCKERS TO REMOVE: ' + best.blockers.map(b => '\n- ' + b).join(''))
    if (best.revisions.length) L.push('REVISION INSTRUCTIONS FROM THE REVIEWER (apply every one; they are this round\'s acceptance criteria):' + best.revisions.map(x => '\n- ' + x).join(''))
    else L.push('The reviewer gave no revision instructions: raise the weakest criteria above without regressing the others.')
    if (best.review_file) L.push(`Full review: ${best.review_file}`)
  }
  if (last && best && last.round !== best.round) {
    L.push('')
    L.push(`LAST ATTEMPT DID NOT IMPROVE: round ${last.round}${last.path ? ' (' + last.path + ')' : ''}${typeof last.overall === 'number' ? ', overall ' + last.overall : ''}. ` +
      (last.approach ? 'Its approach was: ' + last.approach + ' ' : '') + (last.summary ? 'Reviewer: ' + last.summary + ' ' : '') +
      'Do not repeat that approach; start again from the previous best above.')
  }
  L.push('')
  L.push(SERVER_RULES)
  L.push('')
  L.push('CHECK BEFORE RETURNING: look at every candidate (Read the PNG; for SVG mcp__image__svg_render then Read the PNG, plus mcp__image__svg_inspect) and confirm size or aspect ratio, transparency when asked, legible required text, no obvious artefacts. Drop candidates that clearly fail; return at most 3.')
  L.push('RETURN the schema: status, outputs (candidate paths, your pick first, image or SVG files only, no sidecars), primary (your pick), ops_used, approach (<= 3 sentences, what changed versus the previous best), missing_env (only when blocked), notes (<= 3 sentences). Keep fields short; the files on disk are the deliverable.')
  return L.join('\n')
}

// ---------------------------------------------------------------------------- reviewer prompt
const RUBRIC = [
  'fidelity: subject, count, action, setting, style, framing, required and excluded elements of the brief; edit mode: the instruction executed inside the region.',
  'composition: focal point, hierarchy, balance, crop, copy-safe areas as the brief asks.',
  'typography: required strings exact letter by letter, legible at target size, well set; N/A when no text is requested and none is required (stray glyphs count under artefacts).',
  'colour: palette against the brief or brand hex (delta-E), harmony, casts, WCAG contrast (4.5:1 text, 3:1 large text and needed graphics).',
  'artefacts: anatomy, garbled text, seams, duplicates, halos, fringes, mask edges, banding, jaggies, hairline gaps, tracing noise.',
  'technical: format, size or aspect (2% tolerance), alpha when asked, SVG validity and safety, viewBox, node count and palette budget, layers when layered output is wanted.',
  'references: identity, product and style of the references; edits, cutouts and upscales: faithful to the source with pixels outside the mask unchanged; N/A only when there is no reference and no source.',
].map(s => '- ' + s).join('\n')
const PROFILE_TABLE = PROFILE_NAMES.map(n => '  ' + n + ': ' + fmtWeights(PROFILES[n])).join('\n')

function reviewerPrompt(r, cands, prod, best, prevJsons) {
  const stem = `${RUN_DIR}/review-round-${r}`
  const file = stem + '.md'
  const L = []
  L.push(`You are the reviewer for round ${r} of at most ${MAX_ROUNDS} in the visual-iterate workflow (a saved workflow run by the main thread). Apply your visual-review skill exactly (anchors, caps, artefact checklists, revision grammar, stop rules). Judge, do not produce: never call a producing tool (image_generate, image_generate_with_references, image_edit, image_generate_transparent, image_segment, image_remove_background, image_upscale, vector_generate, image_vectorize, svg_transform, svg_layerize, layers_compose, export_pdf, svg_optimize, mask_convert) and never modify a candidate; use the local inspection tools, Read and Pillow snippets.`)
  L.push('')
  L.push('BRIEF:\n' + BRIEF)
  L.push('')
  L.push(`KIND: ${KIND}. MODE: ${MODE}.` + (SOURCE ? ` SOURCE: ${SOURCE} (edit mode: compare at the same scale; everything the brief does not ask to change must stay as in the source).` : ''))
  if (REFS.length) L.push('REFERENCES: ' + REFS.join(', '))
  if (OUT.layered || OUT.pdf) L.push(`DELIVERABLE: the best attempt will be exported as ${[OUT.layered ? 'a layered SVG' : '', OUT.pdf ? (OUT.layered ? 'a layered PDF' : 'a PDF') : ''].filter(Boolean).join(' and ')} afterwards; judge layer-friendliness under technical (separable subject, logical top-level groups for SVG).`)
  L.push('CANDIDATES OF THIS ROUND (score every candidate, report the best one in best_path and write revisions for it only):' + cands.map(c => '\n- ' + c).join(''))
  if (prod && prod.approach) L.push('PRODUCER SAYS: ' + prod.approach + (prod.notes ? ' ' + prod.notes : ''))
  if (best) L.push(`BEST SO FAR: ${best.path} (round ${best.round}), overall ${best.overall} (${fmtScores(best.scores, best.not_applicable)}). Score on the absolute anchors; if this round's best is better its overall must be higher, if worse it must be lower. Look at it again when in doubt.`)
  if (prevJsons.length) L.push('PREVIOUS REVIEW JSONS (ledger and strategy ladder; never repeat a revision that already failed): ' + prevJsons.join(', '))
  L.push('')
  L.push(`THRESHOLD ${THRESHOLD}; PASS = overall >= ${THRESHOLD} AND every applicable criterion >= ${MIN_CRITERION} AND no blocker.`)
  L.push('CRITERIA (visual-review keys):\n' + RUBRIC)
  if (PROFILE) {
    L.push(`PROFILE (fixed in round 1, reuse it unchanged): ${PROFILE}; weights ${fmtWeights(weightsFor(PROFILE))}.`)
  } else {
    L.push('PROFILE: pick the weight profile from the deliverable (not from the tool that made it) and return it in profile; the workflow fixes it for every later round. Weights (percent, n/a = criterion not applicable):\n' + PROFILE_TABLE +
      (OUT.layered ? `\n  The deliverable is layered: technical gets +${LAYERED_TECHNICAL_BONUS} on top of the profile weight.` : ''))
  }
  L.push('')
  L.push('PROCEDURE:')
  L.push(`1. Call mcp__image__image_ops_status so every revision is executable with exposed operations; when the best fix needs a missing operation, give the best feasible alternative and name its IMAGE_<OP>_URL / _KEY / _MODEL variables in the report (no other provider, no fallback model). Vector fixes are SVG text edits by the producer unless svg_transform is exposed.`)
  L.push(`2. Write the spec and weights from the brief before looking (${stem}/spec.json). Then for each candidate: raster -> mcp__image__image_info, Read the image, then Read zoom crops of every risk region; SVG -> mcp__image__svg_inspect, mcp__image__svg_render at the target sizes and Read the PNGs; layers -> mcp__image__svg_layers. Every render, crop and sheet goes under ${stem}/ (mkdir -p), never next to a candidate.`)
  L.push(`3. Score integers 0-10 with the anchors, then apply the caps; null for N/A criteria (list them in not_applicable). Compute overall and pass with the aggregation snippet, never mentally. Put every cap failure in blockers. Decide verdict with the stop rules in order (PASS, REVISE or STOP); the workflow itself enforces maxRounds and the plateau, so recommend STOP early only for the other reasons the rules name (budget, contradictory or unachievable brief with the exposed operations, the same blocking defect after two different strategies).`)
  L.push(`4. revisions: at most ${MAX_REVISIONS} one-line instructions in the skill's grammar, blocking first, at most 3 major: R1 [blocking|major|minor] <owner agent>/<tool> (IMAGE_<OP>): <exact instruction or prompt delta> | region <pixel box or element id> | mask grow G feather F | keep <...> | verify <check>. No praise, no vague advice. Empty only when pass is true. keep: what scored >= 8 and must not regress.`)
  L.push(`5. Write the report ${file} and its JSON ${stem}.json (visual-review section 10 format; these paths replace the default .stack/out/visual-reviewer/ ones) and return the schema with report = ${file}; summary <= 2 sentences.`)
  return { prompt: L.join('\n'), file, json: stem + '.json' }
}

// ---------------------------------------------------------------------------- normalisation
function matchPath(p, list) {
  if (!isStr(p)) return null
  const t = p.trim()
  if (list.includes(t)) return t
  const hit = list.find(x => x.endsWith('/' + t) || t.endsWith('/' + x) || x.endsWith(t) || t.endsWith(x))
  return hit || null
}
function normProduce(v, r) {
  if (!v || typeof v !== 'object') return { status: 'failed', outputs: [], primary: '', ops_used: [], approach: '', missing_env: [], notes: 'producer returned nothing' }
  const status = ['ok', 'blocked', 'failed'].includes(v.status) ? v.status : 'failed'
  let outputs = strList(v.outputs, 32, 1000).filter(p => !SIDECAR_EXT.test(p))
  const primary = matchPath(v.primary, outputs) || (outputs[0] || '')
  if (primary) outputs = [primary].concat(outputs.filter(p => p !== primary))
  if (outputs.length > MAX_CANDIDATES) {
    note(`round ${r}: ${outputs.length} candidates returned; only the first ${MAX_CANDIDATES} are reviewed (dropped ${outputs.slice(MAX_CANDIDATES).join(', ')})`)
    outputs = outputs.slice(0, MAX_CANDIDATES)
  }
  return {
    status, outputs, primary,
    ops_used: strList(v.ops_used, 10, 40),
    approach: oneLine(v.approach, 600),
    missing_env: strList(v.missing_env, 30, 60).filter(e => ENV_RE.test(e)),
    notes: oneLine(v.notes, 600),
  }
}
function normReview(v, cands, prod, r) {
  if (!v || typeof v !== 'object') return null
  let profile = PROFILE
  if (!profile) {
    profile = PROFILE_NAMES.includes(v.profile) ? v.profile : fallbackProfile()
    if (v.profile !== profile) note(`round ${r}: reviewer profile ${JSON.stringify(v.profile === undefined ? null : v.profile)} is not a visual-review profile; using ${profile}`)
  } else if (isStr(v.profile) && v.profile !== profile) {
    note(`round ${r}: reviewer used profile ${oneLine(v.profile, 40)}; the round-1 profile ${profile} is kept (weights never change between rounds)`)
  }
  const w = weightsFor(profile)
  const naIn = new Set(Array.isArray(v.not_applicable) ? v.not_applicable.filter(isStr) : [])
  const scores = {}
  const na = []
  const missing = []
  let wsum = 0, acc = 0, min = null
  for (const c of CRITERIA) {
    const raw = v.scores && typeof v.scores === 'object' ? toNum(v.scores[c]) : null
    const s = raw === null ? null : round2(Math.max(0, Math.min(10, raw)))
    scores[c] = s
    const optional = OPTIONAL_CRITERIA.includes(c) && (c !== 'references' || !HAS_REFERENCE)
    if (w[c] === null || (optional && (naIn.has(c) || s === null))) { na.push(c); continue }
    if (s === null) { missing.push(c); continue }
    wsum += w[c]
    acc += w[c] * s
    min = min === null ? s : Math.min(min, s)
  }
  const ignoredNa = Array.from(naIn).filter(c => !na.includes(c))
  if (ignoredNa.length) note(`round ${r}: not_applicable ${ignoredNa.join(', ')} ignored (profile ${profile}${HAS_REFERENCE ? '; a reference or source is given, so references is scored' : ''})`)
  const reported = toNum(v.overall)
  let overall = wsum > 0 ? round2(acc / wsum) : (reported === null ? null : round2(Math.max(0, Math.min(10, reported))))
  if (overall === null) { note(`round ${r}: review has neither criterion scores nor an overall; treated as failed`); return null }
  if (missing.length) note(`round ${r}: reviewer gave no score for ${missing.join(', ')}; a pass is impossible without them`)
  if (reported !== null && wsum > 0 && Math.abs(reported - overall) > 0.05) note(`round ${r}: reviewer overall ${round2(reported)} differs from the ${profile} weights (${overall}); the recomputed value is used`)
  const blockers = strList(v.blockers, 10, 300)
  const revisions = strList(v.revisions, MAX_REVISIONS, 500)
  const verdict = ['PASS', 'REVISE', 'STOP'].includes(v.verdict) ? v.verdict : (v.pass === true ? 'PASS' : 'REVISE')
  const rubricPass = overall >= THRESHOLD && !missing.length && min !== null && min >= MIN_CRITERION && !blockers.length
  const reviewerPass = v.pass === true && verdict === 'PASS'
  if (rubricPass && !reviewerPass) note(`round ${r}: scores meet the rubric but the reviewer did not pass it (pass ${v.pass === true}, verdict ${verdict}); not passed`)
  if (!rubricPass && reviewerPass) note(`round ${r}: reviewer passed it but the rubric (overall >= ${THRESHOLD}, every applicable criterion >= ${MIN_CRITERION}, no blocker) does not; not passed`)
  let path = matchPath(v.best_path, cands)
  if (!path) {
    path = prod.primary || cands[0]
    if (isStr(v.best_path)) note(`round ${r}: reviewer best_path "${oneLine(v.best_path, 120)}" is not one of the candidates; using the producer's pick ${path}`)
  }
  return {
    path, profile, scores, not_applicable: na, overall, pass: rubricPass && reviewerPass, reviewer_pass: reviewerPass, verdict,
    reported_overall: reported === null ? null : round2(reported), min_score: min, missing,
    revisions, blocking: revisions.filter(x => /\[blocking\]/i.test(x)).length, blockers,
    keep: strList(v.keep, 10, 200), report: isStr(v.report) ? oneLine(v.report, 300) : '', summary: oneLine(v.summary, 400),
  }
}
// visual-review "best so far": PASS first, then rounds with no criterion < 6, then the highest
// overall, then fewer blocking revisions; a full tie goes to the later round.
function rankKey(x) {
  return [x.pass ? 1 : 0, (x.min_score !== null && x.min_score >= MIN_CRITERION && !x.missing.length) ? 1 : 0, x.overall, -x.blocking]
}
function beats(a, b) {
  if (!b) return true
  const ka = rankKey(a), kb = rankKey(b)
  for (let i = 0; i < ka.length; i++) if (ka[i] !== kb[i]) return ka[i] > kb[i]
  return true
}

// ---------------------------------------------------------------------------- loop
const history = []
const produced = []
const reviews = []
const reviewJsons = []
let best = null
let last = null
let stall = 0
let roundsRun = 0
let blocked = null
let stopReason = 'max-rounds'

for (let r = 1; r <= MAX_ROUNDS; r++) {
  if (lowBudget(ROUND_MIN_BUDGET)) { stopReason = 'budget'; note(`token budget below ${ROUND_MIN_BUDGET}; no round ${r} started`); break }
  roundsRun = r
  phase('Produce')
  const raw = await call(producerPrompt(r, best, last), { label: `produce:r${r}`, phase: 'Produce', agentType: PRODUCER, schema: PRODUCE_SCHEMA })
  const p = normProduce(raw, r)
  const h = { round: r, producer: PRODUCER, status: p.status, outputs: p.outputs, primary: p.primary, ops_used: p.ops_used, approach: p.approach, notes: p.notes }
  history.push(h)

  if (p.status === 'blocked') {
    const env = p.missing_env.length ? p.missing_env : [].concat(...REQUIRED_OPS.map(envNames))
    blocked = { round: r, phase: 'Produce', missing_env: env, notes: p.notes }
    stopReason = 'blocked'
    note(`round ${r}: ${PRODUCER} is blocked by an unconfigured operation` + (env.length ? ` (set ${env.join(', ')})` : '') + '; stopping (no fallbacks)')
    break
  }
  if (p.status !== 'ok' || !p.outputs.length) {
    h.improved = false
    stall++
    note(`round ${r}: producer ${p.status === 'ok' ? 'returned no candidate paths' : 'failed'}${p.notes ? ' (' + oneLine(p.notes, 160) + ')' : ''}; counts as a non-improving round (${stall}/${STALL_LIMIT})`)
    last = { round: r, path: '', overall: null, approach: p.approach, summary: p.notes }
    if (stall >= STALL_LIMIT) { stopReason = 'no-improvement'; break }
    continue
  }
  for (const o of p.outputs) if (!produced.includes(o)) produced.push(o)

  phase('Review')
  const rp = reviewerPrompt(r, p.outputs, p, best, reviewJsons.slice())
  const rv = normReview(await call(rp.prompt, { label: `review:r${r}`, phase: 'Review', agentType: 'visual-reviewer', schema: REVIEW_SCHEMA }), p.outputs, p, r)
  if (!rv) {
    h.improved = false
    h.review = 'failed'
    stall++
    note(`round ${r}: review failed; counts as a non-improving round (${stall}/${STALL_LIMIT})`)
    last = { round: r, path: p.primary, overall: null, approach: p.approach, summary: '' }
    if (stall >= STALL_LIMIT) { stopReason = 'no-improvement'; break }
    continue
  }
  if (!PROFILE) { PROFILE = rv.profile; log(`weight profile fixed for this run: ${PROFILE} (${fmtWeights(weightsFor(PROFILE))})`) }
  reviews.push(rp.file)
  reviewJsons.push(rp.json)
  const prev = best
  const cand = { round: r, path: rv.path, overall: rv.overall, scores: rv.scores, not_applicable: rv.not_applicable, pass: rv.pass, min_score: rv.min_score, missing: rv.missing, blocking: rv.blocking, blockers: rv.blockers, revisions: rv.revisions, keep: rv.keep, verdict: rv.verdict, summary: rv.summary, review_file: rp.file, review_json: rp.json, approach: p.approach }
  const better = beats(cand, prev)
  const improved = !prev || (rv.pass && !prev.pass) || rv.overall >= prev.overall + MIN_GAIN
  Object.assign(h, {
    reviewed_path: rv.path, profile: rv.profile, scores: rv.scores, not_applicable: rv.not_applicable, overall: rv.overall,
    reported_overall: rv.reported_overall, pass: rv.pass, reviewer_pass: rv.reviewer_pass, verdict: rv.verdict, blockers: rv.blockers,
    revisions: rv.revisions, keep: rv.keep, summary: rv.summary, review_file: rp.file, review_json: rp.json, improved, new_best: better,
  })
  if (better) best = cand
  last = { round: r, path: rv.path, overall: rv.overall, approach: p.approach, summary: rv.summary }
  if (improved) stall = 0
  else {
    stall++
    note(`round ${r}: overall ${rv.overall} did not raise the best (${prev.overall}, round ${prev.round}) by ${MIN_GAIN}` + (better ? '; still the best attempt by the best-so-far rule' : '') + `; non-improving round ${stall}/${STALL_LIMIT}`)
  }
  log(`round ${r}: ${rv.path} overall ${rv.overall} verdict ${rv.verdict}${rv.pass ? ', passed' : ''}; best so far round ${best.round} (${best.overall})`)
  if (rv.pass) { stopReason = 'pass'; break }
  if (rv.verdict === 'STOP' && r < MAX_ROUNDS) { stopReason = 'reviewer-stop'; note(`round ${r}: visual-reviewer recommends STOP` + (rv.summary ? ` (${oneLine(rv.summary, 200)})` : '') + '; delivering the best attempt'); break }
  if (stall >= STALL_LIMIT) { stopReason = 'no-improvement'; break }
}

// ---------------------------------------------------------------------------- export
let exported = null
// Raster layer splits (cutouts, masks) are image-editor work; SVG layering and PDF export stay with the producer.
const BEST_IS_SVG = !!best && (SVG_EXT.test(best.path) || (KIND === 'vector' && !RASTER_EXT.test(best.path)))
const EXPORTER = best && !BEST_IS_SVG && OUT.layered ? 'image-editor' : PRODUCER
if ((OUT.layered || OUT.pdf) && best && !blocked) {
  if (lowBudget(EXPORT_MIN_BUDGET)) note(`token budget below ${EXPORT_MIN_BUDGET}; layered/PDF export skipped (run the ${EXPORTER} agent on ${best.path} later)`)
  else {
    phase('Export')
    const dir = `${IMG_DIR}/final`
    const isSvg = BEST_IS_SVG
    const L = []
    L.push(`You are finishing the visual-iterate workflow (a saved workflow run by the main thread): export its best attempt as editable deliverables without changing how it looks. Do not spawn agents, do not launch saved workflows, do not regenerate or restyle the artwork.`)
    L.push('')
    L.push(`BEST ATTEMPT: ${best.path} (round ${best.round}, overall ${best.overall}/10, ${best.pass ? 'passed' : 'did not reach'} threshold ${THRESHOLD}).`)
    L.push('BRIEF (for layer names and structure):\n' + BRIEF)
    L.push(`OUTPUT DIRECTORY: ${dir}/ (mkdir -p; never overwrite the best attempt).`)
    L.push('')
    if (OUT.layered) {
      L.push(isSvg
        ? `LAYERED SVG: mcp__image__svg_layerize(svg_path=${best.path}, by="${MODE === 'edit' && SRC_TYPE !== 'svg' ? 'color' : 'group'}" (use "mapping" with meaningful layer names when the brief names parts or layers), output_path=${dir}/<name>-layered.svg). Then mcp__image__svg_layers must list meaningful labels in a sensible z-order, and mcp__image__svg_render of the layered file must look identical to the best attempt (Read both renders).`
        : `LAYERED SVG: split the raster into layers that make sense for the brief (for example a subject cutout with image_remove_background [BG_REMOVAL] or masks with image_segment [SEGMENT], plus the complete best attempt as the bottom layer) and assemble them with mcp__image__layers_compose at the image's pixel size (one named layer per source, raster sources embedded), output_path=${dir}/<name>-layered.svg. Check with mcp__image__svg_layers and compare mcp__image__svg_render with the best attempt.`)
    }
    if (OUT.pdf) {
      L.push(OUT.layered
        ? `LAYERED PDF: mcp__image__export_pdf(svg_path=<the layered SVG>, layered=true, output_path=${dir}/<name>.pdf); every top-level layer must appear as an Optional Content Group: report the layer names the tool returns.`
        : (isSvg
          ? `PDF: mcp__image__export_pdf(svg_path=${best.path}, layered=false, output_path=${dir}/<name>.pdf).`
          : `PDF: wrap the raster in a one-layer SVG with mcp__image__layers_compose (its pixel size), then mcp__image__export_pdf(svg_path=<that SVG>, layered=false, output_path=${dir}/<name>.pdf).`))
    }
    L.push('')
    L.push(SERVER_RULES)
    L.push('')
    L.push('RETURN the schema: status, layered_svg and pdf paths (empty when not requested or not produced), layers (labels bottom first), missing_env (only when blocked), notes (<= 3 sentences).')
    const ev = await call(L.join('\n'), { label: 'export', phase: 'Export', agentType: EXPORTER, schema: EXPORT_SCHEMA })
    if (!ev || typeof ev !== 'object') {
      exported = { status: 'failed', layered_svg: '', pdf: '', layers: [], missing_env: [], notes: 'export agent returned nothing' }
      note(`export failed: ${EXPORTER} returned nothing`)
    } else {
      exported = {
        status: ['ok', 'blocked', 'failed'].includes(ev.status) ? ev.status : 'failed',
        layered_svg: OUT.layered && isStr(ev.layered_svg) ? ev.layered_svg.trim() : '',
        pdf: OUT.pdf && isStr(ev.pdf) ? ev.pdf.trim() : '',
        layers: strList(ev.layers, 64, 120),
        missing_env: strList(ev.missing_env, 30, 60).filter(e => ENV_RE.test(e)),
        notes: oneLine(ev.notes, 600),
      }
      if (exported.status === 'blocked' && !exported.missing_env.length && !isSvg && OUT.layered) exported.missing_env = envNames('BG_REMOVAL').concat(envNames('SEGMENT'))
      if (exported.status !== 'ok') note(`export ${exported.status}` + (exported.missing_env.length ? ` (set ${exported.missing_env.join(', ')})` : '') + (exported.notes ? ': ' + oneLine(exported.notes, 200) : ''))
      if (OUT.layered && exported.status === 'ok' && !exported.layered_svg) note('export reported ok but returned no layered SVG path')
      if (OUT.pdf && exported.status === 'ok' && !exported.pdf) note('export reported ok but returned no PDF path')
    }
  }
} else if (OUT.layered || OUT.pdf) {
  note('export skipped: ' + (blocked ? 'the run is blocked by an unconfigured operation' : 'no reviewed attempt to export'))
}

// ---------------------------------------------------------------------------- result
const openDoubts = []
if (blocked) {
  openDoubts.push(`The image operation this job needs is not configured. Set ${blocked.missing_env.length ? blocked.missing_env.join(', ') : 'the IMAGE_<OP>_URL / IMAGE_<OP>_KEY / IMAGE_<OP>_MODEL variables image_ops_status lists'} in ~/.claude/stack.env (template config/stack.env.example), reconnect the image server via /mcp, then re-run Workflow visual-iterate with the same args. No other provider was tried (no fallbacks).` +
    (best ? ` Best attempt before the block: ${best.path} (round ${best.round}, overall ${best.overall}, threshold ${THRESHOLD}).` : ''))
}
if (best && !best.pass && !blocked) {
  openDoubts.push(`Best attempt ${best.path} scored ${best.overall} (threshold ${THRESHOLD}) after ${roundsRun} round(s), stopped by ${stopReason}. Accept it, sharpen the brief (see ${best.review_file}), raise maxRounds, or lower threshold.`)
}
if (!best && !blocked) openDoubts.push(`No attempt was reviewed in ${roundsRun} round(s) (stopped by ${stopReason}); check the notes, the image server (image_ops_status) and the brief, then re-run.`)
if (exported && exported.status === 'blocked') {
  openDoubts.push(`The layered export needs an unconfigured operation: set ${exported.missing_env.length ? exported.missing_env.join(', ') : 'the variables image_ops_status lists'} in ~/.claude/stack.env, reconnect /mcp, and re-run the export with the ${EXPORTER} agent on ${best ? best.path : 'the best attempt'}.`)
}
log(`visual-iterate done: ${roundsRun} round(s), stop ${stopReason}, ` + (best ? `best ${best.path} overall ${best.overall}${best.pass ? ' (PASS)' : ''}` : 'no reviewed attempt'))

return {
  started: true,
  pass: !!(best && best.pass),
  rounds: roundsRun,
  stop_reason: stopReason,
  kind: KIND,
  mode: MODE,
  producer: PRODUCER,
  exporter: exported ? EXPORTER : null,
  threshold: THRESHOLD,
  max_rounds: MAX_ROUNDS,
  rubric: { profile: PROFILE, weights: weightsFor(PROFILE || fallbackProfile()), min_criterion: MIN_CRITERION, min_gain: MIN_GAIN, stall_limit: STALL_LIMIT },
  scores: best ? best.scores : null,
  trend: history.filter(x => typeof x.overall === 'number').map(x => ({ round: x.round, path: x.reviewed_path, overall: x.overall, verdict: x.verdict, pass: x.pass })),
  best: best ? {
    round: best.round, path: best.path, overall: best.overall, pass: best.pass, verdict: best.verdict, scores: best.scores,
    not_applicable: best.not_applicable, blockers: best.blockers, revisions: best.revisions, keep: best.keep, summary: best.summary,
    review_file: best.review_file, review_json: best.review_json,
  } : null,
  history,
  outputs: {
    best: best ? best.path : null,
    layered_svg: exported && exported.layered_svg ? exported.layered_svg : null,
    pdf: exported && exported.pdf ? exported.pdf : null,
    layers: exported ? exported.layers : [],
    export_status: exported ? exported.status : (OUT.layered || OUT.pdf ? 'skipped' : 'not-requested'),
    candidates: produced,
    reviews,
    review_jsons: reviewJsons,
    image_dir: IMG_DIR,
    run_dir: RUN_DIR,
  },
  blocked,
  open_doubts: openDoubts,
  notes,
}
